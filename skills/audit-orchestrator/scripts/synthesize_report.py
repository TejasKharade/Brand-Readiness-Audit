import sys
import json
from datetime import datetime, timezone

def calculate_readiness_score(findings, category_metrics=None):
    base_score = 100.0
    
    # Deductions based on finding severity
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        if sev == "critical":
            base_score -= 20.0
        elif sev == "high":
            base_score -= 10.0
        elif sev == "medium":
            base_score -= 5.0
        elif sev == "low":
            base_score -= 2.0

    return max(0.0, min(100.0, round(base_score, 1)))

def synthesize_report(site_url, skill_outputs=None, explicit_findings=None, proactive_recommendations=None):
    if skill_outputs is None:
        skill_outputs = {}
    if explicit_findings is None:
        explicit_findings = []
    if proactive_recommendations is None:
        proactive_recommendations = []

    findings = list(explicit_findings)
    
    # 1. Synthesize Crawl Access findings
    access_data = skill_outputs.get("crawl_access", {})
    if access_data:
        robots = access_data.get("robots", {})
        if robots.get("malformed"):
            findings.append({
                "id": f"FIND-ACCESS-{len(findings)+1:03d}",
                "category": "crawl_access",
                "title": "Malformed robots.txt returning HTML page instead of plain text",
                "severity": "critical",
                "evidence": f"URL {robots.get('resolved_url')} returned HTML content instead of valid robots.txt directives.",
                "suggested_action": {
                    "summary": "Serve robots.txt as plain text (text/plain) with valid User-agent and Disallow rules.",
                    "priority": "high"
                }
            })
        for agent, dis_list in robots.get("disallowed", {}).items():
            if isinstance(dis_list, list) and len(dis_list) > 0 and "/" in dis_list:
                findings.append({
                    "id": f"FIND-ACCESS-{len(findings)+1:03d}",
                    "category": "crawl_access",
                    "title": f"AI Crawler User-Agent '{agent}' is completely blocked by robots.txt",
                    "severity": "critical",
                    "evidence": f"robots.txt contains 'Disallow: /' for User-Agent: {agent}.",
                    "suggested_action": {
                        "summary": f"Update robots.txt to allow {agent} access to public brand content.",
                        "priority": "high"
                    }
                })

    # 2. Synthesize Crawl Render findings
    render_data = skill_outputs.get("crawl_render", {})
    if render_data:
        barriers = render_data.get("rendering_barriers", {})
        if barriers.get("is_thin_initial_content"):
            findings.append({
                "id": f"FIND-RENDER-{len(findings)+1:03d}",
                "category": "crawl_render",
                "title": "Severe initial HTML hydration gap (Client-side rendering barrier)",
                "severity": "high",
                "evidence": f"Initial raw HTML contains only {barriers.get('raw_word_count')} words while rendered DOM contains {barriers.get('rendered_word_count')} words.",
                "suggested_action": {
                    "summary": "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) for core content.",
                    "priority": "high"
                }
            })
        sd_hydr = render_data.get("structured_data_hydration", {}).get("hydration_analysis", {})
        if sd_hydr.get("structured_data_hydration_barrier_detected"):
            trapped = sd_hydr.get("js_trapped_schema_types", [])
            findings.append({
                "id": f"FIND-RENDER-{len(findings)+1:03d}",
                "category": "crawl_render",
                "title": "Structured Data JSON-LD trapped behind Client-Side JavaScript execution",
                "severity": "high",
                "evidence": f"Schema entities {trapped} are dynamically injected via JS and invisible to standard scrapers.",
                "suggested_action": {
                    "summary": "Inject application/ld+json blocks directly into the static raw HTML server response.",
                    "priority": "high"
                }
            })

    # 3. Synthesize Readability findings
    readability_data = skill_outputs.get("readability", {})
    if readability_data:
        struct_data = readability_data.get("structured_data", {})
        if struct_data.get("recognized_entities_count", 0) == 0:
            findings.append({
                "id": f"FIND-READABILITY-{len(findings)+1:03d}",
                "category": "readability",
                "title": "Missing Schema.org JSON-LD structured data",
                "severity": "high",
                "evidence": "Zero recognized Schema.org entities detected on target page.",
                "suggested_action": {
                    "summary": "Add Schema.org JSON-LD markup matching page entity (Organization, Product, Article, etc.).",
                    "priority": "high"
                }
            })

    # Severity counters
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["medium"] += 1

    overall_score = calculate_readiness_score(findings)

    report = {
        "site": site_url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "brand_ai_readiness_score": overall_score,
        "summary": {
            "total_findings": len(findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": findings,
        "proactive_recommendations": proactive_recommendations or [
            "Implement SSR/SSG for core brand pages to ensure raw HTML contain full text.",
            "Embed JSON-LD schema markup directly in raw HTML response body.",
            "Verify robots.txt directives allow GPTBot, PerplexityBot, and ClaudeBot.",
            "Add authoritative sameAs links (Wikipedia, Wikidata, LinkedIn) to Organization schema."
        ]
    }
    return report

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        site_url = params.get('site') or params.get('url', 'https://example.com')
        skill_outputs = params.get('skill_outputs', {})
        explicit_findings = params.get('findings', [])
        recommendations = params.get('proactive_recommendations', [])

        report = synthesize_report(site_url, skill_outputs, explicit_findings, recommendations)
        print(json.dumps(report, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
