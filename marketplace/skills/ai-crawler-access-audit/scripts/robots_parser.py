"""
robots.txt parsing, HTML meta robots extraction, and AI manifest evaluation.
Standard library only (re, urllib.parse). Zero external dependencies.
"""

import re
from urllib.parse import urlparse

try:
    from .constants import (
        BOT_UA, LIVE_SEARCH_BOTS, TRAINING_BOTS, HARMFUL_PATH_PATTERNS
    )
except (ImportError, ValueError):
    from constants import (
        BOT_UA, LIVE_SEARCH_BOTS, TRAINING_BOTS, HARMFUL_PATH_PATTERNS
    )

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

def is_harmful_disallow(path):
    """Checks whether a disallowed path matches core content patterns."""
    path = path.strip().lower()
    for pat in HARMFUL_PATH_PATTERNS:
        if re.search(pat, path):
            return True
    return False

def parse_robots_txt(text):
    """
    Parses robots.txt text line-by-line into structured user-agent rules,
    declared sitemaps, and crawl delay settings.
    """
    lines = text.splitlines()
    current_uas = []
    ua_rules = {}
    last_was_rule = False
    declared_sitemaps = []
    crawl_delays = {}

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
                    for u in current_uas:
                        crawl_delays[u] = delay
                except ValueError:
                    pass
        else:
            current_uas = []

    return {
        "ua_rules": ua_rules,
        "declared_sitemaps": declared_sitemaps,
        "crawl_delays": crawl_delays
    }

def audit_html_robots(html, page_url, collector, is_homepage=False):
    """
    Scans HTML head for <meta name="robots" ...> or bot-specific tags.
    Flags noindex and nofollow directives.
    """
    if not html:
        return
    meta_directives = extract_meta_robots(html)
    for bot_name, content in meta_directives:
        if "noindex" in content:
            code = "HTML_NOINDEX_HOMEPAGE" if is_homepage else "HTML_NOINDEX_INTERIOR"
            sev = "critical" if is_homepage else "high"
            title = f"HTML <meta name='{bot_name}' content='noindex'> on {urlparse(page_url).path or '/'}"
            collector.add(
                code=code,
                title=title,
                severity=sev,
                evidence=f"HTML head on {page_url} contains '<meta name=\"{bot_name}\" content=\"{content}\">'.",
                action_summary=f"Crawlability Failure: Remove 'noindex' directive from HTML meta tags on {page_url}."
            )
        if "nofollow" in content and is_homepage:
            collector.add(
                code="HTML_NOFOLLOW_HOMEPAGE",
                title=f"Homepage specifies <meta name='{bot_name}' content='nofollow'>",
                severity="medium",
                evidence=f"HTML head on {page_url} contains '<meta name=\"{bot_name}\" content=\"{content}\">'.",
                action_summary="Optimization Opportunity: Remove 'nofollow' on homepage to enable AI crawlers to follow links to interior documentation."
            )

def audit_robots_txt(origin, logged_request, collector, sub_timeout=12):
    """
    Fetches and parses robots.txt, evaluating crawl delays, site-wide blocks,
    live search bot restrictions, and training bot policies.
    Returns (res_robots, declared_sitemaps).
    """
    robots_url = f"{origin}/robots.txt"
    res_robots = logged_request(robots_url, BOT_UA, timeout=sub_timeout, purpose="Robots Directives (/robots.txt)")
    declared_sitemaps = []

    if res_robots["status"] == 404:
        collector.add(
            code="ROBOTS_TXT_MISSING",
            title="Missing robots.txt file",
            severity="low",
            evidence=f"GET {robots_url} returned HTTP 404.",
            action_summary="Create a standard robots.txt declaring sitemap locations and confirming search crawl permissions."
        )
    elif res_robots["status"] == 200:
        parsed_robots = parse_robots_txt(res_robots["text"])
        ua_rules = parsed_robots["ua_rules"]
        declared_sitemaps = parsed_robots["declared_sitemaps"]

        # Check crawl delays
        for ua, delay in parsed_robots["crawl_delays"].items():
            if delay > 10.0:
                collector.add(
                    code="EXCESSIVE_CRAWL_DELAY",
                    title=f"Excessive robots.txt Crawl-Delay ({delay}s)",
                    severity="medium",
                    evidence=f"robots.txt declares 'Crawl-delay: {delay}s' for User-agent: {ua}.",
                    action_summary="Lower Crawl-delay to <= 5s or remove it for verified search engines to prevent retrieval timeouts."
                )

        # Check site-wide disallow for *
        if "*" in ua_rules:
            for directive, path in ua_rules["*"]:
                if directive == "disallow" and path in ("/", "/*"):
                    collector.add(
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
                            collector.add(
                                code="AI_SEARCH_BOT_BLOCKED_COMPLETELY",
                                title=f"Live AI search bot completely blocked: {bot_name}",
                                severity="high",
                                evidence=f"robots.txt explicitly specifies 'Disallow: {path}' for User-agent: {bot_token}.",
                                action_summary=f"Allow {bot_token} on public documentation and articles so {bot_name} can cite the brand in live answers."
                            )
                        elif is_harmful_disallow(path):
                            collector.add(
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
                        collector.add(
                            code="AI_TRAINING_BOT_BLOCKED",
                            title=f"AI model training scraper restricted: {bot_name}",
                            severity="low",
                            evidence=f"robots.txt disallows {bot_token} on '{path}'. This limits bulk model training but does not prevent live search citation.",
                            action_summary=f"Informational: Keep disallow if copyright protection is desired; allow if you wish {bot_name} to pre-train on your public docs."
                        )

    return res_robots, declared_sitemaps

def audit_ai_manifests(origin, logged_request, collector, sub_timeout=12):
    """
    Checks presence and substance of /llms.txt and /ai.txt manifests.
    Returns (res_llms, res_ai).
    """
    res_llms = logged_request(f"{origin}/llms.txt", BOT_UA, timeout=sub_timeout, purpose="AI Manifest (/llms.txt)")
    res_ai = logged_request(f"{origin}/ai.txt", BOT_UA, timeout=sub_timeout, purpose="AI Manifest (/ai.txt)")

    if res_llms["status"] == 200:
        if len(res_llms["text"].strip()) < 80:
            collector.add(
                code="LLMS_TXT_STUB",
                title="Near-empty /llms.txt manifest",
                severity="low",
                evidence=f"/llms.txt was found but contains only {len(res_llms['text'].strip())} characters.",
                action_summary="Optimization Opportunity: Populate /llms.txt with an authoritative summary and curated links."
            )
    elif res_ai["status"] == 200:
        collector.add(
            code="AI_TXT_FOUND_NO_LLMS_TXT",
            title="/ai.txt exists; recommend adding /llms.txt alias",
            severity="low",
            evidence=f"GET {origin}/ai.txt returned HTTP 200, but /llms.txt returned HTTP {res_llms['status']}.",
            action_summary="Optimization Opportunity: Add a redirect or copy from /llms.txt to /ai.txt to support modern LLM crawlers expecting the llms.txt convention."
        )
    else:
        collector.add(
            code="LLMS_TXT_MISSING",
            title="Missing /llms.txt or /ai.txt AI context manifest",
            severity="medium",
            evidence=f"GET {origin}/llms.txt returned HTTP {res_llms['status']} and /ai.txt returned HTTP {res_ai['status']}.",
            action_summary="Optimization Opportunity: Publish a clean markdown /llms.txt file at domain root summarizing the product, architecture, and primary documentation links."
        )

    return res_llms, res_ai
