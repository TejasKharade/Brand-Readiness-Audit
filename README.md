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
| `audit-orchestrator` *(entrypoint)* | Runs the five sub-skills, turns their raw facts into findings with evidence, severity, confidence and a prioritized suggested action, and writes the report. |
| `crawl-access-audit` | **Can crawlers get in?** robots.txt per RFC 9309 (live AI-search vs. training crawlers), browser-vs-AI-bot fetches (WAF blocks, redirect chains), TLS, noindex/canonical tags, sitemap health with a representative page sample, crawl depth. |
| `crawl-render-audit` | **Can a non-JavaScript crawler see the content?** Raw-vs-rendered text gap, schema injected by JavaScript, client-side redirects, links only JavaScript reveals (optional local headless Chrome/Edge). |
| `readability-audit` | **Can a machine extract the facts?** JSON-LD completeness and errors, heading structure, entity grounding, facts locked in images/SVG/PDFs, FAQ schema vs. visible text, question headings, author and NAP trust signals. |
| `freshness-corroboration` | **Is it current and corroborated?** Publish/modified dates, copyright year, blog recency, on-site facts checked against web search, Wikipedia/Wikidata presence and `sameAs` links, brand-name ambiguity. |
| `engagement-audit` | **Will a visitor stay?** Homepage navigation reachability, content depth, mobile viewport, cross-page brand consistency, page weight, readiness of pages visitors land on from AI answers, privacy/terms pages. |

## How the entrypoint composes them

1. **Access first.** `check_robots.py` runs before anything else, and every later request is checked against
   that robots.txt at no extra cost. Each sampled page is fetched once — as a browser and as an AI bot.
2. **Reuse, don't refetch.** The render, readability, freshness and engagement skills analyse that same HTML.
   Independent calls within a stage run in parallel and every network script has a hard time limit, so an
   audit is designed to finish in under 5 minutes.
3. **Stop on a bot block.** If a WAF blocks or challenges the bot, the on-site content checks are skipped and
   listed in `categories_not_audited` — never reported as "clean". Off-site web-search checks still run.
4. **One judgement layer.** Sub-skills only gather facts; `synthesize_report.py` assigns severity and confidence,
   adds proactive recommendations tied to what was measured, and always writes a schema-valid report.
   `verify_contracts.py` fails if a sub-skill's output drifts from what the orchestrator reads.

## Report

Follows the handout schema — `site`, `audited_at`, counts by severity, and `findings[]` with `id`, `title`,
`severity`, `evidence` and `suggested_action` — plus `confidence`, `proactive_recommendations` and
`audit_metadata` (pages audited, fetches refused by robots.txt, coverage). Every finding's evidence ends with a
plain-English *"What This Means"*, and there is deliberately no score. Full schema:
[`audit_report_schema.json`](skills/audit-orchestrator/references/audit_report_schema.json).
