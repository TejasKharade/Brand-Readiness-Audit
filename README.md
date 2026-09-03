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

1. **`audit-orchestrator`** (Entrypoint): Receives the website audit request, invokes sub-skills, synthesizes findings, and emits the final JSON audit report.
2. **`crawl-render-audit`**: Checks crawler accessibility (`robots.txt`), JavaScript rendering dependencies, and text extraction capability.
3. **`freshness-corroboration`**: Audits JSON-LD structured data (`schema.org`), entity clarity, and cross-page fact corroboration.
4. **`engagement-audit`**: Evaluates on-site visitor orientation, context retention, and content clarity.