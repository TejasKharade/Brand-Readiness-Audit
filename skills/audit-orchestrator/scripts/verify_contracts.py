
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import os
import re
import glob
import json

# ---------------------------------------------------------------------------
# verify_contracts.py -- marketplace self-check (development / CI, not an audit step)
#
# The orchestrator reads sub-skill output by key name. If a sub-skill renames or
# stops emitting a field, the matching finding silently stops firing and the
# report looks clean. This script fails loudly on that class of drift by
# cross-checking every key `synthesize_report.py` reads against the keys the
# sub-skill scripts actually emit.
#
#   python skills/audit-orchestrator/scripts/verify_contracts.py
#   -> exit 0 = contracts aligned, exit 1 = drift detected
# ---------------------------------------------------------------------------

# Container keys the orchestrator itself creates when nesting sub-skill output,
# plus fields an agent injects (never emitted by a script).
NESTING_KEYS = {
    "crawl_access", "crawl_render", "readability", "freshness_corroboration", "engagement",
    "robots", "dual_identity", "page_signals", "sitemap", "crawl_depth", "sampled_pages", "tls",
    "rendering_barriers", "structured_data_hydration", "client_side_redirects",
    "structured_data", "semantic_structure", "content_consistency", "context_consistency",
    "nontext_facts", "nontext_content", "citation_consistency", "entity_disambiguation",
    "content_dates", "temporal_decay", "navigation_reachability", "content_depth",
    "mobile_responsiveness", "descriptor_consistency", "page_speed_signals",
    "landing_readiness",
}
AGENT_INJECTED_KEYS = {
    "agent_verdict", "ambiguous", "orientation_ok", "has_next_step", "inconsistent", "notes",
    # `readability.additional_pages` is assembled by the agent from
    # check_structured_data.py results it already has for interior pages; no
    # script emits the key itself, so it is a channel, not contract drift.
    "additional_pages",
}


def script_emitted_keys(root):
    keys = set()
    per_file = {}
    for f in sorted(glob.glob(os.path.join(root, "skills", "*", "scripts", "*.py"))):
        base = os.path.basename(f)
        if base in ("synthesize_report.py", "verify_contracts.py"):
            continue
        src = open(f, encoding="utf-8").read()
        found = set(re.findall(r'["\']([a-z_][a-z_0-9]*)["\']\s*:', src))          # dict literals
        found |= set(re.findall(r'\[["\']([a-z_][a-z_0-9]*)["\']\]\s*=', src))     # d["k"] = v
        found |= set(re.findall(r'\bself\.([a-z_][a-z_0-9]*)\b', src))             # parser attrs
        per_file[base] = found
        keys |= found
    return keys, per_file


def orchestrator_read_keys(root):
    src = open(os.path.join(root, "skills", "audit-orchestrator", "scripts",
                            "synthesize_report.py"), encoding="utf-8").read()
    start = src.index("def synthesize_report")
    end = src.index("# Calculate Category Scores")
    region = src[start:end]
    keys = set(re.findall(r'\.get\(["\']([a-z_0-9]+)["\']', region))
    keys |= set(re.findall(r'pick\([^,]+,\s*((?:["\'][a-z_0-9]+["\']\s*,?\s*)+)', region))
    flat = set()
    for k in keys:
        flat |= set(re.findall(r'["\']([a-z_0-9]+)["\']', k)) or {k}
    return {k for k in flat if re.fullmatch(r'[a-z_][a-z_0-9]*', k)}


def shape_probes(root):
    """Key names can all exist while their SHAPE differs (a {path: {agent: bool}}
    map read as {agent: [paths]}), which the name scan cannot see. These offline
    probes pipe real script output into synthesize_report and assert the finding
    that must fire does fire (and the one that must not, does not). No network."""
    for sub in ("audit-orchestrator", "crawl-access-audit", "freshness-corroboration",
                "readability-audit", "crawl-render-audit", "engagement-audit"):
        sys.path.insert(0, os.path.join(root, "skills", sub, "scripts"))
    from synthesize_report import synthesize_report
    from check_robots import check_robots
    from check_entity_disambiguation import check_entity_disambiguation, classify_authority_sameas
    from check_structured_data import check_structured_data
    from check_rendering_barriers import check_rendering_barriers
    from check_semantic_structure import check_semantic_structure
    from check_landing_readiness import check_landing_readiness
    from robots_gate import RobotsGate, robots_token
    import fetch_dual_identity

    bots = ["GPTBot", "ClaudeBot", "*"]
    failures = []

    def titles(skill_outputs):
        rep = synthesize_report("https://probe.example/", skill_outputs)
        return [f["title"] for f in rep.get("findings", [])]

    def probe(name, ok):
        if not ok:
            failures.append(name)

    site_block = check_robots("probe.example", bots, ["/docs/a"],
                              robots_txt="User-agent: GPTBot\nDisallow: /\n")
    probe("robots: site-wide block -> root finding",
          any("Site Root" in t for t in titles({"crawl_access": {"robots": site_block}})))

    page_block = check_robots("probe.example", bots, ["/lp/offer"],
                              robots_txt="User-agent: *\nAllow: /\nDisallow: /lp/\n")
    probe("robots: longest-match page block -> key-page finding",
          any("Key Pages Disallowed" in t for t in titles({"crawl_access": {"robots": page_block}})))

    query_only = check_robots("probe.example", bots, ["https://probe.example/p?utm=1"],
                              robots_txt="User-agent: *\nDisallow: /*?*\n")
    probe("robots: query-string-only block -> no finding",
          not any("robots.txt" in t for t in titles({"crawl_access": {"robots": query_only}})))

    ent = check_entity_disambiguation({
        "brand_name": "Probe", "domain": "probe.example", "bare_name_results": [],
        "wikipedia_results": [{"url": "https://en.wikipedia.org/wiki/Probe_(disambiguation)",
                               "title": "Probe (disambiguation)"}]})
    probe("entity: disambiguation-only results -> presence undetermined, no 'not found' finding",
          ent["wikipedia_page_found"] is None and not any(
              "Wikipedia" in t for t in titles({"freshness_corroboration": {"entity_disambiguation": ent}})))

    unreachable_ent = check_entity_disambiguation({"brand_name": "Probe", "domain": "probe.example", "html": ""})
    probe("entity: html never fetched -> no false 'Missing sameAs' finding",
          unreachable_ent.get("html_provided") is False and not any(
              "sameAs" in t for t in titles({"freshness_corroboration": {"entity_disambiguation": unreachable_ent}})))
    checked_ent = check_entity_disambiguation({
        "brand_name": "Probe", "domain": "probe.example",
        "html": "<html><head><title>Probe</title></head><body>hi</body></html>"})
    probe("entity: html actually checked, no sameAs -> finding still fires",
          checked_ent.get("html_provided") is True and any(
              "sameAs" in t for t in titles({"freshness_corroboration": {"entity_disambiguation": checked_ent}})))

    blocked_dual = {"dual_identity": {"browser_status": 403, "bot_status": 403, "bot_blocked": True,
                                      "comparison_metrics": {"fingerprint_divergence": True}}}
    probe("dual-identity: browser also blocked -> evidence must not claim it 'succeeded'",
          not any("succeeded" in f["evidence"] for f in
                 synthesize_report("https://probe.example/", {"crawl_access": blocked_dual})["findings"]))

    ambiguous_verdict_ent = dict(unreachable_ent)
    ambiguous_verdict_ent["name_ambiguity"] = {
        "agent_verdict": {"ambiguous": True, "notes": "PROBE_MARKER_TEXT distinguishing this from the heuristic list"}}
    probe("ambiguity finding: injected agent_verdict.notes must reach the evidence text",
          any("PROBE_MARKER_TEXT" in f["evidence"] for f in synthesize_report(
              "https://probe.example/", {"freshness_corroboration": {"entity_disambiguation": ambiguous_verdict_ent}})["findings"]))

    # Entity grounding: a page whose only markup is its breadcrumb trail must be
    # reported, and an unrecognised Schema type must never be read as "describes
    # nothing" (negative case below).
    breadcrumb_html = ('<script type="application/ld+json">{"@context":"https://schema.org",'
                       '"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,'
                       '"name":"Home"}]}</script>')
    bc_sd = check_structured_data(breadcrumb_html, "https://probe.example/products/thing")
    probe("grounding: breadcrumb-only page -> navigation-only finding",
          bc_sd["entity_grounding"]["structural_only"] is True and any(
              "Not the Page's Subject" in t for t in titles({"readability": {"structured_data": bc_sd}})))

    unknown_sd = check_structured_data(
        '<script type="application/ld+json">{"@type":"VeterinaryCare","name":"Probe"}</script>'
        + breadcrumb_html, "https://probe.example/")
    probe("grounding: unrecognised Schema type -> no grounding finding at all",
          unknown_sd["entity_grounding"]["structural_only"] is False and not any(
              "Not the Page's Subject" in t or "Identity Entity" in t
              for t in titles({"readability": {"structured_data": unknown_sd}})))

    org_sd = check_structured_data(
        '<script type="application/ld+json">{"@type":"Organization","name":"Probe",'
        '"description":"Probe makes industrial widgets for factory buyers."}</script>',
        "https://probe.example/")
    probe("grounding: homepage with a described Organization -> identity recognised, silent",
          org_sd["entity_grounding"]["has_identity_entity"] is True
          and org_sd["entity_grounding"]["identity_entity_types"] == ["Organization"]
          and not any("Identity Entity" in t or "description" in t.lower()
                      for t in titles({"readability": {"structured_data": org_sd}})))

    probe("grounding: interior page passed via additional_pages is reported",
          any("Not the Page's Subject" in t for t in titles(
              {"readability": {"structured_data": org_sd,
                               "additional_pages": [{"url": "https://probe.example/p/1",
                                                     "structured_data": bc_sd}]}})))

    # Positive counterpart to the two negative grounding probes above: with the
    # classifier working, a homepage carrying only subject markup must raise the
    # identity finding (a probe that can only pass is worthless).
    subject_only_sd = check_structured_data(
        '<script type="application/ld+json">{"@type":"Product","name":"Probe Widget",'
        '"description":"A widget probe used for contract verification runs."}</script>',
        "https://probe.example/")
    probe("grounding: homepage with subject markup but no identity entity -> finding",
          any("Identity Entity" in t for t in titles({"readability": {"structured_data": subject_only_sd}})))

    short_desc_sd = check_structured_data(
        '<script type="application/ld+json">{"@type":"Organization","name":"Probe",'
        '"description":"We do stuff"}</script>', "https://probe.example/")
    probe("description: a label-length description is reported as too short",
          short_desc_sd["description_coverage"]["short_description_entities"] and any(
              "description" in t.lower() for t in titles({"readability": {"structured_data": short_desc_sd}})))

    # sameAs authority: a registry link suppresses the optional encyclopedia
    # nudge; a social-only profile set does not.
    def _ent_with(links):
        return {"brand_name": "Probe", "html_provided": True, "same_as_links": links,
                "same_as_links_found": bool(links), "has_wikidata_or_wikipedia_sameas": False,
                "authority_sameas": classify_authority_sameas(links),
                "wikipedia_page_found": False, "wikidata_entry_found": False}

    probe("sameAs: registry link (GitHub) -> optional encyclopedia nudge suppressed",
          not any("Authority Link" in t for t in titles(
              {"freshness_corroboration": {"entity_disambiguation": _ent_with(
                  ["https://github.com/probe/tool"])}})))

    probe("sameAs: social profiles only -> optional nudge still fires",
          any("Authority Link" in t for t in titles(
              {"freshness_corroboration": {"entity_disambiguation": _ent_with(
                  ["https://www.linkedin.com/company/probe"])}})))

    probe("sameAs: lookalike host must not count as a registry",
          classify_authority_sameas(["https://notgithub.com.evil.net/probe"])["has_registry_sameas"] is False)

    # Raw-vs-rendered parity / link discovery: present only when a rendered DOM
    # exists, and absent (not fabricated) when it does not.
    raw_shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    rendered = ('<html><body><main><p>Probe builds dependable industrial widgets for buyers.</p></main>'
                '<nav><a href="/a">a</a><a href="/b">b</a><a href="/c">c</a><a href="/d">d</a>'
                '<a href="/e">e</a></nav></body></html>')
    rb = check_rendering_barriers(raw_shell, rendered, "https://probe.example/")
    probe("parity: rendered-only sentences quoted in the CSR finding evidence",
          rb["content_parity"]["content_parity_pct"] == 0.0 and any(
              "dependable industrial widgets" in f["evidence"] for f in synthesize_report(
                  "https://probe.example/", {"crawl_render": {"rendering_barriers": rb}})["findings"]))

    probe("link discovery: 5 JS-only internal links -> finding",
          any("Only After JavaScript" in t for t in titles(
              {"crawl_render": {"rendering_barriers": rb}})))

    rb_raw_only = check_rendering_barriers(raw_shell, "", "https://probe.example/")
    probe("parity: no rendered DOM -> parity/link facts are null, not invented",
          rb_raw_only["content_parity"] is None and rb_raw_only["link_discovery"] is None)

    # Question-phrased headings, content positioning, and FAQ-schema-vs-text:
    # all three are pure presence/absence heuristics (see check_semantic_
    # structure.py and check_structured_data.py docstrings for why), so each
    # gets both a positive and a negative case -- a probe that can only pass
    # is worthless.
    unanswered_html = ("<html><body><main><h2>Do you ship internationally?</h2>"
                       "<h2>Returns</h2><p>30 day returns policy applies here.</p>"
                       "</main></body></html>")
    answered_html = ("<html><body><main><h2>Do you ship internationally?</h2>"
                     "<p>Yes.</p></main></body></html>")
    probe("question headings: no content before the next heading -> unanswered",
          check_semantic_structure(unanswered_html, "https://probe.example/"
                                   )["question_headings"]["unanswered_count"] == 1)
    probe("question headings: a one-word real answer counts as answered",
          check_semantic_structure(answered_html, "https://probe.example/"
                                   )["question_headings"]["unanswered_count"] == 0)

    real_para = ("Acme builds dependable industrial safety equipment for factory buyers across "
                "the manufacturing sector, shipping tracked orders worldwide with responsive "
                "customer support and a comprehensive multi-year warranty covering every product "
                "line we currently sell today across every region we operate in worldwide now. "
                "Every unit passes independent third-party certification before it leaves our "
                "factory floor, and our engineering team publishes detailed maintenance schedules "
                "so customers can plan service visits well in advance without unplanned downtime. "
                "A dedicated account manager coordinates delivery timing and answers questions "
                "about specifications, compliance documentation, and long-term parts availability.")
    front_loaded_html = f"<html><body><main><h1>Probe</h1><p>{real_para}</p></main></body></html>"
    buried_html = ("<html><body><main>" + "".join(f"<p>{' '.join(['tiny']*3)}</p>" for _ in range(40))
                  + f"<p>{' '.join(['content']*30)}</p></main></body></html>")
    probe("content positioning: real content right after H1 -> front_loaded True",
          check_semantic_structure(front_loaded_html, "https://probe.example/"
                                   )["content_positioning"].get("front_loaded") is True)
    probe("content positioning: substance buried after 120 words of filler -> front_loaded False",
          check_semantic_structure(buried_html, "https://probe.example/"
                                   )["content_positioning"].get("front_loaded") is False)

    faq_schema_html = ('<script type="application/ld+json">'
                       '{"@type":"FAQPage","mainEntity":[{"@type":"Question",'
                       '"name":"Do you offer international shipping?",'
                       '"acceptedAnswer":{"@type":"Answer","text":'
                       '"Yes, we ship to over fifty countries with tracked courier delivery."}}]}'
                       '</script>')
    faq_absent_page = (faq_schema_html +
                       "<p>Acme was founded in 2010 and focuses on premium industrial widgets "
                       "manufacturing for enterprise clients across many regions with a strong "
                       "emphasis on quality control and long-term reliability engineering.</p>"
                       "<p>Our leadership team publishes quarterly sustainability reports covering "
                       "energy usage, recycling programs, and community outreach at every site.</p>")
    faq_present_page = (faq_schema_html +
                        "<p>We deliver internationally to more than fifty countries using tracked "
                        "courier services every week, with reliable delivery times across all "
                        "regions we serve and dedicated customs support teams on standby always.</p>"
                        "<p>Our logistics partners coordinate customs clearance and provide "
                        "tracking updates throughout transit for every international shipment.</p>")
    probe("FAQ schema: fabricated/absent answer -> flagged as low overlap",
          check_structured_data(faq_absent_page, "https://probe.example/"
                                )["faq_visible_text_check"]["low_overlap_count"] == 1)
    probe("FAQ schema: paraphrased-but-present answer -> not flagged",
          check_structured_data(faq_present_page, "https://probe.example/"
                                )["faq_visible_text_check"]["low_overlap_count"] == 0)

    probe("orchestrator: unanswered question heading -> a real finding, quoting it",
          any("Question-Style Heading" in f["title"] and "ship internationally" in f["evidence"]
              for f in synthesize_report(
                  "https://probe.example/",
                  {"readability": {"semantic_structure": check_semantic_structure(
                      unanswered_html, "https://probe.example/")}})["findings"]))
    probe("orchestrator: FAQ mismatch -> a real finding",
          any("FAQ Schema" in f["title"] for f in synthesize_report(
              "https://probe.example/",
              {"readability": {"structured_data": check_structured_data(
                  faq_absent_page, "https://probe.example/")}})["findings"]))

    # E-E-A-T authorship, NAP consistency, and trust-page presence: three
    # pure presence/absence checks -- positive and negative case each.
    admin_author_html = ('<script type="application/ld+json">'
                         '{"@type":"Article","headline":"News",'
                         '"author":{"@type":"Person","name":"admin"}}</script>')
    real_author_html = ('<script type="application/ld+json">'
                        '{"@type":"Article","headline":"News",'
                        '"author":{"@type":"Person","name":"Jane Smith"}}</script>')
    probe("authorship: literal CMS placeholder ('admin') flagged as generic",
          check_structured_data(admin_author_html, "https://probe.example/"
                                )["entities"][0]["article_completeness"]["generic_placeholder_author"] is True)
    probe("authorship: a real named author is not flagged",
          check_structured_data(real_author_html, "https://probe.example/"
                                )["entities"][0]["article_completeness"]["generic_placeholder_author"] is False)
    probe("authorship: a legitimate organizational byline ('Staff Writer') is NOT flagged",
          check_structured_data(
              '<script type="application/ld+json">{"@type":"Article","headline":"News",'
              '"author":{"@type":"Person","name":"Staff Writer"}}</script>',
              "https://probe.example/")["entities"][0]["article_completeness"]
          ["generic_placeholder_author"] is False)

    local_biz_html = ('<script type="application/ld+json">{"@type":"LocalBusiness","name":"Probe Diner",'
                      '"telephone":"555-123-4567","address":{"streetAddress":"123 Main Street",'
                      '"addressLocality":"Springfield"}}</script>')
    nap_filler = ("Our restaurant has served the community for many years with fresh local "
                 "ingredients and a warm welcoming atmosphere for every visitor daily. Our chefs "
                 "prepare seasonal menus using produce sourced from nearby farms and trusted suppliers.")
    nap_match_page = local_biz_html + f"<p>Call (555) 123-4567. 123 Main Street, Springfield.</p><p>{nap_filler}</p>"
    nap_mismatch_page = local_biz_html + f"<p>Call (999) 000-0000. 999 Oak Avenue, Portland.</p><p>{nap_filler}</p>"
    probe("NAP: matching phone (reformatted) and address -> no mismatch",
          check_structured_data(nap_match_page, "https://probe.example/"
                                )["nap_consistency"]["mismatch_count"] == 0)
    probe("NAP: a genuinely different phone and address -> both flagged",
          check_structured_data(nap_mismatch_page, "https://probe.example/"
                                )["nap_consistency"]["mismatch_count"] == 2)

    trust_pages_html = ("<html><body><h1>Probe</h1><p>Probe builds dependable industrial widgets for "
                        "factory buyers across the manufacturing sector worldwide today.</p>"
                        "<footer><a href='/privacy-policy'>Privacy</a><a href='/terms'>Terms</a>"
                        "</footer></body></html>")
    no_trust_pages_html = ("<html><body><h1>Probe</h1><p>Probe builds dependable industrial widgets "
                           "for factory buyers across the manufacturing sector worldwide today.</p>"
                           "</body></html>")
    probe("trust pages: privacy+terms links detected",
          check_landing_readiness(trust_pages_html, "https://probe.example/"
                                  )["next_step"]["privacy_policy_present"] is True)
    probe("trust pages: absence reported as LOW severity only, never higher",
          not any(f["severity"] in ("medium", "high", "critical") and "Privacy Policy" in f["title"]
                  for f in synthesize_report(
                      "https://probe.example/",
                      {"engagement": {"landing_readiness": check_landing_readiness(
                          no_trust_pages_html, "https://probe.example/")}})["findings"])
          and any(f["severity"] == "low" and "Privacy Policy" in f["title"]
                  for f in synthesize_report(
                      "https://probe.example/",
                      {"engagement": {"landing_readiness": check_landing_readiness(
                          no_trust_pages_html, "https://probe.example/")}})["findings"]))

    # Compressed responses. A Content-Encoding: gzip body decoded as if it
    # were text turned a healthy page into a pile of false "page is empty"
    # findings, so the decoder is probed directly, both encodings and the
    # no-decoder disclosure path.
    import gzip as _gzip
    from fetch_dual_identity import decode_response_body as _decode
    _real = "<html><head><title>T</title></head><body><h1>H</h1><p>text</p></body></html>"
    probe("compression: gzip body is decompressed (via Content-Encoding header)",
          _decode(_gzip.compress(_real.encode()), {"Content-Encoding": "gzip"})[0] == _real)
    probe("compression: gzip body is decompressed from magic bytes with no header",
          _decode(_gzip.compress(_real.encode()), {})[0] == _real)
    probe("compression: an uncompressed body is passed through untouched",
          _decode(_real.encode(), {})[0] == _real)
    probe("compression: an undecodable body reports the reason instead of emitting garbage",
          _decode(bytes([0x1b, 0x3f, 0x00]) + b"garbage", {"Content-Encoding": "br"})
          == ("", "response is brotli-encoded and no brotli decoder is available; content not analysed"))

    # Schema completeness must reach the report (8 of the 9 types were computed
    # and silently dropped before).
    _prod = ('<script type="application/ld+json">{"@type":"Product","name":"G",'
             '"description":"A durable glove for factory use.","offers":{"@type":"Offer"}}</script>')
    probe("schema completeness: a Product with no price/availability is reported",
          any("Incomplete Product Schema" in t for t in titles(
              {"readability": {"structured_data": check_structured_data(_prod, "https://probe.example/p")}})))
    _prod_ok = ('<script type="application/ld+json">{"@type":"Product","name":"G",'
                '"description":"A durable glove for factory use.","offers":{"@type":"Offer",'
                '"price":"9.99","availability":"https://schema.org/InStock"}}</script>')
    probe("schema completeness: a COMPLETE Product is not flagged",
          not any("Incomplete Product Schema" in t for t in titles(
              {"readability": {"structured_data": check_structured_data(_prod_ok, "https://probe.example/p")}})))

    # A static, script-free page must never be told its <h1> is client-injected.
    _static_sem = check_semantic_structure(
        "<html><body><h2>A</h2><p>x</p><h3>B</h3><p>y</p></body></html>", "https://probe.example/")
    _no_csr = {"rendering_barriers": {"client_side_rendering_signals": {
        "likely_client_side_rendering_barrier": False, "spa_mount_points": [],
        "detected_frameworks": [], "inline_framework_signals": [],
        "data_islands_detected": [], "custom_web_elements_count": 0}}}
    probe("h1: render pass ruling out CSR -> 'Missing h1', never 'client-injected'",
          any("Missing primary <h1>" in t for t in titles(
              {"readability": {"semantic_structure": _static_sem}, "crawl_render": _no_csr}))
          and not any("client-injected" in t for t in titles(
              {"readability": {"semantic_structure": _static_sem}, "crawl_render": _no_csr})))

    # A "you need JavaScript" fallback notice is chrome, not the page's first
    # substantial content -- while <html class="no-js"> (Modernizr) must NOT
    # cause the whole document to be excluded.
    _nojs = ('<html class="no-js"><body><div id="nojs"><p>Notice: This page displays a fallback '
             'because interactive scripts did not run.</p></div><main><p>'
             + " ".join(["realcontent"] * 100) + '</p></main></body></html>')
    _cp = check_semantic_structure(_nojs, "https://probe.example/")["content_positioning"]
    probe("content position: a no-JS fallback notice is not the first substantial block",
          "fallback" not in (_cp.get("first_substantial_block_preview") or "")
          and _cp.get("total_main_words", 0) >= 100)

    probe("headings: multiple <h1> is reported (was computed but never read)",
          any("Multiple <h1>" in t for t in titles({"readability": {"semantic_structure":
              check_semantic_structure("<html><body><h1>A</h1><p>x</p><h1>B</h1><p>y</p></body></html>",
                                       "https://probe.example/")}})))

    # robots.txt compliance. The audit must never request a path the site
    # disallows for the identity it is presenting -- the dual-identity fetch
    # sends a GPTBot user-agent, so this is the one place where ignoring
    # robots.txt would mean impersonating a crawler that was told not to come.
    GPTBOT_UA = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
                 "GPTBot/1.2; +https://openai.com/gptbot)")
    BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    BOT_BLOCKED_ROBOTS = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"

    probe("robots gate: a full GPTBot UA string is matched against the GPTBot group",
          robots_token(GPTBOT_UA) == "gptbot" and robots_token(BROWSER_UA) == "*")

    _gate = RobotsGate(robots_txt=BOT_BLOCKED_ROBOTS, status=200)
    probe("robots gate: disallowed for GPTBot, allowed for the browser identity",
          _gate.allows("https://probe.example/", GPTBOT_UA).allowed is False
          and _gate.allows("https://probe.example/", BROWSER_UA).allowed is True)

    probe("robots gate: 404 allows everything, 5xx and unreachable fail closed",
          RobotsGate(robots_txt="", status=404).allows("https://probe.example/x", "GPTBot").allowed is True
          and RobotsGate(robots_txt="", status=503).allows("https://probe.example/x", "GPTBot").allowed is False
          and RobotsGate(robots_txt="", status=None).allows("https://probe.example/x", "GPTBot").allowed is False)

    # The decisive one: no request may leave the process for a disallowed URL.
    _attempted = []
    _real_fetch = fetch_dual_identity.fetch_url
    fetch_dual_identity.fetch_url = lambda url, ua, **kw: (
        _attempted.append(ua) or {"status": 200, "content": "<html></html>",
                                  "content_fingerprints": {}})
    try:
        _dual = fetch_dual_identity.dual_fetch(
            "https://probe.example/", BROWSER_UA, GPTBOT_UA, delay=0,
            robots={"robots_txt": BOT_BLOCKED_ROBOTS, "status": 200})
    finally:
        fetch_dual_identity.fetch_url = _real_fetch

    probe("robots gate: NO request is issued as GPTBot when robots.txt forbids it",
          not any("GPTBot" in ua for ua in _attempted) and len(_attempted) == 1)

    probe("robots gate: a skipped bot leg is not scored as a bot block",
          _dual["robots_skipped_bot_fetch"] is True and _dual["bot_blocked"] is False
          and not any("Blocks AI" in t or "Bot Blocked" in t
                      for t in titles({"crawl_access": {"dual_identity": _dual}})))

    probe("robots gate: the skipped leg itself carries the refusal reason",
          _dual["bot_fetch"].get("skipped_by_robots") is True
          and _dual["bot_fetch"].get("fetched") is False
          and (_dual["bot_fetch"].get("robots_decision") or {}).get("rule") == "Disallow: /")

    probe("robots gate: the report states which fetch was skipped and why",
          [e.get("rule") for e in synthesize_report(
              "https://probe.example/", {"crawl_access": {"dual_identity": _dual}}
          )["audit_metadata"]["robots_restricted_fetches"]] == ["Disallow: /"])

    _allowed_dual = dict(_dual, robots_skipped_bot_fetch=False, robots_skipped_browser_fetch=False,
                         robots_decisions={}, bot_fetch={"status": 200})
    probe("robots gate: an unrestricted audit reports full coverage",
          synthesize_report("https://probe.example/", {"crawl_access": {"dual_identity": _allowed_dual}}
                            )["audit_metadata"]["robots_compliance"]
          == "all fetches allowed by robots.txt")

    # Crawler classes: a training-only block must NOT be critical or trip the
    # gate, while blocking a live-search crawler still must.
    training_only = check_robots("probe.example", ["GPTBot", "CCBot", "OAI-SearchBot", "*"], ["/"],
                                 robots_txt="User-agent: GPTBot\nDisallow: /\n\nUser-agent: CCBot\nDisallow: /\n")
    rep = synthesize_report("https://probe.example/", {"crawl_access": {"robots": training_only}})
    probe("robots: training-only root block -> no critical finding, crawl_access barely dented",
          not any(f["severity"] == "critical" for f in rep["findings"])
          and rep["category_scores"]["crawl_access"] > 90)
    search_block = check_robots("probe.example", ["GPTBot", "OAI-SearchBot", "*"], ["/"],
                                robots_txt="User-agent: OAI-SearchBot\nDisallow: /\n")
    probe("robots: live-search crawler root block -> critical",
          any(f["severity"] == "critical" for f in synthesize_report(
              "https://probe.example/", {"crawl_access": {"robots": search_block}})["findings"]))

    # Unparseable JSON-LD must be reported as broken, not as missing.
    from check_structured_data import check_structured_data
    broken_sd = check_structured_data(
        '<script type="application/ld+json">{"@type":"Organization","name":"P",}</script>', "https://probe.example/")
    probe("structured data: unparseable JSON-LD -> 'Present but Unparseable', not 'Missing'",
          any("Unparseable" in t for t in titles({"readability": {"structured_data": broken_sd}}))
          and not any("Missing Schema.org" in t for t in titles({"readability": {"structured_data": broken_sd}})))
    return failures


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    emitted, per_file = script_emitted_keys(root)
    read = orchestrator_read_keys(root)

    drift = sorted(k for k in read
                   if k not in emitted
                   and k not in NESTING_KEYS
                   and k not in AGENT_INJECTED_KEYS)
    probe_failures = shape_probes(root)

    report = {
        "keys_read_by_orchestrator": len(read),
        "keys_emitted_by_scripts": len(emitted),
        "scripts_scanned": len(per_file),
        "contract_drift": drift,
        "shape_probe_failures": probe_failures,
        "ok": not drift and not probe_failures,
    }
    print(json.dumps(report, indent=2))
    if probe_failures:
        sys.stderr.write("\nSHAPE PROBE FAILED: script output no longer produces the expected "
                         "finding:\n" + "".join(f"  - {p}\n" for p in probe_failures))
    if drift:
        sys.stderr.write(
            "\nCONTRACT DRIFT: synthesize_report.py reads these keys but no sub-skill "
            "script emits them -- the matching findings can never fire:\n"
            + "".join(f"  - {k}\n" for k in drift)
            + "Fix by emitting the field in the owning script, or by reading the real "
              "field name (use pick() for aliases).\n")
    return 1 if (drift or probe_failures) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(json.dumps({"ok": False, "script_error": str(e)}))
        sys.exit(1)
