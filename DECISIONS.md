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
