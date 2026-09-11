
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import urllib.parse
from html.parser import HTMLParser

# Search-budget enforcement is the orchestrator's job (references/search_budget.md).

# Domains that indicate a *disambiguated* brand identity presence.
IDENTITY_PLATFORMS = (
    "linkedin.com", "crunchbase.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com", "github.com", "bloomberg.com",
    "wikipedia.org", "wikidata.org", "pitchbook.com", "glassdoor.com",
    "trustpilot.com", "g2.com", "capterra.com", "apps.apple.com",
    "play.google.com",
)


def _registrable(host):
    """Rough registrable domain (last two labels; last three for known 2-level TLDs)."""
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def assess_name_ambiguity(bare_name_results, target_domain_norm, brand_name):
    """Deterministic mistaken-identity signals from the bare brand-name search
    results (Round-2 appendix D). No verdict is forced -- the agent judges the
    result titles for genuinely distinct same-named entities."""
    items = bare_name_results if isinstance(bare_name_results, list) else []
    ranked_hosts = [host_of(extract_url_from_item(it)) for it in items[:10]]
    ranked_hosts = [h for h in ranked_hosts if h]

    target_reg = _registrable(target_domain_norm)
    target_rank = None
    for i, h in enumerate(ranked_hosts):
        if target_domain_norm and (is_same_or_subdomain(h, target_domain_norm)
                                   or _registrable(h) == target_reg):
            target_rank = i + 1
            break

    distinct_regs = sorted({_registrable(h) for h in ranked_hosts if _registrable(h)})
    identity_hits = sorted({p for h in ranked_hosts for p in IDENTITY_PLATFORMS
                            if host_is(h, p)})

    disambig_page = any(
        "disambiguation" in (extract_url_from_item(it).lower()
                             + " " + (it.get("title", "").lower()
                                      if isinstance(it, dict) else ""))
        for it in items
    )

    name_tokens = [t for t in re.split(r"\s+", (brand_name or "").strip()) if t]
    single_short_token = (len(name_tokens) == 1 and name_tokens[0].isalpha()
                          and len(name_tokens[0]) <= 8)

    signals = []
    if target_rank is None and ranked_hosts:
        signals.append("target domain absent from top bare-name results")
    elif target_rank and target_rank > 2:
        signals.append(f"target domain only ranks #{target_rank} for its own name")
    if disambig_page:
        signals.append("a Wikipedia disambiguation page appears for the bare name")
    if len(distinct_regs) >= 7 and len(identity_hits) <= 1:
        signals.append(f"{len(distinct_regs)} unrelated domains in the top results with "
                       f"almost no identity-platform presence")
    if single_short_token:
        signals.append(f"brand name is a single short word ('{name_tokens[0]}') -- "
                       f"higher collision risk (low-confidence signal)")

    if target_rank == 1 or (target_rank and target_rank <= 2 and len(identity_hits) >= 2):
        risk = "low"
    elif len(signals) >= 2 or disambig_page:
        risk = "elevated"
    elif signals:
        risk = "moderate"
    else:
        risk = "low"

    return {
        "target_domain_rank": target_rank,
        "distinct_registrable_domains": distinct_regs,
        "identity_platform_coverage": identity_hits,
        "wikipedia_disambiguation_detected": disambig_page,
        "brand_name_is_single_short_token": single_short_token,
        "ambiguity_signals": signals,
        "ambiguity_risk": risk,
        "needs_agent_disambiguation_judgment": risk != "low",
    }


def host_of(url_str):
    if not url_str or not isinstance(url_str, str):
        return ""
    s = url_str.strip()
    if "://" not in s:
        s = "https://" + s
    try:
        h = urllib.parse.urlparse(s).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def host_is(host, target):
    """True when host == target or is a real subdomain of target (not a
    substring trick like 'fakewikipedia.org.spam.net')."""
    host = (host or "").lower()
    return host == target or host.endswith("." + target)


def any_result_on_host(results, target):
    for item in results if isinstance(results, list) else []:
        if host_is(host_of(extract_url_from_item(item)), target):
            return True
    return False


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

# Non-entity JSON-LD types that may carry a `sameAs`-like key we do NOT want
# (kept minimal; almost nothing but real entities uses sameAs).
_NON_ENTITY_TYPES = {"breadcrumblist", "itemlist", "webpage", "webpagelement",
                     "siteNavigationElement".lower(), "collectionpage"}


# Public identity registries: places that hold a *record* of an entity with a
# canonical, machine-resolvable URL, as opposed to a self-published social
# profile. A sameAs link to one of these anchors the brand in a database AI
# systems already resolve against, which is the job a Wikidata link does. Many
# real brands -- an open-source project, a B2B supplier, a local firm -- will
# never meet encyclopedia notability, so "no Wikipedia link" is not a defect
# when a registry record is linked instead.
#
# Social profiles (LinkedIn, X, Facebook, Instagram, YouTube) are deliberately
# NOT here: they are self-asserted pages, not registry records, and the audit
# already treats them as ordinary sameAs links.
AUTHORITY_REGISTRY_HOSTS = {
    # encyclopedic / knowledge graph
    "wikipedia.org": "encyclopedia",
    "wikidata.org": "knowledge_graph",
    "dbpedia.org": "knowledge_graph",
    # source code and package registries
    "github.com": "code_registry",
    "gitlab.com": "code_registry",
    "codeberg.org": "code_registry",
    "sourceforge.net": "code_registry",
    "npmjs.com": "package_registry",
    "pypi.org": "package_registry",
    "crates.io": "package_registry",
    "pkg.go.dev": "package_registry",
    "rubygems.org": "package_registry",
    "packagist.org": "package_registry",
    "nuget.org": "package_registry",
    "mvnrepository.com": "package_registry",
    "hub.docker.com": "package_registry",
    "huggingface.co": "model_registry",
    # app stores (a listing is a reviewed, canonical record)
    "apps.apple.com": "app_store",
    "play.google.com": "app_store",
    # company and organization registers
    "opencorporates.com": "company_register",
    "crunchbase.com": "company_register",
    # persistent identifier authorities
    "orcid.org": "persistent_id",
    "isni.org": "persistent_id",
    "ror.org": "persistent_id",
    "viaf.org": "persistent_id",
}


def classify_authority_sameas(links):
    """Split sameAs links into registry-grade identity anchors and the rest.

    Host matching goes through host_is(), so 'dropbox.com' is never mistaken
    for a match on 'x.com' and 'notgithub.com.evil.net' never matches
    'github.com'.
    """
    registry_links = []
    for url_str in links or []:
        host = host_of(url_str)
        if not host:
            continue
        for target, kind in AUTHORITY_REGISTRY_HOSTS.items():
            if host_is(host, target):
                registry_links.append({"url": url_str, "host": target, "kind": kind})
                break
    return {
        "registry_links": registry_links[:10],
        "registry_hosts": sorted({r["host"] for r in registry_links}),
        "registry_kinds": sorted({r["kind"] for r in registry_links}),
        "has_registry_sameas": bool(registry_links),
    }


def extract_same_as_links(html_content):
    """Harvest `sameAs` from ANY plausible entity node in the JSON-LD graph --
    Organization and all its subtypes, every LocalBusiness subtype (Dentist,
    LawFirm, Restaurant, ...), Person (personal brands), NGO, WebSite, etc.
    The old whitelist ({organization, corporation, brand, localbusiness, store,
    restaurant}) silently dropped sameAs for most real business types."""
    same_as_links = []
    same_as_on_org_typed_node = False
    if not html_content:
        return same_as_links, same_as_on_org_typed_node

    def add(v):
        nonlocal same_as_links
        if isinstance(v, str) and v.strip():
            same_as_links.append(v.strip())
        elif isinstance(v, list):
            for u in v:
                if isinstance(u, str) and u.strip():
                    same_as_links.append(u.strip())
        elif isinstance(v, dict) and isinstance(v.get("@id"), str):
            same_as_links.append(v["@id"].strip())

    def walk(obj):
        nonlocal same_as_on_org_typed_node
        if isinstance(obj, dict):
            raw_type = obj.get("@type", "")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            types_lower = [str(t).lower().rsplit("/", 1)[-1] for t in types if t]
            if "sameAs" in obj and not any(t in _NON_ENTITY_TYPES for t in types_lower):
                add(obj.get("sameAs"))
                if any("organization" in t or "localbusiness" in t or t in
                       ("person", "brand", "corporation", "ngo", "store")
                       for t in types_lower):
                    same_as_on_org_typed_node = True
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for block_str in extract_json_ld_blocks(html_content):
        try:
            walk(json.loads(block_str))
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

    return deduped, same_as_on_org_typed_node

def extract_url_from_item(item):
    """Fix Secondary 4: Fallback across url, link, href for search result item key flexibility."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("url") or item.get("link") or item.get("href") or ""
    return ""

_DISAMBIG_RX = re.compile(r"disambiguation|may (?:also )?refer to", re.I)
_TITLE_SUFFIX_RX = re.compile(r"\s*[-–—|:]\s*(?:wikipedia|wikidata)\b.*$", re.I)
_PAREN_QUALIFIER_RX = re.compile(r"\s*\([^)]*\)\s*$")
# A MediaWiki namespace page ("Category:Foo", "Talk:Foo", "Kategorie:Foo") has
# no space after the colon; an article title with a colon ("Halo: Reach") does.
_NAMESPACE_SLUG_RX = re.compile(r"^[^_:/]+:[^_]")


def _norm_tokens(s):
    return [t for t in re.split(r"[^0-9a-z]+", (s or "").lower()) if t]


def best_entity_match(results, host, brand_name, domain):
    """Pick the result on `host` that is most plausibly THIS brand's article.

    Returns (match_or_None, candidates). Every on-host result becomes a
    candidate with its score and reason; disambiguation / namespace pages score
    0. Scores: the site's domain in the title or slug (3) > title equals the
    brand name once qualifiers are stripped (2) > title contains every brand
    token (1). Ties keep search rank. The agent still verifies the snippet --
    a score is a text match, not an identity proof.
    """
    brand_tokens = _norm_tokens(brand_name)
    dom = extract_domain(domain)
    dom_tokens = _norm_tokens(dom)
    candidates, seen = [], set()
    for rank, it in enumerate(results if isinstance(results, list) else []):
        url = extract_url_from_item(it)
        if not url or url in seen or not host_is(host_of(url), host):
            continue
        seen.add(url)
        title = it.get("title", "") if isinstance(it, dict) else ""
        snippet = it.get("snippet", "") if isinstance(it, dict) else ""
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path or "")
        slug = path.rsplit("/", 1)[-1]
        clean_title = _TITLE_SUFFIX_RX.sub("", title).strip()
        # Wikidata item URLs are opaque (Q-ids); only Wikipedia slugs name the page.
        name_text = clean_title or ("" if host == "wikidata.org" else slug.replace("_", " "))

        score, reason = 0, "no brand-name match in title"
        if _DISAMBIG_RX.search(slug) or _DISAMBIG_RX.search(title) or _DISAMBIG_RX.search(snippet[:160]):
            reason = "disambiguation page"
        elif host == "wikipedia.org" and _NAMESPACE_SLUG_RX.match(slug):
            reason = "non-article namespace page"
        else:
            title_tokens = _norm_tokens(name_text)
            slug_tokens = _norm_tokens(slug) if host == "wikipedia.org" else []
            core_tokens = _norm_tokens(_PAREN_QUALIFIER_RX.sub("", name_text))

            def has_seq(hay, needle):
                n = len(needle)
                return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))

            if len(dom_tokens) >= 2 and (has_seq(title_tokens, dom_tokens) or has_seq(slug_tokens, dom_tokens)):
                score, reason = 3, f"site domain '{dom}' appears in the page title"
            elif brand_tokens and core_tokens == brand_tokens:
                score, reason = 2, "title equals the brand name"
            elif brand_tokens and all(t in title_tokens for t in brand_tokens):
                score, reason = 1, "title contains every brand-name token"
        candidates.append({"url": url, "title": title, "snippet": snippet[:300],
                           "match_score": score, "match_reason": reason, "_rank": rank})

    ranked = sorted((c for c in candidates if c["match_score"] > 0),
                    key=lambda c: (-c["match_score"], c["_rank"]))
    for c in candidates:
        c.pop("_rank", None)
    return (ranked[0] if ranked else None), candidates[:6]


def check_entity_disambiguation(params):
    brand_name = params.get("brand_name", "")
    domain = params.get("domain", "")
    html_content = params.get("html", "")
    bare_name_results = params.get("bare_name_results", [])
    wikipedia_results = params.get("wikipedia_results", [])
    wikidata_results = params.get("wikidata_results", [])

    # `same_as_links_found: false` on empty html is indistinguishable from a
    # genuinely checked page with no sameAs links -- e.g. when the target site
    # could not be fetched at all (blocked, timed out) and the caller has no
    # html to pass. `html_provided` lets the orchestrator tell "checked, found
    # none" apart from "never checked" so it doesn't report an unreachable
    # site as if it had confirmed-absent sameAs links.
    html_provided = isinstance(html_content, str) and bool(html_content.strip())

    # 1. On-site JSON-LD sameAs extraction (any entity type)
    same_as_links, on_org_node = extract_same_as_links(html_content)
    has_wiki_sameas = any(host_is(host_of(u), "wikipedia.org") or host_is(host_of(u), "wikidata.org")
                          for u in same_as_links)

    # 2. Bare-name search evaluation. Distinguish "no domain supplied" (can't
    #    run the check) from "domain supplied but absent from results".
    target_domain_norm = extract_domain(domain)
    domain_provided = bool(target_domain_norm)
    search_domains = []
    target_in_top_results = None if not domain_provided else False

    if isinstance(bare_name_results, list):
        for item in bare_name_results[:10]:
            d = extract_domain(extract_url_from_item(item))
            if d:
                search_domains.append(d)
                if domain_provided and is_same_or_subdomain(d, target_domain_norm):
                    target_in_top_results = True

    # 3. Wikipedia / Wikidata presence -- host-checked, not substring.
    #
    # A wikipedia.org URL in the results is NOT proof the brand has an article:
    # a query for "monday.com wikipedia" returns "Monday (disambiguation)" and
    # the article on the weekday before "Monday.com". So presence requires a
    # result that is not a disambiguation page and whose title carries every
    # token of the brand name (a matching domain slug ranks highest). When
    # results exist but none match -- e.g. the brand trades under a different
    # name than its article -- presence is None (undetermined) and the
    # candidates go to the agent, rather than asserting a false "not found".
    # Every supplied result set is searched for both hosts: a "[brand] wikipedia"
    # query routinely surfaces the Wikidata item too, and that must count.
    def as_list(x):
        return x if isinstance(x, list) else []

    pooled = as_list(bare_name_results) + as_list(wikipedia_results) + as_list(wikidata_results)
    wiki_match, wiki_cands = best_entity_match(pooled, "wikipedia.org", brand_name, domain)
    data_match, data_cands = best_entity_match(pooled, "wikidata.org", brand_name, domain)

    def presence(match, cands):
        if match:
            free = any(extract_url_from_item(r) == match["url"] for r in as_list(bare_name_results))
            return True, ("bare_name_results" if free else "dedicated_query")
        if cands:
            return None, "results_found_but_none_match_brand"
        return False, "not_found"

    wikipedia_page_found, wikipedia_presence_source = presence(wiki_match, wiki_cands)
    wikidata_entry_found, wikidata_presence_source = presence(data_match, data_cands)

    # 4. Name-ambiguity / mistaken-identity signals (Round-2 appendix D)
    ambiguity = assess_name_ambiguity(bare_name_results, target_domain_norm, brand_name)

    # Budget backstop: estimate searches consumed from the result-sets supplied.
    consumed = sum(1 for k in ("bare_name_results", "wikipedia_results", "wikidata_results")
                   if params.get(k))
    rem = params.get("search_budget_remaining")
    rem = rem if isinstance(rem, int) else None
    search_budget = {
        "remaining_before": rem,
        "searches_consumed_estimate": consumed,
        "remaining_after": (rem - consumed) if rem is not None else None,
        "over_budget": rem is not None and rem < consumed,
        "note": ("bare-name search is the anchor query -- it also feeds name_ambiguity "
                 "and target_domain_rank; run the dedicated wikipedia query only if the "
                 "bare-name results did not already surface a wikipedia.org page, and the "
                 "wikidata query only if wikipedia found nothing."),
    }

    return {
        "brand_name": brand_name,
        "domain": domain,
        "domain_provided": domain_provided,
        "html_provided": html_provided,
        "same_as_links": same_as_links,
        "same_as_links_found": len(same_as_links) > 0,
        "same_as_on_organization_typed_node": on_org_node,
        "has_wikidata_or_wikipedia_sameas": has_wiki_sameas,
        "authority_sameas": classify_authority_sameas(same_as_links),
        "bare_name_search": {
            "search_result_domains": search_domains,
            "target_domain_in_top_results": target_in_top_results
        },
        "wikipedia_page_found": wikipedia_page_found,
        "wikidata_entry_found": wikidata_entry_found,
        "wikipedia_presence_source": wikipedia_presence_source,
        "wikidata_presence_source": wikidata_presence_source,
        # Raw indicators: any result on the host at all, matching or not.
        "wikipedia_any_result": bool(wiki_cands),
        "wikidata_any_result": bool(data_cands),
        "search_budget": search_budget,
        "name_ambiguity": ambiguity,
        # The best brand-matching result (never a disambiguation page) plus all
        # scored candidates, so the agent can confirm the page describes THIS
        # brand (industry / founding / location) rather than a same-named
        # entity -- or pick a candidate the text match scored 0 (a brand whose
        # article uses its legal name, say) and override presence.
        "entity_match_evidence": {
            "wikipedia_result": wiki_match,
            "wikidata_result": data_match,
            "wikipedia_candidates": wiki_cands,
            "wikidata_candidates": data_cands,
            "needs_entity_match_verification": bool(wiki_cands or data_cands),
        },
        "entity_match_caveat": ("A Wikipedia/Wikidata result for the bare brand "
                                "name may describe a different same-named entity; "
                                "confirm the result actually refers to this brand "
                                "before treating it as authoritative."),
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
                    params = {"domain": raw_arg}
            else:
                params = {"domain": raw_arg}

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        result = check_entity_disambiguation(params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "brand_name": None,
            "domain": None,
            "domain_provided": False,
            "html_provided": False,
            "same_as_links": [],
            "same_as_links_found": False,
            "same_as_on_organization_typed_node": False,
            "has_wikidata_or_wikipedia_sameas": False,
            "authority_sameas": classify_authority_sameas([]),
            "bare_name_search": {
                "search_result_domains": [],
                "target_domain_in_top_results": None
            },
            # None, not False: a crash is "undetermined", never "no article".
            "wikipedia_page_found": None,
            "wikidata_entry_found": None,
            "name_ambiguity": {"ambiguity_risk": "low", "ambiguity_signals": [],
                               "needs_agent_disambiguation_judgment": False},
            "entity_match_evidence": {"wikipedia_result": None, "wikidata_result": None,
                                      "wikipedia_candidates": [], "wikidata_candidates": [],
                                      "needs_entity_match_verification": False},
            "script_error": str(e)
        }))
