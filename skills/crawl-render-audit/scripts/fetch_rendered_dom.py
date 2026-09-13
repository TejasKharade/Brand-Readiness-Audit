
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import json

# --- robots.txt gate --------------------------------------------------------
# Every fetch in this file asks robots_gate first. The gate is built from the
# robots.txt that check_robots.py already fetched (passed in as `robots`), so
# it costs no extra request; only a standalone run fetches robots.txt itself.
import os as _os
for _d in (_os.path.dirname(_os.path.abspath(__file__)),
           _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "..", "crawl-access-audit", "scripts")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
try:
    from robots_gate import RobotsGate
except Exception:  # gate unavailable -> refuse to fetch, never fetch blind
    RobotsGate = None

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse

# ---------------------------------------------------------------------------
# Optional rendered-DOM capture using a Chromium-family browser that is
# ALREADY installed on the machine (Chrome, Edge, Chromium). Nothing is
# downloaded or bundled, and no Python dependency is needed.
#
# Its only job is to produce the `rendered_html` input that
# check_rendering_barriers.py and check_structured_data_hydration.py already
# accept -- without it they fall back to raw-HTML-only heuristics. When no
# browser is present it returns available: false and the audit continues
# exactly as before.
#
# Safety and budget:
#   * The browser sandbox stays ON. `--no-sandbox` is never passed unless the
#     caller explicitly sets allow_no_sandbox (Chrome refuses to start as root
#     on Linux without it; that trade-off belongs to the operator, not a default).
#   * A throwaway profile directory is created per run and deleted afterwards,
#     so no cookies, logins or extensions from the user's own browser are used.
#   * Images are not loaded, and a hard wall-clock timeout kills the whole
#     browser process tree, so a hanging page cannot stall the audit.
#   * Only http(s) URLs are rendered.
# ---------------------------------------------------------------------------

# 18s (down from 25s): SKILL.md's own guidance says "a typical page renders in
# 1-8s" -- 25s was headroom for a slow-but-live host, not the typical cost.
# General worst-case-ceiling trim (see check_sitemap.py's SITEMAP_FETCH_DEADLINE_S
# comment for the full reasoning); the caller may still pass a higher
# timeout_s explicitly (clamped up to 45) for a page it knows is heavy.
DEFAULT_TIMEOUT_S = 18.0
DEFAULT_SETTLE_MS = 5000          # virtual time for scripts/timers to finish after load
MAX_RENDERED_BYTES = 2 * 1024 * 1024

PATH_NAMES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "chrome", "msedge", "microsoft-edge", "microsoft-edge-stable",
]


def _windows_candidates():
    roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
             os.environ.get("LOCALAPPDATA")]
    rels = [r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe"]
    return [os.path.join(r, rel) for r in roots if r for rel in rels]


def _mac_candidates():
    return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]


def find_browser(explicit_path=None):
    if explicit_path:
        return explicit_path if os.path.isfile(explicit_path) else None
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    extra = _windows_candidates() if sys.platform == "win32" else (
        _mac_candidates() if sys.platform == "darwin" else ["/snap/bin/chromium"])
    for p in extra:
        if os.path.isfile(p):
            return p
    return None


def _kill_tree(proc):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def fetch_rendered_dom(url, timeout_s=DEFAULT_TIMEOUT_S, settle_ms=DEFAULT_SETTLE_MS,
                       browser_path=None, user_agent=None, allow_no_sandbox=False,
                       robots=None):
    result = {
        "url": url,
        "available": False,          # a browser was found and produced a DOM
        "browser": None,
        "rendered_html": "",
        "rendered_bytes": 0,
        "truncated": False,
        "elapsed_ms": None,
        "timed_out": False,
        "error": None,
        # WHY `available` is false, distinct from the free-text `error` string
        # -- "no_browser_installed" is the specific case the orchestrator must
        # disclose to the reader as an audit-environment limitation ("this run
        # could not measure client-side rendering at all"), not silently
        # absorb into a generic raw-HTML-only fallback. The other reasons are
        # either already reported elsewhere (skipped_by_robots) or genuinely
        # site/host-specific rather than an environment capability gap.
        "unavailable_reason": None,
    }

    scheme = urllib.parse.urlparse(str(url or "")).scheme.lower()
    if scheme not in ("http", "https"):
        result["error"] = "Only http(s) URLs are rendered"
        result["unavailable_reason"] = "unsupported_scheme"
        return result

    # Rendering pulls the page plus every script, stylesheet and image it
    # references -- by far the heaviest fetch this audit performs, and the one
    # it would be least defensible to run against a disallowed path.
    gate = RobotsGate.for_url(url, robots=robots) if RobotsGate else None
    if gate is not None:
        decision = gate.allows(url, user_agent or "*")
        if not decision.allowed:
            result["skipped_by_robots"] = True
            result["robots_decision"] = decision.as_dict()
            result["error"] = "Not rendered: %s" % decision.reason
            result["unavailable_reason"] = "skipped_by_robots"
            return result

    browser = find_browser(browser_path)
    if not browser:
        result["error"] = ("No Chrome/Edge/Chromium browser found on this machine; continue with raw-HTML-only "
                           "render checks (rendered_html omitted)")
        result["unavailable_reason"] = "no_browser_installed"
        return result
    result["browser"] = os.path.basename(browser)

    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0 and not allow_no_sandbox:
        result["error"] = ("Running as root: Chromium will not start with its sandbox enabled. Re-run as a "
                           "non-root user, or pass allow_no_sandbox: true if you accept disabling the sandbox")
        result["unavailable_reason"] = "root_no_sandbox"
        return result

    profile_dir = tempfile.mkdtemp(prefix="render_profile_")
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--mute-audio",
        "--hide-scrollbars",
        "--blink-settings=imagesEnabled=false",
        f"--user-data-dir={profile_dir}",
        f"--virtual-time-budget={int(settle_ms)}",
    ]
    if user_agent:
        cmd.append(f"--user-agent={user_agent}")
    if allow_no_sandbox:
        cmd.append("--no-sandbox")
    cmd += ["--dump-dom", url]

    popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    t0 = time.time()
    proc = None
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            result["timed_out"] = True
            result["error"] = f"Browser did not finish rendering within {timeout_s:.0f}s"
            result["unavailable_reason"] = "timed_out"
            return result
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        if proc.returncode != 0 or not out:
            result["error"] = f"Browser exited with code {proc.returncode} and no DOM output"
            result["unavailable_reason"] = "render_failed"
            return result
        if len(out) > MAX_RENDERED_BYTES:
            out = out[:MAX_RENDERED_BYTES]
            result["truncated"] = True
        html_text = out.decode("utf-8", errors="replace")
        result["rendered_html"] = html_text
        result["rendered_bytes"] = len(out)
        result["available"] = True
        return result
    except Exception as e:
        if proc and proc.poll() is None:
            _kill_tree(proc)
        result["error"] = f"Browser launch failed: {e}"
        result["unavailable_reason"] = "launch_failed"
        return result
    finally:
        if result["elapsed_ms"] is None:
            result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        # The browser can hold profile files open for a moment after exit.
        for _ in range(3):
            shutil.rmtree(profile_dir, ignore_errors=True)
            if not os.path.exists(profile_dir):
                break
            time.sleep(0.5)


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


def _num(v, default, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    try:
        params = {}
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params = {"url": raw_arg}
            else:
                params = {"url": raw_arg}
        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass
        out = fetch_rendered_dom(
            params.get("url") or params.get("site") or "",
            timeout_s=_num(params.get("timeout_s"), DEFAULT_TIMEOUT_S, 5, 45),
            settle_ms=_num(params.get("settle_ms"), DEFAULT_SETTLE_MS, 0, 15000),
            browser_path=params.get("browser_path"),
            user_agent=params.get("user_agent"),
            allow_no_sandbox=params.get("allow_no_sandbox") is True,
            robots=params.get("robots"),
        )
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"available": False, "rendered_html": "", "error": f"Script execution failed: {e}"}))
