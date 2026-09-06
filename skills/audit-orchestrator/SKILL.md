---
name: audit-orchestrator
description: Entrypoint master orchestrator skill that coordinates execution across all 5 specialized sub-skills (crawl-access-audit, crawl-render-audit, readability-audit, freshness-corroboration, engagement-audit) and synthesizes the final Brand AI Readiness Audit Report.
license: MIT
allowed-tools: code_execution
---

# `audit-orchestrator` Skill

Serves as the entrypoint master orchestrator for conducting complete end-to-end Brand AI Readiness Audits across target website domains and URLs.

> [!NOTE]
> **Orchestrator Role**:
> The `audit-orchestrator` skill coordinates the sequential execution of all 5 specialized sub-skills (`crawl-access-audit`, `crawl-render-audit`, `readability-audit`, `freshness-corroboration`, `engagement-audit`) and synthesizes their raw JSON findings into a unified, authoritative Brand AI Readiness Audit Report.

---

## Inputs

The orchestrator receives target audit parameters:

- `site` *(string)*: Canonical target website domain or URL (e.g. `"https://example.com"`).
- `skill_outputs` *(object, optional)*: Key-value map of sub-skill JSON output objects (`crawl_access`, `crawl_render`, `readability`, `freshness_corroboration`, `engagement`).
- `findings` *(list of objects, optional)*: Additional explicit findings to inject.
- `proactive_recommendations` *(list of strings, optional)*: Custom remediation recommendations.

---

## Workflow & Sub-Skill Execution Procedure

### Step 1: Crawl Access Audit (`crawl-access-audit`)
Run specialized access scripts to evaluate bot accessibility:
- `scripts/check_robots.py`: Audit `robots.txt` directives for AI crawlers (`GPTBot`, `PerplexityBot`, `ClaudeBot`, `Bytespider`).
- `scripts/fetch_dual_identity.py`: Compare HTTP responses for User-Agent browser vs. AI bot identity.
- `scripts/check_sitemap.py`: Validate XML sitemap presence and reachability.
- `scripts/check_page_signals.py`: Inspect indexing meta tags (`noindex`, `nofollow`, canonicals).
- `scripts/check_crawl_depth.py`: Evaluate internal link structure and URL depth.

### Step 2: Crawl Render Audit (`crawl-render-audit`)
Run rendering barrier scripts:
- `scripts/check_rendering_barriers.py`: Compare initial raw HTML vs. rendered DOM text word counts.
- `scripts/check_structured_data_hydration.py`: Detect JSON-LD schema trapped behind client-side JS execution.
- `scripts/check_client_side_redirects.py`: Detect client-side JS and meta refresh redirects.

### Step 3: Readability Audit (`readability-audit`)
Run structural and semantic audit scripts:
- `scripts/check_structured_data.py`: Validate Schema.org JSON-LD completeness across 9 schema types.
- `scripts/check_semantic_structure.py`: Validate heading hierarchy (`<h1>`, `<h2>`) and outline structure.
- `scripts/check_nontext_facts.py`: Verify machine-readable alternatives for non-text facts.
- `scripts/check_content_consistency.py`: Detect contradiction between tabular markup and prose.

### Step 4: Freshness & Corroboration Audit (`freshness-corroboration`)
Run temporal and corroboration scripts:
- `scripts/check_content_dates.py`: Extract publication, modification, and copyright dates.
- `scripts/check_temporal_decay.py`: Detect post recency decay on blog/listing pages.
- `scripts/check_citation_consistency.py`: Corroborate on-site facts against external web search snippets.
- `scripts/check_entity_disambiguation.py`: Evaluate `sameAs` entity links (Wikidata, Wikipedia).

### Step 5: On-Site Engagement Audit (`engagement-audit`)
Run visitor orientation and engagement scripts:
- `scripts/check_navigation_reachability.py`: Audit 1-level homepage navigation reachability for key URLs.
- `scripts/check_content_depth.py`: Evaluate visible word count against reference thresholds and extract text pairs.
- `scripts/check_mobile_responsive_signals.py`: Check `<meta viewport>` and inline media queries.
- `scripts/check_descriptor_consistency.py`: Audit cross-page brand phrase consistency in titles/H1s.
- `scripts/check_page_speed_signals.py`: Measure HTML byte size, CSS/JS resource bytes, and image counts.

### Step 6: Master Synthesis (`scripts/synthesize_report.py`)

Run `scripts/synthesize_report.py` to aggregate all sub-skill findings:

```bash
echo '{
  "site": "https://example.com",
  "skill_outputs": {
    "crawl_access": { ... },
    "crawl_render": { ... },
    "readability": { ... },
    "freshness_corroboration": { ... },
    "engagement": { ... }
  }
}' | python skills/audit-orchestrator/scripts/synthesize_report.py
```

The script extracts findings across all 5 skills, formats IDs (`F-001`, `F-002`), assigns severities (`critical`, `high`, `medium`, `low`), calculates per-category scores and the overall **Brand AI Readiness Score** (0.0 to 100.0), and outputs a structured JSON report.

---

## Output Schema

Produces the master audit report conforming to `references/audit_report_schema.json`:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-06T21:28:45Z",
  "brand_ai_readiness_score": 75.0,
  "category_scores": {
    "crawl_access": 80.0,
    "crawl_render": 90.0,
    "readability": 85.0,
    "freshness_corroboration": 95.0,
    "engagement": 85.0
  },
  "summary": {
    "total_findings": 3,
    "critical": 1,
    "high": 0,
    "medium": 1,
    "low": 1
  },
  "findings": [
    {
      "id": "F-001",
      "category": "crawl_access",
      "title": "AI Crawler 'GPTBot' is completely blocked by robots.txt",
      "severity": "critical",
      "evidence": "robots.txt contains Disallow: / for User-agent: GPTBot.",
      "suggested_action": {
        "summary": "Update robots.txt to allow GPTBot access to public brand content.",
        "priority": "critical"
      }
    }
  ],
  "proactive_recommendations": [
    "Ensure robots.txt allows access to AI crawler user-agents (GPTBot, PerplexityBot, ClaudeBot).",
    "Implement Server-Side Rendering (SSR) so raw HTML responses contain full text and JSON-LD schema.",
    "Add authoritative sameAs references (Wikidata, Wikipedia, LinkedIn) to Organization schema markup."
  ],
  "audit_metadata": {
    "audited_pages_count": 5,
    "skills_invoked_count": 5,
    "marketplace_version": "1.0.0"
  }
}
```

---

## Guardrails

> [!IMPORTANT]
> **Deterministic Synthesis**:
> `synthesize_report.py` calculates severity deductions deterministically (`critical`: -20.0, `high`: -10.0, `medium`: -5.0, `low`: -2.0) and caps scores between 0.0 and 100.0. All finding IDs strictly adhere to `^F-[0-9]{3,}$`.
