# AI Crawler Checklists & Inspection Rules

## Common AI Crawler User-Agents

- `GPTBot` (OpenAI Scraper)
- `ChatGPT-User` (OpenAI On-Demand Search)
- `ClaudeBot` / `Claude-Web` (Anthropic)
- `PerplexityBot` (Perplexity AI)
- `Bytespider` (ByteDance)
- `Google-Extended` (Gemini Training / Grounding)

## Scope

`robots.txt` and HTTP-level access rules are audited by **`crawl-access-audit`**,
not here. This skill only inspects HTML payloads for rendering / redirect
barriers. The user-agent list above is for reference (it is the same crawler
population both skills care about).

## Audit Rules (this skill)

1. **Client-Side Rendering Checks**:
   - A SPA mount point (`<div id="root">`, `<div id="app">`, `<div id="__next">`, framework class fragments, …) that is **empty or near-empty in the initial response** is a rendering barrier. A mount point that already contains server-rendered content (e.g. hydrated Next.js SSR) is **not** a barrier.
   - Verdict is multi-signal (see `rendering_checklists.md` §1), never a single word-count or ratio cutoff.

2. **Redirect Checks**:
   - Meta refresh counts only with a `url=` target; JS `location` assignments with a string-literal target are dead-ends for non-JS crawlers.
