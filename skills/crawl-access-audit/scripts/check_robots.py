
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import os
import re
import urllib.parse
import urllib.request
from urllib.error import URLError, HTTPError
import socket
import time

# ---------------------------------------------------------------------------
# RFC 9309 (Robots Exclusion Protocol) evaluation.
#
# Python's urllib.robotparser is NOT used: it applies the FIRST matching rule
# in file order and does not understand `*` / `$` wildcards. Under RFC 9309 the
# MOST SPECIFIC (longest) matching rule wins and Allow wins a tie, so a group
#     Allow: /
#     Disallow: /lp/
# disallows /lp/... -- stdlib scores it allowed. It also silently ignores rules
# such as `Disallow: /*?*`.
# ---------------------------------------------------------------------------


def _product_token(agent):
    return str(agent or "").split("/")[0].strip().lower()


def parse_robots_txt(text):
    """Returns (groups, sitemaps). A group is one or more consecutive
    user-agent lines followed by its rules; groups naming the same agent are
    combined at evaluation time (RFC 9309 2.2.1)."""
    groups, sitemaps = [], []
    cur, last_was_ua = None, False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key in ("user-agent", "useragent", "user agent"):
            if cur is None or not last_was_ua:
                cur = {"agents": [], "rules": [], "crawl_delay": None}
                groups.append(cur)
            cur["agents"].append(val.lower())
            last_was_ua = True
        elif key in ("allow", "disallow"):
            last_was_ua = False
            if cur is not None:
                cur["rules"].append((key, val))
        elif key == "crawl-delay":
            last_was_ua = False
            if cur is not None:
                try:
                    cur["crawl_delay"] = float(val)
                except ValueError:
                    pass
        elif key == "sitemap":
            sitemaps.append(val)          # global, not part of any group
        # unknown directives (e.g. Content-Signal) are ignored
    return groups, sitemaps


_RX_CACHE = {}


def _rule_regex(pattern):
    rx = _RX_CACHE.get(pattern)
    if rx is None:
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        rx = re.compile("^" + "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
                        + ("$" if anchored else ""))
        _RX_CACHE[pattern] = rx
    return rx


def _path_and_query(path_or_url):
    s = str(path_or_url or "/")
    if "://" in s:
        p = urllib.parse.urlparse(s)
        s = (p.path or "/") + (("?" + p.query) if p.query else "")
    if not s.startswith("/"):
        s = "/" + s
    return s


def evaluate_robots(groups, agent, path_or_url):
    """Returns {"disallowed": bool, "rule": str|None, "group": str|None}."""
    token = _product_token(agent)
    target = _path_and_query(path_or_url)
    matched = [g for g in groups if token in g["agents"]]
    group_label = token
    if not matched:
        matched = [g for g in groups if "*" in g["agents"]]
        group_label = "*"
    if not matched or target == "/robots.txt":
        return {"disallowed": False, "rule": None, "group": group_label if matched else None}
    best = None  # (length, kind, pattern)
    for g in matched:
        for kind, pat in g["rules"]:
            if pat == "":
                continue                       # empty rule matches nothing
            if _rule_regex(pat).match(target):
                n = len(pat)
                if best is None or n > best[0] or (n == best[0] and kind == "allow"):
                    best = (n, kind, pat)
    if best is None:
        return {"disallowed": False, "rule": None, "group": group_label}
    return {"disallowed": best[1] == "disallow",
            "rule": f"{best[1].capitalize()}: {best[2]}", "group": group_label}


class RFC9309Robots:
    """Drop-in for the `can_fetch(agent, url)` interface other scripts use."""

    def __init__(self, text):
        self.groups, self.sitemaps = parse_robots_txt(text)

    def can_fetch(self, agent, url):
        return not evaluate_robots(self.groups, agent, url)["disallowed"]


# ---------------------------------------------------------------------------
# Crawler purpose classes (references/ai_crawler_classes.json). Blocking a
# training-only token (GPTBot, CCBot) keeps a site out of future model
# training but NOT out of live AI search citations, which come from separate
# retrieval tokens (OAI-SearchBot, PerplexityBot, Claude-SearchBot, ...).
# The class is a documented fact about the token, reported here; deciding
# how severe a block is stays with the orchestrator.
# ---------------------------------------------------------------------------
_FALLBACK_DEFAULT_AGENTS = ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "*"]


def load_crawler_classes():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "references", "ai_crawler_classes.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        classes = data.get("classes", {}) if isinstance(data, dict) else {}
        return {str(k).lower(): v for k, v in classes.items() if isinstance(v, dict)}
    except Exception:
        return {}


# Display casing for default agents, matching how operators write the tokens.
_TOKEN_CASING = {
    "oai-searchbot": "OAI-SearchBot", "chatgpt-user": "ChatGPT-User", "gptbot": "GPTBot",
    "claude-searchbot": "Claude-SearchBot", "claude-user": "Claude-User", "claudebot": "ClaudeBot",
    "anthropic-ai": "anthropic-ai", "perplexitybot": "PerplexityBot", "perplexity-user": "Perplexity-User",
    "googlebot": "Googlebot", "google-extended": "Google-Extended", "bingbot": "Bingbot",
    "applebot": "Applebot", "applebot-extended": "Applebot-Extended", "duckassistbot": "DuckAssistBot",
    "meta-externalfetcher": "Meta-ExternalFetcher", "meta-externalagent": "Meta-ExternalAgent",
    "meta-webindexer": "Meta-WebIndexer",
    "ccbot": "CCBot", "bytespider": "Bytespider",
}


def default_bot_agents(classes=None):
    classes = load_crawler_classes() if classes is None else classes
    if not classes:
        return list(_FALLBACK_DEFAULT_AGENTS)
    return [_TOKEN_CASING.get(t, t) for t in classes] + ["*"]


def classify_agents(agents, classes=None):
    """{agent: {"class", "role", "operator"}}. '*' covers every crawler without
    its own robots group, so it is classed 'wildcard' and handled like
    retrieval. Tokens missing from the reference are 'unclassified', also
    handled like retrieval, so an unknown bot never gets a softer verdict."""
    classes = load_crawler_classes() if classes is None else classes
    out = {}
    for agent in agents:
        token = _product_token(agent)
        if token == "*":
            out[agent] = {"class": "wildcard", "role": "all_unlisted_crawlers", "operator": None,
                          "honors_robots_txt": None}
            continue
        info = classes.get(token)
        if info:
            out[agent] = {"class": info.get("class", "unclassified"),
                          "role": info.get("role"), "operator": info.get("operator"),
                          # False: the operator says robots.txt may not apply
                          # (user-initiated fetchers), so a block is not effective.
                          "honors_robots_txt": info.get("honors_robots_txt")}
        else:
            out[agent] = {"class": "unclassified", "role": None, "operator": None,
                          "honors_robots_txt": None}
    return out


def check_robots(domain, bot_user_agents, test_paths=None, robots_txt=None):
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
        "evaluation": "RFC 9309 (longest match wins, Allow wins ties, * and $ wildcards)",
        "disallowed": {},          # {path: {agent: bool}}
        "matched_rules": {},       # {path: {agent: {"rule", "group"}}}
        "root_blocked_agents": [], # agents that may not fetch "/" (the homepage)
        "blocked_paths_by_agent": {},  # {agent: [tested paths disallowed]}
        # {agent: {class: retrieval|training|wildcard|unclassified, role, operator}}
        "agent_classes": classify_agents(bot_user_agents),
        "crawl_delay": None,
        "sitemap_url": None,
        "sitemap_urls": [],
        "error": None,
        "fetch_deadline_exceeded": False,
        # Raw directives + HTTP status, so robots_gate.RobotsGate can govern
        # every other fetch in the audit without re-requesting robots.txt.
        # `reachable` alone is not enough: RFC 9309 treats 404 as "allow all"
        # and 5xx/unreachable as "disallow all", and both are `reachable:
        # false` here.
        "robots_txt": "",
        "fetch_status": None,
    }

    content = ""
    success_candidate = None
    first_malformed = None
    candidate_errors = []
    skipped_candidates = []
    # Wall-clock ceiling across ALL candidates combined: on a slow-but-not-dead
    # server, 4 candidates x a per-request timeout can otherwise run unbounded
    # (the old worst case was ~40s per the comment below; a single check_robots
    # call is only one of several network-bound steps in a <5min audit budget).
    # Once this is hit, remaining candidates are skipped rather than tried --
    # a robots.txt this slow is itself worth reporting, not worth waiting out.
    fetch_deadline_s = 18.0
    fetch_start = time.time()

    if robots_txt is not None:
        # Caller already holds the file (offline evaluation / tests).
        success_candidate = f"https://{domain}/robots.txt"
        content = robots_txt
        candidates = []

    # Attempt fetch across candidates in order
    for robots_url in candidates:
        if time.time() - fetch_start > fetch_deadline_s:
            skipped_candidates.append(robots_url)
            continue

        attempt_error = None
        attempt_content = ""
        attempt_malformed = False

        attempt_status = None
        # Handle HTTP/network/timeout failures without crashing
        try:
            req = urllib.request.Request(
                robots_url,
                headers={"User-Agent": "Mozilla/5.0 (robots-checker)"}
            )

            # 6s per request: on a slow-but-live server a lower per-request
            # timeout risks a false "unreachable"; fetch_deadline_s above is
            # the real backstop against a pathologically slow candidate chain.
            with urllib.request.urlopen(req, timeout=6) as response:
                attempt_content = response.read().decode("utf-8", errors="replace")

                attempt_status = getattr(response, "status", None)
                if response.status != 200:
                    attempt_error = f"HTTP {response.status}"
                else:
                    # Detect HTTP 200 responses that are actually HTML
                    stripped = attempt_content.strip().lower()
                    if (stripped.startswith("<!doctype html") or "<html" in stripped or "<body" in stripped):
                        attempt_malformed = True
                        attempt_error = "Returned HTML instead of robots.txt"
                        
        except HTTPError as e:
            attempt_status = e.code
            attempt_error = f"HTTP {e.code}"
        except (URLError, socket.timeout) as e:
            attempt_error = str(e)
        except Exception as e:
            attempt_error = str(e)

        if attempt_status is not None:
            result["fetch_status"] = attempt_status
        if attempt_error is None and not attempt_malformed:
            # Found a reachable, non-HTML robots.txt
            success_candidate = robots_url
            content = attempt_content
            result["fetch_status"] = attempt_status or 200
            break
        else:
            if attempt_malformed and first_malformed is None:
                first_malformed = robots_url
            candidate_errors.append(f"{robots_url} ({attempt_error})")

    # If all candidates failed
    if success_candidate is None:
        if first_malformed is not None:
            # The server answered 200, but with an HTML page instead of
            # robots.txt directives. Report it; previously this state was held
            # in a local variable and never reached the output.
            result["reachable"] = True
            result["malformed"] = True
            result["resolved_url"] = first_malformed
            result["error"] = "robots.txt returned an HTML page instead of directives"
            return result
        error_msg = f"All URL variants failed: {', '.join(candidate_errors)}" if candidate_errors else \
            "No candidate URL was attempted"
        if skipped_candidates:
            error_msg += (f"; {len(skipped_candidates)} remaining candidate(s) skipped after "
                         f"{fetch_deadline_s:.0f}s wall-clock budget: {', '.join(skipped_candidates)}")
            result["fetch_deadline_exceeded"] = True
        result["error"] = error_msg
        return result

    # Success state
    result["reachable"] = True
    result["resolved_url"] = success_candidate
    result["robots_txt"] = content
    if result.get("fetch_status") is None:
        result["fetch_status"] = 200

    # Treat empty robots.txt as valid/usable, parse whatever is there
    try:
        groups, sitemaps = parse_robots_txt(content)
    except Exception as e:
        result["malformed"] = True
        result["error"] = f"Parse error: {str(e)}"
        return result

    if sitemaps:
        result["sitemap_url"] = sitemaps[0]
        result["sitemap_urls"] = sitemaps

    star = [g for g in groups if "*" in g["agents"]]
    result["crawl_delay"] = next((g["crawl_delay"] for g in star if g["crawl_delay"] is not None), None)

    # Always evaluate the homepage, plus every caller-supplied path. A path may
    # be a full URL (query string included -- rules like `Disallow: /*?*` apply).
    paths = ["/"] + [p for p in (test_paths or []) if p not in ("/", "")]
    for path in paths:
        result["disallowed"][path] = {}
        result["matched_rules"][path] = {}
        for agent in bot_user_agents:
            try:
                ev = evaluate_robots(groups, agent, path)
                result["disallowed"][path][agent] = ev["disallowed"]
                result["matched_rules"][path][agent] = {"rule": ev["rule"], "group": ev["group"]}
            except Exception:
                # Do not assume an evaluation failure means "allowed"
                result["disallowed"][path][agent] = "unknown_error"

    # A URL blocked only because of its query string (e.g. `Disallow: /*?*`)
    # while the same path without the query is allowed is ordinary
    # duplicate-URL hygiene, not an access defect. Record it separately.
    result["query_variant_only_blocks"] = {}
    for path in paths:
        target = _path_and_query(path)
        if "?" not in target:
            continue
        base = target.split("?", 1)[0]
        for agent in bot_user_agents:
            if result["disallowed"][path].get(agent) is True:
                base_ev = evaluate_robots(groups, agent, base)
                if not base_ev["disallowed"]:
                    result["matched_rules"][path][agent]["query_variant_only"] = True
                    result["query_variant_only_blocks"].setdefault(agent, []).append(path)

    for agent in bot_user_agents:
        if result["disallowed"]["/"].get(agent) is True:
            result["root_blocked_agents"].append(agent)
        blocked = [p for p in paths
                   if p != "/" and result["disallowed"][p].get(agent) is True
                   and not result["matched_rules"][p].get(agent, {}).get("query_variant_only")]
        if blocked:
            result["blocked_paths_by_agent"][agent] = blocked

    return result

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
        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not domain_arg:
            domain_arg = params.get("domain") or params.get("url") or "example.com"

        # Default: every token in references/ai_crawler_classes.json (retrieval
        # AND training) plus "*", so a training-only block can be told apart
        # from a block that removes the site from live AI search answers.
        bot_agents = params.get("bot_user_agents") or default_bot_agents()
        test_paths = params.get("test_paths", ["/"])

        output = check_robots(domain_arg, bot_agents, test_paths,
                              robots_txt=params.get("robots_txt"))
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
