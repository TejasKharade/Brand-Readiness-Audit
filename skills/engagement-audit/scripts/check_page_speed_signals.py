import sys
import json
import re
import html.parser

class SpeedSignalParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_count = 0
        self.external_scripts = 0
        self.inline_scripts = 0
        self.stylesheet_count = 0
        self.inline_style_bytes = 0
        self.image_count = 0
        self.images_without_lazy = 0
        self.total_nodes = 0

    def handle_starttag(self, tag, attrs):
        self.total_nodes += 1
        attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
        
        if tag == "script":
            self.script_count += 1
            if "src" in attrs_dict:
                self.external_scripts += 1
            else:
                self.inline_scripts += 1
        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            if "stylesheet" in rel:
                self.stylesheet_count += 1
        elif tag == "style":
            pass
        elif tag == "img":
            self.image_count += 1
            loading = attrs_dict.get("loading", "").lower()
            if loading != "lazy":
                self.images_without_lazy += 1

    def handle_data(self, data):
        if self.lasttag == "style" and data:
            self.inline_style_bytes += len(data.encode('utf-8'))

def check_page_speed_signals(html_content, url):
    if not html_content:
        html_content = ""

    html_bytes = len(html_content.encode('utf-8'))
    html_kb = round(html_bytes / 1024.0, 2)

    parser = SpeedSignalParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    # Performance risk thresholds
    is_heavy_html = html_kb > 200.0  # >200KB initial HTML
    has_excessive_scripts = parser.external_scripts > 15
    has_unoptimized_images = parser.image_count > 5 and (parser.images_without_lazy / parser.image_count) > 0.5
    has_heavy_dom = parser.total_nodes > 1500

    return {
        "url": url,
        "payload_size_kb": html_kb,
        "is_heavy_html_payload": is_heavy_html,
        "dom_metrics": {
            "estimated_dom_nodes": parser.total_nodes,
            "has_heavy_dom": has_heavy_dom
        },
        "resource_counts": {
            "total_scripts": parser.script_count,
            "external_scripts": parser.external_scripts,
            "inline_scripts": parser.inline_scripts,
            "stylesheets": parser.stylesheet_count,
            "inline_style_kb": round(parser.inline_style_bytes / 1024.0, 2),
            "total_images": parser.image_count,
            "images_without_lazy_loading": parser.images_without_lazy
        },
        "performance_friction_risks": {
            "excessive_external_scripts": has_excessive_scripts,
            "unoptimized_image_loading": has_unoptimized_images,
            "heavy_html_payload": is_heavy_html,
            "excessive_dom_nodes": has_heavy_dom
        }
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        html_content = params.get('html', '')
        url = params.get('url', '')

        result = check_page_speed_signals(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
