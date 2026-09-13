
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import os
import json
import threading

"""Runs check_content_depth.py + check_landing_readiness.py +
check_mobile_responsive_signals.py in ONE process instead of three. See
readability-audit/scripts/run_all.py for the full rationale.

Only these three of engagement-audit's six scripts qualify for this simple
per-page bundling: each takes just this one page's already-fetched html (and
url/page_type_hint) with no network I/O and no cross-page input.
check_navigation_reachability.py and check_descriptor_consistency.py need
data gathered ACROSS pages (key-URL reachability, cross-page title/H1
comparison) and check_page_speed_signals.py does its own network fetch of
CSS/JS resources -- all three stay separate calls.

Purely additive: each function is imported unchanged and called exactly as
`synthesize_report.py` already expects; the individual scripts are untouched
and still work standalone."""

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from check_content_depth import check_content_depth
from check_landing_readiness import check_landing_readiness
from check_mobile_responsive_signals import check_mobile_responsive_signals


def run_all(html_content, url, page_type_hint="unknown"):
    out = {}
    try:
        out["content_depth"] = check_content_depth(html_content, url, page_type_hint)
    except Exception as e:
        out["content_depth"] = {"error": f"content_depth check failed: {type(e).__name__}: {e}"}
    try:
        out["landing_readiness"] = check_landing_readiness(html_content, url, page_type_hint)
    except Exception as e:
        out["landing_readiness"] = {"error": f"landing_readiness check failed: {type(e).__name__}: {e}"}
    try:
        out["mobile_responsiveness"] = check_mobile_responsive_signals(html_content)
    except Exception as e:
        out["mobile_responsiveness"] = {"error": f"mobile_responsiveness check failed: {type(e).__name__}: {e}"}
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
        page_type_hint = params.get("page_type_hint", "unknown")

        result = run_all(html_content, url, page_type_hint)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
