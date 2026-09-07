#!/usr/bin/env python3
"""
Semantic parity evaluator and diagnostic rules engine for js-render-content-audit.
Compares Pass A (raw HTTP) vs Pass B (hydrated DOM) across sentences, headings,
structured data, internal links, and latency budgets.
Pure standard library. Zero external dependencies.
"""

import re
from urllib.parse import urlparse

try:
    from .constants import (
        LATENCY_BUDGET_MS,
        PARITY_EMPTY_SHELL_THRESHOLD,
        PARITY_CORE_GAP_THRESHOLD,
        PARITY_PARTIAL_GAP_THRESHOLD
    )
    from .http_fetcher import fetch_pass_a
    from .browser_runner import fetch_pass_b
    from .feature_extractor import extract_features
except (ImportError, ValueError):
    from constants import (
        LATENCY_BUDGET_MS,
        PARITY_EMPTY_SHELL_THRESHOLD,
        PARITY_CORE_GAP_THRESHOLD,
        PARITY_PARTIAL_GAP_THRESHOLD
    )
    from http_fetcher import fetch_pass_a
    from browser_runner import fetch_pass_b
    from feature_extractor import extract_features


def audit_render_parity(target_url, browser_bin):
    """
    Executes Pass A vs Pass B diff on a specific URL and returns findings and parity metrics.
    """
    res_a = fetch_pass_a(target_url)
    res_b = fetch_pass_b(target_url, browser_bin) if browser_bin else None

    feat_a = extract_features(res_a["html"], target_url)
    feat_b = extract_features(res_b["html"], target_url) if (res_b and res_b["status"] == 200) else None

    findings = []
    finding_counter = 1

    def add_finding(code, title, severity, evidence, action_summary, action_priority=None):
        nonlocal finding_counter
        f_id = f"RND-{finding_counter:03d}"
        finding_counter += 1
        findings.append({
            "id": f_id,
            "code": code,
            "title": title,
            "severity": severity,
            "evidence": evidence,
            "suggested_action": {
                "summary": action_summary,
                "priority": action_priority or severity
            }
        })

    # Check 0: HTTP status failure on Pass A
    if res_a["status"] == 0 or res_a["status"] >= 400:
        is_homepage = urlparse(target_url).path in ("", "/")
        sev = "critical" if is_homepage else "high"
        add_finding(
            code="RAW_FETCH_FAILURE",
            title=f"Direct HTTP fetch failed on {urlparse(target_url).path or '/'}",
            severity=sev,
            evidence=f"Raw fetch returned HTTP {res_a['status']}: {res_a['error']}.",
            action_summary="Fix server routing or permissions to ensure the URL returns HTTP 200 to AI search bots."
        )
        return {
            "url": target_url,
            "findings": findings,
            "metrics": {
                "pass_a_status": res_a["status"],
                "pass_b_status": res_b["status"] if res_b else 0,
                "parity_pct": 0.0
            }
        }

    # If no browser was available on the host machine, gracefully fallback
    if not feat_b:
        # Fallback static checks for obvious empty shells
        if len(feat_a["sentences"]) == 0 and ("<div id=\"root\">" in res_a["html"] or "<div id=\"app\">" in res_a["html"]):
            add_finding(
                code="EMPTY_SHELL_SPA_SUSPECTED",
                title="Probable empty-shell Single Page Application (SPA)",
                severity="high",
                evidence="Raw HTML contains an empty mounting container (<div id='root'> or #app) with 0 extracted sentences.",
                action_summary="Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) to ensure content is delivered in raw HTML."
            )
        return {
            "url": target_url,
            "findings": findings,
            "metrics": {
                "pass_a_status": res_a["status"],
                "pass_b_status": res_b["status"] if res_b else 0,
                "browser_available": bool(browser_bin),
                "pass_b_error": res_b.get("error") if res_b else "No browser binary detected",
                "raw_sentences_count": len(feat_a["sentences"])
            }
        }

    # 1. Core Sentence & Paragraph Parity Comparison
    missing_sentences = []
    text_a_clean = re.sub(
        r"\s+", " ",
        feat_a["clean_text"].lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    )
    for s in feat_b["sentences"]:
        s_clean = re.sub(
            r"\s+", " ",
            s.lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
        ).strip()
        words = s_clean.split()
        probe = " ".join(words[:min(6, len(words))])
        if probe not in text_a_clean:
            missing_sentences.append(s)

    # Group missing text into coherent missing content blocks/sections
    missing_content_blocks = []
    current_block = []
    for s in missing_sentences:
        current_block.append(s)
        if len(" ".join(current_block)) >= 180 or len(current_block) >= 3:
            missing_content_blocks.append(" ".join(current_block))
            current_block = []
    if current_block:
        missing_content_blocks.append(" ".join(current_block))

    # Also extract full paragraphs present in Pass B absent from Pass A
    for p in feat_b.get("paragraphs", []):
        p_clean = re.sub(
            r"\s+", " ",
            p.lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
        ).strip()
        p_words = p_clean.split()
        probe = " ".join(p_words[:min(7, len(p_words))])
        if probe not in text_a_clean:
            if not any(p in b or b in p for b in missing_content_blocks):
                missing_content_blocks.append(p)

    total_b_sentences = len(feat_b["sentences"])
    if total_b_sentences > 0:
        parity_pct = round((1 - (len(missing_sentences) / total_b_sentences)) * 100, 1)
    else:
        parity_pct = 100.0

    # Format actual missing text sections for evidence
    missing_evidence_lines = []
    for idx_b, b in enumerate(missing_content_blocks[:3], 1):
        b_clean = b.strip()
        snippet = b_clean if len(b_clean) <= 200 else b_clean[:200] + "..."
        missing_evidence_lines.append(f"Section {idx_b}: \"{snippet}\"")
    missing_evidence_str = "\n".join(missing_evidence_lines) if missing_evidence_lines else "No substantive text blocks missing."

    # Flag: EMPTY_SHELL_SPA (Critical)
    if total_b_sentences >= 2 and len(feat_a["sentences"]) == 0 and parity_pct < PARITY_EMPTY_SHELL_THRESHOLD:
        add_finding(
            code="EMPTY_SHELL_SPA",
            title=f"Core content is client-rendered and invisible in raw HTML: {urlparse(target_url).path or '/'}",
            severity="critical",
            evidence=(
                f"Raw HTTP response delivered 0 text sentences, while rendered browser DOM produced {total_b_sentences} sentences (Parity: {parity_pct}%).\n"
                f"Actual Missing Content from Browser DOM:\n{missing_evidence_str}"
            ),
            action_summary="Pre-render primary page content using SSR (Next.js/Nuxt) or SSG so search crawlers can index and cite it without executing JavaScript."
        )
    # Flag: CORE_CONTENT_RENDER_GAP (High)
    elif total_b_sentences >= 3 and parity_pct < PARITY_CORE_GAP_THRESHOLD:
        add_finding(
            code="CORE_CONTENT_RENDER_GAP",
            title=f"Significant content render gap ({parity_pct}% parity) on {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=(
                f"Pass B rendered {total_b_sentences} sentences, but Pass A only contained {total_b_sentences - len(missing_sentences)} in raw HTML ({len(missing_sentences)} missing sentences, {parity_pct}% parity).\n"
                f"Actual Missing Content from Browser DOM:\n{missing_evidence_str}"
            ),
            action_summary="Ensure core documentation, product specifications, and descriptive text are rendered server-side in static HTML."
        )
    # Flag: PARTIAL_CONTENT_RENDER_GAP (Medium)
    elif total_b_sentences >= 3 and parity_pct < PARITY_PARTIAL_GAP_THRESHOLD and missing_content_blocks:
        add_finding(
            code="PARTIAL_CONTENT_RENDER_GAP",
            title=f"Substantive content sections ({len(missing_content_blocks)} blocks) are missing from raw HTML on {urlparse(target_url).path or '/'}",
            severity="medium",
            evidence=(
                f"Rendered browser DOM produced {len(missing_sentences)} sentences ({parity_pct}% parity) that do not appear in raw HTML.\n"
                f"Actual Missing Content Sections:\n{missing_evidence_str}"
            ),
            action_summary="Render these content sections server-side in static HTML so AI search bots index the full text without executing JavaScript."
        )

    # 2. Heading & Topic Mutation
    if feat_b["h1_list"] and not feat_a["h1_list"]:
        h1_rendered = feat_b["h1_list"][0]
        add_finding(
            code="HEADING_RENDER_GAP",
            title=f"Primary <h1> is injected via client JavaScript on {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=f"Rendered DOM contains <h1> '{h1_rendered}', but raw HTML has 0 <h1> tags.",
            action_summary="Render primary <h1> tags in static HTML to ensure AI crawlers immediately identify the topic."
        )

    # 3. Structured Data Timing
    missing_schemas = [s for s in feat_b["schema_types"] if s not in feat_a["schema_types"]]
    if missing_schemas:
        add_finding(
            code="STRUCTURED_DATA_TIMING",
            title=f"JSON-LD structured data is injected via client JavaScript: {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=f"Schema types [{', '.join(missing_schemas)}] were found in the rendered DOM but absent from initial raw HTML.",
            action_summary="Move JSON-LD <script type='application/ld+json'> tags to server-rendered HTML so AI crawlers extract entity schema without JavaScript execution."
        )

    # 4. Internal Link Discovery Gap
    missing_links = feat_b["internal_links"] - feat_a["internal_links"]
    if len(missing_links) >= 5:
        sample_links = list(missing_links)[:3]
        add_finding(
            code="INTERNAL_LINK_DISCOVERY_GAP",
            title=f"Navigation links ({len(missing_links)} URLs) are locked inside client JavaScript on {urlparse(target_url).path or '/'}",
            severity="medium",
            evidence=f"{len(missing_links)} internal links exist only in the rendered DOM (e.g., {', '.join(sample_links)}).",
            action_summary="Use standard HTML <a href='...'> anchor tags in static navigation menus to allow search spiders to discover interior pages."
        )

    # 5. Time-to-Content-Complete Budgeting
    if res_b["elapsed_ms"] > LATENCY_BUDGET_MS:
        add_finding(
            code="RENDER_LATENCY_EXCEEDED",
            title=f"Headless render latency ({res_b['elapsed_ms']:.0f}ms) exceeds crawl time budget on {urlparse(target_url).path or '/'}",
            severity="medium",
            evidence=f"Hydration and DOM stabilization took {res_b['elapsed_ms']:.0f}ms (threshold: {LATENCY_BUDGET_MS}ms). Real-world AI crawlers (OAI-SearchBot) operate on strict 3-5 second timeouts and drop slow-rendering pages.",
            action_summary="Optimize client bundle size, defer non-critical scripts, or implement server-side pre-rendering to keep time-to-content under 3.5 seconds."
        )

    metrics = {
        "pass_a_status": res_a["status"],
        "pass_b_status": res_b["status"],
        "pass_a_latency_ms": res_a["elapsed_ms"],
        "pass_b_latency_ms": res_b["elapsed_ms"],
        "parity_pct": parity_pct,
        "sentences_pass_a": len(feat_a["sentences"]),
        "sentences_pass_b": total_b_sentences,
        "pass_a_excerpt": feat_a["clean_text"][:250].replace("\n", " ").strip(),
        "pass_b_excerpt": feat_b["clean_text"][:250].replace("\n", " ").strip(),
        "missing_sentences_count": len(missing_sentences),
        "missing_content_blocks": missing_content_blocks[:4],
        "missing_snippets_sample": missing_sentences[:3]
    }

    return {
        "url": target_url,
        "findings": findings,
        "metrics": metrics
    }
