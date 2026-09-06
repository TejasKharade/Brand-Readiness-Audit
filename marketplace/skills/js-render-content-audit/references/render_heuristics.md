# Reference Guide: JavaScript Rendering Gaps & Semantic Parity

This guide establishes the rules and patterns for evaluating client-side rendering (CSR) vs. server-side rendering (SSR) in the context of AI search discoverability.

---

## 1. The Core AI Searchbot Principle

AI search engines (`OAI-SearchBot`, `PerplexityBot`, `Google-Extended`) prioritize crawl throughput. When discovering or indexing content, they fetch raw HTML via HTTP GET. While Googlebot eventually queues pages for JavaScript rendering, AI answer engines generating live citations often rely on immediate or near-immediate HTML extraction.

A website does **not** need to deliver 100% of its UI in static HTML. Modern websites are expected to use runtime JavaScript for interactive elements.

### The Deciding Rule:
* **Load-Bearing Content (Must be in Raw HTML)**: Brand name, primary topic `<h1>`, value proposition, core explanatory text, documentation articles, product specifications, pricing terms, and structured schema (`application/ld+json`).
* **Harmless Runtime Clutter (Can be in Client JS)**: Analytics tags, cookie consent banners, dark/light theme toggles, search input autocompletes, dynamic timestamps ("Updated 2m ago"), shopping cart counters ("Cart (0)"), and interactive chat widgets.

---

## 2. The 4 Critical Failure Modes

### Failure Mode 1: Empty-Shell Single Page App (`EMPTY_SHELL_SPA`)
* **Mechanism**: Server returns a minimal HTML container (e.g., `<div id="root"></div>` or `<div id="app"></div>`) and relies on `bundle.js` to fetch data from an API and render content on the client.
* **Symptom**: Pass A (Raw HTML) contains zero domain text or a `<noscript>` tag warning. Pass B (Rendered DOM) contains the actual product page or article.
* **AI Impact**: The AI crawler sees a blank page. The domain is invisible in citation search.
* **Severity**: **CRITICAL**.

### Failure Mode 2: Heading & Topic Mutation (`HEADING_RENDER_GAP`)
* **Mechanism**: The static HTML contains no `<h1>` or a placeholder (e.g., `<h1>Loading...</h1>` or `<title>React App</title>`), while client JavaScript replaces it with the real topic heading upon mount.
* **Symptom**: `<h1>` in Pass A is missing, empty, or mismatched with `<h1>` in Pass B.
* **AI Impact**: The AI crawler cannot reliably determine the primary subject of the page during initial topic classification.
* **Severity**: **HIGH**.

### Failure Mode 3: Structured Data Timing (`STRUCTURED_DATA_TIMING`)
* **Mechanism**: Schema.org JSON-LD tags are injected dynamically via `useEffect`, Google Tag Manager, or client-side JavaScript instead of being hardcoded into the initial HTML document stream.
* **Symptom**: Pass A has 0 `<script type="application/ld+json">` tags, but Pass B has 1 or more.
* **AI Impact**: Fast crawlers do not execute JavaScript just to extract entity metadata. The brand loses Knowledge Graph grounding.
* **Severity**: **HIGH**.

### Failure Mode 4: Navigation & Deep-Link Disconnect (`INTERNAL_LINK_DISCOVERY_GAP`)
* **Mechanism**: Internal links to documentation, pricing, or product categories are rendered as JavaScript event listeners (`<button onClick="...">`) or dynamically mounted menus, rather than standard HTML `<a href="...">` anchor tags.
* **Symptom**: Internal `<a href>` count in Pass A is significantly lower than Pass B.
* **AI Impact**: Crawlers cannot traverse or discover deep interior pages without a complete site render.
* **Severity**: **MEDIUM**.

---

## 3. Heuristic Decision Matrix for the Agent

When reviewing `missing_text_snippets` emitted by `check_render.py`, apply this classification:

| Missing Snippet Content | Examples | Verdict |
| :--- | :--- | :--- |
| **Product / Brand Facts** | "Garage is an open-source S3 compatible storage server..." | **FLAG (CRITICAL/HIGH)** |
| **Pricing / Plan Terms** | "$20/month per user, billed annually. Includes 10TB..." | **FLAG (HIGH)** |
| **Technical Instructions** | "Run docker run -d -p 3900:3900 garage to launch..." | **FLAG (HIGH)** |
| **Cookie / Privacy Notice** | "We use cookies to improve your experience. Accept all..." | **DISMISS (HARMLESS)** |
| **Theme / State Buttons** | "Dark Mode", "Toggle navigation", "Collapse sidebar" | **DISMISS (HARMLESS)** |
| **Dynamic Timestamps** | "Updated 5 minutes ago", "Current server time: 14:00" | **DISMISS (HARMLESS)** |
| **Shopping Cart / Profile** | "Cart: 0 items", "Sign in to account" | **DISMISS (HARMLESS)** |
