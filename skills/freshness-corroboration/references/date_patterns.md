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
- **Scanned on visible text only** — `<script>`, `<style>`, and HTML-comment bodies are stripped first, so a bundled library's `/* … Copyright 2015 … */` banner or an inline `var year = 2019` cannot supply a false copyright year.
- Year Range Extraction: Matches all 4-digit years (`20\d{2}|19\d{2}`) inside the copyright block; `copyright_years_all` reports every year, `copyright_year` is the max.

## 2b. JSON-LD Date Age & Sanity
Also in `scripts/check_content_dates.py`: `datePublished` / `dateModified` are parsed to real dates and aged against now (`date_modified_age_days`, `effective_content_age_days`). `content_date_issues` flags `dateModified` earlier than `datePublished`, future dates, and unparseable values. This is the highest-value freshness signal and feeds the "Structured Content Date (dateModified) Is Stale" finding.

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

- **High Confidence Path**: structured `<time datetime="YYYY-MM-DD">` tags. Relative `<time>` bodies ("2 days ago", "yesterday") are recognised via `RELATIVE_RECENT_RX` and treated as a very recent post (`has_relative_recent_timestamps: true`, `days_since_last_post: 0`) instead of being silently dropped.
- **Footer scoping**: a page-level `<footer>` is boilerplate and suppressed, but a per-post `<article><footer class="post-meta">` is **not** — depth counters track `<article>` vs `<footer>` so post-card dates are no longer lost.
- **Ranking**: full `year+month+day` dates outrank year-only matches; implausible future years (`> current_year + 1`) are dropped, so "Roadmap 2027" can't become the newest post.
- **Year-only precision**: when only a year is recoverable (e.g. a non-English month name the English `MONTH_MAP` cannot parse), the date is resolved to **31 December of that year, capped at today** -- never 1 January. Inventing Jan 1 overstates age by up to 11 months and can flip the 365-day decay verdict; assuming the latest possible date makes `days_since_last_post` a *lower bound*, so `is_decayed` can never be a false positive. `date_precision` reports `day` / `year_only` / `relative_recent`.
- **Output**: emits `days_since_last_post`, `is_decayed` (`> 365` days), `most_recent_post_date_iso`, `date_precision`, `text_date_snippets` — the fields the orchestrator's decay finding and the agent's low-confidence judgement both consume.
- **Known Limitation**: incidental year mentions in sidebars / testimonials that lack any `<time>` tag can still appear in `text_date_snippets`; `detection_confidence: "low"` flags this, and the agent judges the snippets rather than trusting the loose max.
