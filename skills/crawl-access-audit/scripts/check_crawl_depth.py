import sys
import json
import time
import urllib.parse
import urllib.robotparser
import urllib.request
from html.parser import HTMLParser
from urllib.error import URLError, HTTPError
import socket

MAX_PAGES = 40
MAX_DEPTH = 3
TIMEOUT_SECONDS = 30

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
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip('/')
        return f"{netloc}{path}".lower()
    except Exception:
        return ""

def get_robots_parser(domain):
    try:
        parsed = urllib.parse.urlparse(domain)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base_domain}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            req = urllib.request.Request(robots_url, headers={'User-Agent': 'Mozilla/5.0 (crawler-bot)'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    rp.parse(response.read().decode('utf-8', errors='replace').splitlines())
                    return rp
        except Exception:
            pass
        return None
    except Exception:
        return None

def check_crawl_depth(start_url, target_url, robots_parser=None):
    start_time = time.time()
    robots_check_unavailable = False
    
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

    def build_result(depth, path, error):
        res = {
            "depth": depth,
            "path": path,
            "error": error,
            "pages_crawled": pages_crawled
        }
        if robots_check_unavailable:
            res["robots_check_unavailable"] = True
        return res

    while queue:
        if time.time() - start_time > TIMEOUT_SECONDS:
            return build_result(None, [], "Timeout exceeded")
            
        if pages_crawled >= MAX_PAGES:
            return build_result(None, [], "Max pages limit reached")
            
        current_url, depth, path = queue.pop(0)
        
        if normalize_for_match(current_url) == target_normalized:
            return build_result(depth, path, None)
            
        if depth >= MAX_DEPTH:
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

if __name__ == "__main__":
    try:
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing start_url or target_url arguments"}))
            sys.exit(0)
            
        start_url = sys.argv[1]
        target_url = sys.argv[2]
        
        output = check_crawl_depth(start_url, target_url)
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
