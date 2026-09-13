
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import os
import json
import threading

"""Runs every readability-audit check in ONE process instead of four separate
subprocess invocations.

Why this exists: `check_structured_data.py`, `check_semantic_structure.py`,
and `check_content_consistency.py` are pure in-memory string/HTML parsing --
zero network I/O -- and `check_nontext_facts.py`'s only network cost (linked
PDFs) is already wall-clock-bounded on its own (`PDF_INSPECTION_DEADLINE_S`).
None of the four benefit from being separate OS processes; each separate
subprocess spawn plus the calling agent's own per-call turn/notification
overhead (observed directly: a real audit on a rate-limited host stacked this
cost across ~26 total script invocations) is pure waste that scales with
invocation COUNT, not with how slow or fast the target site is -- so cutting
it here helps every audited site, not just a slow one.

This is purely additive: every check function below is imported unchanged
from its own script and called exactly as `synthesize_report.py` already
expects (see readability-audit/SKILL.md's Output Schema) -- nothing about
detection logic, output shape, or field names changes. The individual
scripts are untouched and still work standalone (verify_contracts.py and the
test suite call them directly), so this does not replace them, only adds a
faster way to invoke all four together."""

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from check_structured_data import check_structured_data
from check_semantic_structure import check_semantic_structure
from check_nontext_facts import check_nontext_facts
from check_content_consistency import check_content_consistency


def run_all(html_content, url, robots=None, max_pdfs=3):
    """Returns the same four containers `synthesize_report.py` reads whether
    they came from four separate script calls or this one combined call --
    each wrapped so ONE check's internal bug can never blank out the other
    three (matching every other script's own "always return structured JSON,
    never crash" guarantee, just applied per-section here)."""
    out = {}
    for key, fn, kwargs in (
        ("structured_data", check_structured_data, {}),
        ("semantic_structure", check_semantic_structure, {}),
        ("content_consistency", check_content_consistency, {}),
        ("nontext_facts", check_nontext_facts, {"robots": robots, "max_pdfs": max_pdfs}),
    ):
        try:
            out[key] = fn(html_content, url, **kwargs)
        except Exception as e:
            out[key] = {"error": f"{key} check failed: {type(e).__name__}: {e}"}
    return out


def read_stdin_safe(timeout=5.0):
    if sys.stdin.isatty():
        return ""
    res = []

    def target():
        try:
            res.append(sys.stdin.read())
        except Exception:
            pass
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return res[0].lstrip("\ufeff") if res else ""


if __name__ == "__main__":
    try:
        html_content = ""
        url = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html_content = params.get("html", "")
                    url = params.get("url", "")
                except json.JSONDecodeError:
                    url = raw_arg
            else:
                url = raw_arg

        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not html_content:
            html_content = params.get("html", "")
        if not url:
            url = params.get("url", "")

        result = run_all(html_content, url, robots=params.get("robots"),
                         max_pdfs=params.get("max_pdfs", 3))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
