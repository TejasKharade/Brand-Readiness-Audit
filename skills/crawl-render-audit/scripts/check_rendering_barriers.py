
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
"""
check_rendering_barriers.py — Crawl-Render Audit Skill  v2
Detects Client-Side Rendering (CSR) barriers that prevent non-JS AI crawlers
from reading main page content.

Fixes applied (v2):
  F1  - Word count scoped to <main>/<article> (excludes nav/footer boilerplate)
  F2  - WAF/bot-challenge interstitial detector (Cloudflare, Datadome, Akamai)
  F3  - Skeleton-screen / shimmer-loader detector (prose-density + heading repetition)
  F4  - Expanded SPA mount point detection: 20+ IDs + class-name fragment matching
  F5  - OR-gate SPA logic: mount point alone is sufficient, decoupled from word count
  F6  - Hashed bundle path detection (/_next/static/, /__nuxt/, /assets/chunk-)
  F7  - Inline script body scanning for framework bootstrap signatures
  F8  - hydration_ratio outputs null + hydration_ratio_is_assumed when no rendered_html
  F9  - Main-area hydration ratio computed separately when rendered_html available
  F10 - Custom Web Component (hyphenated tag name) counted as CSR signal
  F11 - <script type="application/json"> excluded from word count via skip-stack
  F12 - Nested skip-tag tracking uses a stack (not a boolean), no premature exit
  F13 - hidden_depth capped at 200 and never below 0 (malformed HTML guard)
"""

import sys
import json
import html
import re
import urllib.parse
from html.parser import HTMLParser
from collections import Counter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPA_MOUNT_IDS = {
    "root", "app", "__next", "__nuxt", "app-root", "react-root",
    "___gatsby", "gatsby-focus-wrapper",
    "ember-application", "ember-app",
    "angular-app", "ng-app",
    "vue-app", "svelte-app",
    "blazor-app", "blazor-content",
    "app-container", "main-content",
    "portal-root", "page-content",
    "spa-root", "client-root",
}

# Exact-set matching misses the very common branded / suffixed mount id
# (`trello-root`, `acme-app`, `react-root-card-back`, `shop-app-container`).
# These patterns catch the shape instead of enumerating every brand.
SPA_MOUNT_ID_PATTERN = re.compile(
    r"^(?:[a-z0-9]+[-_])?(?:root|app|mount|spa|client)(?:[-_][a-z0-9-]+)?$"
    r"|^(?:react|vue|ng|angular|svelte|ember|next|nuxt|gatsby|blazor|qwik|astro)"
    r"[-_][a-z0-9-]*(?:root|app|mount|container|wrapper)[a-z0-9-]*$",
    re.I,
)

# Skeleton/shimmer scaffolding named in an id or class. Bare "placeholder" is
# deliberately NOT a token: it names form-input placeholders, lazy-image
# placeholders and empty-state boxes on fully server-rendered pages.
SKELETON_TOKEN_PATTERN = re.compile(
    r"\b(?:skeleton|shimmer|ghost-?(?:element|card|loader)|"
    r"loading-?(?:state|placeholder|skeleton))\b", re.I)

# Words of real raw content above which a page is not "trapped" behind JS. A
# skeleton marker on a page that already carries this much server-rendered
# text is decoration, not a rendering barrier.
RAW_CONTENT_WORD_FLOOR = 120
NEAR_EMPTY_RAW_WORDS = 25

# The most explicit statement a page can make that it requires JavaScript.
NOSCRIPT_JS_REQUIRED_PATTERN = re.compile(
    r"(?:enable|turn\s+on|activate)\s+javascript"
    r"|javascript\s+(?:is\s+)?(?:required|must\s+be|needs?\s+to\s+be)"
    r"|requires?\s+javascript"
    r"|doesn'?t\s+work\s+without\s+javascript"
    r"|<noscript>\s*you\s+need\s+to\s+enable",
    re.I)

# Structural-emptiness trigger: a payload this large with no headings and no
# paragraphs is a shell whatever framework (if any) built it.
STRUCTURALLY_EMPTY_MIN_BYTES = 50 * 1024
# Hydration-shell density: many blocks carrying almost no words.
LOW_DENSITY_MIN_BLOCKS = 20
LOW_DENSITY_WORDS_PER_BLOCK = 3.0

# Class-name substrings that strongly indicate a SPA wrapper element
SPA_CLASS_FRAGMENTS = [
    "react-app", "vue-app", "angular-app", "svelte-app", "ember-app",
    "nuxt-app", "gatsby-app", "next-app", "ng-view", "ng-app",
]

# (regex-on-src, framework-label) for <script src="..."> detection.
# Anchored to path/version boundaries so generic English words in a filename
# (e.g. "reactions-widget.js", "revue.js", "triangular.js") do not false-match.
FRAMEWORK_SRC_PATTERNS = [
    (re.compile(r"/_next/static/"),                       "React/Next.js"),
    (re.compile(r"/__nuxt/|/_nuxt/"),                     "Vue/Nuxt"),
    (re.compile(r"/_astro/"),                             "Astro"),
    (re.compile(r"\bnext(?:\.min)?\.js\b|next-router"),   "React/Next.js"),
    (re.compile(r"\breact(?:-dom|-router|-redux)?"
                r"(?:\.production|\.development)?"
                r"(?:\.min)?\.js\b|/react@|/react/umd/"), "React"),
    (re.compile(r"\bvue(?:\.global|\.runtime|\.esm"
                r"|\.common)?(?:\.prod|\.min)?\.js\b"
                r"|/vue@|/vue/dist/"),                    "Vue"),
    (re.compile(r"\bnuxt(?:\.min)?\.js\b|/nuxt/dist/"),   "Vue/Nuxt"),
    (re.compile(r"@angular/|\bangular(?:\.min)?\.js\b"
                r"|/zone\.js|polyfills-[\w]+\.js"),       "Angular"),
    (re.compile(r"\bsvelte\b[/.]|svelte-hmr|/@sveltejs/"),"Svelte"),
    (re.compile(r"\bember(?:\.debug|\.prod|\.min)?\.js\b"
                r"|/ember-cli/"),                         "Ember.js"),
    (re.compile(r"/assets/chunk-|/static/js/(?:main|app|"
                r"runtime|chunk)|webpack-[\w]+\.js"
                r"|/chunk\.[\w]+\.js|/bundle\.[\w]+\.js"
                r"|/vendor\.[\w]+\.js"),                  "Client-Side JS Bundle"),
]

# (compiled-regex, framework-label) for inline <script> body scanning (F7)
INLINE_FRAMEWORK_PATTERNS = [
    (re.compile(r"ReactDOM\s*\.\s*(?:render|createRoot|hydrateRoot)\s*\(", re.I), "React"),
    (re.compile(r"createApp\s*\([^)]*\)\s*\.\s*mount\s*\(",                re.I), "Vue"),
    (re.compile(r"new\s+Vue\s*\(\s*\{",                                     re.I), "Vue"),
    (re.compile(r"platformBrowserDynamic\s*\(\s*\)",                        re.I), "Angular"),
    (re.compile(r"bootstrapModule\s*\(",                                    re.I), "Angular"),
    (re.compile(r"window\.__remixContext\s*=",                              re.I), "React/Remix"),
    (re.compile(r"window\.__NEXT_DATA__\s*=",                               re.I), "React/Next.js"),
    (re.compile(r"window\.__nuxt\s*=",                                      re.I), "Vue/Nuxt"),
    (re.compile(r"window\.__qwikManifest__\s*=",                            re.I), "Qwik"),
    (re.compile(r"window\.__astro\s*=",                                     re.I), "Astro"),
    (re.compile(r"window\.__PAGE_MODEL__\s*=",                              re.I), "Data Island SPA"),
    (re.compile(r"Svelte\.\w+\s*\(",                                        re.I), "Svelte"),
    (re.compile(r"Ember\.Application\.create\s*\(",                         re.I), "Ember.js"),
]

DATA_ISLAND_IDS = {
    "__NEXT_DATA__", "__NUXT__", "__STATE__", "__INITIAL_STATE__",
    "__REDUX_STATE__", "__APOLLO_STATE__", "__RELAY_STORE__",
}

# WAF interstitial page-title phrases
WAF_TITLE_PATTERN = re.compile(
    r"just a moment|attention required|access denied|browser check|"
    r"checking your browser|security check|human verification|"
    r"ddos protection|ray id",
    re.I,
)
WAF_ID_CLASS_TOKENS = {
    "cf-challenge-body", "cf-browser-verification", "cf-wrapper",
    "cf-error-overview", "captcha-container", "ddos-protection",
    "px-captcha", "datadome-interstitial", "akamai-wait-spinner",
}
WAF_INLINE_PATTERN = re.compile(
    r"window\._cf_chl_opt|window\.__ddg_runtime|window\.__akamai|"
    r"window\.botd|_px\.init|window\.__DDGU",
    re.I,
)

# Tags whose text is never visible content — skip entirely (F11: added application/json type)
SKIP_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "template", "object", "embed",
}
# <script type="..."> values that should be treated as non-executable / data blobs
SKIP_SCRIPT_TYPES = {
    "application/json", "text/template", "text/x-template",
    "text/html", "application/x-ndjson", "application/ld+json",
}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
CONTENT_AREA_TAGS = {"main", "article", "section"}
BOILERPLATE_TAGS  = {"header", "footer", "nav", "aside"}

# Block-level tags that end a run of text. Without these breaks, adjacent
# elements' text runs together into one long pseudo-sentence and the
# raw-vs-rendered sentence comparison below matches on the wrong boundaries.
TEXT_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "header", "footer", "nav", "aside",
    "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "td", "th", "form",
    "fieldset", "figure", "figcaption", "blockquote", "pre", "hr", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "address", "details", "summary",
}

# Custom elements that ship server-rendered / progressively-enhanced content and
# must NOT be treated as a client-side-rendering bootstrap signal.
SSR_CUSTOM_ELEMENTS = {
    "turbo-frame", "turbo-stream", "turbo-cable-stream-source",
    "astro-island", "astro-slot", "astro-static-slot", "is-land",
    "trix-editor", "rails-ujs", "live-view", "phx-", "hotwire-",
    "amp-img", "amp-video", "amp-analytics", "amp-ad", "amp-list",
    "model-viewer", "lite-youtube", "media-chrome",
}

# Tags that imply the end of an open <p> (block-level start after unclosed <p>),
# plus same-name / sibling auto-closers. Keeps depth counters balanced on the
# malformed-but-common HTML that html.parser does NOT auto-correct.
_CLOSES_OPEN_P = {
    "p", "div", "section", "article", "main", "header", "footer", "nav",
    "aside", "ul", "ol", "dl", "table", "form", "fieldset", "figure",
    "blockquote", "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "address",
}
_SIBLING_AUTOCLOSE = {
    "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
    "option": {"option"}, "optgroup": {"optgroup", "option"},
    "tr": {"tr"}, "td": {"td", "th"}, "th": {"td", "th"},
    "thead": {"thead", "tbody", "tfoot"}, "tbody": {"thead", "tbody", "tfoot"},
    "tfoot": {"thead", "tbody", "tfoot"},
}
_MAX_EL_STACK = 400


# ---------------------------------------------------------------------------
# Robust HTML Parser (replaces SimpleTextAndHeadingParser)
# ---------------------------------------------------------------------------

class RobustContentParser(HTMLParser):
    """
    Parses raw HTML, tracking word counts for the full document and for
    the semantic content area (<main>/<article>/<section>) separately.
    Collects inline script bodies, SPA signals, and WAF fingerprints.
    """

    def __init__(self):
        super().__init__()

        # F1: separate word buffers
        self._all_words  = []      # full doc minus boilerplate
        self._main_words = []      # strictly inside <main>/<article>/<section>
        self._in_boilerplate = 0   # header/footer/nav/aside  -- frame-maintained
        self._content_depth  = 0   # main/article/section     -- frame-maintained

        # structural counters for raw-vs-rendered delta comparison
        self.p_count = 0
        self.li_count = 0
        self.jsonld_block_count = 0
        # Same counters restricted to non-boilerplate regions. The density
        # ratio must count blocks on the same basis the word count uses --
        # otherwise a 50-link footer inflates the denominator while its words
        # are (correctly) excluded, faking a hydration shell.
        self.p_count_content = 0
        self.li_count_content = 0
        self.heading_count_content = 0
        self.ssr_custom_elements_count = 0   # custom tags on the SSR denylist

        # F12: stack-based skip-tag tracking
        self._skip_stack      = []
        self._cur_script_type = None   # "js" | "skip" | None
        self._cur_script_body = []

        # Element stack of frames {tag, hid, boiler, content} so that every
        # counter is decremented by exactly the frame that incremented it,
        # even when the page omits close tags (html.parser does not auto-fix).
        self._el_stack = []
        self._hidden_depth = 0     # derived from frames, never goes stuck

        # Heading tracking
        self._headings    = []
        self._cur_h_level = None
        self._cur_h_text  = []

        # SPA / framework signals
        self.spa_mount_points     = []
        self.detected_frameworks  = set()
        self.data_islands         = []
        self.custom_elements_count = 0   # F10
        self.inline_script_bodies  = []  # F7
        self.skeleton_markers      = []  # id/class tokens declaring a skeleton
        self.noscript_text         = []  # captured, never counted as content

        # WAF fingerprints
        self._page_title_parts = []
        self._in_title         = False
        self.waf_id_class_hits = []
        self.waf_inline_hit    = False

        # Visible text kept verbatim (block-delimited) so raw and rendered can
        # be compared sentence by sentence, not just by counts -- a count says
        # "content is missing", the sentences say WHICH content. Boilerplate is
        # excluded on the same basis as the word counters, which also keeps
        # cookie banners and nav labels out of the comparison.
        self._text_chunks = []
        # Every <a href> seen, including inside nav/header: link discovery is
        # precisely about navigation, so boilerplate must NOT be excluded here.
        self.link_hrefs = []

    # ---- helpers ----

    def _in_skip(self):
        return bool(self._skip_stack)

    def _pop_frame(self):
        """Pop one element frame and undo exactly the counter bumps it made."""
        fr = self._el_stack.pop()
        if fr["hid"]:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        if fr["boiler"]:
            self._in_boilerplate = max(0, self._in_boilerplate - 1)
        if fr["content"]:
            self._content_depth = max(0, self._content_depth - 1)
        return fr

    def _imply_end_tags(self, opening_tag):
        """Close frames that HTML implies are closed by `opening_tag`."""
        # a new block-level element closes an open <p>
        if opening_tag in _CLOSES_OPEN_P:
            while self._el_stack and self._el_stack[-1]["tag"] == "p":
                self._pop_frame()
        # sibling auto-closers (li closes li, td closes td/th, ...)
        closes = _SIBLING_AUTOCLOSE.get(opening_tag)
        if closes and self._el_stack and self._el_stack[-1]["tag"] in closes:
            self._pop_frame()

    # ---- tag handlers ----

    def handle_starttag(self, tag, attrs):
        tag_lower  = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}

        style     = attrs_dict.get("style", "").replace(" ", "").lower()
        is_hidden_self = (
            "hidden" in attrs_dict
            or attrs_dict.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )

        # Extract attributes needed for signal detection (must happen before skip-stack check)
        element_id    = attrs_dict.get("id",    "").strip()
        element_class = attrs_dict.get("class", "").lower()

        # F6: framework detection via <script src="..."> including path-prefix patterns
        # (Must run BEFORE skip-stack push since <script> will be immediately skipped)
        if tag_lower == "script":
            src = attrs_dict.get("src", "").lower()
            if src:
                for pattern, label in FRAMEWORK_SRC_PATTERNS:
                    if pattern.search(src):
                        self.detected_frameworks.add(label)
                        break

        # F11/F12: push skip-stack on SKIP_TAGS or non-executable <script> types
        if tag_lower not in VOID_TAGS:
            script_type = attrs_dict.get("type", "").lower().strip()
            if tag_lower == "script" and script_type == "application/ld+json":
                self.jsonld_block_count += 1
            if tag_lower in SKIP_TAGS or script_type in SKIP_SCRIPT_TYPES:
                self._skip_stack.append(tag_lower)
                if tag_lower == "script":
                    is_exec = not script_type or script_type in (
                        "text/javascript", "application/javascript",
                        "module", "text/ecmascript",
                    )
                    self._cur_script_type = "js" if is_exec else "skip"
                    self._cur_script_body = []
                    # Data island IDs on skipped <script type="application/json"> elements
                    # (F11: still detect the ID even though text content is skipped)
                    if element_id in DATA_ISLAND_IDS:
                        self.data_islands.append(element_id)
                        self.detected_frameworks.add(f"SSR Data Island ({element_id})")
                return  # skip structural/word-count processing for this element

        # ---- element stack + frame-maintained depth counters ----
        self._imply_end_tags(tag_lower)
        frame = {"tag": tag_lower, "hid": False, "boiler": False, "content": False}
        if is_hidden_self or self._hidden_depth > 0:
            self._hidden_depth += 1
            frame["hid"] = True
        if tag_lower in BOILERPLATE_TAGS:
            self._in_boilerplate += 1
            frame["boiler"] = True
        if tag_lower in CONTENT_AREA_TAGS:
            self._content_depth += 1
            frame["content"] = True
        if len(self._el_stack) < _MAX_EL_STACK:
            self._el_stack.append(frame)
        else:
            # runaway malformed input: undo this frame's bumps, stop tracking depth
            if frame["hid"]:     self._hidden_depth = max(0, self._hidden_depth - 1)
            if frame["boiler"]:  self._in_boilerplate = max(0, self._in_boilerplate - 1)
            if frame["content"]: self._content_depth = max(0, self._content_depth - 1)

        if tag_lower == "title":
            self._in_title = True

        if tag_lower in TEXT_BLOCK_TAGS:
            self._text_chunks.append("\n")
        if tag_lower == "a" and self._hidden_depth == 0:
            href = attrs_dict.get("href", "").strip()
            if href:
                self.link_hrefs.append(href)

        if tag_lower == "p" and self._hidden_depth == 0:
            self.p_count += 1
            if self._in_boilerplate == 0:
                self.p_count_content += 1
        elif tag_lower == "li" and self._hidden_depth == 0:
            self.li_count += 1
            if self._in_boilerplate == 0:
                self.li_count_content += 1

        if re.match(r"^h[1-6]$", tag_lower):
            if self._hidden_depth == 0 and self._in_boilerplate == 0:
                self.heading_count_content += 1
            self._cur_h_level = int(tag_lower[1])
            self._cur_h_text  = []

        # F4a: SPA mount point — known ID, or the branded/suffixed *shape*
        # (`trello-root`, `acme-app`, `react-root-card-back`).
        eid = element_id.lower()
        if eid and (eid in SPA_MOUNT_IDS or SPA_MOUNT_ID_PATTERN.match(eid)):
            self.spa_mount_points.append(f"{tag_lower}#{eid}")

        # F4b: SPA mount point — class fragment match
        for frag in SPA_CLASS_FRAGMENTS:
            if frag in element_class:
                self.spa_mount_points.append(f"{tag_lower}.{frag}")
                break

        # Self-declared skeleton scaffolding in an id or class name.
        for attr_val in (eid, element_class):
            m = SKELETON_TOKEN_PATTERN.search(attr_val or "")
            if m:
                token = f"{tag_lower}[{m.group(0).lower()}]"
                if token not in self.skeleton_markers:
                    self.skeleton_markers.append(token)
                break

        # SSR Data Island IDs (for non-script elements; script elements handled above)
        if element_id in DATA_ISLAND_IDS:
            self.data_islands.append(element_id)
            self.detected_frameworks.add(f"SSR Data Island ({element_id})")

        # F10: custom web components use hyphenated tag names (per HTML spec).
        # Split the count: SSR/progressive-enhancement custom elements (Turbo,
        # Astro islands, AMP, model-viewer, ...) ship server-rendered content and
        # must NOT be read as a client-side-rendering bootstrap signal.
        if "-" in tag_lower and tag_lower not in VOID_TAGS:
            if tag_lower in SSR_CUSTOM_ELEMENTS or any(
                tag_lower.startswith(p) for p in SSR_CUSTOM_ELEMENTS if p.endswith("-")
            ):
                self.ssr_custom_elements_count += 1
            else:
                self.custom_elements_count += 1

        # F2: WAF id/class token matching
        for attr_name in ("id", "class"):
            val = attrs_dict.get(attr_name, "").lower()
            for tok in WAF_ID_CLASS_TOKENS:
                if tok in val:
                    self.waf_id_class_hits.append(f"{attr_name}:{tok}")

    def handle_endtag(self, tag):
        tag_lower = tag.lower()

        if tag_lower in TEXT_BLOCK_TAGS and not self._skip_stack:
            self._text_chunks.append("\n")

        # F12: pop skip-stack on matching close tag
        if self._skip_stack and self._skip_stack[-1] == tag_lower:
            self._skip_stack.pop()
            if tag_lower == "script":
                body = "".join(self._cur_script_body).strip()
                if body and self._cur_script_type == "js":
                    self.inline_script_bodies.append(body)
                    # F2: check WAF inline signals immediately
                    if WAF_INLINE_PATTERN.search(body):
                        self.waf_inline_hit = True
                self._cur_script_type = None
                self._cur_script_body = []
            return

        # Unwind the element stack to the matching frame, undoing each popped
        # frame's counter bumps. If the tag isn't on the stack (stray close),
        # pop nothing. This keeps hidden/boilerplate/content depth balanced even
        # when the page omits intermediate close tags.
        if tag_lower not in VOID_TAGS:
            depth_of = None
            for i in range(len(self._el_stack) - 1, -1, -1):
                if self._el_stack[i]["tag"] == tag_lower:
                    depth_of = i
                    break
            if depth_of is not None:
                while len(self._el_stack) > depth_of:
                    self._pop_frame()

        if tag_lower == "title":
            self._in_title = False

        if re.match(r"^h[1-6]$", tag_lower) and self._cur_h_level is not None:
            text = " ".join("".join(self._cur_h_text).split())
            if text and self._hidden_depth == 0:
                self._headings.append({"level": self._cur_h_level, "text": text})
            self._cur_h_level = None
            self._cur_h_text  = []

    def handle_data(self, data):
        # F7 + F11: collect JS script body; skip non-JS (data/template) script types
        if self._skip_stack and self._skip_stack[-1] == "script":
            if self._cur_script_type == "js":
                self._cur_script_body.append(data)
            return

        # <noscript> text is never counted as page content, but its *presence*
        # is captured -- a "please enable JavaScript" message is the most
        # explicit CSR-barrier declaration a page can make.
        if self._skip_stack and self._skip_stack[-1] == "noscript":
            if data and data.strip():
                self.noscript_text.append(data.strip())
            return

        if self._in_skip():
            return

        if self._in_title:
            self._page_title_parts.append(data)

        if self._hidden_depth > 0 or not data.strip():
            return

        if self._cur_h_level is not None:
            self._cur_h_text.append(data)

        words = re.findall(r"\w+", data)
        if not words:
            return

        # F1: exclude boilerplate from both buffers
        if self._in_boilerplate == 0:
            self._text_chunks.append(data)
            self._all_words.extend(words)
        if self._content_depth > 0 and self._in_boilerplate == 0:
            self._main_words.extend(words)

    # ---- derived properties ----

    @property
    def all_word_count(self):  return len(self._all_words)

    @property
    def main_word_count(self): return len(self._main_words)

    @property
    def headings(self):        return self._headings

    @property
    def page_title(self):      return " ".join(self._page_title_parts).strip()

    @property
    def visible_text(self):    return "".join(self._text_chunks)


# ---------------------------------------------------------------------------
# Sentence-level raw-vs-rendered comparison
#
# Counts answer "how much is missing"; sentences answer "WHAT is missing",
# which is what a site owner actually needs in order to act. The comparison
# normalises both sides to lowercase alphanumerics before matching, so an
# apostrophe written as &rsquo; in the raw HTML and as a literal character in
# the serialised DOM (or any other entity/punctuation difference) does not
# read as missing content.
# ---------------------------------------------------------------------------

SENTENCE_MIN_CHARS = 25
SENTENCE_MIN_WORDS = 4
SENTENCE_PROBE_WORDS = 7
MAX_SENTENCES_COMPARED = 400      # bounds the work on very large pages


def _normalise_for_match(text):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", html.unescape(text or "").lower()).split())


def extract_sentences(visible_text):
    """Substantive sentences from block-delimited visible text. Fragments and
    code-like strings are dropped: they are noisy to compare and useless as
    evidence."""
    out = []
    for candidate in re.split(r"(?<=[.!?])\s+|\n+", visible_text or ""):
        s = " ".join(candidate.split())
        if len(s) < SENTENCE_MIN_CHARS or len(s.split()) < SENTENCE_MIN_WORDS:
            continue
        if re.search(r"[{}<>|\\]|\)\s*;|=>|function\s*\(", s):
            continue
        out.append(s)
        if len(out) >= MAX_SENTENCES_COMPARED:
            break
    return out


def compare_sentence_parity(raw_parser, rend_parser):
    """Which rendered sentences are absent from the raw HTML a non-JS crawler
    receives. Returns None when there is no rendered DOM to compare against."""
    if rend_parser is None:
        return None
    rendered_sentences = extract_sentences(rend_parser.visible_text)
    raw_sentences = extract_sentences(raw_parser.visible_text)
    raw_norm = _normalise_for_match(raw_parser.visible_text)

    missing = []
    for s in rendered_sentences:
        norm = _normalise_for_match(s)
        if not norm:
            continue
        probe = " ".join(norm.split()[:SENTENCE_PROBE_WORDS])
        if probe and probe not in raw_norm:
            missing.append(s)

    total = len(rendered_sentences)
    parity = round((1 - len(missing) / total) * 100, 1) if total else 100.0
    return {
        "rendered_sentence_count": total,
        "raw_sentence_count": len(raw_sentences),
        "missing_from_raw_count": len(missing),
        "content_parity_pct": parity,
        # Evidence: the actual text a non-JS crawler cannot see.
        "missing_text_samples": [s[:220] for s in missing[:5]],
        "comparison_capped": total >= MAX_SENTENCES_COMPARED,
    }


def compare_link_discovery(raw_parser, rend_parser, page_url):
    """Internal links that exist only after JavaScript runs -- navigation built
    from onClick handlers or mounted menus rather than <a href>, which crawlers
    cannot traverse. Returns None without a rendered DOM."""
    if rend_parser is None:
        return None
    base_host = (urllib.parse.urlparse(page_url or "").netloc or "").lower()

    def internal_set(parser):
        out = set()
        for href in parser.link_hrefs:
            if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                continue
            try:
                full = urllib.parse.urljoin(page_url or "", href)
                p = urllib.parse.urlparse(full)
            except Exception:
                continue
            if p.scheme not in ("http", "https"):
                continue
            if base_host and p.netloc.lower() != base_host:
                continue
            out.add(f"{p.scheme}://{p.netloc}{p.path}".rstrip("/"))
        return out

    raw_links, rend_links = internal_set(raw_parser), internal_set(rend_parser)
    only_rendered = sorted(rend_links - raw_links)
    return {
        "raw_internal_links": len(raw_links),
        "rendered_internal_links": len(rend_links),
        "links_only_after_js_count": len(only_rendered),
        "links_only_after_js_samples": only_rendered[:5],
    }


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def detect_waf_interstitial(p: RobustContentParser) -> dict:
    """
    F2: Requires >= 2 independent WAF signals, or the unambiguous inline JS
    variable (e.g. window._cf_chl_opt), to flag a WAF interstitial page.
    """
    signals = []
    if p.waf_id_class_hits:
        signals.append(f"waf_html_elements:{p.waf_id_class_hits[:3]}")
    if p.waf_inline_hit:
        signals.append("waf_inline_js_variable")
    if p.page_title and WAF_TITLE_PATTERN.search(p.page_title):
        signals.append(f"waf_page_title:\"{p.page_title[:60]}\"")
    if p.main_word_count < 30 and p.all_word_count > 100:
        signals.append("boilerplate_inflation:main<30,total>100")
    detected = len(signals) >= 2 or p.waf_inline_hit
    return {"waf_challenge_detected": detected, "waf_signals": signals}


def scan_inline_scripts(bodies: list) -> set:
    """F7: Scan collected inline <script> bodies for framework bootstrap signatures."""
    combined = "\n".join(bodies)
    found = set()
    for pattern, label in INLINE_FRAMEWORK_PATTERNS:
        if pattern.search(combined):
            found.add(label)
    return found


def detect_skeleton_screen(p: RobustContentParser) -> bool:
    """
    F3: Detects skeleton/shimmer UIs, but only on pages whose raw content area
    is below RAW_CONTENT_WORD_FLOOR -- a skeleton only matters when the real
    content is missing from the payload. A page naming its own scaffolding
    (skeleton/shimmer in an id or class) declares one outright; otherwise fall
    back to heading repetition and low prose density.
    """
    eff_words = p.main_word_count if p.main_word_count > 0 else p.all_word_count
    if eff_words >= RAW_CONTENT_WORD_FLOOR:
        return False
    if p.skeleton_markers:
        return True
    headings = p.headings
    if len(headings) >= 4:
        texts     = [h["text"].lower().strip() for h in headings]
        top_count = Counter(texts).most_common(1)[0][1]
        if top_count / len(texts) > 0.5:
            return True
    if len(headings) >= 6 and p.main_word_count > 0:
        if (p.main_word_count / len(headings)) < 5:
            return True
    return False


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------

def _parse(html: str) -> RobustContentParser:
    p = RobustContentParser()
    try:
        p.feed(html or "")
    except Exception:
        pass
    return p


def check_rendering_barriers(raw_html, rendered_html, url):
    raw_present = bool(raw_html and raw_html.strip())
    raw      = _parse(raw_html)
    has_rend = bool(rendered_html and rendered_html.strip())
    rend     = _parse(rendered_html) if has_rend else None

    raw_words_all  = raw.all_word_count
    raw_words_main = raw.main_word_count
    # F1: prefer main-area word count; fall back to full-doc count if no <main>/<article> found
    eff_raw = raw_words_main if raw_words_main > 0 else raw_words_all

    # F7: inline script framework detection
    inline_detected = scan_inline_scripts(raw.inline_script_bodies)
    all_frameworks  = raw.detected_frameworks | inline_detected

    # F2: WAF interstitial check
    waf_result  = detect_waf_interstitial(raw)
    # F3: skeleton screen check
    is_skeleton = detect_skeleton_screen(raw)

    # F8 + F9: hydration ratios (null when no rendered_html)
    hydration_ratio      = None
    main_hydration_ratio = None
    is_assumed           = True

    if has_rend:
        rend_all  = rend.all_word_count
        rend_main = rend.main_word_count
        eff_rend  = rend_main if rend_main > 0 else rend_all
        hydration_ratio = round(raw_words_all / max(rend_all, 1), 3)
        is_assumed      = False
        if eff_rend > 0:
            main_hydration_ratio = round(eff_raw / max(eff_rend, 1), 3)

    # -------------------------------------------------------------------
    # Hydration barrier: decided by a COUNT of independent structural
    # deltas between raw HTML and rendered DOM -- not a single ratio
    # cutoff. The ratio is retained only as supporting evidence. This
    # generalises to custom SPA frameworks (Web Components, "data island"
    # bootstrappers) because it compares actual structure, not framework
    # name lists.
    # -------------------------------------------------------------------

    # Heading hydration gap (used both as evidence and as a delta signal)
    raw_h_texts      = {h["text"].lower() for h in raw.headings}
    missing_headings = []
    if rend:
        for rh in rend.headings:
            if rh["text"].lower() not in raw_h_texts:
                missing_headings.append(rh)

    structural_deltas = []
    thin = False
    if has_rend and rend is not None:
        eff_rend = (rend.main_word_count if rend.main_word_count > 0 else rend.all_word_count)
        heading_delta = len(rend.headings) - len(raw.headings)
        jsonld_delta  = rend.jsonld_block_count - raw.jsonld_block_count
        para_delta    = rend.p_count - raw.p_count
        li_delta      = rend.li_count - raw.li_count

        if eff_rend >= 2 * max(eff_raw, 1) and eff_raw < RAW_CONTENT_WORD_FLOOR:
            structural_deltas.append(
                f"rendered main text ({eff_rend}w) >= 2x raw ({eff_raw}w) and raw is below the "
                f"{RAW_CONTENT_WORD_FLOOR}w content floor")
        if heading_delta >= 2:
            structural_deltas.append(f"{heading_delta} headings appear only after JS render")
        if jsonld_delta >= 1:
            structural_deltas.append(f"{jsonld_delta} JSON-LD block(s) injected only by JS")
        if para_delta >= 3:
            structural_deltas.append(f"{para_delta} <p> blocks appear only after JS render")
        if li_delta >= 6:
            structural_deltas.append(f"{li_delta} list items appear only after JS render")

        near_empty_shell = eff_raw < NEAR_EMPTY_RAW_WORDS and eff_rend > 150
        if near_empty_shell:
            structural_deltas.append(
                f"raw HTML content area is near-empty ({eff_raw}w) while rendered DOM has {eff_rend}w")

        # >=2 independent deltas, OR the single unambiguous near-empty-shell signal
        thin = len(structural_deltas) >= 2 or near_empty_shell

    # F5: raw-only SPA-shell gate. Without a rendered comparison a hydration
    # *gap* cannot be measured; the most that can be said is that the payload
    # looks like an unfilled shell -- (framework|mount|data-island|custom
    # elements) AND a near-empty raw content area. One named floor, corroborated.
    mount_detected   = bool(raw.spa_mount_points)
    fwork_detected   = bool(all_frameworks)
    data_isl_present = bool(raw.data_islands)
    raw_content_area_empty  = eff_raw < RAW_CONTENT_WORD_FLOOR
    raw_content_near_empty  = eff_raw < NEAR_EMPTY_RAW_WORDS

    # Bare hyphenated custom elements only count as a bootstrap signal when they
    # are numerous AND the raw content area is genuinely empty (an unfilled
    # <x-app></x-app> shell) -- NOT when the page just uses a web-component
    # design system or Turbo/Astro server rendering.
    custom_shell = raw.custom_elements_count >= 3 and raw_content_near_empty

    csr_bootstrap_present = mount_detected or fwork_detected or data_isl_present

    # --- Independent barrier signals that do NOT require a framework
    # fingerprint. A shell is a shell whatever built it. ---
    noscript_blob = " ".join(raw.noscript_text)
    noscript_js_required = bool(NOSCRIPT_JS_REQUIRED_PATTERN.search(noscript_blob))

    raw_bytes = len(raw_html or "")
    structurally_empty = (
        raw.p_count == 0 and len(raw.headings) == 0
        and raw_bytes >= STRUCTURALLY_EMPTY_MIN_BYTES
    )

    # Hydration shell: many content blocks carrying almost no words. Catches
    # pages whose absolute word count squeaks over the floor but whose blocks
    # are empty scaffolding (e.g. 68 <p> holding 127 words). Blocks are counted
    # on the same non-boilerplate basis as the words, so a big nav or footer
    # link list cannot fake the ratio.
    content_blocks = (raw.p_count_content + raw.heading_count_content
                      + raw.li_count_content)
    words_per_block = (eff_raw / content_blocks) if content_blocks else None
    low_density_shell = (
        content_blocks >= LOW_DENSITY_MIN_BLOCKS
        and words_per_block is not None
        and words_per_block < LOW_DENSITY_WORDS_PER_BLOCK
    )

    barrier_reasons = []
    if not raw_present:
        # Nothing to audit -- do NOT report "no barrier" as if it were a pass.
        is_spa_likely = None
    else:
        if thin:
            barrier_reasons.append("measured raw-vs-rendered hydration gap")
        if waf_result["waf_challenge_detected"]:
            barrier_reasons.append("WAF/bot-challenge interstitial")
        if noscript_js_required:
            barrier_reasons.append(
                f"<noscript> declares JavaScript is required: "
                f"\"{noscript_blob[:90].strip()}\"")
        if structurally_empty:
            barrier_reasons.append(
                f"no headings and no <p> in {round(raw_bytes/1024)}KB of HTML "
                f"({eff_raw} words) -- unfilled shell")
        if low_density_shell:
            barrier_reasons.append(
                f"{content_blocks} content blocks holding only {eff_raw} words "
                f"({words_per_block:.1f} words/block) -- hydration shell")
        if csr_bootstrap_present and raw_content_area_empty:
            barrier_reasons.append(
                f"CSR bootstrap present (mounts={raw.spa_mount_points[:2]}, "
                f"frameworks={sorted(all_frameworks)[:2]}) with only {eff_raw} raw words")
        if custom_shell:
            barrier_reasons.append("empty custom-element shell")
        if is_skeleton:   # detect_skeleton_screen already requires thin raw content
            barrier_reasons.append(
                f"skeleton screen{' (self-declared: ' + str(raw.skeleton_markers[:2]) + ')' if raw.skeleton_markers else ''}")
        is_spa_likely = bool(barrier_reasons)

    return {
        "raw_html_present": raw_present,
        "has_rendered_comparison": has_rend,
        "word_counts": {
            "initial_raw_words_total":     raw_words_all,
            "initial_raw_words_main_area": raw_words_main,
            "effective_raw_words":         eff_raw,
            "rendered_dom_words_total":    rend.all_word_count if rend else None,
            "rendered_dom_words_main_area": rend.main_word_count if rend else None,
            "hydration_ratio":             hydration_ratio,
            "main_area_hydration_ratio":   main_hydration_ratio,
            "hydration_ratio_is_assumed":  is_assumed,
        },
        "hydration_gaps": {
            "thin_initial_content_detected":  thin,
            "structural_delta_signals":       structural_deltas,
            "structural_delta_count":         len(structural_deltas),
            "skeleton_screen_detected":       is_skeleton,
            "missing_initial_headings_count": len(missing_headings),
            "missing_initial_headings":       missing_headings[:10],
            "raw_structure": {
                "paragraphs": raw.p_count, "list_items": raw.li_count,
                "headings": len(raw.headings), "jsonld_blocks": raw.jsonld_block_count,
            },
            "rendered_structure": ({
                "paragraphs": rend.p_count, "list_items": rend.li_count,
                "headings": len(rend.headings), "jsonld_blocks": rend.jsonld_block_count,
            } if rend else None),
        },
        # Both are null without a rendered DOM. They do not feed the barrier
        # verdict above (which stands on its own signals); they say WHICH text
        # and WHICH links a non-JS crawler misses, as evidence for the fix.
        "content_parity": compare_sentence_parity(raw, rend),
        "link_discovery": compare_link_discovery(raw, rend, url),
        "client_side_rendering_signals": {
            "spa_mount_points":          raw.spa_mount_points,
            "detected_frameworks":       sorted(all_frameworks),
            "data_islands_detected":     raw.data_islands,
            "custom_web_elements_count": raw.custom_elements_count,
            "ssr_custom_elements_count": raw.ssr_custom_elements_count,
            "inline_framework_signals":  sorted(inline_detected),
            "skeleton_markers":          raw.skeleton_markers[:6],
            "noscript_requires_javascript": noscript_js_required,
            "noscript_text":             (noscript_blob[:200] or None),
            "structurally_empty":        structurally_empty,
            "content_blocks":            content_blocks,
            "words_per_content_block":   round(words_per_block, 2) if words_per_block is not None else None,
            "low_density_shell":         low_density_shell,
            "barrier_reasons":           barrier_reasons,
            "likely_client_side_rendering_barrier": is_spa_likely,
        },
        "waf_interstitial": waf_result,
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


if __name__ == "__main__":
    try:
        raw_html = rendered_html = url = ""
        params = {}
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params        = json.loads(raw_arg)
                    raw_html      = params.get("raw_html", "") or params.get("html", "")
                    rendered_html = params.get("rendered_html", "")
                    url           = params.get("url", "")
                except json.JSONDecodeError:
                    url = raw_arg
            else:
                url = raw_arg
        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                sp = json.loads(input_data)
                if isinstance(sp, dict):
                    params.update(sp)
            except json.JSONDecodeError:
                pass
        if not raw_html:      raw_html      = params.get("raw_html", "") or params.get("html", "")
        if not rendered_html: rendered_html = params.get("rendered_html", "")
        if not url:           url           = params.get("url", "")
        result = check_rendering_barriers(raw_html, rendered_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
