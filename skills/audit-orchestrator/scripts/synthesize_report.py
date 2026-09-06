import sys
import json
from datetime import datetime, timezone

def calculate_category_score(findings, category_name):
    base_score = 100.0
    for f in findings:
        if f.get("category") == category_name:
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

def calculate_overall_readiness_score(category_scores):
    if not category_scores:
        return 100.0
    avg = sum(category_scores.values()) / len(category_scores)
    return max(0.0, min(100.0, round(avg, 1)))

def extract_audited_urls(site_url, skill_outputs):
    urls = set()
    if site_url:
        urls.add(site_url)

    for skill_name, data in skill_outputs.items():
        if not isinstance(data, dict):
            continue
        # Direct URL keys
        for key in ["url", "homepage_url", "site"]:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                urls.add(val.strip())
        
        # Nested URL objects/lists
        pages = data.get("pages")
        if isinstance(pages, list):
            for p in pages:
                if isinstance(p, dict) and "url" in p and isinstance(p["url"], str):
                    urls.add(p["url"].strip())

        key_urls = data.get("key_content_reachability")
        if isinstance(key_urls, list):
            for item in key_urls:
                if isinstance(item, dict) and "key_content_url" in item and isinstance(item["key_content_url"], str):
                    urls.add(item["key_content_url"].strip())

    return max(1, len(urls))

def add_finding(findings, category, title, severity, evidence, suggested_summary, priority=None):
    if priority is None:
        priority = severity
    finding_id = f"F-{len(findings)+1:03d}"
    findings.append({
        "id": finding_id,
        "category": category,
        "title": title,
        "severity": severity.lower(),
        "evidence": evidence,
        "suggested_action": {
            "summary": suggested_summary,
            "priority": priority.lower()
        }
    })

def synthesize_report(site_url, skill_outputs=None, explicit_findings=None, proactive_recommendations=None):
    if skill_outputs is None:
        skill_outputs = {}
    if explicit_findings is None:
        explicit_findings = []
    if proactive_recommendations is None:
        proactive_recommendations = []

    findings = list(explicit_findings)

    # 1. Crawl Access Skill Findings
    access = skill_outputs.get("crawl_access", {})
    if access:
        robots = access.get("robots", {})
        if robots.get("malformed"):
            add_finding(
                findings, "crawl_access",
                "Malformed robots.txt returning HTML instead of plain text",
                "critical",
                f"URL {robots.get('resolved_url')} returned HTML content instead of plain text directives.",
                "Serve robots.txt with text/plain Content-Type and valid directives."
            )
        for agent, dis_list in robots.get("disallowed", {}).items():
            if isinstance(dis_list, list) and "/" in dis_list:
                add_finding(
                    findings, "crawl_access",
                    f"AI Crawler '{agent}' is completely blocked by robots.txt",
                    "critical",
                    f"robots.txt contains Disallow: / for User-agent: {agent}.",
                    f"Update robots.txt to allow {agent} access to public brand content."
                )

        dual = access.get("dual_identity", {})
        if dual.get("bot_blocked") or dual.get("bot_challenged"):
            add_finding(
                findings, "crawl_access",
                "AI Bot Identity HTTP Fetch Blocked or Challenged",
                "critical",
                f"Browser status {dual.get('browser_status')} succeeded while AI Bot status {dual.get('bot_status')} was blocked/challenged.",
                "Remove Cloudflare/WAF challenge rules targeting AI bot User-Agents."
            )

        page_sig = access.get("page_signals", {})
        if page_sig.get("is_noindex"):
            add_finding(
                findings, "crawl_access",
                "Robots meta tag contains noindex directive",
                "critical",
                f"Page URL {page_sig.get('url')} specifies meta name='robots' content='noindex'.",
                "Remove noindex directive from main brand content pages."
            )

        sitemap = access.get("sitemap", {})
        if sitemap.get("sitemap_found") is False:
            add_finding(
                findings, "crawl_access",
                "Missing or Unreachable XML Sitemap",
                "high",
                "No valid sitemap found at /sitemap.xml or declared in robots.txt.",
                "Generate and submit a clean XML sitemap at /sitemap.xml."
            )

    # 2. Crawl Render Skill Findings
    render = skill_outputs.get("crawl_render", {})
    if render:
        barriers = render.get("rendering_barriers", {})
        if barriers.get("is_thin_initial_content"):
            add_finding(
                findings, "crawl_render",
                "Severe Initial HTML Hydration Gap (Client-side Rendering Barrier)",
                "high",
                f"Initial raw HTML contains only {barriers.get('raw_word_count')} words vs {barriers.get('rendered_word_count')} words in rendered DOM.",
                "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) for core pages."
            )

        sd_hydr = render.get("structured_data_hydration", {}).get("hydration_analysis", {})
        if sd_hydr.get("structured_data_hydration_barrier_detected"):
            trapped = sd_hydr.get("js_trapped_schema_types", [])
            add_finding(
                findings, "crawl_render",
                "Structured Data JSON-LD Trapped Behind JS Execution",
                "high",
                f"Schema entities {trapped} are injected dynamically via JS and invisible to raw HTML scrapers.",
                "Inject JSON-LD script blocks directly into static raw HTML responses."
            )

        js_redirect = render.get("client_side_redirects", {})
        if js_redirect.get("is_js_redirect_detected"):
            add_finding(
                findings, "crawl_render",
                "Client-side JavaScript or Meta Refresh Redirect Detected",
                "medium",
                f"Page performs client-side redirect to {js_redirect.get('target_url')}.",
                "Replace client-side redirects with HTTP 301/302 server redirects."
            )

    # 3. Readability Skill Findings
    readability = skill_outputs.get("readability", {})
    if readability:
        struct_data = readability.get("structured_data", {})
        if struct_data and struct_data.get("recognized_entities_count", 0) == 0:
            add_finding(
                findings, "readability",
                "Missing Schema.org JSON-LD Structured Data",
                "high",
                "Zero recognized Schema.org entities detected on target page.",
                "Add Schema.org JSON-LD markup matching page entity (Organization, Product, Article, etc.)."
            )

        semantic = readability.get("semantic_structure", {})
        if semantic.get("h1_missing"):
            add_finding(
                findings, "readability",
                "Missing primary <h1> header tag",
                "medium",
                "Page HTML contains no <h1> tag for topic orientation.",
                "Add a clear, topic-defining <h1> tag at the top of the page content."
            )

    # 4. Freshness & Corroboration Skill Findings
    freshness = skill_outputs.get("freshness_corroboration", {})
    if freshness:
        citations = freshness.get("citation_consistency", {})
        if citations.get("contains_contradiction"):
            add_finding(
                findings, "freshness_corroboration",
                "Off-site Citation Contradiction Detected",
                "high",
                f"External web search snippets contradict on-site claims for fact '{citations.get('fact_type')}'.",
                "Audit external brand mentions and update third-party profiles for accurate citation consistency."
            )

        entities = freshness.get("entity_disambiguation", {})
        if entities and entities.get("has_wikidata_or_wikipedia_sameas") is False:
            add_finding(
                findings, "freshness_corroboration",
                "Missing Authoritative sameAs Links in Organization Schema",
                "medium",
                "Organization schema lacks sameAs links pointing to Wikipedia, Wikidata, or official social profiles.",
                "Add verified sameAs links (Wikidata, Wikipedia, LinkedIn) to Organization JSON-LD."
            )

    # 5. Engagement Skill Findings
    engagement = skill_outputs.get("engagement", {})
    if engagement:
        reach = engagement.get("navigation_reachability", {})
        for item in reach.get("key_content_reachability", []):
            if item.get("directly_linked_from_homepage") is False:
                add_finding(
                    findings, "engagement",
                    "Key Content URL Unreachable from Homepage 1-Level Navigation",
                    "medium",
                    f"URL {item.get('key_content_url')} is not directly linked from the homepage.",
                    "Add direct navigation or footer links to key content pages from the homepage."
                )

        depth = engagement.get("content_depth", {})
        if depth.get("below_reference_range"):
            add_finding(
                findings, "engagement",
                "Thin Content Depth Below Reference Range",
                "medium",
                f"Page word count ({depth.get('visible_word_count')}) is below reference minimum ({depth.get('reference_min_word_count')}) for type '{depth.get('page_type_hint')}'.",
                "Expand page content depth with comprehensive details, FAQs, and specs."
            )

        mobile = engagement.get("mobile_responsiveness", {})
        if mobile.get("viewport_and_media_query_both_absent"):
            add_finding(
                findings, "engagement",
                "Missing Mobile Viewport Meta Tag",
                "high",
                "Page HTML lacks <meta name='viewport'> tag, causing rendering friction on mobile devices.",
                "Add <meta name='viewport' content='width=device-width, initial-scale=1'> to page <head>."
            )

        speed = engagement.get("page_speed_signals", {})
        if speed and len(speed.get("resource_fetch_errors", [])) > 0:
            add_finding(
                findings, "engagement",
                "External CSS/JS Resource Fetch Errors Encountered",
                "low",
                f"{len(speed.get('resource_fetch_errors'))} external stylesheet/script resource fetches failed or returned HTTP errors.",
                "Verify external asset availability and clean up broken resource references."
            )

    # Calculate Category Scores
    category_names = ["crawl_access", "crawl_render", "readability", "freshness_corroboration", "engagement"]
    category_scores = {cat: calculate_category_score(findings, cat) for cat in category_names}
    overall_score = calculate_overall_readiness_score(category_scores)

    # Severity Summary Counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["medium"] += 1

    audited_pages_cnt = extract_audited_urls(site_url, skill_outputs)
    skills_invoked_cnt = max(1, len([k for k in skill_outputs if skill_outputs[k]]))

    default_recs = [
        "Ensure robots.txt allows access to AI crawler user-agents (GPTBot, PerplexityBot, ClaudeBot).",
        "Implement Server-Side Rendering (SSR) so raw HTML responses contain full text and JSON-LD schema.",
        "Add authoritative sameAs references (Wikidata, Wikipedia, LinkedIn) to Organization schema markup.",
        "Ensure key product/service landing pages are directly linked from homepage navigation.",
        "Include <meta name='viewport' content='width=device-width, initial-scale=1'> on all page templates."
    ]

    report = {
        "site": site_url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "brand_ai_readiness_score": overall_score,
        "category_scores": category_scores,
        "summary": {
            "total_findings": len(findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": findings,
        "proactive_recommendations": proactive_recommendations or default_recs,
        "audit_metadata": {
            "audited_pages_count": audited_pages_cnt,
            "skills_invoked_count": skills_invoked_cnt,
            "marketplace_version": "1.0.0"
        }
    }
    return report

import threading

def read_stdin_safe(timeout=0.2):
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
    return res[0] if res else ""

if __name__ == "__main__":
    try:
        params = {}

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params["site"] = raw_arg
            else:
                params["site"] = raw_arg

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=0.2)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        site_url = params.get('site') or params.get('url', 'https://example.com')
        skill_outputs = params.get('skill_outputs', {})
        explicit_findings = params.get('findings', [])
        recommendations = params.get('proactive_recommendations', [])

        report = synthesize_report(site_url, skill_outputs, explicit_findings, recommendations)
        print(json.dumps(report, indent=2))
    except Exception as e:
        print(json.dumps({
            "site": None,
            "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "brand_ai_readiness_score": 0.0,
            "category_scores": {
                "crawl_access": 0.0, "crawl_render": 0.0, "readability": 0.0,
                "freshness_corroboration": 0.0, "engagement": 0.0
            },
            "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
            "findings": [],
            "proactive_recommendations": [],
            "audit_metadata": {
                "audited_pages_count": 0,
                "skills_invoked_count": 0,
                "marketplace_version": "1.0.0"
            },
            "script_error": str(e)
        }))
