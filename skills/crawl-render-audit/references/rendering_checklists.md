# Client-Side Rendering & DOM Hydration Reference Checklist

This reference document outlines the thresholds, rendering architecture patterns, and remediation guidance used by `crawl-render-audit`.

## 1. Hydration Ratio Thresholds

- **Hydration Ratio Formula**: `initial_raw_words / rendered_dom_words`
- **Optimal (SSR / SSG)**: `0.80 - 1.00`. The initial HTML payload carries almost all visible body text and headings.
- **Moderate Hydration Gap**: `0.30 - 0.79`. Some secondary content or dynamic components require client-side JS rendering.
- **Severe Client-Side Barrier**: `< 0.30` or `raw_words < 50` while `rendered_words > 300`. Non-JS crawlers see a thin/empty page shell, failing indexation.

## 2. Structured Data Hydration Barriers

- **Server-Rendered JSON-LD**: JSON-LD script blocks are embedded directly inside `<head>` or `<body>` in the raw HTTP payload. Easily readable by fast HTTP scrapers (GPTBot, PerplexityBot).
- **Client-Injected JSON-LD**: JSON-LD scripts are appended dynamically via client-side JavaScript (`document.createElement('script')` or React Helmet). Invisible to non-JS scrapers.

## 3. Client-Side Redirect Hazards

- **Standard HTTP Redirects (301/302)**: Handled at the HTTP protocol layer. Preferred for search engine & AI crawler discoverability.
- **Meta Refresh (`<meta http-equiv="refresh">`)**: HTML-level redirect. May be delayed or ignored by fast scrapers.
- **JS Location Redirect (`window.location = "..."`)**: Requires JavaScript execution to discover the target URL. Creates a discovery dead-end for non-JS crawlers.

## 4. Recommended Architectural Fixes

1. **Server-Side Rendering (SSR)**: Implement Next.js App Router, Nuxt.js, or SvelteKit to render full HTML on the server.
2. **Static Site Generation (SSG)**: Pre-render marketing pages, blogs, and product detail pages at build time.
3. **Dynamic Rendering**: Serve pre-rendered HTML payloads specifically to recognized AI crawler User-Agents (e.g. `GPTBot`, `ClaudeBot`).
