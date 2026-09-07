#!/usr/bin/env python3
"""
JavaScript Rendering & Semantic Parity Audit Tool (Pure Standard Library)
Zero external dependencies. Portable, deterministic, and sandbox-safe.

Entrypoint orchestrator coordinating Pass A (raw HTTP) and Pass B (hydrated DOM)
semantic parity audits across discovered site archetypes.
"""

import sys
import os
import json
import time
from urllib.parse import urlparse

try:
    from .browser_runner import find_headless_browser
    from .http_fetcher import fetch_pass_a
    from .feature_extractor import extract_features
    from .parity_evaluator import audit_render_parity
except (ImportError, ValueError):
    from browser_runner import find_headless_browser
    from http_fetcher import fetch_pass_a
    from feature_extractor import extract_features
    from parity_evaluator import audit_render_parity


def get_url_depth(u):
    """Calculates path depth of a given URL."""
    p = urlparse(u).path.strip("/")
    return len([seg for seg in p.split("/") if seg]) if p else 0


def audit_render(target_input, input_json_path=None, max_pages=15):
    """
    Main entrypoint for Skill 2. Can audit a standalone URL or consume Skill 1's output JSON.
    """
    browser_bin = find_headless_browser()

    urls_to_audit = []
    if input_json_path and os.path.exists(input_json_path):
        try:
            with open(input_json_path, "rb") as f:
                raw_bytes = f.read()
                # Support UTF-16 (Windows PowerShell '>' redirection) and UTF-8
                if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
                    content = raw_bytes.decode("utf-16", errors="replace")
                else:
                    content = raw_bytes.decode("utf-8", errors="replace")
                skill1_data = json.loads(content)
                sampled = skill1_data.get("sampled_pages", {})
                curated = sampled.get("curated_sample", [])
                if curated:
                    urls_to_audit = curated[:max_pages]
        except Exception:
            pass

    if not urls_to_audit:
        if not target_input.startswith("http://") and not target_input.startswith("https://"):
            target_url = f"https://{target_input}"
        else:
            target_url = target_input
        urls_to_audit = [target_url]

    # Tier 2 Fallback: If fewer than 5 URLs were supplied (e.g. standalone run or missing upstream sample),
    # crawl internal links from homepage HTML to ensure rich multi-page coverage
    if len(urls_to_audit) < 5:
        first_url = urls_to_audit[0]
        res_sample = fetch_pass_a(first_url)
        if res_sample.get("status") == 200:
            feat_sample = extract_features(res_sample.get("html", ""), first_url)
            discovered_internals = sorted(list(feat_sample.get("internal_links", set())), key=get_url_depth)
            for d_url in discovered_internals:
                if len(urls_to_audit) >= max_pages:
                    break
                if d_url not in urls_to_audit:
                    urls_to_audit.append(d_url)

    parsed = urlparse(urls_to_audit[0])
    site_domain = parsed.netloc

    all_findings = []
    per_page_metrics = []

    for url in urls_to_audit:
        depth = get_url_depth(url)
        res = audit_render_parity(url, browser_bin)
        all_findings.extend(res["findings"])
        m = res["metrics"]
        m["depth"] = depth
        per_page_metrics.append({
            "url": url,
            "depth": depth,
            "metrics": m
        })

    # Summary counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        s = f["severity"].lower()
        if s in severity_counts:
            severity_counts[s] += 1

    return {
        "site": site_domain,
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_findings": len(all_findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": all_findings,
        "render_profile": {
            "browser_engine": os.path.basename(browser_bin) if browser_bin else "None (Static Fallback)",
            "pages_audited": len(urls_to_audit),
            "per_page_metrics": per_page_metrics
        }
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_render.py <domain_or_url> [--input-json <path>] [--max-pages <N>] [--json]")
        sys.exit(1)

    target = sys.argv[1]
    input_json_path = None
    if "--input-json" in sys.argv:
        idx = sys.argv.index("--input-json")
        if idx + 1 < len(sys.argv):
            input_json_path = sys.argv[idx + 1]

    max_pages = 15
    if "--max-pages" in sys.argv:
        idx = sys.argv.index("--max-pages")
        if idx + 1 < len(sys.argv):
            try:
                max_pages = int(sys.argv[idx + 1])
            except ValueError:
                pass

    result = audit_render(target, input_json_path=input_json_path, max_pages=max_pages)

    if "--json" in sys.argv or not sys.stdout.isatty():
        print(json.dumps(result, indent=2))
    else:
        print(f"\nJavaScript Render & Parity Audit for: {result['site']}")
        print(f"Engine: {result['render_profile']['browser_engine']}")
        print(f"Pages Audited ({result['render_profile']['pages_audited']}):")
        for p in result['render_profile']['per_page_metrics']:
            m = p['metrics']
            print(f"  • [Depth {p.get('depth', 0)}] {p['url']} → Parity: {m.get('parity_pct', 0)}% (Pass A: {m.get('pass_a_latency_ms', 0)}ms, Pass B: {m.get('pass_b_latency_ms', 0)}ms)")
        print(f"\nSummary: {result['summary']['total_findings']} total findings "
              f"({result['summary']['critical']} Critical, {result['summary']['high']} High, "
              f"{result['summary']['medium']} Medium)\n")
        for f in result["findings"]:
            print(f"[{f['id']}] {f['title']} ({f['severity'].upper()})")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']['summary']}\n")


if __name__ == "__main__":
    main()
