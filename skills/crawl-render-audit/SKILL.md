---
name: crawl-render-audit
description: Audits website off-site discoverability by checking robots.txt rules for AI crawlers, client-side JavaScript rendering barriers, non-text locked facts, and machine extractability of core page content.
license: MIT
---

# Crawl & Render Audit Skill

## When to use
Use when auditing a website's technical discoverability for AI search engines, LLM scrapers (GPTBot, ClaudeBot, PerplexityBot), and automated web indexers.

## Inputs
- `url` or `domain`: Target site URL or hostname.

## Procedure

1. **AI Crawler Access Verification (`robots.txt` & WAF Detection)**:
   - Analyze `check_robots.py` output across major AI crawlers (`GPTBot`, `ClaudeBot`, `PerplexityBot`, `CCBot`, `Bytespider`).
   - Flag explicit `Disallow` directives on key brand pages as `Critical` discoverability blockers.
   - Inspect fingerprint evidence array from `fetch_dual_identity.py` (Cloudflare, AWS WAF, Akamai, PerimeterX). Flag active bot challenges or HTTP 403/503 blocks as `High` severity findings.

2. **JavaScript Rendering & DOM Hydration Audit**:
   - Compare raw HTML HTTP response vs. rendered DOM.
   - Compare `content_length_ratio` and `thin_content_detected` flag between browser and bot fetches.
   - Flag facts (pricing, specs, brand claims) requiring client-side JS execution to render as discoverability risks for non-JS AI scrapers.

3. **Page Indexing Directives & Canonical Health**:
   - Inspect meta tags (`noindex`, `noai`, `noimageindex`) and `X-Robots-Tag` headers from `check_page_signals.py`.
   - Flag any `noindex` or `noai` directives on public marketing/product pages.
   - Verify `canonical` link consistency.

4. **Sitemap Health & Crawl Depth Analysis**:
   - Evaluate `check_sitemap.py` results:
     - Distinguish between genuinely empty sitemaps vs. traversal failures (`is_sitemap_index: true`, `child_sitemaps_checked: 0`, and `child_sitemap_errors` present).
     - Check `ssl_verification_bypassed` flags on sitemap or sampled URLs to identify misconfigured SSL certificates.
   - Inspect `check_crawl_depth.py` outputs. Flag key target pages requiring >3 clicks to reach from root.

## Output
Emits a list of evidence-backed findings focused on technical crawlability and machine rendering accessibility.
