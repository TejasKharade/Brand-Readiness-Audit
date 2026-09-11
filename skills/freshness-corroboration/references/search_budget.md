# Search Budget & Non-Deterministic Execution Reference

Web search operations carry real per-call monetary, rate, and performance costs, and
search engine outputs are non-deterministic and vary over time. `freshness-corroboration`
is the only skill in the marketplace that uses search — spend it sparingly.

## The one ceiling

| Scope | Ceiling |
| :--- | :--- |
| Standard single-page audit | **6 web searches** |
| Hard cap for a single-page audit | **8** |
| Full audit run (multiple pages / many facts) | **12 absolute** — the orchestrator stops corroboration when this is reached |

The old "3 per script" per-script ceilings are withdrawn — they double-counted
(3 + 3 + N-facts × 3 does not fit 6). Use the priority ladder instead.

## Priority ladder (spend in this order, stop when budget is gone)

1. **`"[Brand Name]"`** (bare name) — always. Anchors `name_ambiguity`,
   `target_domain_rank`, and Wikipedia/Wikidata presence when a brand-matching
   page appears in the results (`wikipedia_presence_source: "bare_name_results"`).
2. **`"[Brand Name] wikipedia"`** — only if step 1 did not already surface a
   brand-matching `wikipedia.org` page (a disambiguation page does not count).
3. **`"[Brand Name] wikidata"`** — only if no brand-matching Wikipedia page was found.
4. **`"[Brand Name] founded year"`** — only if the site states a founding year.
5. **`"[Brand Name] company"` / `"what is [Brand Name]"`** — only if budget
   remains and the site has a clear one-line description.
6. **`"[Brand Name] headquarters"`** — only if budget remains and the site
   states a location.

`name_ambiguity` and `entity_match_evidence` cost **0 extra searches** — they are
derived from queries 1–3.

## Enforcement

- **Never corroborate a fact the page does not state.** `check_citation_consistency.py`
  returns `skipped_reason` and consumes nothing when `fact_value_on_site` is empty.
- Thread `search_budget_remaining` (int) into `check_citation_consistency.py` and
  `check_entity_disambiguation.py`. Each echoes a `search_budget` block:
  `{remaining_before, searches_consumed_estimate, remaining_after, over_budget}`.
  When `over_budget` is true, stop.
- **Snippet-only.** Scripts parse titles, domains, and snippet excerpts only.
  They MUST NOT fetch or scrape full external pages.
- **Confidence labeling.** All search-derived findings are lower-confidence and
  less reproducible than deterministic checks. "No corroboration found in N
  searches" is evidence of brand fragility, NOT proof of absence.
