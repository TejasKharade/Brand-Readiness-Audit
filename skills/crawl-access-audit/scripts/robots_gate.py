import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
"""The single place this marketplace decides whether it may fetch a URL.

Every script in this marketplace that opens an HTTP connection to the audited
site asks this module first. Previously only `check_crawl_depth.py` consulted
robots.txt for its own link-following crawl; the dual-identity fetch, the
sitemap URL spot-checks, the page-weight resource probes, the linked-PDF reads
and the headless render all fetched unconditionally. The worst case was
concrete rather than theoretical: `fetch_dual_identity.py` sends a
`GPTBot/1.2` user-agent, so on a site whose robots.txt carries
`User-agent: GPTBot / Disallow: /` the audit requested a forbidden path *while
identifying as the crawler that was forbidden*.

Design notes
------------
* **No extra requests.** `check_robots.py` already fetches robots.txt at the
  start of every audit. Pass its output (or the raw text) in, and this gate
  costs zero additional HTTP requests. Only a script run standalone, with
  nothing passed in, fetches robots.txt itself -- once, cached per host for
  the life of the process.

* **RFC 9309 status semantics** (section 2.3.1), which are not the same as
  "reachable or not":
    - `2xx` -> parse and apply the rules.
    - `4xx` (404 included) -> no robots.txt exists; **everything is allowed**.
      Failing closed here would make every site without a robots.txt
      unauditable, which the RFC explicitly does not ask for.
    - `5xx`, timeout, DNS failure -> robots.txt is *unreachable*, and the RFC
      says a crawler may assume complete disallow. This gate **fails closed**.
    - HTTP 200 returning an HTML page -> zero parseable directives, which is
      the same as no rules at all: allowed, with the anomaly recorded.

* **Robots matches product tokens, not whole UA strings.** A full browser
  user-agent belongs to the `*` group; `...compatible; GPTBot/1.2; ...`
  belongs to the `GPTBot` group. `robots_token()` does that reduction, so a
  caller can pass whatever user-agent it is really going to send.

* **This gate never decides severity.** It answers "may I fetch this?" and
  records why. Whether a block is worth reporting, and how badly, stays in
  the orchestrator like every other judgement in this marketplace.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from check_robots import RFC9309Robots, evaluate_robots, parse_robots_txt, load_crawler_classes
except Exception:  # pragma: no cover - check_robots.py is always beside this file
    RFC9309Robots = None
    evaluate_robots = parse_robots_txt = load_crawler_classes = None

# robots.txt itself is never governed by robots.txt.
ALWAYS_ALLOWED_PATHS = ("/robots.txt",)

# A crawl-delay longer than this is not worth honouring inside a <5 minute
# audit: the run would blow its budget waiting. The gate reports the value and
# lets the caller skip the page instead of hammering it.
MAX_HONOURED_CRAWL_DELAY_S = 10.0

_GATE_CACHE = {}


class RobotsDecision(object):
    """Why a fetch was permitted or refused, in a form the report can quote."""

    __slots__ = ("allowed", "reason", "rule", "agent", "source", "crawl_delay_s")

    def __init__(self, allowed, reason, rule=None, agent=None, source=None, crawl_delay_s=None):
        self.allowed = allowed
        self.reason = reason
        self.rule = rule
        self.agent = agent
        self.source = source
        self.crawl_delay_s = crawl_delay_s

    # Deliberately NOT truthiness-testable. Defining __bool__ here made a
    # *denied* decision falsy, so `decision.as_dict() if decision else None`
    # threw away precisely the decisions worth recording. Callers ask
    # `decision.allowed` (or `is not None`), which cannot be misread.
    def as_dict(self):
        out = {"allowed": self.allowed, "reason": self.reason}
        if self.rule:
            out["rule"] = self.rule
        if self.agent:
            out["agent"] = self.agent
        if self.source:
            out["source"] = self.source
        if self.crawl_delay_s:
            out["crawl_delay_s"] = self.crawl_delay_s
        return out


def _known_crawler_tokens():
    tokens = set()
    if load_crawler_classes:
        try:
            tokens |= {str(k) for k in load_crawler_classes().keys()}
        except Exception:
            pass
    # Tokens this marketplace sends or checks even when the reference file is
    # unavailable, so the reduction below never silently degrades to "*".
    tokens |= {"gptbot", "claudebot", "ccbot", "google-extended", "bytespider",
               "perplexitybot", "oai-searchbot", "claude-searchbot", "chatgpt-user",
               "perplexity-user", "applebot", "applebot-extended", "meta-externalagent",
               "amazonbot", "youbot", "diffbot", "cohere-ai", "timpibot", "omgili"}
    return tokens


def robots_token(user_agent):
    """Reduce a user-agent string to the robots.txt product token it matches.

    A generic browser user-agent matches no named group, so it is governed by
    `*` -- which is the correct reading: our audit is an automated client, and
    a site that disallows `*` has disallowed us too.
    """
    ua = (user_agent or "").strip()
    if not ua:
        return "*"
    if ua == "*":
        return "*"
    lowered = ua.lower()
    # A bare token was passed ("GPTBot"), not a full UA string.
    if " " not in ua and "/" not in ua:
        return ua
    for token in sorted(_known_crawler_tokens(), key=len, reverse=True):
        if token in lowered:
            return token
    return "*"


class RobotsGate(object):
    """Answers 'may this audit fetch that URL?' for one host."""

    def __init__(self, robots_txt=None, status=None, error=None, host=None, malformed=False):
        self.host = host
        self.status = status
        self.error = error
        self.malformed = malformed
        self.robots_txt = robots_txt or ""
        self.groups = []
        self.sitemaps = []
        self._parse_failed = False

        if self.robots_txt and parse_robots_txt:
            try:
                self.groups, self.sitemaps = parse_robots_txt(self.robots_txt)
            except Exception:
                self._parse_failed = True

    # -- construction ------------------------------------------------------
    @classmethod
    def from_robots_result(cls, robots_result):
        """Build from `check_robots.py` output -- costs no HTTP request."""
        r = robots_result if isinstance(robots_result, dict) else {}
        return cls(
            robots_txt=r.get("robots_txt") or r.get("content") or "",
            status=r.get("fetch_status") if r.get("fetch_status") is not None
            else (200 if r.get("reachable") else None),
            error=r.get("error"),
            host=r.get("host"),
            malformed=bool(r.get("malformed")),
        )

    @classmethod
    def for_url(cls, url, robots=None, timeout=6, use_cache=True):
        """Preferred entrypoint.

        `robots` may be: a `check_robots.py` result dict, `{"robots_txt": ...,
        "status": ...}`, the raw robots.txt text, or None. Only the None case
        performs a request, and only once per host per process.
        """
        host = _host_of(url)
        if isinstance(robots, dict):
            gate = (cls.from_robots_result(robots) if ("reachable" in robots or "matched_rules" in robots)
                    else cls(robots_txt=robots.get("robots_txt") or robots.get("text") or "",
                             status=robots.get("status"), error=robots.get("error"), host=host,
                             malformed=bool(robots.get("malformed"))))
            gate.host = gate.host or host
            if use_cache:
                _GATE_CACHE[host] = gate
            return gate
        if isinstance(robots, str) and robots.strip():
            gate = cls(robots_txt=robots, status=200, host=host)
            if use_cache:
                _GATE_CACHE[host] = gate
            return gate
        if use_cache and host in _GATE_CACHE:
            return _GATE_CACHE[host]
        gate = cls._fetch(url, timeout=timeout)
        if use_cache:
            _GATE_CACHE[host] = gate
        return gate

    @classmethod
    def _fetch(cls, url, timeout=6):
        host = _host_of(url)
        parsed = urllib.parse.urlparse(url if "://" in (url or "") else "https://" + (url or ""))
        robots_url = "%s://%s/robots.txt" % (parsed.scheme or "https", parsed.netloc)
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": "Mozilla/5.0 (robots-checker)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200) or 200
                stripped = text.strip().lower()
                malformed = stripped.startswith("<!doctype html") or "<html" in stripped
                return cls(robots_txt="" if malformed else text, status=status,
                           host=host, malformed=malformed)
        except urllib.error.HTTPError as e:
            return cls(robots_txt="", status=e.code, host=host)
        except (urllib.error.URLError, socket.timeout) as e:
            return cls(robots_txt="", status=None, error=str(e), host=host)
        except Exception as e:
            return cls(robots_txt="", status=None, error=str(e), host=host)

    # -- decisions ---------------------------------------------------------
    def allows(self, url, user_agent="*"):
        path = urllib.parse.urlparse(url or "").path or "/"
        if path in ALWAYS_ALLOWED_PATHS:
            return RobotsDecision(True, "robots.txt itself is never governed by robots.txt",
                                  source="exempt")

        status = self.status
        if status is None:
            return RobotsDecision(
                False,
                "robots.txt could not be retrieved (%s), so per RFC 9309 the audit assumes "
                "a complete disallow rather than fetching anyway" % (self.error or "network error"),
                source="unreachable")
        if 500 <= int(status) < 600:
            return RobotsDecision(
                False,
                "robots.txt returned HTTP %s; RFC 9309 treats an unavailable robots.txt as a "
                "complete disallow" % status,
                source="server_error")
        if 400 <= int(status) < 500:
            return RobotsDecision(True, "no robots.txt published (HTTP %s), so nothing is disallowed" % status,
                                  source="absent")
        if self.malformed or self._parse_failed:
            return RobotsDecision(True, "robots.txt contained no parseable directives, so nothing is disallowed",
                                  source="unparseable")

        agent = robots_token(user_agent)
        if not self.groups or not evaluate_robots:
            return RobotsDecision(True, "robots.txt declares no rules", agent=agent, source="empty")

        try:
            verdict = evaluate_robots(self.groups, agent, url)
        except Exception:
            # Never let an evaluator bug turn into an unchecked fetch.
            return RobotsDecision(False, "robots.txt rules could not be evaluated; refusing to fetch",
                                  agent=agent, source="evaluator_error")

        if verdict.get("disallowed"):
            return RobotsDecision(
                False,
                "robots.txt disallows %s for user-agent %s (matched group '%s')" % (
                    path, agent, verdict.get("group") or agent),
                rule=verdict.get("rule"), agent=agent, source="disallow")
        return RobotsDecision(True, "allowed by robots.txt", rule=verdict.get("rule"),
                              agent=agent, source="allow")

    def crawl_delay_s(self, user_agent="*"):
        """Crawl-delay declared for this agent, if any (seconds, float)."""
        agent = robots_token(user_agent).lower()
        best = None
        for g in self.groups or []:
            agents = [str(a).lower() for a in (g.get("agents") or [])]
            if agent in agents or "*" in agents:
                delay = g.get("crawl_delay")
                if delay is None:
                    continue
                try:
                    delay = float(delay)
                except (TypeError, ValueError):
                    continue
                # A named group beats the wildcard group.
                if agent in agents:
                    return delay
                best = delay if best is None else max(best, delay)
        return best


def _host_of(url):
    try:
        s = url if "://" in (url or "") else "https://" + (url or "")
        return urllib.parse.urlparse(s).netloc.lower()
    except Exception:
        return ""


def skipped_payload(url, decision, extra=None):
    """Uniform shape every gated fetcher returns instead of its normal output.

    The orchestrator must be able to tell "we were not allowed to look" apart
    from "we looked and found nothing" -- reporting the second when the first
    is true would be a fabricated finding.
    """
    payload = {
        "url": url,
        "skipped_by_robots": True,
        "fetched": False,
        "robots_decision": decision.as_dict() if decision is not None else None,
        "error": "Not fetched: %s" % (decision.reason if decision else "disallowed by robots.txt"),
    }
    if extra:
        payload.update(extra)
    return payload


def polite_delay(gate, user_agent="*", minimum=0.0):
    """Sleep long enough to honour crawl-delay, bounded by the audit budget.

    Returns the delay actually applied. A crawl-delay beyond
    MAX_HONOURED_CRAWL_DELAY_S is not slept off -- the caller is expected to
    skip the extra page instead, which is politer than either ignoring the
    directive or stalling the run.
    """
    declared = None
    try:
        declared = gate.crawl_delay_s(user_agent) if gate else None
    except Exception:
        declared = None
    delay = max(minimum, min(declared or 0.0, MAX_HONOURED_CRAWL_DELAY_S))
    if delay > 0:
        try:
            time.sleep(delay)
        except Exception:
            pass
    return delay


if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    params = {}
    if raw.startswith("{"):
        try:
            params = json.loads(raw)
        except json.JSONDecodeError:
            params = {"url": raw}
    elif raw:
        params = {"url": raw}

    url = params.get("url", "")
    gate = RobotsGate.for_url(url, robots=params.get("robots"))
    agents = params.get("user_agents") or [params.get("user_agent", "*")]
    print(json.dumps({
        "url": url,
        "robots_status": gate.status,
        "decisions": {a: gate.allows(url, a).as_dict() for a in agents},
        "crawl_delay_s": gate.crawl_delay_s(agents[0] if agents else "*"),
    }, indent=2))
