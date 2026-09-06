---
name: ai-crawler-access-audit
description: Audit any website for crawler accessibility and AI discoverability blocks including robots.txt directives, live search crawler discrimination, llms.txt manifest presence, sitemap validity, and HTTP response headers. Use when diagnosing why an AI assistant cannot reach or index a domain, evaluating bot blocking policies, or pre-flighting an audit.
license: Apache-2.0
allowed-tools:
  - run_command
---

# AI Crawler Access Audit

Audits protocol-level gates that dictate whether conversational AI assistants (such as ChatGPT Search, Perplexity AI, Claude Web, and Gemini) can access, crawl, and index a domain's public content.

## When to use
Use this skill at the beginning of an audit to evaluate:
- Whether `robots.txt` blocks all crawlers or singles out AI search engines.
- Whether core content paths (`/docs/`, `/blog/`, `/products/`) are accidentally disallowed.
- Whether the site actively discriminates against AI bot user-agents with 403/401 HTTP errors.
- Whether a standardized `llms.txt` context manifest is published.
- Whether XML sitemaps are declared, reachable, and well-formed.

## Inputs
- `target`: A URL or domain name (e.g., `https://example.com` or `example.com`).

## Procedure (Deterministic Steps)

1. **Execute Diagnostic Check**:
   Run the bundled pure Python inspection script against the target domain:
   ```bash
   python scripts/check_access.py <target> --json
   ```
   *Note: This script uses only Python standard library (zero third-party dependencies).*

2. **Evaluate robots.txt & Transport Context**:
   - Differentiate **Live Search Crawlers** (`OAI-SearchBot`, `PerplexityBot`, `Claude-Web`) from **Training Scrapers** (`GPTBot`, `CCBot`).
   - Distinguish legitimate administrative disallows from harmful public content disallows. Consult `references/bot_directory.md`.
   - Verify SSL/TLS validity and flag certificates expired or expiring within 14 days.
   - Inspect redirect chains: treat 1-2 hops as normal; flag chains with 3 or more hops as latency optimization opportunities; flag loops as critical.

3. **Verify AI Manifests, Sitemap & HTML Directives**:
   - Check `/llms.txt` and `/ai.txt` manifests.
   - Validate XML sitemap syntax and extract URL inventory.
   - Check both HTTP headers (`X-Robots-Tag`) and HTML head (`<meta name="robots">`) for indexing restrictions.

## Output Schema
Emits findings along with a curated `sampled_pages` inventory for downstream specialist skills:
```json
{
  "site": "example.com",
  "audited_at": "YYYY-MM-DDTHH:MM:SSZ",
  "summary": {
    "total_findings": 0,
    "critical": 0,
    "high": 0,
    "medium": 0
  },
  "findings": [
    {
      "id": "ACC-001",
      "title": "Finding summary title",
      "severity": "critical | high | medium | low",
      "evidence": "Exact HTTP status code, URL, or rule string observed",
      "suggested_action": {
        "summary": "Concrete mechanism-sound fix",
        "priority": "critical | high | medium | low"
      }
    }
  ],
  "sampled_pages": {
    "homepage": "https://example.com",
    "total_discovered": 84,
    "doc_pages": ["https://example.com/docs/..."],
    "blog_pages": ["https://example.com/blog/..."],
    "curated_sample": ["https://example.com", "https://example.com/docs/..."]
  }
}
```
