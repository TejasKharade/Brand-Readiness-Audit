# Architectural Decisions & Optimization Backlog

This document tracks all design trade-offs, scope decisions, and deferred optimizations made during the development of the `brand-ai-readiness-audit` skill marketplace. These items will be reviewed and iterated on during the final consolidation and optimization phase before competition submission.

---

## 1. Page Sampling Frame: Deep Testing vs. 5-Minute Runtime Budget

* **Decision**: During skill development and field testing, we deliberately widen the page sampling cap from 3 to **8–10 pages** (via an adjustable `--max-pages` flag).
* **Rationale**: Restricting the crawl to 3 pages early in development masks hydration bugs, route mismatch errors, and template variations that only appear on deep documentation or interior product pages. We prioritize discovering real failure modes first.
* **Final Optimization Plan**:
  * Implement route-based **archetype clustering** (auditing 1 representative URL per route pattern, e.g. `/docs/*`, `/blog/*`, `/pricing`) so auditing 3–4 pages reliably represents 1,000+ pages.
  * Enforce strict budget guards to guarantee the entire marketplace finishes in **$< 5\text{ minutes}$** on standard evaluation machines.

---

## 2. Headless Browser Strategy (Zero-Binary Package Compliance)

* **Decision**: We do NOT bundle Chromium binaries (150–200MB) inside the repository or the submission zip. Instead, `check_render.py` auto-detects and invokes the host machine's native browser (`chrome.exe`, `msedge.exe`, `google-chrome`, or `chromium`) via standard CLI flags (`--headless --disable-gpu --dump-dom`).
* **Rationale**:
  * Respects the **$\le 50\text{MB}$ zip limit** for the Adobe Hackathon Round 3 submission.
  * Ensures zero pip dependencies for browser automation (`urllib.request` + `subprocess` standard library).
* **Final Optimization Plan**:
  * Verify graceful degradation behavior when running in headless environments where no browser binary exists (ensure the fallback static inspection runs cleanly without unhandled exceptions).

---

## 3. Two-Pass Parity Engine vs. Hardcoded Word Thresholds

* **Decision**: Replaced naive word-count criteria (e.g., `word_count < 150`) with **sentence-level substring containment parity** between Pass A (raw bot HTTP GET) and Pass B (hydrated browser DOM).
* **Rationale**: Concise pages (e.g., 1-line tool definitions, atomic answers) are highly valuable for AI citation and should never be penalized. The tool only flags pages where content rendered in Pass B is missing from Pass A.
* **Final Optimization Plan**:
  * Refine noise-filtering heuristics to ignore dynamic third-party tracking scripts, live chat greetings, and cookie banners.

---

## 4. Deferred Concurrency & Performance Enhancements

The following optimizations are deferred to the final polish phase to avoid multi-process race conditions during active skill authoring:

1. **Parallel Worker Pool (`concurrent.futures.ThreadPoolExecutor`)**:
   * *Status*: Deferred.
   * *Target*: Run Pass B browser instances in parallel (3 concurrent workers) to cut wall-clock render time by 60–70%.
2. **Aggressive Chromium Subsystem Blocking**:
   * *Status*: Partially implemented (`--blink-settings=imagesEnabled=false`, `--disable-remote-fonts`, `--disable-background-networking`, `--disable-sync`, `--mute-audio`).
   * *Target*: Add request-interception rules if CDP (Chrome DevTools Protocol) is adopted.
3. **Smart Triage Pass (Skip Pass B on Verified Static Pages)**:
   * *Status*: Under evaluation.
   * *Trade-off*: Skipping Pass B saves time, but risks missing client-injected JSON-LD (`STRUCTURED_DATA_TIMING`) or dynamic navigation links (`INTERNAL_LINK_DISCOVERY_GAP`).

---

## 5. Pruned Schema Suite vs. Legacy SEO Dogma (Skill 3)

* **Decision**: Refused to implement legacy SEO mandates for interior pages (e.g. flagging missing `TechArticle` or `BreadcrumbList` as high-severity errors). Instead, pruned the check suite to **4 high-leverage checks**:
  1. `SCHEMA_SYNTAX_AND_TIMING` (Syntax errors & client-JS deferral via Skill 2 handoff)
  2. `ENTITY_ROOT_GROUNDING` (Brand/Org/SoftwareApp on homepage + `sameAs` authority links)
  3. `SCHEMA_FACT_CONTRADICTION` (Price, stock availability, software version vs on-page text)
  4. `SCHEMA_DESCRIPTION_VACUOUS` (Zero-entropy corporate marketing buzzwords)
* **Rationale**:
  * An empirical probe of top AI-cited sites (`stripe.com/docs`, `docs.rs`, `linear.app`) revealed they have **0 JSON-LD tags**. Modern LLM RAG engines vectorize raw HTML directly and derive hierarchy from URL paths. Flagging clean documentation sites for missing schema produces false positives and discredits the tool.
  * Conversely, the probe confirmed that entity ambiguity (the Garage problem) is real: small/niche tools without `sameAs` grounding lose citations to third-party mirrors (`docs.rs`).
* **Final Optimization Plan**:
  * Evaluate potential light `INFO` suggestions for `SoftwareApplication` or `FAQPage` on interior pages where structured data can provide instant answers without making it a blocking penalty.

---

## 6. Full-Content Section Audit & Anti-Overfitting Safeguards (Skill 4)

* **Decision**: Audits the entire page body section-by-section without skipping paragraphs or deep subsections, while applying strict anti-overfitting rules:
  1. **Dropped `CITABILITY_SOURCE_AUTHENTICITY` domain whitelist**: Hardcoded domain tiering would falsely flag legitimate research blogs (e.g. Dan Luu, Martin Fowler, custom engineering domains). Substantive links are trusted without arbitrary whitelists.
  2. **Dropped `TEMPORAL_ANCHORING_STALE` duplication**: Freshness and date checks belong exclusively to Skill 3 (structured data and metadata) to prevent duplicate findings.
  3. **Archetype-Calibrated Flooding**: 400-word flooding threshold applies strictly to `/blog/*` and `/guides/*`. Technical documentation (`/docs/*`) is raised to 800+ words to accommodate legitimate API and flag reference listings.
  4. **Deterministic Heading Lexicon**: Low-entropy headings (`Overview`, `Details`, `Features`, `Introduction`) are mechanically matched against an explicit reference list in `references/content_quality_rules.md`.

---

## 7. E-Commerce Platform Calibration & Multi-Variant Safeguards

* **Tested Platform**: `allbirds.com` (Headless Shopify Plus architecture with heavy dynamic bundles, 760+ pages, and multi-variant product schemas).
* **Key Calibrations**:
  1. **Sitemap Child Unwrapping**: Fixed substring false-match where `"item" in "sitemap"` caused the scraper to pick the first child sitemap indiscriminately. Added explicit regex word boundary pattern `re.search(r"[_\-/](products?|items?|goods?)[_\-\./\?]", u, re.I)` to discover and sample product pages alongside docs and blogs.
  2. **Multi-Variant Inventory Aggregation**: In real-world e-commerce, multi-variant products (e.g. shoes with 15 size options) legitimately contain both `InStock` and `OutOfStock` offers. Previous logic fired 8 duplicate `SCHEMA_AVAILABILITY_CONTRADICTION` errors on the same page. Calibrated the check to aggregate across all variant offers—only triggering when structured data uniformly declares one status while page text announces the exact opposite.
  3. **Per-URL Finding De-duplication**: Guarded `_add_finding` against duplicate finding codes on the same URL to prevent multi-offer spam on catalog pages.

---

## 8. Plain-English Verbose Logging & Audit Telemetry Overhaul

* **Context**: The terminal audit pipeline runner (`test_pipeline.py`) was overhauled to provide deep visibility into every step of the audit without requiring users to parse raw JSON logs or decipher cryptic error codes.
* **Key Implementations**:
  1. **Plain-English Explanations Registry**: Created an explicit registry mapping all audit finding codes across Gates 1–4 to four standardized fields:
     - **What Happened**: Simple, non-jargon explanation of the technical condition.
     - **Why It Matters for AI**: Real-world causal impact on search citation, brand visibility, or hallucination in ChatGPT Search, Perplexity, Claude, and Gemini.
     - **Technical Evidence**: Verifiable HTTP status codes, headers, sentence diffs, or JSON-LD snippets.
     - **How to Fix It**: Concrete, step-by-step remediation instructions for webmasters and developers.
  2. **Comprehensive Request Logging (Visited Pages)**: Every single network request across all skills is logged with its HTTP response status, elapsed latency in milliseconds, target URL, and operational purpose (e.g. `Root URL (AI Search Bot)`, `Robots Directives (/robots.txt)`, `XML Sitemap`, `Interior Sample Page`).
  3. **Network Error Resiliency & Unbuffered I/O**:
     - Added automatic retry loops (2 attempts with backoff) and native `gzip`/`deflate` response decompression to `fetch_raw_html` in Skills 3 and 4 to handle transient socket drops or compressed payloads.
     - Added explicit `PAGE_FETCH_ERROR` finding generation so network failures are never silently dropped.
     - Integrated `sys.stdout.flush()` across all terminal outputs to eliminate line-interleaving or delayed buffering on Windows PowerShell consoles.

---

# Future Improvements & Hybrid Architecture Suggestions

## 9. Hybrid Bot vs. Human Discrimination Test
Presently, the `ai-crawler-access-audit` skill only performs a paired "Human vs. Bot" User-Agent discrimination test on the homepage (`origin`). For all interior deep pages (e.g., documentation, blogs), the crawler only requests the page using the AI Bot User-Agent.

**The Problem:**
- **False Assumptions**: If an interior page returns a `403 Forbidden` to the Bot, the current system cannot distinguish whether that page is genuinely private for *everyone*, or if the Bot was specifically discriminated against by a path-specific WAF rule.
- **Performance Constraints**: Performing a paired Human vs. Bot test on every single discovered page would double the number of HTTP requests, severely slowing down the audit.

**The Verdict: Hybrid Approach**
Instead of testing every page twice, the optimal technical design is a lazy-evaluation hybrid approach:
1. **Baseline**: Always perform the paired check on the homepage to establish the domain's baseline WAF posture.
2. **Standard Traversal**: Traverse all deep pages normally, using *only* the AI Bot User-Agent to conserve network requests and speed.
3. **Fallback Trigger**: **If and only if** the Bot hits a `401 Unauthorized`, `403 Forbidden`, or WAF challenge on a deep page, *then* trigger a secondary fallback request using the Human browser User-Agent. 
4. **Evaluation**: If the fallback Human request succeeds (HTTP 200) where the Bot failed, explicitly flag it as a **Path-Specific Bot Discrimination**. If both fail, treat it as a standard restricted page.

---

## 10. Dynamic Archetype Sampling
Instead of forcing a rigid distribution of sampled pages (e.g., 4 products, 3 docs, 2 blogs), the crawler should dynamically adapt its sample based on the detected website archetype. 
- E-commerce sites (e.g., Nike): Sample 12 products, 0 docs.
- SaaS/DevTools (e.g., Docker): Sample 10 docs, 0 products.

---

## 11. URL Folder Clustering for Massive Sites
When auditing massive sites (3000+ pages), randomly selecting 15 pages often results in missing critical hubs (like `/docs`) because they get buried under thousands of repetitive blog posts.
- **Proposed Solution**: We will extract all 3000 URL strings, but instead of randomly picking from the massive pile, we will mathematically cluster them by their "folder" paths (e.g., grouping all `/blog/*` together, all `/p/*` together). 
- We then force the script to only select 1 or 2 URLs from each cluster bucket. This guarantees we have room left in our 15-page limit to pick the rare but highly important `/docs/` links, ensuring maximum diversity without ever needing to download all 3000 pages.

---

## 12. Centralized Configuration File
Currently, values like `max_pages=15` or `max_sitemaps=5` are hardcoded. We need to extract all of these framework limits into a dedicated configuration file (e.g., `audit_config.json` or `.yaml`) so they can be easily tuned per-run without touching the core Python scripts.

---

## 13. Semantic Parity Scoring (LLM Evaluation)
The current JavaScript render audit relies on rigid mathematical parity (e.g., triggering a failure if < 60% of sentences match). This is flawed because it penalizes pages where the missing 40% is just boilerplate fluff (headers, footers, related links) injected by JS.
- **Proposed Solution**: Stop relying purely on math. Instead, extract the actual block of text that the crawler missed (`missing_content_blocks`) and pass it to an LLM evaluator. 
- Ask the LLM: *"Is this missing text critical to the core topic of the page, or is it irrelevant boilerplate?"* 
- Only trigger a parity failure if the LLM confirms that substantive, core content was hidden behind JavaScript.
