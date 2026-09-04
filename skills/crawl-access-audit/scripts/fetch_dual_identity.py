import sys
import json
import time
import html.parser

# Handle requests import safely
try:
    import requests
    from requests.exceptions import RequestException, Timeout
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

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
        
        # Parse HTML for login wall and thin content
        parser = TextExtractor()
        parser_error = None
        try:
            parser.feed(html_content)
        except Exception as e:
            parser_error = str(e)
            
        visible_text = parser.get_text()
        visible_text_len = len(visible_text)
        
        # 3. Thin content
        is_thin = visible_text_len < thin_threshold
        
        # 4. Login wall
        login_wall = False
        if parser.has_form and parser.has_password_input and is_thin:
            login_wall = True
            
        return {
            "cloudflare_challenge": bool(cf_matches),
            "cloudflare_signals": cf_matches,
            "captcha": bool(captcha_matches),
            "captcha_signals": captcha_matches,
            "login_wall": login_wall,
            "thin_content": is_thin,
            "visible_text_length": visible_text_len,
            "_fingerprint_error": parser_error
        }
    except Exception as e:
        # Fallback to safe defaults on catastrophic failure, but surface the error for debugging
        return {
            "cloudflare_challenge": False,
            "cloudflare_signals": [],
            "captcha": False,
            "captcha_signals": [],
            "login_wall": False,
            "thin_content": False,
            "visible_text_length": 0,
            "_fingerprint_error": f"Fatal analysis error: {str(e)}"
        }

def fetch_url(url, user_agent, timeout=10):
    start_time = time.time()
    default_fingerprints = {
        "cloudflare_challenge": False, "cloudflare_signals": [], "captcha": False, "captcha_signals": [], 
        "login_wall": False, "thin_content": False, "visible_text_length": 0, "_fingerprint_error": None
    }
    
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout, allow_redirects=True)
        response_time = time.time() - start_time
        
        content = resp.text if resp.text else ""
        fingerprints = analyze_fingerprints(content)
        
        # Cap size AFTER analysis.
        MAX_CONTENT_LEN = 500 * 1024
        if len(content) > MAX_CONTENT_LEN:
            content = content[:MAX_CONTENT_LEN] + "\n...[TRUNCATED]"
            
        return {
            "status": resp.status_code,
            "final_url": resp.url,
            "redirect_count": len(resp.history),
            "response_time": round(response_time, 3),
            "response_headers": dict(resp.headers),
            "content": content,
            "content_fingerprints": fingerprints,
            "error": None
        }
    except Timeout:
        return {
            "status": "timeout", "final_url": None, "redirect_count": 0,
            "response_time": round(time.time() - start_time, 3),
            "response_headers": {}, "content": "",
            "content_fingerprints": default_fingerprints, "error": "Request timed out"
        }
    except RequestException as e:
        return {
            "status": None, "final_url": None, "redirect_count": 0,
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
            for k in ["cloudflare_challenge", "captcha", "login_wall", "thin_content"]
        )
        comparison["fingerprint_divergence"] = divergence
    
    return {
        "url": url,
        "browser_fetch": browser_result,
        "bot_fetch": bot_result,
        "comparison_metrics": comparison
    }

if __name__ == "__main__":
    try:
        if not REQUESTS_AVAILABLE:
            print(json.dumps({"error": "could not verify — tool unavailable (requests library missing)"}))
            sys.exit(0)
            
        if len(sys.argv) < 2:
            print(json.dumps({"error": "Missing URL argument"}))
            sys.exit(0)
            
        url = sys.argv[1]
        
        input_data = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        try:
            params = json.loads(input_data) if input_data.strip() else {}
        except json.JSONDecodeError:
            params = {}
            
        browser_ua = params.get("browser_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        bot_ua = params.get("bot_user_agent", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)")
        
        result = dual_fetch(url, browser_ua, bot_ua)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
