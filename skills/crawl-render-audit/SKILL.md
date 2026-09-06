---
name: crawl-render-audit
description: Audits website client-side rendering (CSR) barriers, DOM hydration gaps, JS-trapped structured data, and client-side redirects that prevent non-JS AI crawlers (GPTBot, ClaudeBot, PerplexityBot) from discovering key page content.
license: MIT
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
   - **If you do NOT possess a Headless Browser tool**:
     - Fetch the page using your standard HTTP GET tool, pass the payload as `raw_html`, and leave `rendered_html` completely blank/omitted.
     - The Python scripts will dynamically adapt by inspecting `raw_html` for client-side SPA mount points (`div#root`, `div#app`), JS framework signatures, and `<script>` bundles.

## Procedure & Hybrid Execution Flow

1. **Rendering Barriers & Hydration Gap Check (`check_rendering_barriers.py`)**:
   - Run `scripts/check_rendering_barriers.py` to compare word counts, heading sequences (`<h1>`-`<h6>`), and detect SPA framework signatures (`React`, `Vue`, `Angular`, `<div id="root">`).
   - **LLM Semantic Fallback:** If `thin_initial_content_detected: true` or `hydration_ratio < 0.30`, the LLM inspects the rendered DOM to identify high-value brand facts (pricing, specs, brand claims) trapped behind client-side JavaScript.

2. **Structured Data Hydration Check (`check_structured_data_hydration.py`)**:
   - Run `scripts/check_structured_data_hydration.py` to identify JSON-LD Schema entities (`Product`, `Organization`, `Article`, `FAQPage`) present in the rendered DOM but missing from the raw initial HTML payload.
   - **LLM Semantic Fallback:** If `structured_data_hydration_barrier_detected: true`, the LLM evaluates the severity of the hidden metadata for search engine indexing.

3. **Client-Side Redirect Audit (`check_client_side_redirects.py`)**:
   - Run `scripts/check_client_side_redirects.py` to detect `<meta http-equiv="refresh">` tags and `window.location` JS redirects that confuse non-JS indexers.
   - **LLM Semantic Fallback:** If client-side redirects are detected, the LLM evaluates whether non-JS AI crawlers will hit a discovery dead-end.

## Output
Emits a structured JSON evidence payload:

```json
{
  "rendering_barriers": { ... },
  "structured_data_hydration": { ... },
  "client_side_redirects": { ... },
  "llm_semantic_fallbacks": {
    "trapped_fact_observations": "...",
    "indexing_risk_assessment": "..."
  }
}
```

## Guardrails & Constraints
- Read-Only: Never modifies any website.
- Zero External Dependencies: All scripts run locally using standard Python libraries only. No Playwright/Selenium or external API services.
- Bounded Execution: Millisecond script execution time.
- Evidence Only: Provides structured evidence; leaves severity scoring and remediation to the audit-orchestrator.
