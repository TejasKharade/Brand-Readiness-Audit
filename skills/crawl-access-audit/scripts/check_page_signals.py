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
        s = str(url).strip()
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
            x_robots = ""
            if isinstance(headers, dict):
                for k, v in headers.items():
                    if k.lower() == "x-robots-tag":
                        x_robots = str(v)
                        break
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

import threading

def read_stdin_safe(timeout=0.2):
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
        url = ""
        headers = {}
        content = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    url = params.get("url", "")
                    headers = params.get("headers", {})
                    content = params.get("content", "")
                except json.JSONDecodeError:
                    url = raw_arg
            else:
                url = raw_arg

        input_data = read_stdin_safe(timeout=0.2)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not url:
            url = params.get("url", "")
        if not headers:
            headers = params.get("headers", {})
        if not content:
            content = params.get("content", "")

        result = check_signals(url, headers, content)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
