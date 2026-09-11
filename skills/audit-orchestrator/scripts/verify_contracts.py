
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
                "readability-audit", "crawl-render-audit"):
        sys.path.insert(0, os.path.join(root, "skills", sub, "scripts"))
    from synthesize_report import synthesize_report
    from check_robots import check_robots
    from check_entity_disambiguation import check_entity_disambiguation, classify_authority_sameas
    from check_structured_data import check_structured_data
    from check_rendering_barriers import check_rendering_barriers
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
    probe("robots: training-only root block -> no critical finding, no gate",
          not any(f["severity"] == "critical" for f in rep["findings"]) and rep["brand_ai_readiness_score"] > 40)
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
