#!/usr/bin/env python3
"""
check_schema.py - Structured Data, Entity Grounding, and Semantic Parity Auditor

Audits websites for Schema.org Knowledge Graph grounding, authoritative sameAs
disambiguation, atomic fact consistency (pricing, availability, versioning), and
description extractability. Distinguishes static schema from client-JS-deferred schema.

Part of the brand-ai-readiness-audit suite (Gate 3: Content Understandability & Entity Trust).
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
    from .parser import (
        extract_visible_text,
        extract_json_ld,
        get_schema_types,
        get_url_depth
    )
    from .entity_evaluator import (
        evaluate_root_entity,
        evaluate_fact_consistency,
        evaluate_description_extractability
    )
except (ImportError, ValueError):
    from http_client import fetch_raw_html, load_json_multienconding
    from parser import (
        extract_visible_text,
        extract_json_ld,
        get_schema_types,
        get_url_depth
    )
    from entity_evaluator import (
        evaluate_root_entity,
        evaluate_fact_consistency,
        evaluate_description_extractability
    )


class SchemaEntityAuditor:
    def __init__(self, target_url, input_access=None, input_render=None, max_pages=15):
        self.target_url = target_url
        self.input_access = input_access
        self.input_render = input_render
        self.max_pages = max_pages
        self.parsed_url = urlparse(target_url)
        self.domain = self.parsed_url.netloc
        self.findings = []
        self.entity_profile = {
            "root_entity_detected": False,
            "root_entity_types": [],
            "same_as_authorities": [],
            "pages_audited": 0,
            "pages_with_schema": 0,
            "schema_coverage_pct": 0.0,
            "pages": []
        }

    def _add_finding(self, code, title, severity, evidence, suggested_action, url=None):
        target_url = url or self.target_url
        for existing in self.findings:
            if existing["code"] == code and existing["url"] == target_url:
                return
        finding_id = f"ENT-{len(self.findings) + 1:03d}"
        self.findings.append({
            "id": finding_id,
            "code": code,
            "title": title,
            "severity": severity,
            "url": target_url,
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

        # Cap audit to at most max_pages
        urls_to_audit = urls_to_audit[:self.max_pages]
        self.entity_profile["pages_audited"] = len(urls_to_audit)

        # Check Skill 2 render profile for JS-deferred schema handoff
        js_timing_findings = []
        if self.input_render and os.path.isfile(self.input_render):
            try:
                render_data = load_json_multienconding(self.input_render)
                findings_list = render_data.get("findings", [])
                if not findings_list and "skill_2" in render_data:
                    findings_list = render_data.get("skill_2", {}).get("findings", [])
                for f in findings_list:
                    if f.get("code") == "STRUCTURED_DATA_TIMING":
                        js_timing_findings.append(f)
            except Exception:
                pass

        # If Skill 2 flagged deferred schema, surface it immediately
        for jf in js_timing_findings:
            self._add_finding(
                code="SCHEMA_TIMING_JS_DEFERRED",
                title="Structured data is injected via client-side JavaScript rather than static HTML",
                severity="HIGH",
                evidence=jf.get("evidence", "Schema exists in rendered DOM but is missing in raw HTTP fetch."),
                suggested_action="Embed JSON-LD <script type='application/ld+json'> in server-rendered static HTML so fast AI search bots (OAI-SearchBot) can read it without executing JavaScript.",
                url=jf.get("url", self.target_url)
            )

        # Audit each page
        for page_url in urls_to_audit:
            self._audit_single_page(
                page_url,
                is_homepage=(page_url == self.target_url or urlparse(page_url).path in ("", "/"))
            )

        if self.entity_profile["pages_audited"] > 0:
            pct = round((self.entity_profile["pages_with_schema"] / self.entity_profile["pages_audited"]) * 100, 1)
            self.entity_profile["schema_coverage_pct"] = pct

        return self.to_dict()

    def _audit_single_page(self, page_url, is_homepage=False):
        depth = get_url_depth(page_url)
        raw_html, err = fetch_raw_html(page_url)
        if err or not raw_html:
            self.entity_profile.setdefault("pages", []).append({
                "url": page_url,
                "depth": depth,
                "status": 0,
                "error": err or "Empty response",
                "schemas_found": []
            })
            self._add_finding(
                code="PAGE_FETCH_ERROR",
                title=f"Failed to fetch {urlparse(page_url).path or '/'}: {err or 'Empty response'}",
                severity="HIGH",
                evidence=f"Request to {page_url} failed: {err or 'Empty response'}",
                suggested_action="Ensure the server is responsive and that firewalls do not block automated search crawler requests.",
                url=page_url
            )
            return

        visible_text = extract_visible_text(raw_html)
        schema_nodes, syntax_errors = extract_json_ld(raw_html)

        detected_types = set()
        for sn in schema_nodes:
            detected_types.update(get_schema_types(sn))

        self.entity_profile.setdefault("pages", []).append({
            "url": page_url,
            "depth": depth,
            "status": 200,
            "error": None,
            "schemas_found": sorted(list(detected_types))
        })

        # Check 1: Syntax Validation
        for syn_err in syntax_errors:
            self._add_finding(
                code="SCHEMA_SYNTAX_INVALID",
                title=f"Malformed JSON-LD syntax on {urlparse(page_url).path or '/'}",
                severity="HIGH",
                evidence=syn_err,
                suggested_action="Ensure JSON-LD content strictly adheres to valid RFC 8259 JSON syntax without unescaped characters or unquoted attributes.",
                url=page_url
            )

        if schema_nodes:
            self.entity_profile["pages_with_schema"] += 1
        elif not is_homepage:
            self._add_finding(
                code="SCHEMA_ENTIRELY_MISSING",
                title=f"Interior page lacks any Schema.org structured data",
                severity="MEDIUM",
                evidence=f"No JSON-LD metadata found. Search engines rely on structured data to understand specific page types (e.g., Product, Article, Breadcrumb).",
                suggested_action="Embed JSON-LD <script type='application/ld+json'> on interior pages to define their specific entity type and properties.",
                url=page_url
            )

        # Check 2: Homepage Entity Root Grounding (The Garage Problem)
        if is_homepage:
            evaluate_root_entity(page_url, schema_nodes, self._add_finding, self.entity_profile)

        # Check 3: Atomic Fact Consistency (Price, Availability, Version)
        evaluate_fact_consistency(page_url, schema_nodes, visible_text, self._add_finding)

        # Check 4: Extractability & Fluff Detection
        evaluate_description_extractability(page_url, schema_nodes, self._add_finding)

    def to_dict(self):
        summary = {
            "total_findings": len(self.findings),
            "critical": sum(1 for f in self.findings if f["severity"] == "CRITICAL"),
            "high": sum(1 for f in self.findings if f["severity"] == "HIGH"),
            "medium": sum(1 for f in self.findings if f["severity"] == "MEDIUM"),
            "low": sum(1 for f in self.findings if f["severity"] == "LOW"),
            "info": sum(1 for f in self.findings if f["severity"] == "INFO")
        }
        return {
            "site": self.domain,
            "summary": summary,
            "findings": self.findings,
            "entity_profile": self.entity_profile
        }


def main():
    parser = argparse.ArgumentParser(description="Structured Data, Entity Grounding, and Semantic Parity Auditor")
    parser.add_argument("url", help="Target domain or root URL (e.g., https://example.com)")
    parser.add_argument("--input-access", help="Path to Skill 1 output JSON (sampled_pages)")
    parser.add_argument("--input-render", help="Path to Skill 2 output JSON (render_profile & timing)")
    parser.add_argument("--max-pages", type=int, default=15, help="Maximum pages to audit (default: 15)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON to stdout")

    args = parser.parse_args()

    url = args.url
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    auditor = SchemaEntityAuditor(
        target_url=url,
        input_access=args.input_access,
        input_render=args.input_render,
        max_pages=args.max_pages
    )

    report = auditor.run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nStructured Data & Entity Audit for: {report['site']}")
        print(f"Pages Audited ({report['entity_profile']['pages_audited']}) [Schema Coverage: {report['entity_profile']['schema_coverage_pct']}%]:")
        for p in report['entity_profile'].get('pages', []):
            sc_str = ", ".join(p.get("schemas_found", [])) or "None"
            status_desc = f"HTTP {p.get('status', 0)}" if p.get('status') else f"Failed ({p.get('error', 'Unknown')})"
            print(f"  • [Depth {p.get('depth', 0)}] {p['url']} → Schemas: [{sc_str}] ({status_desc})")
        print(f"\nRoot Entity: {'Found (' + ', '.join(report['entity_profile']['root_entity_types']) + ')' if report['entity_profile']['root_entity_detected'] else 'Missing'}")
        if report['entity_profile']['same_as_authorities']:
            print(f"sameAs Authorities: {', '.join(report['entity_profile']['same_as_authorities'])}")
        print(f"\nSummary: {report['summary']['total_findings']} total findings "
              f"({report['summary']['critical']} Critical, {report['summary']['high']} High, "
              f"{report['summary']['medium']} Medium, {report['summary']['low']} Low)\n")

        for f in report["findings"]:
            print(f"[{f['code']}] {f['title']} ({f['severity']})")
            print(f"  Url:      {f['url']}")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']}\n")


if __name__ == "__main__":
    main()
