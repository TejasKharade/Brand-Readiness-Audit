import sys
import json
import re
from html.parser import HTMLParser

class RedirectParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta_refreshes = []
        self.script_blocks = []
        self.in_script = False
        self.current_script_text = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == 'meta':
            attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
            if attrs_dict.get('http-equiv', '').lower() == 'refresh':
                content = attrs_dict.get('content', '')
                self.meta_refreshes.append(content)
        elif tag_lower == 'script':
            attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
            script_type = attrs_dict.get('type', '').lower()
            # Only include executable JS scripts (exclude application/ld+json, templates, etc.)
            if not script_type or 'javascript' in script_type or script_type in ('text/ecmascript', 'module'):
                self.in_script = True
                self.current_script_text = []

    def handle_data(self, data):
        if self.in_script and data:
            self.current_script_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.in_script:
            full_script = "".join(self.current_script_text)
            if full_script.strip():
                self.script_blocks.append(full_script)
            self.in_script = False
            self.current_script_text = []

def check_client_side_redirects(raw_html, url):
    parser = RedirectParser()
    try:
        parser.feed(raw_html or '')
    except Exception:
        pass

    combined_scripts = "\n".join(parser.script_blocks)

    # Detect window.location / location.href / location.replace JS redirects strictly in script blocks
    js_redirect_patterns = [
        r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        r'location\.replace\s*\(\s*["\']([^"\']+)["\']\s*\)',
        r'location\.assign\s*\(\s*["\']([^"\']+)["\']\s*\)'
    ]

    detected_js_redirects = []
    for pat in js_redirect_patterns:
        matches = re.findall(pat, combined_scripts, re.IGNORECASE)
        for m in matches:
            if m not in detected_js_redirects:
                detected_js_redirects.append(m)

    has_redirect = bool(parser.meta_refreshes or detected_js_redirects)

    return {
        'client_side_redirect_detected': has_redirect,
        'meta_http_equiv_refreshes': parser.meta_refreshes,
        'js_location_redirects': detected_js_redirects
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

if __name__ == '__main__':
    try:
        raw_html = ""
        url = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    raw_html = params.get("raw_html", "") or params.get("html", "")
                    url = params.get("url", "")
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

        if not raw_html:
            raw_html = params.get('raw_html', '') or params.get('html', '')
        if not url:
            url = params.get('url', '')

        result = check_client_side_redirects(raw_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
