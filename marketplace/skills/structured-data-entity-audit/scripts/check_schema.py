#!/usr/bin/env python3
"""
check_schema.py - Structured Data, Entity Grounding, and Semantic Parity Auditor

Audits websites for Schema.org Knowledge Graph grounding, authoritative sameAs
disambiguation, atomic fact consistency (pricing, availability, versioning), and
description extractability. Distinguishes static schema from client-JS-deferred schema.

Part of the brand-ai-readiness-audit suite (Gate 3: Content Understandability & Entity Trust).
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
from urllib.parse import urlparse, urljoin
from urllib.error import URLError, HTTPError

USER_AGENT = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

# Authoritative Entity Graph domains whitelist
AUTHORITY_REGISTRY = [
    "wikidata.org",
    "wikipedia.org",
    "github.com",
    "gitlab.com",
    "crates.io",
    "npmjs.com",
    "pypi.org",
    "docker.com",
    "pkg.go.dev",
    "linkedin.com",
    "crunchbase.com",
    "opencorporates.com",
    "x.com",
    "twitter.com"
]

ROOT_ENTITY_TYPES = {
    "Organization",
    "Corporation",
    "LocalBusiness",
    "OnlineBusiness",
    "Brand",
    "SoftwareApplication",
    "WebApplication",
    "MobileApplication",
    "NGO"
}

BUZZWORD_PATTERNS = [
    r"leading provider of\b",
    r"innovative (?:solutions|products|technology)\b",
    r"cutting-edge\b",
    r"all-in-one (?:platform|solution)\b",
    r"world-class\b",
    r"seamless (?:end-to-end|integration)\b",
    r"next-generation\b",
    r"empowering businesses\b",
    r"game-changing\b",
    r"transform(?:ing)? your workflow\b",
    r"scalable synergy\b"
]


def load_json_multienconding(filepath):
    """Safely loads JSON from disk handling UTF-8, UTF-16, and UTF-8-BOM."""
    for enc in ["utf-8-sig", "utf-16", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"Unable to parse JSON file {filepath} with any supported encoding.")


def fetch_raw_html(url, timeout=12):
    """Fetches raw HTML stream simulating AI search crawler."""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None, f"Non-HTML content type: {content_type}"
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw_bytes = resp.read()
            try:
                text = raw_bytes.decode(charset, errors="replace")
            except Exception:
                text = raw_bytes.decode("utf-8", errors="replace")
            return text, None
    except HTTPError as e:
        return None, f"HTTP Error {e.code}: {e.reason}"
    except URLError as e:
        return None, f"URL Error: {e.reason}"
    except Exception as e:
        return None, f"Network Error: {str(e)}"


def extract_visible_text(html_content):
    """Strips tags, scripts, and comments to yield clean visible text."""
    if not html_content:
        return ""
    # Remove script and style elements
    clean = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    clean = re.sub(r"<!--.*?-->", " ", clean, flags=re.DOTALL)
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Unescape entities
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def extract_json_ld(html_content):
    """
    Extracts all JSON-LD blocks from raw HTML.
    Returns:
        parsed_objects: list of parsed dicts
        syntax_errors: list of error descriptions
    """
    if not html_content:
        return [], []

    pattern = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(html_content)

    parsed_objects = []
    syntax_errors = []

    for idx, raw_snippet in enumerate(matches):
        snippet_str = raw_snippet.strip()
        if not snippet_str:
            continue

        try:
            data = json.loads(snippet_str)
            _collect_schema_nodes(data, parsed_objects)
        except json.JSONDecodeError as err:
            # Attempt recovery: unescape HTML entities
            recovered = False
            try:
                unescaped = html.unescape(snippet_str)
                data = json.loads(unescaped)
                _collect_schema_nodes(data, parsed_objects)
                recovered = True
            except Exception:
                pass

            if not recovered:
                # Attempt recovery: strip JS comments
                try:
                    no_comments = re.sub(r"//.*?\n|/\*.*?\*/", "", snippet_str)
                    data = json.loads(no_comments)
                    _collect_schema_nodes(data, parsed_objects)
                    recovered = True
                except Exception:
                    pass

            if not recovered:
                syntax_errors.append(f"Tag #{idx+1} JSON parse error: {str(err)} near '{snippet_str[:60]}...'")

    return parsed_objects, syntax_errors


def _collect_schema_nodes(node, collector):
    """Recursively flattens JSON-LD objects, arrays, and @graph nodes."""
    if isinstance(node, dict):
        if "@graph" in node and isinstance(node["@graph"], list):
            for child in node["@graph"]:
                _collect_schema_nodes(child, collector)
        else:
            collector.append(node)
            # Inspect nested entities (e.g. publisher, brand, offers, mainEntity)
            for k, v in node.items():
                if isinstance(v, dict) and "@type" in v:
                    _collect_schema_nodes(v, collector)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and "@type" in item:
                            _collect_schema_nodes(item, collector)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_nodes(item, collector)


def get_schema_types(schema_node):
    """Extracts @type as a set of strings from a schema node."""
    stype = schema_node.get("@type", "")
    if isinstance(stype, list):
        return set(stype)
    elif isinstance(stype, str) and stype:
        return {stype}
    return set()


def check_sameas_authorities(same_as_list):
    """Evaluates sameAs URLs against recognized authoritative registries."""
    if not same_as_list:
        return []
    if isinstance(same_as_list, str):
        same_as_list = [same_as_list]

    recognized = []
    for link in same_as_list:
        if not isinstance(link, str):
            continue
        try:
            parsed = urlparse(link)
            domain = parsed.netloc.lower()
            for auth in AUTHORITY_REGISTRY:
                if auth in domain:
                    recognized.append({"url": link, "authority": auth})
                    break
        except Exception:
            continue
    return recognized


class SchemaEntityAuditor:
    def __init__(self, target_url, input_access=None, input_render=None):
        self.target_url = target_url
        self.input_access = input_access
        self.input_render = input_render
        self.parsed_url = urlparse(target_url)
        self.domain = self.parsed_url.netloc
        self.findings = []
        self.entity_profile = {
            "root_entity_detected": False,
            "root_entity_types": [],
            "same_as_authorities": [],
            "pages_audited": 0,
            "pages_with_schema": 0,
            "schema_coverage_pct": 0.0
        }

    def _add_finding(self, code, title, severity, evidence, suggested_action, url=None):
        finding_id = f"ENT-{len(self.findings) + 1:03d}"
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
            except Exception:
                pass

        if curated_sample:
            for item in curated_sample:
                u = item.get("url") if isinstance(item, dict) else item
                if u and u.rstrip("/") not in seen_normalized:
                    urls_to_audit.append(u)
                    seen_normalized.add(u.rstrip("/"))

        # Cap audit to at most 6 pages for speed and token economy
        urls_to_audit = urls_to_audit[:6]
        self.entity_profile["pages_audited"] = len(urls_to_audit)

        # Check Skill 2 render profile for JS-deferred schema handoff
        js_timing_findings = []
        if self.input_render and os.path.isfile(self.input_render):
            try:
                render_data = load_json_multienconding(self.input_render)
                findings_list = render_data.get("findings", [])
                if not findings_list and "skill_2" in render_data:
                    findings_list = render_data.get("skill_2", {}).get("findings", [])
                for f in findings_list:
                    if f.get("code") == "STRUCTURED_DATA_TIMING":
                        js_timing_findings.append(f)
            except Exception:
                pass

        # If Skill 2 flagged deferred schema, surface it immediately
        for jf in js_timing_findings:
            self._add_finding(
                code="SCHEMA_TIMING_JS_DEFERRED",
                title="Structured data is injected via client-side JavaScript rather than static HTML",
                severity="HIGH",
                evidence=jf.get("evidence", "Schema exists in rendered DOM but is missing in raw HTTP fetch."),
                suggested_action="Embed JSON-LD <script type='application/ld+json'> in server-rendered static HTML so fast AI search bots (OAI-SearchBot) can read it without executing JavaScript.",
                url=jf.get("url", self.target_url)
            )

        # Audit each page
        for page_url in urls_to_audit:
            self._audit_single_page(page_url, is_homepage=(page_url == self.target_url or urlparse(page_url).path in ("", "/")))

        if self.entity_profile["pages_audited"] > 0:
            pct = round((self.entity_profile["pages_with_schema"] / self.entity_profile["pages_audited"]) * 100, 1)
            self.entity_profile["schema_coverage_pct"] = pct

        return self.to_dict()

    def _audit_single_page(self, page_url, is_homepage=False):
        raw_html, err = fetch_raw_html(page_url)
        if err or not raw_html:
            return

        visible_text = extract_visible_text(raw_html)
        schema_nodes, syntax_errors = extract_json_ld(raw_html)

        # Check 1: Syntax Validation
        for syn_err in syntax_errors:
            self._add_finding(
                code="SCHEMA_SYNTAX_INVALID",
                title=f"Malformed JSON-LD syntax on {urlparse(page_url).path or '/'}",
                severity="HIGH",
                evidence=syn_err,
                suggested_action="Ensure JSON-LD content strictly adheres to valid RFC 8259 JSON syntax without unescaped characters or unquoted attributes.",
                url=page_url
            )

        if schema_nodes:
            self.entity_profile["pages_with_schema"] += 1

        # Check 2: Homepage Entity Root Grounding (The Garage Problem)
        if is_homepage:
            self._evaluate_root_entity(page_url, schema_nodes)

        # Check 3: Atomic Fact Consistency (Price, Availability, Version)
        self._evaluate_fact_consistency(page_url, schema_nodes, visible_text)

        # Check 4: Extractability & Fluff Detection
        self._evaluate_description_extractability(page_url, schema_nodes)

    def _evaluate_root_entity(self, page_url, schema_nodes):
        if not schema_nodes:
            self._add_finding(
                code="ENTITY_ROOT_GROUNDING_MISSING",
                title="Homepage lacks root entity Schema.org definition (Organization or SoftwareApplication)",
                severity="HIGH",
                evidence="Zero Schema.org metadata found on homepage. AI search engines cannot establish verified brand identity or associate interior pages with an authoritative entity, risking attribution loss to third-party mirrors.",
                suggested_action="Add a <script type='application/ld+json'> declaring your Organization or SoftwareApplication, including name, url, description, and sameAs links to authoritative code and business registries.",
                url=page_url
            )
            return

        found_root_types = set()
        all_sameas = []

        for node in schema_nodes:
            types = get_schema_types(node)
            for t in types:
                if t in ROOT_ENTITY_TYPES:
                    found_root_types.add(t)

            sameas = node.get("sameAs")
            if sameas:
                if isinstance(sameas, list):
                    all_sameas.extend(sameas)
                elif isinstance(sameas, str):
                    all_sameas.append(sameas)

        if not found_root_types:
            self._add_finding(
                code="ENTITY_ROOT_GROUNDING_MISSING",
                title="Homepage lacks primary Organization or SoftwareApplication entity",
                severity="MEDIUM",
                evidence=f"Homepage declared generic schema types ({', '.join([list(get_schema_types(n))[0] for n in schema_nodes if get_schema_types(n)]) or 'WebSite'}) but lacks an explicit Organization, Brand, or SoftwareApplication definition.",
                suggested_action="Nest an Organization or SoftwareApplication schema in your homepage JSON-LD to ground your brand in AI Knowledge Graphs.",
                url=page_url
            )
        else:
            self.entity_profile["root_entity_detected"] = True
            self.entity_profile["root_entity_types"] = sorted(list(found_root_types))

            # Evaluate sameAs links
            recognized = check_sameas_authorities(all_sameas)
            self.entity_profile["same_as_authorities"] = [r["url"] for r in recognized]

            if not all_sameas:
                # Differentiate software/tech from general brands
                is_software = any("Software" in t or "Application" in t for t in found_root_types)
                severity = "HIGH" if is_software else "MEDIUM"
                self._add_finding(
                    code="ENTITY_SAMEAS_MISSING",
                    title="Root entity lacks authoritative sameAs disambiguation links",
                    severity=severity,
                    evidence=f"Declared entity ({', '.join(found_root_types)}) has no 'sameAs' property pointing to verified external knowledge graphs or code/package registries.",
                    suggested_action="Add 'sameAs' links pointing to your official GitHub repository, Crates.io/npm/PyPI package, LinkedIn company page, or Wikidata entry.",
                    url=page_url
                )
            elif not recognized:
                self._add_finding(
                    code="ENTITY_SAMEAS_WEAK",
                    title="Declared sameAs links do not reference recognized authority registries",
                    severity="LOW",
                    evidence=f"Found sameAs links ({', '.join(all_sameas[:3])}) but none match recognized global entity graphs (Wikidata, Wikipedia) or authority registries (GitHub, Crates.io, npm, LinkedIn).",
                    suggested_action="Include links to high-authority registries such as GitHub, Crates.io, LinkedIn, or Wikidata in your sameAs array.",
                    url=page_url
                )

    def _evaluate_fact_consistency(self, page_url, schema_nodes, visible_text):
        """Cross-examines pricing, stock availability, and version claims against on-page text."""
        if not schema_nodes or not visible_text:
            return

        for node in schema_nodes:
            # 1. Pricing Contradiction Check
            offers = node.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
            for offer in offer_list:
                price = offer.get("price") if isinstance(offer, dict) else None
                if price is not None:
                    try:
                        price_num = float(str(price).replace("$", "").replace(",", "").strip())
                        # Look for explicit contradictory prices in visible text
                        visible_prices = re.findall(r"(?:[\$€£]\s*(\d+(?:\.\d{2})?)|(\d+(?:\.\d{2})?)\s*(?:USD|EUR|GBP))", visible_text)
                        found_numbers = set()
                        for p1, p2 in visible_prices:
                            val = p1 or p2
                            if val:
                                try:
                                    found_numbers.add(float(val))
                                except ValueError:
                                    pass

                        # If schema claims a non-zero price, but page shows completely different pricing
                        if price_num > 0 and found_numbers and price_num not in found_numbers:
                            # Avoid false positives if page mentions other numbers by checking for common price indicators
                            if len(found_numbers) <= 3:
                                self._add_finding(
                                    code="SCHEMA_PRICE_CONTRADICTION",
                                    title=f"Structured data price (${price_num:g}) contradicts visible page pricing",
                                    severity="HIGH",
                                    evidence=f"JSON-LD offers.price claims {price_num:g}, but visible on-page text prominently displays {[f'${n:g}' for n in found_numbers]}.",
                                    suggested_action="Synchronize the JSON-LD offers.price with the actual visible pricing displayed to users.",
                                    url=page_url
                                )
                    except ValueError:
                        pass

                # 2. Availability Contradiction Check
                avail = offer.get("availability") if isinstance(offer, dict) else None
                if avail and isinstance(avail, str):
                    avail_clean = avail.split("/")[-1].lower()
                    if "instock" in avail_clean:
                        if re.search(r"\b(out of stock|sold out|currently unavailable)\b", visible_text, re.IGNORECASE):
                            self._add_finding(
                                code="SCHEMA_AVAILABILITY_CONTRADICTION",
                                title="Structured data claims 'InStock' but page displays 'Out of stock'",
                                severity="HIGH",
                                evidence="JSON-LD availability declares InStock, but visible page text contains 'Out of stock' or 'Sold out'.",
                                suggested_action="Update structured data availability to OutOfStock to prevent AI engines from misleading users on item availability.",
                                url=page_url
                            )
                    elif "outofstock" in avail_clean:
                        if re.search(r"\b(in stock|available now|ready to ship)\b", visible_text, re.IGNORECASE):
                            self._add_finding(
                                code="SCHEMA_AVAILABILITY_CONTRADICTION",
                                title="Structured data claims 'OutOfStock' but page displays 'In stock'",
                                severity="HIGH",
                                evidence="JSON-LD availability declares OutOfStock, but visible page text announces 'In stock' or 'Available now'.",
                                suggested_action="Synchronize structured data availability to InStock.",
                                url=page_url
                            )

            # 3. Software Version Contradiction
            version = node.get("softwareVersion") or node.get("version")
            if version and isinstance(version, str):
                # Check for newer version prominently in text
                ver_matches = re.findall(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", visible_text)
                if ver_matches and version not in ver_matches:
                    clean_v = version.lstrip("v")
                    if clean_v not in ver_matches:
                        # Find highest version in text
                        try:
                            schema_v_tuple = tuple(int(x) for x in clean_v.split(".") if x.isdigit())
                            max_text_v = None
                            for vm in ver_matches[:5]:
                                vt = tuple(int(x) for x in vm.split(".") if x.isdigit())
                                if len(vt) >= 2 and vt > schema_v_tuple:
                                    max_text_v = vm
                                    break
                            if max_text_v:
                                self._add_finding(
                                    code="SCHEMA_VERSION_STALE",
                                    title=f"Structured data softwareVersion ({version}) is stale",
                                    severity="MEDIUM",
                                    evidence=f"JSON-LD declares softwareVersion '{version}', while visible page text features newer version '{max_text_v}'.",
                                    suggested_action=f"Update JSON-LD softwareVersion property to match current release '{max_text_v}'.",
                                    url=page_url
                                )
                        except Exception:
                            pass

    def _evaluate_description_extractability(self, page_url, schema_nodes):
        """Checks schema descriptions for missing content, extreme brevity, or generic buzzword fluff."""
        if not schema_nodes:
            return

        missing_desc_by_type = {}

        for node in schema_nodes:
            types = get_schema_types(node)
            # Only evaluate load-bearing descriptive entities
            matching_types = types.intersection({"Organization", "Brand", "SoftwareApplication", "Product", "Service", "WebSite"})
            if not matching_types:
                continue

            primary_type = list(matching_types)[0]
            name = node.get("name")
            desc = node.get("description")

            if desc is None or (isinstance(desc, str) and not desc.strip()):
                if primary_type not in missing_desc_by_type:
                    missing_desc_by_type[primary_type] = []
                missing_desc_by_type[primary_type].append(name)
                continue

            if isinstance(desc, str):
                desc_clean = desc.strip()
                entity_label = f"{primary_type} ('{name}')" if name else primary_type
                if len(desc_clean) < 25:
                    self._add_finding(
                        code="SCHEMA_DESCRIPTION_TOO_SHORT",
                        title=f"Schema entity description is too brief ({len(desc_clean)} chars)",
                        severity="MEDIUM",
                        evidence=f"{entity_label} description ('{desc_clean}') provides insufficient semantic context for AI vector embeddings and summarization.",
                        suggested_action="Expand description to 60-150 characters with concrete functional capabilities and domain terms.",
                        url=page_url
                    )
                    continue

                # Check for vacuous buzzword density
                matches = [p for p in BUZZWORD_PATTERNS if re.search(p, desc_clean, re.IGNORECASE)]
                if len(matches) >= 2:
                    cleaned_matches = [m.replace(r"\b", "").replace("(?:", "").replace(")", "") for m in matches]
                    buzzwords_str = ", ".join(cleaned_matches)
                    self._add_finding(
                        code="SCHEMA_DESCRIPTION_VACUOUS",
                        title=f"Schema description for {entity_label} contains generic marketing fluff",
                        severity="MEDIUM",
                        evidence=f"Description ('{desc_clean[:100]}...') relies on generic corporate buzzwords ({buzzwords_str}) yielding zero atomic facts for AI RAG citation.",
                        suggested_action="Replace corporate buzzwords with concrete factual capabilities: specific protocols supported, architecture, target users, and key use cases.",
                        url=page_url
                    )

        # Emit aggregated missing description findings per type
        for stype, names in missing_desc_by_type.items():
            named_items = [n for n in names if n]
            if len(names) == 1:
                title_item = f"{stype} ('{named_items[0]}')" if named_items else stype
                self._add_finding(
                    code="SCHEMA_DESCRIPTION_MISSING",
                    title=f"Schema entity ({title_item}) lacks description property on {urlparse(page_url).path or '/'}",
                    severity="MEDIUM",
                    evidence=f"The {title_item} entity has no 'description' field. AI summarizers rely on this field for atomic entity synthesis.",
                    suggested_action="Provide a factual, 1-2 sentence description explaining what the entity is, who uses it, and its core capabilities.",
                    url=page_url
                )
            else:
                names_summary = f" ({', '.join(named_items[:3])}...)" if named_items else ""
                self._add_finding(
                    code="SCHEMA_DESCRIPTION_MISSING",
                    title=f"{len(names)} {stype} entities lack description property on {urlparse(page_url).path or '/'}",
                    severity="MEDIUM",
                    evidence=f"{len(names)} instances of {stype}{names_summary} have no 'description' field. AI summarizers rely on this field for atomic entity synthesis.",
                    suggested_action="Provide a factual, 1-2 sentence description for each entity explaining its capabilities and purpose.",
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
            "entity_profile": self.entity_profile
        }


def main():
    parser = argparse.ArgumentParser(description="Structured Data, Entity Grounding, and Semantic Parity Auditor")
    parser.add_argument("url", help="Target domain or root URL (e.g., https://example.com)")
    parser.add_argument("--input-access", help="Path to Skill 1 output JSON (sampled_pages)")
    parser.add_argument("--input-render", help="Path to Skill 2 output JSON (render_profile & timing)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON to stdout")

    args = parser.parse_args()

    url = args.url
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    auditor = SchemaEntityAuditor(
        target_url=url,
        input_access=args.input_access,
        input_render=args.input_render
    )

    report = auditor.run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nStructured Data & Entity Audit for: {report['site']}")
        print(f"Pages Audited: {report['entity_profile']['pages_audited']} (Schema Coverage: {report['entity_profile']['schema_coverage_pct']}%)")
        print(f"Root Entity: {'Found (' + ', '.join(report['entity_profile']['root_entity_types']) + ')' if report['entity_profile']['root_entity_detected'] else 'Missing'}")
        if report['entity_profile']['same_as_authorities']:
            print(f"sameAs Authorities: {', '.join(report['entity_profile']['same_as_authorities'])}")
        print(f"Summary: {report['summary']['total_findings']} total findings "
              f"({report['summary']['critical']} Critical, {report['summary']['high']} High, "
              f"{report['summary']['medium']} Medium, {report['summary']['low']} Low)\n")

        for f in report["findings"]:
            print(f"[{f['code']}] {f['title']} ({f['severity']})")
            print(f"  Url:      {f['url']}")
            print(f"  Evidence: {f['evidence']}")
            print(f"  Action:   {f['suggested_action']}\n")


if __name__ == "__main__":
    main()
