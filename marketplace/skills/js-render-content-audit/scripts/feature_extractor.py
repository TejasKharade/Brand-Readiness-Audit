#!/usr/bin/env python3
"""
HTML feature extractor for js-render-content-audit.
Extracts title, h1, JSON-LD schemas, internal links, substantive paragraphs, and sentences.
Pure standard library. Zero external dependencies.
"""

import re
import json
import html as html_lib
from urllib.parse import urlparse, urljoin

try:
    from .constants import (
        SENTENCE_MIN_CHARS,
        SENTENCE_MIN_WORDS,
        PARAGRAPH_MIN_CHARS,
        PARAGRAPH_MIN_WORDS
    )
except (ImportError, ValueError):
    from constants import (
        SENTENCE_MIN_CHARS,
        SENTENCE_MIN_WORDS,
        PARAGRAPH_MIN_CHARS,
        PARAGRAPH_MIN_WORDS
    )


def extract_features(html, base_url):
    """
    Extracts structural and semantic elements while stripping non-content boilerplate.
    Focuses on: title, h1, json-ld schemas, internal links, and substantive sentences.
    """
    if not html:
        return {
            "title": "",
            "h1_list": [],
            "schema_types": [],
            "internal_links": set(),
            "clean_text": "",
            "paragraphs": [],
            "sentences": []
        }

    # 1. Extract <title>
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.DOTALL)
    title = html_lib.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""

    # 2. Extract <h1> tags
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.DOTALL)
    h1_list = [html_lib.unescape(re.sub(r"<[^>]+>", "", h)).strip() for h in h1_matches]
    h1_list = [re.sub(r"\s+", " ", h) for h in h1_list if h]

    # 3. Extract JSON-LD Schema types
    schema_types = []
    for script_match in re.finditer(r'<script\s+[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.DOTALL):
        try:
            data = json.loads(script_match.group(1).strip())
            if isinstance(data, dict):
                stype = data.get("@type")
                if stype:
                    schema_types.append(stype if isinstance(stype, str) else str(stype))
                if "@graph" in data and isinstance(data["@graph"], list):
                    for item in data["@graph"]:
                        if isinstance(item, dict) and "@type" in item:
                            schema_types.append(str(item["@type"]))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "@type" in item:
                        schema_types.append(str(item["@type"]))
        except Exception:
            pass

    # 4. Extract internal <a href> links
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    internal_links = set()
    for link_match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.I):
        href = link_match.group(1).strip()
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full_url = urljoin(base_url, href)
        parsed_link = urlparse(full_url)
        if parsed_link.netloc.lower() == base_domain:
            norm_link = f"{parsed_link.scheme}://{parsed_link.netloc}{parsed_link.path}".rstrip("/")
            if norm_link:
                internal_links.add(norm_link)

    # 5. Clean boilerplate noise
    cleaned = html
    # Remove script, style, svg, noscript
    cleaned = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", cleaned, flags=re.I | re.DOTALL)
    # Remove header, nav, footer, aside
    cleaned = re.sub(r"<(header|nav|footer|aside)[^>]*>.*?</\1>", " ", cleaned, flags=re.I | re.DOTALL)
    # Remove modal/dialog/consent containers
    cleaned = re.sub(r'<[^>]+(?:id|class)=["\'][^"\']*(?:cookie|consent|modal|banner|overlay|dialog)[^"\']*["\'][^>]*>.*?</[^>]+>', " ", cleaned, flags=re.I | re.DOTALL)

    # Prioritize <main> or <article> if available
    main_match = re.search(r"<(main|article)[^>]*>(.*?)</\1>", cleaned, re.I | re.DOTALL)
    content_html = main_match.group(2) if main_match else cleaned

    # Insert newlines around block tags so separate elements don't merge into one giant line
    content_html = re.sub(r"<(/?(?:div|p|li|tr|th|td|h[1-6]|br|hr)[^>]*)>", r"\n<\1>\n", content_html, flags=re.I)

    # Strip all remaining HTML tags
    raw_text = re.sub(r"<[^>]+>", " ", content_html)
    clean_text = html_lib.unescape(raw_text)
    clean_text = clean_text.replace('\xa0', ' ').replace('&nbsp;', ' ')
    clean_text = clean_text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    clean_text = re.sub(r"[ \t]+", " ", clean_text)
    clean_text = re.sub(r"\n\s*\n+", "\n", clean_text).strip()

    # Extract substantive paragraphs
    paragraphs = []
    for p in clean_text.split("\n"):
        p = p.strip()
        if len(p) >= PARAGRAPH_MIN_CHARS and len(p.split()) >= PARAGRAPH_MIN_WORDS and not re.search(r"[{};()=<>|\\]", p):
            paragraphs.append(p)

    # Extract substantive sentences (>= 25 chars, >= 4 words, not code/garbage)
    candidate_sentences = re.split(r"(?<=[.!?])\s+|\n+", clean_text)
    sentences = []
    for s in candidate_sentences:
        s = s.strip()
        if len(s) >= SENTENCE_MIN_CHARS and len(s.split()) >= SENTENCE_MIN_WORDS:
            # Filter obvious CSS/JS leftovers
            if not re.search(r"[{};()=<>|\\]", s):
                sentences.append(s)

    return {
        "title": title,
        "h1_list": h1_list,
        "schema_types": list(set(schema_types)),
        "internal_links": internal_links,
        "clean_text": clean_text,
        "paragraphs": paragraphs,
        "sentences": sentences
    }
