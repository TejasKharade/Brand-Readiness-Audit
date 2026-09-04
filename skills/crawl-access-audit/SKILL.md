---
name: crawl-access-audit
description: Gathers raw, structured data on whether a website's pages are
  reachable by AI-assistant and search crawlers — robots.txt rules, actual
  server behavior under browser vs. bot identities, page-level indexing
  signals, sitemap health, and crawl depth. Produces structured facts only;
  does not diagnose root causes or assign severity. Use as the first data-
  gathering stage of an AI-discoverability audit, feeding a diagnosis/
  orchestrator skill.
license: MIT
---

# Crawl Access Audit Skill

## When to use
Use as the first data-gathering stage of an AI-discoverability audit, feeding a diagnosis/orchestrator skill. This skill performs ONLY the "data gathering" half of an accessibility audit — collecting raw, uninterpreted facts about whether/how a crawler can access a website.

## Inputs
- `domain`: Target site domain (e.g., `example.com`).
- `sampled_pages`: A list of specific page URLs to audit (e.g., `["https://example.com/about", "https://example.com/product/1"]`).
- `target_page` (Optional): A target page URL for crawl depth testing.

## Procedure
1. **Robots.txt Analysis**: Run `check_robots.py` to parse `robots.txt` and gather rules for various AI bots.
2. **Dual-Identity Fetch**: For each sampled page, run `fetch_dual_identity.py` to fetch the page twice (once as a real browser, once as a specific AI crawler) to compare server responses, detect access barriers, and capture raw headers and content. *(Integration Note: The orchestrator MUST pass the `resolved_url` domain returned by `check_robots.py` to subsequent scripts. Furthermore, if `check_robots.py` indicates the path is explicitly disallowed for AI bots, the orchestrator MUST skip the AI bot fetch for that URL to respect `robots.txt` compliance, and instead flag the blockage immediately as a finding.)*
3. **Page Signals Extraction**: For each sampled page, run `check_page_signals.py` (using output from step 2) to extract indexing signals (`noindex`, `canonical`).
4. **Sitemap Analysis**: Run `check_sitemap.py` to spot-check sitemap validity and sample URLs.
5. **Crawl Depth Check**: Run `check_crawl_depth.py` to perform a bounded breadth-first crawl to find the shortest path to a target page.

*Note: This skill ONLY gathers data and does not interpret it. If a tool/capability is unavailable (e.g. no network, `requests` not installed), report "could not verify — tool unavailable" as a finding-level note rather than omitting the check.*

## Output
A JSON object combining the raw outputs of all five scripts:
```json
{
  "robots": { ... },
  "dual_fetches": [ { "url": "...", "browser_fetch": { ... }, "bot_fetch": { ... }, "page_signals": { ... } } ],
  "sitemap": { ... },
  "crawl_depth": { ... }
}
```

## Allowed Tools
- Web fetch / HTTP client
- Code execution (Python)

## Guardrails & Constraints
- **Read-Only**: Must never modify the target site. No login, no form-submission, no CAPTCHA-solving.
- **Respect robots.txt**: For its OWN crawling in `check_crawl_depth.py`.
- **Rate-Limiting**: Respects delays between requests to the same host.
- **Global Request Budget**: Across ALL scripts combined, one full audit run against a single host must not exceed roughly 60-80 total HTTP requests (robots.txt + 2 requests per sampled page x N pages + sitemap spot-checks + crawl-depth BFS capped at 40).
