
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import time
import urllib.parse
import urllib.robotparser
import urllib.request
from html.parser import HTMLParser
from urllib.error import URLError, HTTPError
import socket

import math

# The exploration budget scales with site scale (URL count from the sitemap
# step, when available) instead of a flat cap, but stays clamped so a large
# site can never turn this into a rate-abusing crawl (handout: <5 min, respect
# robots, no rate abuse). With no site_url_count supplied, the historical
# defaults apply.
DEFAULT_MAX_PAGES = 40
DEFAULT_MAX_DEPTH = 3
DEFAULT_TIMEOUT_SECONDS = 30

MAX_PAGES_FLOOR, MAX_PAGES_CEIL = 20, 60
TIMEOUT_FLOOR, TIMEOUT_CEIL = 20, 45

# module-level names kept for backward compatibility with any external importer
MAX_PAGES = DEFAULT_MAX_PAGES
MAX_DEPTH = DEFAULT_MAX_DEPTH
TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS


def derive_budget(site_url_count=None, max_pages=None, max_depth=None, time_budget_s=None):
    """Return (max_pages, max_depth, timeout_s, description)."""
    if isinstance(max_pages, int) and max_pages > 0:
        mp = max_pages
    elif isinstance(site_url_count, int) and site_url_count > 0:
        mp = int(math.ceil(math.sqrt(site_url_count) * 2))
        mp = max(MAX_PAGES_FLOOR, min(mp, MAX_PAGES_CEIL))
    else:
        mp = DEFAULT_MAX_PAGES

    if isinstance(max_depth, int) and max_depth > 0:
        md = max_depth
    elif isinstance(site_url_count, int) and site_url_count > 500:
        md = 4
    else:
        md = DEFAULT_MAX_DEPTH

    if isinstance(time_budget_s, (int, float)) and time_budget_s > 0:
        tb = float(time_budget_s)
    elif isinstance(site_url_count, int) and site_url_count > 0:
        tb = 15 + site_url_count / 200.0
        tb = max(TIMEOUT_FLOOR, min(tb, TIMEOUT_CEIL))
    else:
        tb = DEFAULT_TIMEOUT_SECONDS

    desc = (f"max_pages={mp}, max_depth={md}, wall_clock={round(tb,1)}s "
            f"(from site_url_count={site_url_count})" if site_url_count
            else f"max_pages={mp}, max_depth={md}, wall_clock={round(tb,1)}s (defaults)")
    return mp, md, tb, desc

class LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []
        
    def handle_starttag(self, tag, attrs):
        try:
            if tag == "a":
                attrs_dict = dict(attrs)
                href = attrs_dict.get("href")
                if href:
                    if href.startswith(("javascript:", "mailto:", "tel:")):
                        return
                    if href.startswith("#"):
                        return
                        
                    abs_url = urllib.parse.urljoin(self.base_url, href)
                    abs_url = urllib.parse.urlunparse(urllib.parse.urlparse(abs_url)._replace(fragment=""))
                    self.links.append(abs_url)
        except Exception:
            pass

def normalize_for_match(url):
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

def _robots_parser_from_text(text):
    """Prefer the RFC 9309 evaluator shared with check_robots.py (longest match
    wins, wildcards honoured). stdlib robotparser applies the first matching
    rule, which can let this crawler fetch a path the site disallows."""
    try:
        import os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from check_robots import RFC9309Robots
        return RFC9309Robots(text)
    except Exception:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        return rp


def get_robots_parser(domain):
    try:
        if "://" not in domain:
            domain = "https://" + domain
        parsed = urllib.parse.urlparse(domain)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base_domain}/robots.txt"
        try:
            req = urllib.request.Request(robots_url, headers={'User-Agent': 'Mozilla/5.0 (crawler-bot)'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    return _robots_parser_from_text(
                        response.read().decode('utf-8', errors='replace'))
        except Exception:
            pass
        return None
    except Exception:
        return None

# A URL more than this many folders deep is reported as deep. This is a
# structural fact about the URL, not a quality judgement -- the orchestrator
# reports it as a low-severity crawl-friction signal only.
DEEP_URL_FOLDER_THRESHOLD = 3


# Segments that add URL length without adding hierarchy. Counting them makes
# every localized site (/de/, /en-us/) and every date-structured blog
# (/blog/2026/03/slug) look one-to-two levels deeper than it is.
# A locale prefix is an ISO 639-1 language code (a fixed, standard set -- like
# the HTML void-element list, not a fitted keyword list), optionally followed by
# a region/script subtag: /de/, /en-us/, /pt_BR/, /zh-hant/, /es-419/.
# Matching ANY two-letter segment was wrong: it discounted real folders such
# as /lp/ (landing pages), /cp/, /ux/.
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr
cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu
gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk
kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms
mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro
ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl
tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu
""".split())
_LOCALE_SEG_RX = re.compile(r"^([a-z]{2})(?:[-_](?:[a-z]{2}|\d{3}|[a-z]{4}))?$", re.I)


def _is_locale_segment(seg):
    m = _LOCALE_SEG_RX.match(seg or "")
    return bool(m) and m.group(1).lower() in ISO_639_1


_YEAR_SEG_RX   = re.compile(r"^(?:19|20)\d{2}$")
_MONTHDAY_RX   = re.compile(r"^(?:0[1-9]|[12]\d|3[01])$")


def url_folder_depth(url):
    """Number of *meaningful* path folders. '/a/b/c' -> 3.

    Not counted: a trailing filename (index.html), empty segments, leading
    locale codes (/de/, /en-us/, /pt-br/), and date segments (/2026/03/12/).
    Returns (depth, ignored_segments) so the evidence can show its working."""
    try:
        path = urllib.parse.urlparse(url or "").path or "/"
        segs = [s for s in path.split("/") if s]
        if segs and "." in segs[-1]:
            segs = segs[:-1]          # a file, not a folder level

        ignored = []
        kept = []
        for i, s in enumerate(segs):
            # locale codes only count as noise in the leading position
            if i == 0 and _is_locale_segment(s):
                ignored.append(f"{s} (locale)")
                continue
            if _YEAR_SEG_RX.match(s):
                ignored.append(f"{s} (year)")
                continue
            if _MONTHDAY_RX.match(s) and any("(year)" in x for x in ignored):
                ignored.append(f"{s} (month/day)")
                continue
            kept.append(s)
        return len(kept), ignored
    except Exception:
        return 0, []


def check_crawl_depth(start_url, target_url, robots_parser=None, site_url_count=None,
                      max_pages=None, max_depth=None, time_budget_s=None):
    start_time = time.time()
    robots_check_unavailable = False

    budget_max_pages, budget_max_depth, budget_timeout, budget_desc = derive_budget(
        site_url_count, max_pages, max_depth, time_budget_s)

    try:
        target_url = urllib.parse.urlunparse(urllib.parse.urlparse(target_url)._replace(fragment=""))
        target_domain = urllib.parse.urlparse(target_url).netloc
    except Exception as e:
        return {"depth": None, "path": [], "error": f"Invalid target URL: {str(e)}", "pages_crawled": 0}
    
    if robots_parser is not None:
        rp = robots_parser
    else:
        rp = get_robots_parser(start_url)
        if rp is None:
            robots_check_unavailable = True

    user_agent = "GPTBot" 
    
    queue = [(start_url, 0, [start_url])]
    visited = set([start_url])
    pages_crawled = 0
    
    target_normalized = normalize_for_match(target_url)

    folder_depth, ignored_segments = url_folder_depth(target_url)

    def build_result(depth, path, error):
        res = {
            "url": target_url,
            "depth": depth,                     # click-distance from start_url
            "path": path,
            "error": error,
            "pages_crawled": pages_crawled,
            "url_depth": folder_depth,          # meaningful folder levels
            "url_depth_ignored_segments": ignored_segments,
            "is_deep_url": folder_depth > DEEP_URL_FOLDER_THRESHOLD,
            "deep_url_threshold": DEEP_URL_FOLDER_THRESHOLD,
            "exploration_budget": budget_desc
        }
        if robots_check_unavailable:
            res["robots_check_unavailable"] = True
        return res

    while queue:
        if time.time() - start_time > budget_timeout:
            return build_result(None, [], "Timeout exceeded")

        if pages_crawled >= budget_max_pages:
            return build_result(None, [], "Max pages limit reached")

        current_url, depth, path = queue.pop(0)

        if normalize_for_match(current_url) == target_normalized:
            return build_result(depth, path, None)

        if depth >= budget_max_depth:
            continue
            
        if rp is None:
            continue
        else:
            try:
                if not rp.can_fetch(user_agent, current_url):
                    continue
            except Exception:
                continue
            
        pages_crawled += 1
        
        try:
            req = urllib.request.Request(current_url, headers={'User-Agent': 'Mozilla/5.0 (crawler-bot)'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    content = response.read().decode('utf-8', errors='replace')
                    
                    parser = LinkExtractor(current_url)
                    try:
                        parser.feed(content)
                    except Exception:
                        pass
                    
                    for link in set(parser.links):
                        try:
                            link_domain = urllib.parse.urlparse(link).netloc
                            if link_domain == target_domain and link not in visited:
                                visited.add(link)
                                queue.append((link, depth + 1, path + [link]))
                        except Exception:
                            pass
        except Exception:
            pass # Ignore fetch errors and continue
            
    return build_result(None, [], "Target not found within bounds")

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
        start_url = None
        target_url = None
        params = {}

        if len(sys.argv) > 1:
            raw1 = sys.argv[1].strip()
            if raw1.startswith("{"):
                try:
                    params = json.loads(raw1)
                    start_url = params.get("start_url") or params.get("url") or params.get("domain")
                    target_url = params.get("target_url") or params.get("target_page")
                except json.JSONDecodeError:
                    start_url = raw1
            else:
                start_url = raw1

        if len(sys.argv) > 2:
            target_url = sys.argv[2].strip()

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not start_url:
            start_url = params.get("start_url") or params.get("url") or params.get("domain") or "https://example.com"
        if not target_url:
            target_url = params.get("target_url") or params.get("target_page") or start_url

        if not start_url.startswith("http://") and not start_url.startswith("https://"):
            start_url = "https://" + start_url
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        def _int_or_none(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        output = check_crawl_depth(
            start_url, target_url,
            site_url_count=_int_or_none(params.get("site_url_count")),
            max_pages=_int_or_none(params.get("max_pages")),
            max_depth=_int_or_none(params.get("max_depth")),
            time_budget_s=params.get("time_budget_s"),
        )
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
