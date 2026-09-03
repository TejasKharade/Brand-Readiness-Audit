# AI Crawler Checklists & Inspection Rules

## Common AI Crawler User-Agents

- `GPTBot` (OpenAI Scraper)
- `ChatGPT-User` (OpenAI On-Demand Search)
- `ClaudeBot` / `Claude-Web` (Anthropic)
- `PerplexityBot` (Perplexity AI)
- `Bytespider` (ByteDance)
- `Google-Extended` (Gemini Training / Grounding)

## Audit Rules

1. **robots.txt Checks**:
   - If `User-agent: *` contains `Disallow: /`, mark as **CRITICAL**.
   - If specific AI agents (`GPTBot`, `ClaudeBot`) are explicitly disallowed from core content sections, mark as **HIGH**.

2. **Client-Side Rendering Checks**:
   - If `<div id="app"></div>` or `<div id="root"></div>` contains 0 text nodes in initial response, mark as **HIGH** (JS rendering required for discovery).
