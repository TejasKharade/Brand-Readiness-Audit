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

1. **AI Crawler Access Verification**:
   - Inspect `robots.txt` for disallow rules targeting AI agents (e.g. `User-agent: GPTBot`, `User-agent: ClaudeBot`, `User-agent: PerplexityBot`, `User-agent: CCBot`).
   - Flag any blocked paths containing primary product/brand information as high-severity discoverability findings.

2. **JavaScript Rendering & DOM Hydration Audit**:
   - Compare raw HTML HTTP responses against client-side rendered DOM.
   - Detect whether critical brand facts, pricing, or product specs require JavaScript execution to be visible.
   - Flag facts hidden behind dynamic JS rendering as potential discovery gaps for non-JS crawlers.

3. **Text Extractability & Non-Text Fact Lockout**:
   - Inspect page structure for key information locked inside raster images, canvas elements, or PDFs without plain text alt tags or transcriptions.
   - Verify semantic HTML tags (`<h1>`-`<h6>`, `<p>`, `<article>`, `<section>`, `<table>`) are used instead of plain `<div>` soup.

## Output
Emits a list of evidence-backed findings focused on technical crawlability and machine rendering accessibility.
