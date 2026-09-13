
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import os
import json
import threading

"""Runs all three crawl-render-audit analysis checks in ONE process instead
of three separate subprocess invocations. See readability-audit/scripts/
run_all.py for the full rationale -- same reasoning applies here: all three
checks are pure in-memory comparisons of already-fetched raw_html/
rendered_html strings, zero network I/O of their own (the one network call
in this skill, fetch_rendered_dom.py's headless render, stays a SEPARATE
call, since it is genuinely slow and the agent may want to run it in
parallel with other pages' fetches).

Purely additive: each function is imported unchanged and called exactly as
`synthesize_report.py` already expects; the individual scripts are untouched
and still work standalone."""

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from check_rendering_barriers import check_rendering_barriers
from check_structured_data_hydration import check_structured_data_hydration
from check_client_side_redirects import check_client_side_redirects


def run_all(raw_html, rendered_html, url):
    out = {}
    for key, fn, args in (
        ("rendering_barriers", check_rendering_barriers, (raw_html, rendered_html, url)),
        ("structured_data_hydration", check_structured_data_hydration, (raw_html, rendered_html, url)),
        ("client_side_redirects", check_client_side_redirects, (raw_html, url)),
    ):
        try:
            out[key] = fn(*args)
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
        params = {}
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    pass

        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        raw_html = params.get("raw_html", "") or params.get("html", "")
        rendered_html = params.get("rendered_html", "")
        url = params.get("url", "")

        result = run_all(raw_html, rendered_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
