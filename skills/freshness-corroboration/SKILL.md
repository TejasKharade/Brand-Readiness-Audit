---
name: freshness-corroboration
description: Checks whether a site's content is current (structured date
  metadata, explicit temporal anchors, copyright year, blog/news
  recency) and whether facts stated on the site are corroborated by
  independent external sources, with basic entity-disambiguation checks
  (sameAs schema, Wikipedia/Wikidata presence). Uses web search, so
  findings are lower-confidence and less reproducible than the
  marketplace's other, fully-deterministic skills. Produces structured
  facts only; does not diagnose root causes or assign severity. Use as a
  data-gathering stage of an AI-discoverability audit, feeding a
  diagnosis/orchestrator skill.
license: MIT
---

# Freshness & Corroboration Audit Skill

## When to use
Use as the data-gathering stage for content recency, off-site fact corroboration, and entity disambiguation.

> [!IMPORTANT]
> **Lower-Confidence & Reproducibility Notice**: This is the **only skill** in the marketplace requiring web search. Because web search engine outputs vary over time and across queries, findings from this skill must be weighted as lower-confidence and less reproducible than fully deterministic skills (`crawl-access-audit`, `readability-audit`). Reporting "no corroboration found in N searches" is evidence of brand fragility, NOT proof of total absence.

## Inputs
- `brand_name`: Target brand or organization name.
- `domain`: Target site domain (e.g. `example.com`).
- `html`: Already-fetched HTML content for the target page (homepage, About page, or blog/news listing).
- `facts_to_verify` (optional): List of key brand facts found on site (e.g., founding year, headquarters location) to corroborate via web search.

## Procedure & Script Execution Flow

1. **On-Site Content Dates Analysis (`scripts/check_content_dates.py`)** — *No Search*
   ```bash
   echo '{"html": "...", "url": "https://example.com"}' | python skills/freshness-corroboration/scripts/check_content_dates.py
   ```
   - Extracts `dateModified` and `datePublished` from JSON-LD blocks.
   - Searches visible text for explicit temporal anchors loaded from `references/date_patterns.json`.
   - Extracts copyright footer year and computes `copyright_year_age_years` as a raw number.

2. **Temporal Decay / Listing Recency (`scripts/check_temporal_decay.py`)** — *No Search*
   ```bash
   echo '{"url": "https://example.com/blog", "html": "..."}' | python skills/freshness-corroboration/scripts/check_temporal_decay.py
   ```
   - Best-effort heuristic parsing of article/blog listing pages for visible dates.
   - Reports `most_recent_post_date_found`, `post_count_found`, and `detection_confidence` (`high` for `<time datetime="...">` tags, `low` for loose text pattern matching).
   - *Known Limitation*: Loose text date matching applies boilerplate filtering (footers/copyrights), but incidental non-boilerplate year mentions (e.g. sidebars or testimonials) remain a known trade-off, which is why results without structured `<time>` tags are explicitly flagged with `detection_confidence: "low"`.

3. **Citation & Fact Corroboration (`scripts/check_citation_consistency.py`)** — *Uses Web Search*
   - Execute up to **3 web searches** combining the brand name with the fact being checked using the following query patterns:
     - For `founding_year`: `"[Brand Name] founded year"`
     - For `headquarters`: `"[Brand Name] headquarters address"`
     - For `custom`: `"[Brand Name] [custom_fact_label]"`
   - Pass search result titles and snippets into `scripts/check_citation_consistency.py`:
   ```bash
   echo '{"brand_name": "Acme", "fact_type": "founding_year", "fact_value_on_site": "2018", "search_results": [{"url": "https://en.wikipedia.org/wiki/Acme", "title": "Acme - Wikipedia", "snippet": "Acme was founded in 2018..."}]}' | python skills/freshness-corroboration/scripts/check_citation_consistency.py
   ```
   - Parses search result titles/snippets only (does NOT scrape full pages).
   - Reports `external_mentions_found` (capped at 5), `corroboration_count` (distinct domains), and `contains_contradiction: bool`.

4. **Entity Disambiguation (`scripts/check_entity_disambiguation.py`)** — *Uses Web Search*
   - Check the given homepage/About page HTML for `sameAs` links in `Organization` JSON-LD blocks (`has_wikidata_or_wikipedia_sameas`).
   - Execute **3 web searches** using these exact query patterns:
     - Query 1 (Bare Brand Name): `"[Brand Name]"` (checks if `domain` appears in top results).
     - Query 2 (Wikipedia Search): `"[Brand Name] wikipedia"` (checks if `wikipedia_page_found` is true).
     - Query 3 (Wikidata Search): `"[Brand Name] wikidata"` (checks if `wikidata_entry_found` is true).
   - Pass search result domains into `scripts/check_entity_disambiguation.py`:
   ```bash
   echo '{"brand_name": "Acme", "domain": "acme.com", "html": "...", "bare_name_results": [...], "wikipedia_results": [...], "wikidata_results": [...]}' | python skills/freshness-corroboration/scripts/check_entity_disambiguation.py
   ```

## Shared Search Budget Rules
- Search ceiling: Maximum 3 searches for `check_citation_consistency.py` per fact, 3 searches for `check_entity_disambiguation.py`.
- Shared skill ceiling: Maximum **6 searches per site audited**. See `references/search_budget.md` for orchestrator budgeting rules.

## Output Schema
```json
{
  "content_dates": {
    "date_published": "2025-01-15T08:00:00Z",
    "date_modified": "2025-06-20T10:00:00Z",
    "explicit_temporal_anchors_found": ["as of 2025"],
    "copyright_year": 2025,
    "copyright_year_age_years": 1
  },
  "temporal_decay": {
    "most_recent_post_date_found": "2025-06-01",
    "post_count_found": 5,
    "detection_confidence": "high"
  },
  "citation_consistency": {
    "external_mentions_found": [],
    "corroboration_count": 0,
    "contains_contradiction": false,
    "search_error": null
  },
  "entity_disambiguation": {
    "same_as_links": ["https://en.wikipedia.org/wiki/Acme"],
    "has_wikidata_or_wikipedia_sameas": true,
    "bare_name_search": {
      "search_result_domains": ["acme.com", "wikipedia.org"],
      "target_domain_in_top_results": true
    },
    "wikipedia_page_found": true,
    "wikidata_entry_found": true
  }
}
```

## Guardrails & Constraints
- **Allowed Tools**: `web_search`, `code_execution` (HTTP client is NOT required by this skill's scripts as it operates on pre-fetched HTML).
- **Read-only**: Never modifies external sites; does not perform form submission or automated account interactions.
- **Snippet-Only Extraction**: Web search scripts parse titles/snippets only; they never fetch or scrape full external web pages from search results.
- **Discrepancy Reporting**: Does not adjudicate which of two conflicting facts is correct; reports discrepancies objectively for downstream orchestrator evaluation.
- **Phase A / Phase B Split**: Emits raw facts only; severity scores and root cause diagnoses belong strictly to the orchestrator.
