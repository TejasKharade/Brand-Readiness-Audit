---
name: crawl-access-audit
description: Gathers raw, structured data on whether a website's pages are
  reachable by AI-assistant and search crawlers — robots.txt rules (split by
  live-search vs. training crawlers), actual server behavior under browser vs.
  bot identities, TLS certificate validity, page-level indexing signals,
  sitemap health with a representative page sample, and crawl depth. Produces structured facts only;
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
   - **Retrieval vs. training crawlers.** By default every token in
     `references/ai_crawler_classes.json` is tested (plus `*`), and each
     tested agent is reported in `agent_classes` with its documented purpose:
     `retrieval` (fetches pages for live AI search / assistant answers —
     `OAI-SearchBot`, `ChatGPT-User`, `PerplexityBot`, `Claude-SearchBot`,
     `Googlebot`, `Bingbot`, …) or `training` (collects content for model
     training only — `GPTBot`, `ClaudeBot`, `CCBot`, `Bytespider`,
     `Google-Extended`, …). Blocking `GPTBot` keeps a site out of future
     OpenAI model training but does **not** remove it from ChatGPT search
     citations, which come from `OAI-SearchBot`. `*` is classed `wildcard`; a
     token not in the file is `unclassified`. Each entry records whether the
     operator's documentation was checked (`verified`) and
     `honors_robots_txt`: user-initiated fetchers such as `ChatGPT-User`,
     `Perplexity-User` and `Meta-ExternalFetcher` are documented as fetching
     at a person's request with robots.txt possibly not applying, so a
     robots.txt block on them is **not an effective control** and is never
     scored — it is only mentioned in the evidence.
   - The orchestrator raises **critical** when a retrieval (or unclassified)
     crawler cannot fetch `/`, and **high** when one is disallowed on a tested
     key page. When every tested retrieval crawler is still allowed and only
     training tokens (or `*`, with named retrieval crawlers explicitly
     allowed) are blocked, it raises **medium** at the root and **low** on a
     key page instead — often a deliberate licensing choice, and not a loss
     of live AI search visibility. Output without `agent_classes` (older
     callers) is treated exactly as before: every block is retrieval-impacting.
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
   - Returns `bot_blocked` (bot status 401/403, or `generic_block` matched a
     known signal), `bot_soft_blocked` (both fetches answered 2xx, but the
     bot's content is `thin_content` while the browser's is not -- a custom
     WAF/CDN interstitial served with a healthy status code, worded however
     that vendor happens to word it, which no fixed keyword list can
     enumerate in advance), `bot_challenged`, `rate_limited`, and
     `robots_decisions: {browser, bot}` (each identity's gate decision,
     including the exact `rule`/`reason` that permitted or refused it) at the
     **top level of the dual-fetch result** -- alongside, not instead of, the
     nested `browser_fetch`/`bot_fetch` payloads. **These top-level fields
     are the orchestrator's only reliable signal that robots.txt permitted a
     request the site's own security infrastructure then blocked anyway (a
     policy/enforcement mismatch, more serious than a robots.txt disallow) --
     dropping them while assembling `sampled_pages` below silently disables
     that detection**, since `synthesize_report.py` can only fall back to
     reconstructing a coarser guess from the raw fetch bodies, which cannot
     recover `robots_decisions` at all.
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
   - **Choosing pages to audit: `representative_sample`.** Pages sharing a URL
     structure are almost always one template, so the script groups listed
     URLs by structure (first path segment, and the group's typical depth —
     no keyword lists, so any language or naming scheme works) and returns
     up to 6 picks: the homepage, then one URL from each group in descending
     group size, then a second URL from the largest groups. Non-page files
     (`.pdf`, images, `.xml`, …) and URLs whose spot-check returned non-2xx
     are skipped; `url_groups` reports each group's size. Use the homepage
     plus the first 1–2 other entries as `sampled_pages` — this covers the
     templates that render the most pages, where the first N sitemap entries
     are usually all one template (all blog posts, or all products).

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

6. **TLS certificate (`scripts/check_tls.py <host-or-url>`)** — one TLS
   handshake, no HTTP request. Pass the host the audited pages are actually
   served from (the host of `bot_fetch.final_url`, not an unresolved alias):
   - An expired, not-yet-valid, hostname-mismatched, self-signed or revoked
     certificate makes every standards-compliant client — AI crawlers
     included — abort before fetching anything, whatever robots.txt allows.
     The dual-identity fetch shows only a bare connection error with no
     content; this step names the cause. Failures are classified from
     OpenSSL's verify code (`failure_kind`, `verify_code`, `verify_message`),
     with no certificate-parsing dependency.
   - `untrusted_chain` usually means the server omits its intermediate
     certificate (browsers recover, most non-browser clients do not), but a
     trust store missing on the auditing machine looks identical, so the
     orchestrator reports it as high at reduced confidence rather than critical.
   - A valid certificate reports `not_after`, `days_remaining` and
     `expiring_soon` (≤ 14 days). A DNS or connection failure sets
     `https_reachable: false` with `error` and is **not** a certificate
     finding — reachability is the dual fetch's job.
   ```bash
   python skills/crawl-access-audit/scripts/check_tls.py '{"url": "https://www.example.com/"}'
   ```

## Output
A JSON object combining the raw outputs of all six scripts. Page-signal
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
                     "page_signals": { "...output of check_page_signals.py..." } },
      "bot_blocked": false,
      "bot_soft_blocked": false,
      "bot_challenged": false,
      "rate_limited": false,
      "comparison_metrics": { "fingerprint_divergence": false },
      "robots_decisions": { "browser": { "allowed": true }, "bot": { "allowed": true } }
    }
  ],
  "sitemap": { "...output of check_sitemap.py..." },
  "crawl_depth": { "...output of check_crawl_depth.py..." },
  "tls": { "...output of check_tls.py..." }
}
```
`page_signals` output nests under each fetch, as shown. Each `sampled_pages`
entry must also carry forward `bot_blocked` / `bot_soft_blocked` /
`bot_challenged` / `rate_limited` / `comparison_metrics` / `robots_decisions`
from `fetch_dual_identity.py`'s own return value for that page -- do not
nest only `browser_fetch`/`bot_fetch` and drop the rest; those top-level
fields are what the orchestrator uses to detect a policy/enforcement
mismatch (see step 2 above). The orchestrator
(`synthesize_report.py` → `normalize_crawl_access`) accepts this
`sampled_pages` shape **and** a flat `{"dual_identity": …, "page_signals": …}`
single-page shape; when given `sampled_pages` it selects the first page whose
signals show a problem, so a `noindex` or bot block on page 3 is not masked by
a clean page 1.

Key fields the orchestrator consumes from this skill:
`robots.malformed`, `robots.root_blocked_agents`, `robots.disallowed` /
`robots.matched_rules` / `robots.agent_classes`, `sitemap.sitemap_found`,
`tls.certificate_valid` / `.failure_kind` / `.expiring_soon`, each sampled
page's `bot_fetch.status` / `.redirect_count` (a crawler fetch that ends on
a 3xx never reached a page: a redirect loop or too many hops; 3+ hops that do
resolve are a low-severity efficiency finding),
`crawl_depth.is_deep_url` / `.url_depth` (meaningful folders only -- a leading locale segment whose language part is a real ISO 639-1 code (`/de/`, `/en-us/`, `/zh-hant/`) and date segments `/2026/03/` are discounted; a two-letter folder that is not a language code (`/lp/`, `/qa/`) still counts and listed in `url_depth_ignored_segments`, so localized sites and dated blog URLs are not falsely reported as deep), and per page
`page_signals.is_noindex` / `.is_nofollow` / `.duplicate_canonical_tags`,
plus `bot_blocked` / `bot_soft_blocked` / `bot_challenged` / `rate_limited` /
`comparison_metrics.fingerprint_divergence` / `robots_decisions` from the
dual fetch.

No field in this output should assign a severity, name a root cause (e.g.
"blocked by Cloudflare"), or state a suggested fix — that interpretation
happens entirely in the downstream orchestrator/diagnosis skill.

## Guardrails & Constraints
- **Read-only**: never modifies the target site; no login, form submission,
  or CAPTCHA-solving anywhere in these scripts.
- **Respects robots.txt for every request this marketplace makes.**
  `scripts/robots_gate.py` is the single gate: the dual-identity fetch, the
  sitemap URL spot-checks, `check_crawl_depth.py`'s link-following crawl, the
  engagement skill's resource-weight probes, the readability skill's linked-PDF
  reads and the render skill's headless browser all ask it before opening a
  connection. It is built from the robots.txt `check_robots.py` already
  fetched, so compliance costs **zero extra requests**.
  - The check is made against the **identity being presented**, not a generic
    one. `fetch_dual_identity.py` sends a `GPTBot` user-agent, so on a site
    whose robots.txt says `User-agent: GPTBot / Disallow: /` the bot leg is
    **not sent at all** — fetching it would mean requesting a forbidden path
    while identifying as the crawler that was forbidden. The browser leg is
    evaluated against the `*` group and still runs if `*` permits it.
  - **RFC 9309 status semantics**, which are not the same as "reachable":
    `2xx` applies the rules; `4xx` (404 included) means no robots.txt exists
    and nothing is disallowed; `5xx`, a timeout or a DNS failure means
    robots.txt is *unreachable*, and the gate **fails closed** and fetches
    nothing. `robots.txt` itself is always fetchable.
  - **`Crawl-delay` is honoured** where declared, as a floor on the existing
    inter-request spacing, capped at 10 s so one hostile directive cannot
    consume the audit's <5 min budget.
  - A refused fetch is recorded as refused — `skipped_by_robots` with the
    deciding rule — and surfaces in the report's
    `audit_metadata.robots_restricted_fetches`. It is never reported as a
    site defect: "we were not permitted to look" and "we looked and found
    nothing" are different claims, and only the second belongs in a finding.
- **Defensive execution**: every script returns structured JSON on error
  (network failure, timeout, missing dependency) rather than raising an
  unhandled exception or printing a raw stack trace.
- **Global request budget**: across all six scripts combined (`check_tls.py`
  adds a single TLS handshake and no HTTP request), one full
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
