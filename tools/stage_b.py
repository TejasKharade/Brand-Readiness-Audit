#!/usr/bin/env python3
"""
stage_b.py - Blind Ground-Truth Audit (Stage B)

For a given website, this script:
  1. Captures raw HTML + rendered (post-JS) text for the homepage and a
     couple of interior pages using a real headless browser (Playwright).
  2. Sends that evidence to Gemini with a prompt that reasons from
     first principles (NOT from your skill's checklist) about AI
     discoverability and on-site engagement problems.
  3. Saves the result to audits/{domain}/ground_truth_findings.json

This script must NEVER be given your skill_findings.json, your SKILL.md
files, or the EXPLANATION_REGISTRY codes. It has to stay blind.

Usage (standalone, for testing one site):
    export GEMINI_API_KEY="your_key_here"
    python tools/stage_b.py https://example.com

Usage (called from the orchestrator):
    from stage_b import run_stage_b
    run_stage_b(url, domain, root_dir)
"""

import os
import sys
import json
import re
import time
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright
from google import genai


BLIND_PROMPT_TEMPLATE = """You are investigating a single website to determine why an AI assistant
(like ChatGPT, Perplexity, or Claude) might fail to find, trust, or
correctly cite it -- and why a human visitor who lands on it might not
stay or engage.

Target website: {url}
Domain: {domain}

Below is evidence gathered from this site: the raw HTML a simple crawler
would see, and the fully rendered text a real browser shows after
JavaScript runs, for the homepage and a few interior pages.

EVIDENCE:
{evidence}

Reason from these principles -- do not follow a fixed checklist, and do
not assume a problem exists unless the evidence actually shows it:

1. Crawl & access: Would an automated crawler be able to reach this
   site? (Note: you were not able to check robots.txt/SSL/sitemap
   directly here -- only note this if the evidence itself suggests
   an access problem, e.g. an error page was captured.)
2. Renderability: Is the important content present in the raw HTML, or
   does it only appear in the rendered text? Compare the two evidence
   fields directly for each page. Check headings, navigation links, and
   structured data specifically for this gap.
3. Structured data & entity grounding: Is there valid JSON-LD/Schema.org
   markup visible in the raw HTML? Does it correctly identify the
   organization/product? Does it link out to authoritative profiles
   (Wikidata, LinkedIn, GitHub, etc.)? Does anything in it contradict
   what's visibly on the page (price, stock, version)?
4. Corroboration & freshness: Are important facts dated / freshness-
   marked? Would this content look "stale" or "unverifiable" to an
   AI system reasoning about trust?
5. Content citability: Is content written so an AI could quote a single
   paragraph and have it make sense standalone (clear subject, direct
   answers up front, facts in text not locked in images, real
   statistics/tables)?
6. On-site engagement: Once a visitor actually arrives, is it clear
   what the site is, what to do next, and is there enough context/
   orientation to keep them there?

For each real problem you find, produce a finding in this exact shape:

{{
  "id": "GT-001",
  "title": "short description",
  "severity": "critical | high | medium | low",
  "evidence": "the specific concrete thing you observed -- a URL, a
               missing tag, a text excerpt, a comparison -- not a
               general statement",
  "suggested_action": {{
    "summary": "what to change and how",
    "priority": "critical | high | medium | low"
  }}
}}

Rules:
- Only report what the evidence actually shows. Do not guess or assume.
- Severity should reflect real-world impact: does this actually block
  discovery/citation, or just fall short of best practice?
- Respond with ONLY a single JSON object, no other text, no markdown
  fences, in exactly this shape:

{{
  "site": "{domain}",
  "audited_at": "ISO timestamp",
  "summary": {{"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}},
  "findings": []
}}
"""


def extract_evidence_from_html(raw_html, max_chars=100000):
    """
    Intelligently extract the `<head>` JSON-LD and the `<body>` text content,
    stripping out massive inline <style>, <script>, and <svg> blocks.
    This ensures the Ground Truth LLM sees the actual content and schema
    without hitting token limits or getting truncated in the <head>.
    """
    if not raw_html:
        return ""

    # 1. Extract JSON-LD blocks (we definitely want the LLM to see these)
    json_ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw_html,
        re.DOTALL | re.IGNORECASE
    )

    # 2. Extract body HTML to avoid processing the whole <head> (except for JSON-LD)
    body_match = re.search(r'<body[^>]*>(.*?)</body>', raw_html, re.DOTALL | re.IGNORECASE)
    body_html = body_match.group(1) if body_match else raw_html

    # 3. Strip visual/functional bloat from the body
    body_no_scripts = re.sub(r'<script[^>]*>.*?</script>', ' ', body_html, flags=re.DOTALL | re.IGNORECASE)
    body_no_styles = re.sub(r'<style[^>]*>.*?</style>', ' ', body_no_scripts, flags=re.DOTALL | re.IGNORECASE)
    body_no_svgs = re.sub(r'<svg[^>]*>.*?</svg>', ' ', body_no_styles, flags=re.DOTALL | re.IGNORECASE)

    # 4. Strip remaining HTML tags to get pure text
    clean_body = re.sub(r'<[^>]+>', ' ', body_no_svgs)
    clean_text = re.sub(r'\s+', ' ', clean_body).strip()

    # 5. Assemble final evidence
    evidence_lines = []
    if json_ld_blocks:
        evidence_lines.append("=== JSON-LD STRUCTURED DATA ===")
        for i, block in enumerate(json_ld_blocks):
            evidence_lines.append(block.strip())
            evidence_lines.append("---")
        evidence_lines.append("")

    evidence_lines.append("=== RAW HTML BODY TEXT ===")
    evidence_lines.append(clean_text)

    full_evidence = "\n".join(evidence_lines)
    return full_evidence[:max_chars]


def capture_pages_batch(urls, snippet_chars=100000):
    """Fetch raw HTML + rendered text for a list of URLs, reusing a single
    Playwright browser instance across all pages for speed.

    Returns:
        all_evidence: list of evidence dicts (one per URL, in order)
        homepage_links: <a href> links from the first URL only (for fallback discovery)
    """
    # Raw HTML via requests — can run before Playwright starts
    raw_htmls = {}
    for url in urls:
        try:
            raw_htmls[url] = requests.get(
                url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}
            ).text
        except Exception as e:
            raw_htmls[url] = f"[FETCH ERROR: {e}]"

    rendered_texts = {u: f"[RENDER SKIPPED]" for u in urls}
    homepage_links = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for i, url in enumerate(urls):
                try:
                    pg = browser.new_page()
                    pg.goto(url, wait_until="networkidle", timeout=20000)
                    rendered_texts[url] = pg.inner_text("body")
                    if i == 0:  # collect links only from homepage
                        homepage_links = pg.eval_on_selector_all(
                            "a[href]", "els => els.map(e => e.href)"
                        )
                    pg.close()
                except Exception as e:
                    rendered_texts[url] = f"[RENDER ERROR: {e}]"
            browser.close()
    except Exception as e:
        # Playwright itself failed to start — mark everything
        for url in urls:
            if rendered_texts[url] == "[RENDER SKIPPED]":
                rendered_texts[url] = f"[PLAYWRIGHT ERROR: {e}]"

    all_evidence = [
        {
            "url": url,
            "raw_html_snippet": extract_evidence_from_html(raw_htmls[url], snippet_chars),
            "rendered_text_snippet": rendered_texts[url][:snippet_chars],
        }
        for url in urls
    ]
    return all_evidence, homepage_links


def load_curated_pages(root_dir, domain, homepage_url, max_pages=5):
    """Read the page list Stage A's Skill 1 already discovered (via sitemap)
    and return those same URLs so Stage B audits identical pages.

    Falls back to None if Stage A's raw output isn't found, so the caller
    can fall back to nav-link discovery.

    Path: audits/test_runs/{clean_domain}_audit.json
          → skills.skill_1.sampled_pages.curated_sample_details[].url
    """
    clean_domain = domain.replace(".", "_").replace(":", "_")
    raw_report_path = os.path.join(
        root_dir, "audits", "test_runs", f"{clean_domain}_audit.json"
    )
    if not os.path.isfile(raw_report_path):
        return None

    try:
        with open(raw_report_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        details = (
            raw.get("skills", {})
               .get("skill_1", {})
               .get("sampled_pages", {})
               .get("curated_sample_details", [])
        )
        urls = []
        # Always include homepage first
        if homepage_url.rstrip("/") not in [u.rstrip("/") for u in urls]:
            urls.append(homepage_url)
        for item in details:
            u = item.get("url") if isinstance(item, dict) else item
            if u and u.rstrip("/") != homepage_url.rstrip("/") and u not in urls:
                urls.append(u)
            if len(urls) >= max_pages:
                break
        return urls if len(urls) > 1 else None  # only useful if we got interior pages
    except Exception:
        return None


def extract_json_block(text):
    """Strip ```json fences if present and return the raw JSON string."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text


def clean_interior_links(links, domain, homepage_url, max_links=2):
    """Filter raw <a href> links down to real, unique, same-domain content
    pages -- skipping anchors, tracking query strings, and non-HTML assets."""
    skip_ext = (
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
        ".pdf", ".zip", ".css", ".js", ".xml", ".woff", ".woff2", ".ttf", ".mp4",
    )
    homepage_path = (urlparse(homepage_url).path or "/").rstrip("/") or "/"

    seen = set()
    cleaned = []
    for link in links:
        try:
            parsed = urlparse(link)
        except Exception:
            continue

        if parsed.scheme not in ("http", "https"):
            continue  # skip mailto:, tel:, javascript:, etc.
        if parsed.netloc != domain and not parsed.netloc.endswith("." + domain):
            continue  # off-domain link

        path = (parsed.path or "/").rstrip("/") or "/"
        if path.lower().endswith(skip_ext):
            continue  # not a content page
        if path == homepage_path and not parsed.query:
            continue  # pure same-page anchor, e.g. #skip-to-content

        clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"  # query string dropped
        if clean_url in seen or clean_url.rstrip("/") == homepage_url.rstrip("/"):
            continue

        seen.add(clean_url)
        cleaned.append(clean_url)
        if len(cleaned) >= max_links:
            break

    return cleaned


def run_stage_b(url, domain, root_dir, model_name="gemini-2.5-flash", max_pages=5):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")
    client = genai.Client(api_key=api_key)

    # --- Page selection: prefer Stage A's curated sitemap pages ---
    pages_to_audit = load_curated_pages(root_dir, domain, url, max_pages=max_pages)
    all_evidence = None  # set below in whichever branch runs

    if pages_to_audit:
        # Happy path: same pages Stage A audited — capture them all in one session
        print(f"  [Stage B] Using {len(pages_to_audit)} pages from Stage A sitemap sample:")
        for p in pages_to_audit:
            print(f"             {p}")
        print(f"  [Stage B] Capturing {len(pages_to_audit)} pages (single browser session)...")
        all_evidence, _ = capture_pages_batch(pages_to_audit)
    else:
        # Fallback: discover via homepage nav links (1 level, no recursion).
        # Capture homepage first to get links, then capture interior pages —
        # reuse the homepage evidence so we don't render it twice.
        print(f"  [Stage B] Stage A output not found — falling back to nav-link discovery.")
        print(f"  [Stage B] Capturing homepage for link discovery: {url}")
        homepage_evidence_list, links = capture_pages_batch([url])
        interior_urls = clean_interior_links(links, domain, url, max_links=max_pages - 1)
        pages_to_audit = [url] + interior_urls
        print(f"  [Stage B] Discovered {len(pages_to_audit)} page(s) via nav links.")

        if interior_urls:
            print(f"  [Stage B] Capturing {len(interior_urls)} interior page(s) (single browser session)...")
            interior_evidence_list, _ = capture_pages_batch(interior_urls)
        else:
            interior_evidence_list = []
        all_evidence = homepage_evidence_list + interior_evidence_list

    prompt = BLIND_PROMPT_TEMPLATE.format(
        url=url,
        domain=domain,
        evidence=json.dumps(all_evidence, indent=2)[:500000],
    )

    print(f"  [Stage B] Sending evidence to {model_name} for blind audit...")
    raw_text = None
    last_error = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            raw_text = extract_json_block(response.text)
            break
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                wait_s = 65
                print(f"  [Stage B] Rate limited, waiting {wait_s}s before retry ({attempt + 1}/4)...")
                time.sleep(wait_s)
            elif "UNAVAILABLE" in err_str or "503" in err_str:
                wait_s = 20 * (attempt + 1)
                print(f"  [Stage B] Model temporarily overloaded, waiting {wait_s}s before retry ({attempt + 1}/4)...")
                time.sleep(wait_s)
            else:
                raise
    if raw_text is None:
        raise RuntimeError(f"Gemini call failed after retries: {last_error}")

    try:
        findings = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Gemini did not return valid JSON for {domain}. "
            f"Raw response saved for debugging.\nError: {e}\nResponse:\n{raw_text[:2000]}"
        )

    # Use raw domain as folder name (e.g. "www.docker.com") — must match
    # Stage A's audits/{domain}/ path so Stage C can find both files.
    out_dir = os.path.join(root_dir, "audits", domain)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ground_truth_findings.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2)

    print(f"  [Stage B] Saved: {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python stage_b.py <url>")
        sys.exit(1)

    target_url = sys.argv[1]
    if not target_url.startswith("http"):
        target_url = "https://" + target_url
    target_domain = urlparse(target_url).netloc

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root
    run_stage_b(target_url, target_domain, root)