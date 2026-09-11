
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
    "robots", "dual_identity", "page_signals", "sitemap", "crawl_depth", "sampled_pages",
    "rendering_barriers", "structured_data_hydration", "client_side_redirects",
    "structured_data", "semantic_structure", "content_consistency", "context_consistency",
    "nontext_facts", "nontext_content", "citation_consistency", "entity_disambiguation",
    "content_dates", "temporal_decay", "navigation_reachability", "content_depth",
    "mobile_responsiveness", "descriptor_consistency", "page_speed_signals",
    "landing_readiness",
}
AGENT_INJECTED_KEYS = {
    "agent_verdict", "ambiguous", "orientation_ok", "has_next_step", "inconsistent", "notes",
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
    for sub in ("audit-orchestrator", "crawl-access-audit", "freshness-corroboration"):
        sys.path.insert(0, os.path.join(root, "skills", sub, "scripts"))
    from synthesize_report import synthesize_report
    from check_robots import check_robots
    from check_entity_disambiguation import check_entity_disambiguation

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
