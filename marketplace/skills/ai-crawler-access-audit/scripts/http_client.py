"""
HTTP network client with redirect tracking, gzip decompression, and latency timing.
Pure Python standard library (urllib.request + gzip). Zero external dependencies.
"""

import time
import gzip
import urllib.request
import urllib.error

try:
    from .constants import BOT_UA, BROWSER_UA
except (ImportError, ValueError):
    from constants import BOT_UA, BROWSER_UA

class RedirectTracker(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_hops=10):
        super().__init__()
        self.history = []
        self.max_hops = max_hops
        self.loop_detected = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.history.append((req.full_url, code, newurl))
        visited = [h[0] for h in self.history]
        if newurl in visited or len(self.history) > self.max_hops:
            self.loop_detected = True
            return None
        # Handle HTTP 308 Permanent Redirect for Python <= 3.10
        if code == 308:
            newurl = newurl.replace(' ', '%20')
            content_headers = ("content-length", "content-type")
            newheaders = {k: v for k, v in req.headers.items() if k.lower() not in content_headers}
            return urllib.request.Request(
                newurl,
                headers=newheaders,
                origin_req_host=req.origin_req_host,
                unverifiable=True
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, code, msg, headers)

def make_request(url, ua=BOT_UA, timeout=12):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    tracker = RedirectTracker()
    opener = urllib.request.build_opener(tracker)
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            headers = {k.lower(): v for k, v in resp.getheaders()}
            if data.startswith(b"\x1f\x8b") or headers.get("content-encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            text = data.decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "headers": headers,
                "text": text,
                "elapsed_ms": elapsed_ms,
                "history": tracker.history,
                "final_url": resp.url,
                "loop_detected": tracker.loop_detected,
                "error": None
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        headers = {k.lower(): v for k, v in e.headers.items()} if hasattr(e, "headers") else {}
        return {
            "status": e.code,
            "headers": headers,
            "text": "",
            "elapsed_ms": elapsed_ms,
            "history": tracker.history,
            "final_url": getattr(e, "url", url),
            "loop_detected": tracker.loop_detected,
            "error": str(e)
        }
    except Exception as e:
        return {
            "status": 0,
            "headers": {},
            "text": "",
            "elapsed_ms": 0,
            "history": tracker.history,
            "final_url": url,
            "loop_detected": tracker.loop_detected,
            "error": str(e)
        }

def probe_origin_access(origin, logged_request, collector):
    """
    Probes origin URL with AI search bot User-Agent vs standard desktop browser.
    Evaluates:
    - User-Agent discrimination (OAI-SearchBot vs desktop browser)
    - Origin HTTP access status (401/403 forbidden, >=500 server error, 0 connection failure)
    - Redirect loops and long chains on origin
    - Host-level X-Robots-Tag noindex headers
    Returns (res_bot, res_browser, is_bot_blocked, sub_timeout).
    """
    res_bot = logged_request(origin, BOT_UA, timeout=12, purpose="Root URL (AI Search Bot)")
    res_browser = logged_request(origin, BROWSER_UA, timeout=12, purpose="Root URL (Desktop Browser)")
    
    collector.check_redirects(res_bot, origin)

    is_bot_blocked = False
    if res_bot["status"] in (401, 403) and res_browser["status"] == 200:
        is_bot_blocked = True
        collector.add(
            code="BOT_UA_DISCRIMINATION",
            title="AI Search Bot User-Agent discriminated against",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']} to OAI-SearchBot but HTTP 200 to desktop Chrome.",
            action_summary="Update firewall / CDN rules (Cloudflare, AWS WAF, Akamai) to allow verified AI search crawlers."
        )
    elif res_bot["status"] in (401, 403):
        is_bot_blocked = True
        collector.add(
            code="HTTP_ACCESS_FORBIDDEN",
            title=f"Root URL returns HTTP {res_bot['status']} Forbidden",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']} for both bot and browser.",
            action_summary="Ensure the website root responds with HTTP 200 to public GET requests."
        )
    elif res_bot["status"] >= 500:
        is_bot_blocked = True
        collector.add(
            code="ORIGIN_SERVER_ERROR",
            title=f"Root URL returns HTTP {res_bot['status']} Server Error",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']}.",
            action_summary="Resolve internal server errors on the origin web application."
        )
    elif res_bot["status"] == 0:
        collector.add(
            code="CONNECTION_FAILURE",
            title="Unable to connect to host",
            severity="critical",
            evidence=f"Request to {origin} failed with network error: {res_bot['error']}.",
            action_summary="Ensure the domain is reachable and SSL/TLS certificates are valid."
        )

    # When bot is already confirmed blackholed by WAF, fail fast on secondary probes
    sub_timeout = 3 if is_bot_blocked else 12

    # Host-Level Indexation Headers
    x_robots = res_bot.get("headers", {}).get("x-robots-tag", "").lower()
    if "noindex" in x_robots:
        collector.add(
            code="HOST_NOINDEX_HEADER",
            title="Host returns X-Robots-Tag: noindex header",
            severity="critical",
            evidence=f"Response headers on {origin} contain 'X-Robots-Tag: {x_robots}'.",
            action_summary="Crawlability Failure: Remove 'noindex' directive from HTTP headers on public pages."
        )

    return res_bot, res_browser, is_bot_blocked, sub_timeout
