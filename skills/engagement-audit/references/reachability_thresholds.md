# Content Depth & Word Count Thresholds Reference

This reference documents the word-count reference ranges used by `scripts/check_content_depth.py` when a `page_type_hint` is provided.

> [!WARNING]
> **Heuristic Starting Point Notice**:
> These word-count ranges are **starting-point heuristics** intended to catch extremely thin pages. They vary significantly across industries, site categories, and layout designs (e.g. visual portfolios vs. technical documentation). A page below the reference range is a weak signal worth noting, NOT proof of a quality defect. These numbers have not been empirically validated across a broad sample and should be adjusted after real-site field testing.

## Reference Ranges per `page_type_hint`

| Page Type (`page_type_hint`) | Expected Minimum Words | Recommended Range | Rationale |
| :--- | :--- | :--- | :--- |
| `product` | 200 words | 500+ words | Product pages need sufficient specs, feature details, and warranty/pricing context. |
| `service` | 300 words | 800+ words | Service offerings require process breakdown, deliverables, and client outcomes. |
| `article` | 600 words | 1500+ words | Editorial and educational articles require in-depth topic coverage. |
| `unknown` | None (`null`) | None (`null`) | No range check is attempted when page type is unspecified. Raw word count is reported. |
