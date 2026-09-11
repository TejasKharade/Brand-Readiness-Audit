# Brand AI-Readiness Audit Skill Marketplace

This repository contains an **Agent Skill Marketplace** built according to the **agentskills.io** specification for automated website auditing across **AI Discoverability** and **On-Site Engagement**.

---

## Marketplace Manifest (`marketplace.json`)

The top-level [`marketplace.json`](file:///c:/Users/Tejas%20Kharade/OneDrive/Desktop/brand%20ai%20readiness/marketplace.json) defines the skill entrypoint and module composition:

```json
{
  "name": "brand-ai-readiness-audit",
  "version": "1.0.0",
  "skills": [
    {
      "id": "audit-orchestrator",
      "path": "skills/audit-orchestrator",
      "entrypoint": true
    },
    {
      "id": "crawl-access-audit",
      "path": "skills/crawl-access-audit"
    },
    {
      "id": "crawl-render-audit",
      "path": "skills/crawl-render-audit"
    },
    {
      "id": "readability-audit",
      "path": "skills/readability-audit"
    },
    {
      "id": "freshness-corroboration",
      "path": "skills/freshness-corroboration"
    },
    {
      "id": "engagement-audit",
      "path": "skills/engagement-audit"
    }
  ]
}
```

---

## Marketplace Skills Overview

1. **`audit-orchestrator`** *(Entrypoint Master Skill)*: Coordinates the sequential execution of all 5 specialized sub-skills, aggregates findings, calculates per-category readiness scores, rolls them up into the overall **Brand AI Readiness Score** (0-100) as a *prerequisite-weighted* mean (`crawl_access` 0.30, `crawl_render` 0.25, `readability` 0.20, `engagement` 0.15, `freshness_corroboration` 0.10) with **foundational gates** (a critical `crawl_access` finding caps the overall at 40, a critical `crawl_render` finding at 55), and emits the final JSON audit report including a `scoring_model` block showing the weights and any gate that fired.
2. **`crawl-access-audit`**: Gathers raw technical accessibility facts (`robots.txt` AI crawler permissions, dual-identity browser vs. bot HTTP fetches, indexing meta tags, XML sitemap health, crawl depth).
3. **`crawl-render-audit`**: Evaluates client-side JavaScript rendering barriers, DOM hydration gaps, trapped JSON-LD structured data, and client-side redirects.
4. **`readability-audit`**: Audits Schema.org JSON-LD completeness across 9 schema types, semantic heading hierarchy (`<h1>`-`<h6>`), non-text machine-readable facts, and tabular data consistency.
5. **`freshness-corroboration`**: Audits content publication/modification dates, copyright year ranges, blog temporal decay, off-site web search citation consistency, and Wikipedia/Wikidata `sameAs` entity links.
6. **`engagement-audit`**: Audits human visitor orientation, 1-level homepage navigation reachability, content depth vs. reference ranges, mobile responsiveness viewport tags, cross-page brand phrase consistency, and page weight resource signals.

---

## Output Report Schema

The marketplace's entrypoint skill (`audit-orchestrator`) emits a single JSON audit report conforming to Adobe's Round 3 problem statement specification:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-06T21:28:45Z",
  "brand_ai_readiness_score": 40.0,
  "category_scores": {
    "crawl_access": 80.0,
    "crawl_render": 90.0,
    "readability": 85.0,
    "freshness_corroboration": 95.0,
    "engagement": 85.0
  },
  "scoring_model": {
    "method": "weighted_with_foundational_gates",
    "weights": { "crawl_access": 0.30, "crawl_render": 0.25, "readability": 0.20, "engagement": 0.15, "freshness_corroboration": 0.10 },
    "weighted_subtotal": 85.8,
    "gates_applied": [
      { "category": "crawl_access", "cap": 40.0, "trigger_finding": "F-001", "reason": "critical 'crawl_access' finding caps overall readiness at 40.0" }
    ]
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