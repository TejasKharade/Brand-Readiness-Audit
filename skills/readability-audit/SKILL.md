---
name: readability-audit
description: Analyzes already-fetched HTML content to gather objective, structured evidence regarding machine extractability - structured data (JSON-LD), semantic HTML structure, visible vs. structured content consistency, and non-text fact lockout. Combines standalone Python parsing scripts with Orchestrator-LLM semantic evaluation for unconventional edge cases.
license: MIT
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
- html: Raw HTML content string of the target page (string).
- url: Absolute URL of the target page (string).

## Procedure & Hybrid Execution Flow

1. **Structured Data Extraction (check_structured_data.py + LLM Semantic Fallback)**:
   - Run `scripts/check_structured_data.py` to extract JSON-LD, @graph arrays, and check attribute completeness across 9 major Schema types.
   - **LLM Semantic Fallback:** If `check_structured_data.py` returns `microdata_detected: true` or `rdfa_detected: true`, the LLM uses its HTML inspection tools to extract the inline structured data. If it reports `parse_errors`, the LLM inspects the malformed JSON-LD string to recover broken entities manually. If 0 schema blocks are found, the LLM checks `<meta property="og:...">` tags.

2. **Semantic HTML Structure Check (check_semantic_structure.py + LLM Orientation Evaluation)**:
   - Run `scripts/check_semantic_structure.py` to measure <title>, <meta name="description">, heading sequences (h1-h6), and semantic tag counts (main, article, nav, section).
   - **LLM Semantic Fallback:** The LLM reviews skipped heading levels and <h1> counts to determine if the heading texts logically organize the page or if <div>-written facts could be hidden from naive parsers.

3. **Content Consistency Check (check_content_consistency.py + LLM Contextual Matching)**:
   - Run `scripts/check_content_consistency.py` to extract all scalar facts across any Schema entity (`Product`, `Article`, `Organization`, `Event`, `Recipe`, etc.) and verify their presence in human-visible text.
   - **LLM Semantic Fallback:** If `check_content_consistency.py` reports low `overall_consistency_ratio` or unverified facts due to non-English terms, non-standard layouts, or foreign currencies, the LLM inspects visible text directly to verify fact consistency.

4. **Non-Text Fact Inspection (check_nontext_facts.py + LLM Context Inspection)**:
   - Run `scripts/check_nontext_facts.py` to categorize image ALT attributes into 4 W3C classes (missing, decorative `alt=""`, generic, descriptive) and inspect up to 3 .pdf links for a digital text layer with 10MB streaming size protection.
   - **LLM Semantic Fallback:** If a .pdf file is reported as `pdf_has_text_layer: false` or has a fetch error, the LLM uses basic web-reading tools to inspect if facts are mirrored on alternative HTML pages.

## Output
Combines objective script outputs with LLM semantic fallbacks into a structured evidence JSON object:

```json
{
  "structured_data": { ... },
  "semantic_structure": { ... },
  "context_consistency": { ... },
  "nontext_content": { ... },
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
