#!/usr/bin/env python3
"""
check_content_quality.py - Full-Content AI Citability & RAG Chunking Auditor

Audits the entire content of every webpage section-by-section (zero skipping)
for RAG embedding chunkability, ambiguous anaphora (orphan pronouns), low-entropy
headings, content flooding, and BLUF direct-answer standards.

Part of the brand-ai-readiness-audit suite (Gate 4: AI Citability & Content Quality).
Standard: agentskills.io
Pure Python Standard Library - Zero External Dependencies.
"""

import sys
import os
import re
import json
import ssl
import html
import argparse
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from urllib.error import URLError, HTTPError

USER_AGENT = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

LOW_ENTROPY_HEADINGS = {
    "overview",
    "introduction",
    "background",
    "details",
    "summary",
    "more information",
    "more info",
    "about",
    "features",
    "general",
    "misc",
    "miscellaneous",
    "notes",
    "conclusion",
    "info"
}

ORPHAN_PRONOUN_PATTERN = re.compile(
    r"^(?:it|they|this\s+(?:tool|platform|solution|system|software|library|framework|service|app|utility)|as\s+(?:mentioned|stated|seen|discussed)\s+(?:above|earlier|before)|like\s+we\s+said)\b",
    re.IGNORECASE
)

PREAMBLE_FLUFF_PATTERNS = [
    re.compile(r"in today'?s (?:fast-paced|rapidly changing|digital|modern) (?:world|era|landscape)", re.IGNORECASE),
    re.compile(r"in (?:the|an) era of\b", re.IGNORECASE),
    re.compile(r"it is no secret that\b", re.IGNORECASE),
    re.compile(r"have you ever wondered\b", re.IGNORECASE),
    re.compile(r"in an increasingly (?:connected|complex) world\b", re.IGNORECASE),
    re.compile(r"businesses (?:everywhere|today) are (?:striving|looking) to\b", re.IGNORECASE)
]


def load_json_multienconding(filepath):
    """Safely loads JSON handling UTF-8, UTF-16, and UTF-8-BOM."""
    for enc in ["utf-8-sig", "utf-16", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"Unable to parse JSON file {filepath} with any supported encoding.")


def fetch_raw_html(url, timeout=12):
    """Fetches raw HTML stream simulating AI search crawler with gzip and retry support."""
    import gzip
    import time
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    last_err = None
    for attempt in range(2):
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return None, f"Non-HTML content type: {content_type}"
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                raw_bytes = resp.read()
                if raw_bytes.startswith(b"\x1f\x8b") or resp.headers.get("content-encoding") == "gzip":
                    try:
                        raw_bytes = gzip.decompress(raw_bytes)
                    except Exception:
                        pass
                try:
                    text = raw_bytes.decode(charset, errors="replace")
                except Exception:
                    text = raw_bytes.decode("utf-8", errors="replace")
                return text, None
        except HTTPError as e:
            return None, f"HTTP {e.code} ({e.reason})"
        except Exception as e:
            last_err = f"Network Error: {str(e)}"
            if attempt == 0:
                time.sleep(1)
                continue
    return None, last_err or "Connection failed after 2 attempts"


def detect_archetype(url):
    """Calibrates page archetype based on URL slug."""
    path = urlparse(url).path.lower().rstrip("/")
    if not path or path == "":
        return "homepage"
    if any(p in path for p in ["/docs", "/documentation", "/api", "/reference", "/build"]):
        return "documentation"
    if any(p in path for p in ["/blog", "/guide", "/guides", "/article", "/articles", "/posts", "/post"]):
        return "guide_article"
    if any(p in path for p in ["/pricing", "/product", "/products", "/plans"]):
        return "pricing_product"
    return "general"


def clean_html_strip_boilerplate(raw_html):
    """Strips non-content tags (nav, footer, script, style) without losing section body."""
    if not raw_html:
        return ""
    # Strip script, style, noscript, svg
    clean = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    # Strip comments
    clean = re.sub(r"<!--.*?-->", " ", clean, flags=re.DOTALL)
    # Strip navigation, footer, aside boilerplate
    clean = re.sub(r"<(nav|footer|aside)[^>]*>.*?</\1>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
    return clean


def partition_into_sections(cleaned_html):
    """
    Partitions the entire body into sequential sections demarcated by headings.
    Captures 100% of the substantive page content without skipping anything.
    """
    heading_pattern = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
    matches = list(heading_pattern.finditer(cleaned_html))

    sections = []

    if not matches:
        # No headings on page - treat entire content as single section
        text = extract_text_from_html(cleaned_html)
        if text:
            sections.append({
                "level": 0,
                "heading": "Preamble / Document Body",
                "html": cleaned_html,
                "text": text,
                "word_count": len(text.split()),
                "sentences": split_sentences(text)
            })
        return sections

    # 1. Capture opening preamble before the first heading
    first_match_start = matches[0].start()
    preamble_html = cleaned_html[:first_match_start].strip()
    preamble_text = extract_text_from_html(preamble_html)
    if preamble_text and len(preamble_text.split()) >= 10:
        sections.append({
            "level": 0,
            "heading": "Document Preamble",
            "html": preamble_html,
            "text": preamble_text,
            "word_count": len(preamble_text.split()),
            "sentences": split_sentences(preamble_text)
        })

    # 2. Iterate through every heading and its succeeding content
    for idx, match in enumerate(matches):
        level = int(match.group(1))
        raw_heading = match.group(2)
        heading_text = extract_text_from_html(raw_heading)

        content_start = match.end()
        content_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned_html)
        section_html = cleaned_html[content_start:content_end].strip()
        section_text = extract_text_from_html(section_html)

        sections.append({
            "level": level,
            "heading": heading_text,
            "html": section_html,
            "text": section_text,
            "word_count": len(section_text.split()) if section_text else 0,
            "sentences": split_sentences(section_text) if section_text else []
        })

    return sections


def extract_text_from_html(html_snippet):
    """Converts HTML snippet to clean visible plain text."""
    if not html_snippet:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html_snippet)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def split_sentences(text):
    """Splits text into clean sentence list."""
    if not text:
        return []
    # Split on periods/exclamations/questions followed by space and capital letter or end
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'‘“])", text)
    return [s.strip() for s in raw if len(s.strip()) > 3]


def get_url_depth(u):
    p = urlparse(u).path.strip("/")
    return len([seg for seg in p.split("/") if seg]) if p else 0


class ContentQualityAuditor:
    def __init__(self, target_url, input_access=None, max_pages=15):
        self.target_url = target_url
        self.input_access = input_access
        self.max_pages = max_pages
        self.parsed_url = urlparse(target_url)
        self.domain = self.parsed_url.netloc
        self.findings = []
        self.content_profile = {
            "pages_audited": 0,
            "total_sections_audited": 0,
            "total_words_audited": 0,
            "autonomous_chunk_ratio_pct": 100.0,
            "pages": []
        }

    def _add_finding(self, code, title, severity, evidence, suggested_action, url=None):
        finding_id = f"CNT-{len(self.findings) + 1:03d}"
        self.findings.append({
            "id": finding_id,
            "code": code,
            "title": title,
            "severity": severity,
            "url": url or self.target_url,
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
                elif "skills" in access_data and "skill_1" in access_data["skills"]:
                    curated_sample = access_data["skills"]["skill_1"].get("sampled_pages", {}).get("curated_sample", [])
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

        # Cap to at most max_pages
        urls_to_audit = urls_to_audit[:self.max_pages]
        self.content_profile["pages_audited"] = len(urls_to_audit)

        total_sections = 0
        autonomous_sections = 0

        for page_url in urls_to_audit:
            p_sec, p_auto = self._audit_single_page(page_url)
            total_sections += p_sec
            autonomous_sections += p_auto

        if total_sections > 0:
            pct = round((autonomous_sections / total_sections) * 100, 1)
            self.content_profile["autonomous_chunk_ratio_pct"] = pct

        return self.to_dict()

    def _audit_single_page(self, page_url):
        depth = get_url_depth(page_url)
        raw_html, err = fetch_raw_html(page_url)
        if err or not raw_html:
            self.content_profile.setdefault("pages", []).append({
                "url": page_url,
                "depth": depth,
                "status": 0,
                "error": err or "Empty response",
                "archetype": "unknown",
                "sections_count": 0,
                "word_count": 0,
                "headings": []
            })
            self._add_finding(
                code="PAGE_FETCH_ERROR",
                title=f"Failed to fetch content on {urlparse(page_url).path or '/'}: {err or 'Empty response'}",
                severity="HIGH",
                evidence=f"Request to {page_url} failed: {err or 'Empty response'}",
                suggested_action="Ensure the server is responsive and that firewalls do not block automated search crawler requests.",
                url=page_url
            )
            return 0, 0

        archetype = detect_archetype(page_url)
        cleaned_html = clean_html_strip_boilerplate(raw_html)
        sections = partition_into_sections(cleaned_html)

        page_word_count = sum(s["word_count"] for s in sections)
        self.content_profile["total_words_audited"] += page_word_count
        self.content_profile["total_sections_audited"] += len(sections)

        self.content_profile["pages"].append({
            "url": page_url,
            "depth": depth,
            "status": 200,
            "error": None,
            "archetype": archetype,
            "sections_count": len(sections),
            "word_count": page_word_count,
            "headings": [s["heading"] for s in sections if s["level"] > 0]
        })

        substantive_sections = 0
        autonomous_sections = 0

        # Section-by-Section Full Content Audit (Zero Skipping)
        for idx, sec in enumerate(sections):
            heading = sec["heading"]
            text = sec["text"]
            wc = sec["word_count"]
            sentences = sec["sentences"]
            sec_html = sec["html"]

            if wc < 15 and not re.search(r"<img", sec_html, re.IGNORECASE):
                continue

            substantive_sections += 1
            is_autonomous = True

            # Check 1: RAG_CHUNK_ORPHAN_PRONOUN (Ambiguous Anaphora)
            if sentences and wc >= 25 and sec["level"] > 0:
                first_sent = sentences[0].strip()
                if ORPHAN_PRONOUN_PATTERN.search(first_sent):
                    is_autonomous = False
                    sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
                    self._add_finding(
                        code="RAG_CHUNK_ORPHAN_PRONOUN",
                        title=f"Section '{heading}' opens with an ambiguous pronoun (orphan chunk risk)",
                        severity="HIGH",
                        evidence=(
                            f"Opening sentence: '{first_sent}'\n"
                            f"Actual Section Content Excerpt:\n  \"{sample_excerpt}\"\n"
                            f"The section relies on an ambiguous pronoun rather than naming the explicit subject entity."
                        ),
                        suggested_action=f"Replace the opening pronoun with the explicit brand or technical noun (e.g. name the tool/feature directly) so RAG vector chunkers retain context.",
                        url=page_url
                    )

            if is_autonomous:
                autonomous_sections += 1

            # Check 2: RAG_HEADING_LOW_ENTROPY
            if sec["level"] > 0 and heading:
                norm_heading = heading.lower().strip()
                # If heading is solely one of the low-entropy words
                if norm_heading in LOW_ENTROPY_HEADINGS:
                    sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
                    self._add_finding(
                        code="RAG_HEADING_LOW_ENTROPY",
                        title=f"Heading '{heading}' has low semantic entropy",
                        severity="MEDIUM",
                        evidence=(
                            f"Heading '{heading}' provides zero search-intent tokens when prepended to chunk embeddings.\n"
                            f"Section Content Excerpt:\n  \"{sample_excerpt}\""
                        ),
                        suggested_action=f"Rename '{heading}' to include specific topic nouns (e.g., replace 'Overview' with 'System Architecture Overview' or 'Installation Guide').",
                        url=page_url
                    )

            # Check 2b: BLUF_QUESTION_ANSWER_DEFICIT (Question-Heading Direct Answer)
            if sec["level"] > 0 and heading and sentences and archetype != "homepage":
                is_question = bool(re.search(r"\?$|^(?:what|how|why|when|where|is|can|does|which)\b", heading.strip(), re.IGNORECASE))
                if is_question and len(sentences) >= 1:
                    first_sent = sentences[0].strip()
                    if re.search(r"^(?:in this (?:section|article|post)|to (?:understand|answer) this|before (?:we|diving)|it is important to note|let'?s (?:take a look|explore))\b", first_sent, re.IGNORECASE):
                        sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
                        self._add_finding(
                            code="BLUF_QUESTION_ANSWER_DEFICIT",
                            title=f"Question heading '{heading}' lacks a direct answer in its opening sentence",
                            severity="MEDIUM",
                            evidence=(
                                f"Heading is a direct question ('{heading}'), but opening sentence deflects rather than answering directly:\n  \"{first_sent}\"\n"
                                f"Section Opening:\n  \"{sample_excerpt}\""
                            ),
                            suggested_action="Adopt Bottom-Line-Up-Front (BLUF): formulate the direct answer to the heading's question in the very first sentence so AI search engines can quote it immediately.",
                            url=page_url
                        )

            # Check 3: BLUF_FLUFF_PREAMBLE (First 150 words of guide/blog)
            if idx <= 1 and archetype in ("guide_article", "general") and wc >= 30:
                first_150_words = " ".join(text.split()[:150])
                for pattern in PREAMBLE_FLUFF_PATTERNS:
                    match = pattern.search(first_150_words)
                    if match:
                        sample_excerpt = first_150_words[:260] + ("..." if len(first_150_words) > 260 else "")
                        self._add_finding(
                            code="BLUF_FLUFF_PREAMBLE",
                            title=f"Opening text contains generic throat-clearing fluff instead of a direct answer",
                            severity="MEDIUM",
                            evidence=(
                                f"Found cliche '{match.group(0)}' in opening text.\n"
                                f"Opening Text Excerpt:\n  \"{sample_excerpt}\""
                            ),
                            suggested_action="Adopt Bottom-Line-Up-Front (BLUF): remove introductory digital cliches and provide a direct declarative definition in the first sentence.",
                            url=page_url
                        )
                        break

            # Check 4: RAG_SECTION_CONTENT_FLOODING (Archetype Calibrated)
            has_lists = bool(re.search(r"<(ul|ol)", sec_html, re.IGNORECASE))
            has_tables = bool(re.search(r"<table", sec_html, re.IGNORECASE))
            has_code = bool(re.search(r"<(pre|code)", sec_html, re.IGNORECASE))

            threshold = 400 if archetype in ("guide_article", "general") else 800 if archetype == "documentation" else 99999
            if archetype != "homepage" and wc > threshold:
                if not has_lists and not has_tables and not (archetype == "documentation" and has_code):
                    sample_excerpt = text[:260] + ("..." if len(text) > 260 else "")
                    self._add_finding(
                        code="RAG_SECTION_CONTENT_FLOODING",
                        title=f"Section '{heading}' contains continuous prose flooding ({wc} words)",
                        severity="MEDIUM",
                        evidence=(
                            f"Section contains {wc} words of continuous prose without subheadings, bullet lists, or tables, triggering 'Lost in the Middle' attention degradation in LLM retrieval.\n"
                            f"Section Opening Excerpt:\n  \"{sample_excerpt}\""
                        ),
                        suggested_action="Break this section into self-contained 40-80 word paragraphs and introduce subheadings (<h3>) or bulleted lists.",
                        url=page_url
                    )

            # Check 5: CONTENT_LOCK_IMAGE_TRAP
            if wc < 15 and re.search(r"<img", sec_html, re.IGNORECASE):
                img_matches = re.findall(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', sec_html, re.IGNORECASE)
                for src in img_matches:
                    src_lower = src.lower()
                    if any(k in src_lower for k in ["pricing", "comparison", "benchmark", "architecture", "table", "specs", "features"]):
                        self._add_finding(
                            code="CONTENT_LOCK_IMAGE_TRAP",
                            title=f"Substantive data appears locked inside image asset ({os.path.basename(src)})",
                            severity="MEDIUM",
                            evidence=f"Section '{heading}' has only {wc} words of text but embeds '{os.path.basename(src)}'. AI crawlers cannot index or cite data locked in raster images.",
                            suggested_action="Provide an HTML <table> or structured text equivalent alongside the image so AI search engines can ingest the data.",
                            url=page_url
                        )
                        break

        # Page-Level Proactive Info Checks (Zero Severity Penalty)
        self._evaluate_page_proactive_suggestions(page_url, archetype, page_word_count, cleaned_html)

        return substantive_sections, autonomous_sections

    def _evaluate_page_proactive_suggestions(self, page_url, archetype, page_word_count, cleaned_html):
        """Generates constructive INFO suggestions without penalizing the site score."""
        # 1. Statistical Density Suggestion on substantive articles
        if archetype == "guide_article" and page_word_count >= 350:
            plain_text = extract_text_from_html(cleaned_html)
            numeric_data = re.findall(r"\b(?:\d+(?:\.\d+)?%|\d+\s*(?:ms|gb|mb|tb|kbps|mbps|req/s|qps))\b", plain_text, re.IGNORECASE)
            if len(numeric_data) == 0:
                self._add_finding(
                    code="CITABILITY_STATISTICAL_SUGGESTION",
                    title="Consider adding quantitative metrics to improve AI citation probability",
                    severity="INFO",
                    evidence=f"Page contains {page_word_count} words but 0 explicit numeric statistics or benchmarks.",
                    suggested_action="The Princeton GEO study demonstrated that adding verifiable statistics increases AI citation probability by +37%. Consider integrating benchmark data or concrete metrics.",
                    url=page_url
                )

        # 2. Tabular Formatting Suggestion on pricing content
        pricing_matches = re.findall(r"\b(?:free|pro|enterprise|starter|standard|plan|pricing)\b", cleaned_html, re.IGNORECASE)
        has_table = bool(re.search(r"<table", cleaned_html, re.IGNORECASE))
        has_currency = bool(re.search(r"[\$€£]\s*\d+", cleaned_html))

        if len(pricing_matches) >= 3 and has_currency and not has_table and archetype != "homepage":
            self._add_finding(
                code="STRUCTURE_TABULAR_SUGGESTION",
                title="Consider presenting comparative pricing options in a structured table",
                severity="INFO",
                evidence="Page contains multiple pricing indicators but 0 <table> elements. LLMs quote structured tables at a significantly higher rate than narrative prose.",
                suggested_action="Structure plan comparisons into an HTML <table> with rows and columns for plan names, prices, and features.",
                url=page_url
            )

        # 3. External Attribution vs. Circular Self-Citation
        if archetype in ("guide_article", "general") and page_word_count >= 350:
            all_links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>', cleaned_html, re.IGNORECASE)
            parsed_target = urlparse(page_url)
            internal_links = []
            external_links = []
            for link in all_links:
                if link.startswith("#") or link.startswith("javascript:") or link.startswith("mailto:"):
                    continue
                p = urlparse(link)
                if not p.netloc or p.netloc.lower() == parsed_target.netloc.lower():
                    internal_links.append(link)
                else:
                    external_links.append(link)

            # Circular citation check: Has links, but 100% of them point to own domain
            if len(all_links) >= 3 and len(external_links) == 0:
                self._add_finding(
                    code="CITABILITY_CIRCULAR_CITATION",
                    title="Article relies entirely on circular self-citations with zero external reference links",
                    severity="MEDIUM",
                    evidence=f"Page contains {len(internal_links)} links, but 100% of them point back to {parsed_target.netloc}. Zero external primary sources or research citations are provided.",
                    suggested_action="Integrate outbound citations to authoritative external sources (standards, benchmarks, institutional studies) to establish a verifiable credibility chain for LLMs.",
                    url=page_url
                )

        # 4. Temporal Anchoring Recency Check
        if archetype in ("guide_article", "documentation") and page_word_count >= 300:
            plain_text = extract_text_from_html(cleaned_html)
            has_recent_year = bool(re.search(r"\b(2025|2026)\b", plain_text))
            has_stale_year = bool(re.search(r"\b(2020|2021|2022|2023)\b", plain_text))
            has_update_marker = bool(re.search(r"\b(updated|last modified|as of)\b", plain_text, re.IGNORECASE))
            if has_stale_year and not has_recent_year and not has_update_marker:
                self._add_finding(
                    code="TEMPORAL_ANCHORING_SUGGESTION",
                    title="Content contains older year references with no recent temporal anchors",
                    severity="INFO",
                    evidence=f"Page mentions historical years without recent temporal anchors (2025/2026 or 'Updated' markers).",
                    suggested_action="Add explicit temporal markers (e.g., 'Updated for 2026' or 'As of Q1 2026') to signal to generative engines that this content remains current.",
                    url=page_url
                )

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
            "content_profile": self.content_profile
        }


def main():
    parser = argparse.ArgumentParser(description="Full-Content AI Citability & RAG Chunking Auditor")
    parser.add_argument("url", help="Target domain or root URL (e.g., https://example.com)")
    parser.add_argument("--input-access", help="Path to Skill 1 output JSON (sampled_pages)")
    parser.add_argument("--max-pages", type=int, default=15, help="Maximum pages to audit (default: 15)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON to stdout")

    args = parser.parse_args()

    url = args.url
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    auditor = ContentQualityAuditor(
        target_url=url,
        input_access=args.input_access,
        max_pages=args.max_pages
    )

    report = auditor.run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nContent Quality & AI Citability Audit for: {report['site']}")
        print(f"Pages Audited ({report['content_profile']['pages_audited']}):")
        for p in report['content_profile'].get('pages', []):
            status_desc = f"HTTP {p.get('status', 0)}" if p.get('status') else f"Failed ({p.get('error', 'Unknown')})"
            print(f"  • [Depth {p.get('depth', 0)}] [{p.get('archetype', 'general')}] {p['url']} → {p.get('sections_count', 0)} sections, {p.get('word_count', 0)} words ({status_desc})")
        print(f"\nTotal Sections: {report['content_profile']['total_sections_audited']} | "
              f"Total Words: {report['content_profile']['total_words_audited']}")
        print(f"Autonomous Chunk Ratio: {report['content_profile']['autonomous_chunk_ratio_pct']}%")
        print(f"Summary: {report['summary']['total_findings']} total findings "
              f"({report['summary']['critical']} Critical, {report['summary']['high']} High, "
              f"{report['summary']['medium']} Medium, {report['summary']['info']} Info)\n")

        for f in report["findings"]:
            print(f"[{f['code']}] {f['title']} ({f['severity']})")
            print(f"  Url:      {f['url']}")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']}\n")


if __name__ == "__main__":
    main()
