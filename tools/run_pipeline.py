#!/usr/bin/env python3
"""
run_pipeline.py - Runs Stage A + Stage B + Stage C across every site in sites.csv,
                  then produces a cross-site aggregate report.

Usage:
    export GEMINI_API_KEY="your_key_here"
    export OPENROUTER_API_KEY="your_key_here"
    python tools/run_pipeline.py

Expects sites.csv at the repo root with a header row including a "url"
column (see sites.csv template). Writes results per site to:
    audits/{domain}/skill_findings.json        (Stage A, from test_pipeline.py)
    audits/{domain}/ground_truth_findings.json (Stage B, blind agent)
    audits/{domain}/stage_c_scorecard.json     (Stage C, LLM judge)

After all sites complete, writes:
    audits/aggregate_report.json               (cross-site roll-up)

Stage C is skipped for a site if either Stage A or Stage B output is missing.
The aggregate step is skipped if no Stage C scorecards exist yet.
"""

import os
import sys
import csv
import time
import subprocess
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # allow "from stage_b import ..."
from stage_b import run_stage_b
from stage_c import run_stage_c

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root
SITES_CSV = os.path.join(ROOT_DIR, "sites.csv")
TEST_PIPELINE = os.path.join(ROOT_DIR, "test_pipeline.py")


def format_url(raw_url):
    raw_url = raw_url.strip()
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = "https://" + raw_url
    return raw_url


def main():
    if not os.path.isfile(SITES_CSV):
        print(f"[ERROR] sites.csv not found at {SITES_CSV}")
        sys.exit(1)

    with open(SITES_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} sites from sites.csv\n")

    results = []
    for i, row in enumerate(rows, 1):
        raw_url = row.get("url", "").strip()
        if not raw_url:
            continue
        url = format_url(raw_url)
        domain = urlparse(url).netloc

        print("=" * 70)
        print(f"[{i}/{len(rows)}] {domain}")
        print("=" * 70)

        status = {"domain": domain, "url": url, "stage_a": "skipped", "stage_b": "skipped", "stage_c": "skipped"}

        # --- Stage A: run your existing skill pipeline ---
        try:
            print("  [Stage A] Running test_pipeline.py...")
            proc = subprocess.run(
                [sys.executable, TEST_PIPELINE, url],
                cwd=ROOT_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            if proc.returncode == 0:
                status["stage_a"] = "ok"
            else:
                status["stage_a"] = f"failed (exit {proc.returncode})"
                print(proc.stderr[-2000:])
        except Exception as e:
            status["stage_a"] = f"error: {e}"

        # --- Stage B: blind ground-truth agent ---
        try:
            run_stage_b(url, domain, ROOT_DIR)
            status["stage_b"] = "ok"
        except Exception as e:
            status["stage_b"] = f"error: {e}"
            print(f"  [Stage B] ERROR: {e}")

        # --- Stage C: LLM judge (compares A vs B) ---
        try:
            result = run_stage_c(domain, ROOT_DIR)
            status["stage_c"] = "ok" if result else "skipped (missing input)"
        except Exception as e:
            status["stage_c"] = f"error: {e}"
            print(f"  [Stage C] ERROR: {e}")

        results.append(status)
        print()
        time.sleep(2)  # be polite between sites

    print("=" * 70)
    print("RUN SUMMARY")
    print("=" * 70)
    for r in results:
        print(
            f"  {r['domain']:<35} "
            f"A: {r['stage_a']:<18} "
            f"B: {r['stage_b']:<18} "
            f"C: {r['stage_c']}"
        )

    # --- Aggregate: cross-site roll-up (no API calls, instant) ---
    print()
    print("=" * 70)
    print("RUNNING AGGREGATE REPORT")
    print("=" * 70)
    aggregate_script = os.path.join(ROOT_DIR, "tools", "aggregate.py")
    try:
        proc = subprocess.run(
            [sys.executable, aggregate_script],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(proc.stdout)
        if proc.returncode != 0:
            print(f"[WARNING] aggregate.py exited with code {proc.returncode}")
            if proc.stderr:
                print(proc.stderr[-1000:])
    except Exception as e:
        print(f"[WARNING] Could not run aggregate.py: {e}")


if __name__ == "__main__":
    main()