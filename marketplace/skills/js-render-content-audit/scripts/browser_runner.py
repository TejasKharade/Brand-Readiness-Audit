#!/usr/bin/env python3
"""
Headless browser detection and Pass B DOM hydration runner.
Pure standard library. Zero external dependencies.
"""

import os
import sys
import time
import shutil
import subprocess

try:
    from .constants import (
        BROWSER_CANDIDATES,
        WIN_PATHS,
        MAC_PATHS,
        LINUX_PATHS,
        HEADLESS_FLAGS
    )
except (ImportError, ValueError):
    from constants import (
        BROWSER_CANDIDATES,
        WIN_PATHS,
        MAC_PATHS,
        LINUX_PATHS,
        HEADLESS_FLAGS
    )


def find_headless_browser():
    """
    Auto-detects host system headless browser binary across Windows, Linux, and macOS.
    Does not require Playwright or bundled Chromium binaries.
    """
    # 1. Standard executable names on PATH
    for c in BROWSER_CANDIDATES:
        path = shutil.which(c)
        if path:
            return path

    # 2. Windows specific default installation paths
    if sys.platform == "win32":
        for p in WIN_PATHS:
            if os.path.exists(p):
                return p

    # 3. macOS specific application paths
    if sys.platform == "darwin":
        for p in MAC_PATHS:
            if os.path.exists(p):
                return p

    # 4. Linux specific common paths
    if sys.platform.startswith("linux"):
        for p in LINUX_PATHS:
            if os.path.exists(p):
                return p

    return None


def fetch_pass_b(url, browser_bin, timeout=25):
    """
    Pass B: Rendered DOM capture via native system headless browser.
    Spawns headless subprocess with --dump-dom and measures execution latency.
    """
    if not browser_bin:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": 0,
            "error": "No host headless browser detected on system."
        }

    cmd = [browser_bin] + HEADLESS_FLAGS + [url]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        stdout_text = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_text = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        if proc.returncode == 0 and stdout_text:
            return {
                "status": 200,
                "html": stdout_text,
                "elapsed_ms": elapsed_ms,
                "error": None
            }
        else:
            return {
                "status": 0,
                "html": "",
                "elapsed_ms": elapsed_ms,
                "error": f"Headless browser exited with code {proc.returncode}: {stderr_text[:200]}"
            }
    except subprocess.TimeoutExpired:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": timeout * 1000,
            "error": f"Browser rendering timed out after {timeout}s"
        }
    except Exception as e:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": 0,
            "error": str(e)
        }
