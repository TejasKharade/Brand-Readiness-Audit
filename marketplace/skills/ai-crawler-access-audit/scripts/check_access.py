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
import gzip
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

def make_request(url, ua, timeout=12):
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
            headers = {k.lower(): v for k, v in resp.getheaders()}
            if data.startswith(b"\x1f\x8b") or headers.get("content-encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            text = data.decode("utf-8", errors="replace")
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
    pages_visited = []

    def get_url_depth(u):
        p = urlparse(u).path.strip("/")
        return len([seg for seg in p.split("/") if seg]) if p else 0

    def logged_request(url, ua, timeout=12, purpose=""):
        res = make_request(url, ua, timeout=timeout)
        pages_visited.append({
            "url": url,
            "depth": get_url_depth(url),
            "purpose": purpose or urlparse(url).path or "/",
            "status": res["status"],
            "elapsed_ms": res.get("elapsed_ms", 0),
            "error": res.get("error")
        })
        return res
    
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
    res_bot = logged_request(origin, BOT_UA, purpose="Root URL (AI Search Bot)")
    res_browser = logged_request(origin, BROWSER_UA, purpose="Root URL (Desktop Browser)")
    check_redirects(res_bot, origin)
    
    is_bot_blocked = False
    if (res_bot["status"] in (401, 403) or (res_bot["status"] == 0 and res_browser["status"] == 200)) and res_browser["status"] == 200:
        is_bot_blocked = True
        discrimination_type = f"HTTP {res_bot['status']}" if res_bot["status"] else f"silent network drop / timeout ({res_bot['error']})"
        add_finding(
            code="BOT_UA_DISCRIMINATION",
            title="Active AI Search Bot Discrimination (WAF Block)",
            severity="critical",
            evidence=f"GET {origin} resulted in {discrimination_type} to OAI-SearchBot but returned HTTP 200 to standard Desktop Browser.",
            action_summary="Update firewall / CDN rules (Cloudflare, Akamai, WAF) to permit AI search crawler user-agents on public pages."
        )
    elif res_bot["status"] in (401, 403):
        is_bot_blocked = True
        add_finding(
            code="HTTP_ACCESS_FORBIDDEN",
            title=f"Root URL returns HTTP {res_bot['status']} Forbidden to AI crawlers",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']}: {res_bot['error'] or 'Access Forbidden'}. Automated crawlers are rejected at the edge/origin.",
            action_summary="Update web server permissions, IP filtering, or edge CDN WAF rules to allow search crawlers to access the public site."
        )
    elif res_bot["status"] >= 500:
        is_bot_blocked = True
        add_finding(
            code="ORIGIN_SERVER_ERROR",
            title=f"Root URL returns HTTP {res_bot['status']} Server Error",
            severity="critical",
            evidence=f"GET {origin} returned HTTP {res_bot['status']}.",
            action_summary="Resolve internal server errors on the origin web application."
        )
    elif res_bot["status"] == 0:
        add_finding(
            code="CONNECTION_FAILURE",
            title="Unable to connect to host",
            severity="critical",
            evidence=f"Request to {origin} failed with network error: {res_bot['error']}.",
            action_summary="Ensure the domain is reachable and SSL/TLS certificates are valid."
        )

    # When bot is already confirmed blackholed by WAF, fail fast on secondary probes
    sub_timeout = 3 if is_bot_blocked else 12

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
    res_robots = logged_request(robots_url, BOT_UA, timeout=sub_timeout, purpose="Robots Directives (/robots.txt)")
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
    res_llms = logged_request(f"{origin}/llms.txt", BOT_UA, timeout=sub_timeout, purpose="AI Manifest (/llms.txt)")
    res_ai = logged_request(f"{origin}/ai.txt", BOT_UA, timeout=sub_timeout, purpose="AI Manifest (/ai.txt)")
    
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

    # 5. Sitemap Validation & Multi-Tier URL Discovery
    candidate_sitemaps = list(declared_sitemaps)
    standard_root_sitemap = f"{origin}/sitemap.xml"
    if standard_root_sitemap not in candidate_sitemaps:
        candidate_sitemaps.append(standard_root_sitemap)
    if f"{origin}/sitemap_index.xml" not in candidate_sitemaps:
        candidate_sitemaps.append(f"{origin}/sitemap_index.xml")

    discovered_urls = []
    sitemap_target = candidate_sitemaps[0]
    sitemap_status = 0
    sitemap_had_child_index = False
    sitemap_child_count = 0
    sitemap_empty_locs = False

    def extract_loc_urls(xml_text):
        """Extracts all <loc> values from XML string with ET and regex fallback."""
        locs = []
        is_index = False
        try:
            root = ET.fromstring(xml_text)
            root_tag = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()
            if "sitemapindex" in root_tag:
                is_index = True
            for elem in root.iter():
                tag_name = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
                if tag_name == "sitemap":
                    is_index = True
                if tag_name == "loc" and "image" not in elem.tag.lower() and "video" not in elem.tag.lower() and elem.text:
                    u_val = elem.text.strip()
                    if u_val.startswith("http://") or u_val.startswith("https://"):
                        locs.append(u_val)
        except Exception:
            pass

        if not locs:
            # Resilient fallback: regex extraction
            rx_matches = re.findall(r'<loc>\s*(https?://[^\s<]+)\s*</loc>', xml_text, re.I)
            if rx_matches:
                locs = rx_matches
                if "<sitemapindex" in xml_text.lower() or "<sitemap>" in xml_text.lower():
                    is_index = True

        if not is_index:
            if "<sitemapindex" in xml_text.lower() or any(u.endswith(".xml") or ".xml?" in u for u in locs[:5]):
                is_index = True

        return locs, is_index

    PAGE_MEDIA_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico', '.pdf', '.zip', '.gz', '.tar', '.xml', '.txt', '.json', '.css', '.js', '.m3u8', '.mp4', '.mov', '.ts', '.webm', '.avi', '.mp3', '.wav', '.woff', '.woff2')

    for candidate in candidate_sitemaps[:4]:
        res_sitemap = logged_request(candidate, BOT_UA, timeout=sub_timeout, purpose=f"XML Sitemap ({candidate})")
        sitemap_status = res_sitemap["status"]
        if res_sitemap["status"] == 200:
            sitemap_target = candidate
            raw_locs, is_index = extract_loc_urls(res_sitemap["text"])
            
            if is_index:
                sitemap_had_child_index = True
                # Child sitemaps end in .xml or .gz - do NOT filter them out
                child_sitemaps = [u for u in raw_locs if u.endswith(".xml") or u.endswith(".gz") or "sitemap" in u.lower()]
                sitemap_child_count = len(child_sitemaps)
                if child_sitemaps:
                    # Sample up to 5 child sitemaps prioritizing diverse topics
                    selected_children = []
                    for pattern in [r"[_\-/](static|main|pages)[_\-\./\?]", r"[_\-/](products?|items?|cars?|goods?)[_\-\./\?]", r"[_\-/](blog|articles?|posts?|docs?)[_\-\./\?]"]:
                        match = next((u for u in child_sitemaps if re.search(pattern, u, re.I) and u not in selected_children), None)
                        if match:
                            selected_children.append(match)
                    for u in child_sitemaps:
                        if len(selected_children) >= 5:
                            break
                        if u not in selected_children:
                            selected_children.append(u)

                    all_leaf_urls = []
                    for child_url in selected_children:
                        res_child = logged_request(child_url, BOT_UA, timeout=sub_timeout, purpose=f"Child Sitemap ({urlparse(child_url).path})")
                        if res_child["status"] == 200:
                            child_locs, _ = extract_loc_urls(res_child["text"])
                            for leaf_u in child_locs:
                                if not any(leaf_u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and "sitemap" not in urlparse(leaf_u).path.lower():
                                    all_leaf_urls.append(leaf_u)

                    discovered_urls = all_leaf_urls
            else:
                # Direct URL set
                leaf_urls = [u for u in raw_locs if not any(u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and "sitemap" not in urlparse(u).path.lower()]
                discovered_urls = leaf_urls
                if not raw_locs:
                    sitemap_empty_locs = True

            if discovered_urls:
                break

    # Tier 2: Mandatory HTML Link-Discovery Fallback (Crucial Safety Net)
    # If sitemap gave fewer than 5 URLs or failed, crawl internal links from Homepage HTML
    if len(discovered_urls) < 5:
        homepage_html = res_browser.get("text", "") or res_bot.get("text", "")
        if homepage_html:
            html_links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\']', homepage_html, re.I)
            for href in html_links:
                href = href.strip()
                if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                full_u = urljoin(origin, href)
                p_u = urlparse(full_u)
                if p_u.netloc.lower() == parsed.netloc.lower() and p_u.scheme in ("http", "https"):
                    clean_u = f"{p_u.scheme}://{p_u.netloc}{p_u.path}".rstrip("/")
                    if not any(clean_u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and clean_u not in discovered_urls and clean_u != origin.rstrip("/"):
                        discovered_urls.append(clean_u)

    # Diagnostic Findings for Sitemap
    if sitemap_status == 404 and not discovered_urls:
        add_finding(
            code="SITEMAP_MISSING",
            title="No discoverable sitemap.xml",
            severity="medium",
            evidence=f"Checked candidate sitemaps ({', '.join(candidate_sitemaps[:2])}) but received HTTP 404.",
            action_summary="Generate and publish an XML sitemap at /sitemap.xml and declare it in robots.txt."
        )
    elif sitemap_status == 200 and sitemap_empty_locs and not sitemap_had_child_index:
        add_finding(
            code="SITEMAP_EMPTY",
            title="XML sitemap contains zero URL locations",
            severity="high",
            evidence=f"Fetched sitemap candidate at {sitemap_target} (HTTP 200) but extracted 0 <loc> tags from document.",
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
            deep_bot = logged_request(deep_url, BOT_UA, purpose=f"Sample Page (AI Bot: {urlparse(deep_url).path})")
            deep_browser = logged_request(deep_url, BROWSER_UA, purpose=f"Sample Page (Browser: {urlparse(deep_url).path})")
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

    # 7. Direct Deep Target URL Check (if target provided was a specific subpage)
    if target_url.rstrip("/") != origin.rstrip("/"):
        t_bot = logged_request(target_url, BOT_UA, purpose=f"Target URL (AI Bot: {urlparse(target_url).path})")
        t_browser = logged_request(target_url, BROWSER_UA, purpose=f"Target URL (Browser: {urlparse(target_url).path})")
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

    NON_HTML_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico', '.pdf', '.zip', '.gz', '.tar', '.xml', '.txt', '.json', '.css', '.js', '.m3u8', '.mp4', '.mov', '.ts', '.webm', '.avi', '.mp3', '.wav', '.woff', '.woff2')
    valid_urls = [u for u in discovered_urls if (u.startswith("http://") or u.startswith("https://")) and not urlparse(u).path.lower().endswith(NON_HTML_EXTS)]
    interior_urls = [u for u in valid_urls if u.rstrip("/") != origin.rstrip("/")]

    # Check for Deeply Buried Important Pages (Requirement 2)
    IMPORTANT_PATTERNS = r"/(docs?|documentation|guides?|learn|api|manual|products?|items?|pricing|plans|security|trust|about|compliance|support)/"
    deep_important_pages = []
    for u in interior_urls:
        depth = get_url_depth(u)
        if depth >= 4 and re.search(IMPORTANT_PATTERNS, u, re.I):
            deep_important_pages.append((depth, u))

    if deep_important_pages:
        deep_important_pages.sort(key=lambda x: x[0], reverse=True)
        max_d, sample_deep_url = deep_important_pages[0]
        segments = [s for s in urlparse(sample_deep_url).path.strip("/").split("/") if s]
        add_finding(
            code="DEEPLY_BURIED_IMPORTANT_PAGE",
            title=f"Important page buried deep in URL path hierarchy (Depth {max_d}): {urlparse(sample_deep_url).path}",
            severity="medium",
            evidence=f"Critical page '{sample_deep_url}' is located at path depth {max_d} ({len(segments)} segments: {' / '.join(segments)}). AI search crawlers allocate significantly less crawl budget to URLs nested 4+ levels deep.",
            action_summary="Flatten URL structure to depth 2 or 3 (e.g. '/docs/topic' or '/product/name') to ensure rapid discovery and high citation priority by AI engines."
        )

    # Stratified Sampling up to Depth 3 (Requirement 1)
    pricing_pages = [u for u in interior_urls if re.search(r"/(pricing|plans|buy|subscribe)/", u, re.I)]
    doc_pages = [u for u in interior_urls if re.search(r"/(docs?|documentation|guides?|learn|api|crate)/", u, re.I)]
    product_pages = [u for u in interior_urls if re.search(r"/(products?|items?|p/|pr\?|goods?|dp/)", u, re.I) or "/p/itm" in u]
    blog_pages = [u for u in interior_urls if re.search(r"/(blog|articles?|news|posts?)/", u, re.I)]
    about_pages = [u for u in interior_urls if re.search(r"/(about|company|contact|team|security)/", u, re.I)]

    pricing_pages.sort(key=get_url_depth)
    doc_pages.sort(key=get_url_depth)
    product_pages.sort(key=get_url_depth)
    blog_pages.sort(key=get_url_depth)
    about_pages.sort(key=get_url_depth)

    curated_sample = [origin]
    sample_details = [{"url": origin, "depth": 0, "archetype": "homepage"}]

    def add_to_sample(url_list, count, arch):
        added = 0
        for u in url_list:
            if u not in curated_sample:
                curated_sample.append(u)
                sample_details.append({"url": u, "depth": get_url_depth(u), "archetype": arch})
                added += 1
                if added >= count:
                    break

    add_to_sample(pricing_pages, 2, "pricing")
    add_to_sample(doc_pages, 3, "documentation")
    add_to_sample(product_pages, 4, "product")
    add_to_sample(blog_pages, 2, "article")
    add_to_sample(about_pages, 2, "about")

    # If sample is under 15 pages, add shallowest remaining interior pages (depth <= 3)
    remaining_shallow = [u for u in interior_urls if u not in curated_sample and get_url_depth(u) <= 3]
    remaining_shallow.sort(key=get_url_depth)
    for u in remaining_shallow:
        if len(curated_sample) >= 15:
            break
        curated_sample.append(u)
        sample_details.append({"url": u, "depth": get_url_depth(u), "archetype": "general"})

    # Always ensure at least 1 deeper leaf page is sampled if available
    if len(curated_sample) < 15 and interior_urls:
        deepest = max(interior_urls, key=get_url_depth)
        if deepest not in curated_sample:
            curated_sample.append(deepest)
            sample_details.append({"url": deepest, "depth": get_url_depth(deepest), "archetype": "deep_leaf"})

    sampled_pages = {
        "homepage": origin,
        "total_discovered": len(discovered_urls),
        "doc_pages": doc_pages[:10],
        "blog_pages": blog_pages[:10],
        "product_pages": product_pages[:10],
        "curated_sample": curated_sample[:15],
        "curated_sample_details": sample_details[:15]
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
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": findings,
        "sampled_pages": sampled_pages,
        "audit_telemetry": {
            "tls_result": tls_res if parsed.scheme == "https" and parsed.hostname else None,
            "origin_status": res_bot["status"],
            "robots_txt_status": res_robots["status"],
            "llms_txt_status": res_llms["status"],
            "ai_txt_status": res_ai["status"],
            "sitemap_target": sitemap_target if discovered_urls else None,
            "sitemap_status": sitemap_status,
            "candidate_sitemaps_tested": candidate_sitemaps[:4],
            "total_discovered_urls": len(discovered_urls),
            "pages_visited": pages_visited
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
