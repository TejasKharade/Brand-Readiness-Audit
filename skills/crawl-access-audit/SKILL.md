---
name: crawl-access-audit
description: Gathers raw, structured data on whether a website's pages are
  reachable by AI-assistant and search crawlers — robots.txt rules, actual
  server behavior under browser vs. bot identities, page-level indexing
  signals, sitemap health, and crawl depth. Produces structured facts only;
  does not diagnose root causes, identify blocking systems, or assign
  severity. Use as the first data-gathering stage of an AI-discoverability
  audit, feeding a diagnosis/orchestrator skill.
license: MIT
compatibility: Requires Python 3 and outbound network access
allowed-tools: Bash Read
---

# Crawl Access Audit Skill

## When to use
Use as the first data-gathering stage of an AI-discoverability audit. This
skill performs ONLY the "data gathering" half of an accessibility audit —
collecting raw, uninterpreted facts about whether/how a crawler can access a
website. Interpretation (deciding WHY a page is blocked, identifying which
bot-management system is responsible, comparing browser vs. bot results) is
explicitly out of scope here and belongs to the orchestrator/diagnosis skill
that consumes this skill's output.

## Inputs
- `domain`: Target site domain or URL (e.g., `example.com` or
  `https://example.com`).
- `sampled_pages`: A list of specific page URLs to audit (e.g.,
  `["https://example.com/about", "https://example.com/product/1"]`).
- `target_page` (optional): A page URL to measure crawl depth against, for
  the crawl-depth check.
- `bot_user_agent` (optional): The AI-crawler User-Agent string to test
  with across all checks (default: a current GPTBot string — see
  `references/bot_user_agents.md`). Only one bot identity is tested per
  audit run; to test multiple bots, invoke this skill once per bot.

## Procedure & Script Execution Flow

1. **Robots.txt analysis (`scripts/check_robots.py <domain>`)**
   - Tries four URL variants in order (`https://domain`, `https://www.domain`,
     `http://domain`, `http://www.domain`, skipping a redundant www variant
     if the input already includes it) and stops at the first that
     succeeds. Returns which variant worked as `resolved_url`.
   - Detects a 200 response that is actually an HTML page rather than real
     robots.txt content (`reachable: true, malformed: true` — reported, not
     silently treated as "no robots.txt").
   - **Evaluates rules per RFC 9309, not Python's `urllib.robotparser`.** The
     stdlib parser applies the *first* rule in file order and ignores `*` / `$`
     wildcards, so `Allow: /` followed by `Disallow: /lp/` scores `/lp/…` as
     allowed. Here the agent's own group is used (groups naming the same agent
     are merged, `*` only as fallback), the **longest matching rule wins**,
     `Allow` wins a tie, and `/robots.txt` is always allowed.
   - Always evaluates `/` plus every entry in `test_paths` (pass the audited
     page URLs — full URLs are accepted and their query string is matched) for
     each agent in `bot_user_agents`. Output: `disallowed {path: {agent: bool}}`,
     `matched_rules {path: {agent: {rule, group}}}` (the exact line that
     decided it — use it as evidence), `root_blocked_agents`, and
     `blocked_paths_by_agent`.
   - A URL blocked **only** because of its query string (`Disallow: /*?*` on a
     tracking-parameter URL whose bare path is allowed) is listed in
     `query_variant_only_blocks` and excluded from `blocked_paths_by_agent`:
     that is duplicate-URL hygiene, not an access defect.
   - The orchestrator raises **critical** when an AI crawler cannot fetch `/`,
     and **high** when a tested key page is disallowed for one.
   - Extracts `crawl_delay` (from the `*` group) and `sitemap_url` /
     `sitemap_urls` if declared. Pass `robots_txt` in the stdin JSON to
     evaluate a file you already hold without fetching.
   - Each candidate uses a 6s per-request timeout, and an 18s wall-clock
     ceiling caps the whole 4-candidate chain (`fetch_deadline_exceeded: true`
     when it fires, with the untried candidates listed) — a slow-but-live
     robots.txt no longer costs up to the old ~40s worst case.
   - **`resolved_url` from this step MUST be passed to the orchestrator and
     reused as the working domain for steps 2 and 5** — do not let those
     steps re-attempt their own www/https resolution independently; this
     avoids duplicated, possibly-inconsistent fallback logic across scripts.

2. **Dual-identity fetch (`scripts/fetch_dual_identity.py <url>`)** — run
   once per sampled page:
   - Fetches the page once with a normal browser User-Agent and once with
     the configured bot User-Agent (2-second delay between the two
     requests to the same host).
   - For each of the two fetches, returns `status` (or `"timeout"`),
     `final_url`, `redirect_count`, `response_time`, `response_headers`
     (raw, unclassified — see Guardrails), and `content`.
   - Runs five content fingerprint checks on EACH fetch's content
     independently (see `references/content_fingerprints.md` for exact signal
     lists and rationale): `cloudflare_challenge`, `captcha`, `generic_block`,
     `login_wall` (see reference doc for 3-condition rule), and `thin_content`.
   - `thin_content` is NOT a fixed character cutoff. Text is split into
     main-body text vs. chrome (`<nav>`/`<header>`/`<footer>`/`<aside>`), and
     the page is flagged thin only when the main-body text is near-empty
     (< 80 chars — a true block page or unfilled JS shell) OR the main-body
     text is a tiny fraction (< 15%) of a non-trivial total (a page that is
     almost all menu/boilerplate). The output carries `main_text_length`,
     `content_to_total_ratio`, and `thin_content_reason` as evidence. A
     minimalist hero page with a few sentences of real copy is not thin.
   - Non-boilerplate text extraction uses `html.parser`; it still includes
     any inline script/style
     text.
   - If the `requests` library is unavailable in the execution environment,
     returns a structured `"tool unavailable"` error rather than failing
     silently or crashing.
   - This script does NOT compare the two fetches against each other or
     decide whether bot-blocking occurred — it only returns both fetches'
     raw data side by side for the orchestrator to compare.

3. **Page signals (`scripts/check_page_signals.py`, via stdin JSON with
   `url`, `headers`, `content`)** — run once per fetch result (i.e. twice
   per sampled page, once for the browser fetch's content/headers and once
   for the bot fetch's, so the orchestrator can see if signals differ by
   identity):
   - **Indexing directives** — `noindex_meta` / `nofollow_meta` from the
     robots meta tag, and `noindex_header` / `nofollow_header` from the
     `X-Robots-Tag` response header (header keys matched case-insensitively).
     Bot-specific meta names (`googlebot`, `gptbot`, `claudebot`,
     `perplexitybot`, `google-extended`, …) are honoured alongside
     `name="robots"`, and the `content="none"` shorthand expands to
     noindex + nofollow. `robots_directives_seen` lists every directive
     parsed. `is_noindex` / `is_nofollow` are the rolled-up booleans
     (meta OR header) the orchestrator consumes.
   - `canonical_url` and `canonical_differs_from_self` — compares the
     canonical target against the page's own URL after normalizing (strip
     query string entirely, strip leading "www.", strip trailing slash,
     lowercase). `canonical_tag_count` and `duplicate_canonical_tags` flag
     pages that declare more than one `rel=canonical` (crawlers may ignore
     all of them); the last tag parsed is the one reported in `canonical_url`.

4. **Sitemap analysis (`scripts/check_sitemap.py <sitemap_url>`)**
   - Uses `resolved_url`'s domain plus the `sitemap_url` from step 1 if
     declared, otherwise falls back to `{resolved_url}/sitemap.xml`.
   - **Conventional-path probe**: pass `conventional_url` (`{resolved_url}/sitemap.xml`)
     when robots.txt declared the sitemap somewhere else. `conventional_path_check`
     then reports whether that path answers 2xx with a body that does not parse as a
     sitemap (`soft_200: true`) -- the signature of SPA catch-all routing serving a
     page for every unmatched route, the same shape as the `robots.malformed` check.
     A **404/410 there is correct behaviour** when robots.txt declares the sitemap
     elsewhere and is never reported. The probe is skipped entirely when
     `conventional_url` equals the sitemap already being checked, so no duplicate
     request is made.
   - Auto-decompresses gzip sitemaps (magic-byte detection) and parses
     XML namespace-safely (classifies `<loc>` entries as sitemap index items
     if inside `<sitemap>` tags OR if the URL string ends in `.xml`/`.xml.gz`).
   - Verifies SSL certificates by default; only on an SSL verification
     failure does it retry once with a relaxed context, flagging
     `ssl_verification_bypassed: true` at the top level and per
     sampled URL — this bypass flag being true is itself worth surfacing
     as a minor trust/health signal downstream, not just a technical
     workaround.
   - For a sitemap index file, expands an ADAPTIVE number of child sitemaps
     — `clamp(ceil(sqrt(child_count)), 3, 6)`, evenly spaced by index — and
     aggregates their URLs; reports `child_sitemaps_total`,
     `child_sitemaps_sampled`, `child_sitemaps_checked`, `sampling_strategy`,
     and per-child failures in `child_sitemap_errors` without treating a
     partial-traversal failure as "the site has no pages."
   - **Interpretation note for the orchestrator**: if `is_sitemap_index` is
     true, `child_sitemaps_checked` is 0, and `child_sitemap_errors` is
     non-empty, this is a traversal failure, not evidence the site lacks
     content — do not report "empty sitemap" as a finding in this case.
     If `child_sitemaps_total > child_sitemaps_sampled`, treat `url_count`
     as a sample across the expanded children only, not a site-wide total.
   - Spot-checks an ADAPTIVE sample of listed URLs —
     `clamp(ceil(sqrt(url_count)), 5, 15)`, evenly spaced by index (not the
     first N) — using a HEAD request that falls back to GET on 403/405.
     `sampling_strategy.urls_sampled` records the count actually used.
   - A 30s wall-clock ceiling covers the root fetch, every child sitemap, and
     every URL spot-check combined -- on a slow-but-live host this bounds the
     script even at the full 6-child/15-URL adaptive ceiling, which otherwise
     has no fixed limit on its own. Remaining work is skipped once the
     ceiling is hit (`time_budget_exceeded: true`, skipped entries recorded
     with an explicit `"skipped: ...budget exceeded"` error) rather than run
     to completion regardless of elapsed time.

5. **Crawl depth (`scripts/check_crawl_depth.py <start_url> <target_url>`)**
   - Bounded BFS to find the shortest click-path from `start_url` to
     `target_page`, same-domain links only. The exploration budget is
     ADAPTIVE: pass `site_url_count` (from step 4's `url_count`) and the
     script derives `max_pages = clamp(ceil(sqrt(N)*2), 20, 60)`,
     `max_depth` 3 (4 for N > 500), and a wall-clock cap of
     `clamp(15 + N/200, 20, 45)` seconds — always clamped so a large site
     can never turn this into a rate-abusing crawl. With no `site_url_count`
     the historical defaults apply (40 pages / depth 3 / 30 s). The chosen
     budget is echoed back as `exploration_budget`.
   - Discovers links via `<a href>` parsing, resolving relative URLs and
     discarding javascript:/mailto:/tel:/fragment-only links.
   - Target matching is done on normalized URLs (www/trailing-slash/
     fragment-insensitive), not exact string equality.
   - **Must be called with the SAME resolved robots parser as step 1**
     (pass the already-fetched robots data/parser from step 1 into this
     script rather than letting it re-fetch robots.txt independently — this
     script accepts an optional pre-resolved parser for exactly this
     reason). If no parser is supplied and this script's own standalone
     robots.txt fetch fails, it fails CLOSED (treats all paths as
     disallowed and stops crawling further) rather than silently allowing
     everything, and reports `robots_check_unavailable: true` so this
     degraded state is visible in the output.

## Output
A JSON object combining the raw outputs of all five scripts. Page-signal
results are grouped under each sampled page's browser/bot fetch pair so the
orchestrator can compare signals by identity:
```json
{
  "robots": { "...output of check_robots.py..." },
  "sampled_pages": [
    {
      "url": "https://example.com/product/1",
      "browser_fetch": { "...output of fetch_dual_identity.py's browser side...",
                          "page_signals": { "...output of check_page_signals.py..." } },
      "bot_fetch": { "...output of fetch_dual_identity.py's bot side...",
                     "page_signals": { "...output of check_page_signals.py..." } }
    }
  ],
  "sitemap": { "...output of check_sitemap.py..." },
  "crawl_depth": { "...output of check_crawl_depth.py..." }
}
```
`page_signals` output nests under each fetch, as shown. The orchestrator
(`synthesize_report.py` → `normalize_crawl_access`) accepts this
`sampled_pages` shape **and** a flat `{"dual_identity": …, "page_signals": …}`
single-page shape; when given `sampled_pages` it selects the first page whose
signals show a problem, so a `noindex` or bot block on page 3 is not masked by
a clean page 1.

Key fields the orchestrator consumes from this skill:
`robots.malformed`, `robots.root_blocked_agents`, `robots.disallowed` /
`robots.matched_rules`, `sitemap.sitemap_found`,
`crawl_depth.is_deep_url` / `.url_depth` (meaningful folders only -- a leading locale segment whose language part is a real ISO 639-1 code (`/de/`, `/en-us/`, `/zh-hant/`) and date segments `/2026/03/` are discounted; a two-letter folder that is not a language code (`/lp/`, `/qa/`) still counts and listed in `url_depth_ignored_segments`, so localized sites and dated blog URLs are not falsely reported as deep), and per page
`page_signals.is_noindex` / `.is_nofollow` / `.duplicate_canonical_tags`,
plus `bot_blocked` / `bot_challenged` / `rate_limited` /
`comparison_metrics.fingerprint_divergence` from the dual fetch.

No field in this output should assign a severity, name a root cause (e.g.
"blocked by Cloudflare"), or state a suggested fix — that interpretation
happens entirely in the downstream orchestrator/diagnosis skill.

## Guardrails & Constraints
- **Read-only**: never modifies the target site; no login, form submission,
  or CAPTCHA-solving anywhere in these scripts.
- **Respects robots.txt** for this skill's own crawling in
  `check_crawl_depth.py`, failing closed (not open) if robots.txt cannot be
  verified.
- **Defensive execution**: every script returns structured JSON on error
  (network failure, timeout, missing dependency) rather than raising an
  unhandled exception or printing a raw stack trace.
- **Global request budget**: across all five scripts combined, one full
  audit run against a single host should stay within roughly 60-90 total
  HTTP requests (robots.txt attempts + 2 fetches per sampled page + up to
  ~22 sitemap-related requests at the adaptive ceiling: ≤6 child sitemaps +
  ≤15 URL spot-checks + 1 root + up to 60 crawl-depth requests at the
  adaptive ceiling). Every adaptive cap in this skill is clamped precisely
  so this ceiling holds for a 20-page site and a 200,000-page site alike —
  the audit never becomes a rate-abusing crawl.
- **Wall-clock ceilings, per script, not just request counts**: a request
  *count* budget does not bound wall-clock time against a slow-but-live host
  (a handful of hanging connections can each eat a full timeout). `check_robots.py`
  (18s across all 4 candidates), `check_sitemap.py` (30s across the root fetch
  plus every child/spot-check), and `check_crawl_depth.py` (its existing
  `derive_budget` timeout) each enforce their own internal deadline and return
  partial results with an explicit `*_deadline_exceeded` / `time_budget_exceeded`
  flag rather than hang — this is what actually keeps a single-page audit
  inside the <5 minute handout constraint on a slow target. There is no
  process-level timer spanning scripts (each Bash invocation is a fresh
  process); staying under budget across MANY sampled pages is the calling
  agent's job — see audit-orchestrator's runtime-budget guidance for capping
  `sampled_pages` and running independent script calls in parallel.
- `response_headers` returned by `fetch_dual_identity.py` are raw and
  unclassified — this skill does not attempt to name which bot-management
  product (Cloudflare, Akamai, etc.) produced a given response; that
  classification, if needed, is orchestrator-level work using these raw
  headers as input.
