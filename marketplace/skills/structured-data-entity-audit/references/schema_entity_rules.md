# Schema & Entity Disambiguation Rules

This reference defines the evaluation heuristics, authoritative registries, atomic fact extraction patterns, and description extractability criteria used by the `structured-data-entity-audit` skill.

---

## 1. Entity Grounding & `sameAs` Authority Registry

For AI citation engines (ChatGPT Search, Perplexity, Claude), smaller brands and open-source tools face an acute **entity ambiguity barrier**. Without explicit disambiguation anchors, AI models conflate niche tools with generic terms or cite third-party documentation mirrors (e.g. citing `docs.rs` rather than `garagehq`).

### Authoritative Entity Graph Whitelist
Root entity schemas (`Organization`, `Brand`, `SoftwareApplication`) should include `sameAs` links pointing to recognized authoritative registries:

* **Global Knowledge Graphs:**
  * `wikidata.org/wiki/Q...`
  * `wikipedia.org/wiki/...`
* **Code & Package Ecosystem Registries:**
  * `github.com/...`
  * `gitlab.com/...`
  * `crates.io/crates/...`
  * `npmjs.com/package/...`
  * `pypi.org/project/...`
  * `hub.docker.com/r/...`
  * `pkg.go.dev/...`
* **Corporate & Business Registries:**
  * `linkedin.com/company/...`
  * `crunchbase.com/organization/...`
  * `opencorporates.com/...`
* **Verified Social & Community Anchors:**
  * `x.com/...` / `twitter.com/...`
  * `youtube.com/...`

### Entity Grounding Severity Calibration
* **Software / Developer Tools / Niche SaaS**: **HIGH**. If a software product or developer library lacks both Wikidata and code/package registry `sameAs` links, AI engines frequently misattribute authoring or cite mirrors.
* **General Consumer / Early-Stage Brands**: **MEDIUM / OPTIMIZATION**. Early-stage entities without Wikipedia/Wikidata entries should provide LinkedIn, GitHub, or Crunchbase profiles as verifiable baseline grounding.

---

## 2. Root Entity Types & Semantic Hierarchy

The homepage is the primary anchor of the brand's entity graph. It should declare at least one primary root entity:

| Primary Entity Type | Allowed Equivalents / Subtypes | Context |
| :--- | :--- | :--- |
| `Organization` | `Corporation`, `OnlineBusiness`, `LocalBusiness`, `NGO` | Corporate / brand identity |
| `Brand` | `Organization`, `Product` | Consumer / retail identity |
| `SoftwareApplication` | `WebApplication`, `MobileApplication` | Developer tools / SaaS products |
| `WebSite` | `WebPage` | General site-level metadata |

*Note*: If a site uses `Brand` instead of `Organization`, or `WebApplication` instead of `SoftwareApplication`, accept it via semantic inheritance.

---

## 3. Atomic Fact Consistency Patterns

AI search engines extract structured values (`price`, `availability`, `softwareVersion`) for instant answers in search summaries. If schema claims contradict visible on-page text, AI engines either hallucinate or degrade source trust.

### A. Pricing Discrepancies
* **Schema Fields:** `offers.price`, `offers[].price`, `price`
* **Extraction:** Extract numeric price values from schema.
* **HTML Text Scan:** Search visible HTML text for currency symbols (`$`, `€`, `£`, `USD`, `EUR`) followed by numbers.
* **Failure Condition:** Schema declares `$0` or `$49` while visible text explicitly displays `$79` or `Free` when schema says `$99`.

### B. Stock Availability Discrepancies
* **Schema Fields:** `offers.availability`, `availability`
* **Schema Values:** `https://schema.org/InStock`, `https://schema.org/OutOfStock`, `InStock`, `OutOfStock`
* **Visible Text Scan:** Look for explicit badges: `"Sold out"`, `"Out of stock"`, `"Back in stock"`, `"Currently unavailable"`.
* **Failure Condition:** Schema says `InStock` while visible text declares `"Out of Stock"` (or vice-versa).

### C. Software Version Discrepancies
* **Schema Fields:** `softwareVersion`, `version`
* **Failure Condition:** Schema lists an obsolete version (e.g. `0.7.0`) while visible page text prominently displays a newer release (e.g. `v0.9.1` or `Release 1.0`).

---

## 4. Vacuous Description & Fluff Corpus

AI summarization engines vectorize schema `description` properties as semantic anchors. Descriptions filled with zero-information corporate buzzwords provide zero retrievable facts.

### A. Length Rules
* **Missing / Empty**: `description` is absent or `""`. Severity: **HIGH**.
* **Too Short (< 25 characters)**: e.g. `"Fast software"`, `"Analytics tool"`. Severity: **MEDIUM**.

### B. Low-Entropy Marketing Buzzwords
Descriptions where $> 50\%$ of the content consists of empty corporate filler rather than functional capability:
* `"leading provider of"`
* `"innovative solutions"`
* `"cutting-edge technology"`
* `"all-in-one platform"`
* `"world-class"`
* `"seamless end-to-end"`
* `"next-generation"`
* `"empowering businesses"`
* `"game-changing"`
* `"transform your workflow"`
* `"scalable synergy"`

---

## 5. Multi-Skill Timing Handoff (JS-Deferred Schema)

From Skill 2 (`js-render-content-audit`):
* If JSON-LD `<script type="application/ld+json">` is detected in Pass B (Rendered DOM) but was absent in Pass A (Raw HTTP stream), flag **`SCHEMA_TIMING_JS_DEFERRED`** (Severity: **HIGH**).
* Fast AI crawlers (like `OAI-SearchBot`) fetch pages via raw HTTP. If structured data is injected late via React `useEffect`, Next.js client hydration, or Google Tag Manager, raw HTTP crawlers receive zero schema.
