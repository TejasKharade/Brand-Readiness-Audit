import sys
import json
import urllib.parse
from html.parser import HTMLParser

class MetaLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.noindex = False
        self.canonical = None
        
    def handle_starttag(self, tag, attrs):
        try:
            attrs_dict = dict(attrs)
            if tag == "meta":
                if attrs_dict.get("name", "").lower() == "robots":
                    if "noindex" in attrs_dict.get("content", "").lower():
                        self.noindex = True
            elif tag == "link":
                if attrs_dict.get("rel", "").lower() == "canonical":
                    self.canonical = attrs_dict.get("href")
        except Exception:
            pass

def normalize_url(url):
    try:
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip('/')
        return f"{parsed.netloc}{path}".lower()
    except Exception:
        return ""

def check_signals(url, headers, content):
    try:
        parser = MetaLinkParser()
        try:
            if content:
                parser.feed(content)
        except Exception:
            pass
            
        # Check headers
        noindex_header = False
        try:
            x_robots = headers.get("X-Robots-Tag", "")
            if x_robots and "noindex" in x_robots.lower():
                noindex_header = True
        except Exception:
            pass
            
        canonical_differs = False
        try:
            if parser.canonical:
                abs_canonical = urllib.parse.urljoin(url, parser.canonical)
                norm_canonical = normalize_url(abs_canonical)
                norm_url = normalize_url(url)
                if norm_canonical and norm_url:
                    canonical_differs = norm_canonical != norm_url
        except Exception:
            pass
            
        return {
            "noindex_meta": parser.noindex,
            "noindex_header": noindex_header,
            "canonical_url": parser.canonical,
            "canonical_differs_from_self": canonical_differs
        }
    except Exception as e:
        return {
            "noindex_meta": False,
            "noindex_header": False,
            "canonical_url": None,
            "canonical_differs_from_self": False,
            "error": f"Signal check failed: {str(e)}"
        }

if __name__ == "__main__":
    try:
        input_data = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        try:
            params = json.loads(input_data)
            if not params:
                print(json.dumps({"error": "Missing input data"}))
                sys.exit(0)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON input"}))
            sys.exit(0)
            
        url = params.get("url", "")
        headers = params.get("headers", {})
        content = params.get("content", "")
        
        result = check_signals(url, headers, content)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
