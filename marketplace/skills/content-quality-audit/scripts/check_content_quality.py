#!/usr/bin/env python3
"""
check_content_quality.py - Full-Content AI Citability & RAG Chunking Auditor

Audits the entire content of every webpage section-by-section (zero skipping)
for RAG embedding chunkability, ambiguous anaphora (orphan pronouns), low-entropy
headings, content flooding, and BLUF direct-answer standards.

Part of the brand-ai-readiness-audit suite (Gate 4: AI Citability & Content Quality).
Standard: agentskills.io
Pure Python Standard Library - Zero External Dependencies.
"""

import sys
import os
import re
import json
import argparse
from urllib.parse import urlparse, urljoin

try:
    from .http_client import fetch_raw_html, load_json_multienconding
    from .section_parser import (
        detect_archetype,
        clean_html_strip_boilerplate,
        partition_into_sections,
        get_url_depth
    )
    from .evaluator import audit_section, evaluate_page_proactive_suggestions
except (ImportError, ValueError):
    from http_client import fetch_raw_html, load_json_multienconding
    from section_parser import (
        detect_archetype,
        clean_html_strip_boilerplate,
        partition_into_sections,
        get_url_depth
    )
    from evaluator import audit_section, evaluate_page_proactive_suggestions


class ContentQualityAuditor:
    def __init__(self, target_url, input_access=None, max_pages=15, flooding_threshold=None, metrics_threshold=350):
        self.target_url = target_url
        self.input_access = input_access
        self.max_pages = max_pages
        self.flooding_threshold = flooding_threshold
        self.metrics_threshold = metrics_threshold
        self.parsed_url = urlparse(target_url)
        self.domain = self.parsed_url.netloc
        self.findings = []
        self.content_profile = {
            "pages_audited": 0,
            "total_sections_audited": 0,
            "total_words_audited": 0,
            "autonomous_chunk_ratio_pct": 100.0,
            "pages": []
        }

    def _add_finding(self, code, title, severity, evidence, suggested_action, url=None):
        finding_id = f"CNT-{len(self.findings) + 1:03d}"
        
        # Normalize severity: map "info" to "low" and ensure lowercase
        norm_severity = "low" if severity.lower() == "info" else severity.lower()
        
        # Ensure suggested_action is an object
        if isinstance(suggested_action, str):
            suggested_action = {"summary": suggested_action, "priority": norm_severity}

        self.findings.append({
            "id": finding_id,
            "code": code,
            "title": title,
            "severity": norm_severity,
            "url": url or self.target_url,
            "evidence": evidence,
            "suggested_action": suggested_action
        })

    def run(self):
        # 1. Determine list of URLs to audit
        urls_to_audit = [self.target_url]
        seen_normalized = {self.target_url.rstrip("/")}
        curated_sample = []

        if self.input_access and os.path.isfile(self.input_access):
            try:
                access_data = load_json_multienconding(self.input_access)
                if "sampled_pages" in access_data:
                    curated_sample = access_data.get("sampled_pages", {}).get("curated_sample", [])
                elif "skill_1" in access_data:
                    curated_sample = access_data.get("skill_1", {}).get("sampled_pages", {}).get("curated_sample", [])
                elif "skills" in access_data and "skill_1" in access_data["skills"]:
                    curated_sample = access_data["skills"]["skill_1"].get("sampled_pages", {}).get("curated_sample", [])
            except Exception:
                pass

        if curated_sample:
            for item in curated_sample:
                u = item.get("url") if isinstance(item, dict) else item
                if u and u.rstrip("/") not in seen_normalized:
                    urls_to_audit.append(u)
                    seen_normalized.add(u.rstrip("/"))

        # Tier 2 Fallback: If fewer than 5 URLs were supplied (e.g. standalone run or missing upstream sample),
        # crawl internal links from root HTML to ensure comprehensive multi-page coverage
        if len(urls_to_audit) < 5:
            root_html, _ = fetch_raw_html(self.target_url)
            if root_html:
                base_domain = self.parsed_url.netloc.lower()
                for link_match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\']', root_html, re.I):
                    href = link_match.group(1).strip()
                    if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
                        continue
                    full_u = urljoin(self.target_url, href)
                    p_u = urlparse(full_u)
                    if p_u.netloc.lower() == base_domain and p_u.scheme in ("http", "https"):
                        clean_u = f"{p_u.scheme}://{p_u.netloc}{p_u.path}".rstrip("/")
                        if clean_u not in seen_normalized:
                            seen_normalized.add(clean_u)
                            urls_to_audit.append(clean_u)
                            if len(urls_to_audit) >= self.max_pages:
                                break

        # Cap to at most max_pages
        urls_to_audit = urls_to_audit[:self.max_pages]
        self.content_profile["pages_audited"] = len(urls_to_audit)

        total_sections = 0
        autonomous_sections = 0

        for page_url in urls_to_audit:
            p_sec, p_auto = self._audit_single_page(page_url)
            total_sections += p_sec
            autonomous_sections += p_auto

        if total_sections > 0:
            pct = round((autonomous_sections / total_sections) * 100, 1)
            self.content_profile["autonomous_chunk_ratio_pct"] = pct

        return self.to_dict()

    def _audit_single_page(self, page_url):
        depth = get_url_depth(page_url)
        raw_html, err = fetch_raw_html(page_url)
        if err or not raw_html:
            self.content_profile.setdefault("pages", []).append({
                "url": page_url,
                "depth": depth,
                "status": 0,
                "error": err or "Empty response",
                "archetype": "unknown",
                "sections_count": 0,
                "word_count": 0,
                "headings": []
            })
            self._add_finding(
                code="PAGE_FETCH_ERROR",
                title=f"Failed to fetch content on {urlparse(page_url).path or '/'}: {err or 'Empty response'}",
                severity="HIGH",
                evidence=f"Request to {page_url} failed: {err or 'Empty response'}",
                suggested_action="Ensure the server is responsive and that firewalls do not block automated search crawler requests.",
                url=page_url
            )
            return 0, 0

        archetype = detect_archetype(page_url)
        cleaned_html = clean_html_strip_boilerplate(raw_html)
        sections = partition_into_sections(cleaned_html)

        page_word_count = sum(s["word_count"] for s in sections)
        self.content_profile["total_words_audited"] += page_word_count
        self.content_profile["total_sections_audited"] += len(sections)

        self.content_profile["pages"].append({
            "url": page_url,
            "depth": depth,
            "status": 200,
            "error": None,
            "archetype": archetype,
            "sections_count": len(sections),
            "word_count": page_word_count,
            "headings": [s["heading"] for s in sections if s["level"] > 0]
        })

        substantive_sections = 0
        autonomous_sections = 0

        # Section-by-Section Full Content Audit (Zero Skipping)
        for idx, sec in enumerate(sections):
            is_substantive, is_autonomous = audit_section(
                sec, idx, archetype, page_url, self._add_finding, self.flooding_threshold
            )
            if is_substantive:
                substantive_sections += 1
                if is_autonomous:
                    autonomous_sections += 1

        # Page-Level Proactive Info Checks (Zero Severity Penalty)
        evaluate_page_proactive_suggestions(
            page_url, archetype, page_word_count, cleaned_html, self._add_finding, self.metrics_threshold
        )

        return substantive_sections, autonomous_sections

    def to_dict(self):
        summary = {
            "total_findings": len(self.findings),
            "critical": sum(1 for f in self.findings if f["severity"] == "critical"),
            "high": sum(1 for f in self.findings if f["severity"] == "high"),
            "medium": sum(1 for f in self.findings if f["severity"] == "medium"),
            "low": sum(1 for f in self.findings if f["severity"] == "low")
        }
        return {
            "site": self.domain,
            "summary": summary,
            "findings": self.findings,
            "content_profile": self.content_profile
        }


def main():
    parser = argparse.ArgumentParser(description="Full-Content AI Citability & RAG Chunking Auditor")
    parser.add_argument("url", help="Target domain or root URL (e.g., https://example.com)")
    parser.add_argument("--input-access", help="Path to Skill 1 output JSON (sampled_pages)")
    parser.add_argument("--max-pages", type=int, default=15, help="Maximum pages to audit (default: 15)")
    parser.add_argument("--flooding-threshold", type=int, help="Override words limit for prose flooding")
    parser.add_argument("--metrics-threshold", type=int, default=350, help="Min words for metrics suggestion (default: 350)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON to stdout")

    args = parser.parse_args()

    url = args.url
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    auditor = ContentQualityAuditor(
        target_url=url,
        input_access=args.input_access,
        max_pages=args.max_pages,
        flooding_threshold=args.flooding_threshold,
        metrics_threshold=args.metrics_threshold
    )

    report = auditor.run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nContent Quality & AI Citability Audit for: {report['site']}")
        print(f"Pages Audited ({report['content_profile']['pages_audited']}):")
        for p in report['content_profile'].get('pages', []):
            status_desc = f"HTTP {p.get('status', 0)}" if p.get('status') else f"Failed ({p.get('error', 'Unknown')})"
            print(f"  • [Depth {p.get('depth', 0)}] [{p.get('archetype', 'general')}] {p['url']} → {p.get('sections_count', 0)} sections, {p.get('word_count', 0)} words ({status_desc})")
        print(f"\nTotal Sections: {report['content_profile']['total_sections_audited']} | "
              f"Total Words: {report['content_profile']['total_words_audited']}")
        print(f"Autonomous Chunk Ratio: {report['content_profile']['autonomous_chunk_ratio_pct']}%")
        print(f"Summary: {report['summary']['total_findings']} total findings "
              f"({report['summary']['critical']} Critical, {report['summary']['high']} High, "
              f"{report['summary']['medium']} Medium, {report['summary']['low']} Low)\n")

        for f in report["findings"]:
            print(f"[{f['code']}] {f['title']} ({f['severity'].upper()})")
            print(f"  Url:      {f['url']}")
            print(f"  Evidence: {f['evidence']}")
            if isinstance(f['suggested_action'], dict):
                print(f"  Action:   {f['suggested_action'].get('summary', '')}\n")
            else:
                print(f"  Action:   {f['suggested_action']}\n")


if __name__ == "__main__":
    main()
