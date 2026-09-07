#!/usr/bin/env python3
"""
test_pipeline.py - Interactive Multi-Skill Brand AI-Readiness Audit Pipeline Runner

Executes the complete AI Readiness Audit pipeline across all 4 core skills in sequence:
  Step 1: AI Crawler Access Audit      (Gate 1: Crawl & Protocol Access)
  Step 2: JS Render & Parity Audit      (Gate 2: Parse & Hydration Parity)
  Step 3: Structured Data & Entity Audit(Gate 3: Entity Trust & Grounding)
  Step 4: Content Quality & Citability  (Gate 4: AI Citability & RAG Chunking)

Outputs detailed, comprehensive, self-explanatory logs in simple plain English.
Logs all visited pages, network requests, latency metrics, errors, and actionable fixes.
"""

import sys
import os
import re
import json
import time
import shutil
import tempfile
import subprocess
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(ROOT_DIR, "marketplace", "skills")

# =====================================================================
# Plain-English Explanations Registry for All Audit Findings
# =====================================================================
EXPLANATION_REGISTRY = {
    # Gate 1: Crawlability & Protocol Access
    "LLMS_TXT_MISSING": {
        "what": "The website does not have an /llms.txt or /ai.txt context manifest at its domain root.",
        "why": "AI search engines (like ChatGPT Search, Perplexity, and Claude) look for /llms.txt to instantly understand what your company does, what products you offer, and which documentation pages are official. Without it, AI crawlers must guess by parsing raw pages, which often leads to outdated or hallucinated answers about your brand.",
        "fix": "Create a clean markdown file at /llms.txt summarizing your company, core products, and links to primary documentation."
    },
    "LLMS_TXT_STUB": {
        "what": "An /llms.txt file was found, but it is nearly empty (fewer than 80 characters).",
        "why": "AI crawlers expect a substantive summary of your brand and services. An empty or stub file provides zero useful context for AI answer generation.",
        "fix": "Expand /llms.txt with a factual 2-3 paragraph overview of your brand and direct markdown links to key pages."
    },
    "AI_TXT_FOUND_NO_LLMS_TXT": {
        "what": "The site has an /ai.txt file but is missing an /llms.txt file.",
        "why": "Modern AI search engines follow the emerging /llms.txt convention. Adding /llms.txt ensures compatibility with all LLM crawlers.",
        "fix": "Create a symlink, redirect, or copy of /ai.txt at /llms.txt."
    },
    "BOT_UA_DISCRIMINATION": {
        "what": "The website's firewall (WAF/CDN) blocks AI search crawlers (like ChatGPT's OAI-SearchBot) while allowing regular desktop web browsers.",
        "why": "When users ask ChatGPT or Perplexity for brand recommendations or product specs, the AI cannot fetch your pages in real time to cite you. Your brand is completely invisible in live AI search results.",
        "fix": "Update your firewall (Cloudflare, Akamai, AWS WAF) to whitelist legitimate AI search user-agents (e.g., OAI-SearchBot, PerplexityBot)."
    },
    "HTTP_ACCESS_FORBIDDEN": {
        "what": "The server returned HTTP 401 or 403 Forbidden to automated crawlers.",
        "why": "Automated AI crawlers are rejected at the edge or origin server, preventing them from accessing public content.",
        "fix": "Review web server and CDN access control lists to ensure public marketing and documentation pages permit automated requests."
    },
    "CONNECTION_FAILURE": {
        "what": "Unable to connect to the website host; the connection timed out or was dropped.",
        "why": "If AI bots cannot establish a network connection, no content from your domain can ever be indexed or cited.",
        "fix": "Check server uptime, DNS settings, and verify that firewall rate-limiting is not dropping automated requests."
    },
    "ORIGIN_SERVER_ERROR": {
        "what": "The web server returned an HTTP 500-series internal server error.",
        "why": "Server errors cause AI crawlers to back off or mark the site as unstable, reducing crawl frequency.",
        "fix": "Inspect origin application logs to identify and resolve internal server exceptions."
    },
    "SITE_WIDE_DISALLOW": {
        "what": "The robots.txt file contains 'Disallow: /' for all crawlers (User-agent: *).",
        "why": "This instruction explicitly commands all search engines and AI bots not to crawl any page on your website.",
        "fix": "Remove 'Disallow: /' from robots.txt, or replace it with specific path restrictions for sensitive areas only."
    },
    "AI_SEARCH_BOT_BLOCKED_COMPLETELY": {
        "what": "A live AI search crawler (like ChatGPT Search or Perplexity) is explicitly blocked in robots.txt.",
        "why": "Users asking questions in ChatGPT Search or Perplexity will receive answers that cite your competitors instead of your official website.",
        "fix": "Remove the Disallow rule for that bot in robots.txt to allow real-time live search citation."
    },
    "AI_SEARCH_BOT_KEY_PATH_BLOCKED": {
        "what": "A critical content path (such as /docs, /products, /pricing, or /blog) is blocked for AI search bots in robots.txt.",
        "why": "AI search engines cannot verify pricing, feature lists, or technical documentation, leading to inaccurate answers.",
        "fix": "Allow access to public documentation, pricing, and product paths in robots.txt."
    },
    "AI_TRAINING_BOT_BLOCKED": {
        "what": "An AI model training scraper (e.g., GPTBot or CCBot) is disallowed in robots.txt.",
        "why": "This is an informational setting. It prevents bulk pre-training scraping while still allowing live search citations if live search bots are permitted.",
        "fix": "Keep this rule if you want copyright protection against model training; remove it if you want future foundation models to pre-train on your public documentation."
    },
    "SITEMAP_MISSING": {
        "what": "No XML sitemap was found at /sitemap.xml or declared in robots.txt.",
        "why": "AI crawlers rely on sitemaps to discover new and updated pages. Without a sitemap, interior pages remain undiscovered.",
        "fix": "Generate an XML sitemap at /sitemap.xml and add a 'Sitemap: https://yourdomain.com/sitemap.xml' directive to robots.txt."
    },
    "SITEMAP_EMPTY": {
        "what": "The XML sitemap exists and was fetched successfully, but it contains zero page URLs.",
        "why": "An empty sitemap provides no URLs for AI crawlers to index.",
        "fix": "Populate your sitemap.xml with canonical URLs for all public pages on your website."
    },
    "SITEMAP_MALFORMED": {
        "what": "The XML sitemap contains syntax errors or invalid formatting that prevented parsing.",
        "why": "Automated crawlers abort processing when encountering invalid XML, stopping page discovery in its tracks.",
        "fix": "Validate sitemap.xml against the standard XML sitemap protocol schema and fix any unescaped characters or unclosed tags."
    },
    "TLS_CERT_INVALID": {
        "what": "The SSL/TLS certificate failed cryptographic verification.",
        "why": "Modern AI search crawlers enforce strict TLS validation. A broken certificate aborts the crawl immediately.",
        "fix": "Install a valid, trusted SSL/TLS certificate from a recognized certificate authority (e.g., Let's Encrypt)."
    },
    "TLS_CERT_EXPIRED": {
        "what": "The SSL/TLS certificate on the server is expired.",
        "why": "AI crawlers refuse to establish connections with servers hosting expired certificates.",
        "fix": "Renew and install your SSL/TLS certificate immediately."
    },
    "TLS_HOSTNAME_MISMATCH": {
        "what": "The SSL/TLS certificate domain name does not match the website hostname.",
        "why": "Hostname mismatches trigger security warnings that cause automated bots to drop the connection.",
        "fix": "Reissue the certificate to include all relevant subdomains in the Subject Alternative Name (SAN) list."
    },
    "HOST_NOINDEX_HEADER": {
        "what": "The HTTP response header contains 'X-Robots-Tag: noindex'.",
        "why": "This header instructs all search and AI engines never to index this page, even if robots.txt allows crawling.",
        "fix": "Remove the 'X-Robots-Tag: noindex' header from your web server or CDN configuration on public pages."
    },
    "HTML_NOINDEX_HOMEPAGE": {
        "what": "The homepage HTML contains a `<meta name='robots' content='noindex'>` tag.",
        "why": "This completely prevents search engines and AI models from including your homepage in search indexes.",
        "fix": "Remove the 'noindex' meta tag from your homepage template."
    },
    "REDIRECT_LOOP": {
        "what": "A circular redirect loop was detected when fetching the website.",
        "why": "Crawlers will abort after multiple hops, failing to retrieve any content.",
        "fix": "Fix URL rewriting and redirect rules in your server configuration."
    },
    "REDIRECT_CHAIN_LONG": {
        "what": "The URL required 3 or more redirects before reaching the final destination page.",
        "why": "Long redirect chains waste crawl budget and introduce latency for live citation crawlers.",
        "fix": "Update internal links and canonical tags to point directly to the final destination URL."
    },
    "DEEPLY_BURIED_IMPORTANT_PAGE": {
        "what": "A critical page (documentation, pricing, product, or trust/about) is buried 4 or more levels deep in the URL path hierarchy.",
        "why": "AI search crawlers (such as OAI-SearchBot) allocate limited crawl budgets to each domain and prioritize shallow paths. Pages buried 4+ levels deep (e.g., /a/b/c/d/page) receive significantly lower crawl frequency, resulting in missing or delayed citations for important features and pricing.",
        "fix": "Flatten URL structure to depth 2 or 3 (e.g., '/docs/topic' or '/products/name') to ensure rapid discovery and high citation priority by AI engines."
    },

    # Gate 2: Parse & Hydration Parity
    "EMPTY_SHELL_SPA": {
        "what": "The raw HTML is an empty shell with 0 sentences; all content is rendered via client JavaScript.",
        "why": "Fast AI search bots inspect raw HTML without running a full browser. Because no content is delivered in raw HTML, the bot sees a completely blank page and cannot cite your brand.",
        "fix": "Pre-render primary page content using Server-Side Rendering (Next.js/Nuxt) or Static Site Generation (SSG) so raw HTML contains full visible text."
    },
    "CORE_CONTENT_RENDER_GAP": {
        "what": "Over 40% of the page's visible text is absent from raw HTML and only renders after JavaScript execution.",
        "why": "Fast AI search bots see a significantly degraded version of your page. Crucial product descriptions, specifications, or guides remain completely invisible.",
        "fix": "Render core documentation, product specifications, and descriptive text server-side in static HTML."
    },
    "PARTIAL_CONTENT_RENDER_GAP": {
        "what": "Substantive text sections present in the browser DOM are completely missing from initial raw HTML.",
        "why": "AI search bots parsing raw HTML miss these specific sections, resulting in incomplete answers and missed citation opportunities for user queries.",
        "fix": "Render these substantive content sections server-side in static HTML so AI bots index the full text without executing JavaScript."
    },
    "SENTENCE_PARITY_LOW": {
        "what": "A significant percentage of the page's text is missing from raw HTML and only appears after client-side JavaScript executes.",
        "why": "Many AI crawlers fetch raw HTML without running a full browser. Content locked behind JavaScript is invisible to them.",
        "fix": "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) so all key text is present in the initial HTML."
    },
    "INTERNAL_LINK_DISCOVERY_GAP": {
        "what": "Multiple internal navigation links only exist after client-side JavaScript runs.",
        "why": "AI search spiders discover interior pages by following standard HTML `<a href='...'>` tags. Links created via JavaScript click handlers remain undiscovered.",
        "fix": "Use standard HTML `<a href='...'>` anchor tags in all navigation bars, footers, and content menus."
    },
    "HEADING_RENDER_GAP": {
        "what": "The primary `<h1>` heading is injected dynamically via client-side JavaScript instead of being in the raw HTML.",
        "why": "AI crawlers look at the `<h1>` tag in raw HTML to instantly understand the topic of the page. Without it, the AI may misclassify your content.",
        "fix": "Render the primary `<h1>` tag server-side in the initial static HTML response."
    },
    "STRUCTURED_DATA_TIMING": {
        "what": "JSON-LD structured data is injected by client-side JavaScript instead of being delivered in raw HTML.",
        "why": "Fast AI search bots parse Schema.org metadata directly from raw HTML. If schema is injected via JS, the bot misses your entity data completely.",
        "fix": "Embed your `<script type='application/ld+json'>` tags directly in server-rendered HTML."
    },
    "RENDER_LATENCY_EXCEEDED": {
        "what": "Headless browser rendering took longer than 4.5 seconds to stabilize.",
        "why": "Real-time AI search bots operate on strict 3-5 second timeouts. Pages that take longer to hydrate will be aborted before content is read.",
        "fix": "Optimize JavaScript bundle sizes, eliminate heavy blocking third-party scripts, or implement server-side pre-rendering."
    },

    # Gate 3: Entity Trust & Grounding
    "ROOT_ENTITY_MISSING": {
        "what": "No Organization, Corporation, or Brand Schema.org structured data was found on the homepage.",
        "why": "Without an explicit Organization schema, AI models cannot reliably connect your website to your brand name in their Knowledge Graph, increasing the risk of brand confusion or hallucinated competitors.",
        "fix": "Add a JSON-LD `<script type='application/ld+json'>` block defining an Organization with name, url, and logo."
    },
    "SAMEAS_AUTHORITY_GAP": {
        "what": "Your Organization schema does not include `sameAs` links to recognized authoritative entity registries.",
        "why": "AI systems (ChatGPT, Perplexity, Claude) cross-reference Wikidata, Wikipedia, LinkedIn, Crunchbase, and GitHub to verify that your company is real and authoritative. Missing sameAs links mean lower trust and fewer citations.",
        "fix": "Add official profile links (e.g., Wikidata, Wikipedia, LinkedIn, GitHub, Crunchbase) to the `sameAs` array in your Organization schema."
    },
    "ENTITY_SAMEAS_MISSING": {
        "what": "Declared root entity lacks authoritative sameAs disambiguation links.",
        "why": "Without sameAs links pointing to authoritative graphs (Wikidata, Wikipedia, LinkedIn, GitHub), AI models cannot distinguish your brand from similarly named entities.",
        "fix": "Add 'sameAs' links pointing to your official GitHub repo, package registry (npm/PyPI/Crates), LinkedIn page, or Wikidata entry."
    },
    "ENTITY_SAMEAS_WEAK": {
        "what": "Declared sameAs links do not reference recognized authority registries.",
        "why": "AI knowledge graph consolidators prioritize links to high-authority entity registries. Generic social profiles or blogs provide weak disambiguation signals.",
        "fix": "Include links to high-authority registries such as GitHub, LinkedIn, Crunchbase, or Wikidata in your sameAs array."
    },
    "SCHEMA_DESCRIPTION_MISSING": {
        "what": "One or more Schema.org entities on the page lack a 'description' property.",
        "why": "AI summarizers and answer engines use schema descriptions for atomic entity synthesis. Missing descriptions force AI models to guess or scrape less reliable text.",
        "fix": "Add a concise, factual 1-2 sentence description explaining what the entity is, who uses it, and its core capabilities."
    },
    "SCHEMA_DESCRIPTION_TOO_SHORT": {
        "what": "Schema entity description is extremely brief (under 25 characters).",
        "why": "Very short descriptions provide insufficient semantic context for AI vector embeddings and knowledge graph ingestion.",
        "fix": "Expand description to 60-150 characters with concrete functional capabilities and domain terms."
    },
    "SCHEMA_DESCRIPTION_VACUOUS": {
        "what": "Schema description contains generic marketing fluff and corporate buzzwords instead of factual capabilities.",
        "why": "Buzzwords like 'world-class, leading provider of next-generation solutions' yield zero atomic facts for AI RAG retrieval and are discounted by summarization models.",
        "fix": "Replace buzzwords with concrete facts: specific protocols supported, architecture, target users, and key use cases."
    },
    "SCHEMA_PRICE_CONTRADICTION": {
        "what": "Structured data price contradicts the visible price displayed on the web page.",
        "why": "When JSON-LD prices disagree with on-page text, AI engines detect a factual contradiction and distrust the site, resulting in refusal to quote pricing or quoting obsolete rates.",
        "fix": "Synchronize the JSON-LD offers.price with the actual visible pricing displayed on the page."
    },
    "SCHEMA_AVAILABILITY_CONTRADICTION": {
        "what": "Structured data availability (e.g. InStock) contradicts visible on-page stock status (e.g. Out of stock).",
        "why": "AI search assistants that check live product availability will quote incorrect stock information to buyers, degrading trust.",
        "fix": "Ensure JSON-LD offers.availability accurately mirrors visible product inventory state."
    },
    "SCHEMA_VERSION_STALE": {
        "what": "Structured data softwareVersion is older than the release version prominently featured on the page.",
        "why": "AI search engines reading structured data will report outdated version numbers to developers and prospective users.",
        "fix": "Update JSON-LD softwareVersion property during deployment to match current release notes."
    },
    "SCHEMA_DATE_MODIFIED_MISSING": {
        "what": "Article or documentation schema lacks a dateModified timestamp.",
        "why": "Generative AI engines deprioritize undated articles for freshness-sensitive technical queries.",
        "fix": "Add an ISO-8601 'dateModified' timestamp (e.g. '2026-01-15T00:00:00Z') to article schema."
    },
    "SCHEMA_SYNTAX_INVALID": {
        "what": "The JSON-LD code on the page contains invalid JSON syntax (e.g., unescaped quotes or trailing commas).",
        "why": "When JSON syntax is broken, parsers discard the entire structured data block, blinding search engines to your schema.",
        "fix": "Validate and fix the JSON-LD syntax using standard RFC 8259 JSON format."
    },

    # Gate 4: AI Citability & RAG Chunking
    "RAG_CHUNK_ORPHAN_PRONOUN": {
        "what": "A content section begins with an ambiguous pronoun (like 'It', 'They', 'This') instead of naming the actual product or subject.",
        "why": "AI search engines split web pages into standalone chunks for retrieval. When an AI retrieves this chunk alone, it cannot tell what 'It' refers to and refuses to cite it as an authoritative answer.",
        "fix": "Replace opening pronouns with explicit nouns (e.g., change 'It delivers 20 hours of battery...' to 'The MacBook Air delivers 20 hours of battery...')."
    },
    "RAG_HEADING_LOW_ENTROPY": {
        "what": "A content section uses a generic, low-information heading (e.g., 'Overview', 'Features', 'Details').",
        "why": "AI search engines match user questions directly against headings. A generic heading like 'Features' has very low search relevance compared to a descriptive heading like 'Nike Air Zoom Cushioning Features'.",
        "fix": "Make headings descriptive by including specific brand, product, and capability keywords."
    },
    "RAG_CHUNK_LOW_ENTROPY_HEADING": {
        "what": "A content section uses a generic, low-information heading (e.g., 'Overview', 'Features', 'Details').",
        "why": "AI search engines match user questions directly against headings. Generic headings provide zero search-intent tokens when prepended to chunk embeddings.",
        "fix": "Rename heading to include specific topic nouns (e.g., replace 'Overview' with 'System Architecture Overview')."
    },
    "BLUF_QUESTION_ANSWER_DEFICIT": {
        "what": "A section with a question heading does not deliver a direct answer in its opening sentence.",
        "why": "AI search engines expect Bottom-Line-Up-Front (BLUF). If the opening sentence deflects ('To answer this, let's explore...') rather than giving the answer, AI engines skip quoting it.",
        "fix": "Adopt BLUF: formulate the direct answer to the heading's question in the very first sentence so AI search engines can quote it immediately."
    },
    "BLUF_FLUFF_PREAMBLE": {
        "what": "Article opening contains generic throat-clearing fluff instead of a direct answer.",
        "why": "Opening with cliches like 'In today's fast-paced digital world...' dilutes semantic information and triggers AI search summarizers to skip the preamble.",
        "fix": "Remove introductory digital cliches and provide a direct declarative definition in the first sentence."
    },
    "RAG_BLUF_DELAY": {
        "what": "The direct answer to the section heading is delayed or buried under marketing fluff.",
        "why": "Generative AI engines favor 'Bottom Line Up Front' (BLUF) formatting. If the direct answer isn't in the first sentence, the AI is much more likely to quote a competitor who answers immediately.",
        "fix": "Place the direct, factual answer in the very first sentence under the heading before elaborating."
    },
    "RAG_SECTION_CONTENT_FLOODING": {
        "what": "Section contains large continuous prose without subheadings, lists, or tables.",
        "why": "Long continuous blocks of text trigger 'Lost in the Middle' attention degradation in LLM retrieval. AI chunkers struggle to isolate atomic facts.",
        "fix": "Break this section into self-contained 40-80 word paragraphs and introduce subheadings (<h3>) or bulleted lists."
    },
    "CONTENT_LOCK_IMAGE_TRAP": {
        "what": "Substantive data (pricing, comparison, benchmarks) appears locked inside an image asset.",
        "why": "AI search crawlers cannot reliably extract or cite data embedded inside raster images (PNG/JPG).",
        "fix": "Provide an HTML <table> or structured text equivalent alongside the image so AI search engines can ingest the data."
    },
    "CITABILITY_CIRCULAR_CITATION": {
        "what": "Article relies entirely on circular self-citations with zero external reference links.",
        "why": "LLM verification algorithms score claims higher when backed by outbound citations to authoritative external primary sources.",
        "fix": "Integrate outbound citations to authoritative external sources (standards, benchmarks, institutional studies) to establish a verifiable credibility chain."
    },
    "CITABILITY_STATISTICAL_SUGGESTION": {
        "what": "Content lacks quantitative metrics, benchmark statistics, or verifiable numbers.",
        "why": "The Princeton GEO study proved that adding verifiable statistics increases AI citation probability by +37%.",
        "fix": "Integrate quantitative metrics, benchmark data, or concrete performance statistics into substantive articles."
    },
    "STRUCTURE_TABULAR_SUGGESTION": {
        "what": "Comparative pricing or feature lists are formatted as narrative prose rather than a structured HTML table.",
        "why": "LLMs extract and quote structured HTML <table> elements at a significantly higher rate than narrative text.",
        "fix": "Structure plan comparisons into an HTML <table> with clear rows and columns for plan names, prices, and features."
    },
    "PAGE_FETCH_ERROR": {
        "what": "An HTTP or network error occurred when attempting to fetch this page.",
        "why": "If an AI crawler encounters a connection failure, timeout, or HTTP error on a page, it cannot extract content or structured data from that URL.",
        "fix": "Check server availability, DNS resolution, and firewall rules to ensure the page responds reliably."
    },
    "TEMPORAL_ANCHORING_SUGGESTION": {
        "what": "Content mentions older years without recent temporal anchors (2025/2026 or 'Last Updated' markers).",
        "why": "AI models prioritize fresh, current information. Without temporal markers, content may be deemed obsolete and skipped.",
        "fix": "Add explicit freshness markers (e.g., 'Updated for 2026' or 'As of Q1 2026') to signal ongoing accuracy."
    }
}


def print_banner(text, char="="):
    line = char * max(70, len(text) + 4)
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")
    sys.stdout.flush()


def print_step_header(step_num, total_steps, title, gate_name, purpose_desc):
    line = "=" * 76
    print(f"\n{line}")
    print(f"  STEP {step_num}/{total_steps}: {title.upper()}")
    print(f"  {gate_name}")
    print(f"{line}")
    print(f"  PURPOSE & AI IMPACT:")
    # Word wrap purpose description nicely
    words = purpose_desc.split()
    current_line = "  "
    for w in words:
        if len(current_line) + len(w) + 1 > 74:
            print(current_line)
            current_line = "  " + w
        else:
            current_line += (" " if current_line != "  " else "") + w
    if current_line.strip():
        print(current_line)
    print("-" * 76)
    sys.stdout.flush()


def format_url(raw_url):
    raw_url = raw_url.strip()
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = "https://" + raw_url
    return raw_url


def run_command_stream(cmd, step_name):
    """Executes command and returns parsed JSON if stdout is JSON, or raw output."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        elapsed = time.time() - t0

        if proc.returncode != 0:
            print(f"\n[ERROR] {step_name} failed with exit code {proc.returncode} in {elapsed:.2f}s:")
            print(proc.stderr.strip() or proc.stdout.strip())
            return None, elapsed

        out_text = proc.stdout.strip()
        data = None
        try:
            data = json.loads(out_text)
        except json.JSONDecodeError:
            first_brace = out_text.find("{")
            last_brace = out_text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(out_text[first_brace:last_brace + 1])
                except Exception:
                    pass

        return data if data else out_text, elapsed

    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n[ERROR] Execution error in {step_name}: {str(e)}")
        return None, elapsed


def print_finding_card(f, index):
    code = f.get("code", "UNKNOWN")
    title = f.get("title", "Untitled Finding")
    severity = f.get("severity", "medium").upper()
    url = f.get("url") or f.get("evidence_url") or ""
    evidence = f.get("evidence", "No technical evidence provided.")
    suggested = f.get("suggested_action", {})
    action_summary = suggested.get("summary") if isinstance(suggested, dict) else str(suggested)

    # Get plain English explanations
    expl = EXPLANATION_REGISTRY.get(code, {})
    what = expl.get("what", title)
    why = expl.get("why", "Affects how AI models perceive and cite this website.")
    fix = expl.get("fix", action_summary)

    sev_badge = f"[{severity}]"
    print(f"\n  +-- ISSUE #{index}: {sev_badge} {title}")
    if url:
        print(f"  |   Affected URL:  {url}")
    print(f"  |")
    print(f"  |   * What is this?")
    print(f"  |     {what}")
    print(f"  |")
    print(f"  |   * Why does this matter for AI search?")
    print(f"  |     {why}")
    print(f"  |")
    print(f"  |   * Technical Evidence & Real Content:")
    for line in str(evidence).splitlines():
        print(f"  |     {line}")
    print(f"  |")
    print(f"  |   * How to fix it:")
    print(f"  |     {fix}")
    print(f"  +-------------------------------------------------------------------")


# =====================================================================
# Step Loggers: Beautiful, Plain-English, Comprehensive
# =====================================================================

def log_skill_1_results(s1_data, elapsed_time):
    """Step 1: AI Crawler Access Audit Logger"""
    print_step_header(
        1, 4,
        "AI Crawler Access Audit",
        "Gate 1: Crawlability & Network Protocol Access",
        "Tests whether AI search bots (ChatGPT Search, Perplexity, ClaudeBot) can physically "
        "connect to your site, navigate sitemaps, and access pages without being blocked "
        "by firewalls, expired SSL certificates, or restrictive robots.txt rules."
    )

    if not isinstance(s1_data, dict):
        print("  [!] Skill 1 did not return structured report data.")
        return

    telemetry = s1_data.get("audit_telemetry", {})
    sampled = s1_data.get("sampled_pages", {})
    findings = s1_data.get("findings", [])
    summary = s1_data.get("summary", {})

    # 1. Pages Visited & Network Log (Neat table)
    pages_visited = telemetry.get("pages_visited", [])
    print("\n  [PAGES VISITED & NETWORK LOG]")
    if pages_visited:
        print(f"  Total Requests Made: {len(pages_visited)}")
        print(f"  {'#':<3} {'Status':<10} {'Latency':<9} {'Depth':<8} {'Purpose / Resource':<35} {'URL'}")
        print(f"  {'-'*3} {'-'*10} {'-'*9} {'-'*8} {'-'*35} {'-'*45}")
        for idx, req in enumerate(pages_visited, 1):
            status = req.get("status", 0)
            status_str = f"HTTP {status}" if status else "FAILED"
            time_str = f"{req.get('elapsed_ms', 0):.0f}ms"
            d = req.get("depth", 0)
            depth_str = f"Depth {d}"
            purpose = req.get("purpose", "")
            if len(purpose) > 33:
                purpose = purpose[:30] + "..."
            url = req.get("url", "")
            err = req.get("error")
            err_suffix = f" [ERR: {err}]" if err else ""
            print(f"  {idx:<3} {status_str:<10} {time_str:<9} {depth_str:<8} {purpose:<35} {url}{err_suffix}")
    else:
        print(f"   • Target Root: {sampled.get('homepage', 'Unknown')}")

    # 2. Key Infrastructure Telemetry
    print("\n  [NETWORK INFRASTRUCTURE TELEMETRY]")
    tls = telemetry.get("tls_result")
    if tls:
        tls_status = tls.get("status", "unknown")
        if tls_status == "valid":
            days = tls.get("days_remaining", 0)
            issuer = tls.get("issuer", "Unknown CA")
            print(f"   • SSL/TLS Certificate: Valid (Issued by {issuer} | Expires in {days} days)")
        else:
            print(f"   • SSL/TLS Certificate: FAILED ({tls.get('error', 'Verification error')})")
    else:
        print("   • SSL/TLS Certificate: Not checked (HTTP target)")

    robots_status = telemetry.get("robots_txt_status", 0)
    robots_str = f"Accessible (HTTP {robots_status})" if robots_status == 200 else f"Missing / Unreachable (HTTP {robots_status})"
    print(f"   • Robots Directives:   {robots_str}")

    llms_status = telemetry.get("llms_txt_status", 0)
    ai_status = telemetry.get("ai_txt_status", 0)
    if llms_status == 200:
        manifest_str = "Published (/llms.txt found)"
    elif ai_status == 200:
        manifest_str = "Published (/ai.txt found)"
    else:
        manifest_str = f"Missing (/llms.txt: HTTP {llms_status}, /ai.txt: HTTP {ai_status})"
    print(f"   • AI Context Manifest: {manifest_str}")

    sitemap_target = telemetry.get("sitemap_target")
    total_discovered = sampled.get("total_discovered", 0)
    if total_discovered > 0:
        print(f"   • XML Sitemap:         Verified ({sitemap_target} -> {total_discovered:,} page URLs discovered)")
    else:
        candidates = telemetry.get("candidate_sitemaps_tested", [])
        print(f"   • XML Sitemap:         0 page URLs extracted (Tested: {', '.join(candidates[:2])})")

    # 3. Curated Sample Pages Selected for Downstream Audits
    curated_details = sampled.get("curated_sample_details", [])
    curated = sampled.get("curated_sample", [])
    if curated_details:
        print(f"\n  [CURATED SAMPLE PAGES FOR DEEP AUDIT ({len(curated_details)} pages across depths 0-3+)]")
        print(f"  {'#':<3} {'Archetype':<16} {'Depth':<8} {'URL'}")
        print(f"  {'-'*3} {'-'*16} {'-'*8} {'-'*55}")
        for idx, item in enumerate(curated_details, 1):
            arch = item.get("archetype", "general").replace("_", " ").title()
            d = item.get("depth", 0)
            u = item.get("url", "")
            print(f"  {idx:<3} {arch:<16} Depth {d:<4} {u}")
    elif curated:
        print(f"\n  [CURATED SAMPLE PAGES FOR DEEP AUDIT ({len(curated)} pages)]")
        for idx, u in enumerate(curated, 1):
            print(f"   {idx}. {u}")

    # 4. Detailed Findings
    print(f"\n  [GATE 1 ISSUES DETECTED: {len(findings)} ({summary.get('critical', 0)} Critical, {summary.get('high', 0)} High, {summary.get('medium', 0)} Medium, {summary.get('low', 0)} Low)]")
    if not findings:
        print("   [ALL CLEAR] No crawlability blockers found! AI search bots have full access to discover pages.")
    else:
        for idx, f in enumerate(findings, 1):
            print_finding_card(f, idx)
    sys.stdout.flush()


def log_skill_2_results(s2_data, elapsed_time):
    """Step 2: JS Render & Parity Audit Logger"""
    print_step_header(
        2, 4,
        "JavaScript Render & Parity Audit",
        "Gate 2: Parse & Hydration Parity",
        "Compares what fast AI search bots see in raw HTML (Pass A) versus what human "
        "users see after JavaScript runs in a headless web browser (Pass B). Content that "
        "requires JavaScript to render is often invisible to AI citation engines."
    )

    if not isinstance(s2_data, dict):
        print("  [!] Skill 2 did not return structured report data.")
        return

    r_prof = s2_data.get("render_profile", {})
    findings = s2_data.get("findings", [])
    summary = s2_data.get("summary", {})
    per_page = r_prof.get("per_page_metrics", [])

    print(f"\n  [RENDERING ENGINE & AUDIT SCOPE]")
    print(f"  Browser Binary: {r_prof.get('browser_engine', 'Headless Chrome / Edge')}")
    print(f"  Pages Audited:  {r_prof.get('pages_audited', len(per_page))}")

    # Neat Tabular Summary
    print(f"\n  [PAGES AUDITED & CONTENT PARITY METRICS]")
    if per_page:
        print(f"  {'#':<3} {'Depth':<8} {'Parity':<9} {'Pass A (Raw)':<20} {'Pass B (DOM)':<20} {'URL'}")
        print(f"  {'-'*3} {'-'*8} {'-'*9} {'-'*20} {'-'*20} {'-'*45}")
        for idx, p in enumerate(per_page, 1):
            url = p.get("url", "")
            depth = p.get("depth", 0)
            m = p.get("metrics", {})
            parity = m.get("parity_pct", 0.0)
            pass_a_str = f"{m.get('sentences_pass_a', 0)} sent ({m.get('pass_a_latency_ms', 0):.0f}ms)"
            pass_b_str = f"{m.get('sentences_pass_b', 0)} sent ({m.get('pass_b_latency_ms', 0):.0f}ms)"
            print(f"  {idx:<3} Depth {depth:<4} {parity:>5.1f}%   {pass_a_str:<20} {pass_b_str:<20} {url}")

    # Detailed Content Inspection & Real Text Excerpts
    print(f"\n  [CONTENT INSPECTION & REAL TEXT COMPARISON]")
    for idx, p in enumerate(per_page, 1):
        url = p.get("url", "")
        depth = p.get("depth", 0)
        m = p.get("metrics", {})
        parity = m.get("parity_pct", 0.0)
        pass_a_lat = m.get("pass_a_latency_ms", 0)
        pass_b_lat = m.get("pass_b_latency_ms", 0)
        pass_a_st = m.get("pass_a_status", 0)
        pass_b_st = m.get("pass_b_status", 0)
        sent_a = m.get("sentences_pass_a", 0)
        sent_b = m.get("sentences_pass_b", 0)
        missing_count = m.get("missing_sentences_count", 0)
        missing_blocks = m.get("missing_content_blocks", [])

        print(f"\n  Page #{idx}: {url} (Path Depth: {depth})")
        print(f"   • Pass A (Raw HTML Bot):   HTTP {pass_a_st} in {pass_a_lat:.0f}ms | Extracted: {sent_a} sentences")
        if m.get("pass_a_excerpt"):
            print(f"     Raw Text Excerpt: \"{m['pass_a_excerpt']}...\"")
        print(f"   • Pass B (Browser DOM):    HTTP {pass_b_st} in {pass_b_lat:.0f}ms | Extracted: {sent_b} sentences")
        if m.get("pass_b_excerpt"):
            print(f"     DOM Text Excerpt: \"{m['pass_b_excerpt']}...\"")
        print(f"   • Content Parity:          {parity:.1f}%")

        if missing_blocks:
            print(f"   • [ACTUAL CONTENT MISSING FROM RAW HTML ({missing_count} sentences in {len(missing_blocks)} blocks)]:")
            for b_idx, block in enumerate(missing_blocks[:3], 1):
                clean_b = block.strip()
                if len(clean_b) > 220:
                    clean_b = clean_b[:220] + "..."
                print(f"     Block #{b_idx}: \"{clean_b}\"")
        elif missing_count > 0:
            snippets = m.get("missing_snippets_sample", [])
            print(f"   • Missing Text Sample: \"{snippets[0][:120]}...\"")
        else:
            print(f"   • Parity Status:           100% of substantive content is delivered in static HTML.")

    print(f"\n  [GATE 2 ISSUES DETECTED: {len(findings)} ({summary.get('critical', 0)} Critical, {summary.get('high', 0)} High, {summary.get('medium', 0)} Medium)]")
    if not findings:
        print("   [ALL CLEAR] Excellent! 100% content parity achieved. Fast AI bots see everything humans see.")
    else:
        for idx, f in enumerate(findings, 1):
            print_finding_card(f, idx)
    sys.stdout.flush()


def log_skill_3_results(s3_data, elapsed_time):
    """Step 3: Structured Data & Entity Grounding Audit Logger"""
    print_step_header(
        3, 4,
        "Structured Data & Entity Audit",
        "Gate 3: Entity Trust & Grounding",
        "Verifies whether search engines and AI models can unambiguously identify who your "
        "company is, what brand or products you own, and whether external authoritative "
        "registries (Wikidata, Wikipedia, LinkedIn) confirm your identity."
    )

    if not isinstance(s3_data, dict):
        print("  [!] Skill 3 did not return structured report data.")
        return

    e_prof = s3_data.get("entity_profile", {})
    findings = s3_data.get("findings", [])
    summary = s3_data.get("summary", {})

    print(f"\n  [KNOWLEDGE GRAPH & ENTITY PROFILE]")
    root_detected = e_prof.get("root_entity_detected", False)
    root_types = e_prof.get("root_entity_types", [])
    if root_detected:
        print(f"   • Root Entity:        Found ({', '.join(root_types)})")
    else:
        print(f"   • Root Entity:        MISSING (No Organization or Brand schema on homepage)")

    same_as = e_prof.get("same_as_authorities", [])
    if same_as:
        print(f"   • Verified Authorities (sameAs):")
        for auth in same_as:
            print(f"     - {auth}")
    else:
        print(f"   • Verified Authorities (sameAs): None found (Lacks Wikidata, Wikipedia, or LinkedIn links)")

    cov = e_prof.get("schema_coverage_pct", 0.0)
    with_schema = e_prof.get("pages_with_schema", 0)
    audited = e_prof.get("pages_audited", 0)
    print(f"   • Schema Coverage:    {cov:.1f}% ({with_schema}/{audited} audited pages contain structured data)")

    # Neat Tabular Display of All Visited Pages
    print(f"\n  [PAGES AUDITED FOR STRUCTURED DATA]")
    pages = e_prof.get("pages", [])
    if pages:
        print(f"  {'#':<3} {'Depth':<8} {'Status':<10} {'Schemas Detected':<35} {'URL'}")
        print(f"  {'-'*3} {'-'*8} {'-'*10} {'-'*35} {'-'*45}")
        for idx, p in enumerate(pages, 1):
            url = p.get("url", "")
            depth = p.get("depth", 0)
            st = p.get("status", 200)
            st_str = f"HTTP {st}" if st else "FAILED"
            schemas = p.get("schemas_found", [])
            schema_str = ", ".join(schemas) if schemas else "None"
            if len(schema_str) > 33:
                schema_str = schema_str[:30] + "..."
            print(f"  {idx:<3} Depth {depth:<4} {st_str:<10} {schema_str:<35} {url}")
    else:
        print(f"   • Audited {audited} pages across the website.")

    print(f"\n  [GATE 3 ISSUES DETECTED: {len(findings)} ({summary.get('critical', 0)} Critical, {summary.get('high', 0)} High, {summary.get('medium', 0)} Medium, {summary.get('low', 0)} Low)]")
    if not findings:
        if root_detected and with_schema > 0:
            print("   [ALL CLEAR] Brand is fully grounded in the Knowledge Graph with valid structured data!")
        elif not root_detected:
            print("   [NOTE] No schema syntax errors found, but no root Organization or Brand entity was detected.")
        else:
            print("   [ALL CLEAR] Valid structured data verified on audited pages.")
    else:
        for idx, f in enumerate(findings, 1):
            print_finding_card(f, idx)
    sys.stdout.flush()


def log_skill_4_results(s4_data, elapsed_time):
    """Step 4: Content Quality & Citability Audit Logger"""
    print_step_header(
        4, 4,
        "Content Quality & AI Citability Audit",
        "Gate 4: AI Citability & RAG Chunking",
        "Evaluates whether your page content is written and organized so generative AI "
        "search engines (ChatGPT, Perplexity, Gemini) can parse sections into self-contained "
        "chunks and quote them as authoritative direct answers to user questions."
    )

    if not isinstance(s4_data, dict):
        print("  [!] Skill 4 did not return structured report data.")
        return

    c_prof = s4_data.get("content_profile", {})
    findings = s4_data.get("findings", [])
    summary = s4_data.get("summary", {})

    print(f"\n  [CONTENT QUALITY & RAG CHUNK METRICS]")
    print(f"   • Pages Audited:           {c_prof.get('pages_audited', 0)}")
    print(f"   • Total Sections Audited:  {c_prof.get('total_sections_audited', 0)}")
    print(f"   • Total Words Audited:     {c_prof.get('total_words_audited', 0):,}")
    auto_ratio = c_prof.get("autonomous_chunk_ratio_pct", 100.0)
    print(f"   • Autonomous Chunk Ratio:  {auto_ratio:.1f}% (Sections that can stand alone as direct AI answers)")

    # Neat Tabular Display of All Audited Pages
    print(f"\n  [PAGES AUDITED & ARCHETYPE BREAKDOWN]")
    pages = c_prof.get("pages", [])
    if pages:
        print(f"  {'#':<3} {'Depth':<8} {'Archetype':<16} {'Sections':<10} {'Words':<10} {'URL'}")
        print(f"  {'-'*3} {'-'*8} {'-'*16} {'-'*10} {'-'*10} {'-'*45}")
        for idx, p in enumerate(pages, 1):
            url = p.get("url", "")
            depth = p.get("depth", 0)
            arch = p.get("archetype", "general").replace("_", " ").title()
            sc = p.get("sections_count", 0)
            wc = p.get("word_count", 0)
            print(f"  {idx:<3} Depth {depth:<4} {arch:<16} {sc:<10} {wc:<10,} {url}")

    print(f"\n  [AUDITED CONTENT DETAILS & HEADING STRUCTURE]")
    for idx, p in enumerate(pages, 1):
        url = p.get("url", "")
        depth = p.get("depth", 0)
        arch = p.get("archetype", "general").replace("_", " ").title()
        wc = p.get("word_count", 0)
        sc = p.get("sections_count", 0)
        headings = p.get("headings", [])
        print(f"\n   • Page #{idx}: {url} (Path Depth: {depth}, {arch})")
        print(f"     Content Volume: {wc:,} words across {sc} sections")
        if headings:
            preview = ", ".join([f"'{h}'" for h in headings[:4]])
            extra = f" (+{len(headings)-4} more)" if len(headings) > 4 else ""
            print(f"     Key Headings:   {preview}{extra}")

    print(f"\n  [GATE 4 ISSUES DETECTED: {len(findings)} ({summary.get('critical', 0)} Critical, {summary.get('high', 0)} High, {summary.get('medium', 0)} Medium, {summary.get('info', 0)} Info)]")
    if not findings:
        if c_prof.get("total_words_audited", 0) > 0:
            print("   [ALL CLEAR] Content is highly autonomous, informative, and optimized for AI citation!")
        else:
            print("   [NOTE] No content could be audited because pages could not be fetched.")
    else:
        for idx, f in enumerate(findings, 1):
            print_finding_card(f, idx)
    sys.stdout.flush()


def log_pipeline_scorecard(pipeline_results, total_time, domain, report_file):
    """Executive Scorecard & Causal Chain Assessment"""
    print_banner(f"FINAL AUDIT SCORECARD - {domain.upper()}", "=")

    # Count findings and deduplicate repeated fetch errors on identical URLs
    seen_dead_urls = set()
    total_critical = 0
    total_high = 0
    total_medium = 0
    total_low = 0

    for skill_key, s_data in pipeline_results.items():
        if isinstance(s_data, dict):
            for f in s_data.get("findings", []):
                sev = f.get("severity", "").upper()
                code = f.get("code", "")
                url = f.get("url") or f.get("evidence_url") or ""
                if "FETCH" in code or "PAGE_FETCH" in code or "RAW_FETCH" in code:
                    if url and url in seen_dead_urls:
                        continue
                    if url:
                        seen_dead_urls.add(url)
                if sev == "CRITICAL":
                    total_critical += 1
                elif sev == "HIGH":
                    total_high += 1
                elif sev == "MEDIUM":
                    total_medium += 1
                else:
                    total_low += 1

    total_findings = total_critical + total_high + total_medium + total_low

    # Calculate overall AI Readiness Grade (0 - 100)
    deductions = (total_critical * 25) + (total_high * 10) + (total_medium * 4) + (total_low * 1)
    score = max(0, min(100, 100 - deductions))

    if score >= 90:
        grade = "A+ (Leader in AI Readiness)"
    elif score >= 80:
        grade = "A  (Strong AI Visibility)"
    elif score >= 70:
        grade = "B  (Good - Has Optimization Gaps)"
    elif score >= 55:
        grade = "C  (Fair - Blockers Need Attention)"
    elif score >= 40:
        grade = "D  (Poor - Significant AI Crawl/Grounding Issues)"
    else:
        grade = "F  (Failing - Blocked from AI Search)"

    print(f"  Target Domain:         {domain}")
    print(f"  Total Audit Runtime:   {total_time:.2f} seconds")
    print(f"  AI-Readiness Score:    {score}/100 -> Grade: {grade}")
    print(f"  Total Issues Logged:   {total_findings} ({total_critical} Critical, {total_high} High, {total_medium} Medium, {total_low} Low/Info)")

    # Evaluate Causal Chain Gates
    g1_findings = pipeline_results.get('skill_1', {}).get('findings', [])
    g2_findings = pipeline_results.get('skill_2', {}).get('findings', [])
    g3_findings = pipeline_results.get('skill_3', {}).get('findings', [])
    g4_findings = pipeline_results.get('skill_4', {}).get('findings', [])

    g1_blocked = any(f.get('severity', '').upper() == 'CRITICAL' for f in g1_findings)
    g1_warn = any(f.get('severity', '').upper() == 'HIGH' for f in g1_findings)
    g1_status = "[FAIL] BLOCKED (Firewall or Protocol Failure)" if g1_blocked else "[WARN] WARNINGS" if g1_warn else "[PASS] CLEAR (Accessible to AI bots)"

    g2_spa_blocked = any(f.get('code') == 'EMPTY_SHELL_SPA' for f in g2_findings)
    g2_blocked = any(f.get('severity', '').upper() == 'CRITICAL' for f in g2_findings)
    g2_warn = any(f.get('severity', '').upper() == 'HIGH' for f in g2_findings)
    if g1_blocked:
        g2_status = "[BLOCKED] UNREACHABLE (Gate 1 failed)"
    elif g2_spa_blocked:
        g2_status = "[FAIL] BLOCKED (0% content visible without JS)"
    elif g2_blocked:
        g2_status = "[FAIL] BLOCKED (Root content inaccessible)"
    elif g2_warn:
        g2_status = "[WARN] GAPS (Partial fetch failure on interior page)"
    else:
        g2_status = "[PASS] CLEAR (Full static content parity)"

    # Gate 3 Status
    if "skill_3" in pipeline_results and isinstance(pipeline_results["skill_3"], dict):
        g3_has_crit = any(f.get('severity', '').upper() == 'CRITICAL' for f in g3_findings)
        g3_has_high = any(f.get('severity', '').upper() == 'HIGH' for f in g3_findings)
        g3_root = pipeline_results.get('skill_3', {}).get('entity_profile', {}).get('root_entity_detected', False)
        if g3_has_crit:
            g3_status = "[FAIL] BLOCKED (Root schema or protocol failure)"
        elif g3_has_high or not g3_root:
            g3_status = "[WARN] UNGROUNDED (Missing Organization/sameAs or Page Gaps)"
        else:
            g3_status = "[PASS] GROUNDED (Valid Knowledge Graph schema)"
    elif g1_blocked:
        g3_status = "[BLOCKED] UNTESTED (Gate 1 failure)"
    else:
        g3_status = "[WARN] NOT RUN"

    # Gate 4 Status
    if "skill_4" in pipeline_results and isinstance(pipeline_results["skill_4"], dict):
        g4_words = pipeline_results.get('skill_4', {}).get('content_profile', {}).get('total_words_audited', 0)
        g4_has_issues = any(f.get('severity', '').upper() in ('HIGH', 'MEDIUM') for f in g4_findings)
        if g4_words == 0 and g4_has_issues:
            g4_status = "[FAIL] BLOCKED (Content fetch failed)"
        elif g4_has_issues:
            g4_status = "[WARN] IMPROVEMENTS NEEDED (Ambiguous pronouns/headings/citations)"
        else:
            g4_status = "[PASS] CITABLE (Clear, autonomous RAG chunks)"
    elif g1_blocked:
        g4_status = "[BLOCKED] UNTESTED (Gate 1 failure)"
    else:
        g4_status = "[WARN] NOT RUN"

    print("\n  AI CITATION CAUSAL CHAIN:")
    print(f"  +-- Gate 1: Crawl & Protocol Access:    {g1_status}")
    print(f"  +-- Gate 2: Parse & Content Parity:     {g2_status}")
    print(f"  +-- Gate 3: Entity Trust & Grounding:   {g3_status}")
    print(f"  +-- Gate 4: AI Citability & RAG Chunks: {g4_status}")

    # Prioritized Action Plan
    all_findings_flat = []
    for s_data in pipeline_results.values():
        if isinstance(s_data, dict):
            all_findings_flat.extend(s_data.get("findings", []))

    criticals = [f for f in all_findings_flat if f.get("severity", "").upper() == "CRITICAL"]
    highs = [f for f in all_findings_flat if f.get("severity", "").upper() == "HIGH"]
    mediums = [f for f in all_findings_flat if f.get("severity", "").upper() == "MEDIUM"]

    print("\n  PRIORITIZED ACTION PLAN:")
    action_counter = 1
    if criticals:
        for f in criticals[:3]:
            print(f"  {action_counter}. [URGENT] {f.get('title')}")
            sug = f.get('suggested_action', {})
            act = sug.get('summary') if isinstance(sug, dict) else str(sug)
            print(f"     Action: {act}")
            action_counter += 1
    if highs and action_counter <= 4:
        for f in highs[:2]:
            print(f"  {action_counter}. [HIGH PRIORITY] {f.get('title')}")
            sug = f.get('suggested_action', {})
            act = sug.get('summary') if isinstance(sug, dict) else str(sug)
            print(f"     Action: {act}")
            action_counter += 1
    if mediums and action_counter <= 5:
        for f in mediums[:2]:
            print(f"  {action_counter}. [OPTIMIZATION] {f.get('title')}")
            sug = f.get('suggested_action', {})
            act = sug.get('summary') if isinstance(sug, dict) else str(sug)
            print(f"     Action: {act}")
            action_counter += 1
    if action_counter == 1:
        print("  1. No urgent actions needed. Your website is in the top tier for AI discoverability!")

    print(f"\n  [SAVED FULL AUDIT REPORT]")
    print(f"  Machine-readable JSON saved to:")
    print(f"  {report_file}")
    print("=" * 76 + "\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print_banner("Brand AI-Readiness Audit Pipeline Runner")

    # 1. Get Target URL
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    else:
        try:
            target_url = input("Enter website URL to audit (e.g., https://apple.com): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAudit cancelled.")
            sys.exit(0)

    if not target_url:
        print("Error: No URL provided.")
        sys.exit(1)

    target_url = format_url(target_url)
    parsed = urlparse(target_url)
    domain = parsed.netloc or parsed.path.split("/")[0]

    print(f"\nTarget Domain: {domain}")
    print(f"Target Root:   {target_url}")
    print(f"Started At:    {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Temporary directory for intermediate skill handoffs
    temp_dir = tempfile.mkdtemp(prefix="brand_audit_")
    path_access_json = os.path.join(temp_dir, "access_output.json")
    path_render_json = os.path.join(temp_dir, "render_output.json")
    path_schema_json = os.path.join(temp_dir, "schema_output.json")
    path_content_json = os.path.join(temp_dir, "content_output.json")

    pipeline_results = {}
    total_start_time = time.time()

    try:
        # =====================================================================
        # Skill 1: AI Crawler Access Audit
        # =====================================================================
        s1_script = os.path.join(SKILLS_DIR, "ai-crawler-access-audit", "scripts", "check_access.py")
        cmd_s1 = [sys.executable, s1_script, target_url, "--json"]
        s1_data, s1_time = run_command_stream(cmd_s1, "Skill 1 (Crawler Access)")

        if s1_data and isinstance(s1_data, dict):
            pipeline_results["skill_1"] = s1_data
            with open(path_access_json, "w", encoding="utf-8") as f:
                json.dump(s1_data, f, indent=2)
            log_skill_1_results(s1_data, s1_time)
        else:
            print("\n[!] Skill 1 did not return valid JSON. Proceeding with default parameters.")

        # =====================================================================
        # Skill 2: JS Render & Content Parity Audit
        # =====================================================================
        s2_script = os.path.join(SKILLS_DIR, "js-render-content-audit", "scripts", "check_render.py")
        cmd_s2 = [sys.executable, s2_script, target_url, "--json"]
        if os.path.isfile(path_access_json):
            cmd_s2.extend(["--input-json", path_access_json])

        s2_data, s2_time = run_command_stream(cmd_s2, "Skill 2 (JS Render Parity)")

        if s2_data and isinstance(s2_data, dict):
            pipeline_results["skill_2"] = s2_data
            with open(path_render_json, "w", encoding="utf-8") as f:
                json.dump(s2_data, f, indent=2)
            log_skill_2_results(s2_data, s2_time)
        else:
            print("\n[!] Skill 2 did not return valid JSON.")

        # =====================================================================
        # Skill 3: Structured Data & Entity Grounding Audit
        # =====================================================================
        s3_script = os.path.join(SKILLS_DIR, "structured-data-entity-audit", "scripts", "check_schema.py")
        cmd_s3 = [sys.executable, s3_script, target_url, "--json"]
        if os.path.isfile(path_access_json):
            cmd_s3.extend(["--input-access", path_access_json])
        if os.path.isfile(path_render_json):
            cmd_s3.extend(["--input-render", path_render_json])

        s3_data, s3_time = run_command_stream(cmd_s3, "Skill 3 (Entity & Schema)")

        if s3_data and isinstance(s3_data, dict):
            pipeline_results["skill_3"] = s3_data
            with open(path_schema_json, "w", encoding="utf-8") as f:
                json.dump(s3_data, f, indent=2)
            log_skill_3_results(s3_data, s3_time)
        else:
            print("\n[!] Skill 3 did not return valid JSON.")

        # =====================================================================
        # Skill 4: Content Quality & AI Citability Audit
        # =====================================================================
        s4_script = os.path.join(SKILLS_DIR, "content-quality-audit", "scripts", "check_content_quality.py")
        cmd_s4 = [sys.executable, s4_script, target_url, "--json"]
        if os.path.isfile(path_access_json):
            cmd_s4.extend(["--input-access", path_access_json])

        s4_data, s4_time = run_command_stream(cmd_s4, "Skill 4 (Content Quality)")

        if s4_data and isinstance(s4_data, dict):
            pipeline_results["skill_4"] = s4_data
            with open(path_content_json, "w", encoding="utf-8") as f:
                json.dump(s4_data, f, indent=2)
            log_skill_4_results(s4_data, s4_time)
        else:
            print("\n[!] Skill 4 did not return valid JSON.")

        # =====================================================================
        # Executive Scorecard & Report Export
        # =====================================================================
        total_time = time.time() - total_start_time
        clean_domain = domain.replace(".", "_").replace(":", "_")
        test_runs_dir = os.path.join(ROOT_DIR, "audits", "test_runs")
        os.makedirs(test_runs_dir, exist_ok=True)
        report_file = os.path.join(test_runs_dir, f"{clean_domain}_audit.json")

        final_report = {
            "target": target_url,
            "domain": domain,
            "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_runtime_seconds": round(total_time, 2),
            "skills": pipeline_results
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=2)

        log_pipeline_scorecard(pipeline_results, total_time, domain, report_file)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
