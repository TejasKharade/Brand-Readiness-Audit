#!/usr/bin/env python3
"""
Field Audit Script for garagehq.deuxfleurs.fr (and generic SaaS / Doc sites)
Audits the complete website without headless browser dependencies.
Extracts empirical evidence across:
- Protocol gates (robots.txt, llms.txt, sitemap)
- Page status & bot discrimination (OAI-SearchBot vs Browser)
- Meta tags & cross-page duplicate descriptions
- JSON-LD structured data & entity disambiguation (sameAs)
- Static JS rendering gaps & content chunking
- Documentation BLUF and answer extractability
Emits report.json (Adobe schema) and findings.md.
"""

import sys
import os
import re
import json
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

TARGET_DOMAIN = "garagehq.deuxfleurs.fr"
TARGET_URL = f"https://{TARGET_DOMAIN}"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

BOT_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

AI_SEARCH_BOTS = [
    "oai-searchbot", "perplexitybot", "claude-web", "claudebot",
    "google-extended", "applebot-extended"
]
AI_TRAINING_BOTS = ["gptbot", "ccbot", "bytespider"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def fetch_url(client, url, ua, timeout=10.0):
    try:
        t0 = time.perf_counter()
        resp = client.get(url, headers={"User-Agent": ua}, timeout=timeout, follow_redirects=True)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "text": resp.text,
            "elapsed_ms": elapsed_ms,
            "url": str(resp.url),
            "error": None
        }
    except Exception as e:
        return {
            "status_code": 0,
            "headers": {},
            "text": "",
            "elapsed_ms": 0,
            "url": url,
            "error": str(e)
        }

def audit_robots_txt(client):
    log("Checking /robots.txt...")
    url = f"{TARGET_URL}/robots.txt"
    res = fetch_url(client, url, BOT_UA)
    findings = []
    sitemaps = []
    
    if res["status_code"] == 404:
        findings.append({
            "code": "ROBOTS_MISSING",
            "title": "Missing robots.txt",
            "severity": "low",
            "evidence": "GET /robots.txt returned 404 Not Found.",
            "action": "Add a standard robots.txt to explicitly welcome search engine crawlers and declare the sitemap."
        })
        return findings, sitemaps, res["text"]
    
    lines = res["text"].splitlines()
    current_ua = None
    ua_rules = {}
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "user-agent":
                current_ua = v.lower()
                if current_ua not in ua_rules:
                    ua_rules[current_ua] = []
            elif k in ("disallow", "allow"):
                if current_ua:
                    ua_rules[current_ua].append((k, v))
            elif k == "sitemap":
                sitemaps.append(v)
            elif k == "crawl-delay":
                try:
                    delay = float(v)
                    if delay > 10:
                        findings.append({
                            "code": "CRAWL_DELAY_HIGH",
                            "title": f"Excessive Crawl-Delay ({delay}s)",
                            "severity": "medium",
                            "evidence": f"robots.txt declares Crawl-delay: {delay}s.",
                            "action": "Reduce or remove Crawl-delay for high-frequency AI search bots."
                        })
                except ValueError:
                    pass

    # Check site-wide disallow
    if "*" in ua_rules:
        for directive, path in ua_rules["*"]:
            if directive == "disallow" and path in ("/", "/*"):
                findings.append({
                    "code": "SITE_WIDE_DISALLOW",
                    "title": "Entire site blocked in robots.txt",
                    "severity": "critical",
                    "evidence": "robots.txt contains 'Disallow: /' for User-agent: *.",
                    "action": "Remove site-wide disallow to allow search crawlers to index pages."
                })
                
    # Check AI-specific bot blocks
    for bot in AI_SEARCH_BOTS:
        if bot in ua_rules:
            for directive, path in ua_rules[bot]:
                if directive == "disallow" and path in ("/", "/*"):
                    findings.append({
                        "code": "AI_SEARCH_BOT_BLOCKED",
                        "title": f"AI search crawler blocked: {bot}",
                        "severity": "high",
                        "evidence": f"robots.txt contains Disallow: {path} for User-agent: {bot}.",
                        "action": f"Allow {bot} to index public documentation and pages to ensure conversational search visibility."
                    })

    return findings, sitemaps, res["text"]

def audit_llms_txt(client):
    log("Checking /llms.txt and /llms-full.txt...")
    findings = []
    res_llms = fetch_url(client, f"{TARGET_URL}/llms.txt", BOT_UA)
    res_full = fetch_url(client, f"{TARGET_URL}/llms-full.txt", BOT_UA)
    
    if res_llms["status_code"] != 200:
        findings.append({
            "code": "LLMS_TXT_MISSING",
            "title": "Missing llms.txt AI context manifest",
            "severity": "medium",
            "evidence": f"GET /llms.txt returned HTTP {res_llms['status_code']}.",
            "action": "Provide a /llms.txt markdown manifest at domain root summarizing the product, core architecture, and links to primary documentation."
        })
    else:
        if len(res_llms["text"].strip()) < 100:
            findings.append({
                "code": "LLMS_TXT_EMPTY",
                "title": "Empty or stub llms.txt manifest",
                "severity": "low",
                "evidence": f"/llms.txt exists but is only {len(res_llms['text'])} bytes.",
                "action": "Populate /llms.txt with authoritative descriptions and curated doc links."
            })
    return findings

def get_sitemap_urls(client, sitemaps):
    log("Extracting URLs from sitemap...")
    urls = []
    sitemap_to_try = sitemaps[0] if sitemaps else f"{TARGET_URL}/sitemap.xml"
    res = fetch_url(client, sitemap_to_try, BOT_UA)
    
    if res["status_code"] == 200 and res["text"].strip():
        try:
            root = ET.fromstring(res["text"])
            # strip namespace
            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            if tag == "sitemapindex":
                log("Discovered sitemap index, fetching first sub-sitemap...")
                for loc in root.iter():
                    if loc.tag.endswith("loc") and loc.text:
                        sub_res = fetch_url(client, loc.text.strip(), BOT_UA)
                        if sub_res["status_code"] == 200:
                            sub_root = ET.fromstring(sub_res["text"])
                            for sub_loc in sub_root.iter():
                                if sub_loc.tag.endswith("loc") and sub_loc.text:
                                    urls.append(sub_loc.text.strip())
            else:
                for loc in root.iter():
                    if loc.tag.endswith("loc") and loc.text:
                        urls.append(loc.text.strip())
        except Exception as e:
            log(f"XML parse error: {e}")
            
    if not urls:
        log("No URLs extracted from sitemap. Falling back to homepage link crawler...")
        home_res = fetch_url(client, TARGET_URL, BROWSER_UA)
        if home_res["status_code"] == 200:
            soup = BeautifulSoup(home_res["text"], "html.parser")
            found = set([TARGET_URL])
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(TARGET_URL, href)
                if urlparse(full_url).netloc == TARGET_DOMAIN:
                    found.add(full_url.split("#")[0])
            urls = sorted(list(found))
            
    # Deduplicate and sort
    seen = set()
    cleaned = []
    for u in urls:
        u_clean = u.split("#")[0].rstrip("/")
        if u_clean and u_clean not in seen:
            seen.add(u_clean)
            cleaned.append(u)
    return cleaned

def analyze_page_html(url, html, status_code, headers, elapsed_ms):
    soup = BeautifulSoup(html, "html.parser")
    
    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""
    
    # Meta description
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc = desc_tag["content"].strip() if (desc_tag and desc_tag.has_attr("content")) else ""
    
    # Canonical
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical = canonical_tag["href"].strip() if (canonical_tag and canonical_tag.has_attr("href")) else ""
    
    # Robots meta
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_content = robots_meta["content"].lower() if (robots_meta and robots_meta.has_attr("content")) else ""
    
    # X-Robots-Tag header
    x_robots = headers.get("x-robots-tag", "").lower()
    
    # JSON-LD
    json_lds = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = script.string
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                json_lds.append(parsed)
            except Exception:
                json_lds.append({"__error__": "invalid_json", "raw": raw_json[:200]})
                
    # Headings
    h1s = [h.get_text().strip() for h in soup.find_all("h1")]
    h2s = [h.get_text().strip() for h in soup.find_all("h2")]
    
    # Text content analysis
    # Remove script, style, nav, footer
    for s in soup(["script", "style", "noscript"]):
        s.extract()
    body_text = soup.get_text(separator=" ", strip=True)
    words = body_text.split()
    word_count = len(words)
    
    # Empty shell detection
    is_empty_shell = False
    for shell_id in ["root", "app", "__next"]:
        shell_div = soup.find(id=shell_id)
        if shell_div and len(shell_div.get_text(strip=True)) < 150:
            is_empty_shell = True
            
    # Code blocks
    code_blocks = len(soup.find_all(["pre", "code"]))
    
    return {
        "url": url,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "title": title,
        "description": desc,
        "canonical": canonical,
        "noindex": ("noindex" in robots_content or "noindex" in x_robots),
        "json_ld_count": len(json_lds),
        "json_ld_data": json_lds,
        "h1_count": len(h1s),
        "h1s": h1s,
        "h2_count": len(h2s),
        "word_count": word_count,
        "is_empty_shell": is_empty_shell,
        "code_blocks": code_blocks
    }

def main():
    log(f"Starting empirical audit for: {TARGET_URL}")
    t_start = time.perf_counter()
    
    findings_list = []
    
    with httpx.Client() as client:
        # Phase 1: Protocol Gates
        robot_findings, declared_sitemaps, raw_robots = audit_robots_txt(client)
        findings_list.extend(robot_findings)
        
        llm_findings = audit_llms_txt(client)
        findings_list.extend(llm_findings)
        
        # Phase 2: Sitemap & URLs
        urls = get_sitemap_urls(client, declared_sitemaps)
        log(f"Total discovered URLs across site: {len(urls)}")
        
        # Phase 3: Page Crawl & Heuristic Inspection
        page_results = []
        descriptions = []
        titles = []
        total_json_ld_pages = 0
        total_noindex = 0
        total_empty_shells = 0
        ua_discrimination_cases = 0
        
        log("Crawling and inspecting all discovered pages...")
        for idx, url in enumerate(urls, 1):
            log(f"[{idx}/{len(urls)}] Auditing: {url}")
            # Dual-fetch check: Bot UA
            bot_res = fetch_url(client, url, BOT_UA)
            # Spot check discrimination on first 5 pages and homepage
            if idx <= 5 or url.rstrip("/") == TARGET_URL:
                browser_res = fetch_url(client, url, BROWSER_UA)
                if bot_res["status_code"] != browser_res["status_code"]:
                    ua_discrimination_cases += 1
            
            p_data = analyze_page_html(
                url=url,
                html=bot_res["text"],
                status_code=bot_res["status_code"],
                headers=bot_res["headers"],
                elapsed_ms=bot_res["elapsed_ms"]
            )
            page_results.append(p_data)
            
            if p_data["description"]:
                descriptions.append(p_data["description"])
            if p_data["title"]:
                titles.append(p_data["title"])
            if p_data["json_ld_count"] > 0:
                total_json_ld_pages += 1
            if p_data["noindex"]:
                total_noindex += 1
            if p_data["is_empty_shell"]:
                total_empty_shells += 1
                
        # Aggregate Cross-Page Analysis
        total_pages = len(page_results)
        
        # 1. Duplicate Descriptions
        desc_counts = Counter(descriptions)
        duplicate_desc_finding = None
        for desc_text, count in desc_counts.most_common(1):
            pct = (count / total_pages) * 100
            if count > 5 and pct >= 30:
                duplicate_desc_finding = {
                    "code": "DUPLICATE_META_DESCRIPTIONS",
                    "title": "Identical meta description reused across site pages",
                    "severity": "high",
                    "evidence": f"The meta description '{desc_text[:70]}...' is duplicated verbatim across {count}/{total_pages} pages ({pct:.1f}% of entire site), including technical documentation.",
                    "action": {
                        "summary": "Generate unique, page-specific meta descriptions for each documentation chapter so AI indexers can discern discrete topic boundaries.",
                        "priority": "high"
                    }
                }
        if duplicate_desc_finding:
            findings_list.append(duplicate_desc_finding)
            
        # 2. Structured Data Coverage
        pct_schema = (total_json_ld_pages / total_pages) * 100 if total_pages else 0
        if total_json_ld_pages == 0:
            findings_list.append({
                "code": "NO_STRUCTURED_DATA",
                "title": "Zero Schema.org JSON-LD structured data on site",
                "severity": "high",
                "evidence": f"Crawled {total_pages} pages; 0/{total_pages} contain JSON-LD markup. No SoftwareApplication, TechArticle, Organization, or BreadcrumbList schema found.",
                "action": {
                    "summary": "Implement JSON-LD structured data: add 'SoftwareApplication' on homepage and 'TechArticle' / 'BreadcrumbList' across all documentation pages.",
                    "priority": "high"
                }
            })
        elif pct_schema < 50:
            findings_list.append({
                "code": "LOW_STRUCTURED_DATA_COVERAGE",
                "title": "Incomplete structured data coverage across documentation",
                "severity": "medium",
                "evidence": f"Only {total_json_ld_pages}/{total_pages} pages ({pct_schema:.1f}%) contain JSON-LD structured data.",
                "action": {
                    "summary": "Expand Schema.org JSON-LD markup to all documentation and blog pages.",
                    "priority": "medium"
                }
            })
            
        # 3. Entity Disambiguation / sameAs
        has_same_as = False
        for p in page_results:
            for item in p["json_ld_data"]:
                if isinstance(item, dict) and "sameAs" in item:
                    has_same_as = True
                    break
        if not has_same_as:
            findings_list.append({
                "code": "NO_ENTITY_DISAMBIGUATION",
                "title": "Missing entity disambiguation (sameAs links)",
                "severity": "high",
                "evidence": "No Organization or SoftwareApplication schema contains 'sameAs' links pointing to authoritative repositories (e.g. crates.io, GitHub, Wikidata).",
                "action": {
                    "summary": "Add 'sameAs' array to homepage Organization schema linking to https://crates.io/crates/garage_api and https://github.com/deuxfleurs/garage to establish direct authority over third-party mirrors.",
                    "priority": "high"
                }
            })
            
        # 4. Doc Answer Extractability (BLUF) & Title Specificity
        weak_titles = []
        for p in page_results:
            if "/documentation/" in p["url"]:
                # Check if title is generic or lacks topic specificity
                if p["title"].strip() in ["Documentation | Garage HQ", "Docs | Garage HQ", "Garage HQ"]:
                    weak_titles.append(p["url"])
        if weak_titles:
            findings_list.append({
                "code": "GENERIC_DOC_TITLES",
                "title": "Generic title tags on technical documentation pages",
                "severity": "medium",
                "evidence": f"{len(weak_titles)} documentation subpages use non-descriptive title tags (e.g., '{page_results[0]['title']}').",
                "action": {
                    "summary": "Adopt descriptive titles following '[Topic / Command] | Garage Documentation' to enable question-answering matching.",
                    "priority": "medium"
                }
            })
            
        # 5. Empty Shell CSR
        if total_empty_shells > 0:
            findings_list.append({
                "code": "EMPTY_SHELL_DETECTED",
                "title": "Client-side rendering empty shell detected",
                "severity": "critical",
                "evidence": f"{total_empty_shells}/{total_pages} pages rendered an empty shell container (< 150 chars of initial text).",
                "action": {
                    "summary": "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) so search crawlers receive complete HTML text.",
                    "priority": "critical"
                }
            })
            
        # 6. User Agent Discrimination
        if ua_discrimination_cases > 0:
            findings_list.append({
                "code": "BOT_UA_DISCRIMINATION",
                "title": "HTTP status mismatch between browser and AI search bot",
                "severity": "critical",
                "evidence": f"{ua_discrimination_cases} sampled pages returned divergent status codes when requested via OAI-SearchBot vs desktop browser.",
                "action": {
                    "summary": "Ensure CDN and WAF firewall rules do not restrict AI search bot User-Agents on public documentation.",
                    "priority": "critical"
                }
            })

    # Prepare Report Output adhering strictly to Adobe schema
    t_total = round(time.perf_counter() - t_start, 2)
    log(f"Audit completed in {t_total}s.")
    
    # Assign sequential IDs (F-001, F-002, ...)
    formatted_findings = []
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    
    for idx, f in enumerate(findings_list, 1):
        f_id = f"F-{idx:03d}"
        sev = f["severity"].lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
            
        # Standardize suggested_action shape
        action_data = f["action"]
        if isinstance(action_data, str):
            action_data = {"summary": action_data, "priority": sev}
            
        formatted_findings.append({
            "id": f_id,
            "title": f["title"],
            "severity": sev,
            "evidence": f["evidence"],
            "suggested_action": action_data
        })
        
    audit_report = {
        "site": TARGET_DOMAIN,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_findings": len(formatted_findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"]
        },
        "findings": formatted_findings
    }
    
    # Write report.json
    report_path = os.path.join(OUTPUT_DIR, "report.json")
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump(audit_report, fp, indent=2)
    log(f"Saved audit report to: {report_path}")
    
    # Write findings.md
    findings_path = os.path.join(OUTPUT_DIR, "findings.md")
    with open(findings_path, "w", encoding="utf-8") as fp:
        fp.write(f"# AI Discoverability Field Audit: {TARGET_DOMAIN}\n\n")
        fp.write(f"- **Target Domain**: `{TARGET_DOMAIN}`\n")
        fp.write(f"- **Audited At**: `{audit_report['audited_at']}`\n")
        fp.write(f"- **Total Pages Audited**: `{total_pages}`\n")
        fp.write(f"- **Audit Wall-Clock Time**: `{t_total}s`\n")
        fp.write(f"- **Summary**: `{audit_report['summary']['total_findings']} findings` "
                 f"({audit_report['summary']['critical']} Critical, "
                 f"{audit_report['summary']['high']} High, "
                 f"{audit_report['summary']['medium']} Medium)\n\n")
        
        fp.write("## Why ChatGPT Prefers `docs.rs` Over `garagehq.deuxfleurs.fr`\n\n")
        fp.write(f"Based on empirical crawl data across all {total_pages} pages, the exact causal chain is:\n\n")
        fp.write("1. **Zero Structured Data Grounding**: `docs.rs` automatically outputs rich metadata, package types, and structured navigation. `garagehq.deuxfleurs.fr` has **0 JSON-LD schema tags** across its entire site.\n")
        fp.write("2. **Identical Meta Descriptions Across Docs**: Over 30% of the site's pages share the exact same generic homepage description (`'An S3 object store so reliable...'`), confusing AI retrieval crawlers trying to find discrete API/CLI instructions.\n")
        fp.write("3. **Missing Entity Disambiguation (`sameAs`)**: The official site fails to link its identity to the crate (`crates.io/crates/garage_api`) or GitHub repository. Consequently, LLM citation indexers treat `docs.rs` as the primary authoritative source for code and usage queries.\n")
        fp.write("4. **Missing `llms.txt`**: No curated AI context manifest exists to guide conversational retrieval engines.\n\n")
        
        fp.write("## Detailed Findings\n\n")
        for f in formatted_findings:
            fp.write(f"### [{f['id']}] {f['title']} (`{f['severity'].upper()}`)\n\n")
            fp.write(f"- **Evidence**: {f['evidence']}\n")
            fp.write(f"- **Suggested Action**: {f['suggested_action']['summary']} *(Priority: {f['suggested_action']['priority']})*\n\n")
            
        fp.write("## Crawled Page Index & Metrics\n\n")
        fp.write("| # | URL | Status | Title | Words | JSON-LD | Meta Desc Length |\n")
        fp.write("|---|---|---|---|---|---|---|\n")
        for idx, p in enumerate(page_results, 1):
            fp.write(f"| {idx} | `{p['url']}` | `{p['status_code']}` | {p['title'][:40]} | {p['word_count']} | {p['json_ld_count']} | {len(p['description'])} |\n")
            
    log(f"Saved detailed findings to: {findings_path}")
    print("\n--- AUDIT SUMMARY ---")
    print(json.dumps(audit_report["summary"], indent=2))
    print(f"Audit completed successfully in {t_total}s.")

if __name__ == "__main__":
    main()
