---
name: audit-orchestrator
description: Entrypoint master orchestrator skill that coordinates execution across all 5 specialized sub-skills (crawl-access-audit, crawl-render-audit, readability-audit, freshness-corroboration, engagement-audit) and synthesizes the final Brand AI Readiness Audit Report.
license: MIT
compatibility: Requires Python 3 and outbound network access
allowed-tools: Bash Read WebFetch WebSearch
---

# `audit-orchestrator` Skill

Serves as the entrypoint master orchestrator for conducting complete end-to-end Brand AI Readiness Audits across target website domains and URLs.

> [!IMPORTANT]
> **Execute this now — do not produce an implementation plan.** This document
> is a runbook, not a spec to design against: everything needed already
> exists (every script below is written, tested, and ready to invoke). If you
> were asked to audit a website, run the steps below now, without asking for
> approval to start — the scripts are all read-only. **Never modify, delete,
> move or rename any file in this marketplace.** The task is not done until
> `synthesize_report.py` (Step 6) has produced the JSON report and you have
> shown it — saved to a file when the environment allows, otherwise the report
> it prints to stdout (see Step 6); a plan, a summary, or partial findings in
> chat do not satisfy the request.
>
> **"Sequential" below means dependency order between the 5 stages (access
> before render, render before readability, ...) — it does NOT mean issue
> every script call one at a time.** Within a stage, scripts hit independent
> endpoints: call `check_robots.py`, `check_sitemap.py`, and
> `check_crawl_depth.py` (Step 1), or the dual-identity fetches for several
> sampled pages, as **parallel tool calls in the same turn**. Calling all
> ~26 scripts one at a time across separate turns is the single most common
> way this audit blows past the 5-minute budget — see the runtime-budget
> callout further below for the full breakdown and the worst-case ceiling
> table.

> [!NOTE]
> **Orchestrator Role**:
> The `audit-orchestrator` skill coordinates the execution of all 5 specialized sub-skills (`crawl-access-audit`, `crawl-render-audit`, `readability-audit`, `freshness-corroboration`, `engagement-audit`) — in dependency order, but with independent calls WITHIN a stage parallelized — and synthesizes their raw JSON findings into a unified, authoritative Brand AI Readiness Audit Report.

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
> slow-but-reachable page can cost ~20s for `fetch_dual_identity.py` alone
> (browser leg + bot leg + spacing delay), plus up to 15s for
> `check_page_speed_signals.py` and up to 18s if rendered — a third sampled
> page can add another 50-75s worst case on top of everything else. The network-bound
> scripts (`check_robots.py`, `check_sitemap.py`, `check_page_speed_signals.py`)
> each enforce their own internal wall-clock ceiling and return partial results
> with `fetch_deadline_exceeded` / `time_budget_exceeded: true` on a
> pathologically slow target rather than hanging — treat that as a finding
> ("this page/resource is too slow to reliably serve a crawler"), **not as a
> signal to retry the same call. A script that returns ANY JSON — including a
> `time_budget_exceeded: true` or a 429-throttled result — has already given
> you its final answer for this run; re-invoking it does not get a better
> answer, it only spends another full ceiling's worth of wall-clock time (and,
> observed directly on a rate-limited real host, another round of
> subprocess-spawn and inter-turn notification overhead) for nothing.**

**Cut invocation count, not just per-call time.** Every subprocess call costs
more than its own network wait: process startup plus the calling agent's own
per-call turn/notification overhead (measured directly: this stacked across
roughly two dozen separate invocations on a real audit and was a comparable
contributor to a runtime overrun as the network waits themselves). Several
scripts in Steps 2-5 do no network I/O of their own — they only parse HTML
already fetched in Step 1 — so bundle them into ONE process instead of several:
- `readability-audit/scripts/run_all.py` replaces `check_structured_data.py` +
  `check_semantic_structure.py` + `check_content_consistency.py` +
  `check_nontext_facts.py` (4 calls → 1). Same `{html, url, robots}` input,
  identical output fields, nested under the same keys.
- `crawl-render-audit/scripts/run_all.py` replaces `check_rendering_barriers.py`
  + `check_structured_data_hydration.py` + `check_client_side_redirects.py`
  (3 calls → 1). Same `{raw_html, rendered_html, url}` input.
- `freshness-corroboration/scripts/run_content_dates_and_decay.py` replaces
  `check_content_dates.py` + `check_temporal_decay.py` (2 calls → 1) — pass
  `status` through exactly as before. `check_citation_consistency.py` /
  `check_entity_disambiguation.py` stay separate: they need this turn's own
  `WebSearch` results, which don't exist until after you've searched.
  `engagement-audit/scripts/run_single_page_checks.py` replaces
  `check_content_depth.py` + `check_landing_readiness.py` +
  `check_mobile_responsive_signals.py` (3 calls → 1); `check_navigation_reachability.py`
  and `check_descriptor_consistency.py` need data gathered ACROSS pages and
  `check_page_speed_signals.py` does its own network fetch, so all three stay
  separate. Every aggregator only imports and calls the same functions the
  individual scripts already call — nothing about detection logic or output
  shape changes, and each per-check script still works standalone if you need
  to isolate one.

**Worst-case wall-clock ceilings** (every network-bound script enforces one; a
healthy site uses a small fraction of each):

| Script | Ceiling | Calls in a 2-page audit |
|---|---|---|
| `check_robots.py` | 18 s (4 candidates) | 1 |
| `check_tls.py` | 6 s (one handshake) | 1 |
| `fetch_dual_identity.py` | 20 s (`DUAL_FETCH_TOTAL_BUDGET_S`) | 2 |
| `check_sitemap.py` | 20 s (`SITEMAP_FETCH_DEADLINE_S`) | 1 |
| `check_crawl_depth.py` | 20–45 s (`derive_budget`) | 1 |
| `fetch_rendered_dom.py` | 18 s default (45 max) | ≤2 |
| `check_page_speed_signals.py` | 15 s (`RESOURCE_FETCH_DEADLINE_S`) | ≤2 |
| `check_nontext_facts.py` | 25 s (`PDF_INSPECTION_DEADLINE_S`) | ≤2 |

Summed sequentially against a uniformly pathological host that maxes out every
one of them, that is ~4 minutes (245s) **before** any agent overhead — down
from ~4.65 minutes (279s), a 34s reduction trimmed uniformly across every
network-bound script, not tuned to any one target, precisely so there is real
headroom left for orchestration/agent-side cost on top, which the ceilings
themselves cannot bound. This is why the parallelism, the 2-page cap, and the run_all
aggregators above are requirements, not suggestions: run independent calls in
one turn and the wall clock collapses to the slowest single script, leaving
the budget dominated by your own tool-call latency rather than the target's.
If a run is nonetheless trending long, **shed work in this order** (each step
keeps the report valid, just less complete — say so in the report rather than
silently dropping it): the rendered DOM on the second page → the second sampled
page entirely → `check_crawl_depth.py` → `check_page_speed_signals.py`. Never
shed Step 1: without `crawl_access` there is no report worth emitting.

### Step 1: Crawl Access Audit (`crawl-access-audit`)
Run specialized access scripts to evaluate bot accessibility:
> **Run `check_robots.py` first, then pass its output as `robots` to every
> other script that fetches** (`fetch_dual_identity.py`, `check_sitemap.py`,
> `check_crawl_depth.py`, `check_page_speed_signals.py`,
> `check_nontext_facts.py`, `fetch_rendered_dom.py`). They gate every request
> on it via `crawl-access-audit/scripts/robots_gate.py`. Passing it through
> costs nothing and saves a request per script; omit it and each script fetches
> `/robots.txt` itself rather than proceeding ungated. If a fetch comes back
> `skipped_by_robots`, **do not run the content skills on the empty result** —
> report the reduced coverage instead. The report's
> `audit_metadata.robots_restricted_fetches` lists every refused request.

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

- `scripts/check_robots.py`: Evaluate `robots.txt` for AI crawlers per RFC 9309 (longest match wins, wildcards honoured) against `/` and every audited page URL; reports the deciding rule per path and agent, and each agent's documented purpose (`agent_classes`: live-search/assistant **retrieval** vs. model **training**, from `references/ai_crawler_classes.json`). A block that removes the site from live AI search answers is critical/high; a training-only block is medium/low; a block on a user-initiated fetcher that robots.txt may not apply to is not scored.
- `scripts/fetch_dual_identity.py`: Compare HTTP responses for User-Agent browser vs. AI bot identity.
- `scripts/check_sitemap.py`: Validate XML sitemap presence and reachability.
- `scripts/check_page_signals.py`: Inspect indexing meta tags (`noindex`, `nofollow`, canonicals).
- `scripts/check_crawl_depth.py`: Evaluate internal link structure and URL depth.
- `scripts/check_tls.py`: One TLS handshake with the host the pages are served from — expired, hostname-mismatched, self-signed or untrusted certificates (which make crawlers abort before fetching anything), and certificates expiring within 14 days.
- Redirect loops and chains of 3+ hops are reported from the dual fetch's existing `status` / `redirect_count` (no extra requests). `check_sitemap.py`'s `representative_sample` (one URL per URL-structure group) is the recommended source for choosing `sampled_pages`.

> [!IMPORTANT]
> **Stop then and there if the site's security infrastructure disallows bots.**
> Check `fetch_dual_identity.py`'s result for the homepage BEFORE running Steps
> 2-5: if `bot_blocked`, `bot_soft_blocked`, or `bot_challenged` (with
> `comparison_metrics.fingerprint_divergence: true`) is set, a real non-JS AI
> crawler reaches 0% of this site — **do not** invoke `crawl-render-audit`,
> `readability-audit`, or `engagement-audit` at all, and in Step 4 run only
> `check_citation_consistency.py` / `check_entity_disambiguation.py` (they
> corroborate via external web search, not this site's own blocked fetch) —
> skip `check_content_dates.py` / `check_temporal_decay.py`, which need this
> site's own HTML. Running a headless browser or reading
> `browser_fetch.content` still "succeeds" in that state — Chromium executing
> JavaScript can solve the very challenge that stops a real crawler, and a
> plain browser-identity fetch can simply never have been challenged in the
> first place — but feeding that view into downstream checks manufactures a
> false "high quality" report for content no AI crawler can actually reach,
> drowns the one finding that matters in unrelated low-severity noise (alt
> text, blog dates), and wastes the runtime budget rendering and analyzing
> pages this audit already knows are unreachable. Go straight to Step 6 with
> `crawl_access` populated (plus, optionally, the two off-site freshness
> checks). `synthesize_report.py` enforces this as a backstop too — it sets
> `audit_metadata.coverage_blocked: true` and skips generating findings for
> `crawl_render`/`readability`/`engagement`, and for freshness's
> `content_dates`/`temporal_decay` sub-checks, on its own if it receives their
> output anyway, so an agent that skips this check does not silently produce
> a misleading report — but skipping the calls themselves is what actually
> saves the runtime budget.

### Step 2: Crawl Render Audit (`crawl-render-audit`)
> **Call `scripts/run_all.py` once instead of the three scripts below separately** —
> same `{raw_html, rendered_html, url}` input, same three output keys nested
> in one JSON object. Cuts this step from 3 subprocess calls to 1.
Run rendering barrier scripts:
- `scripts/check_rendering_barriers.py`: Compare initial raw HTML vs. rendered DOM text word counts.
- `scripts/check_structured_data_hydration.py`: Detect JSON-LD schema trapped behind client-side JS execution.
- `scripts/check_client_side_redirects.py`: Detect client-side JS and meta refresh redirects.
- `scripts/fetch_rendered_dom.py` *(optional)*: When the agent has no browser tool, render a page with an already-installed Chrome/Edge/Chromium (sandboxed, throwaway profile, hard timeout) to supply `rendered_html`, so the checks above measure the raw-vs-rendered gap instead of inferring it. Returns `available: false` when no browser exists; then run raw-only. Budget 1–8 s per page — render the homepage and at most one other page.

> [!IMPORTANT]
> **Disclose it plainly when this environment cannot render at all — do not
> just quietly fall back to raw-HTML-only and move on.** If neither your own
> native browser tool NOR `fetch_rendered_dom.py` can produce a rendered DOM
> for this run (`fetch_rendered_dom.py` returns `available: false` with
> `unavailable_reason: "no_browser_installed"` or `"root_no_sandbox"` — this
> is exactly the shape of a locked-down grading sandbox with no Chrome/Edge/
> Chromium installed), pass those two fields through as
> `crawl_render.dom_render_availability` in the Step 6 payload. The
> orchestrator turns this into an explicit, low-severity disclosure finding —
> *"No Headless Browser Available for This Audit Environment"* — telling the
> reader plainly that client-side-rendering detection ran on raw HTML only,
> could not directly observe JavaScript-assembled content, and that any
> `crawl_render` findings in this report are inferred, not measured. This is
> a fact about THIS RUN's tooling, not a defect in the audited site, and
> matters most exactly when it's least visible: a report with zero CSR
> findings could mean "genuinely clean site" or "we had no way to check" —
> the reader must be told which. Omit `dom_render_availability` entirely
> (don't fabricate `available: true`) whenever a real rendered-DOM comparison
> WAS obtained, by either tool.

### Step 3: Readability Audit (`readability-audit`)
> **Call `scripts/run_all.py` once instead of the four scripts below separately** —
> same `{html, url, robots}` input, same four output keys nested in one JSON
> object. Cuts this step from 4 subprocess calls to 1.
Run structural and semantic audit scripts:
- `scripts/check_structured_data.py`: Validate Schema.org JSON-LD completeness across 9 schema types.
- `scripts/check_semantic_structure.py`: Validate heading hierarchy (`<h1>`, `<h2>`) and outline structure.
- `scripts/check_nontext_facts.py`: Verify machine-readable alternatives for non-text facts.
- `scripts/check_content_consistency.py`: Detect contradiction between tabular markup and prose.
- If you ran `check_structured_data.py` (or `run_all.py`) on any page besides the homepage, pass those results through as
  `readability.additional_pages: [{"url": ..., "structured_data": {...}}]`. No extra request is involved —
  that page's HTML was already fetched — and it is where the entity-grounding gap normally shows up: a
  homepage carrying the `Organization` block while product and article pages ship only a breadcrumb trail.
  Entries that are not objects, or whose page has no recognised entities, are ignored.

### Step 4: Freshness & Corroboration Audit (`freshness-corroboration`)
> **Call `scripts/run_content_dates_and_decay.py` once instead of the first two
> scripts below separately** — same `{html, url, status}` input, both output
> keys nested in one JSON object. The other two scripts need this turn's own
> `WebSearch` results and stay separate calls, run after searching.
Run temporal and corroboration scripts:
- `scripts/check_content_dates.py`: Extract publication, modification, and copyright dates. **Pass `status`**
  (the HTTP status of the fetch that produced this page's `html`, e.g. `browser_fetch.status` from Step 1) —
  without it, a 404/410/5xx page's error body can be scanned for dates like real content, misreporting a
  dead page as stale content instead of the reachability defect it actually is.
- `scripts/check_temporal_decay.py`: Detect post recency decay on blog/listing pages. Pass `status` the same way.
- `scripts/check_citation_consistency.py`: Corroborate on-site facts against external web search snippets.
- `scripts/check_entity_disambiguation.py`: Evaluate `sameAs` entity links (Wikidata, Wikipedia).

### Step 5: On-Site Engagement Audit (`engagement-audit`)
> **Call `scripts/run_single_page_checks.py` once instead of `check_content_depth.py`
> + `check_landing_readiness.py` + `check_mobile_responsive_signals.py` separately** —
> same `{html, url, page_type_hint}` input, all three output keys nested in
> one JSON object. `check_navigation_reachability.py`, `check_descriptor_consistency.py`,
> and `check_page_speed_signals.py` need cross-page data or their own network
> fetch and stay separate calls.
Run visitor orientation and engagement scripts:
- `scripts/check_navigation_reachability.py`: Audit 1-level homepage navigation reachability for key URLs.
  **Choose `key_content_urls` deliberately — do not reuse `check_sitemap.py`'s `representative_sample`
  picks.** That field picks one URL per URL-structure group to represent it for content sampling; on a site
  with combinatorial long-tail content (a specific flight route, product variant, listing), that pick is
  exactly the kind of page no homepage would ever link directly. Pass evergreen, top-level pages instead —
  `/pricing`, `/about`, primary category pages. `synthesize_report.py` hedges when a URL structurally looks
  long-tail (a long, hyphen-dense slug, or 3+ path segments), but choosing well up front avoids the noise.
- `scripts/check_content_depth.py`: Detect page intent, then assess content depth against advisory bands for content-bearing intents only; extract heading/paragraph text pairs.
- `scripts/check_mobile_responsive_signals.py`: Check `<meta viewport>` and inline media queries.
- `scripts/check_descriptor_consistency.py`: Audit cross-page brand phrase consistency in titles/H1s.
- `scripts/check_page_speed_signals.py`: Measure HTML byte size, CSS/JS resource bytes, and image counts.
- `scripts/check_landing_readiness.py`: Per sampled page, evaluate cold AI-referral entry — orientation (brand / description / `<h1>`), a forward action (CTA / nav / contact), hygiene (placeholder text, default `<title>`, dead links, mixed content), and reported friction signals.

### Step 6: Master Synthesis (`scripts/synthesize_report.py`)

> [!IMPORTANT]
> **This step is mandatory and always runs — the audit's deliverable IS this
> report.** Run it even when the audit went badly: a sub-skill crashed, the
> site was WAF-blocked, only Step 1 completed. A partial report that states
> what it could not measure is the correct output; prose in the chat is not a
> deliverable, and neither is stopping after collecting evidence.
>
> **Never `echo` a payload, and never author it as your own generated text
> either — redirect scripts' output straight to files instead.** A real
> `skill_outputs` contains the fetched HTML of every sampled page and runs
> **20 KB–800 KB**. `echo '<json>' | python …` truncates it outright (cmd.exe
> caps a command line at 8 KB, `CreateProcess` at 32 KB) — but even writing
> `payload.json` yourself avoids only THAT problem, not the real cost: you'd
> still have to read every script's output into your own context and then
> re-emit those same bytes as generated output tokens to compose the file.
> That regeneration is bounded by your own token-generation rate, not by
> disk or network I/O, and is routinely the single slowest step in an
> otherwise-fast audit. Redirect each script's stdout straight to a file with
> plain shell `>` — the OS moves the bytes, no tokens involved — then
> reference those files **by path** with `--set`:

```bash
python skills/crawl-access-audit/scripts/check_robots.py '{"domain":"example.com"}' > out/robots.json
python skills/crawl-access-audit/scripts/fetch_dual_identity.py '{"url":"...", "robots": ...}' > out/dual.json
# ... every other script, each redirected to its own file ...

python skills/audit-orchestrator/scripts/synthesize_report.py \
  --site https://example.com \
  --set crawl_access.robots=out/robots.json \
  --set crawl_access.dual_identity=out/dual.json \
  --set crawl_render=out/render_all.json \
  --set readability=out/readability_all.json \
  --set freshness_corroboration.content_dates_and_decay=out/freshness_all.json \
  --set engagement.single_page=out/engagement_all.json \
  --out report.json
```

Each `--set <dotted.path>=<file>` reads that file's JSON and places it at
`skill_outputs.<dotted.path>` — a bare key (`crawl_render=...`) merges a whole
category at once (exactly what the `run_all.py` aggregators already return),
while a dotted path (`crawl_access.robots=...`) nests one field. A numeric
segment builds a list index, for a second sampled page:
`--set crawl_access.sampled_pages.1.url=out/p1_url.json`. Repeat `--set` as
many times as you have output files — every argument is a short file path,
never file content, so this command costs the same handful of tokens to issue
whether the underlying data is 20 KB or 800 KB.

`payload.json` (`--input`) is still supported for a caller that already has
the whole object assembled in one place — a programmatic caller, or a smaller
hand-built payload where the regeneration cost above doesn't apply:

```bash
python skills/audit-orchestrator/scripts/synthesize_report.py --input payload.json --out report.json
```

```json
{
  "site": "https://example.com",
  "skill_outputs": {
    "crawl_access": { "...": "..." },
    "crawl_render": { "...": "..." },
    "readability": { "additional_pages": [{ "url": "...", "structured_data": {} }] },
    "freshness_corroboration": { "...": "..." },
    "engagement": { "...": "..." }
  },
  "findings": [],
  "proactive_recommendations": []
}
```

`--out` writes the report to disk (it is also printed to stdout). `findings`
and `proactive_recommendations` are optional: use them to inject agent-judged
findings the scripts cannot produce on their own. `--set` is applied AFTER
`--input`, so it can layer file-referenced fields on top of a smaller
hand-built base. Piping a payload on stdin also works for programmatic
callers, applied last of all.

**If files cannot be written** (a read-only sandbox): put the scratch files in
the system temp directory (`$TMPDIR`, `/tmp`, `%TEMP%`) if that is writable. If
nothing is writable, skip the redirects and `--out`, and pipe the payload to the
script on stdin with a heredoc (never `echo`) —
`python skills/audit-orchestrator/scripts/synthesize_report.py <<'EOF' … EOF` —
then present the report it prints to stdout; that is the deliverable. An `--out`
path that cannot be written never loses the report: it is still printed, with
`audit_metadata.output_error` saying why.

If the payload cannot be parsed, the script does **not** fall back to a clean
empty report — it emits a report carrying a `critical` "Audit Input Could Not
Be Read" finding plus `audit_metadata.input_error`, because a zero-finding
report is otherwise indistinguishable from a healthy site.

The script extracts findings across all 5 skills, formats IDs (`F-001`, `F-002`), assigns severities (`critical`, `high`, `medium`, `low`), and outputs a structured JSON report. There is deliberately no score of any kind, per-category or overall — the handout's required schema asks for `site`/`audited_at`/a severity-count `summary`/`findings` and nothing more; a report of well-evidenced, correctly-severed findings is the deliverable, not a formula on top of them.

---

## Output Schema

Produces the master audit report conforming to `references/audit_report_schema.json`:

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
    "marketplace_version": "1.0.0",
    "robots_restricted_fetches": [],
    "robots_compliance": "all fetches allowed by robots.txt",
    "coverage_blocked": false,
    "categories_not_audited": []
  }
}
```

When `coverage_blocked` is `true` (see the callout after Step 1), `categories_not_audited` lists the categories
whose findings were skipped entirely: `["crawl_render", "readability", "engagement"]` — all three derived from this
site's own fetched/rendered HTML. `freshness_corroboration` is deliberately never in that list: its
`citation_consistency`/`entity_disambiguation` checks corroborate via external web search, not this site's blocked
fetch, and keep running (only its `content_dates`/`temporal_decay` sub-checks, which need this site's own HTML, are
skipped). `findings` carries a critical `crawl_access` entry titled either
`"robots.txt Permits Crawling But the Fetch Is Blocked Anyway (Policy/Enforcement Mismatch)"`
(when robots.txt can be shown to permit the exact request that was blocked — the common case, since a request
robots.txt actually refused is never sent in the first place) or `"AI Bot Identity HTTP Fetch Blocked or Challenged"`
(the same underlying block, worded without the policy-mismatch claim when that permission can't be affirmatively
cited). Those three categories simply have zero findings in that case — that reflects "not evaluated", not
"verified clean", and a reader must check `coverage_blocked` before reading an absence of findings there as a
clean bill of health.

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
> **No Scoring, By Design**:
> `synthesize_report.py` computes no score of any kind — no per-category number, no overall blended figure. The
> handout's required schema is `site`/`audited_at`/a severity-count `summary`/`findings`/`suggested_action` and
> nothing more; it never asks for a score. A report of well-evidenced, correctly-severed findings (severity plus
> `confidence`, the latter distinct from severity — see the `findings[].confidence` field) is the deliverable
> itself, not an input to a formula on top of it. This project's earlier iterations did compute scores — first a
> single blended `brand_ai_readiness_score` with per-category weighting/decay/gates, then a simplified
> per-category-only `category_scores` — both were removed as unnecessary machinery once weighed against a schema
> that never required either.
>
> All findings are renumbered sequentially (`F-001`, `F-002`, ...) after assembly, so caller-supplied explicit findings that carry their own ids cannot leave gaps in the sequence; every id matches `^F-[0-9]{3,}$`.
