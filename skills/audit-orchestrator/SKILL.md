---
name: audit-orchestrator
description: Entrypoint master orchestrator skill that coordinates execution across all 5 specialized sub-skills (crawl-access-audit, crawl-render-audit, readability-audit, freshness-corroboration, engagement-audit) and synthesizes the final Brand AI Readiness Audit Report.
license: MIT
compatibility: Requires Python 3 and outbound network access
allowed-tools: Bash Read WebFetch WebSearch
---

# `audit-orchestrator` Skill

Serves as the entrypoint master orchestrator for conducting complete end-to-end Brand AI Readiness Audits across target website domains and URLs.

> [!NOTE]
> **Orchestrator Role**:
> The `audit-orchestrator` skill coordinates the sequential execution of all 5 specialized sub-skills (`crawl-access-audit`, `crawl-render-audit`, `readability-audit`, `freshness-corroboration`, `engagement-audit`) and synthesizes their raw JSON findings into a unified, authoritative Brand AI Readiness Audit Report.

---

## Quick-Start (Audit Execution Runbook)

> [!IMPORTANT]
> **Zero-Delay Execution — Start Immediately in Turn 1**:
> When an audit is requested, do NOT spend turns browsing directories or reading sub-skill files. Follow this 4-turn execution runbook:
> 
> 1. **Turn 1 — Parallel Baseline Discovery (Launch together in one turn)**:
>    - `python skills/crawl-access-audit/scripts/check_robots.py <url>`
>    - `python skills/crawl-access-audit/scripts/check_sitemap.py <sitemap_or_url>`
>    - `python skills/crawl-access-audit/scripts/check_tls.py <url>`
> 2. **Turn 2 — Targeted Page Access & Raw HTML Retrieval**:
>    - Select `sampled_pages` (the homepage + **at most 1** key page from sitemap `representative_sample`).
>    - Run `python skills/crawl-access-audit/scripts/fetch_dual_identity.py <page_url>` for each sampled page (with `robots` passed). Do NOT probe extra User-Agents.
>    - Run `check_page_signals.py` and `check_crawl_depth.py`.
> 3. **Turn 3 — Content, Structure & Engagement Analysis (Zero Re-Fetches & Zero Code Writing)**:
>    - Pass the retrieved `browser_fetch.content` (raw HTML) directly to Step 2, 3, 4, and 5 scripts using the exact payloads documented below. Do NOT re-fetch URLs.
>    - **Do NOT author custom runner scripts (e.g. `run_turn2.py`, `execute_pipeline.py`) or dump intermediate JSON files in the workspace root.** Run scripts directly via stdin/CLI.
> 4. **Turn 4 — Terminal Synthesis (Single-Pass Execution)**:
>    - Run `synthesize_report.py` strictly once, piping all collected sub-skill outputs directly to `reports/<site_domain>_audit_report.json`.

---

## Inputs

The orchestrator receives target audit parameters:

- `site` *(string)*: Canonical target website domain or URL (e.g. `"https://example.com"`).
- `skill_outputs` *(object, optional)*: Key-value map of sub-skill JSON output objects (`crawl_access`, `crawl_render`, `readability`, `freshness_corroboration`, `engagement`).
- `findings` *(list of objects, optional)*: Additional explicit findings to inject.
- `proactive_recommendations` *(list of strings, optional)*: Custom remediation recommendations.

---

## Workflow & Sub-Skill Execution Procedure

> [!IMPORTANT]
> **Runtime budget (<5 minutes total, per the handout constraint)**: "sequential
> execution of all 5 sub-skills" above describes the DEPENDENCY order (access
> before render, render before readability, ...), not that every script call
> must be issued one at a time. Within a step, the scripts hit independent
> endpoints and DO NOT depend on each other's live output — issue
> `check_robots.py`, `check_sitemap.py`, and `check_crawl_depth.py` (Step 1),
> or the per-page dual-identity fetches for several sampled pages, as parallel
> tool calls in the same turn rather than one after another; sequential
> network-bound calls are the main way an audit overruns 5 minutes on a
> slow-but-reachable site. Cap `sampled_pages` to the homepage plus **at most
> 1** other key page for a standard run (not 1-2) — each additional page
> repeats the dual-identity fetch, the render pass, and the engagement
> per-page checks, and this is the single biggest lever on total runtime: one
> slow-but-reachable page can cost ~30s for `fetch_dual_identity.py` alone
> (browser leg + bot leg + spacing delay), plus up to 20s for
> `check_page_speed_signals.py` and up to 45s if rendered — a third sampled
> page can add another 60-95s worst case on top of everything else. The network-bound
> scripts (`check_robots.py`, `check_sitemap.py`, `check_page_speed_signals.py`)
> each enforce their own internal wall-clock ceiling and return partial results
> with `fetch_deadline_exceeded` / `time_budget_exceeded: true` on a
> pathologically slow target rather than hanging — treat that as a finding
> ("this page/resource is too slow to reliably serve a crawler"), not as a
> signal to retry the same call.

### Step 1: Crawl Access Audit (`crawl-access-audit`)

Execute Step 1 in two tightly coordinated phases to avoid sequential turn latency:

#### Phase 1A — Baseline Discovery (MANDATORY PARALLEL LAUNCH):
Issue these three independent baseline checks **together in a single turn**:
1. `scripts/check_robots.py`: Evaluate `robots.txt` for AI crawlers per RFC 9309 (longest match wins, wildcards honoured) against `/` and audited page URLs; reports deciding rules and documented purpose (`agent_classes`: live-search/assistant **retrieval** vs. model **training**). Its output supplies the `robots` rules gate for Phase 1B fetches.
2. `scripts/check_sitemap.py`: Validate XML sitemap presence and reachability across child sitemaps. Its `representative_sample` output (one URL per URL-structure group) supplies the target URLs for choosing `sampled_pages`.
3. `scripts/check_tls.py`: Independent TLS handshake with the host — checks expired, hostname-mismatched, self-signed/untrusted certs, or certs expiring within 14 days.

> **Do NOT run these three checks sequentially across separate conversation turns.** Launching them simultaneously completes baseline discovery in ~11s instead of 60–90s.

#### Phase 1B — Bot Identity & Crawl Verification (After Phase 1A returns):
Once Phase 1A results are returned, proceed with page-level access checks:
- **Pass `check_robots.py` output as `robots` to every subsequent fetch script** (`fetch_dual_identity.py`, `check_crawl_depth.py`, `check_page_speed_signals.py`, `check_nontext_facts.py`, `fetch_rendered_dom.py`). They gate every request on it via `crawl-access-audit/scripts/robots_gate.py`. Passing it through costs nothing and saves a request per script; omit it and each script fetches `/robots.txt` itself rather than proceeding ungated. If a fetch comes back `skipped_by_robots`, **do not run the content skills on the empty result** — report the reduced coverage instead. The report's `audit_metadata.robots_restricted_fetches` lists every refused request.
- Use `check_sitemap.py`'s `representative_sample` (one URL per URL-structure group) to select `sampled_pages`.
- `scripts/fetch_dual_identity.py`: Compare HTTP responses for User-Agent browser vs. AI bot identity. Run `fetch_dual_identity.py` exactly once per sampled page using its configured bot identity. **Do NOT probe additional User-Agents (e.g. ClaudeBot, PerplexityBot) beyond what `fetch_dual_identity.py` emits.** If `bot_blocked: true` is returned, that is sufficient, conclusive evidence of an edge bot barrier — further per-UA confirmation fetches or debugging probes are strictly prohibited and consume budget without altering findings.
- `scripts/check_page_signals.py`: Inspect indexing meta tags (`noindex`, `nofollow`, canonicals).
- `scripts/check_crawl_depth.py`: Evaluate internal link structure and URL depth.
- Redirect loops and chains of 3+ hops are reported from the dual fetch's existing `status` / `redirect_count` (no extra requests).

> [!IMPORTANT]
> **Fetch each page's HTML exactly once, then reuse it for every skill.**
> `fetch_dual_identity.py` (Step 1) already returns the page's raw HTML in
> `browser_fetch.content` — that same string is the `html`/`raw_html` input
> every other skill asks for (`readability-audit`, `engagement-audit`,
> `crawl-render-audit`'s raw side, `freshness-corroboration`). **Never fetch
> the same URL again to get it.** `readability-audit` and `crawl-render-audit`
> both have `WebFetch` in their `allowed-tools` — that access exists for
> reading *documentation/reference material while auditing*, not for
> re-fetching a page this orchestrator already has the HTML for. Likewise,
> only fetch a rendered DOM once per page (`fetch_rendered_dom.py`, Step 2)
> and reuse that same `rendered_html` for both `check_rendering_barriers.py`
> and `check_structured_data_hydration.py` — never render the same page
> twice. A redundant re-fetch costs as much as the original ~30s
> dual-identity fetch and is pure waste toward the 5-minute budget.

### Step 2: Crawl Render Audit (`crawl-render-audit`)
Run rendering barrier scripts (all scripts accept JSON via stdin or argv[1]):
- `scripts/check_rendering_barriers.py`: `{"url": url, "raw_html": raw_html, "rendered_html": rendered_html or ""}`
  - Compare initial raw HTML vs. rendered DOM text word counts.
- `scripts/check_structured_data_hydration.py`: `{"url": url, "raw_html": raw_html, "rendered_html": rendered_html or ""}`
  - Detect JSON-LD schema trapped behind client-side JS execution.
- `scripts/check_client_side_redirects.py`: `{"url": url, "raw_html": raw_html}`
  - Detect client-side JS and meta refresh redirects.
- `scripts/fetch_rendered_dom.py` *(optional)*: `{"url": url, "robots": robots}`
  - Optional Chrome headless render. **Skip when target site serves bot/WAF challenge or to protect the 5-minute budget** — pass `rendered_html: ""` to the checks above.

### Step 3: Readability Audit (`readability-audit`)
Run structural and semantic audit scripts:
- `scripts/check_structured_data.py`: `{"url": url, "html": raw_html}`
  - Validate Schema.org JSON-LD completeness across 9 schema types.
- `scripts/check_semantic_structure.py`: `{"url": url, "html": raw_html}`
  - Validate heading hierarchy (`<h1>`, `<h2>`) and outline structure.
- `scripts/check_nontext_facts.py`: `{"url": url, "html": raw_html, "robots": robots}`
  - Verify machine-readable alternatives for non-text facts (images, audio/video, icons).
- `scripts/check_content_consistency.py`: `{"url": url, "html": raw_html}`
  - Detect contradiction between tabular markup and prose.
- If you ran `check_structured_data.py` on any page besides the homepage, pass those results through as
  `readability.additional_pages: [{"url": ..., "structured_data": {...}}]`. No extra request is involved —
  that page's HTML was already fetched — and it is where the entity-grounding gap normally shows up: a
  homepage carrying the `Organization` block while product and article pages ship only a breadcrumb trail.
  Entries that are not objects, or whose page has no recognised entities, are ignored.

### Step 4: Freshness & Corroboration Audit (`freshness-corroboration`)
Run temporal and corroboration scripts:
- `scripts/check_content_dates.py`: `{"url": url, "html": raw_html}`
  - Extract publication, modification, and copyright dates.
- `scripts/check_temporal_decay.py`: `{"url": url, "html": raw_html}`
  - Detect post recency decay on blog/listing pages.
- `scripts/check_citation_consistency.py`: `{"url": url, "html": raw_html}`
  - Corroborate on-site facts against external web search snippets.
- `scripts/check_entity_disambiguation.py`: `{"url": url, "html": raw_html}`
  - Evaluate `sameAs` entity links (Wikidata, Wikipedia).

### Step 5: On-Site Engagement Audit (`engagement-audit`)
Run visitor orientation and engagement scripts:
- `scripts/check_navigation_reachability.py`: `{"homepage_url": site_url, "html": homepage_raw_html}`
  - Audit 1-level homepage navigation reachability for key URLs.
- `scripts/check_content_depth.py`: `{"url": url, "html": raw_html}`
  - Detect page intent, then assess content depth against advisory bands for content-bearing intents only.
- `scripts/check_mobile_responsive_signals.py`: `{"url": url, "html": raw_html}`
  - Check `<meta viewport>` and inline media queries.
- `scripts/check_descriptor_consistency.py`: `{"pages": [{"url": u1, "html": h1}, {"url": u2, "html": h2}]}`
  - Audit cross-page brand phrase consistency in titles/H1s.
- `scripts/check_page_speed_signals.py`: `{"url": url, "robots": robots}`
  - Measure HTML byte size, CSS/JS resource bytes, and image counts.
- `scripts/check_landing_readiness.py`: `{"url": url, "html": raw_html}`
  - Per sampled page, evaluate cold AI-referral entry — orientation (brand / description / `<h1>`), forward action CTA, and hygiene.

### Step 6: Master Synthesis (`scripts/synthesize_report.py`)

Run `scripts/synthesize_report.py` to aggregate all sub-skill findings in a **strict single pass**:

```bash
echo '{
  "site": "https://example.com",
  "skill_outputs": {
    "crawl_access": { ... },
    "crawl_render": { ... },
    "readability": { ..., "additional_pages": [ { "url": "...", "structured_data": { ... } } ] },
    "freshness_corroboration": { ... },
    "engagement": { ... }
  }
}' | python skills/audit-orchestrator/scripts/synthesize_report.py > reports/<site_domain>_audit_report.json
```

> [!IMPORTANT]
> **Single-Pass Execution Rules**:
> - **Execute `synthesize_report.py` strictly once as the final terminal step.** Do NOT run it a second time, do NOT re-synthesize, and do NOT create custom scratch audit scripts (e.g. `run_audit.py`).
> - **Proactive recommendations are automatically populated**: If not supplied in the input payload, the script automatically derives tailored recommendations from findings and strategic AI readiness best practices (`/llms.txt`, crawler logs, entity schema). Do NOT launch a follow-up turn to "review" or "add recommendations".
> - **Self-validating schema**: The script automatically validates its output against `references/audit_report_schema.json` before emitting, guaranteeing complete contract compliance in one step.

The script extracts findings across all 5 skills, formats IDs (`F-001`, `F-002`), assigns severities (`critical`, `high`, `medium`, `low`), calculates five independent per-category scores (0.0 to 100.0, see Guardrails below), and outputs a structured JSON report. There is deliberately no single blended overall score — the handout's required schema asks for `site`/`audited_at`/a severity-count `summary`/`findings` and nothing more; a report of well-evidenced, correctly-severed findings is the deliverable, not a formula on top of them.

---

## Output Schema

Produces the master audit report conforming to `references/audit_report_schema.json`:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-06T21:28:45Z",
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

`audited_pages_count` counts distinct URLs found in `crawl_access.sampled_pages` and `engagement...key_content_reachability` (the two named containers that represent "pages this audit actually looked at" — a page fully sampled, or a key URL checked for nav reachability), wherever those containers are nested, plus each skill's own top-level `url`/`homepage_url`/`site` field. It deliberately does NOT sweep every dict with a `url`-shaped key anywhere in `skill_outputs` — that also picks up sitemap spot-checks (a single HEAD request, not full analysis) and raw on-page link lists (a URL merely noticed as an href target, never fetched), wildly overcounting. If you add a new per-page container to a sub-skill, name it (or register it) the same way rather than assuming a generic URL sweep will find it.

---

## Guardrails

> [!IMPORTANT]
> **Contract self-check**:
> `scripts/verify_contracts.py` cross-checks every output key `synthesize_report.py`
> reads against the keys the sub-skill scripts actually emit, and exits non-zero on
> drift. Run it after changing any sub-skill's output shape — a renamed field would
> otherwise silently disable the matching finding and make a broken site look clean.
> ```bash
> python skills/audit-orchestrator/scripts/verify_contracts.py
> ```
> `normalize_crawl_access()` and `pick()` in `synthesize_report.py` additionally
> absorb known shape/alias differences (`sampled_pages` vs flat `dual_identity`,
> `nontext_facts` vs `nontext_content`, `content_consistency` vs `context_consistency`,
> `sitemap_found` vs `exists`).

> [!IMPORTANT]
> **Deterministic Synthesis**:
> `synthesize_report.py` calculates each of the five `category_scores` independently and deterministically. Each category starts at 100.0; every finding in that category deducts a fixed amount by severity (`critical`: -20.0, `high`: -10.0, `medium`: -5.0, `low`: -2.0), scaled by the finding's `confidence` in [0, 1] (a confidence-0.5 critical finding costs 10, not 20 — missing/invalid confidence defaults to 1.0, full weight); the result is clamped to 0.0-100.0. That's the entire model: no cross-category weighting, no diminishing-returns decay on repeated same-severity findings, no foundational-score gates, no blended overall number. Every category's score can be verified by hand directly from the findings list — deliberately favoring "a judge can check this in one pass" over the more elaborate weighted-and-gated model this project used earlier, which required tracing a weighted mean through per-category decay curves and a confidence-softened cap to see why a headline number landed where it did.
>
> This is a considered simplification, not an oversight — an earlier iteration of this scoring layer did have per-category diminishing returns and foundational gates capping the overall score when a critical `crawl_access`/`crawl_render` finding hit. Both pieces addressed real concerns (many small findings shouldn't crush a category out of proportion to severity; a site that fails at the foundational crawl-access/render level shouldn't average out to "decent" just because other categories look clean), but neither is required by the handout's schema, and in practice this marketplace's checks already aggregate repeat instances into one finding with a count in the evidence ("5 low-overlap FAQ pairs", not five findings) rather than emitting duplicates — so the decay protection was hardening against a scenario the check design mostly prevents anyway. **The foundational-severity reasoning itself is still real and still visible** — a `crawl_access` or `crawl_render` critical finding still deducts a full -20 from its own category, same as any other critical, and a reader comparing `category_scores` sees immediately that access/render is the weak point; it just no longer reaches through to suppress an overall number that no longer exists.
>
> All findings are renumbered sequentially (`F-001`, `F-002`, ...) after assembly, so caller-supplied explicit findings that carry their own ids cannot leave gaps in the sequence; every id matches `^F-[0-9]{3,}$`.
