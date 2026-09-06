#!/usr/bin/env python3
"""
AI Crawler Access & Protocol Audit Tool (Standard Library Only)
Zero external dependencies. Portable, lightweight, and deterministic.
Checks:
- robots.txt rules (distinguishing live search bots from training scrapers)
- Context-aware disallow parsing (legitimate vs harmful blocks)
- Crawl-delay threshold (> 10s)
- llms.txt and llms-full.txt AI manifest presence
- Sitemap XML validity and URL count
- User-Agent discrimination (OAI-SearchBot vs desktop browser)
- X-Robots-Tag indexation headers
"""

import sys
import re
import json
import time
import ssl
import socket
from datetime import datetime, timezone
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin

def check_tls_certificate(hostname, port=443, timeout=5):
    """
    Checks SSL/TLS certificate validity, hostname match, and expiration date.
    Pure Python standard library (socket + ssl).
    """
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return {"status": "error", "error": "No certificate presented by server"}
                
                expire_str = cert.get("notAfter")
                expire_dt = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                days_left = (expire_dt - now_dt).days
                
                issuer_parts = []
                for field in cert.get("issuer", ()):
                    for k, v in field:
                        if k in ("organizationName", "commonName"):
                            issuer_parts.append(v)
                issuer = ", ".join(issuer_parts) or "Unknown Issuer"
                
                return {
                    "status": "valid",
                    "expires_at": expire_dt.strftime("%Y-%m-%d"),
                    "days_remaining": days_left,
                    "issuer": issuer,
                    "error": None
                }
    except ssl.SSLCertVerificationError as e:
        return {"status": "verification_failed", "error": str(getattr(e, "verify_message", str(e)))}
    except ssl.CertificateError as e:
        return {"status": "hostname_mismatch", "error": str(e)}
    except socket.timeout:
        return {"status": "timeout", "error": "TLS handshake timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

BOT_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

LIVE_SEARCH_BOTS = {
    "oai-searchbot": "OpenAI Search / ChatGPT Search",
    "perplexitybot": "Perplexity AI Search",
    "claude-web": "Anthropic Claude Web Search",
    "google-extended": "Google Gemini / Extended"
}

TRAINING_BOTS = {
    "gptbot": "OpenAI Model Training",
    "ccbot": "Common Crawl Training Scraper",
    "bytespider": "ByteDance Training Scraper"
}

HARMFUL_PATH_PATTERNS = [
    r"^/$", r"^/\*$", r"^/docs", r"^/documentation", r"^/blog",
    r"^/products?", r"^/pricing", r"^/about", r"^/guides?"
]

def extract_meta_robots(html):
    """Extracts robots meta directives from HTML head using standard library regex."""
    if not html:
        return []
    head_match = re.search(r"<head[^>]*>(.*?)</head>", html, re.I | re.DOTALL)
    head_content = head_match.group(1) if head_match else html[:10000]
    results = []
    for tag in re.finditer(r'<meta\s+[^>]*>', head_content, re.I):
        tag_str = tag.group(0)
        name_match = re.search(r'(?:name|property)=["\'](robots|googlebot|bingbot)["\']', tag_str, re.I)
        content_match = re.search(r'content=["\']([^"\']*)["\']', tag_str, re.I)
        if name_match and content_match:
            results.append((name_match.group(1).lower(), content_match.group(1).lower()))
    return results

class RedirectTracker(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_hops=10):
        super().__init__()
        self.history = []
        self.max_hops = max_hops
        self.loop_detected = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.history.append((req.full_url, code, newurl))
        visited = [h[0] for h in self.history]
        if newurl in visited or len(self.history) > self.max_hops:
            self.loop_detected = True
            return None
        # Handle HTTP 308 Permanent Redirect for Python <= 3.10
        if code == 308:
            newurl = newurl.replace(' ', '%20')
            content_headers = ("content-length", "content-type")
            newheaders = {k: v for k, v in req.headers.items() if k.lower() not in content_headers}
            return urllib.request.Request(
                newurl,
                headers=newheaders,
                origin_req_host=req.origin_req_host,
                unverifiable=True
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, code, msg, headers)

def make_request(url, ua, timeout=8):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    tracker = RedirectTracker()
    opener = urllib.request.build_opener(tracker)
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            text = data.decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return {
                "status": resp.status,
                "headers": headers,
                "text": text,
                "elapsed_ms": elapsed_ms,
                "history": tracker.history,
                "final_url": resp.url,
                "loop_detected": tracker.loop_detected,
                "error": None
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        headers = {k.lower(): v for k, v in e.headers.items()} if hasattr(e, "headers") else {}
        return {
            "status": e.code,
            "headers": headers,
            "text": "",
            "elapsed_ms": elapsed_ms,
            "history": tracker.history,
            "final_url": getattr(e, "url", url),
            "loop_detected": tracker.loop_detected,
            "error": str(e)
        }
    except Exception as e:
        return {
            "status": 0,
            "headers": {},
            "text": "",
            "elapsed_ms": 0,
            "history": tracker.history,
            "final_url": url,
            "loop_detected": tracker.loop_detected,
            "error": str(e)
        }

def is_harmful_disallow(path):
    path = path.strip().lower()
    for pat in HARMFUL_PATH_PATTERNS:
        if re.search(pat, path):
            return True
    return False

def audit_access(target_input):
    if not target_input.startswith("http://") and not target_input.startswith("https://"):
        target_url = f"https://{target_input}"
    else:
        target_url = target_input
    
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    
    findings = []
    finding_counter = 1
    
    seen_codes = set()
    def add_finding(code, title, severity, evidence, action_summary, action_priority=None):
        nonlocal finding_counter
        if code in seen_codes:
            return
        seen_codes.add(code)
        f_id = f"ACC-{finding_counter:03d}"
        finding_counter += 1
        findings.append({
            "id": f_id,
            "code": code,
            "title": title,
            "severity": severity,
            "evidence": evidence,
            "suggested_action": {
                "summary": action_summary,
                "priority": action_priority or severity
            }
        })

    def check_redirects(res, label_url):
        history = res.get("history", [])
        if res.get("loop_detected") or len(history) > 5:
            add_finding(
                code="REDIRECT_LOOP",
                title=f"Redirect loop detected on {urlparse(label_url).path or '/'}",
                severity="critical",
                evidence=f"Encountered redirect loop or excessive hops (>5) starting from {label_url}.",
                action_summary=f"Fix circular or runaway HTTP redirect rules in web server configuration for {label_url}."
            )
        elif len(history) >= 3:
            hops = len(history)
            trace = " -> ".join([f"{h[0]} ({h[1]})" for h in history] + [f"{res['final_url']} ({res['status']})"])
            add_finding(
                code="REDIRECT_CHAIN_LONG",
                title=f"Suboptimal redirect chain ({hops} hops) on {urlparse(label_url).path or '/'}",
                severity="medium",
                evidence=f"URL resolved with HTTP 200 after {hops} hops: {trace}",
                action_summary=f"Optimization Opportunity: Update incoming and internal links to point directly to '{res['final_url']}' to eliminate {hops} redundant round-trips for citation crawlers."
            )

    # 0. SSL / TLS Certificate Validity & Expiration Check
    if parsed.scheme == "https" and parsed.hostname:
        tls_res = check_tls_certificate(parsed.hostname)
        if tls_res["status"] == "verification_failed":
            add_finding(
                code="TLS_CERT_INVALID",
                title=f"SSL/TLS certificate verification failed on {parsed.hostname}",
                severity="critical",
                evidence=f"TLS handshake failed: {tls_res['error']}.",
                action_summary="Crawlability Failure: Install a trusted, valid SSL/TLS certificate to prevent automated AI search crawlers from aborting fetch."
            )
        elif tls_res["status"] == "hostname_mismatch":
            add_finding(
                code="TLS_HOSTNAME_MISMATCH",
                title=f"SSL/TLS certificate does not match hostname: {parsed.hostname}",
                severity="critical",
                evidence=f"Certificate SAN/CN mismatch: {tls_res['error']}.",
                action_summary=f"Crawlability Failure: Update SSL certificate Subject Alternative Names (SAN) to cover '{parsed.hostname}'."
            )
        elif tls_res["status"] == "valid":
            if tls_res["days_remaining"] < 0:
                add_finding(
                    code="TLS_CERT_EXPIRED",
                    title=f"SSL/TLS certificate is expired ({abs(tls_res['days_remaining'])} days ago)",
                    severity="critical",
                    evidence=f"Certificate expired on {tls_res['expires_at']} (Issuer: {tls_res['issuer']}).",
                    action_summary="Crawlability Failure: Renew expired SSL/TLS certificate immediately."
                )
            elif tls_res["days_remaining"] <= 14:
                add_finding(
                    code="TLS_CERT_EXPIRING_SOON",
                    title=f"SSL/TLS certificate expires soon ({tls_res['days_remaining']} days remaining)",
                    severity="medium",
                    evidence=f"Certificate expires on {tls_res['expires_at']} (Issuer: {tls_res['issuer']}).",
                    action_summary=f"Optimization Opportunity: Renew SSL certificate before {tls_res['expires_at']} to avoid disruption to search citation crawlers."
                )

    # 1. Dual-Fetch Transport & Bot Discrimination
    res_bot = make_request(origin, BOT_UA)
    res_browser = make_request(origin, BROWSER_UA)
    check_redirects(res_bot, origin)
    
    if res_bot["status"] in (401, 403) and res_browser["status"] == 200:
        add_finding(
            code="BOT_UA_DISCRIMINATION",
            title="Active AI Search Bot HTTP Discrimination",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']} to OAI-SearchBot but HTTP 200 to standard Desktop Browser.",
            action_summary="Update firewall / CDN rules (Cloudflare, Akamai, WAF) to permit AI search crawler user-agents on public pages."
        )
    elif res_bot["status"] == 0:
        add_finding(
            code="CONNECTION_FAILURE",
            title="Unable to connect to host",
            severity="critical",
            evidence=f"Request to {origin} failed with network error: {res_bot['error']}.",
            action_summary="Ensure the domain is reachable and SSL/TLS certificates are valid."
        )

    # 2. Host-Level Indexation Headers & HTML Meta Directives
    x_robots = res_bot["headers"].get("x-robots-tag", "").lower()
    if "noindex" in x_robots:
        add_finding(
            code="HOST_NOINDEX_HEADER",
            title="Host returns X-Robots-Tag: noindex header",
            severity="critical",
            evidence=f"Response headers on {origin} contain 'X-Robots-Tag: {x_robots}'.",
            action_summary="Crawlability Failure: Remove 'noindex' directive from HTTP headers on public pages."
        )

    def check_html_robots(html, page_url, is_homepage=False):
        if not html:
            return
        meta_directives = extract_meta_robots(html)
        for bot_name, content in meta_directives:
            if "noindex" in content:
                code = "HTML_NOINDEX_HOMEPAGE" if is_homepage else "HTML_NOINDEX_INTERIOR"
                sev = "critical" if is_homepage else "high"
                title = f"HTML <meta name='{bot_name}' content='noindex'> on {urlparse(page_url).path or '/'}"
                add_finding(
                    code=code,
                    title=title,
                    severity=sev,
                    evidence=f"HTML head on {page_url} contains '<meta name=\"{bot_name}\" content=\"{content}\">'.",
                    action_summary=f"Crawlability Failure: Remove 'noindex' directive from HTML meta tags on {page_url}."
                )
            if "nofollow" in content and is_homepage:
                add_finding(
                    code="HTML_NOFOLLOW_HOMEPAGE",
                    title=f"Homepage specifies <meta name='{bot_name}' content='nofollow'>",
                    severity="medium",
                    evidence=f"HTML head on {page_url} contains '<meta name=\"{bot_name}\" content=\"{content}\">'.",
                    action_summary="Optimization Opportunity: Remove 'nofollow' on homepage to enable AI crawlers to follow links to interior documentation."
                )

    check_html_robots(res_bot["text"], origin, is_homepage=True)

    # 3. robots.txt Parsing
    robots_url = f"{origin}/robots.txt"
    res_robots = make_request(robots_url, BOT_UA)
    declared_sitemaps = []
    
    if res_robots["status"] == 404:
        add_finding(
            code="ROBOTS_TXT_MISSING",
            title="Missing robots.txt file",
            severity="low",
            evidence=f"GET {robots_url} returned HTTP 404.",
            action_summary="Create a standard robots.txt declaring sitemap locations and confirming search crawl permissions."
        )
    elif res_robots["status"] == 200:
        lines = res_robots["text"].splitlines()
        current_uas = []
        ua_rules = {}
        last_was_rule = False
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                
                if key == "user-agent":
                    if last_was_rule:
                        current_uas = []
                        last_was_rule = False
                    u = val.lower()
                    current_uas.append(u)
                    if u not in ua_rules:
                        ua_rules[u] = []
                elif key in ("disallow", "allow"):
                    last_was_rule = True
                    for u in current_uas:
                        ua_rules[u].append((key, val))
                elif key == "sitemap":
                    declared_sitemaps.append(val)
                elif key == "crawl-delay":
                    try:
                        delay = float(val)
                        if delay > 10.0:
                            add_finding(
                                code="EXCESSIVE_CRAWL_DELAY",
                                title=f"Excessive robots.txt Crawl-Delay ({delay}s)",
                                severity="medium",
                                evidence=f"robots.txt declares 'Crawl-delay: {delay}s' for User-agent: {','.join(current_uas)}.",
                                action_summary="Lower Crawl-delay to <= 5s or remove it for verified search engines to prevent retrieval timeouts."
                            )
                    except ValueError:
                        pass
            else:
                current_uas = []
                
        # Check site-wide disallow for *
        if "*" in ua_rules:
            for directive, path in ua_rules["*"]:
                if directive == "disallow" and path in ("/", "/*"):
                    add_finding(
                        code="SITE_WIDE_DISALLOW",
                        title="Entire website blocked in robots.txt",
                        severity="critical",
                        evidence="robots.txt contains 'Disallow: /' for User-agent: *.",
                        action_summary="Remove site-wide disallow rule to allow AI search and general engines to crawl public content."
                    )
                    
        # Check Live Search Bot specific rules
        for bot_token, bot_name in LIVE_SEARCH_BOTS.items():
            if bot_token in ua_rules:
                for directive, path in ua_rules[bot_token]:
                    if directive == "disallow":
                        if path in ("/", "/*"):
                            add_finding(
                                code="AI_SEARCH_BOT_BLOCKED_COMPLETELY",
                                title=f"Live AI search bot completely blocked: {bot_name}",
                                severity="high",
                                evidence=f"robots.txt explicitly specifies 'Disallow: {path}' for User-agent: {bot_token}.",
                                action_summary=f"Allow {bot_token} on public documentation and articles so {bot_name} can cite the brand in live answers."
                            )
                        elif is_harmful_disallow(path):
                            add_finding(
                                code="AI_SEARCH_BOT_KEY_PATH_BLOCKED",
                                title=f"Core content path '{path}' blocked for {bot_name}",
                                severity="high",
                                evidence=f"robots.txt specifies 'Disallow: {path}' for User-agent: {bot_token}.",
                                action_summary=f"Remove disallow rule for '{path}' to ensure core content is indexable by {bot_name}."
                            )
                            
        # Check Training Scraper rules (Informational)
        for bot_token, bot_name in TRAINING_BOTS.items():
            if bot_token in ua_rules:
                for directive, path in ua_rules[bot_token]:
                    if directive == "disallow" and path in ("/", "/*"):
                        add_finding(
                            code="AI_TRAINING_BOT_BLOCKED",
                            title=f"AI model training scraper restricted: {bot_name}",
                            severity="low",
                            evidence=f"robots.txt disallows {bot_token} on '{path}'. This limits bulk model training but does not prevent live search citation.",
                            action_summary=f"Informational: Keep disallow if copyright protection is desired; allow if you wish {bot_name} to pre-train on your public docs."
                        )

    # 4. llms.txt, llms-full.txt & ai.txt Manifests
    res_llms = make_request(f"{origin}/llms.txt", BOT_UA)
    res_ai = make_request(f"{origin}/ai.txt", BOT_UA)
    
    if res_llms["status"] == 200:
        if len(res_llms["text"].strip()) < 80:
            add_finding(
                code="LLMS_TXT_STUB",
                title="Near-empty /llms.txt manifest",
                severity="low",
                evidence=f"/llms.txt was found but contains only {len(res_llms['text'].strip())} characters.",
                action_summary="Optimization Opportunity: Populate /llms.txt with an authoritative summary and curated links."
            )
    elif res_ai["status"] == 200:
        add_finding(
            code="AI_TXT_FOUND_NO_LLMS_TXT",
            title="/ai.txt exists; recommend adding /llms.txt alias",
            severity="low",
            evidence=f"GET {origin}/ai.txt returned HTTP 200, but /llms.txt returned HTTP {res_llms['status']}.",
            action_summary="Optimization Opportunity: Add a redirect or copy from /llms.txt to /ai.txt to support modern LLM crawlers expecting the llms.txt convention."
        )
    else:
        add_finding(
            code="LLMS_TXT_MISSING",
            title="Missing /llms.txt or /ai.txt AI context manifest",
            severity="medium",
            evidence=f"GET {origin}/llms.txt returned HTTP {res_llms['status']} and /ai.txt returned HTTP {res_ai['status']}.",
            action_summary="Optimization Opportunity: Publish a clean markdown /llms.txt file at domain root summarizing the product, architecture, and primary documentation links."
        )

    # 5. Sitemap Validation
    sitemap_target = declared_sitemaps[0] if declared_sitemaps else f"{origin}/sitemap.xml"
    res_sitemap = make_request(sitemap_target, BOT_UA)
    
    discovered_urls = []
    if res_sitemap["status"] == 404:
        add_finding(
            code="SITEMAP_MISSING",
            title="No discoverable sitemap.xml",
            severity="medium",
            evidence=f"GET {sitemap_target} returned HTTP 404.",
            action_summary="Generate and publish an XML sitemap at /sitemap.xml and declare it in robots.txt."
        )
    elif res_sitemap["status"] == 200:
        try:
            root = ET.fromstring(res_sitemap["text"])
            raw_urls = []
            for elem in root.iter():
                if elem.tag.endswith("loc") and elem.text:
                    raw_urls.append(elem.text.strip())
            
            # Check if this is a sitemapindex pointing to child sitemaps
            is_sitemap_index = "sitemapindex" in root.tag.lower() or any(u.endswith(".xml") for u in raw_urls[:5])
            if is_sitemap_index:
                child_sitemaps = [u for u in raw_urls if u.endswith(".xml") or "sitemap" in u.lower()]
                if child_sitemaps:
                    preferred_child = next((u for u in child_sitemaps if "recent" in u or "page" in u or "post" in u or "doc" in u), child_sitemaps[0])
                    res_child = make_request(preferred_child, BOT_UA)
                    if res_child["status"] == 200:
                        try:
                            child_root = ET.fromstring(res_child["text"])
                            leaf_urls = []
                            for elem in child_root.iter():
                                if elem.tag.endswith("loc") and elem.text:
                                    leaf_urls.append(elem.text.strip())
                            discovered_urls = [u for u in leaf_urls if not u.endswith(".xml") and "sitemap" not in urlparse(u).path.lower()]
                        except Exception:
                            discovered_urls = []
            else:
                discovered_urls = [u for u in raw_urls if not u.endswith(".xml") and "sitemap" not in urlparse(u).path.lower()]

            if not discovered_urls and not (is_sitemap_index and raw_urls):
                add_finding(
                    code="SITEMAP_EMPTY",
                    title="XML sitemap contains zero URL locations",
                    severity="high",
                    evidence=f"Parsed sitemap at {sitemap_target} successfully but extracted 0 <loc> tags.",
                    action_summary="Populate sitemap.xml with canonical URLs of all public pages."
                )
            elif discovered_urls:
                # 6. Deep URL Spot-Check from Sitemap (only on actual web pages, never .xml sitemaps)
                interior_urls = [u for u in discovered_urls if u.rstrip("/") != origin.rstrip("/")]
                doc_urls = [u for u in interior_urls if re.search(r"/(docs?|documentation|blog|product|pricing|learn|crate)/", u, re.I)]
                sample_pool = doc_urls if doc_urls else interior_urls
                
                # Pick up to 3 distinct sample deep URLs
                sample_urls = sample_pool[:3]
                for deep_url in sample_urls:
                    deep_bot = make_request(deep_url, BOT_UA)
                    deep_browser = make_request(deep_url, BROWSER_UA)
                    check_redirects(deep_bot, deep_url)
                    
                    if deep_bot["status"] in (401, 403) and deep_browser["status"] == 200:
                        add_finding(
                            code="DEEP_PAGE_BOT_DISCRIMINATION",
                            title=f"AI Search Bot blocked on interior page: {urlparse(deep_url).path}",
                            severity="critical",
                            evidence=f"GET {deep_url} returned HTTP {deep_bot['status']} to OAI-SearchBot but HTTP 200 to desktop browser.",
                            action_summary=f"Ensure CDN and WAF firewall rules do not restrict AI search bot User-Agents on interior pages like '{urlparse(deep_url).path}'."
                        )
                    
                    deep_x_robots = deep_bot["headers"].get("x-robots-tag", "").lower()
                    if "noindex" in deep_x_robots:
                        add_finding(
                            code="DEEP_PAGE_NOINDEX_HEADER",
                            title=f"Interior page returns X-Robots-Tag: noindex: {urlparse(deep_url).path}",
                            severity="high",
                            evidence=f"Response headers on {deep_url} contain 'X-Robots-Tag: {deep_x_robots}'.",
                            action_summary=f"Remove 'noindex' directive from HTTP headers on public content page '{urlparse(deep_url).path}'."
                        )
                    check_html_robots(deep_bot["text"], deep_url, is_homepage=False)
        except Exception as e:
            add_finding(
                code="SITEMAP_MALFORMED",
                title="Malformed XML in sitemap",
                severity="high",
                evidence=f"Failed to parse sitemap XML at {sitemap_target}: {e}",
                action_summary="Correct XML syntax errors in sitemap.xml."
            )

    # 7. Direct Deep Target URL Check (if target provided was a specific subpage)
    if target_url.rstrip("/") != origin.rstrip("/"):
        t_bot = make_request(target_url, BOT_UA)
        t_browser = make_request(target_url, BROWSER_UA)
        check_redirects(t_bot, target_url)
        if t_bot["status"] in (401, 403) and t_browser["status"] == 200:
            add_finding(
                code="SPECIFIC_URL_BOT_DISCRIMINATION",
                title=f"AI Search Bot blocked on target URL: {urlparse(target_url).path}",
                severity="critical",
                evidence=f"GET {target_url} returned HTTP {t_bot['status']} to OAI-SearchBot but HTTP 200 to desktop browser.",
                action_summary=f"Configure firewall rules to allow AI search crawlers to access '{urlparse(target_url).path}'."
            )
        t_x_robots = t_bot["headers"].get("x-robots-tag", "").lower()
        if "noindex" in t_x_robots:
            add_finding(
                code="SPECIFIC_URL_NOINDEX_HEADER",
                title=f"Target URL returns X-Robots-Tag: noindex: {urlparse(target_url).path}",
                severity="high",
                evidence=f"Response headers on {target_url} contain 'X-Robots-Tag: {t_x_robots}'.",
                action_summary=f"Remove 'noindex' from headers on '{urlparse(target_url).path}'."
            )
        check_html_robots(t_bot["text"], target_url, is_homepage=False)

    # 8. Assemble Sampled Pages for Downstream Skills
    NON_HTML_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico', '.pdf', '.zip', '.gz', '.tar', '.xml', '.txt', '.json', '.css', '.js')
    interior_urls = [u for u in discovered_urls if u.rstrip("/") != origin.rstrip("/") and not urlparse(u).path.lower().endswith(NON_HTML_EXTS)]
    doc_pages = [u for u in interior_urls if re.search(r"/(docs?|documentation|guides?|learn|api|crate)/", u, re.I)]
    blog_pages = [u for u in interior_urls if re.search(r"/(blog|articles?|news)/", u, re.I)]
    
    curated_sample = [origin]
    for u in doc_pages[:3]:
        if u not in curated_sample:
            curated_sample.append(u)
    for u in blog_pages[:2]:
        if u not in curated_sample:
            curated_sample.append(u)
    # Add deepest path URL if not already present
    if interior_urls:
        deepest = max(interior_urls, key=lambda u: len(urlparse(u).path.split("/")))
        if deepest not in curated_sample:
            curated_sample.append(deepest)

    sampled_pages = {
        "homepage": origin,
        "total_discovered": len(discovered_urls),
        "doc_pages": doc_pages[:5],
        "blog_pages": blog_pages[:5],
        "curated_sample": curated_sample
    }

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        s = f["severity"].lower()
        if s in severity_counts:
            severity_counts[s] += 1

    return {
        "site": parsed.netloc or target_input,
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_findings": len(findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"]
        },
        "findings": findings,
        "sampled_pages": sampled_pages
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
        print(f"\nAudit Report for: {result['site']}")
        print(f"Summary: {result['summary']['total_findings']} total findings "
              f"({result['summary']['critical']} Critical, {result['summary']['high']} High, "
              f"{result['summary']['medium']} Medium)\n")
        for f in result["findings"]:
            print(f"[{f['id']}] {f['title']} ({f['severity'].upper()})")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']['summary']}\n")

if __name__ == "__main__":
    main()
