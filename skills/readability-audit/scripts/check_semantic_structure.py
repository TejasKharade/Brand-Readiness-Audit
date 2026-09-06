import sys
import json
import re
from html.parser import HTMLParser

class SemanticStructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_text = []
        self.in_title = False
        self.meta_description = None
        self.headings = [] # list of dicts: {level, text, tag_index, is_aria}
        self.current_heading_level = None
        self.current_heading_is_aria = False
        self.current_heading_text = []
        
        self.main_count = 0
        self.article_count = 0
        self.nav_count = 0
        self.section_count = 0
        self.ul_count = 0
        self.ol_count = 0
        self.table_count = 0
        self.div_count = 0
        self.picture_count = 0
        self.svg_count = 0
        
        self.visible_words = []
        self.skip_tags = {'script', 'style', 'noscript', 'iframe'}
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.in_skip = False
        self.current_skip_tag = None
        self.tag_index = 0
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        self.tag_index += 1
        attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
        
        # Check hidden attributes (CSS display:none / visibility:hidden / hidden attribute / aria-hidden=true)
        style_attr = attrs_dict.get('style', '').lower()
        is_hidden = ('hidden' in attrs_dict or
                     attrs_dict.get('aria-hidden', '').lower() == 'true' or
                     'display:none' in style_attr.replace(' ', '') or
                     'visibility:hidden' in style_attr.replace(' ', ''))
        
        if tag_lower not in self.void_tags:
            if is_hidden or self.hidden_depth > 0:
                self.hidden_depth += 1

        if tag_lower in self.skip_tags and not self.in_skip:
            self.in_skip = True
            self.current_skip_tag = tag_lower

        if tag_lower == 'title':
            self.in_title = True
            self.title_text = []
        elif tag_lower == 'meta':
            if attrs_dict.get('name', '').lower() == 'description':
                self.meta_description = attrs_dict.get('content', '')
                
        # Native or ARIA Headings
        role = attrs_dict.get('role', '').lower()
        if re.match(r'^h[1-6]$', tag_lower):
            self.current_heading_level = int(tag_lower[1])
            self.current_heading_is_aria = False
            self.current_heading_text = []
        elif role == 'heading':
            aria_level = attrs_dict.get('aria-level')
            try:
                lvl = int(aria_level) if aria_level else 2
            except ValueError:
                lvl = 2
            self.current_heading_level = lvl
            self.current_heading_is_aria = True
            self.current_heading_text = []

        # Native Tag or ARIA Role Counts
        if tag_lower == 'main' or role == 'main':
            self.main_count += 1
        if tag_lower == 'article' or role == 'article':
            self.article_count += 1
        if tag_lower == 'nav' or role == 'navigation':
            self.nav_count += 1
        if tag_lower == 'section' or role == 'region':
            self.section_count += 1
        if tag_lower == 'ul':
            self.ul_count += 1
        if tag_lower == 'ol':
            self.ol_count += 1
        if tag_lower == 'table':
            self.table_count += 1
        if tag_lower == 'div':
            self.div_count += 1
        if tag_lower == 'picture':
            self.picture_count += 1
        if tag_lower == 'svg':
            self.svg_count += 1

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self.in_skip and tag_lower == self.current_skip_tag:
            self.in_skip = False
            self.current_skip_tag = None

        if tag_lower == 'title':
            self.in_title = False
        elif (re.match(r'^h[1-6]$', tag_lower) or self.current_heading_is_aria) and self.current_heading_level is not None:
            text = ' '.join(''.join(self.current_heading_text).split())
            if text and self.hidden_depth == 0:
                self.headings.append({
                    'level': self.current_heading_level,
                    'text': text,
                    'tag_index': self.tag_index,
                    'is_aria': self.current_heading_is_aria
                })
            self.current_heading_level = None
            self.current_heading_is_aria = False
            self.current_heading_text = []

        if tag_lower not in self.void_tags and self.hidden_depth > 0:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title_text.append(data)
        if self.current_heading_level is not None and self.hidden_depth == 0:
            self.current_heading_text.append(data)
        if not self.in_skip and self.hidden_depth == 0 and data.strip():
            words = re.findall(r'\w+', data)
            self.visible_words.extend(words)

def check_semantic_structure(html_content, url):
    parser = SemanticStructureParser()
    try:
        parser.feed(html_content or '')
    except Exception:
        pass

    title_str = ' '.join(''.join(parser.title_text).split()) if parser.title_text else None
    h1_count = sum(1 for h in parser.headings if h['level'] == 1)
    
    skipped_levels = []
    if parser.headings:
        prev_level = 0
        for idx, h in enumerate(parser.headings):
            curr_level = h['level']
            if prev_level > 0 and curr_level > prev_level + 1:
                skipped_levels.append({
                    'index': idx,
                    'from_level': prev_level,
                    'to_level': curr_level,
                    'heading_text': h['text']
                })
            prev_level = curr_level

    return {
        'title': {
            'present': bool(title_str),
            'text': title_str
        },
        'meta_description': {
            'present': parser.meta_description is not None,
            'text': parser.meta_description
        },
        'headings': {
            'total_count': len(parser.headings),
            'h1_count': h1_count,
            'sequence': parser.headings,
            'skipped_levels': skipped_levels
        },
        'semantic_elements': {
            'main_count': parser.main_count,
            'article_count': parser.article_count,
            'nav_count': parser.nav_count,
            'section_count': parser.section_count,
            'ul_count': parser.ul_count,
            'ol_count': parser.ol_count,
            'table_count': parser.table_count,
            'div_count': parser.div_count,
            'picture_count': parser.picture_count,
            'svg_count': parser.svg_count
        },
        'visible_text_word_count': len(parser.visible_words)
    }

if __name__ == '__main__':
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}
            
        html_content = params.get('html', '')
        url = params.get('url', '')
        
        result = check_semantic_structure(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
