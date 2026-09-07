#!/usr/bin/env python3
"""
HTML, JSON-LD, and Schema.org parsers for structured-data-entity-audit.
Pure Python Standard Library - Zero External Dependencies.
"""

import re
import json
import html
from urllib.parse import urlparse

try:
    from .constants import AUTHORITY_REGISTRY
except (ImportError, ValueError):
    from constants import AUTHORITY_REGISTRY


def extract_visible_text(html_content):
    """Strips tags, scripts, and comments to yield clean visible text."""
    if not html_content:
        return ""
    # Remove script and style elements
    clean = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    clean = re.sub(r"<!--.*?-->", " ", clean, flags=re.DOTALL)
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Unescape entities
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def extract_json_ld(html_content):
    """
    Extracts all JSON-LD blocks from raw HTML.
    Returns:
        parsed_objects: list of parsed dicts
        syntax_errors: list of error descriptions
    """
    if not html_content:
        return [], []

    pattern = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(html_content)

    parsed_objects = []
    syntax_errors = []

    for idx, raw_snippet in enumerate(matches):
        snippet_str = raw_snippet.strip()
        if not snippet_str:
            continue

        try:
            data = json.loads(snippet_str)
            _collect_schema_nodes(data, parsed_objects)
        except json.JSONDecodeError as err:
            # Attempt recovery: unescape HTML entities
            recovered = False
            try:
                unescaped = html.unescape(snippet_str)
                data = json.loads(unescaped)
                _collect_schema_nodes(data, parsed_objects)
                recovered = True
            except Exception:
                pass

            if not recovered:
                # Attempt recovery: strip JS comments
                try:
                    no_comments = re.sub(r"//.*?\n|/\*.*?\*/", "", snippet_str)
                    data = json.loads(no_comments)
                    _collect_schema_nodes(data, parsed_objects)
                    recovered = True
                except Exception:
                    pass

            if not recovered:
                syntax_errors.append(f"Tag #{idx+1} JSON parse error: {str(err)} near '{snippet_str[:60]}...'")

    return parsed_objects, syntax_errors


def _collect_schema_nodes(node, collector):
    """Recursively flattens JSON-LD objects, arrays, and @graph nodes."""
    if isinstance(node, dict):
        if "@graph" in node and isinstance(node["@graph"], list):
            for child in node["@graph"]:
                _collect_schema_nodes(child, collector)
        else:
            collector.append(node)
            # Inspect nested entities (e.g. publisher, brand, offers, mainEntity)
            for k, v in node.items():
                if isinstance(v, dict) and "@type" in v:
                    _collect_schema_nodes(v, collector)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and "@type" in item:
                            _collect_schema_nodes(item, collector)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_nodes(item, collector)


def get_schema_types(schema_node):
    """Extracts @type as a set of strings from a schema node."""
    stype = schema_node.get("@type", "")
    if isinstance(stype, list):
        return set(stype)
    elif isinstance(stype, str) and stype:
        return {stype}
    return set()


def check_sameas_authorities(same_as_list):
    """Evaluates sameAs URLs against recognized authoritative registries."""
    if not same_as_list:
        return []
    if isinstance(same_as_list, str):
        same_as_list = [same_as_list]

    recognized = []
    for link in same_as_list:
        if not isinstance(link, str):
            continue
        try:
            parsed = urlparse(link)
            domain = parsed.netloc.lower()
            for auth in AUTHORITY_REGISTRY:
                if auth in domain:
                    recognized.append({"url": link, "authority": auth})
                    break
        except Exception:
            continue
    return recognized


def get_url_depth(u):
    """Calculates path depth of a given URL."""
    p = urlparse(u).path.strip("/")
    return len([seg for seg in p.split("/") if seg]) if p else 0
