---
name: structured-data-entity-audit
description: Audits web pages for Schema.org entity grounding, authoritative sameAs disambiguation, atomic fact consistency (pricing, availability, versioning), and description extractability.
license: MIT
---

# Structured Data & Entity Grounding Audit

## When to use
Use this skill when auditing a website's Knowledge Graph grounding and structured data accuracy for AI search engines (ChatGPT Search, Perplexity, Claude). It identifies entity ambiguity (the Garage problem), fact contradictions between schema and on-page text, vacuous descriptions, and client-JS-deferred schema.

## Inputs
* `domain_or_url`: Target domain or page URL (e.g., `https://example.com`).
* `--input-access` (Optional): Path to Skill 1 output JSON containing `sampled_pages["curated_sample"]`.
* `--input-render` (Optional): Path to Skill 2 output JSON containing `render_profile` for JS timing validation.

## Procedure
1. **Execute Entity & Schema Audit**:
   Run the audit script:
   ```bash
   python scripts/check_schema.py <domain_or_url> [--input-access <path>] [--input-render <path>] --json
   ```
2. **Evaluate Root Entity Grounding (`ENTITY_ROOT_GROUNDING`)**:
   * Inspect the homepage for `Organization`, `Brand`, or `SoftwareApplication`.
   * Verify presence of authoritative `sameAs` links (Wikidata, GitHub, Crates.io, LinkedIn, Crunchbase) using [references/schema_entity_rules.md](references/schema_entity_rules.md).
   * Flag missing entity grounding as High severity for niche developer/SaaS tools (prevents AI engines from conflating the brand or citing third-party mirrors).
3. **Cross-Examine Atomic Facts (`SCHEMA_FACT_CONTRADICTION`)**:
   * Compare schema values (`offers.price`, `availability`, `softwareVersion`) against visible on-page text.
   * Flag contradictions where schema claims obsolete or conflicting facts that induce AI hallucinations.
4. **Inspect Extractability & Fluff (`SCHEMA_DESCRIPTION_VACUOUS`)**:
   * Check schema `description` strings against the low-entropy buzzword corpus in [references/schema_entity_rules.md](references/schema_entity_rules.md).
   * Flag empty descriptions or generic marketing filler that provides zero extractable facts for RAG embeddings.
5. **Detect JS-Deferred Schema (`SCHEMA_TIMING_JS_DEFERRED`)**:
   * If `--input-render` indicates JSON-LD was only injected after client JS execution, flag schema delivery timing.

## Output
Emits standard JSON containing:
* `site`: Audited domain.
* `summary`: Finding counts by severity (`critical`, `high`, `medium`, `low`).
* `findings`: Diagnostic findings with causal evidence and actionable remediation.
* `entity_profile`: Discovered entity types, declared `sameAs` authorities, and schema coverage.
