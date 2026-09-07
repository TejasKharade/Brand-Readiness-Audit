#!/usr/bin/env python3
"""
Raw HTTP fetcher simulating an AI SearchBot crawler (Pass A).
Pure standard library. Zero external dependencies.
"""

import time
import urllib.request
import urllib.error

try:
    from .constants import BOT_UA
except (ImportError, ValueError):
    from constants import BOT_UA


def fetch_pass_a(url, timeout=15):
    """
    Pass A: Fast raw HTTP GET from the perspective of an AI SearchBot.
    Simulates OAI-SearchBot and measures direct server response latency.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BOT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    last_err = None
    for attempt in range(2):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
                html = data.decode("utf-8", errors="replace")
                return {
                    "status": resp.status,
                    "html": html,
                    "final_url": resp.url,
                    "elapsed_ms": elapsed_ms,
                    "error": None
                }
        except urllib.error.HTTPError as e:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            data = e.read() if hasattr(e, "read") else b""
            html = data.decode("utf-8", errors="replace")
            return {
                "status": e.code,
                "html": html,
                "final_url": getattr(e, "url", url),
                "elapsed_ms": elapsed_ms,
                "error": str(e)
            }
        except Exception as e:
            last_err = e
            time.sleep(0.5)

    return {
        "status": 0,
        "html": "",
        "final_url": url,
        "elapsed_ms": 0,
        "error": str(last_err)
    }
