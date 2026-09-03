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

1. **Initialization & Dispatch**:
   - Parse input website URL.
   - Invoke `crawl-render-audit` to evaluate off-site crawlability, AI bot blocking (`robots.txt`), and JavaScript rendering dependencies.
   - Invoke `freshness-corroboration` to inspect JSON-LD structured data (`schema.org`), fact consistency, and entity clarity across pages.
   - Invoke `engagement-audit` to assess on-site orientation, visitor retention signals, and content density.

2. **Synthesis & Deduplication**:
   - Merge findings from all three audit modules.
   - Assign unique identifiers (`F-001`, `F-002`, etc.) to each distinct issue.
   - Map severity levels (`critical`, `high`, `medium`, `low`) based on empirical impact on AI discovery and visitor engagement.

3. **Action & Prioritization Generation**:
   - Formulate concrete, mechanism-sound `suggested_action` recommendations for each finding.
   - Generate proactive recommendations for areas where discoverability or engagement can be strengthened even without explicit defects.

4. **Report Emission**:
   - Format and output the final audit report JSON according to the mandatory schema definition in `references/audit_report_schema.json`.

## Output
Emits a validated JSON report adhering to the standard Audit Report schema.
