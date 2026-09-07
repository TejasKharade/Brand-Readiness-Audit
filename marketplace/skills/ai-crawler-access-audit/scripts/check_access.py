#!/usr/bin/env python3
"""
AI Crawler Access & Protocol Audit Tool (Standard Library Only).
Zero external dependencies. Portable, lightweight, and deterministic.

Evaluates:
- SSL/TLS certificate validity, hostname match, and expiration
- User-Agent discrimination (OAI-SearchBot vs desktop browser)
- robots.txt rules (distinguishing live search bots from training scrapers)
- Host-level X-Robots-Tag indexation headers and HTML meta robots
- llms.txt, llms-full.txt, and ai.txt AI manifest presence
- Sitemap XML validity, sitemapindex traversal, and URL inventory
- Deep URL spot-checks and buried important page detection (depth >= 4)
"""

import sys
import os
import json
import time
from urllib.parse import urlparse

# Ensure local modules inside scripts/ are importable regardless of working directory
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from constants import BOT_UA
from collector import FindingCollector
from tls_checker import audit_tls
from http_client import make_request, probe_origin_access
from robots_parser import (
    audit_html_robots, audit_robots_txt, audit_ai_manifests
)
from sitemap_discovery import (
    get_url_depth, explore_sitemaps, extract_html_fallback_links,
    audit_sitemap_findings, audit_deep_urls, audit_target_subpage,
    stratified_sample_urls, audit_buried_pages
)

def audit_access(target_input):
    """
    Orchestrates the deterministic Gate 1 protocol and crawlability audit.
    Returns complete structured JSON report.
    """
    if not target_input.startswith("http://") and not target_input.startswith("https://"):
        target_url = f"https://{target_input}"
    else:
        target_url = target_input
    
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    collector = FindingCollector()

    def logged_request(url, ua=BOT_UA, timeout=12, purpose=""):
        res = make_request(url, ua=ua, timeout=timeout)
        collector.log_page(
            url=url,
            depth=get_url_depth(url),
            purpose=purpose or urlparse(url).path or "/",
            status=res["status"],
            elapsed_ms=res.get("elapsed_ms", 0),
            error=res.get("error")
        )
        return res

    # 0. SSL/TLS Certificate Audit
    tls_result = audit_tls(parsed.hostname or target_input, collector)

    # 1. User-Agent Discrimination Probe (AI Search Bot vs Standard Browser)
    res_bot, res_browser, is_bot_blocked, sub_timeout = probe_origin_access(
        origin, logged_request, collector
    )

    # 2. Host-Level Indexation Headers & HTML Meta Directives (Homepage)
    audit_html_robots(res_bot["text"], origin, collector, is_homepage=True)

    # 3. robots.txt Parsing & Rule Verification
    res_robots, declared_sitemaps = audit_robots_txt(
        origin, logged_request, collector, sub_timeout=sub_timeout
    )

    # 4. llms.txt, llms-full.txt & ai.txt Manifests
    res_llms, res_ai = audit_ai_manifests(
        origin, logged_request, collector, sub_timeout=sub_timeout
    )

    # 5. Sitemap Validation & Multi-Tier URL Discovery
    candidate_sitemaps = list(declared_sitemaps)
    for std_sm in (f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"):
        if std_sm not in candidate_sitemaps:
            candidate_sitemaps.append(std_sm)

    sitemap_result = explore_sitemaps(candidate_sitemaps, logged_request, sub_timeout=sub_timeout)
    discovered_urls = sitemap_result["discovered_urls"]

    # Tier 2: Mandatory HTML Link-Discovery Fallback
    if len(discovered_urls) < 5:
        homepage_html = res_browser.get("text", "") or res_bot.get("text", "")
        discovered_urls = extract_html_fallback_links(homepage_html, origin, parsed.netloc, discovered_urls)
        sitemap_result["discovered_urls"] = discovered_urls

    audit_sitemap_findings(sitemap_result, candidate_sitemaps, collector)

    # 6. Deep URL Spot-Check from Sitemap
    audit_deep_urls(discovered_urls, origin, logged_request, collector, audit_html_robots)

    # 7. Direct Deep Target URL Check (if target provided was a specific subpage)
    audit_target_subpage(target_url, origin, logged_request, collector, audit_html_robots)

    # 8. Stratified Sampling & Buried Page Analysis
    sampled_pages_data = stratified_sample_urls(discovered_urls, origin, max_sample=15)
    audit_buried_pages(sampled_pages_data["interior_urls"], collector)

    sampled_pages = {
        "homepage": sampled_pages_data["homepage"],
        "total_discovered": sampled_pages_data["total_discovered"],
        "doc_pages": sampled_pages_data["doc_pages"],
        "blog_pages": sampled_pages_data["blog_pages"],
        "product_pages": sampled_pages_data["product_pages"],
        "curated_sample": sampled_pages_data["curated_sample"],
        "curated_sample_details": sampled_pages_data["curated_sample_details"]
    }

    return {
        "site": parsed.netloc or target_input,
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_findings": len(collector.findings),
            **collector.get_summary()
        },
        "findings": collector.findings,
        "sampled_pages": sampled_pages,
        "audit_telemetry": {
            "tls_result": tls_result,
            "origin_status": res_bot["status"],
            "robots_txt_status": res_robots["status"],
            "llms_txt_status": res_llms["status"],
            "ai_txt_status": res_ai["status"],
            "sitemap_target": sitemap_result["sitemap_target"],
            "sitemap_status": sitemap_result["sitemap_status"],
            "candidate_sitemaps_tested": candidate_sitemaps[:3],
            "total_discovered_urls": len(discovered_urls),
            "pages_visited": collector.pages_visited
        }
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_access.py <domain_or_url> [--json]")
        sys.exit(1)

    target = sys.argv[1]
    result = audit_access(target)

    if "--json" in sys.argv or not sys.stdout.isatty():
        print(json.dumps(result, indent=2))
    else:
        print(f"\nAI Crawler Access Audit for: {result['site']}")
        print(f"Summary: {result['summary']['total_findings']} total findings "
              f"({result['summary']['critical']} Critical, {result['summary']['high']} High, "
              f"{result['summary']['medium']} Medium, {result['summary']['low']} Low)\n")
        
        telemetry = result.get("audit_telemetry", {})
        print("Telemetry:")
        print(f"  TLS Status:       {telemetry.get('tls_result', {}).get('status')} ({telemetry.get('tls_result', {}).get('days_remaining')} days remaining)")
        print(f"  Origin Status:    {telemetry.get('origin_status')}")
        print(f"  robots.txt:       HTTP {telemetry.get('robots_txt_status')}")
        print(f"  llms.txt:         HTTP {telemetry.get('llms_txt_status')}")
        print(f"  Sitemap:          HTTP {telemetry.get('sitemap_status')} ({telemetry.get('sitemap_target')})")
        print(f"  Discovered URLs:  {telemetry.get('total_discovered_urls')}")
        print(f"  Sampled for Eval: {len(result['sampled_pages']['curated_sample'])}\n")
        
        for f in result["findings"]:
            print(f"[{f['id']}] {f['title']} ({f['severity'].upper()})")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']['summary']}\n")

if __name__ == "__main__":
    main()
