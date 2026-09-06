import sys
import json
import urllib.parse
from html.parser import HTMLParser

def normalize_url(url_str):
    if not url_str or not isinstance(url_str, str):
        return ""
    s = url_str.strip()
    if not s or s.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    try:
        if "://" not in s:
            s = "https://" + s
        parsed = urllib.parse.urlparse(s)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip('/')
        return f"{netloc}{path}".lower()
    except Exception:
        return ""

class HomepageLinkParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.has_nav = False
        self.direct_links = []

    def handle_starttag(self, tag, attrs):
        try:
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
            role = attrs_dict.get("role", "").lower()
            
            if tag == "nav" or role == "navigation":
                self.has_nav = True

            if tag == "a":
                href = attrs_dict.get("href")
                if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    abs_url = urllib.parse.urljoin(self.base_url, href)
                    # Strip fragments
                    abs_url = urllib.parse.urlunparse(urllib.parse.urlparse(abs_url)._replace(fragment=""))
                    self.direct_links.append(abs_url)
        except Exception:
            pass

def check_navigation_reachability(params):
    homepage_html = params.get("homepage_html", "") or params.get("html", "")
    homepage_url = params.get("homepage_url", "") or params.get("url", "https://example.com")
    key_content_urls = params.get("key_content_urls", [])

    if not isinstance(key_content_urls, list):
        key_content_urls = []

    parser = HomepageLinkParser(homepage_url)
    try:
        if homepage_html:
            parser.feed(homepage_html)
    except Exception:
        pass

    direct_links_raw = parser.direct_links
    normalized_homepage_links = set(normalize_url(u) for u in direct_links_raw if normalize_url(u))

    reachability_results = []
    for key_url in key_content_urls:
        norm_key = normalize_url(key_url)
        is_linked = norm_key in normalized_homepage_links if norm_key else False
        reachability_results.append({
            "key_content_url": key_url,
            "directly_linked_from_homepage": is_linked
        })

    return {
        "homepage_url": homepage_url,
        "has_nav_element": parser.has_nav,
        "total_homepage_links": len(direct_links_raw),
        "key_content_reachability": reachability_results
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        result = check_navigation_reachability(params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "homepage_url": None,
            "has_nav_element": False,
            "total_homepage_links": 0,
            "key_content_reachability": [],
            "script_error": str(e)
        }))
