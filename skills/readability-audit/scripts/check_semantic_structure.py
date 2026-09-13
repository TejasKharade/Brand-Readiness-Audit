
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
from html.parser import HTMLParser

# --- Content-block boundaries ------------------------------------------------
# Any of these tags starting OR ending flushes whatever text has been
# accumulating and starts a fresh "block". This mirrors crawl-render-audit's
# proven TEXT_BLOCK_TAGS approach and for the same two reasons: it correctly
# handles nesting (<li><p>text</p></li> still produces exactly one block, not
# two -- flushing on every boundary regardless of depth means there is never a
# stack to merge), and it correctly handles text with no wrapping tag at all
# (loose text directly inside <body> or <div>, common on older or simpler
# markup) -- a leaf-tag-only approach would silently miss that text entirely.
BLOCK_BOUNDARY_TAGS = {
    "p", "div", "section", "article", "main", "header", "footer", "nav", "aside",
    "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "td", "th", "form",
    "fieldset", "figure", "figcaption", "blockquote", "pre", "hr", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "address", "details", "summary",
}

CHROME_TAGS = {"nav", "header", "footer", "aside"}
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}

# A "you need JavaScript" fallback notice is markup furniture, not page
# content -- but it lives in a plain <div>, not a <noscript>, on plenty of real
# sites (python.org ships `<div id="nojs">Notice: This page displays a
# fallback...`), so the skip_tags list never caught it and it was being picked
# as the page's FIRST SUBSTANTIAL CONTENT BLOCK for the positioning check.
#
# Matched on id / class TOKEN only, and never on <html> or <body>: the
# Modernizr convention puts `class="no-js"` on the <html> element itself, and
# treating that as chrome would silently exclude the entire document.
NOJS_NOTICE_IDS = {"nojs", "no-js", "js-disabled", "javascript-disabled",
                   "js-warning", "noscript-warning", "browser-not-supported"}
NOJS_NOTICE_CLASSES = {"nojs-message", "no-js-message", "js-disabled-message",
                       "noscript-message", "javascript-required"}

# Tier 1 (high confidence): ends in a question mark -- ASCII "?" (English,
# Spanish, French, German, ...) or Arabic "؟" (U+061F).
_QUESTION_MARK_CHARS = ("?", "؟")

# Tier 2 (weaker): opens with a common English interrogative word, matched as
# a whole word so "Isaac Newton's Legacy" does not match "Is". English-only by
# construction -- a heading in another language that doesn't also end in a
# question mark is simply not detected as a question. That is a missed
# detection, never a wrong one: it reduces recall on non-English content
# without ever producing a false claim, which is the honest limit of a
# dependency-free, stdlib-only check.
_QUESTION_WORD_RX = re.compile(
    r"^(what|how|why|when|where|who|which|whom|whose|is|are|can|could|does|do|"
    r"did|should|will|would|may|might)\b", re.IGNORECASE)

# Deliberately lenient: this checks PRESENCE, not quality. "No." is a
# complete, valid single-word FAQ answer -- requiring more than that would
# misfire on exactly the short-answer style that is extremely common across
# real FAQ sections on almost every kind of site. Only a heading with
# genuinely nothing (or only another heading) after it is flagged; any real
# block, however short, counts as answered.
ANSWER_PRESENCE_MIN_WORDS = 1

SUBSTANTIAL_BLOCK_MIN_WORDS = 12     # long enough to be a real sentence or two
MIN_MAIN_WORDS_FOR_POSITIONING = 80  # below this, "position in the document" is meaningless
FRONT_LOADED_FRACTION_THRESHOLD = 0.30


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

        # Content-block tracking for question-heading/content-positioning
        # checks. chrome_depth mirrors hidden_depth's exact nesting mechanics
        # (increments on any tag while already inside chrome, decrements on
        # any closing tag while still inside) so nav-menu text and footer
        # boilerplate never count as "the answer" or "the main content".
        self.chrome_depth = 0
        self.blocks = []          # [{'tag_index': int, 'text': str}], document order
        self._current_chunk = []

    def _flush_block(self):
        text = ' '.join(''.join(self._current_chunk).split())
        if text:
            self.blocks.append({'tag_index': self.tag_index, 'text': text})
        self._current_chunk = []

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

        if tag_lower in BLOCK_BOUNDARY_TAGS:
            self._flush_block()

        is_chrome_tag = tag_lower in CHROME_TAGS or attrs_dict.get('role', '').lower() in CHROME_ROLES
        if tag_lower not in ('html', 'body'):
            el_id = attrs_dict.get('id', '').strip().lower()
            el_classes = set(attrs_dict.get('class', '').lower().split())
            if el_id in NOJS_NOTICE_IDS or (el_classes & NOJS_NOTICE_CLASSES):
                is_chrome_tag = True
        if tag_lower not in self.void_tags:
            if is_chrome_tag or self.chrome_depth > 0:
                self.chrome_depth += 1

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
        if tag_lower in BLOCK_BOUNDARY_TAGS:
            self._flush_block()

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
        if tag_lower not in self.void_tags and self.chrome_depth > 0:
            self.chrome_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title_text.append(data)
        if self.current_heading_level is not None and self.hidden_depth == 0:
            self.current_heading_text.append(data)
        if not self.in_skip and self.hidden_depth == 0 and data.strip():
            words = re.findall(r'\w+', data)
            self.visible_words.extend(words)
        # Block-chunk text excludes heading labels (a heading is not itself
        # "content"), hidden/chrome/skip regions -- same gates as above, plus
        # chrome, so nav/footer text never counts as a heading's answer or as
        # main-content for the positioning check.
        if (self.current_heading_level is None and not self.in_skip
                and self.hidden_depth == 0 and self.chrome_depth == 0 and data.strip()):
            self._current_chunk.append(data)

def _word_count(text):
    return len(re.findall(r'\w+', text or ''))


def find_question_headings(headings, blocks):
    """Which headings are phrased as questions, and does real content
    (any of it, not judged for quality -- see ANSWER_PRESENCE_MIN_WORDS)
    immediately follow each one before the next heading starts."""
    detected = []
    for idx, h in enumerate(headings):
        text = h['text']
        stripped = text.rstrip()
        ends_q = bool(stripped) and stripped[-1] in _QUESTION_MARK_CHARS
        starts_q = bool(_QUESTION_WORD_RX.match(text.strip()))
        if not (ends_q or starts_q):
            continue

        heading_tag_index = h['tag_index']
        next_heading_tag_index = (headings[idx + 1]['tag_index']
                                  if idx + 1 < len(headings) else None)
        next_block_words = 0
        for b in blocks:
            if b['tag_index'] <= heading_tag_index:
                continue
            if next_heading_tag_index is not None and b['tag_index'] >= next_heading_tag_index:
                break
            next_block_words = _word_count(b['text'])
            break

        detected.append({
            'heading_text': text,
            'ends_with_question_mark': ends_q,
            'starts_with_question_word': starts_q,
            'next_block_word_count': next_block_words,
            'has_content_following': next_block_words >= ANSWER_PRESENCE_MIN_WORDS,
        })
    return detected


def analyze_content_positioning(blocks):
    """Where, as a fraction of the page's main-content word count, does the
    first substantial block of text appear. Excludes chrome (nav/header/
    footer/aside) entirely -- both from the total and from the search -- so a
    large navigation menu cannot make a page look "front-loaded" or "buried"
    for reasons that have nothing to do with its actual content.

    Returns checked: False (never a guessed verdict) when there isn't enough
    signal to say anything meaningful: too little main content overall, or no
    single block ever reaches the substantial-length floor (a page built
    entirely of short list items is a legitimate style, not a defect)."""
    total_main_words = sum(_word_count(b['text']) for b in blocks)
    if total_main_words < MIN_MAIN_WORDS_FOR_POSITIONING:
        return {
            'checked': False,
            'reason': f'insufficient main content ({total_main_words} words) to evaluate positioning'
        }

    running = 0
    first_substantial = None
    for b in blocks:
        wc = _word_count(b['text'])
        if wc >= SUBSTANTIAL_BLOCK_MIN_WORDS:
            first_substantial = {'word_offset': running, 'text': b['text'][:160]}
            break
        running += wc

    if first_substantial is None:
        return {
            'checked': False,
            'reason': 'no single content block reaches the substantial-length threshold '
                     '(content may be legitimately structured as many short blocks)'
        }

    fraction = first_substantial['word_offset'] / total_main_words
    return {
        'checked': True,
        'total_main_words': total_main_words,
        'first_substantial_block_word_offset': first_substantial['word_offset'],
        'first_substantial_block_fraction': round(fraction, 4),
        'first_substantial_block_preview': first_substantial['text'],
        'front_loaded': fraction <= FRONT_LOADED_FRACTION_THRESHOLD,
    }


def check_semantic_structure(html_content, url):
    parser = SemanticStructureParser()
    try:
        parser.feed(html_content or '')
    except Exception:
        pass
    parser._flush_block()  # trailing text with no closing block tag after it

    title_str = ' '.join(''.join(parser.title_text).split()) if parser.title_text else None
    h1_count = sum(1 for h in parser.headings if h['level'] == 1)

    question_headings = find_question_headings(parser.headings, parser.blocks)
    content_positioning = analyze_content_positioning(parser.blocks)

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
        # Rolled-up booleans consumed by the orchestrator.
        'h1_missing': h1_count == 0,
        'multiple_h1': h1_count > 1,
        # Structural fingerprint of a CLIENT-INJECTED <h1>: the outline's root
        # is absent while its children are present. Hand-written HTML rarely
        # ships h2/h3 with no h1; a JS-rendered hero headline does exactly this.
        # The orchestrator uses this to say "server-render the <h1>" rather than
        # the wrong advice "add an <h1>".
        'h1_missing_but_subheadings_present': (
            h1_count == 0
            and sum(1 for h in parser.headings if h.get('level') in (2, 3)) > 0
        ),
        'subheading_levels_present': sorted({
            h.get('level') for h in parser.headings if h.get('level')
        }),
        'heading_hierarchy_issues': [
            f"level {s.get('from_level')} -> {s.get('to_level')} at '{str(s.get('heading_text'))[:60]}'"
            for s in skipped_levels
        ],
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
        'visible_text_word_count': len(parser.visible_words),
        'question_headings': {
            'detected': question_headings,
            'unanswered_count': sum(1 for q in question_headings if not q['has_content_following']),
        },
        'content_positioning': content_positioning,
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
        html_content = ""
        url = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html_content = params.get("html", "")
                    url = params.get("url", "")
                except json.JSONDecodeError:
                    url = raw_arg
            else:
                url = raw_arg

        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
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

        result = check_semantic_structure(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
