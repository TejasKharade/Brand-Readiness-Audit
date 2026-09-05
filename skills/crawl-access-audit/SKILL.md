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
     robots.txt content (flagged as `malformed`).
   - For each path in `test_paths` and each agent in `bot_user_agents`
     (passed via stdin JSON), reports whether that path is disallowed.
   - Extracts `crawl_delay` (from the `*` block) and `sitemap_url` if
     declared.
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
     `login_wall` (see reference doc for 3-condition rule), and `thin_content`
     (default threshold 300 characters).
   - Text extraction includes all visible text via `html.parser`; it does
     not currently strip `<script>`/`<style>`/`<nav>`/`<header>`/`<footer>`
     content specifically, so `thin_content` and fingerprint checks operate
     on the page's full text content including any inline script/style
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
   - `noindex_meta` / `noindex_header` — checked case-insensitively against
     header keys.
   - `canonical_url` and `canonical_differs_from_self` — compares the
     canonical target against the page's own URL after normalizing (strip
     query string entirely, strip leading "www.", strip trailing slash,
     lowercase). Does not currently detect duplicate/conflicting canonical
     tags on the same page (only the last one parsed is retained).

4. **Sitemap analysis (`scripts/check_sitemap.py <sitemap_url>`)**
   - Uses `resolved_url`'s domain plus the `sitemap_url` from step 1 if
     declared, otherwise falls back to `{resolved_url}/sitemap.xml`.
   - Auto-decompresses gzip sitemaps (magic-byte detection) and parses
     XML namespace-safely (classifies `<loc>` entries as sitemap index items
     if inside `<sitemap>` tags OR if the URL string ends in `.xml`/`.xml.gz`).
   - Verifies SSL certificates by default; only on an SSL verification
     failure does it retry once with a relaxed context, flagging
     `ssl_verification_bypassed: true` at the top level and per
     sampled URL — this bypass flag being true is itself worth surfacing
     as a minor trust/health signal downstream, not just a technical
     workaround.
   - For a sitemap index file, expands up to the first 3 child sitemaps
     and aggregates their URLs; reports `child_sitemaps_total`,
     `child_sitemaps_checked`, and per-child failures in
     `child_sitemap_errors` without treating a partial-traversal failure as
     "the site has no pages."
   - **Interpretation note for the orchestrator**: if `is_sitemap_index` is
     true, `child_sitemaps_checked` is 0, and `child_sitemap_errors` is
     non-empty, this is a traversal failure, not evidence the site lacks
     content — do not report "empty sitemap" as a finding in this case.
     Similarly, if `child_sitemaps_total > 3`, treat `url_count` as a
     sample across the first 3 children only, not a site-wide total.
   - Samples up to 5 listed URLs (evenly spaced by index, not the first 5)
     and checks each resolves, using a HEAD request that falls back to GET
     if the server returns 403/405 for HEAD.

5. **Crawl depth (`scripts/check_crawl_depth.py <start_url> <target_url>`)**
   - Bounded BFS (max depth 3, max 40 pages visited, 30-second wall-clock
     cap, same-domain links only) to find the shortest click-path from
     `start_url` to `target_page`.
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
  audit run against a single host should stay within roughly 60-80 total
  HTTP requests (robots.txt attempts + 2 fetches per sampled page + up to 6
  sitemap-related requests + up to 40 crawl-depth requests). The
  orchestrator is responsible for tracking this budget across scripts if
  auditing many sampled pages in one run.
- `response_headers` returned by `fetch_dual_identity.py` are raw and
  unclassified — this skill does not attempt to name which bot-management
  product (Cloudflare, Akamai, etc.) produced a given response; that
  classification, if needed, is orchestrator-level work using these raw
  headers as input.
