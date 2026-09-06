import sys
import json
import urllib.robotparser
import urllib.request
from urllib.error import URLError, HTTPError
import socket

def check_robots(domain, bot_user_agents, test_paths=None):
    # Strip existing protocol if given to build candidates reliably
    if domain.startswith("http://"):
        domain = domain[7:]
    elif domain.startswith("https://"):
        domain = domain[8:]
    domain = domain.rstrip("/")

    # Build an ordered list of candidate URLs
    candidates = []
    if domain.startswith("www."):
        bare_domain = domain[4:]
        candidates.extend([
            f"https://{domain}/robots.txt",
            f"https://{bare_domain}/robots.txt",
            f"http://{domain}/robots.txt",
            f"http://{bare_domain}/robots.txt",
        ])
    else:
        candidates.extend([
            f"https://{domain}/robots.txt",
            f"https://www.{domain}/robots.txt",
            f"http://{domain}/robots.txt",
            f"http://www.{domain}/robots.txt",
        ])

    result = {
        "reachable": False,
        "malformed": False,
        "resolved_url": None,
        "disallowed": {},
        "crawl_delay": None,
        "sitemap_url": None,
        "error": None
    }

    rp = urllib.robotparser.RobotFileParser()
    content = ""
    success_candidate = None
    candidate_errors = []

    # Attempt fetch across candidates in order
    for robots_url in candidates:
        rp.set_url(robots_url)
        attempt_error = None
        attempt_content = ""
        attempt_malformed = False

        # Handle HTTP/network/timeout failures without crashing
        try:
            req = urllib.request.Request(
                robots_url,
                headers={"User-Agent": "Mozilla/5.0 (robots-checker)"}
            )

            # Note: Worst case full run across 4 failing candidates takes up to ~40s
            with urllib.request.urlopen(req, timeout=10) as response:
                attempt_content = response.read().decode("utf-8", errors="replace")

                if response.status != 200:
                    attempt_error = f"HTTP {response.status}"
                else:
                    # Detect HTTP 200 responses that are actually HTML
                    stripped = attempt_content.strip().lower()
                    if (stripped.startswith("<!doctype html") or "<html" in stripped or "<body" in stripped):
                        attempt_malformed = True
                        attempt_error = "Returned HTML instead of robots.txt"
                        
        except HTTPError as e:
            attempt_error = f"HTTP {e.code}"
        except (URLError, socket.timeout) as e:
            attempt_error = str(e)
        except Exception as e:
            attempt_error = str(e)

        if attempt_error is None and not attempt_malformed:
            # Found a reachable, non-HTML robots.txt
            success_candidate = robots_url
            content = attempt_content
            break
        else:
            candidate_errors.append(f"{robots_url} ({attempt_error})")

    # If all candidates failed
    if success_candidate is None:
        result["error"] = f"All URL variants failed: {', '.join(candidate_errors)}"
        return result

    # Success state
    result["reachable"] = True
    result["resolved_url"] = success_candidate

    # Treat empty robots.txt as valid/usable, parse whatever is there
    try:
        rp.parse(content.splitlines())
    except Exception as e:
        result["malformed"] = True
        result["error"] = f"Parse error: {str(e)}"
        return result

    sitemaps = rp.site_maps()
    if sitemaps:
        result["sitemap_url"] = sitemaps[0]

    # Keep crawl-delay separate
    result["crawl_delay"] = rp.crawl_delay("*")

    # Base domain to use for URL path checks (derived from whichever variant worked)
    resolved_base = success_candidate[:success_candidate.rfind("/robots.txt")]

    # Check paths against relevant AI user agents
    if test_paths:
        for path in test_paths:
            result["disallowed"][path] = {}
            for agent in bot_user_agents:
                url = f"{resolved_base}/{path.lstrip('/')}"
                try:
                    # can_fetch returns True if allowed to crawl, so we invert it for 'disallowed'
                    result["disallowed"][path][agent] = not rp.can_fetch(agent, url)
                except Exception:
                    # Do not assume can_fetch() failure means "allowed"; return unknown
                    result["disallowed"][path][agent] = "unknown_error"

    return result

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
        domain_arg = None
        params = {}

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    domain_arg = params.get("domain") or params.get("url")
                except json.JSONDecodeError:
                    domain_arg = raw_arg
            else:
                domain_arg = raw_arg

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=0.2)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not domain_arg:
            domain_arg = params.get("domain") or params.get("url") or "example.com"

        bot_agents = params.get("bot_user_agents", ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "*"])
        test_paths = params.get("test_paths", ["/"])

        output = check_robots(domain_arg, bot_agents, test_paths)
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
