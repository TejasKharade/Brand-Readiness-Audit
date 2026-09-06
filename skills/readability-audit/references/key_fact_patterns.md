# Key Fact Extraction Patterns & Reference Heuristics

This file documents the configurable patterns, regexes, normalization maps, and image ALT classification rules used by `check_content_consistency.py` and `check_nontext_facts.py`.

## 1. Universal Schema Fact Consistency (`check_content_consistency.py`)

- **Schema-Agnostic Matching**: Extracts scalar structured facts (`name`, `headline`, `price`, `availability`, `telephone`, `startDate`, `datePublished`, `author`) from any schema entity and verifies presence in visible HTML text.
- **Matching Heuristics**:
  1. Exact substring match.
  2. Currency / numeric value extraction match.
  3. Token overlap fuzzy match (>= 70% non-stopword token overlap).
- **Hidden Element Exclusions**: Uses `hidden_depth` tracking to exclude `display:none`, `visibility:hidden`, `hidden`, and `aria-hidden="true"` text.

## 2. Image ALT Classification Rules (`check_nontext_facts.py`)

Categorizes non-text visual elements into 4 W3C-compliant classes:
1. `images_missing_alt`: `alt` attribute omitted entirely (W3C accessibility flaw).
2. `images_decorative_alt`: `alt=""` (explicit empty string, W3C standard for decorative icons/spacers).
3. `images_generic_alt`: Placeholder strings (`"logo"`, `"image"`, `"photo"`, `"banner"`).
4. `images_with_descriptive_alt`: Informative alt text describing the image content.

## 3. PDF Document Inspection (`check_nontext_facts.py`)

- **Streaming Safety**: Streamed download capped at **10MB max size** (`stream=True` with chunk iteration) to prevent Out-Of-Memory memory bombs.
- **Link Cap**: Inspects up to 3 PDF links per page.
- **Text Layer Extraction**: Evaluates whether digital text layer contains >20 characters (`"pdf_has_text_layer": true/false`).
