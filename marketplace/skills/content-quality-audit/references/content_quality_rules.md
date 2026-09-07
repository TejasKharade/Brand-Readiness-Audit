# Content Quality & AI Citability Rules

This reference defines the evaluation heuristics, low-entropy heading lexicons, ambiguous pronoun patterns, and archetype calibrations used by the `content-quality-audit` skill.

---

## 1. Low-Entropy Heading Lexicon

When RAG retrieval systems chunk a webpage, section headings are often prepended to chunk text to form the vector embedding (e.g., `Page Title > Section Heading > Paragraph`). 

Headings that contain only generic filler words provide **zero semantic signal** to the embedding model:

### Exact Low-Entropy Trigger List (Normalized Lowercase)
* `overview`
* `introduction`
* `background`
* `details`
* `summary`
* `more information` / `more info`
* `about`
* `features`
* `general`
* `misc` / `miscellaneous`
* `notes`
* `conclusion`

*Evaluation Rule*: If a heading consists *solely* of one of these generic phrases (e.g. `## Overview` or `### Details`), flag **`RAG_HEADING_LOW_ENTROPY`**. If it includes specific domain nouns (e.g. `## Architecture Overview` or `### Pricing Details`), it passes.

---

## 2. Ambiguous Anaphora & Orphan Chunk Patterns

AI search engines (Perplexity, ChatGPT Search) chunk long documents into 256–512 token segments. If a section starts with an ambiguous pronoun, the chunk loses its subject entity and receives low vector similarity scores.

### High-Risk Opening Anaphora Patterns (First Sentence of Section)
* `^it\b` (e.g. *"It provides high availability..."*)
* `^they\b` (e.g. *"They allow developers to..."*)
* `^this (?:tool|platform|solution|system|software|library|framework|service)\b` (e.g. *"This tool ensures that..."*)
* `^as (?:mentioned|stated|seen|discussed) (?:above|earlier|before)\b`
* `^like we said\b`

*Evaluation Rule*: If the opening sentence matches these patterns without naming a specific entity noun, flag **`RAG_CHUNK_ORPHAN_PRONOUN`**. The fix is to explicitly restate the subject (e.g. *"Garage S3 provides high availability..."*).

---

## 3. Empty Throat-Clearing & Fluff Preambles

Opening paragraphs that waste tokens on generic digital cliches dilute information entropy and are skipped by AI extractors:

### High-Risk Preamble Cliches
* `in today'?s (?:fast-paced|rapidly changing|digital|modern) (?:world|era|landscape)`
* `in (?:the|an) era of\b`
* `it is no secret that\b`
* `have you ever wondered\b`
* `in an increasingly (?:connected|complex) world\b`
* `businesses (?:everywhere|today) are (?:striving|looking) to\b`

*Evaluation Rule*: If detected in the first 150 words of a guide or article, flag **`BLUF_FLUFF_PREAMBLE`**. Recommend replacing with a direct declarative definition.

---

## 4. Content Flooding Thresholds by Archetype

When an author puts too much continuous prose under a single heading without structural delimiters, the LLM chunker splits the text mid-thought, causing "Lost in the Middle" attention degradation:

| Archetype | Word Count Threshold | Structural Mitigations Accepted |
| :--- | :--- | :--- |
| **Guides / Blog (`/blog/*`, `/guides/*`)** | $> 400$ words continuous prose | Subheadings (`<h3>`), lists (`<ul>`, `<ol>`), tables (`<table>`) |
| **Documentation (`/docs/*`)** | $> 800$ words continuous prose | Code blocks (`<pre><code>`), command listings, tables |
| **Homepage / Commercial (`/`, `/pricing`)** | Exempt | Visual layouts, short copy blocks |

*Evaluation Rule*: If continuous prose exceeds the threshold without any structural breaks, flag **`RAG_SECTION_CONTENT_FLOODING`**.

---

## 5. Proactive Citability Suggestions (INFO Only)

To prevent overfitting on non-research websites (local businesses, simple SaaS sites), these checks are strictly informational:

* **`CITABILITY_STATISTICAL_SUGGESTION` (INFO)**: If an informational article/guide contains zero quantitative data points (numbers, percentages, metrics), suggest adding verifiable benchmarks referencing the Princeton study (+37% citation probability).
* **`STRUCTURE_TABULAR_SUGGESTION` (INFO)**: If a page contains 3+ distinct price figures or plan tier names in running prose with zero `<table>` elements, suggest formatting as a comparison table for higher LLM quote probability.
