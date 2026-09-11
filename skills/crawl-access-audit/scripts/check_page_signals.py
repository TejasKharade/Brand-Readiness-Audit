
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import urllib.parse
from html.parser import HTMLParser

# Robots meta directives are also honoured on bot-specific meta names
# (<meta name="googlebot">, <meta name="gptbot">, ...), not just name="robots".
ROBOTS_META_NAMES = {
    "robots", "googlebot", "googlebot-news", "bingbot", "slurp",
    "gptbot", "claudebot", "perplexitybot", "google-extended", "applebot",
}


class MetaLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.noindex = False
        self.nofollow = False
        self.none_directive = False
        self.directives_seen = []
        self.canonical = None
        self.canonical_count = 0

    def handle_starttag(self, tag, attrs):
        try:
            t = tag.lower()
            attrs_dict = {k.lower(): (v or "") for k, v in attrs}
            if t == "meta":
                name = attrs_dict.get("name", "").lower().strip()
                if name in ROBOTS_META_NAMES:
                    content = attrs_dict.get("content", "").lower()
                    for part in [p.strip() for p in content.split(",")]:
                        if part and part not in self.directives_seen:
                            self.directives_seen.append(part)
                    if "noindex" in content:
                        self.noindex = True
                    if "nofollow" in content:
                        self.nofollow = True
                    # `content="none"` is shorthand for noindex, nofollow
                    if "none" in [p.strip() for p in content.split(",")]:
                        self.none_directive = True
                        self.noindex = True
                        self.nofollow = True
            elif t == "link":
                rels = attrs_dict.get("rel", "").lower().split()
                if "canonical" in rels:
                    self.canonical_count += 1
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
            
        # X-Robots-Tag header (may carry noindex and/or nofollow)
        noindex_header = False
        nofollow_header = False
        x_robots = ""
        try:
            if isinstance(headers, dict):
                for k, v in headers.items():
                    if k.lower() == "x-robots-tag":
                        x_robots = str(v)
                        break
            xr = x_robots.lower()
            if "noindex" in xr or "none" in [p.strip() for p in xr.split(",")]:
                noindex_header = True
            if "nofollow" in xr or "none" in [p.strip() for p in xr.split(",")]:
                nofollow_header = True
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

        is_noindex = bool(parser.noindex or noindex_header)
        is_nofollow = bool(parser.nofollow or nofollow_header)

        return {
            "url": url,
            "noindex_meta": parser.noindex,
            "noindex_header": noindex_header,
            "nofollow_meta": parser.nofollow,
            "nofollow_header": nofollow_header,
            # Rolled-up booleans consumed by the orchestrator (meta OR header).
            "is_noindex": is_noindex,
            "is_nofollow": is_nofollow,
            "robots_directives_seen": parser.directives_seen,
            "x_robots_tag": x_robots or None,
            "canonical_url": parser.canonical,
            "canonical_tag_count": parser.canonical_count,
            "duplicate_canonical_tags": parser.canonical_count > 1,
            "canonical_differs_from_self": canonical_differs
        }
    except Exception as e:
        return {
            "url": url,
            "noindex_meta": False,
            "noindex_header": False,
            "nofollow_meta": False,
            "nofollow_header": False,
            "is_noindex": False,
            "is_nofollow": False,
            "robots_directives_seen": [],
            "x_robots_tag": None,
            "canonical_url": None,
            "canonical_tag_count": 0,
            "duplicate_canonical_tags": False,
            "canonical_differs_from_self": False,
            "error": f"Signal check failed: {str(e)}"
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

        input_data = read_stdin_safe(timeout=5.0)
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
