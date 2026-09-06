---
name: engagement-audit
description: Audits static HTML human visitor engagement signals including homepage navigation reachability, content depth, mobile responsiveness, cross-page descriptor consistency, and page weight resource signals.
license: MIT
allowed-tools: code_execution, http_client
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

Run `scripts/check_content_depth.py` to evaluate visible word count against reference ranges and extract heading-paragraph text pairs:

```bash
echo '{
  "html": "<page_html>",
  "url": "https://example.com/product/1",
  "page_type_hint": "product"
}' | python skills/engagement-audit/scripts/check_content_depth.py
```

The script extracts visible word count, compares it against reference ranges in `references/reachability_thresholds.json`, and extracts up to 5 `heading_followup_text_pairs` containing `<h2>`/`<h3>` headings and their immediately following `<p>` text.

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

---

### Step 5: Check Page Speed & Resource Signals

Run `scripts/check_page_speed_signals.py` to measure raw page weight signals:

```bash
echo '{
  "html": "<page_html>",
  "url": "https://example.com/page"
}' | python skills/engagement-audit/scripts/check_page_speed_signals.py
```

The script measures HTML byte size, parses `<link rel="stylesheet">`, `<script src>`, and `<img>` tags, issues lightweight `HEAD` requests (capped at the first 15 CSS/JS resources, with `GET` fallback) to sum `total_css_js_bytes`, counts images (`image_count`), and reports raw `resource_count_total` page weight proxy metrics.

---

### Step 6: Agent Qualitative Evaluation (Heading Directness & Description Specificity)

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
    "visible_word_count": 450,
    "reference_min_word_count": 200,
    "below_reference_range": false,
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
    "pages": [
      {
        "url": "https://example.com",
        "title": "Acme Widgets - Home",
        "h1": "Welcome to Acme Widgets",
        "brand_phrase_present_in_title": true,
        "brand_phrase_present_in_h1": true
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
> **Heuristic Starting Point Notice**:
> Content depth word-count reference ranges (in `references/reachability_thresholds.json`) are starting-point heuristics intended to catch extremely thin pages. They vary significantly across site categories (e.g. SaaS dashboards vs. long-form documentation). A word count below reference is a weak signal, NOT proof of a defect.
>
> **Page Speed Resource Measurement Scope**:
> `check_page_speed_signals.py` measures up to 15 CSS and JS resources via lightweight `HEAD` requests (`GET` fallback) to avoid excessive network overhead. Images are counted (`image_count`) without fetching. It reports raw numbers only and does NOT produce a fast/slow verdict.
>
> **Inline CSS Limitation**:
> `check_mobile_responsive_signals.py` inspects inline `<style>` tags only. Lack of inline `@media` rules is a weak signal because modern sites load external CSS stylesheets.
>
> **Navigation Crawl Scope**:
> `check_navigation_reachability.py` checks direct 1-level HTML links on the homepage. JavaScript-rendered mega-menus or multi-click navigation paths are outside this single-pass scope.
