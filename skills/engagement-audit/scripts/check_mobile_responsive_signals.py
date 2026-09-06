import sys
import json
import re
from html.parser import HTMLParser

class ResponsiveSignalParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.viewport_present = False
        self.viewport_content = None
        self.inline_style_blocks = []
        self.in_style_tag = False
        self.current_style_text = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
        
        if tag_lower == "meta":
            name = attrs_dict.get("name", "").lower()
            if name == "viewport":
                self.viewport_present = True
                self.viewport_content = attrs_dict.get("content")
        elif tag_lower == "style":
            self.in_style_tag = True
            self.current_style_text = []

    def handle_data(self, data):
        if self.in_style_tag and data:
            self.current_style_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "style" and self.in_style_tag:
            self.in_style_tag = False
            full_style = "".join(self.current_style_text)
            if full_style.strip():
                self.inline_style_blocks.append(full_style)
            self.current_style_text = []

def check_mobile_responsive_signals(html_content):
    if not html_content:
        html_content = ""

    parser = ResponsiveSignalParser()
    try:
        if html_content:
            parser.feed(html_content)
    except Exception:
        pass

    inline_media_found = False
    combined_styles = "\n".join(parser.inline_style_blocks)
    if "@media" in combined_styles.lower():
        inline_media_found = True

    both_absent = (not parser.viewport_present) and (not inline_media_found)

    return {
        "viewport_meta_present": parser.viewport_present,
        "viewport_meta_content": parser.viewport_content,
        "inline_media_queries_found": inline_media_found,
        "viewport_and_media_query_both_absent": both_absent,
        "note": "Inline @media query check is a weak, incomplete signal because most external stylesheets are uninspected."
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
        params = {}
        html_content = ""

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html_content = params.get("html", "")
                except json.JSONDecodeError:
                    html_content = raw_arg
            else:
                html_content = raw_arg

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=0.2)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
                    if not html_content:
                        html_content = params.get("html", "")
            except json.JSONDecodeError:
                if not html_content:
                    html_content = input_data

        result = check_mobile_responsive_signals(html_content)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "viewport_meta_present": False,
            "viewport_meta_content": None,
            "inline_media_queries_found": False,
            "viewport_and_media_query_both_absent": True,
            "note": "Inline @media query check is a weak, incomplete signal because most external stylesheets are uninspected.",
            "script_error": str(e)
        }))
