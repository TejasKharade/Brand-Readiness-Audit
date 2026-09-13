---
name: readability-audit
description: Analyzes already-fetched HTML content to gather objective, structured evidence regarding machine extractability - structured data (JSON-LD), semantic HTML structure, visible vs. structured content consistency, and non-text fact lockout. Combines standalone Python parsing scripts with Orchestrator-LLM semantic evaluation for unconventional edge cases.
license: MIT
compatibility: Requires Python 3; minimal outbound network (capped PDF text-layer fetches only)
allowed-tools: Bash Read WebFetch
---

# Readability Audit Skill

## When to use
Use during an AI-readability or discrepancy audit to collect objective structural evidence from page HTML that has already been fetched by an upstream skill or orchestrator.

This skill:
- Expects html and url supplied directly by the caller.
- Does NOT crawl or fetch normal web pages themselves.
- Does NOT assign severity or generate final remediations (leaves this to the audit-orchestrator).

The ONLY permitted network activity is capped PDF-link text layer inspection performed by check_nontext_facts.py (maximum 3 PDFs per page).

## Inputs
- html: Raw HTML content string of the target page (string) — **reuse
  `crawl-access-audit`'s `fetch_dual_identity.py` output
  (`browser_fetch.content`) for this same page; do not fetch it again.**
  `WebFetch` is declared in `allowed-tools` only for the capped PDF
  text-layer reads in `check_nontext_facts.py`, not for re-fetching the page.
- url: Absolute URL of the target page (string).

## Procedure & Hybrid Execution Flow

> [!IMPORTANT]
> **Prefer `scripts/run_all.py` over calling the four scripts below separately.**
> None of them do any network I/O of their own (`check_nontext_facts.py`'s
> linked-PDF reads are internally wall-clock-bounded either way), so there is
> no parallelism benefit to four separate subprocess calls — only four times
> the process-spawn and orchestrator-turn overhead. `run_all.py` takes the
> same `{html, url, robots}` input and returns the same four output keys
> (`structured_data`, `semantic_structure`, `content_consistency`,
> `nontext_facts`) in one JSON object, by importing and calling these exact
> same functions — detection logic and output shape are unchanged.

1. **Structured Data Extraction (check_structured_data.py + LLM Semantic Fallback)**:
   - Run `scripts/check_structured_data.py` to extract JSON-LD, @graph arrays, and check attribute completeness across 9 major Schema types.
   - **Unparseable JSON-LD is reported, not dropped.** A block is retried with the recoveries a lenient consumer applies (HTML-unescaping, and raw control characters such as a literal newline inside a string); only a block that still fails lands in `parse_errors` (`block_index`, `error`, `snippet`). The orchestrator reports a page whose only JSON-LD is broken as **"Present but Unparseable"** (high) — the fix is to correct the syntax, not to add schema — and a broken block beside valid ones as a medium finding, instead of the previous behavior of calling the first case "Missing" and ignoring the second.
   - **Entity grounding (`entity_grounding`).** Valid markup can still answer neither question an answer
     engine asks — *who publishes this page* and *what is it about*. Each parsed entity is sorted into
     identity (`Organization` and subtypes, `Brand`, `Person`, `WebSite`), subject (`Product`, `Article`,
     `Service`, `Event`, …), scaffolding/value objects (`BreadcrumbList`, `ListItem`, `WebPage`,
     `PostalAddress`, `AggregateRating`, …) or `unclassified`. Two orchestrator findings follow: a page whose
     entities are **all** scaffolding (`structural_only`) describes only its own breadcrumb trail, and a
     **homepage** (`is_site_root`, including a locale prefix such as `/en-us/`) with markup but no identity
     entity has nothing for `sameAs`, logo or contact facts to attach to. `structural_only` is asserted only
     when every type is a *classified* scaffolding type, so an unrecognised Schema type never produces either
     finding.
   - **Description coverage (`description_coverage`).** A `description` is the sentence an assistant quotes
     when asked about you. Entities for which a description is meaningful are counted, and those with none —
     or with fewer than `min_useful_chars` (25) characters, a label rather than a summary — are reported with
     the offending text. This is a presence/length test only: the audit never judges wording or scans for
     marketing buzzwords.
   - **Interior pages (optional).** Pass any additional page you already parsed to the orchestrator as
     `readability.additional_pages: [{url, structured_data}]`. It costs no extra request (that HTML was
     fetched by the render or engagement pass) and it is where the grounding gap usually lives: the homepage
     carries the `Organization` block while product and article pages ship nothing but a breadcrumb trail.
   - **FAQ schema vs. visible text (`faq_visible_text_check`).** FAQPage schema is only trustworthy when its
     answers correspond to something a visitor — and therefore a non-JS crawler — can actually see. Each
     answer's meaningful vocabulary (stopwords and short words stripped) is checked for **word overlap**
     against the page's own visible text, not exact substring matching, so a legitimately reworded answer is
     never mistaken for absence — only a near-total vocabulary mismatch (`< 25%` overlap) is reported, and
     only when the answer itself carries enough signal to judge (`>= 4` significant words) and the page
     actually returned enough visible text to compare against (`>= 20` significant words; otherwise
     `checked: false`, never a false "answer absent" claim caused by a blocked or empty fetch).
   - **Authorship / E-E-A-T (`article_completeness.author_names`, `.generic_placeholder_author`).** A real
     named byline is repeatedly the single most-cited concrete AI-trust signal in published GEO/AEO guidance.
     Flags only a narrow, high-confidence CMS-default placeholder list (`admin`, `webmaster`, `unknown`,
     `guest`, …) — a legitimate organizational byline like `"Staff Writer"` or `"Editorial Team"` is
     deliberately never flagged, since real publications use those on purpose. Requires **every** listed
     author to be a placeholder before flagging (one real name among co-authors clears it).
   - **NAP consistency (`nap_consistency`).** Does the `LocalBusiness`/`Organization` schema's telephone and
     address actually match the page's own visible text — the on-site instance of "agreement across the web
     matters." Phone numbers are compared as individual digit-token candidates extracted from visible text
     (never the whole page glued into one digit blob, which would let an unrelated number — a zip code, a
     street number — corrupt the match), tolerant of formatting and a missing country-code prefix. Addresses
     reuse the FAQ check's word-overlap approach. `checked: false` when there's too little visible text to
     compare against, or no telephone/address to compare in the first place.
   - **LLM Semantic Fallback:** If `check_structured_data.py` returns `microdata_detected: true` or `rdfa_detected: true`, the LLM uses its HTML inspection tools to extract the inline structured data. If it reports `parse_errors`, the LLM inspects the malformed JSON-LD string to recover broken entities manually. If 0 schema blocks are found, the LLM checks `<meta property="og:...">` tags.

2. **Semantic HTML Structure Check (check_semantic_structure.py + LLM Orientation Evaluation)**:
   - Run `scripts/check_semantic_structure.py` to measure <title>, <meta name="description">, heading sequences (h1-h6), and semantic tag counts (main, article, nav, section).
   - **Question-phrased headings (`question_headings`).** A heading ending in `?` (or Arabic `؟`) or opening
     with a common interrogative word (`How`, `What`, `Why`, …, matched as a whole word so `"Isaac Newton's
     Legacy"` never matches `"Is"`) sets up a direct-answer expectation immediately below it — the single
     most reliably-cited AEO pattern in published research. This checks **presence, not quality**: any real
     text at all before the next heading counts as answered (a one-word FAQ answer like `"No."` is a
     complete, valid answer), so only a question heading with genuinely nothing following it is reported.
     Nav/header/footer/aside text never counts as an answer.
   - **Content front-loading (`content_positioning`).** Where, as a fraction of the page's main-content word
     count (chrome excluded), the first substantial (`>= 12`-word) block of text appears — informed by
     published findings that a large share of AI citations come from early in a document. Reports
     `checked: false` rather than a guessed verdict whenever there isn't enough signal: under 80 words of
     main content total, or no single block ever reaching the substantial-length floor (a page built from
     many short list items is a legitimate style, not a defect).
   - **LLM Semantic Fallback:** The LLM reviews skipped heading levels and <h1> counts to determine if the heading texts logically organize the page or if <div>-written facts could be hidden from naive parsers.

3. **Content Consistency Check (check_content_consistency.py extracts; agent judges)**:
   - Run `scripts/check_content_consistency.py` to **extract** the list of scalar facts across any Schema entity (`Product`, `Article`, `Organization`, `Event`, `Recipe`, …). Its string/number match against visible text is a **first-pass heuristic only** — it misfires on formatting variance (`$1,299` vs `1,299 USD` vs "just under thirteen hundred"), synonyms (`in stock` vs `ships today`), unit conversions, date formats, and any non-English text.
   - **Agent judgment (authoritative):** for each extracted `{fact, structured_value}` pair, judge whether the visible text corroborates it — batched, one call, working from the fact list plus the relevant visible-text snippet, not the whole page. `overall_consistency_ratio` is the deterministic floor when no agent judgment is supplied.

4. **Non-Text Fact Inspection (check_nontext_facts.py + LLM Context Inspection)**:
   - Run `scripts/check_nontext_facts.py` to categorize image ALT attributes into 4 W3C classes (missing, decorative `alt=""`, generic, descriptive) and inspect up to 3 .pdf links for a digital text layer.
> **robots.txt:** each linked PDF this script downloads is gated by `crawl-access-audit/scripts/robots_gate.py`. Pass `check_robots.py`'s output as `robots` in the script's JSON input so the gate reuses the robots.txt already fetched (zero extra requests); without it the gate fetches `/robots.txt` once itself rather than proceeding ungated. A refused request comes back marked `skipped_by_robots` with the deciding rule — treat it as *not measured*, never as a fault found in the site.

     - **Empty (`alt=""`) or missing alt is a defect ONLY when it leaves a link/button with no
       accessible name at all** — `unlabeled_interactive_images` flags an `<a href>`/`<button>` whose
       ONLY content is such an image, with no other text, `aria-label`, or `title` on the element and no
       other labeling image alongside it. This is deliberately much narrower than every `alt=""` image:
       most empty alts are correctly decorative (a spacer, a background flourish, an icon beside real
       link text) — that is the W3C-recommended thing to do, and flagging all of them would manufacture
       findings against sites doing the right thing. This check only fires on the unambiguous case: the
       control has genuinely nothing a screen reader or a non-visual AI crawler could read to know what
       it does.
     - **Generic ALT / filename detection is pattern-based, not a fixed word list.** An ALT is downgraded to `generic` when it is a generic term, a generic term + number (`image`, `photo 2`, `banner-3`), a camera/CMS stem typed into the alt (`IMG_2041`, `DSC00192.jpg`), or a copy of the file name that is itself machine-formatted (`team_photo_02`, `hero-banner-final.webp`). A short human label that happens to equal the file name (`alt="Canva"` on `canva.png`, typical of logo walls) stays `descriptive`, and a short alt is never penalised just because the file name is a hash — the alt is what the crawler reads. `autogenerated_filename_count` separately flags `src` stems like `IMG_2043`, `DSC00192`, timestamps, hex hashes, UUIDs, `screenshot-2`, `unnamed`.
     - **PDF text-layer detection inflates compressed streams.** It reads up to 1 MB (hard ceiling 10 MB), then decides in order: tagged-PDF structure → `/ToUnicode` CMap → uncompressed `BT … Tj/TJ` operators → **FlateDecode (zlib) content streams inflated and scanned for the same operators** → `/Subtype /Image` XObject with no text found ⇒ `has_text_layer: false` → truncated & inconclusive ⇒ `has_text_layer: null` (never a false negative). The chosen path is reported in `method`.
     - **Bounded by wall clock, not just by request timeout** (`PDF_INSPECTION_DEADLINE_S`, 25 s across all PDFs on a page; each body is read in chunks against the same budget). A per-request `timeout` cannot bound this on its own: the socket timeout resets every time a byte arrives, so a host trickling a 1 MB PDF a few bytes at a time never trips it and would hang the audit past the <5 min runtime constraint. A PDF cut short by the budget is reported `truncated: true` with `has_text_layer: null` and `read_deadline_exceeded`/`deadline_exceeded` — **not measured**, never "this PDF has no text layer".
   - **LLM Semantic Fallback:** If a .pdf file is reported as `has_text_layer: false` or `null`, or has a fetch error, the LLM uses basic web-reading tools to inspect if facts are mirrored on alternative HTML pages.

## Output
Combines objective script outputs with LLM semantic fallbacks into a structured evidence JSON object:

Container names below are the contract `audit-orchestrator/scripts/synthesize_report.py`
consumes. (The legacy aliases `context_consistency` / `nontext_content` are still
accepted by the orchestrator, but new output should use these names.)

```json
{
  "structured_data": { ... },
  "semantic_structure": { ... },
  "content_consistency": { ... },
  "nontext_facts": { ... },
  "llm_semantic_fallbacks": {
    "microdata_or_rdfa_found": false,
    "contextual_price_notes": "...",
    "contextual_availability_notes": "..."
  }
}
```

## Basic LLM Tools Used During Fallback
When a fallback is triggered, the LLM uses standard/basic agent tools only:
1. **Raw HTML Text Inspection (`view_file` / string search)**: Searches raw HTML string for Microdata (`itemprop`), RDFa, or OpenGraph meta tags when JSON-LD script returns 0 blocks.
2. **Basic Web Reading (`read_url_content`)**: Reads public URL/documentation content if a PDF link fetch fails or lacks a text layer (`pdf_has_text_layer: false`).
3. **Semantic String Matching (LLM Native Reasoning)**: Evaluates non-English stock terms, foreign currencies, or heading hierarchy organization directly in text without custom API scripts.

## Guardrails & Constraints
- Read-Only: Never modifies any website.
- No Crawling: Analyzes already-fetched HTML passed via stdin (except for maximum 3 .pdf links).
- Bounded Runtime: All scripts execute in milliseconds; LLM fallbacks are triggered only when script regex/parsing returns incomplete or anomalous results.
- No OCR: Does not perform OCR on images or PDFs.
- Evidence Only: Provides structured facts and semantic observations; leaves severity assignment, root-cause diagnosis, and recommendations to the audit-orchestrator.
