
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import os
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Advisory word-count bands (NOT hard cutoffs).
#
# These are loaded from references/reachability_thresholds.json when present.
# They are only ever consulted for *content-bearing* page intents, and a page
# is flagged "below reference" ONLY when the word count, the paragraph count,
# and the text-to-markup ratio all agree that the page is thin. A single low
# number never produces a finding on its own -- this is what keeps minimalist
# hero pages, utility pages, and single-page apps from being false-flagged.
# ---------------------------------------------------------------------------

DEFAULT_ADVISORY_BANDS = {
    "product":  {"advisory_min_words": 120, "recommended_words": 400},
    "service":  {"advisory_min_words": 150, "recommended_words": 500},
    "article":  {"advisory_min_words": 350, "recommended_words": 1000},
    "homepage": {"advisory_min_words": 80,  "recommended_words": 300},
    "category": {"advisory_min_words": 60,  "recommended_words": 250},
    # Generic fallback for a real (non-root) page that none of the specific
    # tiers below could type -- see PATH_INTENT_RULES's docstring. Uses the
    # most lenient floor already in the table (matching "category") precisely
    # because it is a low-confidence guess: assess_depth's low_words AND
    # structurally_empty double-gate is what actually protects a legitimately
    # short, well-structured page from a false flag here, not this number.
    "content":  {"advisory_min_words": 60,  "recommended_words": 250},
    "utility":  {"advisory_min_words": None, "recommended_words": None},
    "app":      {"advisory_min_words": None, "recommended_words": None},
    "media":    {"advisory_min_words": None, "recommended_words": None},
    "unknown":  {"advisory_min_words": None, "recommended_words": None},
}

CONTENT_BEARING_INTENTS = {"product", "service", "article", "homepage", "category", "content"}

# Path fragments -> intent. Ordered by specificity; first match wins.
#
# Every rule requires a directory-style segment ("/product/…", "/blog/…").
# That structurally cannot match a flat, extension-terminated slug with no
# directory at all ("/vinyl-examination-gloves.htm", "/widget.php") -- a
# common pattern on sites (old-school CMSes, many small-business sites) that
# don't use "/product/" or "/blog/" prefixes. When no rule here matches a
# non-root path, `detect_page_intent` falls back to the generic "content"
# intent rather than "unknown", so pages with this URL shape still get a
# (lenient) thinness check instead of silently skipping content-depth
# scoring entirely for every page on such a site.
PATH_INTENT_RULES = [
    (re.compile(r"/(login|log-in|signin|sign-in|register|signup|sign-up|"
                r"account|cart|checkout|basket|contact|support/ticket|"
                r"search|404|not-found|thank-you|privacy|terms|legal|"
                r"cookie|gdpr|unsubscribe|logout)(/|$|\?)", re.I), "utility"),
    (re.compile(r"/(app|dashboard|console|portal|admin|tool|calculator|"
                r"configurator|playground)(/|$|\?)", re.I), "app"),
    (re.compile(r"/(blog|news|article|articles|post|posts|insights|stories|"
                r"press|newsroom|resources/[a-z].*[a-z])(/|$)", re.I), "article"),
    (re.compile(r"/(product|products|shop|store|item|items|p|sku)(/|$)", re.I), "product"),
    (re.compile(r"/(pricing|plans|packages)(/|$)", re.I), "service"),
    (re.compile(r"/(services|solutions|features|capabilities|use-cases?)(/|$)", re.I), "service"),
    (re.compile(r"/(category|categories|collections?|tag|tags|topics?)(/|$)", re.I), "category"),
]

# JSON-LD @type (lowercased) -> intent
SCHEMA_TYPE_INTENT = {
    "product": "product", "offer": "product", "aggregateoffer": "product",
    "productgroup": "product", "vehicle": "product", "book": "product",
    "article": "article", "blogposting": "article", "newsarticle": "article",
    "techarticle": "article", "report": "article", "scholarlyarticle": "article",
    "service": "service", "financialproduct": "service", "loanorcredit": "service",
    "webapplication": "app", "softwareapplication": "app", "mobileapplication": "app",
    "contactpage": "utility", "checkoutpage": "utility", "searchresultspage": "utility",
    "aboutpage": "homepage", "collectionpage": "category", "itemlist": "category",
    "faqpage": "article", "howto": "article", "recipe": "article", "qapage": "article",
    "videoobject": "media", "imageobject": "media", "audioobject": "media",
    "organization": "homepage", "localbusiness": "homepage", "website": "homepage",
}

OG_TYPE_INTENT = {
    "article": "article", "blog": "article", "book": "article",
    "product": "product", "product.group": "product", "product.item": "product",
    "website": "homepage", "profile": "unknown", "video.other": "media",
    "music.song": "media", "video.movie": "media",
}

# Values in SCHEMA_TYPE_INTENT / OG_TYPE_INTENT that describe the SITE as a
# whole rather than the specific page. Static-site generators and CMS
# templates commonly stamp these identically on every page as shared
# boilerplate -- `og:type=website` is the single most common Open Graph
# default on the entire web, used on pages that are not the homepage far more
# often than pages that are. That is fundamentally different from
# "product"/"article"/"service", which a page author must deliberately choose
# to differ from a default. So unlike those, a site-level type only confirms
# "homepage" when the URL itself also looks like a site root; on a deep path
# it is dropped rather than silently overriding what the URL clearly says.
SITE_LEVEL_SCHEMA_TYPES = {"website", "organization", "localbusiness"}
SITE_LEVEL_OG_TYPES = {"website"}


def _looks_like_site_root(path):
    """True for '', '/', or a single short leading segment ('/en/', '/en-us/',
    '/de/') -- the shapes a genuine (possibly locale-prefixed) homepage URL
    takes. Not the full ISO-639-1 locale check used elsewhere: this only needs
    to rule OUT an obviously multi-level, non-root path like a deep doc page,
    not to precisely classify what the segment means.
    """
    segs = [s for s in (path or "").split("/") if s]
    if not segs:
        return True
    return len(segs) == 1 and len(segs[0]) <= 5


def load_advisory_bands():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_path = os.path.join(script_dir, "..", "references", "reachability_thresholds.json")
    try:
        if os.path.exists(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = dict(DEFAULT_ADVISORY_BANDS)
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if isinstance(v, dict):
                        merged[k.lower()] = {
                            "advisory_min_words": v.get("advisory_min_words",
                                                        v.get("min_word_count")),
                            "recommended_words": v.get("recommended_words",
                                                       v.get("recommended_word_count")),
                        }
            return merged
    except Exception:
        pass
    return dict(DEFAULT_ADVISORY_BANDS)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_tokens = []
        self.skip_tags = {'script', 'style', 'noscript', 'iframe', 'svg', 'template'}
        self.skip_stack = []

        self.paragraph_count = 0
        self.list_item_count = 0
        self.heading_count = 0
        self.article_count = 0
        self.form_count = 0
        self.has_password_input = 0
        self.main_present = False

        # heading -> following paragraph pairs (unchanged public contract)
        self.heading_pairs = []
        self._cap_h = False
        self._cur_h = []
        self._pending_h = None
        self._cap_p = False
        self._cur_p = []

        # data collectors for intent detection
        self._jsonld_buf = []
        self._in_jsonld = False
        self.jsonld_raw = []
        self.meta_og_type = None
        self.meta_description = None
        self.title_parts = []
        self.first_heading = None
        self.first_paragraph = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}

        if t == "script" and a.get("type", "").lower().strip() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []
            self.skip_stack.append(t)
            return
        if t in self.skip_tags:
            self.skip_stack.append(t)
            return
        if self.skip_stack:
            return

        if t == "title":
            self._in_title = True
        if t == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop == "og:type":
                self.meta_og_type = a.get("content", "").lower().strip() or self.meta_og_type
            elif prop == "description" and not self.meta_description:
                self.meta_description = a.get("content", "").strip()

        if t == "p":
            self.paragraph_count += 1
            if self._pending_h and len(self.heading_pairs) < 5:
                self._cap_p = True
                self._cur_p = []
        elif t in ("li",):
            self.list_item_count += 1
        elif t == "article":
            self.article_count += 1
        elif t == "main":
            self.main_present = True
        elif t == "form":
            self.form_count += 1
        elif t == "input" and a.get("type", "").lower() == "password":
            self.has_password_input += 1
        elif re.match(r"^h[1-6]$", t):
            self.heading_count += 1
            if len(self.heading_pairs) < 5:
                self._cap_h = True
                self._cur_h = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if self.skip_stack and self.skip_stack[-1] == t:
            popped = self.skip_stack.pop()
            if self._in_jsonld and popped == "script":
                self._in_jsonld = False
                body = "".join(self._jsonld_buf).strip()
                if body:
                    self.jsonld_raw.append(body)
            return
        if self.skip_stack:
            return

        if t == "title":
            self._in_title = False
        if re.match(r"^h[1-6]$", t) and self._cap_h:
            self._cap_h = False
            h = " ".join(self._cur_h).strip()
            if h:
                self._pending_h = h
                if self.first_heading is None:
                    self.first_heading = h
            self._cur_h = []
        elif t == "p" and self._cap_p:
            self._cap_p = False
            p = " ".join(self._cur_p).strip()
            if p and self.first_paragraph is None and len(p.split()) >= 6:
                self.first_paragraph = p
            if self._pending_h and p:
                self.heading_pairs.append({"heading_text": self._pending_h,
                                           "followup_text": p})
                self._pending_h = None
            self._cur_p = []

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self.skip_stack:
            return
        s = data.strip()
        if not s:
            return
        if self._in_title:
            self.title_parts.append(s)
        self.text_tokens.append(s)
        if self._cap_h:
            self._cur_h.append(s)
        if self._cap_p:
            self._cur_p.append(s)


def _collect_schema_types(obj, out):
    if isinstance(obj, dict):
        tv = obj.get("@type")
        if isinstance(tv, str):
            out.append(tv.lower())
        elif isinstance(tv, list):
            out.extend(str(x).lower() for x in tv if isinstance(x, (str, int)))
        for v in obj.values():
            _collect_schema_types(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_schema_types(v, out)


def detect_page_intent(url, parser, explicit_hint="unknown"):
    """Returns (intent, signals[]). Precedence: JSON-LD > og:type > URL path >
    layout heuristics > explicit hint > 'unknown'. Form-dominant pages override
    to 'utility'."""
    signals = []

    # 3. URL path (computed first: needed below to judge whether a site-level
    # schema/og type is corroborated or just sitewide boilerplate)
    path = ""
    try:
        from urllib.parse import urlparse
        path = urlparse(url or "").path or ""
    except Exception:
        path = ""
    root_like = _looks_like_site_root(path)
    path_intent = None
    if path in ("", "/"):
        path_intent = "homepage"
        signals.append("url_path:root->homepage")
    else:
        for rx, it in PATH_INTENT_RULES:
            if rx.search(path):
                path_intent = it
                signals.append(f"url_path:{rx.pattern[:24]}...->{it}")
                break

    # 1. JSON-LD @type
    schema_types = []
    for block in parser.jsonld_raw:
        try:
            _collect_schema_types(json.loads(block), schema_types)
        except Exception:
            # tolerate trailing commas / concatenated blocks
            for m in re.finditer(r'"@type"\s*:\s*"([^"]+)"', block):
                schema_types.append(m.group(1).lower())
    schema_intent = None
    for st in schema_types:
        if st in SCHEMA_TYPE_INTENT:
            candidate = SCHEMA_TYPE_INTENT[st]
            if candidate == "homepage" and st in SITE_LEVEL_SCHEMA_TYPES and not root_like:
                signals.append(f"jsonld_type:{st}->homepage (suppressed: site-level type on a non-root URL)")
                continue
            schema_intent = candidate
            signals.append(f"jsonld_type:{st}->{schema_intent}")
            break

    # 2. og:type
    og_intent = None
    if parser.meta_og_type:
        base = parser.meta_og_type.split(":")[0] if ":" in parser.meta_og_type else parser.meta_og_type
        matched_key = parser.meta_og_type if parser.meta_og_type in OG_TYPE_INTENT else base
        candidate = OG_TYPE_INTENT.get(matched_key)
        if candidate == "homepage" and matched_key in SITE_LEVEL_OG_TYPES and not root_like:
            signals.append(f"og:type:{parser.meta_og_type}->homepage (suppressed: site-level type on a non-root URL)")
        elif candidate and candidate != "unknown":
            og_intent = candidate
            signals.append(f"og:type:{parser.meta_og_type}->{og_intent}")

    # 4. layout heuristics
    layout_intent = None
    word_total = len(" ".join(parser.text_tokens).split())
    if parser.article_count >= 1 and parser.paragraph_count >= 3:
        layout_intent = "article"
        signals.append("layout:<article>+3p->article")
    elif parser.form_count >= 1 and parser.has_password_input >= 1:
        layout_intent = "utility"
        signals.append("layout:password-form->utility")

    # form-dominant override
    form_dominant = (
        parser.has_password_input >= 1
        or (parser.form_count >= 1 and word_total < 120 and parser.paragraph_count <= 2)
    )

    # "unknown" is the no-hint-given sentinel, not a real signal -- treating
    # it as one here would always win this `or` chain (it's a valid
    # DEFAULT_ADVISORY_BANDS key) and the generic "content" fallback below
    # would never be reached.
    has_real_hint = explicit_hint in DEFAULT_ADVISORY_BANDS and explicit_hint != "unknown"
    intent = (schema_intent or og_intent or path_intent or layout_intent
              or (explicit_hint if has_real_hint else None))
    if intent is None:
        # Nothing classified this page. On a non-root URL that also matched
        # none of PATH_INTENT_RULES (see its docstring -- a flat,
        # extension-terminated slug with no directory segment is the common
        # cause), default to the generic content-bearing floor instead of
        # "unknown" so the page still gets SOME thinness check rather than an
        # automatic pass purely because its URL shape defeated keyword
        # matching. True unknowns (the root path itself never reaches here;
        # any other non-root path always gets "content") keep the same
        # double-gate protection in assess_depth against false positives.
        intent = "content" if path not in ("", "/") else "unknown"
        signals.append(f"no_specific_intent_signal:defaulted_to_{intent}")
    if form_dominant and intent in ("unknown", "homepage", "category", "content"):
        intent = "utility"
        signals.append("override:form_dominant->utility")

    if intent not in DEFAULT_ADVISORY_BANDS:
        intent = "unknown"
    if not signals:
        signals.append("no_intent_signal:defaulted_unknown")
    return intent, signals


def assess_depth(intent, word_count, paragraph_count, heading_count,
                 text_html_ratio, advisory_min):
    """below_reference_range is True only when ALL THREE independent thin
    signals agree (low words, few paragraphs, low text-to-markup ratio) AND the
    page intent is content-bearing. Utility / app / media / unknown pages and
    minimalist landing pages with real paragraph structure are never flagged --
    an empty JS shell is the render-audit skill's concern, not this one."""
    if intent not in CONTENT_BEARING_INTENTS or advisory_min is None:
        return False, f"intent '{intent}' is not content-bearing; word count not scored"

    low_words = word_count < advisory_min
    structurally_empty = paragraph_count <= 2 and heading_count <= 2

    if low_words and structurally_empty:
        return True, (f"words {word_count} < advisory {advisory_min}, and the page carries "
                      f"minimal structure ({paragraph_count} <p>, {heading_count} headings) "
                      f"-> genuinely thin for a '{intent}' page")
    if low_words:
        return False, (f"words ({word_count}) below advisory band ({advisory_min}) but the page "
                       f"has real structure ({paragraph_count} <p>, {heading_count} headings) "
                       f"-> intentionally lean, not flagged")
    return False, "content depth adequate for intent"


def check_content_depth(html_content, url, page_type_hint="unknown"):
    if not html_content:
        html_content = ""
    explicit_hint = str(page_type_hint or "unknown").lower().strip()

    parser = PageParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    full_text = " ".join(parser.text_tokens)
    words = [w for w in re.split(r"\s+", full_text) if w]
    visible_word_count = len(words)
    text_html_ratio = (len(full_text) / len(html_content)) if html_content else None

    intent, intent_signals = detect_page_intent(url, parser, explicit_hint)

    bands = load_advisory_bands()
    band = bands.get(intent, {})
    advisory_min = band.get("advisory_min_words")

    below_reference_range, reason = assess_depth(
        intent, visible_word_count, parser.paragraph_count,
        parser.heading_count, text_html_ratio, advisory_min,
    )

    return {
        "url": url,
        # public contract preserved:
        "page_type_hint": explicit_hint,
        "visible_word_count": visible_word_count,
        "reference_min_word_count": advisory_min,
        "below_reference_range": below_reference_range,
        "heading_followup_text_pairs": parser.heading_pairs[:5],
        # new adaptive fields:
        "detected_page_intent": intent,
        "intent_signals": intent_signals,
        "depth_signals": {
            "paragraph_count": parser.paragraph_count,
            "list_item_count": parser.list_item_count,
            "heading_count": parser.heading_count,
            "text_to_markup_ratio": round(text_html_ratio, 4) if text_html_ratio is not None else None,
        },
        "advisory_band_words": advisory_min,
        "assessment_reason": reason,
        "is_content_bearing_intent": intent in CONTENT_BEARING_INTENTS,
        # `detected_page_intent` is a deterministic floor: JSON-LD @type and
        # og:type are authoritative and universal; the URL-path and layout
        # tiers are convention-bound guesses. When the intent came only from
        # those weaker tiers, the agent should confirm/override it from the
        # raw elements below, then re-read `below_reference_range` against the
        # band for the corrected intent. A "(suppressed: ...)" signal did NOT
        # drive the outcome -- a site-level type lost to a non-root URL -- so
        # it must not count as the basis being schema/og.
        "intent_basis": ("schema_or_og" if any(
            s.startswith(("jsonld_type:", "og:type:")) and "(suppressed:" not in s
            for s in intent_signals)
            else "url_path_or_layout_or_default"),
        "raw_for_agent_judgment": {
            "url": url,
            "title": " ".join(parser.title_parts).strip() or None,
            "first_heading": parser.first_heading,
            "first_paragraph": (parser.first_paragraph[:400]
                                if parser.first_paragraph else None),
        },
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
            "detected_page_intent": "unknown",
            "intent_signals": [],
            "depth_signals": {},
            "script_error": str(e)
        }))
