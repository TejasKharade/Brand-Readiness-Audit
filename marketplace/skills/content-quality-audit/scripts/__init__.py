"""
content-quality-audit package.
Full-content AI citability, RAG chunking, and ambiguous anaphora audit engine.
"""

from .check_content_quality import ContentQualityAuditor
from .http_client import fetch_raw_html, load_json_multienconding
from .section_parser import (
    detect_archetype,
    clean_html_strip_boilerplate,
    partition_into_sections,
    extract_text_from_html,
    split_sentences
)
from .evaluator import audit_section, evaluate_page_proactive_suggestions

__all__ = [
    "ContentQualityAuditor",
    "fetch_raw_html",
    "load_json_multienconding",
    "detect_archetype",
    "clean_html_strip_boilerplate",
    "partition_into_sections",
    "extract_text_from_html",
    "split_sentences",
    "audit_section",
    "evaluate_page_proactive_suggestions",
]
