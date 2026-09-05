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
   - Extract `<script type="application/ld+json">` elements from page HTML.
   - Validate core schemas (`Organization`, `Product`, `Article`, `FAQPage`, `BreadcrumbList`).
   - Check for required schema attributes (`@context`, `@type`, `name`, `url`, `description`, `logo`).
   - Flag invalid JSON or missing key schema blocks as `Medium` severity findings.

2. **Entity Disambiguation & `sameAs` Coverage**:
   - Verify `Organization` or `Brand` schema contains authoritative `sameAs` links (Wikipedia, Wikidata, official social channels, LinkedIn, Crunchbase).
   - Assess entity ambiguity risks where brand names overlap with generic terms or third-party products.

3. **Cross-Page Fact Corroboration & Consistency**:
   - Cross-check critical brand facts (pricing tiers, contact emails, product names, key features) across home, product, and documentation pages.
   - Flag conflicting or outdated facts that risk causing RAG (Retrieval-Augmented Generation) hallucinations.

## Output
Emits findings regarding missing structured data, uncorroborated facts, and entity ambiguity along with JSON-LD remediation snippets.
