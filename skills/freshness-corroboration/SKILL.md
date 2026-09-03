---
name: freshness-corroboration
description: Audits website structured data (schema.org JSON-LD), brand entity disambiguation, and fact freshness/corroboration across pages to prevent AI hallucinations and misrepresentations.
license: MIT
---

# Freshness & Corroboration Audit Skill

## When to use
Use when auditing structured metadata, schema.org markup, entity consistency, and fact corroboration across pages to ensure AI assistants can confidently extract, verify, and cite brand claims.

## Inputs
- `url` or `domain`: Target site URL or hostname.

## Procedure

1. **JSON-LD & Structured Data Validation**:
   - Parse HTML for embedded JSON-LD (`<script type="application/ld+json">`).
   - Validate schema types (`Organization`, `Product`, `Article`, `FAQPage`, `BreadcrumbList`).
   - Check for missing critical fields (e.g. `name`, `description`, `url`, `logo`, `sameAs`, `offers`, `price`).

2. **Entity Disambiguation & `sameAs` Links**:
   - Check if `Organization` schema includes authoritative `sameAs` entity links (Wikipedia, Wikidata, official social profiles, Crunchbase).
   - Identify entity ambiguity risks where brand name overlaps with common nouns or third-party products.

3. **Cross-Page Fact Corroboration & Consistency**:
   - Compare key facts (pricing, product names, contact information, release dates) across different site pages.
   - Detect conflicting or stale information that degrades AI confidence during retrieval-augmented generation (RAG).

## Output
Emits findings regarding missing structured data, uncorroborated facts, and entity ambiguity along with JSON-LD remediation snippets.
