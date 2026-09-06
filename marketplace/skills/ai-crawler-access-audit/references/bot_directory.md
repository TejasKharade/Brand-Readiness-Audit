# AI Bot Directory & robots.txt Interpretation Guide

This reference provides the classification criteria for AI user agents and distinguishing legitimate crawl-budget disallows from harmful AI invisibility defects.

## 1. AI User-Agent Classification

| User-Agent Token | Classification | Primary Operator | Impact if Blocked | Recommended Severity |
| :--- | :--- | :--- | :--- | :--- |
| `OAI-SearchBot` | Live Search / Citation | OpenAI | Complete exclusion from real-time ChatGPT Search citations | **HIGH / CRITICAL** |
| `PerplexityBot` | Live Search / Citation | Perplexity AI | Complete exclusion from Perplexity answer citations | **HIGH / CRITICAL** |
| `Claude-Web` | Live Search / Citation | Anthropic | Exclusion from Claude real-time web retrieval | **HIGH / CRITICAL** |
| `ClaudeBot` | General Crawler | Anthropic | Reduced training and background knowledge indexing | **MEDIUM** |
| `Google-Extended` | Knowledge / Gemini | Google | Prevents Gemini and Google AI Overviews from training on data | **MEDIUM** |
| `GPTBot` | Training Scraper | OpenAI | Prevents OpenAI model training; does NOT block search citations | **LOW / INFORMATIONAL** |
| `CCBot` | Common Crawl | Common Crawl | Prevents bulk open LLM training corpus inclusion | **LOW / INFORMATIONAL** |
| `Bytespider` | Training Scraper | ByteDance | Prevents ByteDance model scraping | **LOW / INFORMATIONAL** |

---

## 2. Disallow Context: Legitimate vs. Harmful Blocking

A `Disallow` rule in `robots.txt` is not inherently a defect. Automated audits must evaluate the **path context** before raising a finding:

### A. Legitimate Disallows (Expected & Beneficial — DO NOT Flag as Defects)
Blocking these paths is standard web hygiene and preserves crawl budget:
* Administrative portals: `/admin/`, `/dashboard/`, `/wp-admin/`, `/backend/`
* Transactional flows: `/cart/`, `/checkout/`, `/account/`, `/billing/`
* Internal APIs & search filters: `/api/internal/`, `/search?*`, `/*?filter=*`
* User authentication: `/login`, `/signup`, `/auth/`, `/logout`

### B. Harmful Disallows (Direct Causes of AI Invisibility — ALWAYS Flag)
* Site-wide blocks: `Disallow: /` or `Disallow: /*`
* Core content directories: `/docs/`, `/documentation/`, `/blog/`, `/articles/`, `/guides/`
* Product and pricing catalogs: `/product/`, `/products/`, `/pricing/`, `/features/`
* About & company trust pages: `/about/`, `/company/`, `/team/`

---

## 3. Crawl-Delay Guidelines

* AI search engines operate within human conversational response deadlines ($< 3\text{ seconds}$).
* A `Crawl-delay` $> 10\text{ seconds}$ forces search crawlers to abandon multi-page retrieval or drop the domain from deep citation queries.
