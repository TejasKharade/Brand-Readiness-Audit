import sys
import json
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

def fetch_content_length(url, timeout=3):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityAudit/1.0"}
    
    # Try HEAD request first
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl), None
    except urllib.error.HTTPError as e:
        # Fall back to GET if 405 Method Not Allowed or 403
        if e.code in [405, 403, 501]:
            try:
                req_get = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req_get, timeout=timeout) as resp_get:
                    cl = resp_get.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        return int(cl), None
                    # Fallback: measure actual read payload size if Content-Length header missing
                    body = resp_get.read(10 * 1024 * 1024)  # Read up to 10MB
                    return len(body), None
            except Exception as get_err:
                return None, f"GET fallback failed: {str(get_err)}"
        return None, f"HTTP Error {e.code}: {e.reason}"
    except Exception as head_err:
        # Fall back to GET on general head exception
        try:
            req_get = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req_get, timeout=timeout) as resp_get:
                cl = resp_get.headers.get("Content-Length")
                if cl and cl.isdigit():
                    return int(cl), None
                body = resp_get.read(10 * 1024 * 1024)
                return len(body), None
        except Exception as get_err:
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

    for res_url in measured_urls:
        length, err = fetch_content_length(res_url)
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
        "resource_fetch_errors": resource_fetch_errors
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

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
            "script_error": str(e)
        }))
