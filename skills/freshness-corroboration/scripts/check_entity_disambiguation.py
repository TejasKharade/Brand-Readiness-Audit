import sys
import json
import re
import urllib.parse
from html.parser import HTMLParser

# Maximum web search calls per script execution (for orchestrator search budgeting)
MAX_SEARCHES_PER_SCRIPT = 3

def extract_domain(url_str):
    if not url_str or not isinstance(url_str, str):
        return ""
    s = url_str.strip()
    if not s:
        return ""
    # Fix Bug 1: Prepend scheme if missing so urllib.parse populates netloc for bare domains (e.g. 'acme.com')
    if "://" not in s:
        s = "https://" + s
    try:
        parsed = urllib.parse.urlparse(s)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""

def is_same_or_subdomain(d1, d2):
    """Fix Bug 2: Replace raw substring ('in') with exact domain or valid subdomain matching."""
    if not d1 or not d2:
        return False
    d1 = d1.lower().strip()
    d2 = d2.lower().strip()
    return d1 == d2 or d1.endswith("." + d2) or d2.endswith("." + d1)

def extract_json_ld_blocks(html_text):
    """
    Fix Bug 3: Robust balanced-brace JSON-LD block extraction that handles literal
    </script> tags or escaped quotes inside JSON string literals without truncating.
    """
    if not html_text:
        return []
    blocks = []
    for m in re.finditer(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>', html_text, re.IGNORECASE):
        start_idx = m.end()
        obj_start = -1
        for i in range(start_idx, len(html_text)):
            if html_text[i] in '{[':
                obj_start = i
                break
        if obj_start == -1:
            continue
        
        stack = []
        in_string = False
        escape = False
        obj_end = -1
        for i in range(obj_start, len(html_text)):
            ch = html_text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch in '{[':
                    stack.append(ch)
                elif ch in '}]':
                    if stack:
                        stack.pop()
                        if not stack:
                            obj_end = i + 1
                            break
        if obj_end != -1:
            blocks.append(html_text[obj_start:obj_end])
    return blocks

def extract_same_as_links(html_content):
    same_as_links = []
    if not html_content:
        return same_as_links

    json_blocks = extract_json_ld_blocks(html_content)

    def search_obj(obj):
        if isinstance(obj, dict):
            # Fix Secondary 2: Explicitly handle @type whether it's a string or list
            raw_type = obj.get('@type', '')
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            types_lower = [str(t).lower() for t in types if t]

            if any(t in ['organization', 'corporation', 'brand', 'localbusiness', 'store', 'restaurant'] or 'organization' in t for t in types_lower):
                same_as = obj.get('sameAs')
                if isinstance(same_as, str) and same_as.strip():
                    same_as_links.append(same_as.strip())
                elif isinstance(same_as, list):
                    for u in same_as:
                        if isinstance(u, str) and u.strip():
                            same_as_links.append(u.strip())
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    search_obj(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    search_obj(item)

    for block_str in json_blocks:
        try:
            data = json.loads(block_str)
            search_obj(data)
        except Exception:
            pass

    # Fix Secondary 3: Normalize URLs for deduplication while preserving original formatting
    seen_normalized = set()
    deduped = []
    for link in same_as_links:
        try:
            p = urllib.parse.urlparse(link)
            norm = f"{p.scheme.lower()}://{p.netloc.lower()}{p.path}".rstrip('/')
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                deduped.append(link)
        except Exception:
            if link not in deduped:
                deduped.append(link)

    return deduped

def extract_url_from_item(item):
    """Fix Secondary 4: Fallback across url, link, href for search result item key flexibility."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("url") or item.get("link") or item.get("href") or ""
    return ""

def check_entity_disambiguation(params):
    brand_name = params.get("brand_name", "")
    domain = params.get("domain", "")
    html_content = params.get("html", "")
    bare_name_results = params.get("bare_name_results", [])
    wikipedia_results = params.get("wikipedia_results", [])
    wikidata_results = params.get("wikidata_results", [])

    # 1. On-site JSON-LD sameAs extraction
    same_as_links = extract_same_as_links(html_content)
    has_wiki_sameas = any('wikipedia.org' in u.lower() or 'wikidata.org' in u.lower() for u in same_as_links)

    # 2. Bare name search evaluation
    target_domain_norm = extract_domain(domain)
    search_domains = []
    target_in_top_results = False

    if isinstance(bare_name_results, list):
        for item in bare_name_results[:10]:
            u = extract_url_from_item(item)
            d = extract_domain(u)
            if d:
                search_domains.append(d)
                if is_same_or_subdomain(d, target_domain_norm):
                    target_in_top_results = True

    # 3. Wikipedia & Wikidata presence check
    wikipedia_page_found = False
    if isinstance(wikipedia_results, list):
        for item in wikipedia_results:
            u = extract_url_from_item(item)
            if 'wikipedia.org' in u.lower():
                wikipedia_page_found = True
                break

    wikidata_entry_found = False
    if isinstance(wikidata_results, list):
        for item in wikidata_results:
            u = extract_url_from_item(item)
            if 'wikidata.org' in u.lower():
                wikidata_entry_found = True
                break

    return {
        "brand_name": brand_name,
        "domain": domain,
        "same_as_links": same_as_links,
        "has_wikidata_or_wikipedia_sameas": has_wiki_sameas,
        "bare_name_search": {
            "search_result_domains": search_domains,
            "target_domain_in_top_results": target_in_top_results
        },
        "wikipedia_page_found": wikipedia_page_found,
        "wikidata_entry_found": wikidata_entry_found
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        result = check_entity_disambiguation(params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "brand_name": None,
            "domain": None,
            "same_as_links": [],
            "has_wikidata_or_wikipedia_sameas": False,
            "bare_name_search": {
                "search_result_domains": [],
                "target_domain_in_top_results": False
            },
            "wikipedia_page_found": False,
            "wikidata_entry_found": False,
            "script_error": str(e)
        }))
