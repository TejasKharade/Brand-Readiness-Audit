"""
XML Sitemap parsing, child sitemap traversal, Tier-2 HTML link discovery,
depth-stratified URL sampling, and deep page spot-checks for AI Crawler Access Audit.
Standard library only (xml.etree.ElementTree, urllib.parse, re). Zero external dependencies.
"""

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin

try:
    from .constants import (
        PAGE_MEDIA_EXTS, NON_HTML_EXTS, IMPORTANT_PATH_PATTERNS,
        BOT_UA, BROWSER_UA
    )
except (ImportError, ValueError):
    from constants import (
        PAGE_MEDIA_EXTS, NON_HTML_EXTS, IMPORTANT_PATH_PATTERNS,
        BOT_UA, BROWSER_UA
    )

def get_url_depth(u):
    """Calculates URL path depth based on non-empty path segments."""
    p = urlparse(u).path.strip("/")
    return len([seg for seg in p.split("/") if seg]) if p else 0

def extract_loc_urls(xml_text):
    """
    Extracts all <loc> values from XML string with dual-strategy:
    ElementTree with namespace handling + regex fallback for unescaped characters.
    Also detects <sitemapindex> presence.
    """
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

def explore_sitemaps(candidate_sitemaps, request_fn, sub_timeout=12):
    """
    Crawls candidate sitemaps, handles child sitemaps in sitemapindex,
    samples diverse categories, and returns leaf URLs and status metadata.
    """
    discovered_urls = []
    sitemap_target = candidate_sitemaps[0]
    sitemap_status = 0
    sitemap_had_child_index = False
    sitemap_child_count = 0
    sitemap_empty_locs = False

    for candidate in candidate_sitemaps[:4]:
        res_sitemap = request_fn(candidate, timeout=sub_timeout, purpose=f"XML Sitemap ({candidate})")
        sitemap_status = res_sitemap["status"]
        if res_sitemap["status"] == 200:
            sitemap_target = candidate
            raw_locs, is_index = extract_loc_urls(res_sitemap["text"])
            
            if is_index:
                sitemap_had_child_index = True
                child_sitemaps = [u for u in raw_locs if u.endswith(".xml") or u.endswith(".gz") or "sitemap" in u.lower()]
                sitemap_child_count = len(child_sitemaps)
                if child_sitemaps:
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
                        res_child = request_fn(child_url, timeout=sub_timeout, purpose=f"Child Sitemap ({urlparse(child_url).path})")
                        if res_child["status"] == 200:
                            child_locs, _ = extract_loc_urls(res_child["text"])
                            for leaf_u in child_locs:
                                if not any(leaf_u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and "sitemap" not in urlparse(leaf_u).path.lower():
                                    all_leaf_urls.append(leaf_u)

                    discovered_urls = all_leaf_urls
            else:
                leaf_urls = [u for u in raw_locs if not any(u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and "sitemap" not in urlparse(u).path.lower()]
                discovered_urls = leaf_urls
                if not raw_locs:
                    sitemap_empty_locs = True

            if discovered_urls:
                break

    return {
        "discovered_urls": discovered_urls,
        "sitemap_target": sitemap_target,
        "sitemap_status": sitemap_status,
        "sitemap_had_child_index": sitemap_had_child_index,
        "sitemap_child_count": sitemap_child_count,
        "sitemap_empty_locs": sitemap_empty_locs
    }

def extract_html_fallback_links(html, origin, base_domain, existing_urls):
    """
    Tier 2: Mandatory HTML Link-Discovery Fallback.
    Extracts internal <a href> links from homepage HTML if sitemap yielded < 5 URLs.
    """
    discovered = list(existing_urls)
    if not html:
        return discovered

    html_links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.I)
    for href in html_links:
        href = href.strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_u = urljoin(origin, href)
        p_u = urlparse(full_u)
        if p_u.netloc.lower() == base_domain.lower() and p_u.scheme in ("http", "https"):
            clean_u = f"{p_u.scheme}://{p_u.netloc}{p_u.path}".rstrip("/")
            if not any(clean_u.lower().endswith(ext) for ext in PAGE_MEDIA_EXTS) and clean_u not in discovered and clean_u != origin.rstrip("/"):
                discovered.append(clean_u)

    return discovered

def audit_sitemap_findings(sitemap_result, candidate_sitemaps, collector):
    """Evaluates sitemap exploration result and adds diagnostic findings."""
    sitemap_status = sitemap_result["sitemap_status"]
    discovered_urls = sitemap_result["discovered_urls"]
    sitemap_empty_locs = sitemap_result["sitemap_empty_locs"]
    sitemap_had_child_index = sitemap_result["sitemap_had_child_index"]
    sitemap_target = sitemap_result["sitemap_target"]

    if sitemap_status == 404 and not discovered_urls:
        collector.add(
            code="SITEMAP_MISSING",
            title="No discoverable sitemap.xml",
            severity="medium",
            evidence=f"Checked candidate sitemaps ({', '.join(candidate_sitemaps[:2])}) but received HTTP 404.",
            action_summary="Generate and publish an XML sitemap at /sitemap.xml and declare it in robots.txt."
        )
    elif sitemap_status == 200 and sitemap_empty_locs and not sitemap_had_child_index:
        collector.add(
            code="SITEMAP_EMPTY",
            title="XML sitemap contains zero URL locations",
            severity="high",
            evidence=f"Fetched sitemap candidate at {sitemap_target} (HTTP 200) but extracted 0 <loc> tags from document.",
            action_summary="Populate sitemap.xml with canonical URLs of all public pages."
        )

def audit_deep_urls(discovered_urls, origin, logged_request, collector, check_html_robots_fn):
    """
    Spot-checks up to 3 interior URLs (preferring documentation/blog/product pages)
    for User-Agent discrimination, redirect loops, X-Robots-Tag, and HTML meta robots.
    """
    if not discovered_urls:
        return
    interior_urls = [u for u in discovered_urls if u.rstrip("/") != origin.rstrip("/")]
    doc_urls = [u for u in interior_urls if any(p in u.lower() for p in ["/docs", "/documentation", "/blog", "/product", "/pricing", "/learn"])]
    sample_pool = doc_urls if doc_urls else interior_urls
    sample_urls = sample_pool[:3]

    for deep_url in sample_urls:
        deep_bot = logged_request(deep_url, BOT_UA, purpose=f"Sample Page (AI Bot: {urlparse(deep_url).path})")
        deep_browser = logged_request(deep_url, BROWSER_UA, purpose=f"Sample Page (Browser: {urlparse(deep_url).path})")
        collector.check_redirects(deep_bot, deep_url)
        
        if deep_bot["status"] in (401, 403) and deep_browser["status"] == 200:
            collector.add(
                code="DEEP_PAGE_BOT_DISCRIMINATION",
                title=f"AI Search Bot blocked on interior page: {urlparse(deep_url).path}",
                severity="critical",
                evidence=f"GET {deep_url} returned HTTP {deep_bot['status']} to OAI-SearchBot but HTTP 200 to desktop browser.",
                action_summary=f"Ensure CDN and WAF firewall rules do not restrict AI search bot User-Agents on interior pages like '{urlparse(deep_url).path}'."
            )
        
        deep_x_robots = deep_bot["headers"].get("x-robots-tag", "").lower()
        if "noindex" in deep_x_robots:
            collector.add(
                code="DEEP_PAGE_NOINDEX_HEADER",
                title=f"Interior page returns X-Robots-Tag: noindex: {urlparse(deep_url).path}",
                severity="high",
                evidence=f"Response headers on {deep_url} contain 'X-Robots-Tag: {deep_x_robots}'.",
                action_summary=f"Remove 'noindex' directive from HTTP headers on public content page '{urlparse(deep_url).path}'."
            )
        check_html_robots_fn(deep_bot["text"], deep_url, collector, is_homepage=False)

def audit_target_subpage(target_url, origin, logged_request, collector, check_html_robots_fn):
    """Direct probe on specific subpage if target_url provided was not the domain root."""
    if target_url.rstrip("/") == origin.rstrip("/"):
        return
    t_bot = logged_request(target_url, BOT_UA, purpose=f"Target URL (AI Bot: {urlparse(target_url).path})")
    t_browser = logged_request(target_url, BROWSER_UA, purpose=f"Target URL (Browser: {urlparse(target_url).path})")
    collector.check_redirects(t_bot, target_url)
    if t_bot["status"] in (401, 403) and t_browser["status"] == 200:
        collector.add(
            code="SPECIFIC_URL_BOT_DISCRIMINATION",
            title=f"AI Search Bot blocked on target URL: {urlparse(target_url).path}",
            severity="critical",
            evidence=f"GET {target_url} returned HTTP {t_bot['status']} to OAI-SearchBot but HTTP 200 to desktop browser.",
            action_summary=f"Configure firewall rules to allow AI search crawlers to access '{urlparse(target_url).path}'."
        )
    t_x_robots = t_bot["headers"].get("x-robots-tag", "").lower()
    if "noindex" in t_x_robots:
        collector.add(
            code="SPECIFIC_URL_NOINDEX_HEADER",
            title=f"Target URL returns X-Robots-Tag: noindex: {urlparse(target_url).path}",
            severity="high",
            evidence=f"Response headers on {target_url} contain 'X-Robots-Tag: {t_x_robots}'.",
            action_summary=f"Remove 'noindex' from headers on '{urlparse(target_url).path}'."
        )
    check_html_robots_fn(t_bot["text"], target_url, collector, is_homepage=False)

def stratified_sample_urls(discovered_urls, origin, max_sample=15):
    """
    Stratified Sampling up to Depth 3 across key archetypes:
    pricing, documentation, product, blog, about, general, deep_leaf.
    """
    valid_urls = [u for u in discovered_urls if (u.startswith("http://") or u.startswith("https://")) and not urlparse(u).path.lower().endswith(NON_HTML_EXTS)]
    interior_urls = [u for u in valid_urls if u.rstrip("/") != origin.rstrip("/")]

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

    # If sample is under max_sample pages, add shallowest remaining interior pages (depth <= 3)
    remaining_shallow = [u for u in interior_urls if u not in curated_sample and get_url_depth(u) <= 3]
    remaining_shallow.sort(key=get_url_depth)
    for u in remaining_shallow:
        if len(curated_sample) >= max_sample:
            break
        curated_sample.append(u)
        sample_details.append({"url": u, "depth": get_url_depth(u), "archetype": "general"})

    # Always ensure at least 1 deeper leaf page is sampled if available
    if len(curated_sample) < max_sample and interior_urls:
        deepest = max(interior_urls, key=get_url_depth)
        if deepest not in curated_sample:
            curated_sample.append(deepest)
            sample_details.append({"url": deepest, "depth": get_url_depth(deepest), "archetype": "deep_leaf"})

    return {
        "homepage": origin,
        "total_discovered": len(discovered_urls),
        "doc_pages": doc_pages[:10],
        "blog_pages": blog_pages[:10],
        "product_pages": product_pages[:10],
        "curated_sample": curated_sample[:max_sample],
        "curated_sample_details": sample_details[:max_sample],
        "interior_urls": interior_urls
    }

def check_buried_important_pages(interior_urls):
    """
    Detects important pages (pricing, documentation, product specs)
    nested 4 or more levels deep in the URL hierarchy.
    """
    deep_important_pages = []
    for u in interior_urls:
        depth = get_url_depth(u)
        if depth >= 4 and re.search(IMPORTANT_PATH_PATTERNS, u, re.I):
            deep_important_pages.append((depth, u))

    if deep_important_pages:
        deep_important_pages.sort(key=lambda x: x[0], reverse=True)
        return deep_important_pages[0]
    return None

def audit_buried_pages(interior_urls, collector):
    """Checks for deeply buried important pages and adds finding if detected."""
    deep_page_result = check_buried_important_pages(interior_urls)
    if deep_page_result:
        max_d, sample_deep_url = deep_page_result
        segments = [s for s in urlparse(sample_deep_url).path.strip("/").split("/") if s]
        collector.add(
            code="DEEPLY_BURIED_IMPORTANT_PAGE",
            title=f"Important page buried deep in URL path hierarchy (Depth {max_d}): {urlparse(sample_deep_url).path}",
            severity="medium",
            evidence=f"Critical page '{sample_deep_url}' is located at path depth {max_d} ({len(segments)} segments: {' / '.join(segments)}). AI search crawlers allocate significantly less crawl budget to URLs nested 4+ levels deep.",
            action_summary="Flatten URL structure to depth 2 or 3 (e.g. '/docs/topic' or '/product/name') to ensure rapid discovery and high citation priority by AI engines."
        )
