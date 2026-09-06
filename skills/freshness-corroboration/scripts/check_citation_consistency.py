import sys
import json
import re
import os
import urllib.parse

MAX_SEARCHES_PER_SCRIPT = 3

def load_patterns():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_path = os.path.join(script_dir, "..", "references", "date_patterns.json")
    
    default_founding = [r"\b(?:founded|established|started|launched|created)\s+(?:in\s+)?(20\d{2}|19\d{2})\b"]
    default_hq = [r"\b(?:headquartered|headquarters|based|located|hq)\s+in\s+([A-Za-z\s,\.]+?)(?=\.|\;|\,|$|\s+and)"]
    default_general_year = r"\b(20\d{2}|19\d{2})\b"

    try:
        if os.path.exists(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return (
                    data.get("founding_year_patterns", default_founding),
                    data.get("headquarters_patterns", default_hq),
                    data.get("general_year_pattern", default_general_year)
                )
    except Exception:
        pass
    return default_founding, default_hq, default_general_year

def extract_domain(url_str):
    if not url_str:
        return ""
    try:
        parsed = urllib.parse.urlparse(url_str)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""

def parse_fact_from_snippet(snippet, title, fact_type):
    founding_pats, hq_pats, general_year_pat = load_patterns()
    combined_text = f"{title or ''} {snippet or ''}".strip()
    if not combined_text:
        return None

    if fact_type == "founding_year":
        for pat in founding_pats:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                return m.group(1)
        m_gen = re.search(general_year_pat, combined_text)
        if m_gen:
            return m_gen.group(1)
    elif fact_type == "headquarters":
        for pat in hq_pats:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    else: # custom
        # Fallback year extraction or generic string match
        m_gen = re.search(general_year_pat, combined_text)
        if m_gen:
            return m_gen.group(1)

    return None

def check_citation_consistency(params):
    brand_name = params.get("brand_name", "")
    fact_type = params.get("fact_type", "custom")
    fact_value_on_site = params.get("fact_value_on_site", "")
    search_results = params.get("search_results", [])
    search_error = params.get("search_error")

    external_mentions = []
    distinct_domains = set()
    contains_contradiction = False

    if not isinstance(search_results, list):
        search_results = []

    # Enforce search result limit
    for item in search_results[:10]:
        if not isinstance(item, dict): continue
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        domain = extract_domain(url) or item.get("domain", "")

        extracted_val = parse_fact_from_snippet(snippet, title, fact_type)
        if extracted_val:
            excerpt = (snippet[:150] + "...") if len(snippet) > 150 else snippet
            external_mentions.append({
                "source_domain": domain,
                "snippet_excerpt": excerpt,
                "extracted_value": extracted_val
            })
            if domain:
                distinct_domains.add(domain)

            # Check for contradiction
            norm_on_site = re.sub(r'[^\w\s]', '', str(fact_value_on_site).lower().strip())
            norm_ext = re.sub(r'[^\w\s]', '', str(extracted_val).lower().strip())
            
            if norm_on_site and norm_ext and norm_on_site != norm_ext and norm_ext not in norm_on_site and norm_on_site not in norm_ext:
                contains_contradiction = True

    # Cap external mentions at 5
    external_mentions = external_mentions[:5]

    return {
        "brand_name": brand_name,
        "fact_type": fact_type,
        "fact_value_on_site": fact_value_on_site,
        "external_mentions_found": external_mentions,
        "corroboration_count": len(distinct_domains),
        "contains_contradiction": contains_contradiction,
        "search_error": search_error
    }

import threading

def read_stdin_safe(timeout=0.2):
    if sys.stdin.isatty():
        return ""
    res = []
    def target():
        try:
            res.append(sys.stdin.read())
        except Exception:
            pass
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return res[0] if res else ""

if __name__ == "__main__":
    try:
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params = {"brand_name": raw_arg}
            else:
                params = {"brand_name": raw_arg}

        input_data = read_stdin_safe(timeout=0.2)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        result = check_citation_consistency(params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "brand_name": None,
            "fact_type": None,
            "fact_value_on_site": None,
            "external_mentions_found": [],
            "corroboration_count": 0,
            "contains_contradiction": False,
            "search_error": str(e)
        }))
