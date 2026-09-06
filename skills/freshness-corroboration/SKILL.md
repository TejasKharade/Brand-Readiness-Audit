---
name: freshness-corroboration
description: Audits content freshness, publication/modification dates, entity disambiguation (sameAs), off-site brand citation consistency, and temporal decay across web pages.
license: MIT
---

# Freshness & Corroboration Audit Skill

## When to use
Use when auditing publication/modification timestamps, entity disambiguation links (`sameAs`), cross-site brand claim consistency, and temporal freshness to ensure AI crawlers and RAG systems possess accurate, up-to-date brand information.

## Inputs
- `html`: Page HTML string.
- `url`: Page URL string.
- `onsite_facts` (optional): Dictionary of key brand facts found on site (e.g. `{"founding_year": "2015", "headquarters": "San Jose, CA"}`).
- `offsite_claims` (optional): List of external benchmark claims to corroborate.
- `same_as_urls` (optional): List of `sameAs` entity URLs from JSON-LD schema.

## Procedure & Script Execution Flow

1. **Content Dates Analysis (`scripts/check_content_dates.py`)**
   ```bash
   echo '{"html": "...", "url": "https://example.com"}' | python skills/freshness-corroboration/scripts/check_content_dates.py
   ```
   - Parses `<meta>` tags (`article:published_time`, `article:modified_time`, `og:updated_time`, `datePublished`, `dateModified`) and Schema JSON-LD dates.
   - Calculates age in days and flags stale (>1yr) or outdated (>2yr) content.

2. **Citation & Entity Disambiguation (`scripts/check_citation_consistency.py`)**
   ```bash
   echo '{"same_as_urls": ["https://en.wikipedia.org/wiki/Brand"], "onsite_facts": {"hq": "San Jose"}, "offsite_claims": [{"fact_key": "hq", "expected_value": "San Jose"}]}' | python skills/freshness-corroboration/scripts/check_citation_consistency.py
   ```
   - Evaluates `sameAs` links against authoritative entity databases (Wikipedia, Wikidata, Crunchbase, official social platforms).
   - Cross-checks on-site brand claims against external benchmark references to detect RAG hallucination risks.

3. **Temporal Decay Detection (`scripts/check_temporal_decay.py`)**
   ```bash
   echo '{"html": "..."}' | python skills/freshness-corroboration/scripts/check_temporal_decay.py
   ```
   - Scans HTML for outdated copyright footers, stale future event announcements (e.g. "launching in 2021"), and deprecated tech/brand markers.

## Output Schema
Emits a combined JSON object containing content date metrics, entity disambiguation status, fact corroboration results, and temporal health status.
