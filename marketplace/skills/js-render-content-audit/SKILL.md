---
name: js-render-content-audit
description: Audits web pages for client-side JavaScript rendering gaps, empty-shell SPA pitfalls, delayed JSON-LD schema timing, and navigation reachability using a two-pass semantic parity diff.
license: MIT
---

# JavaScript Rendering & Content Parity Audit

## When to use
Use this skill when evaluating whether an AI search crawler (which extracts content via fast raw HTTP GET) can access a website's load-bearing text, headings, and schema, or if critical brand information is trapped inside unrendered client-side JavaScript.

## Inputs
* `domain_or_url`: Target domain or page URL (e.g., `https://example.com`).
* `--input-json` (Optional): Path to Skill 1's output JSON containing `sampled_pages["curated_sample"]`.

## Procedure
1. **Locate System Browser**: The bundled script auto-detects host Chrome/Edge/Chromium (`--headless --dump-dom`).
2. **Execute Two-Pass Comparison**:
   * Run the audit script:
     ```bash
     python scripts/check_render.py <domain_or_url> [--input-json <path>] --json
     ```
   * **Pass A**: Fetches raw HTML stream with `OAI-SearchBot` User-Agent.
   * **Pass B**: Captures the fully hydrated DOM via the host's headless browser.
3. **Analyze Content Parity**:
   * The script strips non-content boilerplate (`<nav>`, `<footer>`, `<aside>`, `<script>`, `<style>`, cookie/modal dialogs) and computes substantive sentence containment.
   * Review `missing_snippets_sample` in `render_profile`:
     * **Flag as Critical/High**: If missing text contains core brand identity, product descriptions, pricing, installation guides, documentation, or primary `<h1>`.
     * **Dismiss as Harmless**: If missing text is dynamic UI boilerplate (cookie text, cart counters, theme toggles, live chat greetings).
4. **Inspect Structured Data Timing**:
   * If JSON-LD schema types exist in Pass B but are missing from Pass A, flag `STRUCTURED_DATA_TIMING` (High severity). Crawlers do not execute JavaScript just to extract metadata.
5. **Inspect Link Discovery**:
   * If internal navigation links only exist after JavaScript execution, flag `INTERNAL_LINK_DISCOVERY_GAP` (Medium severity).

## Output
Emits structured JSON conforming to the marketplace standard:
* `site`: Audited domain.
* `summary`: Counts of `critical`, `high`, `medium`, and `low` findings.
* `findings`: Array of findings with `id`, `code`, `title`, `severity`, `evidence`, and `suggested_action`.
* `render_profile`: Per-page parity percentages, latency, and sample missing snippets consumed by downstream skills.
