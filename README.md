# Brand AI Readiness Audit

This repository contains a comprehensive, multi-stage auditing pipeline designed to evaluate how well a website is optimized for modern AI Search Engines (like ChatGPT Search, Perplexity, and Claude) and Large Language Models.

**IMPORTANT NOTE FOR EVALUATORS & AGENTS:** 
> [!IMPORTANT]
> The **`marketplace/`** folder is the official final submission package for the Adobe Hackathon. 
> The `tools/` folder contains local runners, stage orchestrators, and testing pipelines that are for local development only and are not part of the final packaged submission.

## 📁 Repository Structure

### `/marketplace/` (The Official Submission)
This directory contains the production-ready skills that make up the audit.
- `marketplace.json`: The manifest file that declares all skills and the main entrypoint.
- `skills/`: The specialized Python scripts that perform the actual auditing.
  - `ai-crawler-access-audit/`: Skill 1 (Checks robots.txt, firewalls, user-agent blocks, sitemaps, and llms.txt).
  - `js-render-content-audit/`: Skill 2 (Compares fast raw-HTTP reads vs. slow headless-browser DOM hydration to detect JS-hidden content).
  - `structured-data-entity-audit/`: Skill 3 (Extracts JSON-LD schema, checks `sameAs` entity grounding, and verifies page-specific schemas).
  - `content-quality-audit/`: Skill 4 (Chunks text, checks for orphan pronouns, low-entropy headings, fluff, and prose-flooding).

### `/tools/` (Local Development Environment)
Scripts used to run the pipeline locally and evaluate results.
- `run_pipeline.py`: The master script that reads URLs from `sites.csv` and triggers the stages.
- `test_pipeline.py`: Runs the 4 marketplace skills (Stage A).
- `stage_b.py`: Captures web pages into web archives for ground truth evaluation.
- `stage_c.py`: Sends the findings to an LLM judge (via OpenRouter) to evaluate Precision and Recall.
- `aggregate.py`: Aggregates the results into a final scorecard (`aggregate_report.json`).

### `/audits/`
Generated output folder containing logs, JSON outputs from the skills, and the final aggregated scorecards.

### Root Files
- `test_pipeline.py`: Entrypoint for running the marketplace skills.
- `sites.csv`: The target URLs to audit.
- `DECISIONS.md`: Log of architectural tradeoffs and decisions.
- `hybrid_bot_test_suggestion.md`: Sandbox testing notes and future improvement ideas.

## 🚀 How It Works
The pipeline runs sequentially across the skills. If a site fails Skill 1 (e.g., blocks the crawler), the subsequent skills may not run or will run with degraded performance. The goal of this suite is zero-dependency, pure standard-library execution to ensure maximum portability and compliance with sandboxed environments.
