import sys
import json
import re
import os
from html.parser import HTMLParser

def load_thresholds():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_path = os.path.join(script_dir, "..", "references", "reachability_thresholds.json")
    default = {
        "product": {"min_word_count": 200, "recommended_word_count": 500},
        "service": {"min_word_count": 300, "recommended_word_count": 800},
        "article": {"min_word_count": 600, "recommended_word_count": 1500},
        "unknown": {"min_word_count": None, "recommended_word_count": None}
    }
    try:
        if os.path.exists(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

class TextAndHeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_tokens = []
        self.skip_tags = {'script', 'style', 'noscript', 'iframe'}
        self.in_skip_tag = False
        self.current_skip_tag = None
        
        # Heading & paragraph tracking
        self.heading_pairs = []
        self.current_heading_level = None
        self.current_heading_text = []
        self.capture_heading_text = False
        
        self.capture_paragraph_text = False
        self.current_paragraph_text = []
        self.pending_heading = None

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in self.skip_tags and not self.in_skip_tag:
            self.in_skip_tag = True
            self.current_skip_tag = tag_lower
            return

        if self.in_skip_tag:
            return

        if tag_lower in ['h2', 'h3']:
            if len(self.heading_pairs) < 5:
                self.capture_heading_text = True
                self.current_heading_level = tag_lower
                self.current_heading_text = []
        elif tag_lower == 'p':
            if self.pending_heading and len(self.heading_pairs) < 5:
                self.capture_paragraph_text = True
                self.current_paragraph_text = []

    def handle_data(self, data):
        if not self.in_skip_tag and data:
            stripped = data.strip()
            if stripped:
                self.text_tokens.append(stripped)

            if self.capture_heading_text and stripped:
                self.current_heading_text.append(stripped)

            if self.capture_paragraph_text and stripped:
                self.current_paragraph_text.append(stripped)

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self.in_skip_tag and tag_lower == self.current_skip_tag:
            self.in_skip_tag = False
            self.current_skip_tag = None
            return

        if self.in_skip_tag:
            return

        if tag_lower in ['h2', 'h3'] and self.capture_heading_text:
            self.capture_heading_text = False
            heading_str = " ".join(self.current_heading_text).strip()
            if heading_str:
                self.pending_heading = heading_str
            self.current_heading_text = []
        elif tag_lower == 'p' and self.capture_paragraph_text:
            self.capture_paragraph_text = False
            p_str = " ".join(self.current_paragraph_text).strip()
            if self.pending_heading and p_str:
                self.heading_pairs.append({
                    "heading_text": self.pending_heading,
                    "followup_text": p_str
                })
                self.pending_heading = None
            self.current_paragraph_text = []

def check_content_depth(html_content, url, page_type_hint="unknown"):
    if not html_content:
        html_content = ""

    page_type_hint = str(page_type_hint or "unknown").lower().strip()
    if page_type_hint not in ["product", "service", "article", "unknown"]:
        page_type_hint = "unknown"

    parser = TextAndHeadingParser()
    try:
        if html_content:
            parser.feed(html_content)
    except Exception:
        pass

    full_text = " ".join(parser.text_tokens)
    words = [w for w in re.split(r'\s+', full_text) if w]
    visible_word_count = len(words)

    thresholds = load_thresholds()
    type_info = thresholds.get(page_type_hint, {})
    min_words = type_info.get("min_word_count")

    below_reference_range = None
    if page_type_hint != "unknown" and min_words is not None:
        below_reference_range = visible_word_count < min_words

    return {
        "url": url,
        "page_type_hint": page_type_hint,
        "visible_word_count": visible_word_count,
        "reference_min_word_count": min_words,
        "below_reference_range": below_reference_range,
        "heading_followup_text_pairs": parser.heading_pairs[:5]
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
        html_content = ""
        url = ""
        page_type_hint = "unknown"
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html_content = params.get("html", "")
                    url = params.get("url", "")
                    page_type_hint = params.get("page_type_hint", "unknown")
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

        if not html_content:
            html_content = params.get('html', '')
        if not url:
            url = params.get('url', '')
        if page_type_hint == "unknown":
            page_type_hint = params.get('page_type_hint', 'unknown')

        result = check_content_depth(html_content, url, page_type_hint)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "page_type_hint": "unknown",
            "visible_word_count": 0,
            "reference_min_word_count": None,
            "below_reference_range": None,
            "heading_followup_text_pairs": [],
            "script_error": str(e)
        }))
