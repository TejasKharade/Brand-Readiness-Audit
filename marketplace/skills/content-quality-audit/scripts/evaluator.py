#!/usr/bin/env python3
"""
Diagnostic evaluators and citability rules engine for content-quality-audit.
Evaluates section-level RAG chunk autonomy, orphan pronouns, low-entropy headings,
content flooding, and proactive citability improvements.
Pure Python Standard Library - Zero External Dependencies.
"""

import os
import re
from urllib.parse import urlparse

try:
    from .constants import (
        LOW_ENTROPY_HEADINGS,
        ORPHAN_PRONOUN_PATTERN,
        PREAMBLE_FLUFF_PATTERNS,
        FLOODING_THRESHOLD_GUIDE,
        FLOODING_THRESHOLD_DOCS
    )
    from .section_parser import extract_text_from_html
except (ImportError, ValueError):
    from constants import (
        LOW_ENTROPY_HEADINGS,
        ORPHAN_PRONOUN_PATTERN,
        PREAMBLE_FLUFF_PATTERNS,
        FLOODING_THRESHOLD_GUIDE,
        FLOODING_THRESHOLD_DOCS
    )
    from section_parser import extract_text_from_html


def audit_section(sec, idx, archetype, page_url, add_finding):
    """
    Audits a single section top-to-bottom for chunk autonomy and LLM readability.
    Returns tuple: (is_substantive, is_autonomous).
    """
    heading = sec["heading"]
    text = sec["text"]
    wc = sec["word_count"]
    sentences = sec["sentences"]
    sec_html = sec["html"]

    if wc < 15 and not re.search(r"<img", sec_html, re.IGNORECASE):
        return False, False

    is_autonomous = True

    # Check 1: RAG_CHUNK_ORPHAN_PRONOUN (Ambiguous Anaphora)
    if sentences and wc >= 25 and sec["level"] > 0:
        first_sent = sentences[0].strip()
        if ORPHAN_PRONOUN_PATTERN.search(first_sent):
            is_autonomous = False
            sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
            add_finding(
                code="RAG_CHUNK_ORPHAN_PRONOUN",
                title=f"Section '{heading}' opens with an ambiguous pronoun (orphan chunk risk)",
                severity="HIGH",
                evidence=(
                    f"Opening sentence: '{first_sent}'\n"
                    f"Actual Section Content Excerpt:\n  \"{sample_excerpt}\"\n"
                    f"The section relies on an ambiguous pronoun rather than naming the explicit subject entity."
                ),
                suggested_action="Replace the opening pronoun with the explicit brand or technical noun (e.g. name the tool/feature directly) so RAG vector chunkers retain context.",
                url=page_url
            )

    # Check 2: RAG_HEADING_LOW_ENTROPY
    if sec["level"] > 0 and heading:
        norm_heading = heading.lower().strip()
        if norm_heading in LOW_ENTROPY_HEADINGS:
            sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
            add_finding(
                code="RAG_HEADING_LOW_ENTROPY",
                title=f"Heading '{heading}' has low semantic entropy",
                severity="MEDIUM",
                evidence=(
                    f"Heading '{heading}' provides zero search-intent tokens when prepended to chunk embeddings.\n"
                    f"Section Content Excerpt:\n  \"{sample_excerpt}\""
                ),
                suggested_action=f"Rename '{heading}' to include specific topic nouns (e.g., replace 'Overview' with 'System Architecture Overview' or 'Installation Guide').",
                url=page_url
            )

    # Check 2b: BLUF_QUESTION_ANSWER_DEFICIT (Question-Heading Direct Answer)
    if sec["level"] > 0 and heading and sentences and archetype != "homepage":
        is_question = bool(re.search(r"\?$|^(?:what|how|why|when|where|is|can|does|which)\b", heading.strip(), re.IGNORECASE))
        if is_question and len(sentences) >= 1:
            first_sent = sentences[0].strip()
            if re.search(r"^(?:in this (?:section|article|post)|to (?:understand|answer) this|before (?:we|diving)|it is important to note|let'?s (?:take a look|explore))\b", first_sent, re.IGNORECASE):
                sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
                add_finding(
                    code="BLUF_QUESTION_ANSWER_DEFICIT",
                    title=f"Question heading '{heading}' lacks a direct answer in its opening sentence",
                    severity="MEDIUM",
                    evidence=(
                        f"Heading is a direct question ('{heading}'), but opening sentence deflects rather than answering directly:\n  \"{first_sent}\"\n"
                        f"Section Opening:\n  \"{sample_excerpt}\""
                    ),
                    suggested_action="Adopt Bottom-Line-Up-Front (BLUF): formulate the direct answer to the heading's question in the very first sentence so AI search engines can quote it immediately.",
                    url=page_url
                )

    # Check 3: BLUF_FLUFF_PREAMBLE (First 150 words of guide/blog)
    if idx <= 1 and archetype in ("guide_article", "general") and wc >= 30:
        first_150_words = " ".join(text.split()[:150])
        for pattern in PREAMBLE_FLUFF_PATTERNS:
            match = pattern.search(first_150_words)
            if match:
                sample_excerpt = first_150_words[:260] + ("..." if len(first_150_words) > 260 else "")
                add_finding(
                    code="BLUF_FLUFF_PREAMBLE",
                    title="Opening text contains generic throat-clearing fluff instead of a direct answer",
                    severity="MEDIUM",
                    evidence=(
                        f"Found cliche '{match.group(0)}' in opening text.\n"
                        f"Opening Text Excerpt:\n  \"{sample_excerpt}\""
                    ),
                    suggested_action="Adopt Bottom-Line-Up-Front (BLUF): remove introductory digital cliches and provide a direct declarative definition in the first sentence.",
                    url=page_url
                )
                break

    # Check 4: RAG_SECTION_CONTENT_FLOODING (Archetype Calibrated)
    has_lists = bool(re.search(r"<(ul|ol)", sec_html, re.IGNORECASE))
    has_tables = bool(re.search(r"<table", sec_html, re.IGNORECASE))
    has_code = bool(re.search(r"<(pre|code)", sec_html, re.IGNORECASE))

    threshold = FLOODING_THRESHOLD_GUIDE if archetype in ("guide_article", "general") else FLOODING_THRESHOLD_DOCS if archetype == "documentation" else 99999
    if archetype != "homepage" and wc > threshold:
        if not has_lists and not has_tables and not (archetype == "documentation" and has_code):
            sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
            add_finding(
                code="RAG_SECTION_CONTENT_FLOODING",
                title=f"Section '{heading}' contains continuous prose flooding ({wc} words)",
                severity="MEDIUM",
                evidence=(
                    f"Section contains {wc} words of continuous prose without subheadings, bullet lists, or tables, triggering 'Lost in the Middle' attention degradation in LLM retrieval.\n"
                    f"Section Opening Excerpt:\n  \"{sample_excerpt}\""
                ),
                suggested_action="Break this section into self-contained 40-80 word paragraphs and introduce subheadings (<h3>) or bulleted lists.",
                url=page_url
            )

    # Check 5: CONTENT_LOCK_IMAGE_TRAP
    if wc < 15 and re.search(r"<img", sec_html, re.IGNORECASE):
        img_matches = re.findall(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', sec_html, re.IGNORECASE)
        for src in img_matches:
            src_lower = src.lower()
            if any(k in src_lower for k in ["pricing", "comparison", "benchmark", "architecture", "table", "specs", "features"]):
                add_finding(
                    code="CONTENT_LOCK_IMAGE_TRAP",
                    title=f"Substantive data appears locked inside image asset ({os.path.basename(src)})",
                    severity="MEDIUM",
                    evidence=f"Section '{heading}' has only {wc} words of text but embeds '{os.path.basename(src)}'. AI crawlers cannot index or cite data locked in raster images.",
                    suggested_action="Provide an HTML <table> or structured text equivalent alongside the image so AI search engines can ingest the data.",
                    url=page_url
                )
                break

    return True, is_autonomous


def evaluate_page_proactive_suggestions(page_url, archetype, page_word_count, cleaned_html, add_finding):
    """Generates constructive INFO suggestions without penalizing the site score."""
    # 1. Statistical Density Suggestion on substantive articles
    if archetype == "guide_article" and page_word_count >= 350:
        plain_text = extract_text_from_html(cleaned_html)
        numeric_data = re.findall(r"\b(?:\d+(?:\.\d+)?%|\d+\s*(?:ms|gb|mb|tb|kbps|mbps|req/s|qps))\b", plain_text, re.IGNORECASE)
        if len(numeric_data) == 0:
            add_finding(
                code="CITABILITY_STATISTICAL_SUGGESTION",
                title="Consider adding quantitative metrics to improve AI citation probability",
                severity="INFO",
                evidence=f"Page contains {page_word_count} words but 0 explicit numeric statistics or benchmarks.",
                suggested_action="The Princeton GEO study demonstrated that adding verifiable statistics increases AI citation probability by +37%. Consider integrating benchmark data or concrete metrics.",
                url=page_url
            )

    # 2. Tabular Formatting Suggestion on pricing content
    pricing_matches = re.findall(r"\b(?:free|pro|enterprise|starter|standard|plan|pricing)\b", cleaned_html, re.IGNORECASE)
    has_table = bool(re.search(r"<table", cleaned_html, re.IGNORECASE))
    has_currency = bool(re.search(r"[\$€£]\s*\d+", cleaned_html))

    if len(pricing_matches) >= 3 and has_currency and not has_table and archetype != "homepage":
        add_finding(
            code="STRUCTURE_TABULAR_SUGGESTION",
            title="Consider presenting comparative pricing options in a structured table",
            severity="INFO",
            evidence="Page contains multiple pricing indicators but 0 <table> elements. LLMs quote structured tables at a significantly higher rate than narrative prose.",
            suggested_action="Structure plan comparisons into an HTML <table> with rows and columns for plan names, prices, and features.",
            url=page_url
        )

    # 3. External Attribution vs. Circular Self-Citation
    if archetype in ("guide_article", "general") and page_word_count >= 350:
        all_links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>', cleaned_html, re.IGNORECASE)
        parsed_target = urlparse(page_url)
        internal_links = []
        external_links = []
        for link in all_links:
            if link.startswith("#") or link.startswith("javascript:") or link.startswith("mailto:"):
                continue
            p = urlparse(link)
            if not p.netloc or p.netloc.lower() == parsed_target.netloc.lower():
                internal_links.append(link)
            else:
                external_links.append(link)

        # Circular citation check: Has links, but 100% of them point to own domain
        if len(all_links) >= 3 and len(external_links) == 0:
            add_finding(
                code="CITABILITY_CIRCULAR_CITATION",
                title="Article relies entirely on circular self-citations with zero external reference links",
                severity="MEDIUM",
                evidence=f"Page contains {len(internal_links)} links, but 100% of them point back to {parsed_target.netloc}. Zero external primary sources or research citations are provided.",
                suggested_action="Integrate outbound citations to authoritative external sources (standards, benchmarks, institutional studies) to establish a verifiable credibility chain for LLMs.",
                url=page_url
            )

    # 4. Temporal Anchoring Recency Check
    if archetype in ("guide_article", "documentation") and page_word_count >= 300:
        plain_text = extract_text_from_html(cleaned_html)
        has_recent_year = bool(re.search(r"\b(2025|2026)\b", plain_text))
        has_stale_year = bool(re.search(r"\b(2020|2021|2022|2023)\b", plain_text))
        has_update_marker = bool(re.search(r"\b(updated|last modified|as of)\b", plain_text, re.IGNORECASE))
        if has_stale_year and not has_recent_year and not has_update_marker:
            add_finding(
                code="TEMPORAL_ANCHORING_SUGGESTION",
                title="Content contains older year references with no recent temporal anchors",
                severity="INFO",
                evidence="Page mentions historical years without recent temporal anchors (2025/2026 or 'Updated' markers).",
                suggested_action="Add explicit temporal markers (e.g., 'Updated for 2026' or 'As of Q1 2026') to signal to generative engines that this content remains current.",
                url=page_url
            )
