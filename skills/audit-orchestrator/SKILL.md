---
name: audit-orchestrator
description: Entrypoint master orchestrator skill that coordinates execution across all 5 specialized sub-skills (crawl-access-audit, crawl-render-audit, readability-audit, freshness-corroboration, engagement-audit) and synthesizes the final Brand AI Readiness Audit Report.
license: MIT
---

# Audit Orchestrator Skill

## When to use
Use as the main entrypoint to conduct a complete end-to-end Brand AI Readiness Audit for a website domain or target URL.

## Workflow & Sub-Skill Execution Plan

1. **Step 1: Crawl Access Audit (`crawl-access-audit`)**
   - Checks `robots.txt` access rules for AI crawlers (GPTBot, PerplexityBot, ClaudeBot, Bytespider).
   - Performs dual-identity HTTP fetches (Browser vs. AI Bot) to detect bot-blocking or challenges.
   - Evaluates sitemap health and page indexing signals (`noindex`, canonicals).

2. **Step 2: Crawl Render Audit (`crawl-render-audit`)**
   - Compares raw initial HTTP HTML payload vs. JS-rendered DOM.
   - Measures hydration text ratios and identifies client-side JS trapped structured data.

3. **Step 3: Readability Audit (`readability-audit`)**
   - Audits Schema.org JSON-LD completeness across 9 schema types (Product, Organization, Article, FAQPage, BreadcrumbList, Recipe, Event, SoftwareApplication, VideoObject).
   - Validates semantic HTML heading hierarchy and content consistency.

4. **Step 4: Freshness & Corroboration Audit (`freshness-corroboration`)**
   - Parses publication/modification dates and flags stale/outdated content (>1-2 years).
   - Evaluates `sameAs` entity disambiguation coverage and checks off-site citation consistency.

5. **Step 5: On-Site Engagement Audit (`engagement-audit`)**
   - Measures performance friction (DOM node density, payload size, unoptimized assets).
   - Detects layout friction (intrusive overlays, cookie banners, newsletter popups).
   - Audits navigation clarity and orientation quality.

6. **Step 6: Master Synthesis (`scripts/synthesize_report.py`)**
   ```bash
   echo '{"site": "https://example.com", "skill_outputs": {...}}' | python skills/audit-orchestrator/scripts/synthesize_report.py
   ```
   - Combines outputs from all sub-skills into a single JSON report.
   - Assigns severity scores (Critical, High, Medium, Low).
   - Calculates the overall **Brand AI Readiness Score** (0 - 100).
   - Generates a prioritized remediation action plan.

## Output Schema
Produces the final master audit JSON report containing site URL, timestamp, readiness score, summary breakdown, detailed findings list, and proactive recommendations.
