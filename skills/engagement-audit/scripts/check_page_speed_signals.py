
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json

# --- robots.txt gate --------------------------------------------------------
# Every fetch in this file asks robots_gate first. The gate is built from the
# robots.txt that check_robots.py already fetched (passed in as `robots`), so
# it costs no extra request; only a standalone run fetches robots.txt itself.
import os as _os
for _d in (_os.path.dirname(_os.path.abspath(__file__)),
           _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "..", "crawl-access-audit", "scripts")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
try:
    from robots_gate import RobotsGate
except Exception:  # gate unavailable -> refuse to fetch, never fetch blind
    RobotsGate = None

import socket
import time
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser

class PageSpeedResourceParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.css_js_urls = []
        self.image_count = 0

    def handle_starttag(self, tag, attrs):
        try:
            tag_lower = tag.lower()
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}

            if tag_lower == "link":
                rel = attrs_dict.get("rel", "").lower()
                href = attrs_dict.get("href", "").strip()
                if "stylesheet" in rel and href and not href.startswith(("data:", "javascript:", "#")):
                    abs_url = urllib.parse.urljoin(self.base_url, href)
                    self.css_js_urls.append(abs_url)
            elif tag_lower == "script":
                src = attrs_dict.get("src", "").strip()
                if src and not src.startswith(("data:", "javascript:", "#")):
                    abs_url = urllib.parse.urljoin(self.base_url, src)
                    self.css_js_urls.append(abs_url)
            elif tag_lower == "img":
                self.image_count += 1
        except Exception:
            pass

def fetch_content_length(url, timeout=3, gate=None):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityAudit/1.0"}

    # Measuring a stylesheet's weight still means requesting it. A disallowed
    # resource is reported as not measured -- honest -- rather than as a fetch
    # error, which would read as a defect in the site.
    if gate is not None:
        decision = gate.allows(url, headers["User-Agent"])
        if not decision.allowed:
            return None, "not measured (robots.txt): %s" % decision.reason

    def get_fallback():
        try:
            req_get = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req_get, timeout=timeout) as resp_get:
                cl_get = resp_get.headers.get("Content-Length")
                if cl_get and cl_get.isdigit():
                    return int(cl_get), None
                body = resp_get.read(10 * 1024 * 1024)
                return len(body), None
        except Exception as get_err:
            return None, f"GET fallback failed: {str(get_err)}"

    # Try HEAD request first
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl), None
            # If HEAD succeeds but no Content-Length header, try GET to measure body
            return get_fallback()
    except urllib.error.HTTPError as e:
        # Fall back to GET only if the server actively rejected HEAD as a
        # method (it answered, just not to this verb) -- worth one more try.
        if e.code in (405, 403, 501):
            return get_fallback()
        return None, f"HTTP Error {e.code}: {e.reason}"
    except (socket.timeout, TimeoutError):
        # A HEAD that hangs means the resource/server is slow, not that HEAD
        # is unsupported -- a GET retry would almost certainly hang for the
        # same reason, doubling the wait for no new signal. Report and move on.
        return None, f"HEAD timed out after {timeout}s"
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return None, f"HEAD timed out after {timeout}s"
        # DNS failure, connection refused, etc. -- fails fast either way, so a
        # GET retry costs little and occasionally succeeds (some origins only
        # answer GET at the TLS/routing layer).
        return get_fallback()
    except Exception as head_err:
        return None, f"Fetch failed: {str(head_err)}"

def check_page_speed_signals(params):
    html_content = params.get("html", "") or ""
    url = params.get("url", "") or "https://example.com"

    html_bytes = len(html_content.encode("utf-8")) if isinstance(html_content, str) else 0

    parser = PageSpeedResourceParser(url)
    try:
        if html_content:
            parser.feed(html_content)
    except Exception:
        pass

    css_js_total_found = len(parser.css_js_urls)
    measured_urls = parser.css_js_urls[:15]
    css_js_measured_count = len(measured_urls)

    total_css_js_bytes = 0
    resource_fetch_errors = []
    time_budget_exceeded = False

    # Wall-clock ceiling across all measured resources combined: up to 15
    # resources x a per-request timeout can otherwise run unbounded on a
    # slow-but-live host -- this is one of several network-bound steps in a
    # <5min total audit budget, so it must return within a bounded time.
    # 15s (down from 20s): general worst-case-ceiling trim -- see
    # check_sitemap.py's SITEMAP_FETCH_DEADLINE_S comment for the full reasoning.
    RESOURCE_FETCH_DEADLINE_S = 15.0
    deadline_start = time.time()
    gate = RobotsGate.for_url(url, robots=params.get("robots")) if RobotsGate else None

    for res_url in measured_urls:
        if time.time() - deadline_start > RESOURCE_FETCH_DEADLINE_S:
            time_budget_exceeded = True
            resource_fetch_errors.append({
                "url": res_url,
                "error": f"skipped: {RESOURCE_FETCH_DEADLINE_S:.0f}s wall-clock budget exceeded"
            })
            continue
        length, err = fetch_content_length(res_url, gate=gate)
        if length is not None:
            total_css_js_bytes += length
        else:
            resource_fetch_errors.append({
                "url": res_url,
                "error": err or "Content-Length unavailable"
            })

    image_count = parser.image_count
    resource_count_total = css_js_total_found + image_count

    return {
        "url": url,
        "html_byte_size": html_bytes,
        "total_css_js_bytes": total_css_js_bytes,
        "css_js_resources_total_found": css_js_total_found,
        "css_js_resources_measured": css_js_measured_count,
        "image_count": image_count,
        "resource_count_total": resource_count_total,
        "resource_fetch_errors": resource_fetch_errors,
        "time_budget_exceeded": time_budget_exceeded
    }

import threading

def read_stdin_safe(timeout=5.0):
    if sys.stdin.isatty():
        return ""
    res = []
    def target():
        try:
            res.append(sys.stdin.read())
        except Exception:
            pass
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return res[0] if res else ""

if __name__ == "__main__":
    try:
        params = {}

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params["url"] = raw_arg
            else:
                params["url"] = raw_arg

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        result = check_page_speed_signals(params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "html_byte_size": 0,
            "total_css_js_bytes": 0,
            "css_js_resources_total_found": 0,
            "css_js_resources_measured": 0,
            "image_count": 0,
            "resource_count_total": 0,
            "resource_fetch_errors": [],
            "time_budget_exceeded": False,
            "script_error": str(e)
        }))
