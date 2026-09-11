# Content Depth Advisory Bands Reference

This reference documents the **advisory** word bands used by `scripts/check_content_depth.py`.
They are loaded from `reachability_thresholds.json` (the script falls back to identical
built-in defaults if the file is missing).

> [!WARNING]
> **These are advisory bands, not cutoffs.**
> - The script **detects page intent itself** (JSON-LD `@type` → `og:type` → URL path →
>   layout) and only consults a band for a *content-bearing* intent
>   (`product`, `service`, `article`, `homepage`, `category`).
> - `utility`, `app`, `media`, and `unknown` intents are **never scored** — this is how
>   login pages, checkout pages, dashboards, calculators, and minimalist landing pages
>   avoid false positives.
> - `below_reference_range` is set **only when three independent signals agree**: word
>   count below the band **and** `paragraph_count <= 2` **and** `heading_count <= 2`.
>   A low word count on a page that still has real structure (multiple sections /
>   paragraphs / headings) is treated as an intentionally lean page and is **not** flagged.

## Advisory bands per detected intent

| Detected intent | Advisory min words | Recommended | Scored? | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `product`  | 120 | 400+  | yes | Specs, features, pricing/warranty context. |
| `service`  | 150 | 500+  | yes | Process, deliverables, outcomes. |
| `article`  | 350 | 1000+ | yes | Editorial / educational depth. |
| `homepage` | 80  | 300+  | yes | Orientation copy; homepages vary widely, so the band is low. |
| `category` | 60  | 250+  | yes | Listing pages carry mostly links; only near-empty ones matter. |
| `utility`  | — | — | **no** | Login / contact / cart / checkout / search / legal / 404. |
| `app`      | — | — | **no** | Dashboards, consoles, tools, configurators. |
| `media`    | — | — | **no** | Pages whose payload is a video / audio / image object. |
| `unknown`  | — | — | **no** | Intent could not be determined; raw counts still reported. |

The bands are deliberately conservative — they exist to catch a genuinely empty
`product` / `article` stub, not to police prose length. Adjust after real-site field
testing if needed; changing the JSON file is enough, no code change required.
