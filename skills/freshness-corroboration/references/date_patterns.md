# Date Patterns & Temporal Heuristics Reference

This reference documents the regex patterns, heuristics, and known limitations used across `freshness-corroboration` scripts to identify temporal anchors, copyright years, and date signals in search snippets.

> [!IMPORTANT]
> **English-Centric Starting Heuristic Notice**:
> The explicit temporal anchor patterns (e.g., "as of", "updated in", "published on", English month names) and snippet extraction patterns are starting heuristics optimized for English-language web content. In production multi-lingual deployments, these pattern arrays should be expanded with localized phrases for target geographic markets (e.g. "mis à jour le", "aktualisiert am", "stand").

## 1. Explicit Temporal Anchor Phrases
Used by `scripts/check_content_dates.py` to identify explicit text declarations of currency across the full document:

- `as of (?:20\d{2}|19\d{2})`
- `updated (?:in|on|as of)?\s*(?:20\d{2}|19\d{2}|[a-zA-Z]+\s+20\d{2})`
- `current as of`
- `last updated (?:on|in)?`
- `published (?:on|in)?`

## 2. Copyright Footer & Range Patterns
Used by `scripts/check_content_dates.py` to extract copyright years across single years ("© 2026") and multi-year ranges ("© 2019-2026", "© 2018, 2022, 2026"):

- Block Pattern: `(?:copyright|©|\bcopr\b|\&copy\;)\s*([\s\S]{1,120}?)(?=\.|\;|$|<|\n)`
- Year Range Extraction: Matches all 4-digit years (`20\d{2}|19\d{2}`) inside the copyright block and evaluates `max(years)`.

## 3. Search Snippet Fact & Year Extraction Patterns
Used by `scripts/check_citation_consistency.py` to extract candidate years or numbers from search result titles and snippets:

- **Founding Year**: `\b(?:founded|established|started|launched|created)\s+(?:in\s+)?(20\d{2}|19\d{2})\b`
- **Headquarters Location**: `\b(?:headquartered|headquarters|based|located|hq)\s+in\s+([A-Za-z\s,\.]+?)(?=\.|\;|\,|$|\s+and)`
- **General Year Extraction**: `\b(20\d{2}|19\d{2})\b`

> [!NOTE]
> **Known Limitation — Headquarters/Location Contradiction Detection**:
> `check_citation_consistency.py`'s contradiction check uses substring comparison between the on-site value and each external extracted value (after normalizing case and punctuation). This works reliably for `founding_year` (exact 4-digit comparison) but is unreliable for `headquarters`/location facts, since place names have valid aliases and parent-region references that don't share a substring relationship (e.g. on-site "San Francisco" vs. an external snippet saying "Bay Area" would be flagged as a contradiction even though they may refer to the same place; conversely "Delhi" vs. "New Delhi" would NOT be flagged as a contradiction purely because one is a substring of the other, regardless of whether that's the intended interpretation). This is a limitation of string-based comparison without a location-normalization dataset, not a bug — treat `contains_contradiction: true` for `headquarters`-type facts as a lower-confidence signal than the same flag on `founding_year` facts, and expect occasional false positives/negatives on location comparisons specifically.

## 4. Blog Listing Heuristics & Known Limitations
Used by `scripts/check_temporal_decay.py` to analyze blog/news listing recency:

- **High Confidence Path**: Prefers structured `<time datetime="...">` tags present in HTML markup.
- **Low Confidence Heuristic Path**: Falls back to pattern matching and boilerplate phrase filtering (`BOILERPLATE_PATTERNS`, `in_footer` tracking) to exclude copyright lines and taglines.
- **Known Limitation**: Incidental year mentions in sidebars, testimonials (e.g. "Customer since 2020"), or category widgets ("Popular in 2025") that lack structured `<time>` tags may still be included in loose post counts. The script explicitly flags `detection_confidence: "low"` in these cases so the orchestrator weights post count statistics appropriately.
