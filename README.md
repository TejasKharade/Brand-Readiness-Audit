# Brand AI-Readiness Audit — Agent Skill Marketplace

An agentskills.io marketplace that audits any website for **AI discoverability** (can AI assistants reach, read
and cite it?) and **on-site engagement** (do arriving visitors stay?), and writes one JSON report of
evidence-backed findings with prioritized fixes. [`marketplace.json`](marketplace.json) lists six skills;
`audit-orchestrator` is the single entrypoint.

**Requirements:** Python 3 standard library only (nothing to `pip install`) and network access; an installed
Chrome/Edge/Chromium is optional. To run, invoke the skill `marketplace.json` marks `"entrypoint": true` —
[`skills/audit-orchestrator/SKILL.md`](skills/audit-orchestrator/SKILL.md) — with the URL to audit. An agent
that simply opens this folder is pointed to the same skill by [`AGENTS.md`](AGENTS.md).

## Skills

| Skill | What it does |
|---|---|
| `audit-orchestrator` *(entrypoint)* | • Runs the five sub-skills<br>• Turns their raw facts into findings with evidence, severity, confidence and a prioritized suggested action<br>• Writes the report |
| `crawl-access-audit` | **Can crawlers get in?**<br>• robots.txt per RFC 9309 (live AI-search vs. training crawlers)<br>• Browser-vs-AI-bot fetches (WAF blocks, redirect chains)<br>• TLS<br>• noindex/canonical tags<br>• Sitemap health with a representative page sample<br>• Crawl depth |
| `crawl-render-audit` | **Can a non-JavaScript crawler see the content?**<br>• Raw-vs-rendered text gap<br>• Schema injected by JavaScript<br>• Client-side redirects<br>• Links only JavaScript reveals (optional local headless Chrome/Edge) |
| `readability-audit` | **Can a machine extract the facts?**<br>• JSON-LD completeness and errors<br>• Heading structure<br>• Entity grounding<br>• Facts locked in images/SVG/PDFs<br>• FAQ schema vs. visible text<br>• Question headings<br>• Main content starts near the top, not buried below filler<br>• Author and NAP trust signals |
| `freshness-corroboration` | **Is it current and corroborated?**<br>• Publish/modified dates<br>• Copyright year<br>• Blog recency<br>• On-site facts checked against web search<br>• Wikipedia/Wikidata presence and `sameAs` links<br>• Brand-name ambiguity |
| `engagement-audit` | **Will a visitor stay?**<br>• Homepage navigation reachability<br>• Content depth<br>• Mobile viewport<br>• Cross-page brand consistency<br>• Page weight<br>• Readiness of pages visitors land on from AI answers<br>• Privacy/terms pages |

## How the entrypoint composes them

**Step 1 — Crawl access (runs first)**

- `check_robots.py` runs before anything else; every page request in the audit is checked against robots.txt
- The homepage plus at most one key page are each fetched twice — once as a browser, once as an AI bot
- Sitemap, TLS and crawl-depth checks run in the same step

**Steps 2–5 — Rendering, readability, freshness, engagement**

- Reuse the HTML fetched in Step 1 — the page is not downloaded again
- Their only extra requests:
  - Optional browser render (to compare raw vs. rendered content)
  - Page-weight check (sizes of CSS/JS files)
  - PDF text-layer check
  - Web searches (to corroborate facts off-site)
- Speed:
  - Independent calls within a step are meant to run in parallel
  - Every network script has a hard time limit
  - Together these keep an audit within the 5-minute budget

**If the AI bot is blocked**

- Triggered when the AI-bot fetch is blocked or challenged (e.g. by a WAF)
- Rendering, readability and engagement checks are skipped
- Skipped categories are listed in `categories_not_audited` — never reported as "clean"
- Freshness's off-site web-search checks still run

**Step 6 — Synthesis**

- Sub-skills only gather facts; `synthesize_report.py` turns them into findings with severity, confidence and a
  suggested action
- Proactive recommendations are added only where the measured signals call for them
- A schema-valid report is always written, even if a step failed
- `verify_contracts.py` catches mismatches between what sub-skills output and what synthesis reads

## Report

Follows the handout schema — `site`, `audited_at`, counts by severity, and `findings[]` with `id`, `title`,
`severity`, `evidence` and `suggested_action` — plus `confidence`, `proactive_recommendations` and
`audit_metadata` (pages audited, fetches refused by robots.txt, coverage). Every finding's evidence ends with a
plain-English *"What This Means"*
Full schema:
[`audit_report_schema.json`](skills/audit-orchestrator/references/audit_report_schema.json).
