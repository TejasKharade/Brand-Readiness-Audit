---
name: crawl-render-audit
description: Audits website client-side rendering (CSR) barriers, DOM hydration gaps, JS-trapped structured data, and client-side redirects that prevent non-JS AI crawlers (GPTBot, ClaudeBot, PerplexityBot) from discovering key page content.
license: MIT
compatibility: Requires Python 3 and outbound network access. Optional - an installed Chrome, Edge or Chromium enables measured raw-vs-rendered comparison via fetch_rendered_dom.py; without one the skill runs raw-HTML-only.
allowed-tools: Bash Read WebFetch
---

# Crawl & Render Audit Skill

## When to use
Use during an AI discoverability audit to identify JavaScript rendering barriers, DOM hydration content gaps, and client-side redirects between raw initial HTML HTTP payloads and fully rendered DOM payloads.

## Inputs
- `raw_html`: Initial raw HTML HTTP response string (string, required).
- `rendered_html`: Fully rendered DOM HTML string (string, optional).
- `url`: Target page URL (string, optional).

## Adaptive Tool Execution Guidance for the Orchestrator
To execute the `crawl-render-audit` skill, the orchestrating LLM must supply page HTML:

1. **Check Available Environment Tools**:
   - **If you possess a Headless Browser tool** (e.g. capable of executing JavaScript and waiting for DOM hydration):
     - Fetch the page via your browser tool and pass the hydrated DOM as `rendered_html`.
     - Fetch the initial HTTP payload via a basic HTTP GET tool (no JS execution) and pass it as `raw_html`.
   - **If you do NOT possess a Headless Browser tool**, first try the bundled renderer:
     ```bash
     echo '{"url": "https://example.com/"}' | python skills/crawl-render-audit/scripts/fetch_rendered_dom.py
> **robots.txt:** the headless render, which pulls the page and every subresource it references, is gated by `crawl-access-audit/scripts/robots_gate.py`. Pass `check_robots.py`'s output as `robots` in the script's JSON input so the gate reuses the robots.txt already fetched (zero extra requests); without it the gate fetches `/robots.txt` once itself rather than proceeding ungated. A refused request comes back marked `skipped_by_robots` with the deciding rule — treat it as *not measured*, never as a fault found in the site.

     ```
     It uses a Chrome, Edge or Chromium browser **already installed** on the machine (nothing is downloaded or bundled) and returns `{available, rendered_html, browser, elapsed_ms, timed_out, error}`. If `available: true`, pass `rendered_html` alongside `raw_html` — the render checks then *measure* the raw-vs-rendered gap instead of inferring it. Safety and budget: the browser sandbox stays on (`--no-sandbox` only with an explicit `allow_no_sandbox: true`), each run uses a throwaway profile (no cookies or logins from the user's browser), images are not loaded, only `http(s)` URLs are accepted, and a hard timeout (default 25 s, max 45 s) kills the whole browser process tree. `settle_ms` (default 5000) is virtual time for scripts and timers to finish after load. A typical page renders in 1–8 s — render the homepage and at most one other key page, not every sampled page.
   - **If there is no browser tool AND `fetch_rendered_dom.py` returns `available: false`** (no browser installed, or running as root on Linux):
     - Fetch the page using your standard HTTP GET tool, pass the payload as `raw_html`, and leave `rendered_html` completely blank/omitted.
     - The Python scripts will dynamically adapt by inspecting `raw_html` for client-side SPA mount points (`div#root`, `div#app`), JS framework signatures, and `<script>` bundles.

## Procedure & Hybrid Execution Flow

1. **Rendering Barriers & Hydration Gap Check (`check_rendering_barriers.py`)**:
   - Run `scripts/check_rendering_barriers.py`. When a rendered DOM is supplied it compares raw vs. rendered across **multiple structural dimensions** — main-area word count, heading count, `<p>`/`<li>` counts, and JSON-LD block count — and flags `thin_initial_content_detected` only when **two or more** of those deltas agree (or the single unambiguous "near-empty raw shell + populated rendered DOM" signal fires). `hydration_ratio` is still reported, but purely as supporting evidence, not as the decision. Raw-only (no rendered DOM) uses **independent shell signals**, any one of which is sufficient, all listed in `barrier_reasons`: a `<noscript>` block declaring JavaScript is required; **0 headings and 0 `<p>` in ≥50 KB of HTML**; ≥20 content blocks averaging <3 words (a hydration shell whose word count squeaks over the floor); a bootstrap signal (mount point / framework bundle / data-island) plus a near-empty content area; an empty custom-element shell; or a self-declared skeleton (`skeleton`/`shimmer`/`ghost-card`/`loading-placeholder` in an id or class) on a page whose raw content is below the 120-word floor — a bare `placeholder` class (input and lazy-image wrappers) never counts, and lazy-section loaders on a content-rich page are not a shell. Mount points are matched **by shape** (`trello-root`, `acme-app`, `react-root-card-back`), not against a fixed id list, and block counts exclude `<nav>`/`<header>`/`<footer>`/`<aside>` so chrome cannot fake the density ratio. This generalises to custom SPA frameworks and to shells with no recognisable framework fingerprint at all.
   - **LLM Semantic Fallback:** If `thin_initial_content_detected: true`, or `structural_delta_signals` is non-empty, or `likely_client_side_rendering_barrier: true`, the LLM inspects the rendered DOM to identify high-value brand facts (pricing, specs, brand claims) trapped behind client-side JavaScript.
   - When a rendered DOM **is** supplied, the same pass also reports two direct measurements of what a
     non-JS crawler actually loses (both `null` when there is no rendered DOM, and neither one changes the
     barrier verdict — they are evidence, not a second detector):
     - `content_parity` — sentences are extracted from the visible text of both documents (boilerplate such as
       cookie banners, nav and footers excluded; entities and punctuation normalised so `&rsquo;` vs `’` is not
       a difference), and the rendered sentences absent from raw HTML are reported **verbatim** in
       `missing_sentences`. `content_parity_pct` is the share of rendered sentences already present in raw HTML.
       The orchestrator quotes the first missing sentences in its CSR finding, turning "raw HTML is thin" into
       "this is the specific text an AI crawler never sees".
     - `link_discovery` — internal `href`s present only after JavaScript runs (`links_only_after_js`).
       Off-site links are excluded, since only same-site links affect what a crawler can reach next. The
       orchestrator raises a **medium** finding when 5 or more internal links exist only after rendering.

2. **Structured Data Hydration Check (`check_structured_data_hydration.py`)**:
   - Run `scripts/check_structured_data_hydration.py` to identify JSON-LD Schema entities (`Product`, `Organization`, `Article`, `FAQPage`) present in the rendered DOM but missing from the raw initial HTML payload.
   - **LLM Semantic Fallback:** If `structured_data_hydration_barrier_detected: true`, the LLM evaluates the severity of the hidden metadata for search engine indexing.

3. **Client-Side Redirect Audit (`check_client_side_redirects.py`)**:
   - Run `scripts/check_client_side_redirects.py` to detect `<meta http-equiv="refresh">` tags and `window.location` JS redirects that confuse non-JS indexers.
   - **LLM Semantic Fallback:** If client-side redirects are detected, the LLM evaluates whether non-JS AI crawlers will hit a discovery dead-end.

## Output

The orchestrator nests the three script outputs verbatim under these exact
keys (this is the contract `audit-orchestrator/scripts/synthesize_report.py`
reads):

```json
{
  "rendering_barriers": {
    "raw_html_present": true,
    "has_rendered_comparison": false,
    "word_counts": {
      "initial_raw_words_total": 0, "initial_raw_words_main_area": 0,
      "effective_raw_words": 0, "rendered_dom_words_total": null,
      "hydration_ratio": null, "hydration_ratio_is_assumed": true
    },
    "hydration_gaps": {
      "thin_initial_content_detected": false,
      "structural_delta_signals": [], "structural_delta_count": 0,
      "skeleton_screen_detected": false,
      "missing_initial_headings_count": 0,
      "raw_structure": { "paragraphs": 0, "list_items": 0, "headings": 0, "jsonld_blocks": 0 },
      "rendered_structure": null
    },
    "client_side_rendering_signals": {
      "spa_mount_points": [], "detected_frameworks": [], "data_islands_detected": [],
      "custom_web_elements_count": 0, "ssr_custom_elements_count": 0,
      "inline_framework_signals": [],
      "likely_client_side_rendering_barrier": false
    },
    "waf_interstitial": { "waf_challenge_detected": false, "waf_signals": [] }
  },
  "structured_data_hydration": {
    "has_rendered_comparison": false,
    "initial_raw_html": { "json_ld_blocks_count": 0, "detected_schema_types": [] },
    "rendered_dom": { "json_ld_blocks_count": null, "detected_schema_types": null },
    "hydration_analysis": {
      "js_trapped_schema_types": [], "js_injected_blocks_count": 0,
      "structured_data_hydration_barrier_detected": null
    }
  },
  "client_side_redirects": {
    "client_side_redirect_detected": false,
    "meta_http_equiv_refreshes": [], "meta_refresh_noop_no_url": [],
    "js_location_redirects": [],
    "spa_client_routing_detected": false, "spa_client_routing_signals": []
  },
  "llm_semantic_fallbacks": {
    "trapped_fact_observations": "...",
    "indexing_risk_assessment": "..."
  }
}
```

Fields that are `null` mean **not determinable in this run** (no rendered DOM
supplied, or `raw_html` missing) — the orchestrator must treat them as
"not audited", never as a pass.

## Known limitations (raw-only mode)

Static analysis of one HTTP payload cannot see: content hidden or revealed by
**external** CSS classes / `@media` queries; **imperatively** attached Shadow
DOM (`el.attachShadow`); JSON-LD or redirects whose target is assigned from a
**runtime variable**; schema injected later by a **tag manager**; `::before` /
`::after` generated text; text painted into `<canvas>` / WebGL; and DOM inside
**cross-origin `<iframe>`s**. These are also invisible to a non-JS AI crawler,
so the skill's blindness matches the crawler it models — but findings produced
without a `rendered_html` comparison are lower-confidence, and the orchestrator
should note that.

## Guardrails & Constraints
- Read-Only: Never modifies any website.
- Zero External Dependencies: All scripts run locally using standard Python libraries only. No Playwright/Selenium or external API services.
- Bounded Execution: Millisecond script execution time.
- Evidence Only: Provides structured evidence; leaves severity scoring and remediation to the audit-orchestrator.
