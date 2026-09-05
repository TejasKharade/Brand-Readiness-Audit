# Brand AI-Readiness Audit Skill Marketplace

This marketplace contains a modular suite of agent skills built according to the **agentskills.io** specification for auditing websites on **AI Discoverability** and **On-Site Engagement**.

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

## Skills Overview

1. **`audit-orchestrator`** (Entrypoint): Receives the website audit request, invokes data gathering & diagnostic sub-skills, synthesizes findings, and emits the final JSON audit report.
2. **`crawl-access-audit`**: Gathers raw technical accessibility facts (robots.txt permissions, dual-identity browser vs. bot HTTP responses, page indexing signals, sitemaps, crawl depth).
3. **`crawl-render-audit`**: Diagnoses crawler accessibility (`robots.txt`), WAF bot blocks, JavaScript rendering dependencies, and non-text locked content.
4. **`freshness-corroboration`**: Audits JSON-LD structured data (`schema.org`), entity clarity, and cross-page fact corroboration.
5. **`engagement-audit`**: Evaluates on-site visitor orientation, context retention, and content clarity.