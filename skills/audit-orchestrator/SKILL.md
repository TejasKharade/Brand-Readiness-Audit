---
name: audit-orchestrator
description: Entrypoint skill that orchestrates a complete Brand AI-Readiness Audit across discoverability and on-site engagement. Invokes sub-skills, synthesizes evidence-backed findings, deduplicates issues, and emits the final structured JSON audit report.
license: MIT
---

# Audit Orchestrator Skill

## When to use
Use as the main entrypoint when requested to conduct an end-to-end Brand AI-Readiness audit for any website domain or URL.

## Inputs
- `url` or `domain`: The target website to audit (e.g. `https://example.com` or `example.com`).

## Procedure

1. **Initialization & Data Gathering (`crawl-access-audit`)**:
   - Parse input website URL.
   - Run `check_robots.py` to extract `resolved_url` and determine AI bot permissions.
   - **Robots Compliance Rule**: If a URL path is disallowed for an AI bot in `robots.txt`, DO NOT perform a bot HTTP fetch on that path; record a blockage finding directly.
   - Run `fetch_dual_identity.py` for reachable pages, `check_page_signals.py`, `check_sitemap.py`, and `check_crawl_depth.py`.

2. **Off-Site & Technical Discovery Diagnosis (`crawl-render-audit`)**:
   - Synthesize results from `crawl-access-audit`.
   - **Sitemap Multi-Field Evaluation**:
     - If `is_sitemap_index: true`, `child_sitemaps_checked: 0`, and `child_sitemap_errors` is non-empty, classify as a *Sitemap Traversal/Fetch Failure*, NOT an empty site.
     - If `child_sitemaps_total > 3`, report `url_count` as a *Sampled URL Count across initial sub-sitemaps*.
   - Identify WAF / Cloudflare bot blocking, dynamic JS rendering dependency, and missing page indexing signals.

3. **Freshness & Entity Clarity Diagnosis (`freshness-corroboration`)**:
   - Validate JSON-LD (`Organization`, `Product`, `FAQPage`, etc.).
   - Check `sameAs` entity link coverage (Wikipedia, Wikidata, official socials).
   - Detect cross-page fact contradictions (pricing, product specs, contact info).

4. **On-Site Engagement & Conversion Diagnosis (`engagement-audit`)**:
   - Assess hero section orientation and value proposition for deep-linked visitors.
   - Evaluate context retention (breadcrumbs, internal navigation pathways).
   - Measure informative content density vs. marketing fluff or popup noise.

5. **Synthesis, Severity Ranking & Deduplication**:
   - Merge findings across all 4 modules. Assign unique IDs (`F-001`, `F-002`, etc.).
   - Map severity levels (`critical`, `high`, `medium`, `low`) based on empirical impact on AI retrieval confidence and visitor conversion.
   - Generate actionable `suggested_action` fixes (including concrete code/JSON-LD snippets).

6. **Report Emission**:
   - Format and output the final audit report JSON according to `references/audit_report_schema.json`.

## Output
Emits a validated JSON report adhering to the standard Audit Report schema.
