#!/usr/bin/env python3
"""
Constants, regex patterns, and heading lexicons for content-quality-audit.
Pure Python Standard Library - Zero External Dependencies.
"""

import re

USER_AGENT = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

LOW_ENTROPY_HEADINGS = {
    "overview",
    "introduction",
    "background",
    "details",
    "summary",
    "more information",
    "more info",
    "about",
    "features",
    "general",
    "misc",
    "miscellaneous",
    "notes",
    "conclusion",
    "info"
}

ORPHAN_PRONOUN_PATTERN = re.compile(
    r"^(?:it|they|this\s+(?:tool|platform|solution|system|software|library|framework|service|app|utility)|as\s+(?:mentioned|stated|seen|discussed)\s+(?:above|earlier|before)|like\s+we\s+said)\b",
    re.IGNORECASE
)

PREAMBLE_FLUFF_PATTERNS = [
    re.compile(r"in today'?s (?:fast-paced|rapidly changing|digital|modern) (?:world|era|landscape)", re.IGNORECASE),
    re.compile(r"in (?:the|an) era of\b", re.IGNORECASE),
    re.compile(r"it is no secret that\b", re.IGNORECASE),
    re.compile(r"have you ever wondered\b", re.IGNORECASE),
    re.compile(r"in an increasingly (?:connected|complex) world\b", re.IGNORECASE),
    re.compile(r"businesses (?:everywhere|today) are (?:striving|looking) to\b", re.IGNORECASE)
]

FLOODING_THRESHOLD_GUIDE = 400
FLOODING_THRESHOLD_DOCS = 800
