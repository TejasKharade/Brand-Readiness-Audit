# Client-Side Rendering & DOM Hydration Reference Checklist

This reference document outlines the thresholds, rendering architecture patterns, and remediation guidance used by `crawl-render-audit`.

## 1. How the hydration barrier is decided

`hydration_ratio` (`initial_raw_words / rendered_dom_words`) is reported as
**supporting evidence only** — it is not the decision. The bands below are for
human interpretation of that number:

| Band | Meaning |
| :--- | :--- |
| `0.80 - 1.00` | Optimal (SSR / SSG) — raw HTML carries nearly all body text. |
| `0.30 - 0.79` | Partial hydration — some secondary content needs JS. |
| `< 0.30` | Raw payload is mostly empty relative to the rendered DOM. |

`thin_initial_content_detected` (the actual verdict) is set when a rendered DOM
is available and **two or more** independent raw-vs-rendered structural deltas
agree, **or** the single unambiguous near-empty-shell signal fires:

- rendered main-area words ≥ 2× raw **and** raw main-area words `< 120`
- `≥ 2` headings present only after JS render
- `≥ 1` JSON-LD block injected only by JS
- `≥ 3` `<p>` blocks present only after JS render
- `≥ 6` `<li>` items present only after JS render
- **near-empty shell**: raw main-area words `< 25` while rendered DOM `> 150`
  (independently sufficient)

When no rendered DOM is supplied, a hydration *gap* cannot be measured, but a
**shell is still a shell whatever built it**. The raw-only verdict fires on any
of these independent signals, and every one that fires is listed in
`barrier_reasons`:

| Signal | Fires when |
| :--- | :--- |
| `noscript_requires_javascript` | a `<noscript>` block says "enable JavaScript" / "requires JavaScript" — the most explicit possible declaration. `<noscript>` text is still never counted as page content |
| `structurally_empty` | **0 headings and 0 `<p>`** in ≥ 50 KB of HTML — conclusive on its own, no framework fingerprint needed |
| `low_density_shell` | ≥ 20 content blocks holding < 3 words each — catches hydration shells whose absolute word count squeaks over the floor |
| bootstrap + empty content | a mount point / framework bundle / data-island **plus** a raw content area below the 120-word floor |
| `custom_shell` | ≥ 3 non-SSR hyphenated elements with < 25 raw words |
| skeleton | raw content area **below the 120-word floor** **and** either `skeleton_markers` (an id/class token `skeleton`, `shimmer`, `ghost-card`, `loading-placeholder`, …) or the prose-density heuristic. A bare `placeholder` token is not a marker — it is the standard name for input placeholders and lazy-image wrappers on fully server-rendered pages — and loading-state classes on a page that already ships ≥ 120 words of real content are ordinary lazy sections, not a shell |
| WAF | bot-challenge interstitial |

**Mount-point matching is by shape, not an enumerated list.** `SPA_MOUNT_ID_PATTERN`
matches branded and suffixed ids — `trello-root`, `acme-app`, `react-root-card-back`,
`shop-app-container` — so a fixed set of ids like `root`/`app`/`__next` is no longer
the limit.

**Density counts blocks on the same basis as words.** `content_blocks` excludes
`<nav>`/`<header>`/`<footer>`/`<aside>`, matching the word count, so a 50-link
footer cannot inflate the denominator and fake a hydration shell.

Turbo, Astro islands, AMP and other server-rendered custom elements are excluded
from the bootstrap signal. If `raw_html_present` is `false`, the verdict is
`null` (not audited), never `false`.

## 2. Structured Data Hydration Barriers

- **Server-Rendered JSON-LD**: JSON-LD script blocks are embedded directly inside `<head>` or `<body>` in the raw HTTP payload. Easily readable by fast HTTP scrapers (GPTBot, PerplexityBot).
- **Client-Injected JSON-LD**: JSON-LD scripts are appended dynamically via client-side JavaScript (`document.createElement('script')` or React Helmet). Invisible to non-JS scrapers.

## 3. Client-Side Redirect Hazards

- **Standard HTTP Redirects (301/302)**: Handled at the HTTP protocol layer. Preferred for search engine & AI crawler discoverability.
- **Meta Refresh (`<meta http-equiv="refresh" content="0; url=...">`)**: HTML-level redirect. Flagged **only when the `content` carries a `url=` target** — a bare `content="600"` is a periodic same-page refresh, not a redirect, and is reported separately under `meta_refresh_noop_no_url`.
- **JS Location Redirect**: string-literal assignments on any location accessor — `location.href = "..."`, `window.location = "..."`, `document.location = "..."`, `top/self/parent.location...`, and `location.replace(...)` / `location.assign(...)`. Requires JavaScript execution to discover the target, so it is a dead-end for non-JS crawlers. Targets assigned from a runtime variable (`location.href = target`) cannot be resolved by static analysis and are not claimed.
- **SPA client routing** (`history.pushState`, `useNavigate`, Vue/Angular routers): reported as a soft signal (`spa_client_routing_detected`), not a hard redirect — acceptable when every route is also reachable as server-rendered HTML.

## 4. Recommended Architectural Fixes

1. **Server-Side Rendering (SSR)**: Implement Next.js App Router, Nuxt.js, or SvelteKit to render full HTML on the server.
2. **Static Site Generation (SSG)**: Pre-render marketing pages, blogs, and product detail pages at build time.
3. **Dynamic Rendering**: Serve pre-rendered HTML payloads specifically to recognized AI crawler User-Agents (e.g. `GPTBot`, `ClaudeBot`).
