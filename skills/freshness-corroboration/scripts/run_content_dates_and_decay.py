
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import os
import json
import threading

"""Runs check_content_dates.py + check_temporal_decay.py in ONE process
instead of two. See readability-audit/scripts/run_all.py for the full
rationale. Only these two of freshness-corroboration's four scripts qualify:
both are pure in-memory parsing of this page's already-fetched html/status,
with no network I/O of their own. check_citation_consistency.py and
check_entity_disambiguation.py are deliberately NOT included here -- they
consume web-search results the orchestrating agent gathers itself (via
WebSearch), so they cannot run until after that search happens, and stay
separate calls.

Purely additive: each function is imported unchanged and called exactly as
`synthesize_report.py` already expects; the individual scripts are untouched
and still work standalone."""

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from check_content_dates import check_content_dates
from check_temporal_decay import check_temporal_decay


def run_all(html_content, url, status=None):
    out = {}
    for key, fn in (("content_dates", check_content_dates),
                    ("temporal_decay", check_temporal_decay)):
        try:
            out[key] = fn(html_content, url, status=status)
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
    return res[0] if res else ""


if __name__ == "__main__":
    try:
        params = {}
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    pass

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        html_content = params.get("html", "")
        url = params.get("url", "")

        result = run_all(html_content, url, status=params.get("status"))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
