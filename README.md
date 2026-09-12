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
      "id": "freshness-corroboration",
      "path": "skills/freshness-corroboration"
    },
    {
      "id": "engagement-audit",
      "path": "skills/engagement-audit"
    },
    {
      "id": "readability-audit",
      "path": "skills/readability-audit"
    }
  ]
}
```

---

## Marketplace Skills Overview

1. **`audit-orchestrator`** *(Entrypoint Master Skill)*: Coordinates the sequential execution of all 5 specialized sub-skills and synthesizes their raw findings into the final report. There is deliberately no score of any kind, per-category or overall — the handout's required report schema never asks for one; each finding's `severity` (`critical`/`high`/`medium`/`low`) plus its **confidence** (how sure the check is the finding is real, distinct from severity) carry that information instead.
2. **`crawl-access-audit`**: Gathers raw technical accessibility facts — `robots.txt` rules evaluated per RFC 9309 (longest-match, wildcards) and **split by crawler purpose**: live AI-search/assistant retrieval crawlers (`OAI-SearchBot`, `PerplexityBot`, `Claude-SearchBot`, …) versus model-training-only crawlers (`GPTBot`, `ClaudeBot`, `CCBot`, `Google-Extended`, …), verified against each operator's own documentation, so blocking a training crawler is scored very differently from blocking one that feeds live AI search answers; dual-identity browser-vs-bot HTTP fetches (with redirect loop/long-chain detection); **TLS certificate validity** (expired, hostname-mismatched, self-signed, expiring soon); indexing meta tags; XML sitemap health with an adaptive, structurally-grouped **representative page sample** (one URL per URL-structure group, not just the first N listed); and crawl depth.
3. **`crawl-render-audit`**: Evaluates client-side JavaScript rendering barriers, DOM hydration gaps, trapped JSON-LD structured data, and client-side redirects. When no rendered-DOM tool is otherwise available, it can capture one itself via a **locally installed Chrome/Edge/Chromium** (sandboxed, throwaway profile, hard timeout, nothing bundled or downloaded) so raw-vs-rendered comparisons are measured directly instead of inferred from raw HTML alone. When a rendered DOM is available it also measures **content parity** — which sentences exist only after JavaScript runs, quoted verbatim in the finding, so "raw HTML is thin" becomes "here is the text an AI crawler never sees" — and **link discovery**, the internal links a non-JS crawler cannot follow.
4. **`readability-audit`**: Audits Schema.org JSON-LD completeness across 9 schema types — including recovering and explicitly reporting genuinely unparseable JSON-LD (distinguishing "no structured data" from "structured data present but broken") — semantic heading hierarchy (`<h1>`-`<h6>`), non-text machine-readable facts, and tabular data consistency. It also checks **entity grounding** — whether the markup actually answers *who publishes this page* (an `Organization`/`Brand`/`Person` identity anchor on the homepage) and *what the page is about*, catching pages whose only valid schema is their own breadcrumb trail — and whether each entity carries a quotable `description` (a presence/length test; the audit never judges wording). Interior pages already parsed during the run can be passed through `readability.additional_pages` at no extra request cost. Three further checks, all deterministic and zero-extra-request: **question-phrased headings** (a heading ending `?`/`؟` or opening with an interrogative word) are checked for real text — however short — immediately following, since a dangling question with nothing under it gives an answer engine a question with no answer to pair it with; **content front-loading** flags a page whose first substantial block of text is buried deep past mostly-filler content (chrome-excluded, and only when there's enough signal to say so — never a guessed verdict); and **FAQ schema is cross-checked against visible text** via vocabulary overlap (tolerant of paraphrasing, not exact matching) so schema left over from a stale edit, or never actually shown to a visitor, is caught rather than trusted at face value. Two E-E-A-T / trust checks round these out: a real named **author byline** is checked against a narrow, high-confidence list of CMS-default placeholders (`admin`, `webmaster`, …) — never against legitimate organizational bylines like "Staff Writer" — and **NAP (Name/Address/Phone) consistency** confirms `LocalBusiness` schema's contact details actually appear in the page's own visible text, not just in JSON-LD or a `tel:`/click-to-chat link.
5. **`freshness-corroboration`**: Audits content publication/modification dates, copyright year ranges, blog temporal decay, off-site web search citation consistency, and Wikipedia/Wikidata `sameAs` entity links — with confidence-scored candidate matching so a same-named but unrelated entity (a disambiguation page, a namespace page, an unrelated company) is never mistaken for the audited brand. `sameAs` targets are classified: a link to a **public identity registry** (package or code registry, app store, company register, persistent-identifier authority) is a registry-grade anchor of the same kind Wikidata provides, so the optional "no encyclopedia link" nudge is not raised against brands that will never meet encyclopedia notability — while an entry that demonstrably exists off-site but is not linked is reported as the concrete gap it is.
6. **`engagement-audit`**: Audits human visitor orientation, 1-level homepage navigation reachability, content depth vs. adaptive reference ranges, mobile responsiveness viewport tags, cross-page brand phrase consistency (including detection of an identical meta description reused across different pages), page weight resource signals, cold AI-referral landing-page readiness, and (low-severity, informational) trust-page presence — a linked Privacy Policy or Terms page.

---

## Output Report Schema

The marketplace's entrypoint skill (`audit-orchestrator`) emits a single JSON audit report conforming to Adobe's Round 3 problem statement specification:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-06T21:28:45Z",
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
      "title": "AI Crawler Blocked From the Site Root by robots.txt (OAI-SearchBot)",
      "severity": "critical",
      "evidence": "robots.txt disallows the homepage (/) for OAI-SearchBot [retrieval: search_index]. Blocked crawlers that fetch pages for live AI search / assistant answers: ['OAI-SearchBot'].",
      "suggested_action": {
        "summary": "Update robots.txt so OAI-SearchBot may fetch public brand content.",
        "priority": "critical"
      },
      "confidence": 1.0
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

`audit_metadata.robots_restricted_fetches` lists every request the audit declined to make because
`robots.txt` disallowed it (empty when the site permitted everything the audit looked at). All six skills route
every HTTP request through `crawl-access-audit/scripts/robots_gate.py`, which is built from the `robots.txt`
already fetched at the start of the run — so compliance costs no extra requests — and evaluates each request
against **the identity being presented**: the dual-identity fetch's `GPTBot` leg is not sent at all to a site
whose `robots.txt` disallows `GPTBot`. Per RFC 9309, a `404` means nothing is disallowed, while an unreachable
or `5xx` `robots.txt` makes the gate **fail closed** and fetch nothing. A refused fetch is reported as refused,
never as a site defect.

`confidence` (0–1, default 1.0) appears on every finding: how sure the check is the finding is real, as distinct from `severity` (how bad it would be if true).

### No scoring, by design

This report computes no score of any kind — no per-category number, no overall blended figure. The handout's
required schema is `site`/`audited_at`/a severity-count `summary`/`findings`/`suggested_action`, nothing more, and
never asks for one. Each finding's `severity` plus `confidence` carry the information a score would otherwise
compress into a single misleading number.
