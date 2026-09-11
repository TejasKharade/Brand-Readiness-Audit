
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
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

    # --- Meta refresh: only a redirect when the content carries a url= target.
    # `<meta http-equiv="refresh" content="600">` (periodic same-page refresh)
    # is NOT a redirect and must not be flagged as one.
    meta_refresh_redirects = []
    meta_refresh_noop = []
    for content in parser.meta_refreshes:
        m = re.search(r'url\s*=\s*[\'"]?([^\'";]+)', content or "", re.IGNORECASE)
        if m:
            meta_refresh_redirects.append(m.group(1).strip())
        else:
            meta_refresh_noop.append((content or "").strip())

    # --- JS hard redirects: string-literal targets on any location accessor
    # (window/document/top/self/parent + bare `location`).
    _loc = r'(?:(?:window|document|top|self|parent)\s*\.\s*)?location'
    js_redirect_patterns = [
        rf'{_loc}\s*\.\s*href\s*=\s*["\']([^"\']+)["\']',
        rf'{_loc}\s*=\s*["\']([^"\']+)["\']',
        rf'{_loc}\s*\.\s*(?:replace|assign)\s*\(\s*["\']([^"\']+)["\']\s*\)',
    ]
    detected_js_redirects = []
    for pat in js_redirect_patterns:
        for m in re.findall(pat, combined_scripts, re.IGNORECASE):
            if m not in detected_js_redirects:
                detected_js_redirects.append(m)

    has_redirect = bool(meta_refresh_redirects or detected_js_redirects)

    # Flaw 14: SPA client-side routing APIs (soft signal — not a hard redirect).
    # (compiled pattern, human-readable label) so the output never leaks regex.
    spa_routing_patterns = [
        (re.compile(r'history\.(?:pushState|replaceState)\s*\(', re.I), 'History API pushState/replaceState'),
        (re.compile(r'this\.\$router\.(?:push|replace)\s*\(', re.I),   'Vue Router push/replace'),
        (re.compile(r'\brouter\.navigate\s*\(', re.I),                 'Angular Router navigate()'),
        (re.compile(r'\bnavigate\s*\(\s*["\'/]', re.I),                'React Router navigate()'),
        (re.compile(r'\buseNavigate\s*\(\s*\)', re.I),                 'React Router useNavigate hook'),
        (re.compile(r'\buseHistory\s*\(\s*\)', re.I),                  'React Router useHistory hook'),
        (re.compile(r'<(?:Router|BrowserRouter|HashRouter|MemoryRouter)\b'), 'React Router component'),
        (re.compile(r'createBrowserRouter|createHashRouter'),          'React Router v6 data router'),
        (re.compile(r'RouterModule\.forRoot', re.I),                   'Angular RouterModule'),
        (re.compile(r'\bvue-router\b|\bVueRouter\b'),                  'Vue Router'),
    ]
    spa_routing_signals = [label for pat, label in spa_routing_patterns
                           if pat.search(combined_scripts)]

    return {
        'client_side_redirect_detected': has_redirect,
        'meta_http_equiv_refreshes': meta_refresh_redirects,
        'meta_refresh_noop_no_url': meta_refresh_noop,
        'js_location_redirects': detected_js_redirects,
        'spa_client_routing_detected': bool(spa_routing_signals),
        'spa_client_routing_signals': spa_routing_signals[:5],
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

        input_data = read_stdin_safe(timeout=5.0)
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
