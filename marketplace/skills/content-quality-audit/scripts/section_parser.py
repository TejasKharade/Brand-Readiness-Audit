#!/usr/bin/env python3
"""
Section parser, boilerplate stripper, and text tokenizer for content-quality-audit.
Partitions the entire body of every webpage section-by-section (zero skipping)
for granular RAG chunk analysis.
Pure Python Standard Library - Zero External Dependencies.
"""

import re
import html
from urllib.parse import urlparse


def detect_archetype(url):
    """Calibrates page archetype based on URL slug."""
    path = urlparse(url).path.lower().rstrip("/")
    if not path or path == "":
        return "homepage"
    if any(p in path for p in ["/docs", "/documentation", "/api", "/reference", "/build"]):
        return "documentation"
    if any(p in path for p in ["/blog", "/guide", "/guides", "/article", "/articles", "/posts", "/post"]):
        return "guide_article"
    if any(p in path for p in ["/pricing", "/product", "/products", "/plans"]):
        return "pricing_product"
    return "general"


def clean_html_strip_boilerplate(raw_html):
    """Strips non-content tags (nav, footer, script, style) without losing section body."""
    if not raw_html:
        return ""
    # Strip script, style, noscript, svg
    clean = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    # Strip comments
    clean = re.sub(r"<!--.*?-->", " ", clean, flags=re.DOTALL)
    # Strip navigation, footer, aside boilerplate
    clean = re.sub(r"<(nav|footer|aside)[^>]*>.*?</\1>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
    return clean


def extract_text_from_html(html_snippet):
    """Converts HTML snippet to clean visible plain text."""
    if not html_snippet:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html_snippet)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def split_sentences(text):
    """Splits text into clean sentence list."""
    if not text:
        return []
    # Split on periods/exclamations/questions followed by space and capital letter or end
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'‘“])", text)
    return [s.strip() for s in raw if len(s.strip()) > 3]


def partition_into_sections(cleaned_html):
    """
    Partitions the entire body into sequential sections demarcated by headings.
    Captures 100% of the substantive page content without skipping anything.
    """
    heading_pattern = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
    matches = list(heading_pattern.finditer(cleaned_html))

    sections = []

    if not matches:
        # No headings on page - treat entire content as single section
        text = extract_text_from_html(cleaned_html)
        if text:
            sections.append({
                "level": 0,
                "heading": "Preamble / Document Body",
                "html": cleaned_html,
                "text": text,
                "word_count": len(text.split()),
                "sentences": split_sentences(text)
            })
        return sections

    # 1. Capture opening preamble before the first heading
    first_match_start = matches[0].start()
    preamble_html = cleaned_html[:first_match_start].strip()
    preamble_text = extract_text_from_html(preamble_html)
    if preamble_text and len(preamble_text.split()) >= 10:
        sections.append({
            "level": 0,
            "heading": "Document Preamble",
            "html": preamble_html,
            "text": preamble_text,
            "word_count": len(preamble_text.split()),
            "sentences": split_sentences(preamble_text)
        })

    # 2. Iterate through every heading and its succeeding content
    for idx, match in enumerate(matches):
        level = int(match.group(1))
        raw_heading = match.group(2)
        heading_text = extract_text_from_html(raw_heading)

        content_start = match.end()
        content_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned_html)
        section_html = cleaned_html[content_start:content_end].strip()
        section_text = extract_text_from_html(section_html)

        sections.append({
            "level": level,
            "heading": heading_text,
            "html": section_html,
            "text": section_text,
            "word_count": len(section_text.split()) if section_text else 0,
            "sentences": split_sentences(section_text) if section_text else []
        })

    return sections


def get_url_depth(u):
    """Calculates path depth of a given URL."""
    p = urlparse(u).path.strip("/")
    return len([seg for seg in p.split("/") if seg]) if p else 0
