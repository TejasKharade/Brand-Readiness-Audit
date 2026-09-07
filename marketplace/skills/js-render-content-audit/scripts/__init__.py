"""
js-render-content-audit package.
Two-pass JavaScript rendering and semantic parity audit engine.
"""

from .check_render import audit_render
from .parity_evaluator import audit_render_parity
from .browser_runner import find_headless_browser, fetch_pass_b
from .http_fetcher import fetch_pass_a
from .feature_extractor import extract_features

__all__ = [
    "audit_render",
    "audit_render_parity",
    "find_headless_browser",
    "fetch_pass_b",
    "fetch_pass_a",
    "extract_features",
]
