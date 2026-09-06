#!/usr/bin/env python3
"""
JavaScript Rendering & Semantic Parity Audit Tool (Pure Standard Library)
Zero external dependencies. Portable, deterministic, and sandbox-safe.

Performs a true Two-Pass Comparative Evaluation:
- Pass A: Raw HTTP GET via AI SearchBot User-Agent (what OAI-SearchBot sees)
- Pass B: Hydrated DOM render via host headless browser (--headless --dump-dom)

Evaluates:
- Core content parity (substantive sentences present in Pass B vs Pass A)
- Heading & Title mutation (did JS inject or alter the h1?)
- Structured data timing (did client JS dynamically inject JSON-LD?)
- Internal link discovery (are internal navigation links trapped in JS?)
- Deep-link route pre-rendering
"""

import sys
import os
import re
import json
import time
import shutil
import subprocess
from urllib.parse import urlparse, urljoin
import urllib.request
import urllib.error

BOT_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

def find_headless_browser():
    """
    Auto-detects host system headless browser binary across Windows, Linux, and macOS.
    Does not require Playwright or bundled Chromium binaries.
    """
    # 1. Standard executable names on PATH
    candidates = [
        "google-chrome", "google-chrome-stable", "chromium",
        "chromium-browser", "chrome", "msedge", "microsoft-edge"
    ]
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path
            
    # 2. Windows specific default installation paths
    if sys.platform == "win32":
        win_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
        ]
        for p in win_paths:
            if os.path.exists(p):
                return p

    # 3. macOS specific application paths
    if sys.platform == "darwin":
        mac_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium"
        ]
        for p in mac_paths:
            if os.path.exists(p):
                return p

    # 4. Linux specific common paths
    if sys.platform.startswith("linux"):
        linux_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium"
        ]
        for p in linux_paths:
            if os.path.exists(p):
                return p

    return None

def fetch_pass_a(url, timeout=15):
    """Pass A: Fast raw HTTP GET from the perspective of an AI SearchBot."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BOT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    last_err = None
    for attempt in range(2):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
                html = data.decode("utf-8", errors="replace")
                return {
                    "status": resp.status,
                    "html": html,
                    "final_url": resp.url,
                    "elapsed_ms": elapsed_ms,
                    "error": None
                }
        except urllib.error.HTTPError as e:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            data = e.read() if hasattr(e, "read") else b""
            html = data.decode("utf-8", errors="replace")
            return {
                "status": e.code,
                "html": html,
                "final_url": getattr(e, "url", url),
                "elapsed_ms": elapsed_ms,
                "error": str(e)
            }
        except Exception as e:
            last_err = e
            time.sleep(0.5)

    return {
        "status": 0,
        "html": "",
        "final_url": url,
        "elapsed_ms": 0,
        "error": str(last_err)
    }

def fetch_pass_b(url, browser_bin, timeout=15):
    """Pass B: Rendered DOM capture via native system headless browser."""
    if not browser_bin:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": 0,
            "error": "No host headless browser detected on system."
        }
    cmd = [
        browser_bin,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--blink-settings=imagesEnabled=false",
        "--disable-remote-fonts",
        "--disable-background-networking",
        "--disable-sync",
        "--mute-audio",
        "--dump-dom",
        url
    ]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        stdout_text = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_text = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        if proc.returncode == 0 and stdout_text:
            return {
                "status": 200,
                "html": stdout_text,
                "elapsed_ms": elapsed_ms,
                "error": None
            }
        else:
            return {
                "status": 0,
                "html": "",
                "elapsed_ms": elapsed_ms,
                "error": f"Headless browser exited with code {proc.returncode}: {stderr_text[:200]}"
            }
    except subprocess.TimeoutExpired:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": timeout * 1000,
            "error": f"Browser rendering timed out after {timeout}s"
        }
    except Exception as e:
        return {
            "status": 0,
            "html": "",
            "elapsed_ms": 0,
            "error": str(e)
        }

def extract_features(html, base_url):
    """
    Extracts structural and semantic elements while stripping non-content boilerplate.
    Focuses on: title, h1, json-ld schemas, internal links, and substantive sentences.
    """
    if not html:
        return {
            "title": "",
            "h1_list": [],
            "schema_types": [],
            "internal_links": set(),
            "clean_text": "",
            "sentences": []
        }

    # 1. Extract <title>
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

    # 2. Extract <h1> tags
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.DOTALL)
    h1_list = [re.sub(r"<[^>]+>", "", h).strip() for h in h1_matches]
    h1_list = [re.sub(r"\s+", " ", h) for h in h1_list if h]

    # 3. Extract JSON-LD Schema types
    schema_types = []
    for script_match in re.finditer(r'<script\s+[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.DOTALL):
        try:
            data = json.loads(script_match.group(1).strip())
            if isinstance(data, dict):
                stype = data.get("@type")
                if stype:
                    schema_types.append(stype if isinstance(stype, str) else str(stype))
                if "@graph" in data and isinstance(data["@graph"], list):
                    for item in data["@graph"]:
                        if isinstance(item, dict) and "@type" in item:
                            schema_types.append(str(item["@type"]))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "@type" in item:
                        schema_types.append(str(item["@type"]))
        except Exception:
            pass

    # 4. Extract internal <a href> links
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    internal_links = set()
    for link_match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.I):
        href = link_match.group(1).strip()
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        full_url = urljoin(base_url, href)
        parsed_link = urlparse(full_url)
        if parsed_link.netloc.lower() == base_domain:
            norm_link = f"{parsed_link.scheme}://{parsed_link.netloc}{parsed_link.path}".rstrip("/")
            if norm_link:
                internal_links.add(norm_link)

    # 5. Clean boilerplate noise
    cleaned = html
    # Remove script, style, svg, noscript
    cleaned = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", cleaned, flags=re.I | re.DOTALL)
    # Remove header, nav, footer, aside
    cleaned = re.sub(r"<(header|nav|footer|aside)[^>]*>.*?</\1>", " ", cleaned, flags=re.I | re.DOTALL)
    # Remove modal/dialog/consent containers
    cleaned = re.sub(r'<[^>]+(?:id|class)=["\'][^"\']*(?:cookie|consent|modal|banner|overlay|dialog)[^"\']*["\'][^>]*>.*?</[^>]+>', " ", cleaned, flags=re.I | re.DOTALL)

    # Prioritize <main> or <article> if available
    main_match = re.search(r"<(main|article)[^>]*>(.*?)</\1>", cleaned, re.I | re.DOTALL)
    content_html = main_match.group(2) if main_match else cleaned

    # Insert newlines around block tags so separate elements don't merge into one giant line
    content_html = re.sub(r"<(/?(?:div|p|li|tr|th|td|h[1-6]|br|hr)[^>]*)>", r"\n<\1>\n", content_html, flags=re.I)

    # Strip all remaining HTML tags
    raw_text = re.sub(r"<[^>]+>", " ", content_html)
    clean_text = re.sub(r"[ \t]+", " ", raw_text)
    clean_text = re.sub(r"\n\s*\n+", "\n", clean_text).strip()

    # Extract substantive sentences (>= 25 chars, >= 4 words, not code/garbage)
    candidate_sentences = re.split(r"(?<=[.!?])\s+|\n+", clean_text)
    sentences = []
    for s in candidate_sentences:
        s = s.strip()
        if len(s) >= 25 and len(s.split()) >= 4:
            # Filter obvious CSS/JS leftovers
            if not re.search(r"[{};()=<>|\\]", s):
                sentences.append(s)

    return {
        "title": title,
        "h1_list": h1_list,
        "schema_types": list(set(schema_types)),
        "internal_links": internal_links,
        "clean_text": clean_text,
        "sentences": sentences
    }

def audit_render_parity(target_url, browser_bin):
    """
    Executes Pass A vs Pass B diff on a specific URL and returns findings and parity metrics.
    """
    res_a = fetch_pass_a(target_url)
    res_b = fetch_pass_b(target_url, browser_bin) if browser_bin else None

    feat_a = extract_features(res_a["html"], target_url)
    feat_b = extract_features(res_b["html"], target_url) if (res_b and res_b["status"] == 200) else None

    findings = []
    finding_counter = 1

    def add_finding(code, title, severity, evidence, action_summary, action_priority=None):
        nonlocal finding_counter
        f_id = f"RND-{finding_counter:03d}"
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

    # Check 0: HTTP status failure on Pass A
    if res_a["status"] == 0 or res_a["status"] >= 400:
        add_finding(
            code="RAW_FETCH_FAILURE",
            title=f"Direct HTTP fetch failed on {urlparse(target_url).path or '/'}",
            severity="critical",
            evidence=f"Raw fetch returned HTTP {res_a['status']}: {res_a['error']}.",
            action_summary="Fix server routing or permissions to ensure the URL returns HTTP 200 to AI search bots."
        )
        return {
            "url": target_url,
            "findings": findings,
            "metrics": {
                "pass_a_status": res_a["status"],
                "pass_b_status": res_b["status"] if res_b else 0,
                "parity_pct": 0.0
            }
        }

    # If no browser was available on the host machine, gracefully fallback
    if not feat_b:
        # Fallback static checks for obvious empty shells
        if len(feat_a["sentences"]) == 0 and ("<div id=\"root\">" in res_a["html"] or "<div id=\"app\">" in res_a["html"]):
            add_finding(
                code="EMPTY_SHELL_SPA_SUSPECTED",
                title="Probable empty-shell Single Page Application (SPA)",
                severity="high",
                evidence="Raw HTML contains an empty mounting container (<div id='root'> or #app) with 0 extracted sentences.",
                action_summary="Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) to ensure content is delivered in raw HTML."
            )
        return {
            "url": target_url,
            "findings": findings,
            "metrics": {
                "pass_a_status": res_a["status"],
                "pass_b_status": 0,
                "browser_available": False,
                "raw_sentences_count": len(feat_a["sentences"])
            }
        }

    # 1. Core Sentence Parity Comparison
    missing_sentences = []
    text_a_lower = feat_a["clean_text"].lower()
    for s in feat_b["sentences"]:
        # Normalize and check containment
        s_clean = re.sub(r"\s+", " ", s.lower()).strip()
        # Take key 4-word ngram to allow for minor whitespace / quote formatting differences
        words = s_clean.split()
        probe = " ".join(words[:min(6, len(words))])
        if probe not in text_a_lower:
            missing_sentences.append(s)

    total_b_sentences = len(feat_b["sentences"])
    if total_b_sentences > 0:
        parity_pct = round((1 - (len(missing_sentences) / total_b_sentences)) * 100, 1)
    else:
        parity_pct = 100.0

    # Flag: EMPTY_SHELL_SPA (Critical)
    if total_b_sentences >= 2 and len(feat_a["sentences"]) == 0 and parity_pct < 15.0:
        sample_missing = f'"{missing_sentences[0]}"' if missing_sentences else "dynamic text"
        add_finding(
            code="EMPTY_SHELL_SPA",
            title=f"Core content is client-rendered and invisible in raw HTML: {urlparse(target_url).path or '/'}",
            severity="critical",
            evidence=f"Raw HTTP response delivered 0 text sentences, while rendered DOM produced {total_b_sentences} sentences (Parity: {parity_pct}%). Example missing: {sample_missing}",
            action_summary="Pre-render primary page content using SSR (Next.js/Nuxt) or SSG so search crawlers can index and cite it without executing JavaScript."
        )
    # Flag: CORE_CONTENT_RENDER_GAP (High)
    elif total_b_sentences >= 3 and parity_pct < 60.0:
        sample_missing = f'"{missing_sentences[0]}"' if missing_sentences else "multiple sentences"
        add_finding(
            code="CORE_CONTENT_RENDER_GAP",
            title=f"Significant content render gap ({parity_pct}% parity) on {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=f"Pass B rendered {total_b_sentences} sentences, but Pass A only contained {total_b_sentences - len(missing_sentences)} ({len(missing_sentences)} missing). Example missing: {sample_missing}",
            action_summary="Ensure core documentation, product specifications, and descriptive text are rendered server-side in static HTML."
        )

    # 2. Heading & Topic Mutation
    if feat_b["h1_list"] and not feat_a["h1_list"]:
        h1_rendered = feat_b["h1_list"][0]
        add_finding(
            code="HEADING_RENDER_GAP",
            title=f"Primary <h1> is injected via client JavaScript on {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=f"Rendered DOM contains <h1> '{h1_rendered}', but raw HTML has 0 <h1> tags.",
            action_summary="Render primary <h1> tags in static HTML to ensure AI crawlers immediately identify the topic."
        )

    # 3. Structured Data Timing
    missing_schemas = [s for s in feat_b["schema_types"] if s not in feat_a["schema_types"]]
    if missing_schemas:
        add_finding(
            code="STRUCTURED_DATA_TIMING",
            title=f"JSON-LD structured data is injected via client JavaScript: {urlparse(target_url).path or '/'}",
            severity="high",
            evidence=f"Schema types [{', '.join(missing_schemas)}] were found in the rendered DOM but absent from initial raw HTML.",
            action_summary="Move JSON-LD <script type='application/ld+json'> tags to server-rendered HTML so AI crawlers extract entity schema without JavaScript execution."
        )

    # 4. Internal Link Discovery Gap
    missing_links = feat_b["internal_links"] - feat_a["internal_links"]
    if len(missing_links) >= 5:
        sample_links = list(missing_links)[:3]
        add_finding(
            code="INTERNAL_LINK_DISCOVERY_GAP",
            title=f"Navigation links ({len(missing_links)} URLs) are locked inside client JavaScript on {urlparse(target_url).path or '/'}",
            severity="medium",
            evidence=f"{len(missing_links)} internal links exist only in the rendered DOM (e.g., {', '.join(sample_links)}).",
            action_summary="Use standard HTML <a href='...'> anchor tags in static navigation menus to allow search spiders to discover interior pages."
        )

    metrics = {
        "pass_a_status": res_a["status"],
        "pass_b_status": res_b["status"],
        "pass_a_latency_ms": res_a["elapsed_ms"],
        "pass_b_latency_ms": res_b["elapsed_ms"],
        "parity_pct": parity_pct,
        "sentences_pass_a": len(feat_a["sentences"]),
        "sentences_pass_b": total_b_sentences,
        "missing_sentences_count": len(missing_sentences),
        "missing_snippets_sample": missing_sentences[:3]
    }

    return {
        "url": target_url,
        "findings": findings,
        "metrics": metrics
    }

def audit_render(target_input, input_json_path=None, max_pages=8):
    """
    Main entrypoint for Skill 2. Can audit a standalone URL or consume Skill 1's output JSON.
    """
    browser_bin = find_headless_browser()
    
    urls_to_audit = []
    if input_json_path and os.path.exists(input_json_path):
        try:
            with open(input_json_path, "rb") as f:
                raw_bytes = f.read()
                # Support UTF-16 (Windows PowerShell '>' redirection) and UTF-8
                if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
                    content = raw_bytes.decode("utf-16", errors="replace")
                else:
                    content = raw_bytes.decode("utf-8", errors="replace")
                skill1_data = json.loads(content)
                sampled = skill1_data.get("sampled_pages", {})
                curated = sampled.get("curated_sample", [])
                if curated:
                    urls_to_audit = curated[:max_pages]
        except Exception:
            pass

    if not urls_to_audit:
        if not target_input.startswith("http://") and not target_input.startswith("https://"):
            target_url = f"https://{target_input}"
        else:
            target_url = target_input
        urls_to_audit = [target_url]

    parsed = urlparse(urls_to_audit[0])
    site_domain = parsed.netloc

    all_findings = []
    per_page_metrics = []

    for url in urls_to_audit:
        res = audit_render_parity(url, browser_bin)
        all_findings.extend(res["findings"])
        per_page_metrics.append({
            "url": url,
            "metrics": res["metrics"]
        })

    # Summary counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        s = f["severity"].lower()
        if s in severity_counts:
            severity_counts[s] += 1

    return {
        "site": site_domain,
        "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_findings": len(all_findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": all_findings,
        "render_profile": {
            "browser_engine": os.path.basename(browser_bin) if browser_bin else "None (Static Fallback)",
            "pages_audited": len(urls_to_audit),
            "per_page_metrics": per_page_metrics
        }
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_render.py <domain_or_url> [--input-json <path>] [--max-pages <N>] [--json]")
        sys.exit(1)

    target = sys.argv[1]
    input_json_path = None
    if "--input-json" in sys.argv:
        idx = sys.argv.index("--input-json")
        if idx + 1 < len(sys.argv):
            input_json_path = sys.argv[idx + 1]

    max_pages = 8
    if "--max-pages" in sys.argv:
        idx = sys.argv.index("--max-pages")
        if idx + 1 < len(sys.argv):
            try:
                max_pages = int(sys.argv[idx + 1])
            except ValueError:
                pass

    result = audit_render(target, input_json_path=input_json_path, max_pages=max_pages)

    if "--json" in sys.argv or not sys.stdout.isatty():
        print(json.dumps(result, indent=2))
    else:
        print(f"\nJavaScript Render & Parity Audit for: {result['site']}")
        print(f"Engine: {result['render_profile']['browser_engine']}")
        print(f"Pages Audited ({result['render_profile']['pages_audited']}):")
        for p in result['render_profile']['per_page_metrics']:
            m = p['metrics']
            print(f"  • {p['url']} → Parity: {m.get('parity_pct', 0)}% (Pass A: {m.get('pass_a_latency_ms', 0)}ms, Pass B: {m.get('pass_b_latency_ms', 0)}ms)")
        print(f"\nSummary: {result['summary']['total_findings']} total findings "
              f"({result['summary']['critical']} Critical, {result['summary']['high']} High, "
              f"{result['summary']['medium']} Medium)\n")
        for f in result["findings"]:
            print(f"[{f['id']}] {f['title']} ({f['severity'].upper()})")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']['summary']}\n")

if __name__ == "__main__":
    main()
