---
name: engagement-audit
description: Audits static HTML human visitor engagement signals including homepage
  navigation reachability, content depth, mobile responsiveness, cross-page descriptor
  consistency, page weight resource signals, cold AI-referral landing readiness
  (orientation, next-step/dead-end risk, placeholder and default-title hygiene), and
  trust-page presence.
license: MIT
compatibility: Requires Python 3 and outbound network access
allowed-tools: Bash Read
---

# `engagement-audit` Skill

Audits static HTML human visitor engagement signals to verify that visitors arriving via AI search referrals can navigate, consume, and orient themselves on target brand pages.

> [!NOTE]
> **Scope Boundaries**:
> - **Excluded**: Analytics platform metrics (Google Analytics, bounce rate, conversion rate), live AI query execution, external review platform ratings, fast/slow performance quality verdicts, and checks duplicated by sibling skills (JSON-LD validation, heading hierarchy, `sameAs` entity links, JS hydration gaps).
> - **Included**: 1-level homepage navigation reachability, content word-count depth vs. reference ranges, mobile responsiveness tags (`<meta viewport>`, inline `@media`), cross-page title/H1 descriptor consistency, page weight resource signals (HTML byte size, CSS/JS Content-Length sums, image counts), and LLM qualitative judgment of heading answer directness and descriptive language specificity.

---

## Inputs

The invoking agent prepares JSON parameters for the execution scripts:

- `homepage_html` *(string)*: Raw HTML of the homepage.
- `homepage_url` *(string)*: Canonical URL of the homepage.
- `key_content_urls` *(list of strings)*: List of high-priority content URLs to verify reachability from the homepage.
- `html` *(string)*: Page HTML content for single-page depth, mobile responsive, or page speed resource audits.
- `url` *(string)*: Canonical URL of the audited page.
- `page_type_hint` *(string, optional)*: `"product"`, `"service"`, `"article"`, or `"unknown"`. Defaults to `"unknown"`.
- `pages` *(list of objects, optional)*: Array of `{"url": "...", "html": "..."}` objects across 2+ pages for cross-page descriptor consistency audits.

---

## Procedure

### Step 1: Check Homepage Navigation Reachability

Run `scripts/check_navigation_reachability.py` to evaluate homepage link reachability:

```bash
echo '{
  "homepage_html": "<html_content>",
  "homepage_url": "https://example.com",
  "key_content_urls": [
    "https://example.com/pricing",
    "https://example.com/features"
  ]
}' | python skills/engagement-audit/scripts/check_navigation_reachability.py
```

The script parses direct `<a href>` links on the homepage (1-level resolution) and checks whether each key content URL is directly reachable from the homepage.

---

### Step 2: Check Content Depth & Extract Text Pairs

Run `scripts/check_content_depth.py` to assess content depth relative to the page's own detected intent and extract heading-paragraph text pairs:

```bash
echo '{
  "html": "<page_html>",
  "url": "https://example.com/product/1",
  "page_type_hint": "product"
}' | python skills/engagement-audit/scripts/check_content_depth.py
```

`page_type_hint` is optional. The script **detects page intent itself** — JSON-LD `@type` and `<meta property="og:type">` are authoritative and universal; a URL-path and layout tier act as a convention-bound fallback. `intent_basis` reports which tier decided. When `intent_basis` is `url_path_or_layout_or_default`, the agent should confirm or override `detected_page_intent` from `raw_for_agent_judgment` (`title`, `first_heading`, `first_paragraph`, `url`) and then re-read `below_reference_range` against the band for the corrected intent.

**A non-root URL that matches none of the path rules gets `content`, not `unknown`.** `PATH_INTENT_RULES` requires a directory-style segment (`/product/…`, `/blog/…`) — a flat, extension-terminated slug with no directory at all (`/vinyl-examination-gloves.htm`, `/widget.php`) structurally can't match any of them, regardless of what the page actually is. Rather than let that URL shape alone silently exempt the page from every content-depth check (the old behavior — `unknown` is not scored), it falls back to the generic, lenient `content` band (same floor as `category`, 60 words). `assess_depth`'s existing double-gate (low words AND ≤2 paragraphs/headings) still protects a legitimately short, well-structured page from a false flag — the wider net only catches pages that are thin by every measure.

**`website`/`Organization`/`LocalBusiness` are a special case, not full authority.** `og:type=website` is the single most common Open Graph default on the entire web — most static-site generators stamp it on every page, not only the homepage (the same is true of a sitewide `Organization`/`WebSite` JSON-LD block many templates repeat on every page). Unlike `product`/`article`/`service`, which an author must deliberately choose per page, these describe the *site*, not this specific page. So they only resolve to `homepage` when the URL also looks like a site root (`/`, or a single short locale segment like `/en/`); on a deeper path (`/documentation/reference-manual/cli/`) they are dropped and the signal falls through to the URL-path/layout tiers instead of forcing every page into `homepage`. A dropped signal still appears in `intent_signals` as `"...->homepage (suppressed: site-level type on a non-root URL)"` for evidence, but does not count toward `intent_basis: "schema_or_og"`.

An advisory word band (`references/reachability_thresholds.json`) is consulted **only for content-bearing intents**, and `below_reference_range` is set **only when the word count, the paragraph count, and the heading count all agree** the page is thin. Utility, app, media, unknown, and minimalist-but-structured pages are never flagged. The script also returns `depth_signals`, `assessment_reason`, and up to 5 `heading_followup_text_pairs`.

---

### Step 3: Check Mobile Responsiveness Signals

Run `scripts/check_mobile_responsive_signals.py` to inspect mobile viewport configuration:

```bash
echo '{
  "html": "<page_html>"
}' | python skills/engagement-audit/scripts/check_mobile_responsive_signals.py
```

The script checks for `<meta name="viewport">` presence and inline `@media` style declarations.

---

### Step 4: Check Cross-Page Descriptor Consistency

Run `scripts/check_descriptor_consistency.py` across 2 or more sampled pages:

```bash
echo '{
  "pages": [
    {"url": "https://example.com", "html": "<homepage_html>"},
    {"url": "https://example.com/about", "html": "<about_page_html>"}
  ]
}' | python skills/engagement-audit/scripts/check_descriptor_consistency.py
```

The script extracts `<title>` and `<h1>` elements across all sampled pages, dynamically detects `candidate_brand_phrase` (from JSON-LD `Organization` or recurring capitalized title/H1 phrases), and checks whether the brand phrase is consistently present across titles and H1 headers.

It also records each page's `<meta name="description">` and reports `duplicate_meta_descriptions` — the identical description (whitespace- and case-insensitive) on two or more **different** pages. That is a template default: the summary stops saying what each page is about, so search results and AI answers cannot tell the pages apart. Pages are compared by host + path (scheme, `www.`, query, fragment and trailing slash ignored), so one page sampled twice — e.g. with and without a tracking parameter — is never reported against itself; `distinct_pages_audited` counts pages on that basis. The orchestrator raises a medium finding naming the shared text and the pages.

---

### Step 5: Check Page Speed & Resource Signals

Run `scripts/check_page_speed_signals.py` to measure raw page weight signals:
> **robots.txt:** every resource this script measures is gated by `crawl-access-audit/scripts/robots_gate.py`. Pass `check_robots.py`'s output as `robots` in the script's JSON input so the gate reuses the robots.txt already fetched (zero extra requests); without it the gate fetches `/robots.txt` once itself rather than proceeding ungated. A refused request comes back marked `skipped_by_robots` with the deciding rule — treat it as *not measured*, never as a fault found in the site.


```bash
echo '{
  "html": "<page_html>",
  "url": "https://example.com/page"
}' | python skills/engagement-audit/scripts/check_page_speed_signals.py
```

The script measures HTML byte size, parses `<link rel="stylesheet">`, `<script src>`, and `<img>` tags, issues lightweight `HEAD` requests (capped at the first 15 CSS/JS resources, with `GET` fallback) to sum `total_css_js_bytes`, counts images (`image_count`), and reports raw `resource_count_total` page weight proxy metrics.

---

### Step 6: Check AI-Referral Landing Readiness

Run `scripts/check_landing_readiness.py` **per sampled page** (homepage plus each deep page):

```bash
echo '{
  "html": "<page_html>",
  "url": "https://example.com/docs/deploy",
  "page_type_hint": "article"
}' | python skills/engagement-audit/scripts/check_landing_readiness.py
```

AI assistants cite **deep** pages, not homepages, so a referred visitor lands mid-site with no journey context. This script treats each page as a cold entry point. It returns:

- **Reliable, deterministic findings** — **Hygiene**: visible placeholder text (`lorem ipsum`, `coming soon`, `TODO:`), a default/empty `<title>` (`Untitled`, `Home`, framework defaults), `href="#"`/empty links, `http://` assets on an `https://` page. And **Content position** — where the first `<h1>` / first substantive `<p>` sits relative to the document, after `<nav>`/`<header>` are discounted.
- **Trust-page presence** (`privacy_policy_present`, `terms_present`) — a direct link/anchor-text scan for a linked Privacy Policy or Terms page (English plus a few common non-English privacy-page slugs). Reported as a **low-severity, informational** signal, deliberately not escalated: its absence is a real gap on a data-collecting commerce/SaaS site and largely moot on a static personal or docs site, and this check has no way to tell those apart — so it states the fact without asserting a severity the site type doesn't support.
- **A keyword-heuristic floor** for orientation and next-step — `orientation_ok_heuristic`, `has_next_step_heuristic`, `gaps_heuristic`. These use an English-leaning lexicon (action verbs, audience cues, interstitial phrases) and **do not generalise well** across languages, sectors, or naming conventions. Use them only when no agent verdict is supplied.
- **`raw_for_agent_judgment`** — the actual page elements: brand-name candidate, description candidate, `<h1>`, `<title>`, the full link inventory (text + href), button texts, and the utility-context flag.
- **`friction_signals`** — cookie-consent containers, age/region/app-install/newsletter interstitial text, a possible login gate. **Reported, never auto-flagged.**

### Step 6b: Agent semantic verdict (authoritative)

From `raw_for_agent_judgment`, the invoking agent judges — in **one batched call across all sampled pages**, working from the extracted strings, **not** by re-reading the pages:

1. `orientation_ok` — can a visitor who landed here cold tell *who this is* and *what they do*, from this page alone? (Consider the brand candidate, description candidate, `<h1>`, and `<title>` together — a logo alt or a header brand link counts.)
2. `has_next_step` — is there a genuine forward action or navigation among the links/buttons? (Any language; a "Kontakt" link, a docs sidebar, a "了解更多" button all count.)

Write the result back as `landing_readiness_summary.agent_verdict = {"orientation_ok": bool, "has_next_step": bool, "notes": "..."}`. The orchestrator prefers this over the heuristic floor; utility pages (`/login`, `/checkout`, …) are exempt from both.

Distinct from siblings: `check_navigation_reachability` asks whether *specific key URLs* are linked from the homepage; this asks whether *this page* gives a cold visitor any way forward. `check_descriptor_consistency` checks the brand *phrase* across pages; this checks whether a lone deep page is *self-orienting*.

---

### Step 7: Agent Qualitative Evaluation (Heading Directness & Description Specificity)

> **Agent-judgment discipline (applies to Steps 2, 6b and 7).** Judge only the short strings the scripts extracted — `heading_followup_text_pairs`, `raw_for_agent_judgment`, title/`<h1>`/first-paragraph — never re-fetch or re-read the full page. Do it in **one batched call per audit** covering every sampled page. These judgments replace keyword/lexicon heuristics precisely so the result generalises across languages, sectors, and site conventions; do not re-introduce fixed phrase lists.

The invoking AI agent performs qualitative evaluation on the `heading_followup_text_pairs` returned in Step 2:

1. **Heading Answer Directness**:
   - For each extracted `{heading_text, followup_text}` pair, evaluate whether the paragraph text directly answers or satisfies the topic introduced by the heading.
   - Record `answers_heading_directly: true | false`.

2. **Generic vs. Concrete Descriptive Language**:
   - Compare extracted paragraph text against calibration examples in `references/generic_language_examples.md`.
   - Identify whether descriptions rely on generic marketing fluff ("industry-leading", "best-in-class") or cite concrete, specific details (exact metrics, specs, SLAs, or workflows).
   - Record `language_style: "generic_fluff" | "concrete_specific"`.

---

## Output Schema

The skill produces a structured JSON summary combining script-computed facts and agent qualitative findings:

```json
{
  "navigation_reachability": {
    "homepage_url": "https://example.com",
    "has_nav_element": true,
    "total_homepage_links": 42,
    "key_content_reachability": [
      {
        "key_content_url": "https://example.com/pricing",
        "directly_linked_from_homepage": true
      }
    ]
  },
  "content_depth": {
    "url": "https://example.com/product/1",
    "page_type_hint": "product",
    "detected_page_intent": "product",
    "intent_signals": ["jsonld_type:product->product", "url_path:/product/...->product"],
    "visible_word_count": 450,
    "reference_min_word_count": 120,
    "below_reference_range": false,
    "depth_signals": {"paragraph_count": 7, "list_item_count": 12, "heading_count": 5, "text_to_markup_ratio": 0.31},
    "assessment_reason": "content depth adequate for intent",
    "is_content_bearing_intent": true,
    "heading_followup_text_pairs": [
      {
        "heading_text": "Product Features",
        "followup_text": "Our platform syncs inventory across 3 channels in real time."
      }
    ]
  },
  "mobile_responsiveness": {
    "viewport_meta_present": true,
    "viewport_meta_content": "width=device-width, initial-scale=1",
    "inline_media_queries_found": true,
    "viewport_and_media_query_both_absent": false
  },
  "descriptor_consistency": {
    "candidate_brand_phrase": "Acme Widgets",
    "pages_audited": 2,
    "distinct_pages_audited": 2,
    "pages": [
      {
        "url": "https://example.com",
        "title": "Acme Widgets - Home",
        "h1": "Welcome to Acme Widgets",
        "meta_description": "Acme Widgets makes industrial widgets.",
        "brand_phrase_present_in_title": true,
        "brand_phrase_present_in_h1": true
      }
    ],
    "duplicate_meta_descriptions": [
      {
        "description": "Acme Widgets makes industrial widgets.",
        "urls": ["https://example.com", "https://example.com/products/w-200"],
        "page_count": 2
      }
    ]
  },
  "page_speed_signals": {
    "url": "https://example.com/page",
    "html_byte_size": 45210,
    "total_css_js_bytes": 128400,
    "css_js_resources_total_found": 12,
    "css_js_resources_measured": 12,
    "image_count": 8,
    "resource_count_total": 20,
    "resource_fetch_errors": []
  },
  "landing_readiness": {
    "url": "https://example.com/docs/deploy",
    "is_utility_context": false,
    "orientation": {
      "brand_name": {"value": "Acme Inc", "sources": ["jsonld_organization"], "present": true},
      "description": {"value": "Acme automates container deploys...", "source": "meta_description", "present": true},
      "topic_sentence": {"h1_text": "How to deploy with Acme", "present": true},
      "audience_cue": {"matched": "for engineering teams", "present": true},
      "signals_present": 3,
      "orientation_ok": true
    },
    "next_step": {
      "primary_ctas": [{"text": "Get started free", "href": "/signup"}],
      "primary_cta_present": true, "persistent_nav_present": true,
      "contact_path_present": false, "internal_link_count": 4,
      "dead_end_risk": false, "has_next_step": true
    },
    "friction_signals": {
      "cookie_container_detected": null, "interstitial_text_detected": [],
      "possible_login_gate": false, "inline_fixed_overlay_hint": false
    },
    "hygiene": {
      "placeholder_text_found": [], "default_or_empty_title": false,
      "title_value": "Deploy Guide | Acme", "empty_or_hash_links": 0,
      "mixed_content_assets": 0
    },
    "content_position": {"first_content_element_index": 14, "total_elements": 60, "first_content_ratio": 0.233},
    "verdict_basis": "keyword_heuristic_floor -- see raw_for_agent_judgment",
    "raw_for_agent_judgment": {
      "url": "https://example.com/docs/deploy", "title": "Deploy Guide | Acme",
      "h1_text": "How to deploy with Acme", "brand_name_candidate": "Acme Inc",
      "description_candidate": "Acme automates container deploys for engineering teams.",
      "subhead_after_h1": "Acme ships your code to production in seconds.",
      "links": [{"text": "Get started free", "href": "/signup"}, {"text": "Docs", "href": "/docs"}],
      "buttons": [], "note": "Judge orientation and next-step from these elements, not the heuristic booleans."
    },
    "gaps_heuristic": [],
    "landing_readiness_summary": {
      "orientation_ok_heuristic": true, "has_next_step_heuristic": true,
      "no_blocking_hygiene_defect": true, "gap_count_heuristic": 0,
      "agent_verdict": {"orientation_ok": true, "has_next_step": true, "notes": "brand in title + logo; docs sidebar nav"}
    }
  },
  "agent_qualitative_assessment": {
    "heading_directness": [
      {
        "heading_text": "Product Features",
        "answers_heading_directly": true
      }
    ],
    "description_specificity": {
      "language_style": "concrete_specific",
      "rationale": "Cites specific inventory sync channels and real-time execution."
    }
  }
}
```

---

## Known Limitations & Guardrails

> [!WARNING]
> **Advisory-Band Notice**:
> The word bands in `references/reachability_thresholds.json` are *advisory only* and are consulted solely for content-bearing page intents. A low word count on its own never produces a finding — `below_reference_range` requires the word count, paragraph count, and heading count to agree, and utility / app / media / unknown intents are exempt entirely. This is what keeps minimalist brand sites, SaaS utility pages, and single-page apps from being false-flagged.
>
> **Page Speed Resource Measurement Scope**:
> `check_page_speed_signals.py` measures up to 15 CSS and JS resources via lightweight `HEAD` requests (`GET` fallback) to avoid excessive network overhead. Images are counted (`image_count`) without fetching. It reports raw numbers only and does NOT produce a fast/slow verdict.
>
> **Inline CSS Limitation**:
> `check_mobile_responsive_signals.py` inspects inline `<style>` tags only. Lack of inline `@media` rules is a weak signal because modern sites load external CSS stylesheets.
>
> **Navigation Crawl Scope**:
> `check_navigation_reachability.py` checks direct 1-level HTML links on the homepage. JavaScript-rendered mega-menus or multi-click navigation paths are outside this single-pass scope.
