#!/usr/bin/env python3
"""
HTTP client and multi-encoding JSON loader for content-quality-audit.
Pure Python Standard Library - Zero External Dependencies.
"""

import ssl
import json
import gzip
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from .constants import USER_AGENT
except (ImportError, ValueError):
    from constants import USER_AGENT


def load_json_multienconding(filepath):
    """Safely loads JSON handling UTF-8, UTF-16, and UTF-8-BOM."""
    for enc in ["utf-8-sig", "utf-16", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"Unable to parse JSON file {filepath} with any supported encoding.")


def fetch_raw_html(url, timeout=12):
    """Fetches raw HTML stream simulating AI search crawler with gzip and retry support."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    last_err = None
    for attempt in range(2):
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return None, f"Non-HTML content type: {content_type}"
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                raw_bytes = resp.read()
                if raw_bytes.startswith(b"\x1f\x8b") or resp.headers.get("content-encoding") == "gzip":
                    try:
                        raw_bytes = gzip.decompress(raw_bytes)
                    except Exception:
                        pass
                try:
                    text = raw_bytes.decode(charset, errors="replace")
                except Exception:
                    text = raw_bytes.decode("utf-8", errors="replace")
                return text, None
        except HTTPError as e:
            return None, f"HTTP {e.code} ({e.reason})"
        except Exception as e:
            last_err = f"Network Error: {str(e)}"
            if attempt == 0:
                time.sleep(1)
                continue
    return None, last_err or "Connection failed after 2 attempts"
