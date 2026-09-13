
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

# ---------------------------------------------------------------------------
# check_landing_readiness.py  --  engagement-audit
#
# AI assistants cite DEEP pages, not homepages. A visitor arriving from an
# assistant lands mid-site with no journey context. This script evaluates
# whether a single page works as a COLD ENTRY POINT:
#
#   Orientation  -- can the visitor tell who this is and what they do,
#                   from this page alone, without navigating?
#   Next step    -- is there any clear forward action (CTA / nav / contact)?
#   Hygiene      -- placeholder text, default <title>, dead links, mixed content
#   Friction     -- cookie / age / region / app-install / login walls  (reported,
#                   never auto-flagged -- input for orchestrator/LLM judgement)
#
# Deterministic, stdlib only, read-only, operates on already-fetched HTML.
# Emits evidence + multi-signal booleans + a plain-language gap list.
# It does NOT emit a numeric score (that is the orchestrator's job).
# ---------------------------------------------------------------------------

ACTION_LEXICON = [
    "get started", "start free", "start now", "try free", "try it", "try now",
    "sign up", "signup", "create account", "get a demo", "request a demo",
    "book a demo", "request access", "get access", "buy now", "buy", "shop now",
    "add to cart", "subscribe", "download", "install", "get the app",
    "contact sales", "contact us", "talk to sales", "talk to us", "get in touch",
    "request a quote", "get a quote", "book a call", "schedule a call",
    "join now", "join", "register", "learn more", "see pricing", "view pricing",
    "get quote", "start trial", "free trial", "get started free",
]
CTA_CLASS_HINTS = ("btn", "button", "cta", "-primary", "primary-", "hero-cta",
                   "action-button", "signup", "get-started")

CONTACT_HINT_RX = re.compile(
    r"(^|/)(contact|contact-us|support|help|get-in-touch|sales)(/|$|\.)|"
    r"^(mailto:|tel:)", re.I)

# Trust-page presence (privacy/terms): a widely-cited, low-cost trust signal --
# but its absence means very different things on different site types (a
# real problem for a site collecting user data or selling something; largely
# irrelevant for a static personal or docs site with no forms at all). Rather
# than guess site type here, this stays a low-severity, informational signal
# in the orchestrator -- reported as a fact, not asserted as a defect.
PRIVACY_HINT_RX = re.compile(
    r"(^|/)(privacy|privacy-policy|datenschutz|privacidad)(/|$|\.)", re.I)
TERMS_HINT_RX = re.compile(
    r"(^|/)(terms|terms-of-service|terms-and-conditions|tos|legal)(/|$|\.)", re.I)

AUDIENCE_CUE_RX = re.compile(
    r"\b(built|designed|made|created)\s+for\b|"
    r"\bfor\s+(teams|developers|engineers|designers|marketers|founders|"
    r"startups|enterprises?|small\s+business(es)?|agencies|creators|"
    r"individuals|students|freelancers|businesses)\b|"
    r"\bhelps?\s+(you|teams|companies|businesses)\b|"
    r"\bwe\s+help\b|\bwhether\s+you'?re\b", re.I)

PLACEHOLDER_RX = re.compile(
    r"lorem ipsum|dolor sit amet|consectetur adipiscing|"
    r"\bcoming soon\b|under construction|content (goes|to go) here|"
    r"your (text|content|headline) here|insert [\w ]{0,20} here|"
    r"placeholder text|sample text|todo:|fixme:|xxx\b", re.I)

DEFAULT_TITLE_RX = re.compile(
    r"^\s*(untitled( document)?|home|homepage|document|new page|page title|"
    r"welcome to wordpress|my (site|blog|website)|site title|webflow|"
    r"react app|vite \+ \w+|next\.js|nuxt|index|default)\s*$", re.I)

# Known consent-platform container ids/classes -- presence only, non-blocking is common
COOKIE_CONTAINER_RX = re.compile(
    r"onetrust-banner-sdk|ot-sdk-container|cookiebot|cookie-consent|"
    r"cookie-banner|cc-window|cookie-notice|gdpr-consent|"
    r"cookielaw|truste_|didomi-|usercentrics", re.I)

INTERSTITIAL_TEXT_RX = re.compile(
    r"\bare you (over |at least )?(18|21)\b|confirm your age|verify your age|"
    r"select your (country|region|location)|choose your (country|region)|"
    r"open in (the )?app|download (our|the) app|continue in app|"
    r"subscribe to (our )?newsletter to (continue|read)|"
    r"enter your email to (continue|unlock)", re.I)

SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}
BOILERPLATE_TAGS = {"nav", "header", "footer", "aside"}


def _schema_walk(obj, out):
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t] if t else []
        types = [str(x).rsplit("/", 1)[-1].lower() for x in types]
        if any(x in ("organization", "localbusiness", "corporation", "ngo",
                     "onlinebusiness", "website") for x in types):
            if obj.get("name") and not out.get("name"):
                out["name"] = str(obj["name"]).strip()
            if obj.get("description") and not out.get("description"):
                out["description"] = str(obj["description"]).strip()
        for v in obj.values():
            _schema_walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _schema_walk(v, out)


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = []
        self._el_index = 0

        self.title_parts = []
        self._in_title = False
        self.meta = {}                    # name/property -> content

        self._jsonld_buf = []
        self._in_jsonld = False
        self.jsonld_raw = []

        self.first_h1 = None
        self._cap_h1 = False
        self._cur_h1 = []
        self._h1_el_index = None

        self._pending_after_h1 = False
        self.first_p_after_h1 = None
        self.first_substantive_p = None
        self._first_p_el_index = None
        self._cap_p = False
        self._cur_p = []
        self._cur_p_index = None
        self._in_boiler = 0

        self.links = []                   # {text, href, cls}
        self._cap_a = False
        self._cur_a = []
        self._cur_a_href = None
        self._cur_a_cls = ""

        self.buttons = []
        self._cap_btn = False
        self._cur_btn = []

        self.has_nav = False
        self.header_link_count = 0
        self._in_header = 0
        self.password_inputs = 0
        self.form_count = 0

        self.asset_urls = []              # (kind, url)
        self.logo_alts = []
        self.inline_overlay_hint = False

        self.visible_text_parts = []

    # ---- helpers ----
    def _text_ok(self):
        return not self._skip

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        self._el_index += 1

        if t == "script" and a.get("type", "").lower().strip() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []
            self._skip.append(t)
            return
        if t in SKIP_TEXT_TAGS:
            self._skip.append(t)
            return
        if self._skip:
            return

        if t in BOILERPLATE_TAGS:
            self._in_boiler += 1
        if t == "header":
            self._in_header += 1
        if t == "nav" or a.get("role", "").lower() == "navigation":
            self.has_nav = True

        if t == "title":
            self._in_title = True
        elif t == "meta":
            key = (a.get("name") or a.get("property") or "").lower().strip()
            if key:
                self.meta.setdefault(key, a.get("content", "").strip())
        elif t == "h1" and self.first_h1 is None:
            self._cap_h1 = True
            self._cur_h1 = []
            self._h1_el_index = self._el_index
        elif t == "p":
            self._cap_p = True
            self._cur_p = []
            self._cur_p_index = self._el_index
        elif t == "a":
            self._cap_a = True
            self._cur_a = []
            self._cur_a_href = a.get("href")
            self._cur_a_cls = a.get("class", "").lower()
            if self._in_header > 0 and self._cur_a_href:
                self.header_link_count += 1
        elif t == "button":
            self._cap_btn = True
            self._cur_btn = []
        elif t == "form":
            self.form_count += 1
        elif t == "input" and a.get("type", "").lower() == "password":
            self.password_inputs += 1
        elif t == "img":
            src = a.get("src") or a.get("data-src") or ""
            alt = a.get("alt", "")
            cls = a.get("class", "").lower()
            if "logo" in cls or "logo" in src.lower() or "logo" in alt.lower():
                self.logo_alts.append(alt.strip())
            if src.startswith("http://"):
                self.asset_urls.append(("img", src))
        elif t in ("script", "link"):
            src = a.get("src") or a.get("href") or ""
            if src.startswith("http://"):
                self.asset_urls.append((t, src))

        style = a.get("style", "").replace(" ", "").lower()
        if ("position:fixed" in style or "position:sticky" in style) and \
           ("z-index:9" in style or "z-index:1000" in style or "z-index:99" in style):
            self.inline_overlay_hint = True

        idc = (a.get("id", "") + " " + a.get("class", "")).lower()
        if COOKIE_CONTAINER_RX.search(idc):
            self._cookie_hit = getattr(self, "_cookie_hit", None) or idc.strip()[:80]

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._skip and self._skip[-1] == t:
            popped = self._skip.pop()
            if self._in_jsonld and popped == "script":
                self._in_jsonld = False
                body = "".join(self._jsonld_buf).strip()
                if body:
                    self.jsonld_raw.append(body)
            return
        if self._skip:
            return

        if t in BOILERPLATE_TAGS and self._in_boiler > 0:
            self._in_boiler -= 1
        if t == "header" and self._in_header > 0:
            self._in_header -= 1

        if t == "title":
            self._in_title = False
        elif t == "h1" and self._cap_h1:
            self._cap_h1 = False
            self.first_h1 = " ".join(self._cur_h1).strip() or None
            self._pending_after_h1 = self.first_h1 is not None
        elif t == "p" and self._cap_p:
            self._cap_p = False
            txt = " ".join(self._cur_p).strip()
            wc = len(txt.split())
            if self._pending_after_h1 and self.first_p_after_h1 is None and wc >= 4:
                self.first_p_after_h1 = txt
                self._pending_after_h1 = False
            if wc >= 15 and self.first_substantive_p is None and self._in_boiler == 0:
                self.first_substantive_p = txt
                self._first_p_el_index = self._cur_p_index
        elif t == "a" and self._cap_a:
            self._cap_a = False
            self.links.append({
                "text": " ".join(self._cur_a).strip(),
                "href": self._cur_a_href,
                "cls": self._cur_a_cls,
            })
        elif t == "button" and self._cap_btn:
            self._cap_btn = False
            self.buttons.append(" ".join(self._cur_btn).strip())

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._skip:
            return
        s = data.strip()
        if not s:
            return
        if self._in_title:
            self.title_parts.append(s)
        self.visible_text_parts.append(s)
        if self._cap_h1:
            self._cur_h1.append(s)
        if self._cap_p:
            self._cur_p.append(s)
        if self._cap_a:
            self._cur_a.append(s)
        if self._cap_btn:
            self._cur_btn.append(s)


def _is_utility_context(url, page_type_hint, parser=None, word_count=None):
    """Utility pages (auth, cart, checkout, search) are exempt from
    cold-landing expectations.

    Detection is primarily STRUCTURAL so it works in any language: a password
    input, or a form-dominant page with almost no prose, is an auth/transaction
    screen whether its URL says /login, /anmelden, /connexion or /iniciar-sesion.
    The English URL-path list is only an additional hint, never the sole test.
    Returns (is_utility, reason)."""
    if str(page_type_hint or "").lower() in ("utility", "app"):
        return True, f"caller supplied page_type_hint='{page_type_hint}'"

    # --- structural, language-independent ---
    if parser is not None:
        if getattr(parser, "password_inputs", 0) >= 1:
            return True, "page contains a password input (authentication screen)"
        wc = word_count if word_count is not None else 0
        forms = getattr(parser, "form_count", 0) or 0
        if forms >= 1 and wc < 120 and parser.first_h1 is None:
            return True, (f"form-dominant page ({forms} form(s), {wc} words, no <h1>) "
                          f"-- a transaction/search screen, not a content page")

    # --- URL-path hint (English conventions only; a supplement, not the test) ---
    path = ""
    try:
        path = urlparse(url or "").path.lower()
    except Exception:
        pass
    if re.search(r"/(login|log-in|signin|sign-in|signup|sign-up|register|account|"
                 r"cart|checkout|basket|search|404|not-found|reset-password)(/|$)", path):
        return True, "URL path matches a known utility route"
    return False, "not a utility page"


def check_landing_readiness(html, url, page_type_hint="unknown"):
    html = html or ""
    p = LandingParser()
    try:
        p.feed(html)
    except Exception:
        pass

    title = " ".join(p.title_parts).strip()
    full_text = " ".join(p.visible_text_parts)

    # ---- brand name ----
    schema_org = {}
    for block in p.jsonld_raw:
        try:
            _schema_walk(json.loads(block), schema_org)
        except Exception:
            m = re.search(r'"name"\s*:\s*"([^"]{2,80})"', block)
            if m and "name" not in schema_org:
                schema_org["name"] = m.group(1).strip()

    brand_val, brand_sources = None, []
    if schema_org.get("name"):
        brand_val = schema_org["name"]; brand_sources.append("jsonld_organization")
    if p.meta.get("og:site_name"):
        brand_val = brand_val or p.meta["og:site_name"]; brand_sources.append("og:site_name")
    if not brand_val and title:
        parts = re.split(r"\s[|–—\-]\s", title)
        if len(parts) > 1 and 1 <= len(parts[-1].split()) <= 5:
            brand_val = parts[-1].strip(); brand_sources.append("title_suffix")
    if not brand_val:
        for alt in p.logo_alts:
            if alt and 1 <= len(alt.split()) <= 6:
                brand_val = alt; brand_sources.append("logo_alt"); break

    # ---- description of what the org does ----
    desc_val, desc_source = None, None
    if p.meta.get("description") and len(p.meta["description"].split()) >= 4:
        desc_val, desc_source = p.meta["description"], "meta_description"
    elif schema_org.get("description") and len(schema_org["description"].split()) >= 4:
        desc_val, desc_source = schema_org["description"], "jsonld_description"
    elif p.first_p_after_h1 and len(p.first_p_after_h1.split()) >= 6:
        desc_val, desc_source = p.first_p_after_h1, "subhead_paragraph"
    elif p.meta.get("og:description") and len(p.meta["og:description"].split()) >= 4:
        desc_val, desc_source = p.meta["og:description"], "og:description"

    topic_present = bool(p.first_h1)
    audience_match = None
    m = AUDIENCE_CUE_RX.search(full_text[:4000])
    if m:
        audience_match = m.group(0)

    orient_signals = sum([bool(brand_val), bool(desc_val), topic_present])
    orientation_ok = orient_signals >= 2

    # ---- next step ----
    ctas = []
    for lnk in p.links:
        tl = lnk["text"].lower().strip()
        if not tl and not lnk["cls"]:
            continue
        is_action = (any(tl == kw or tl.startswith(kw + " ") or kw in tl
                         for kw in ACTION_LEXICON)
                     or any(h in lnk["cls"] for h in CTA_CLASS_HINTS))
        if is_action and lnk["href"] and not str(lnk["href"]).startswith("#"):
            ctas.append({"text": lnk["text"][:60], "href": lnk["href"][:120]})
    for bt in p.buttons:
        if bt and any(kw in bt.lower() for kw in ACTION_LEXICON):
            ctas.append({"text": bt[:60], "href": None})
    ctas = ctas[:6]

    contact_present = any(
        (lnk["href"] and CONTACT_HINT_RX.search(str(lnk["href"]))) or
        re.search(r"\bcontact\b|\bget in touch\b|\bsupport\b", lnk["text"], re.I)
        for lnk in p.links
    )
    privacy_policy_present = any(
        (lnk["href"] and PRIVACY_HINT_RX.search(str(lnk["href"]))) or
        re.search(r"\bprivacy\s*(policy)?\b", lnk["text"], re.I)
        for lnk in p.links
    )
    terms_present = any(
        (lnk["href"] and TERMS_HINT_RX.search(str(lnk["href"]))) or
        re.search(r"\bterms\b|\bconditions\b", lnk["text"], re.I)
        for lnk in p.links
    )
    internal_links = 0
    host = ""
    try:
        host = urlparse(url or "").netloc.lower().lstrip("www.")
    except Exception:
        pass
    for lnk in p.links:
        h = lnk["href"]
        if not h or str(h).startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            lh = urlparse(urljoin(url or "", h)).netloc.lower().lstrip("www.")
        except Exception:
            lh = ""
        if not lh or lh == host:
            internal_links += 1

    persistent_nav = p.has_nav or p.header_link_count >= 3
    utility_ctx, utility_reason = _is_utility_context(
        url, page_type_hint, parser=p, word_count=len(full_text.split()))
    dead_end_risk = (not ctas and not persistent_nav and not contact_present
                     and internal_links < 5 and not utility_ctx)
    has_next_step = bool(ctas or persistent_nav or contact_present or internal_links >= 5)

    # ---- friction (reported, not auto-flagged) ----
    friction = {
        "cookie_container_detected": getattr(p, "_cookie_hit", None),
        "interstitial_text_detected": sorted(set(
            m.group(0).lower() for m in INTERSTITIAL_TEXT_RX.finditer(full_text[:6000])
        ))[:4],
        "possible_login_gate": bool(
            p.password_inputs and len(full_text.split()) < 120 and not utility_ctx),
        "inline_fixed_overlay_hint": p.inline_overlay_hint,
    }

    # ---- hygiene (cheap, near-zero false positive) ----
    placeholder_hits = sorted(set(
        m.group(0).lower() for m in PLACEHOLDER_RX.finditer(full_text)
    ))[:5]
    default_title = (not title) or bool(DEFAULT_TITLE_RX.match(title))
    empty_links = sum(1 for lnk in p.links
                      if lnk["href"] in (None, "", "#") or str(lnk["href"]).strip() == "#")
    mixed_content = 0
    if str(url or "").startswith("https://"):
        mixed_content = len(p.asset_urls)

    # ---- content position ----
    total_el = max(p._el_index, 1)
    first_content_idx = None
    for cand in (p._h1_el_index, p._first_p_el_index):
        if cand is not None:
            first_content_idx = cand if first_content_idx is None else min(first_content_idx, cand)
    first_content_ratio = round(first_content_idx / total_el, 3) if first_content_idx else None

    # ---- confident gaps only (utility pages such as /login are exempt from
    #      cold-landing expectations -- an assistant will not cite them as an
    #      answer, so their raw signals are recorded but not raised as gaps) ----
    gaps = []
    if not orientation_ok and not utility_ctx:
        missing = []
        if not brand_val:   missing.append("brand/organization name")
        if not desc_val:    missing.append("one-line description of what the brand does")
        if not topic_present: missing.append("a topic-defining <h1>")
        gaps.append("Cold-landing orientation gap: page is missing " +
                    ", ".join(missing) + " -- a visitor arriving here from an AI "
                    "assistant cannot tell who this is or what they offer.")
    if dead_end_risk:
        gaps.append("Dead-end page: no primary call-to-action, no persistent "
                    "navigation, no contact path, and fewer than 5 internal links "
                    "-- the visitor has nowhere to go next.")
    if placeholder_hits:
        gaps.append(f"Placeholder / unfinished text visible on the page: {placeholder_hits}.")
    if default_title:
        gaps.append(f"Default or empty <title> ('{title}') -- the browser tab, "
                    "search snippet, and shared-link preview carry no brand or topic.")

    # Raw page elements for the agent's semantic verdict. The keyword-driven
    # fields below (primary_cta_present, dead_end_risk, audience_cue, the
    # interstitial text list) are an English-leaning HEURISTIC FLOOR only --
    # the agent should judge "does this orient a cold visitor" and "is there a
    # real next step" from these raw elements, which generalise across
    # languages, site types, and naming conventions.
    link_inventory = [{"text": l["text"][:80], "href": l["href"]}
                      for l in p.links if (l["text"].strip() or l["href"])][:40]
    raw_for_agent_judgment = {
        "url": url,
        "page_type_hint": str(page_type_hint or "unknown").lower(),
        "is_utility_context": utility_ctx,
        "utility_context_reason": utility_reason,
        "title": title or None,
        "h1_text": p.first_h1,
        "brand_name_candidate": brand_val,
        "description_candidate": desc_val[:400] if desc_val else None,
        "subhead_after_h1": p.first_p_after_h1,
        "links": link_inventory,
        "buttons": [b[:80] for b in p.buttons if b.strip()][:20],
        "note": ("Judge orientation (can a cold visitor tell who this is and "
                 "what they do?) and next-step (is there a real forward action "
                 "or navigation?) from these elements. Do NOT rely on the "
                 "heuristic booleans; they miss non-English and non-SaaS "
                 "phrasing. Hygiene findings (placeholder text, default title, "
                 "mixed content) are reliable as-is."),
    }

    return {
        "url": url,
        "page_type_hint": str(page_type_hint or "unknown").lower(),
        "is_utility_context": utility_ctx,
        "utility_context_reason": utility_reason,
        "verdict_basis": "keyword_heuristic_floor -- see raw_for_agent_judgment",
        "raw_for_agent_judgment": raw_for_agent_judgment,
        "orientation": {
            "brand_name": {"value": brand_val, "sources": brand_sources, "present": bool(brand_val)},
            "description": {"value": (desc_val[:300] if desc_val else None),
                            "source": desc_source, "present": bool(desc_val)},
            "topic_sentence": {"h1_text": p.first_h1, "present": topic_present},
            "audience_cue": {"matched": audience_match, "present": bool(audience_match)},
            "signals_present": orient_signals,
            "orientation_ok": orientation_ok,
        },
        "next_step": {
            "primary_ctas": ctas,
            "primary_cta_present": bool(ctas),
            "persistent_nav_present": persistent_nav,
            "contact_path_present": contact_present,
            # Informational trust-page signals -- not folded into
            # has_next_step/dead_end_risk, since their absence is a very
            # different-severity problem on a data-collecting commerce/SaaS
            # site than on a static personal or docs site with no forms.
            "privacy_policy_present": privacy_policy_present,
            "terms_present": terms_present,
            "internal_link_count": internal_links,
            "dead_end_risk": dead_end_risk,
            "has_next_step": has_next_step,
        },
        "friction_signals": friction,
        "hygiene": {
            "placeholder_text_found": placeholder_hits,
            "default_or_empty_title": default_title,
            "title_value": title,
            "empty_or_hash_links": empty_links,
            "mixed_content_assets": mixed_content,
        },
        "content_position": {
            "first_content_element_index": first_content_idx,
            "total_elements": total_el,
            "first_content_ratio": first_content_ratio,
        },
        "gaps_heuristic": gaps,
        "landing_readiness_summary": {
            "orientation_ok_heuristic": orientation_ok,
            "has_next_step_heuristic": has_next_step,
            "no_blocking_hygiene_defect": not (placeholder_hits or default_title),
            "gap_count_heuristic": len(gaps),
            "agent_verdict": None,
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
    return res[0].lstrip("\ufeff") if res else ""


if __name__ == "__main__":
    try:
        html = ""
        url = ""
        page_type_hint = "unknown"
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html = params.get("html", "")
                    url = params.get("url", "")
                    page_type_hint = params.get("page_type_hint", "unknown")
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

        if not html:
            html = params.get("html", "")
        if not url:
            url = params.get("url", "")
        if page_type_hint == "unknown":
            page_type_hint = params.get("page_type_hint", "unknown")

        print(json.dumps(check_landing_readiness(html, url, page_type_hint), indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None, "gaps": [], "landing_readiness_summary": {},
            "script_error": str(e),
        }))
