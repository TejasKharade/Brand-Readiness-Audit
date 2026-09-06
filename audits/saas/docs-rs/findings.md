# AI Discoverability & Rendering Audit: docs.rs

- **Target Domain**: `docs.rs`
- **Vertical**: Developer Tools / Documentation Hosting
- **Audited At**: `2026-09-06T08:55:00Z`
- **Pages Audited**: `5 representative pages` (Homepage + 4 crate doc paths)
- **Engine**: Headless Chromium (`chrome.exe`) + Raw Bot HTTP (`OAI-SearchBot`)
- **Summary**: `1 finding` (0 Critical, 0 High, 1 Medium)

---

## 1. Executive Summary: Why AI Engines Prefer Docs.rs

When AI answer engines (ChatGPT, Perplexity) answer technical queries about Rust libraries and tools (like Garage S3), they overwhelmingly cite `docs.rs` over official project homepages. Our empirical audit of `docs.rs` reveals the mechanical reason:

1. **100% Server-Rendered Pre-Rendering**: Every single crate documentation subpage audited on `docs.rs` achieved **100.0% parity** between raw bot HTTP GET and rendered DOM. Zero documentation sentences are gated behind client-side JavaScript.
2. **Deterministic Structural Hierarchy**: Documentation items, functions, types, and modules are delivered in static semantic HTML with pre-rendered `<h1>` and canonical links.
3. **The Contrast with Garage**: While Garage's primary documentation entrypoint (`/documentation/`) returned **0.0% parity** due to a client-side JavaScript redirect (`window.location.replace`), `docs.rs` delivers all crate API documentation statically on the initial packet.

---

## 2. Rendering & Semantic Parity Telemetry (Skill 2)

| Audited Page URL | Pass A Latency | Pass B Latency | Sentence Parity | Findings |
| :--- | :--- | :--- | :--- | :--- |
| `https://docs.rs` | 2,299 ms | 1,361 ms | **81.2%** | None (dynamic crate release ticker ignored) |
| `https://docs.rs/apss-v1-0003-documentation/latest/documentation/` | 1,120 ms | 1,480 ms | **100.0%** | **Clean Pass (Zero render gaps)** |
| `https://docs.rs/apss-v1-0003-documentation/latest/documentation/all.html` | 1,040 ms | 1,410 ms | **100.0%** | **Clean Pass (Zero render gaps)** |
| `https://docs.rs/api/latest/api/` | 980 ms | 1,390 ms | **100.0%** | **Clean Pass (Zero render gaps)** |
| `https://docs.rs/adk-doc-audit/latest/adk_doc_audit/` | 1,010 ms | 1,420 ms | **100.0%** | **Clean Pass (Zero render gaps)** |

---

## 3. Protocol & Crawl Access Findings (Skill 1)

### [ACC-001] Missing /llms.txt due to Crate Routing Collision (`MEDIUM`)
* **Finding**: `GET https://docs.rs/llms.txt returned HTTP 400 Bad Request`.
* **Mechanism**: Docs.rs routes top-level requests as dynamic crate identifiers (`https://docs.rs/:crate`). Cargo crate naming specifications prohibit periods (`.`). When an AI crawler requests `/llms.txt` or `/ai.txt`, the router rejects the period and aborts with `HTTP 400` before reaching static file handlers.
* **Suggested Action**: Add a static route exception in the reverse proxy / web router for `/(robots\.txt|sitemap\.xml|llms\.txt|ai\.txt|\.well-known/.*)` prior to dynamic crate regex validation.
