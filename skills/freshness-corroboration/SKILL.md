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
compatibility: Requires Python 3 and outbound network access for web search
allowed-tools: Bash Read WebSearch
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
- `status` (optional but strongly recommended): The HTTP status code of the fetch that produced `html` —
  reuse it from wherever `html` came from (e.g. `crawl-access-audit`'s `browser_fetch.status` for the
  homepage). Without it, `check_content_dates.py`/`check_temporal_decay.py` cannot tell a real page from a
  404/410/5xx error page that happens to carry a date-like string (a stale copyright year in a shared error
  template), and will report a fabricated staleness finding instead of the real defect: the page not
  loading. Always pass it when auditing anything other than a page you've already confirmed is a live 2xx.
- `facts_to_verify` (optional): List of key brand facts found on site (e.g., founding year, headquarters location) to corroborate via web search.

## Procedure & Script Execution Flow

> [!IMPORTANT]
> **Prefer `scripts/run_content_dates_and_decay.py` over calling steps 1 and 2
> below separately.** Both are pure in-memory HTML parsing with no network
> I/O. It takes the same `{html, url, status}` input and returns both output
> keys (`content_dates`, `temporal_decay`) in one JSON object, by importing
> and calling these exact same functions. Steps 3-4 need this turn's own
> `WebSearch` results and stay separate calls, run after searching.

1. **On-Site Content Dates Analysis (`scripts/check_content_dates.py`)** — *No Search*
   ```bash
   echo '{"html": "...", "url": "https://example.com", "status": 200}' | python skills/freshness-corroboration/scripts/check_content_dates.py
   ```
   - **Pass `status` from the fetch that produced `html`.** A non-2xx status short-circuits to
     `{"checked": false, "fetch_status": ..., "skip_reason": ...}` with every date field `null` — the script
     never scans a 404/410/5xx error page's body for dates, since a shared error template's stale footer
     year would otherwise be misreported as this page's own content age. `checked` defaults true when
     `status` is omitted (older callers), so this is backward compatible, but always pass it when available.
   - Extracts `dateModified` / `datePublished` from JSON-LD, parses them, and computes `date_modified_age_days` / `effective_content_age_days` — the **strongest freshness signal**. Also emits `content_date_issues` (`dateModified` < `datePublished`, future dates, unparseable values).
   - Scans **visible text only** (script/style/HTML-comment bodies stripped) for temporal anchors and the copyright year, so bundled-library banners (`/* jQuery … Copyright 2015 */`) and inline JS vars can no longer supply a wrong year. `copyright_years_all` lists every year seen; `copyright_year` is the max.

2. **Temporal Decay / Listing Recency (`scripts/check_temporal_decay.py`)** — *No Search*
   ```bash
   echo '{"url": "https://example.com/blog", "html": "...", "status": 200}' | python skills/freshness-corroboration/scripts/check_temporal_decay.py
   ```
   - **Pass `status`** the same way as `check_content_dates.py` above, and for the same reason: without it, a
     blog/listing URL that actually 404s gets scanned like real content, and any date-like text in the error
     page's body (often the site's shared chrome) is reported as "the most recent post" — a fabricated
     staleness claim standing in for the real defect, which is that the page doesn't load at all. A non-2xx
     `status` short-circuits to `{"checked": false, "fetch_status": ..., "skip_reason": ...}` instead.
   - Best-effort heuristic parsing of article/blog listing pages for visible dates.
   - Reports `most_recent_post_date_found`, `post_count_found`, and `detection_confidence` (`high` for `<time datetime="...">` tags, `low` for loose text pattern matching).
   - *Known Limitation*: Loose text date matching applies boilerplate filtering (footers/copyrights), but incidental non-boilerplate year mentions (e.g. sidebars or testimonials) remain a known trade-off, which is why results without structured `<time>` tags are explicitly flagged with `detection_confidence: "low"`.
   - `<script>`/`<style>`/`<noscript>`/HTML-comment bodies are stripped before any date scanning (shares `check_content_dates.py`'s `strip_non_visible()`) — otherwise a numeric literal in inline JS (a `setTimeout(fn, 2000)` delay, a `z-index: 2015`) reads as a plausible year on any page carrying one, which is nearly every real page.
   - **Agent judgment when `detection_confidence: "low"`:** the `<time datetime>` path is authoritative and universal — trust it. When it is absent, do **not** trust the loose parse; instead the agent picks the newest *article publish* date from the returned `text_date_snippets` (distinguishing it from copyright years, "since 2009", prices, and testimonial dates). The month-name table is English-only, so non-English listing pages always need this judgment.

3. **Citation & Fact Corroboration (`scripts/check_citation_consistency.py`)** — *Uses Web Search (only for facts the site states; see priority ladder below)*
   - For each fact **that actually appears on the page**, run one search using these patterns:
     - For `founding_year`: `"[Brand Name] founded year"`
     - For `headquarters`: `"[Brand Name] headquarters address"`
     - For `description` (recommended — corroborate *what the brand does*): `"[Brand Name] company"` / `"what is [Brand Name]"`. Pass `fact_type: "description"` with the on-site one-liner (meta description / `Organization.description` / hero sub-head) as `fact_value_on_site`. The script bundles every snippet and sets `needs_agent_judgment: true`; the **agent** flags a finding only if the external framing materially disagrees (different industry / audience / product), not for wording.
     - For `custom`: `"[Brand Name] [custom_fact_label]"`
   - Pass search result titles and snippets into `scripts/check_citation_consistency.py`:
   ```bash
   echo '{"brand_name": "Acme", "fact_type": "founding_year", "fact_value_on_site": "2018", "search_results": [{"url": "https://en.wikipedia.org/wiki/Acme", "title": "Acme - Wikipedia", "snippet": "Acme was founded in 2018..."}]}' | python skills/freshness-corroboration/scripts/check_citation_consistency.py
   ```
   - Parses search result titles/snippets only (does NOT scrape full pages).
   - `contains_contradiction: true` is asserted **only for `founding_year`, and only on a labelled pattern match** ("founded in 2015", "established in the year 2022"). A bare year found anywhere in a snippet ("raised $50M in 2023") goes into `weak_year_mentions` and never triggers a contradiction. `corroboration_count` / `corroborating_domains` count only sources that *agree*; disagreeing ones are in `conflicting_domains`. The labelled pattern is deliberately narrow (year immediately follows the founding verb, with only a short "in"/"in the year (of)" qualifier) rather than a loose gap-matcher — that precision is what keeps a "weak" mention from ever driving a false contradiction, so don't widen it further without the same care.
   - For `headquarters` and `custom` facts the script sets `needs_agent_judgment: true` and returns the snippets — place-name aliases (San Francisco vs. Bay Area) and free-form values cannot be adjudicated by string comparison, so the **agent** compares `fact_value_on_site` against `external_mentions_found` and raises a finding only on a real conflict.

4. **Entity Disambiguation (`scripts/check_entity_disambiguation.py`)** — *Uses Web Search (see priority ladder below — typically 1–2 searches, not 3)*
   - Harvests `sameAs` from **any entity node** in the JSON-LD graph — `Organization` and every subtype, every `LocalBusiness` subtype (`Dentist`, `LawFirm`, `ProfessionalService`, …), `Person` (personal brands), `NGO`, `WebSite`. The old `@type` whitelist silently dropped `sameAs` for most real business types.
   - **Presence means a brand-matching page, not any wikipedia.org URL.** A search for `"monday.com wikipedia"` returns *Monday (disambiguation)* and the weekday article before *Monday.com*. Every on-host result is scored: disambiguation and namespace pages (`Category:`, `Talk:`) score 0; the site's domain in the title/slug scores 3; a title equal to the brand name (qualifiers like "(software)" stripped) scores 2; a title containing every brand token scores 1. `wikipedia_page_found` / `wikidata_entry_found` are `true` only for a score > 0, `false` when no result was on the host at all, and `null` when results exist but none match (`presence_source: "results_found_but_none_match_brand"`) or when no search results were supplied at all (`presence_source: "not_searched"` — WebSearch was not run, so absence is unknown) — the orchestrator never raises "no Wikipedia" on `null`. `wikipedia_any_result` / `wikidata_any_result` keep the raw indicator.
   - `wikipedia_presence_source` / `wikidata_presence_source` report whether presence was confirmed from the bare-name results (free), needed a dedicated query, or is undetermined.
   - `domain_provided: false` means no domain was supplied → `target_domain_in_top_results` is `null` (check could not run), and the orchestrator must **not** raise "domain missing from search results".
   - **Name ambiguity (`name_ambiguity`)** — deterministic mistaken-identity signals from the bare-name results: `target_domain_rank`, `distinct_registrable_domains`, `identity_platform_coverage` (LinkedIn/Crunchbase/Wikipedia/…), `wikipedia_disambiguation_detected`, and a composite `ambiguity_risk` (`low` / `moderate` / `elevated`). `elevated` raises a finding. When `needs_agent_disambiguation_judgment: true`, the agent reads the actual result titles and confirms whether genuinely distinct same-named entities appear, writing back `name_ambiguity.agent_verdict = {"ambiguous": bool, "notes": "..."}` (preferred over the heuristic).
   - **Entity-match evidence (`entity_match_evidence`)** — `wikipedia_result` / `wikidata_result` is the best-scoring match (never a disambiguation page), and `wikipedia_candidates` / `wikidata_candidates` list every on-host result with `match_score` and `match_reason`. The score is a text match, not identity proof: the agent confirms the snippet describes *this* brand (industry / founding / location) rather than a same-named person or company. If a candidate scored 0 but clearly is the brand (article under its legal name), the agent may treat presence as confirmed.
   - Searches: **query 1 (`"[Brand Name]"`) always; query 2 (`"[Brand Name] wikipedia"`) only if query 1 did not surface a wikipedia.org page; query 3 (`"[Brand Name] wikidata"`) only if no Wikipedia page exists.** See the priority ladder in *Shared Search Budget Rules*. Pass `search_budget_remaining`; the script echoes a `search_budget` block.
   - Classifies each `sameAs` target in `authority_sameas`: links to **public identity registries** — a
     code or package registry (GitHub, GitLab, npm, PyPI, crates.io, pkg.go.dev, Docker Hub, …), an app store
     listing, a company register (OpenCorporates, Crunchbase) or a persistent-identifier authority (ORCID,
     ISNI, ROR, VIAF) — are registry-grade identity anchors of the same kind a Wikidata link provides.
     Self-published social profiles (LinkedIn, X, Facebook) are deliberately *not* counted as registries.
     Host matching is exact-or-subdomain, so `dropbox.com` never matches `x.com`. The orchestrator therefore
     suppresses its optional "no Wikipedia/Wikidata link" nudge for a brand that already links a registry
     record (most open-source projects and B2B suppliers will never meet encyclopedia notability), and when
     off-site search *did* find an entry the site does not link, it raises the concrete
     **"Existing Encyclopedic Entry Not Linked From Organization sameAs"** finding instead of the generic one.
   - Pass search result domains into `scripts/check_entity_disambiguation.py`:
   ```bash
   echo '{"brand_name": "Acme", "domain": "acme.com", "html": "...", "bare_name_results": [...], "wikipedia_results": [...], "wikidata_results": [...]}' | python skills/freshness-corroboration/scripts/check_entity_disambiguation.py
   ```

## Shared Search Budget Rules

**One ceiling: 6 web searches for a standard single-page audit** (hard cap 8). Spend them in priority order and stop when the budget is gone — a partial corroboration is fine and is reported as such.

| # | Query | Feeds | Spend it? |
|---|---|---|---|
| 1 | `"[Brand Name]"` (bare name) | `name_ambiguity`, `target_domain_rank`, **and** Wikipedia/Wikidata presence if those URLs appear in the results | **Always** — this is the anchor query |
| 2 | `"[Brand Name] wikipedia"` | `wikipedia_page_found` | **Only if** query 1's results did not already surface a brand-matching `wikipedia.org` page (`wikipedia_page_found` is not `true` after query 1) |
| 3 | `"[Brand Name] wikidata"` | `wikidata_entry_found` | **Only if** no brand-matching Wikipedia page was found (a brand with a Wikipedia article effectively always has a Wikidata item) |
| 4 | `"[Brand Name] founded year"` | `founding_year` corroboration | **Only if** the site actually states a founding year |
| 5 | `"[Brand Name] company"` / `"what is [Brand Name]"` | `description` corroboration (agent judges positioning agreement) | **Only if** budget remains and the site has a clear one-line description |
| 6 | `"[Brand Name] headquarters"` | `headquarters` corroboration (agent judges) | **Only if** budget remains and the site states a location |

**Rules:**
- **Never corroborate a fact the page does not state.** `check_citation_consistency.py` returns `skipped_reason` and spends nothing when `fact_value_on_site` is empty.
- Thread `search_budget_remaining` into `check_citation_consistency.py` and `check_entity_disambiguation.py`; each echoes a `search_budget` block with `remaining_after` and `over_budget`. If `over_budget` is true, stop.
- `name_ambiguity` and the `entity_match_evidence` snippets cost **0 additional searches** — they are derived from queries 1–3.
- See `references/search_budget.md` for the multi-page / multi-fact ceiling (absolute max 12 across a full audit run) and the snippet-only guardrail.

## Output Schema
```json
{
  "content_dates": {
    "checked": true,
    "fetch_status": 200,
    "date_published": "2025-01-15T08:00:00Z",
    "date_modified": "2025-06-20T10:00:00Z",
    "date_modified_age_days": 82,
    "effective_content_age_days": 82,
    "content_date_issues": [],
    "explicit_temporal_anchors_found": ["as of 2025"],
    "copyright_year": 2025,
    "copyright_years_all": [2019, 2025],
    "copyright_year_age_years": 1
  },
  "temporal_decay": {
    "checked": true,
    "fetch_status": 200,
    "most_recent_post_date_found": "June 1, 2025",
    "most_recent_post_date_iso": "2025-06-01",
    "days_since_last_post": 92,
    "is_decayed": false,
    "post_count_found": 5,
    "has_relative_recent_timestamps": false,
    "detection_confidence": "high"
  },
  "citation_consistency": {
    "external_mentions_found": [],
    "weak_year_mentions": [],
    "corroboration_count": 0,
    "corroborating_domains": [],
    "conflicting_domains": [],
    "contains_contradiction": false,
    "contradiction_confidence": null,
    "needs_agent_judgment": false,
    "search_error": null
  },
  "entity_disambiguation": {
    "domain_provided": true,
    "same_as_links": ["https://en.wikipedia.org/wiki/Acme"],
    "same_as_links_found": true,
    "same_as_on_organization_typed_node": true,
    "has_wikidata_or_wikipedia_sameas": true,
    "bare_name_search": {
      "search_result_domains": ["acme.com", "wikipedia.org"],
      "target_domain_in_top_results": true
    },
    "wikipedia_page_found": true,
    "wikidata_entry_found": true,
    "wikipedia_presence_source": "bare_name_results",
    "wikidata_presence_source": "not_found",
    "wikipedia_any_result": true,
    "wikidata_any_result": false,
    "search_budget": {"remaining_before": 6, "searches_consumed_estimate": 1, "remaining_after": 5, "over_budget": false},
    "name_ambiguity": {
      "target_domain_rank": 1,
      "distinct_registrable_domains": ["acme.com", "wikipedia.org", "linkedin.com"],
      "identity_platform_coverage": ["linkedin.com", "wikipedia.org"],
      "wikipedia_disambiguation_detected": false,
      "ambiguity_signals": [],
      "ambiguity_risk": "low",
      "needs_agent_disambiguation_judgment": false
    },
    "entity_match_evidence": {
      "wikipedia_result": {"url": "https://en.wikipedia.org/wiki/Acme", "title": "Acme - Wikipedia", "snippet": "...", "match_score": 2, "match_reason": "title equals the brand name"},
      "wikidata_result": null,
      "wikipedia_candidates": [
        {"url": "https://en.wikipedia.org/wiki/Acme_(disambiguation)", "title": "Acme (disambiguation) - Wikipedia", "snippet": "...", "match_score": 0, "match_reason": "disambiguation page"},
        {"url": "https://en.wikipedia.org/wiki/Acme", "title": "Acme - Wikipedia", "snippet": "...", "match_score": 2, "match_reason": "title equals the brand name"}
      ],
      "wikidata_candidates": [],
      "needs_entity_match_verification": true
    },
    "entity_match_caveat": "A same-name result may describe a different entity; confirm before trusting."
  }
}
```

## Guardrails & Constraints
- **Allowed Tools**: `Bash` (to run the bundled Python scripts), `Read`, and `WebSearch` (the only skill in the marketplace that needs it). The scripts operate on pre-fetched HTML and search-result snippets, so no separate HTTP-fetch tool is required.
- **No LLM Hallucinated Q-IDs**: Never guess or hallucinate Wikidata Q-numbers (e.g. `Q174085`) from internal LLM memory. Always execute `scripts/check_entity_disambiguation.py` to extract real, authoritative `sameAs` links from the target page's JSON-LD HTML or web search results.
- **Read-only**: Never modifies external sites; does not perform form submission or automated account interactions.
- **Snippet-Only Extraction**: Web search scripts parse titles/snippets only; they never fetch or scrape full external web pages from search results.
- **Discrepancy Reporting**: Does not adjudicate which of two conflicting facts is correct; reports discrepancies objectively for downstream orchestrator evaluation.
- **Phase A / Phase B Split**: Emits raw facts only; severity scores and root cause diagnoses belong strictly to the orchestrator.
