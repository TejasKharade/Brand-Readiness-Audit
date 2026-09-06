import sys
import json
import re
from html.parser import HTMLParser

class SimpleTextAndHeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words = []
        self.headings = [] # list of {level, text}
        self.skip_tags = {'script', 'style', 'noscript', 'iframe', 'svg'}
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.in_skip = False
        self.current_skip_tag = None
        self.current_heading_level = None
        self.current_heading_text = []
        self.hidden_depth = 0
        self.spa_mount_points = []
        self.detected_frameworks = set()

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
        
        # Check hidden CSS attributes
        style_attr = attrs_dict.get('style', '').lower()
        is_hidden = ('hidden' in attrs_dict or
                     attrs_dict.get('aria-hidden', '').lower() == 'true' or
                     'display:none' in style_attr.replace(' ', '') or
                     'visibility:hidden' in style_attr.replace(' ', ''))
        
        # HTML5 void elements do not trigger handle_endtag, so exclude them from hidden_depth tracking
        if tag_lower not in self.void_tags:
            if is_hidden or self.hidden_depth > 0:
                self.hidden_depth += 1

        if tag_lower in self.skip_tags and not self.in_skip:
            self.in_skip = True
            self.current_skip_tag = tag_lower

        # Heading detection
        if re.match(r'^h[1-6]$', tag_lower):
            self.current_heading_level = int(tag_lower[1])
            self.current_heading_text = []

        # SPA Root Mount Point Detection
        element_id = attrs_dict.get('id', '')
        if element_id.lower() in ['root', 'app', '__next', '__nuxt', 'app-root', 'react-root']:
            self.spa_mount_points.append(f"{tag_lower}#{element_id.lower()}")

        # SSR Data Island script detection
        if element_id in ['__NEXT_DATA__', '__NUXT__', '__STATE__', '__INITIAL_STATE__']:
            self.detected_frameworks.add(f'SSR Data Island ({element_id})')

        # Script tag framework detection
        if tag_lower == 'script':
            src = attrs_dict.get('src', '').lower()
            if 'react' in src or 'next' in src:
                self.detected_frameworks.add('React/Next.js')
            elif 'vue' in src or 'nuxt' in src:
                self.detected_frameworks.add('Vue/Nuxt')
            elif 'angular' in src:
                self.detected_frameworks.add('Angular')
            elif 'svelte' in src:
                self.detected_frameworks.add('Svelte')
            elif 'webpack' in src or 'chunk' in src or 'bundle' in src:
                self.detected_frameworks.add('Client-Side JS Bundle')

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self.in_skip and tag_lower == self.current_skip_tag:
            self.in_skip = False
            self.current_skip_tag = None

        if re.match(r'^h[1-6]$', tag_lower) and self.current_heading_level is not None:
            text = ' '.join(''.join(self.current_heading_text).split())
            if text and self.hidden_depth == 0:
                self.headings.append({
                    'level': self.current_heading_level,
                    'text': text
                })
            self.current_heading_level = None
            self.current_heading_text = []

        if tag_lower not in self.void_tags and self.hidden_depth > 0:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if self.current_heading_level is not None and self.hidden_depth == 0:
            self.current_heading_text.append(data)
        if not self.in_skip and self.hidden_depth == 0 and data.strip():
            words = re.findall(r'\w+', data)
            self.words.extend(words)

def parse_html_stats(html_content):
    parser = SimpleTextAndHeadingParser()
    try:
        parser.feed(html_content or '')
    except Exception:
        pass
    return {
        'word_count': len(parser.words),
        'headings': parser.headings,
        'spa_mount_points': parser.spa_mount_points,
        'detected_frameworks': list(parser.detected_frameworks)
    }

def check_rendering_barriers(raw_html, rendered_html, url):
    raw_stats = parse_html_stats(raw_html)
    has_rendered = bool(rendered_html and rendered_html.strip())
    rendered_stats = parse_html_stats(rendered_html) if has_rendered else None

    raw_words = raw_stats['word_count']
    rendered_words = rendered_stats['word_count'] if rendered_stats else raw_words
    
    # Calculate hydration content ratio
    hydration_ratio = round(raw_words / max(rendered_words, 1), 2) if has_rendered else 1.0
    thin_initial_content = (hydration_ratio < 0.30) or (has_rendered and raw_words < 50 and rendered_words > 300)

    # Heading hydration gap comparison
    raw_heading_texts = {h['text'].lower() for h in raw_stats['headings']}
    missing_initial_headings = []
    
    if rendered_stats:
        for rh in rendered_stats['headings']:
            if rh['text'].lower() not in raw_heading_texts:
                missing_initial_headings.append(rh)

    # SPA Client-Side Rendering Flags
    is_spa_likely = bool(raw_stats['spa_mount_points'] or raw_stats['detected_frameworks']) and (raw_words < 150)

    return {
        'has_rendered_comparison': has_rendered,
        'word_counts': {
            'initial_raw_words': raw_words,
            'rendered_dom_words': rendered_words if has_rendered else None,
            'hydration_ratio': hydration_ratio if has_rendered else None
        },
        'hydration_gaps': {
            'thin_initial_content_detected': thin_initial_content,
            'missing_initial_headings_count': len(missing_initial_headings),
            'missing_initial_headings': missing_initial_headings
        },
        'client_side_rendering_signals': {
            'spa_mount_points': raw_stats['spa_mount_points'],
            'detected_frameworks': raw_stats['detected_frameworks'],
            'likely_client_side_rendering_barrier': is_spa_likely or thin_initial_content
        }
    }

if __name__ == '__main__':
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}
            
        raw_html = params.get('raw_html', '') or params.get('html', '')
        rendered_html = params.get('rendered_html', '')
        url = params.get('url', '')
        
        result = check_rendering_barriers(raw_html, rendered_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
