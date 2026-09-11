
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json

# --- robots.txt gate --------------------------------------------------------
# Every fetch in this file asks robots_gate first. The gate is built from the
# robots.txt that check_robots.py already fetched (passed in as `robots`), so
# it costs no extra request; only a standalone run fetches robots.txt itself.
import os as _os
for _d in (_os.path.dirname(_os.path.abspath(__file__)),
           _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "..", "crawl-access-audit", "scripts")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
try:
    from robots_gate import RobotsGate, skipped_payload, polite_delay
except Exception:  # gate unavailable -> refuse to fetch, never fetch blind
    RobotsGate = None

    def skipped_payload(url, decision, extra=None):
        out = {"url": url, "skipped_by_robots": True, "fetched": False,
               "error": "Not fetched: robots gate unavailable"}
        if extra:
            out.update(extra)
        return out

    def polite_delay(gate, user_agent="*", minimum=0.0):
        import time as _t
        if minimum > 0:
            _t.sleep(minimum)
        return minimum

import time
import html.parser
import urllib.request
import urllib.error
import socket
import ssl

# "Thin content" is no longer a single character cutoff. It is decided from the
# ratio of real main-body text to page chrome (nav/header/footer/aside), with a
# small absolute floor for pages that carry essentially no readable text at all
# (true block pages, empty JS shells). A minimalist hero page with a few
# sentences of real copy and a big menu is NOT thin; a "checking your browser"
# interstitial whose only text is boilerplate IS.
MAIN_TEXT_ABSOLUTE_FLOOR_CHARS = 80     # ~12 words of real body text
CHROME_DOMINANCE_RATIO = 0.15           # main text < 15% of total, when total is non-trivial
CHROME_DOMINANCE_MIN_TOTAL_CHARS = 200  # only apply the ratio test once there is some text

# Back-compat alias (older callers / tests may still pass thin_threshold)
THIN_CONTENT_THRESHOLD = MAIN_TEXT_ABSOLUTE_FLOOR_CHARS

BOILERPLATE_TAGS = {"nav", "header", "footer", "aside"}

CLOUDFLARE_SIGNALS = [
    "checking your browser", 
    "cf-browser-verification", 
    "cf-chl", 
    "just a moment", 
    "cf-im-under-attack", 
    "enable javascript and cookies to continue"
]

CAPTCHA_SIGNALS = [
    "recaptcha", 
    "hcaptcha", 
    "g-recaptcha", 
    "verify you are human", 
    "captcha-container", 
    "i'm not a robot"
]

LOGIN_WALL_SIGNALS = [
    "sign in", 
    "log in", 
    "password"
]

GENERIC_BLOCK_SIGNALS = [
    "access denied",
    "403 forbidden",
    "access forbidden",
    "request blocked",
    "blocked by security policy"
]

class TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []            # all visible text (main + chrome)
        self.main_text = []       # visible text NOT inside nav/header/footer/aside
        self.boilerplate_text = []
        self.has_password_input = False
        self.has_form = False
        self.skip_tags = {'script', 'style', 'noscript', 'iframe', 'svg', 'template'}
        self.in_skip_tag = False
        self.current_skip_tag = None
        self._boilerplate_depth = 0

    def handle_data(self, data):
        if not self.in_skip_tag and data and data.strip():
            s = data.strip()
            self.text.append(s)
            if self._boilerplate_depth > 0:
                self.boilerplate_text.append(s)
            else:
                self.main_text.append(s)

    def handle_starttag(self, tag, attrs):
        try:
            t = tag.lower()
            if t in self.skip_tags and not self.in_skip_tag:
                self.in_skip_tag = True
                self.current_skip_tag = t
            if t in BOILERPLATE_TAGS:
                self._boilerplate_depth += 1
            if t == "form":
                self.has_form = True
            if t == "input":
                attrs_dict = dict(attrs)
                if attrs_dict.get("type", "").lower() == "password":
                    self.has_password_input = True
        except Exception:
            pass

    def handle_endtag(self, tag):
        t = tag.lower()
        if self.in_skip_tag and t == self.current_skip_tag:
            self.in_skip_tag = False
            self.current_skip_tag = None
        if t in BOILERPLATE_TAGS and self._boilerplate_depth > 0:
            self._boilerplate_depth -= 1

    def get_text(self):
        return " ".join(self.text)

    def get_main_text(self):
        return " ".join(self.main_text)

    def get_boilerplate_text(self):
        return " ".join(self.boilerplate_text)

def _assess_thin_content(main_len, total_len):
    """Returns (is_thin: bool, reason: str). Dynamic: near-empty main text OR
    page text that is overwhelmingly chrome/boilerplate rather than content."""
    if main_len < MAIN_TEXT_ABSOLUTE_FLOOR_CHARS:
        return True, (f"main-body text is {main_len} chars (< {MAIN_TEXT_ABSOLUTE_FLOOR_CHARS} "
                      f"floor) -> effectively no readable content")
    if total_len >= CHROME_DOMINANCE_MIN_TOTAL_CHARS:
        ratio = main_len / total_len
        if ratio < CHROME_DOMINANCE_RATIO:
            return True, (f"main-body text is only {ratio:.0%} of page text "
                          f"({main_len}/{total_len} chars) -> page is almost all nav/chrome")
    return False, (f"main-body text {main_len} chars "
                   f"({(main_len/total_len):.0%} of {total_len} total) -> adequate"
                   if total_len else f"main-body text {main_len} chars -> adequate")


def analyze_fingerprints(html_content, thin_threshold=None):
    try:
        if not html_content:
            html_content = ""
        html_lower = html_content.lower()

        # 1. Cloudflare
        cf_matches = [s for s in CLOUDFLARE_SIGNALS if s in html_lower]

        # 2. CAPTCHA
        captcha_matches = [s for s in CAPTCHA_SIGNALS if s in html_lower]

        # 3. Generic Block
        generic_block_matches = [s for s in GENERIC_BLOCK_SIGNALS if s in html_lower]

        # Parse HTML for login wall and thin content
        parser = TextExtractor()
        parser_error = None
        try:
            parser.feed(html_content)
        except Exception as e:
            parser_error = str(e)

        visible_text = parser.get_text()
        visible_text_len = len(visible_text)
        main_text_len = len(parser.get_main_text())
        boilerplate_text_len = len(parser.get_boilerplate_text())

        # 4. Thin content (dynamic content-to-boilerplate assessment)
        floor = thin_threshold if isinstance(thin_threshold, int) else MAIN_TEXT_ABSOLUTE_FLOOR_CHARS
        if isinstance(thin_threshold, int):
            # explicit override: honour it as a simple floor on main text
            is_thin = main_text_len < floor
            thin_reason = f"explicit threshold: main text {main_text_len} < {floor}"
        else:
            is_thin, thin_reason = _assess_thin_content(main_text_len, visible_text_len)

        content_ratio = round(main_text_len / visible_text_len, 3) if visible_text_len else None

        # 5. Login wall
        login_wall = False
        if parser.has_form and parser.has_password_input and is_thin:
            login_wall = True

        return {
            "cloudflare_challenge": bool(cf_matches),
            "cloudflare_signals": cf_matches,
            "captcha": bool(captcha_matches),
            "captcha_signals": captcha_matches,
            "generic_block": bool(generic_block_matches),
            "generic_block_signals": generic_block_matches,
            "login_wall": login_wall,
            "thin_content": is_thin,
            "thin_content_reason": thin_reason,
            "visible_text_length": visible_text_len,
            "main_text_length": main_text_len,
            "boilerplate_text_length": boilerplate_text_len,
            "content_to_total_ratio": content_ratio,
            "_fingerprint_error": parser_error
        }
    except Exception as e:
        return {
            "cloudflare_challenge": False,
            "cloudflare_signals": [],
            "captcha": False,
            "captcha_signals": [],
            "generic_block": False,
            "generic_block_signals": [],
            "login_wall": False,
            "thin_content": False,
            "thin_content_reason": f"analysis error: {str(e)}",
            "visible_text_length": 0,
            "main_text_length": 0,
            "boilerplate_text_length": 0,
            "content_to_total_ratio": None,
            "_fingerprint_error": f"Fatal analysis error: {str(e)}"
        }

class RedirectTracker(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.redirect_count = 0
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > 10:
            raise urllib.error.HTTPError(newurl, code, "Too many redirects", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch_url(url, user_agent, timeout=10, retries_on_429=1):
    start_time = time.time()
    default_fingerprints = {
        "cloudflare_challenge": False, "cloudflare_signals": [], "captcha": False, "captcha_signals": [],
        "generic_block": False, "generic_block_signals": [],
        "login_wall": False, "thin_content": False, "thin_content_reason": "no content fetched",
        "visible_text_length": 0, "main_text_length": 0, "boilerplate_text_length": 0,
        "content_to_total_ratio": None, "_fingerprint_error": None
    }
    
    tracker = RedirectTracker()
    opener = urllib.request.build_opener(tracker)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    
    for attempt in range(retries_on_429 + 1):
        try:
            with opener.open(req, timeout=timeout) as resp:
                response_time = time.time() - start_time
                status_code = resp.getcode()
                final_url = resp.geturl()
                headers_dict = dict(resp.info())
                
                MAX_BYTES = 500 * 1024
                chunks = []
                bytes_read = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    bytes_read += len(chunk)
                    if bytes_read >= MAX_BYTES:
                        break
                
                raw_bytes = b"".join(chunks)
                try:
                    content = raw_bytes.decode("utf-8", errors="replace")
                except Exception:
                    content = raw_bytes.decode("latin-1", errors="replace")
                    
                fingerprints = analyze_fingerprints(content)
                
                if bytes_read >= MAX_BYTES:
                    content = content[:MAX_BYTES] + "\n...[TRUNCATED]"
                    
                return {
                    "status": status_code,
                    "final_url": final_url,
                    "redirect_count": tracker.redirect_count,
                    "response_time": round(response_time, 3),
                    "response_headers": headers_dict,
                    "content": content,
                    "content_fingerprints": fingerprints,
                    "error": None
                }
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries_on_429:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait_time = 1.5
                if retry_after and str(retry_after).isdigit():
                    wait_time = min(float(retry_after), 3.0)
                time.sleep(wait_time)
                continue

            response_time = time.time() - start_time
            try:
                body_bytes = e.read(500 * 1024)
                content = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                content = ""
            fingerprints = analyze_fingerprints(content) if content else default_fingerprints
            return {
                "status": e.code,
                "final_url": e.url or url,
                "redirect_count": tracker.redirect_count,
                "response_time": round(response_time, 3),
                "response_headers": dict(e.headers) if e.headers else {},
                "content": content,
                "content_fingerprints": fingerprints,
                "error": None
            }
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            return {
                "status": "timeout" if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower() else None,
                "final_url": None, "redirect_count": 0,
                "response_time": round(time.time() - start_time, 3),
                "response_headers": {}, "content": "",
                "content_fingerprints": default_fingerprints, "error": str(e)
            }
        except Exception as e:
            return {
                "status": None, "final_url": None, "redirect_count": 0,
                "response_time": round(time.time() - start_time, 3),
                "response_headers": {}, "content": "",
                "content_fingerprints": default_fingerprints, "error": f"Unexpected error: {str(e)}"
            }

def dual_fetch(url, browser_ua, bot_ua, delay=2.0, timeout=7, robots=None):
    """Fetch `url` twice -- once as a browser, once as an AI crawler.

    Each leg is gated on robots.txt for the identity it presents. The bot leg
    is the one that matters most: it sends a GPTBot user-agent, so on a site
    with `User-agent: GPTBot / Disallow: /` an ungated fetch would request a
    forbidden path *while identifying as the forbidden crawler*. A skipped leg
    is reported as skipped -- never as an empty result, which the checks
    downstream would read as "this page has no content".
    """
    gate = RobotsGate.for_url(url, robots=robots) if RobotsGate else None
    browser_decision = gate.allows(url, browser_ua) if gate else None
    bot_decision = gate.allows(url, bot_ua) if gate else None
    # 7s (down from 10s): this pair of fetches runs once per sampled page, so
    # its cost multiplies with page count; a real server answers in well
    # under this, and a 429-retry (capped at 3s wait) plus this timeout on
    # both fetches already tops out well short of the old ~48s worst case.
    if browser_decision is not None and not browser_decision.allowed:
        browser_result = skipped_payload(url, browser_decision)
    else:
        browser_result = fetch_url(url, browser_ua, timeout=timeout)

    # Honour Crawl-delay when robots.txt declares one longer than our own
    # spacing; `delay` stays the floor, so we are never faster than before.
    polite_delay(gate, bot_ua, minimum=delay)

    if bot_decision is not None and not bot_decision.allowed:
        bot_result = skipped_payload(url, bot_decision)
    else:
        bot_result = fetch_url(url, bot_ua, timeout=timeout)
    
    comparison = {}
    bot_status = bot_result.get("status")
    browser_status = browser_result.get("status")

    if browser_status and bot_status:
        comparison["status_match"] = browser_status == bot_status
        comparison["length_diff_bytes"] = abs(len(browser_result.get("content", "")) - len(bot_result.get("content", "")))
        
        br_fp = browser_result.get("content_fingerprints", {})
        bot_fp = bot_result.get("content_fingerprints", {})
        divergence = any(
            br_fp.get(k) != bot_fp.get(k) 
            for k in ["cloudflare_challenge", "captcha", "generic_block", "login_wall", "thin_content"]
        )
        comparison["fingerprint_divergence"] = divergence
    
    br_fp = browser_result.get("content_fingerprints", {})
    bot_fp = bot_result.get("content_fingerprints", {})
    bot_blocked = (bot_status in [401, 403]) or bot_fp.get("generic_block", False)
    # Only flag as challenged when the challenge is bot-specific (divergence from browser).
    # Shared challenges (e.g. contact-form reCAPTCHA visible to both browser and bot) are NOT bot blocks.
    bot_challenged = (
        (bot_fp.get("cloudflare_challenge", False) and not br_fp.get("cloudflare_challenge", False))
        or
        (bot_fp.get("captcha", False) and not br_fp.get("captcha", False))
    )
    rate_limited = (bot_status == 429) or (browser_status == 429)

    return {
        "url": url,
        # Explicit, so nothing downstream can mistake "we were not allowed to
        # look" for "we looked and the page was empty".
        "robots_skipped_browser_fetch": bool(browser_decision is not None and not browser_decision.allowed),
        "robots_skipped_bot_fetch": bool(bot_decision is not None and not bot_decision.allowed),
        "robots_decisions": {
            "browser": browser_decision.as_dict() if browser_decision is not None else None,
            "bot": bot_decision.as_dict() if bot_decision is not None else None,
        },
        "browser_status": browser_status,
        "bot_status": bot_status,
        "bot_blocked": bot_blocked,
        "bot_challenged": bot_challenged,
        "rate_limited": rate_limited,
        "browser_fetch": browser_result,
        "bot_fetch": bot_result,
        "comparison_metrics": comparison
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
        target_url = None
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    target_url = params.get("url") or params.get("domain")
                except json.JSONDecodeError:
                    target_url = raw_arg
            else:
                target_url = raw_arg

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not target_url:
            target_url = params.get("url") or params.get("domain") or "https://example.com"

        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "https://" + target_url

        browser_ua = params.get("browser_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        bot_ua = params.get("bot_user_agent", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)")

        # `robots`: check_robots.py output (or raw robots.txt text) so the
        # gate reuses the already-fetched file instead of requesting it again.
        result = dual_fetch(target_url, browser_ua, bot_ua, robots=params.get("robots"))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
