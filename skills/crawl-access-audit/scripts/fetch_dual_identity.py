import sys
import json
import time
import html.parser
import urllib.request
import urllib.error
import socket
import ssl

# Default starting threshold for thin content. 
THIN_CONTENT_THRESHOLD = 300 

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
        self.text = []
        self.has_password_input = False
        self.has_form = False
        self.skip_tags = {'script', 'style', 'noscript', 'iframe'}
        self.in_skip_tag = False
        self.current_skip_tag = None
        
    def handle_data(self, data):
        if not self.in_skip_tag and data and data.strip():
            self.text.append(data.strip())
            
    def handle_starttag(self, tag, attrs):
        try:
            if tag in self.skip_tags and not self.in_skip_tag:
                self.in_skip_tag = True
                self.current_skip_tag = tag
            if tag == "form":
                self.has_form = True
            if tag == "input":
                attrs_dict = dict(attrs)
                if attrs_dict.get("type", "").lower() == "password":
                    self.has_password_input = True
        except Exception:
            pass
            
    def handle_endtag(self, tag):
        if self.in_skip_tag and tag == self.current_skip_tag:
            self.in_skip_tag = False
            self.current_skip_tag = None
                
    def get_text(self):
        return " ".join(self.text)

def analyze_fingerprints(html_content, thin_threshold=THIN_CONTENT_THRESHOLD):
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
        
        # 4. Thin content
        is_thin = visible_text_len < thin_threshold
        
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
            "visible_text_length": visible_text_len,
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
            "visible_text_length": 0,
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

def fetch_url(url, user_agent, timeout=10):
    start_time = time.time()
    default_fingerprints = {
        "cloudflare_challenge": False, "cloudflare_signals": [], "captcha": False, "captcha_signals": [], 
        "generic_block": False, "generic_block_signals": [],
        "login_wall": False, "thin_content": False, "visible_text_length": 0, "_fingerprint_error": None
    }
    
    tracker = RedirectTracker()
    opener = urllib.request.build_opener(tracker)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    
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

def dual_fetch(url, browser_ua, bot_ua, delay=2.0, timeout=10):
    browser_result = fetch_url(url, browser_ua, timeout=timeout)
    try:
        time.sleep(delay)
    except Exception:
        pass
    bot_result = fetch_url(url, bot_ua, timeout=timeout)
    
    comparison = {}
    if browser_result.get("status") and bot_result.get("status"):
        comparison["status_match"] = browser_result["status"] == bot_result["status"]
        comparison["length_diff_bytes"] = abs(len(browser_result.get("content", "")) - len(bot_result.get("content", "")))
        
        br_fp = browser_result.get("content_fingerprints", {})
        bot_fp = bot_result.get("content_fingerprints", {})
        divergence = any(
            br_fp.get(k) != bot_fp.get(k) 
            for k in ["cloudflare_challenge", "captcha", "generic_block", "login_wall", "thin_content"]
        )
        comparison["fingerprint_divergence"] = divergence
    
    return {
        "url": url,
        "browser_fetch": browser_result,
        "bot_fetch": bot_result,
        "comparison_metrics": comparison
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

        input_data = read_stdin_safe(timeout=0.2)
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

        result = dual_fetch(target_url, browser_ua, bot_ua)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
