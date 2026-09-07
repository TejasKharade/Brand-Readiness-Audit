"""
structured-data-entity-audit package.
Schema.org entity grounding, sameAs authority checks, and fact consistency audit engine.
"""

from .check_schema import SchemaEntityAuditor
from .http_client import fetch_raw_html, load_json_multienconding
from .parser import extract_json_ld, extract_visible_text, get_schema_types
from .entity_evaluator import (
    evaluate_root_entity,
    evaluate_fact_consistency,
    evaluate_description_extractability
)

__all__ = [
    "SchemaEntityAuditor",
    "fetch_raw_html",
    "load_json_multienconding",
    "extract_json_ld",
    "extract_visible_text",
    "get_schema_types",
    "evaluate_root_entity",
    "evaluate_fact_consistency",
    "evaluate_description_extractability",
]
