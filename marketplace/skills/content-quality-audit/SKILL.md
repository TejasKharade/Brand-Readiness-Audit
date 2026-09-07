---
name: content-quality-audit
description: Audits entire webpage content section-by-section for AI citability, RAG embedding chunkability, ambiguous anaphora (orphan pronouns), low-entropy headings, and content flooding.
license: MIT
---

# Content Quality & AI Citability Audit

## When to use
Use this skill when evaluating how effectively an AI search engine (Perplexity, ChatGPT Search, Claude) or RAG pipeline can parse, chunk, embed, and quote a webpage's actual written content. It diagnoses why technically accessible pages are ignored or distorted by LLMs.

## Inputs
* `domain_or_url`: Target domain or page URL (e.g., `https://example.com`).
* `--input-access` (Optional): Path to Skill 1's output JSON containing `sampled_pages["curated_sample"]`.

## Procedure
1. **Execute Full-Content Quality Audit**:
   Run the audit script:
   ```bash
   python scripts/check_content_quality.py <domain_or_url> [--input-access <path>] --json
   ```
2. **Partition and Audit Every Section (Zero Skipping)**:
   * The tool strips HTML navigation/footer boilerplate and splits the page into sequential sections based on headings (`<h1>`, `<h2>`, `<h3>`).
   * Every section is audited top-to-bottom across the entire page body.
3. **Inspect RAG Chunk Autonomy (`RAG_CHUNK_ORPHAN_PRONOUN`)**:
   * Evaluates the opening sentence of each section.
   * Flags ambiguous pronouns (*"It provides...", "This tool allows..."*) that lose entity context when RAG systems chunk the document into separate vector embeddings.
4. **Detect Low-Entropy Headings (`RAG_HEADING_LOW_ENTROPY`)**:
   * Matches heading titles against the deterministic generic lexicon in [references/content_quality_rules.md](references/content_quality_rules.md) (e.g. `Overview`, `Details`, `Features`).
5. **Evaluate BLUF & Throat-Clearing Filler (`BLUF_FLUFF_PREAMBLE`)**:
   * Audits the first 150 words of articles/guides for empty digital cliches (*"In today's fast-paced world..."*) rather than direct declarative answers.
6. **Detect Content Flooding (`RAG_SECTION_CONTENT_FLOODING`)**:
   * On `/blog/*` and `/guides/*`: Flags sections exceeding 400 words under a single heading without subheadings, lists, or tables.
   * On `/docs/*`: Threshold is raised to 800 words to allow dense technical code references.
7. **Emit Proactive Suggestions (INFO)**:
   * Suggests tabular formatting (`STRUCTURE_TABULAR_SUGGESTION`) and statistical proof points (`CITABILITY_STATISTICAL_SUGGESTION`) where beneficial, with zero severity penalty.

## Output
Emits standard JSON conforming to the marketplace schema:
* `site`: Audited domain.
* `summary`: Counts of `critical`, `high`, `medium`, `low`, and `info` findings.
* `findings`: Section-level diagnostic findings with excerpted evidence and actionable fixes.
* `content_profile`: Total sections audited, total words, heading hierarchy, and autonomous chunk ratio.
