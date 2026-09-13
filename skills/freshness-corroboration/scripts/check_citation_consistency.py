
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import os
import urllib.parse

# Search-budget enforcement is the orchestrator's job (see references/search_budget.md).

def load_patterns():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_path = os.path.join(script_dir, "..", "references", "date_patterns.json")
    
    # "in the year (of)? 2022" is as common a phrasing as bare "in 2022" (e.g.
    # "Established in the year 2022" -- a real snippet, not a one-off) --
    # without it the year sits right after "the year"/"of", which the
    # original pattern's `(?:in\s+)?` did not reach, so it silently fell back
    # to a "weak" (unlabelled) match instead of "labelled". No other filler
    # phrasing is chased here on purpose: this pattern is deliberately
    # narrow and anchored (year immediately follows the verb, optional short
    # qualifier) so a "weak" match never drives a contradiction -- see the
    # docstring on parse_fact_from_snippet.
    default_founding = [r"\b(?:founded|established|started|launched|created)\s+(?:in\s+)?"
                        r"(?:the\s+year\s+(?:of\s+)?)?(20\d{2}|19\d{2})\b"]
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
    """Returns (value, match_strength). match_strength is 'labelled' when a
    fact-specific pattern matched (e.g. 'founded in 2018'), 'weak' when only a
    bare year was found, or None. A 'weak' value must NEVER drive a
    deterministic contradiction -- any year in a snippet ('raised $50M in
    2023') would otherwise be read as a conflicting founding year."""
    founding_pats, hq_pats, general_year_pat = load_patterns()
    combined_text = f"{title or ''} {snippet or ''}".strip()
    if not combined_text:
        return None, None

    if fact_type == "founding_year":
        for pat in founding_pats:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                return m.group(1), "labelled"
        m_gen = re.search(general_year_pat, combined_text)
        if m_gen:
            return m_gen.group(1), "weak"
    elif fact_type == "headquarters":
        for pat in hq_pats:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                return m.group(1).strip(), "labelled"
    else:  # custom
        m_gen = re.search(general_year_pat, combined_text)
        if m_gen:
            return m_gen.group(1), "weak"

    return None, None

def build_budget_block(params, searches_consumed):
    rem = params.get("search_budget_remaining")
    rem = rem if isinstance(rem, int) else None
    return {
        "remaining_before": rem,
        "searches_consumed_estimate": searches_consumed,
        "remaining_after": (rem - searches_consumed) if rem is not None else None,
        "over_budget": rem is not None and rem < searches_consumed,
    }


def check_citation_consistency(params):
    brand_name = params.get("brand_name", "")
    fact_type = params.get("fact_type", "custom")
    fact_value_on_site = params.get("fact_value_on_site", "")
    search_results = params.get("search_results", [])
    search_error = params.get("search_error")
    budget = build_budget_block(params, 1 if search_results else 0)

    # Do not corroborate a fact the site does not actually state.
    if not str(fact_value_on_site).strip():
        return {
            "brand_name": brand_name, "fact_type": fact_type,
            "fact_value_on_site": fact_value_on_site,
            "external_mentions_found": [], "weak_year_mentions": [],
            "corroboration_count": 0, "corroborating_domains": [], "conflicting_domains": [],
            "contains_contradiction": False, "contradiction_confidence": None,
            "needs_agent_judgment": False,
            "skipped_reason": "no on-site value supplied -- nothing to corroborate; do not spend a search",
            "search_budget": build_budget_block(params, 0),
            "search_error": search_error,
        }

    external_mentions = []
    weak_year_mentions = []
    corroborating_domains = set()
    conflicting_domains = set()

    if not isinstance(search_results, list):
        search_results = []

    norm_on_site = re.sub(r"[^\w\s]", "", str(fact_value_on_site).lower().strip())

    # Free-text positioning facts ("what the brand does") have no extractable
    # scalar value -- pass every snippet straight to the agent, which judges
    # whether the external framing broadly agrees with the on-site one-liner.
    is_positioning = fact_type in ("description", "positioning", "what_they_do", "tagline")
    if is_positioning:
        mentions = []
        for item in search_results[:10]:
            if not isinstance(item, dict):
                continue
            snip = item.get("snippet", "")
            mentions.append({
                "source_domain": extract_domain(item.get("url", "")) or item.get("domain", ""),
                "snippet_excerpt": (snip[:240] + "...") if len(snip) > 240 else snip,
                "title": item.get("title", ""),
            })
        return {
            "brand_name": brand_name,
            "fact_type": fact_type,
            "fact_value_on_site": fact_value_on_site,
            "external_mentions_found": mentions[:6],
            "weak_year_mentions": [],
            "corroboration_count": 0,
            "corroborating_domains": [],
            "conflicting_domains": [],
            "contains_contradiction": False,
            "contradiction_confidence": None,
            "needs_agent_judgment": bool(mentions),
            "agent_judgment_task": ("Compare the on-site one-line description against "
                                    "these external snippets. Flag a finding only if "
                                    "the external framing of what this brand does "
                                    "materially disagrees with the on-site positioning "
                                    "(different industry / audience / product), not for "
                                    "wording differences."),
            "search_budget": budget,
            "search_error": search_error,
        }

    for item in search_results[:10]:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        domain = extract_domain(url) or item.get("domain", "")
        excerpt = (snippet[:200] + "...") if len(snippet) > 200 else snippet

        val, strength = parse_fact_from_snippet(snippet, title, fact_type)
        if not val:
            continue

        record = {"source_domain": domain, "snippet_excerpt": excerpt,
                  "extracted_value": val, "match_strength": strength}

        if strength == "weak":
            weak_year_mentions.append(record)
            continue

        external_mentions.append(record)
        norm_ext = re.sub(r"[^\w\s]", "", str(val).lower().strip())
        if norm_on_site and norm_ext:
            agree = (norm_on_site == norm_ext
                     or norm_ext in norm_on_site or norm_on_site in norm_ext)
            if agree and domain:
                corroborating_domains.add(domain)
            elif not agree and domain:
                conflicting_domains.add(domain)

    # Deterministic contradiction is ONLY asserted for founding_year on a
    # labelled (exact 4-digit) mismatch. headquarters / custom facts are left
    # to agent judgement -- place-name aliases and free-form values can't be
    # adjudicated by string comparison.
    deterministic_ok = fact_type == "founding_year"
    contains_contradiction = bool(conflicting_domains) if deterministic_ok else False
    needs_agent_judgment = (not deterministic_ok) and bool(external_mentions or weak_year_mentions)

    return {
        "brand_name": brand_name,
        "fact_type": fact_type,
        "fact_value_on_site": fact_value_on_site,
        "external_mentions_found": external_mentions[:5],
        "weak_year_mentions": weak_year_mentions[:5],
        "corroboration_count": len(corroborating_domains),
        "corroborating_domains": sorted(corroborating_domains),
        "conflicting_domains": sorted(conflicting_domains),
        "contains_contradiction": contains_contradiction,
        "contradiction_confidence": "high" if (contains_contradiction and deterministic_ok) else None,
        "needs_agent_judgment": needs_agent_judgment,
        "search_budget": budget,
        "search_error": search_error
    }

import threading

def read_stdin_safe(timeout=5.0):
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
    return res[0].lstrip("\ufeff") if res else ""

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

        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
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
            "weak_year_mentions": [],
            "corroboration_count": 0,
            "corroborating_domains": [],
            "conflicting_domains": [],
            "contains_contradiction": False,
            "contradiction_confidence": None,
            "needs_agent_judgment": False,
            "search_budget": {"remaining_before": None, "searches_consumed_estimate": 0,
                              "remaining_after": None, "over_budget": False},
            "search_error": str(e)
        }))
