# Search Budget & Non-Deterministic Execution Reference

Unlike HTTP fetches in other skills, web search operations carry real per-call monetary, rate, and performance costs. In addition, web search engine outputs are non-deterministic and vary over time.

## Shared Search Budget Rules

Across an entire audit run for a single target site:

1. **Per-Script Ceiling**:
   - `scripts/check_citation_consistency.py`: Maximum **3 searches** per invocation.
   - `scripts/check_entity_disambiguation.py`: Maximum **3 searches** (1 bare brand name, 1 Wikipedia query, 1 Wikidata query).

2. **Total Skill Search Ceiling**:
   - For a standard single-page audit, the total web search budget for `freshness-corroboration` is **6 searches maximum**.
   - If the orchestrator invokes `check_citation_consistency.py` multiple times for different facts, it MUST enforce an overall ceiling of no more than **10-12 total web searches** per full audit run.

3. **Snippet-Only Extraction Guardrail**:
   - Web search scripts MUST only parse titles, domains, and snippet excerpts returned in the search engine response payload.
   - Scripts MUST NOT fetch or scrape full external web pages from search results. This prevents budget overruns and unexpected network latency.

4. **Confidence & Reproducibility Labeling**:
   - Web search findings are labeled as lower-confidence and less reproducible than fully deterministic checks.
   - Reporting "no external corroboration found in N searches" is recorded as evidence of brand fragility, NOT proof of total absence.
