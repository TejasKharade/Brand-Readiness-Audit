#!/usr/bin/env python3
"""
aggregate.py - Cross-Site Aggregate Report

Reads all stage_c_scorecard.json files under audits/*/
and produces a single machine-readable aggregate report at:

    audits/aggregate_report.json

Designed to be read by a coding agent. The report answers:
  1. Which skills/gates have the worst recall across all sites?
  2. Which specific checks are hardcoded or broken?
  3. What new skills should be built?
  4. What is the severity recalibration rubric?
  5. Which sites are outliers (much harder / easier than expected)?

Usage:
    python tools/aggregate.py

No API calls. Pure local JSON aggregation — instant, free.
"""

import os
import sys
import json
import glob
import time
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDITS_DIR = os.path.join(ROOT_DIR, "audits")
OUTPUT_PATH = os.path.join(AUDITS_DIR, "aggregate_report.json")

GATE_NAMES = [
    "ai_crawler_access",
    "js_render_content",
    "structured_data_entity",
    "content_quality",
    "none_of_the_above",
]

SCORE_DIMS = [
    "recall",
    "precision",
    "evidence_quality",
    "fix_quality",
    "severity_calibration",
]


def load_scorecard(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        return json.loads(text)
    except Exception as e:
        print(f"  [aggregate] WARNING: Could not load {path}: {e}")
        return None


def find_all_scorecards():
    pattern = os.path.join(AUDITS_DIR, "*", "stage_c_scorecard.json")
    return sorted(glob.glob(pattern))


def aggregate_scores(scorecards):
    """Per-site and per-dimension score summary."""
    per_site = []
    dim_totals = defaultdict(list)

    for sc in scorecards:
        site = sc.get("site", "unknown")
        scores = sc.get("scores", {})
        composite = scores.get("composite", 0)
        health = sc.get("overall_health", "unknown")

        site_entry = {"site": site, "health": health, "scores": {}}
        for d in SCORE_DIMS:
            v = scores.get(d, 0)
            site_entry["scores"][d] = v
            dim_totals[d].append(v)
        site_entry["scores"]["composite"] = composite
        dim_totals["composite"].append(composite)
        per_site.append(site_entry)

    # Sort worst composite first so a coding agent sees the biggest problems up top
    per_site.sort(key=lambda x: x["scores"].get("composite", 100))

    averages = {}
    for d, vals in dim_totals.items():
        averages[d] = round(sum(vals) / len(vals), 1) if vals else 0

    return per_site, averages


def aggregate_missed_findings(scorecards):
    """
    Collect all missed findings across sites, group by responsible_gate,
    and identify patterns that recur across multiple sites (systemic gaps).
    """
    gate_misses = defaultdict(list)   # gate -> list of missed finding entries
    fix_location_counts = defaultdict(int)

    for sc in scorecards:
        site = sc.get("site", "unknown")
        for mf in sc.get("recall", {}).get("missed_findings", []):
            gate = mf.get("responsible_gate", "unknown")
            entry = {
                "site": site,
                "gt_id": mf.get("gt_id"),
                "gt_title": mf.get("gt_title"),
                "gt_severity": mf.get("gt_severity"),
                "reason_missed": mf.get("reason_missed"),
                "fix_location": mf.get("fix_location"),
            }
            gate_misses[gate].append(entry)
            fix_loc = mf.get("fix_location", "unknown")
            fix_location_counts[fix_loc] += 1

    # Identify systemic misses: same fix_location appears across 2+ sites
    systemic = []
    title_groups = defaultdict(list)   # rough title cluster -> list of sites
    for sc in scorecards:
        site = sc.get("site", "unknown")
        for mf in sc.get("recall", {}).get("missed_findings", []):
            # Cluster by first 6 words of title as a rough dedup key
            words = mf.get("gt_title", "").lower().split()
            key = " ".join(words[:6])
            title_groups[key].append({
                "site": site,
                "gt_title": mf.get("gt_title"),
                "fix_location": mf.get("fix_location"),
                "gt_severity": mf.get("gt_severity"),
            })

    for key, entries in title_groups.items():
        if len(entries) >= 2:
            sites = list({e["site"] for e in entries})
            systemic.append({
                "pattern": entries[0].get("gt_title"),
                "sites_affected": sites,
                "fix_location": entries[0].get("fix_location"),
                "severity": entries[0].get("gt_severity"),
                "occurrence_count": len(entries),
            })

    systemic.sort(key=lambda x: -x["occurrence_count"])

    # Per-gate miss summary
    gate_summary = {}
    for gate in GATE_NAMES:
        misses = gate_misses.get(gate, [])
        gate_summary[gate] = {
            "total_misses": len(misses),
            "critical_misses": sum(1 for m in misses if m.get("gt_severity") == "critical"),
            "high_misses": sum(1 for m in misses if m.get("gt_severity") == "high"),
            "misses": misses,
        }

    # Top scripts to fix by miss frequency
    top_fix_locations = sorted(
        [{"script": k, "miss_count": v} for k, v in fix_location_counts.items()],
        key=lambda x: -x["miss_count"]
    )

    return gate_summary, systemic, top_fix_locations


def aggregate_false_positives(scorecards):
    """Collect all false positives, group by gate."""
    gate_fps = defaultdict(list)
    for sc in scorecards:
        site = sc.get("site", "unknown")
        for fp in sc.get("precision", {}).get("false_positives", []):
            gate = fp.get("gate", "unknown")
            gate_fps[gate].append({
                "site": site,
                "skill_id": fp.get("skill_id"),
                "skill_title": fp.get("skill_title"),
                "reason": fp.get("reason"),
                "fix_location": fp.get("fix_location"),
            })

    return {
        gate: {"count": len(fps), "examples": fps[:5]}  # cap examples at 5
        for gate, fps in gate_fps.items()
    }


def aggregate_new_skill_candidates(scorecards):
    """
    Deduplicate and rank new skill candidates across all sites.
    A candidate that appears on 3+ sites is a strong signal.
    """
    candidate_groups = defaultdict(list)
    for sc in scorecards:
        site = sc.get("site", "unknown")
        for c in sc.get("new_skill_candidates", []):
            words = c.get("pattern", "").lower().split()
            key = " ".join(words[:5])
            candidate_groups[key].append({
                "site": site,
                "pattern": c.get("pattern"),
                "example_gt_finding": c.get("example_gt_finding"),
                "suggested_script_name": c.get("suggested_script_name"),
            })

    ranked = []
    for key, entries in candidate_groups.items():
        sites = list({e["site"] for e in entries})
        ranked.append({
            "pattern": entries[0].get("pattern"),
            "suggested_script_name": entries[0].get("suggested_script_name"),
            "sites_where_seen": sites,
            "signal_strength": len(sites),  # higher = more sites want this
            "example_gt_findings": [e["example_gt_finding"] for e in entries[:3]],
        })

    ranked.sort(key=lambda x: -x["signal_strength"])
    return ranked


def aggregate_severity_recalibration(scorecards):
    """
    Build a severity recalibration rubric from all miscalibrations.
    Groups by (skill_severity, gt_severity) pair to show directional bias.
    """
    pair_counts = defaultdict(int)
    gate_bias = defaultdict(lambda: defaultdict(int))  # gate -> direction -> count

    for sc in scorecards:
        for mc in sc.get("severity_calibration", {}).get("miscalibrations", []):
            skill_sev = mc.get("skill_severity", "?")
            gt_sev = mc.get("gt_severity", "?")
            gate = mc.get("gate", "unknown")
            pair_counts[(skill_sev, gt_sev)] += 1

            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
            skill_rank = sev_order.get(skill_sev, 2)
            gt_rank = sev_order.get(gt_sev, 2)
            if skill_rank > gt_rank:
                gate_bias[gate]["over_reported"] += 1
            elif skill_rank < gt_rank:
                gate_bias[gate]["under_reported"] += 1

    transition_matrix = [
        {"skill_severity": k[0], "gt_severity": k[1], "count": v}
        for k, v in pair_counts.items()
    ]
    transition_matrix.sort(key=lambda x: -x["count"])

    gate_bias_summary = {
        gate: dict(bias) for gate, bias in gate_bias.items()
    }

    return {
        "transition_matrix": transition_matrix,
        "gate_bias": gate_bias_summary,
        "interpretation": (
            "over_reported means the skill assigns higher severity than ground truth (noisy). "
            "under_reported means the skill assigns lower severity than ground truth (dangerous — "
            "real problems appear minor)."
        ),
    }


def aggregate_hardcoded_assumptions(scorecards):
    """Collect all hardcoded assumption flags, group by gate and script."""
    script_groups = defaultdict(list)
    for sc in scorecards:
        site = sc.get("site", "unknown")
        for ha in sc.get("hardcoded_assumptions", []):
            fix_loc = ha.get("fix_location", "unknown")
            script_groups[fix_loc].append({
                "site": site,
                "gate": ha.get("gate"),
                "description": ha.get("description"),
            })

    return [
        {
            "fix_location": script,
            "occurrence_count": len(entries),
            "sites": list({e["site"] for e in entries}),
            "examples": entries[:3],
        }
        for script, entries in sorted(
            script_groups.items(), key=lambda x: -len(x[1])
        )
    ]


def health_summary(scorecards):
    counts = defaultdict(int)
    for sc in scorecards:
        counts[sc.get("overall_health", "unknown")] += 1
    return dict(counts)


def main():
    paths = find_all_scorecards()
    if not paths:
        print("[aggregate] No stage_c_scorecard.json files found under audits/.")
        print("            Run the full pipeline first: python tools/run_pipeline.py")
        sys.exit(1)

    print(f"[aggregate] Found {len(paths)} site scorecard(s). Loading...")
    scorecards = [sc for p in paths if (sc := load_scorecard(p)) is not None]
    print(f"[aggregate] Successfully loaded {len(scorecards)} scorecard(s).")

    if not scorecards:
        print("[aggregate] All scorecards failed to load. Aborting.")
        sys.exit(1)

    # --- Run all aggregations ---
    per_site, avg_scores = aggregate_scores(scorecards)
    gate_miss_summary, systemic_misses, top_fix_locations = aggregate_missed_findings(scorecards)
    false_positives = aggregate_false_positives(scorecards)
    new_skill_candidates = aggregate_new_skill_candidates(scorecards)
    severity_recalibration = aggregate_severity_recalibration(scorecards)
    hardcoded_assumptions = aggregate_hardcoded_assumptions(scorecards)
    health_counts = health_summary(scorecards)

    report = {
        # ----------------------------------------------------------------
        # Header
        # ----------------------------------------------------------------
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sites_evaluated": len(scorecards),
        "site_list": [sc.get("site") for sc in scorecards],

        # ----------------------------------------------------------------
        # Section 1: Overall score summary
        # Read this first. One number per dimension, averaged across sites.
        # ----------------------------------------------------------------
        "score_summary": {
            "average_scores": avg_scores,
            "health_distribution": health_counts,
            "per_site": per_site,
        },

        # ----------------------------------------------------------------
        # Section 2: Recall gaps — what the skills missed
        # Primary input for: fixing existing skill scripts.
        # Fields: gate_miss_summary (by gate), systemic_misses (patterns
        # that recur across 2+ sites), top_fix_locations (which scripts
        # to open first).
        # ----------------------------------------------------------------
        "recall_gaps": {
            "by_gate": gate_miss_summary,
            "systemic_patterns": systemic_misses,
            "top_scripts_to_fix": top_fix_locations,
        },

        # ----------------------------------------------------------------
        # Section 3: Precision gaps — false positives by gate
        # Primary input for: tightening thresholds, removing noisy checks.
        # ----------------------------------------------------------------
        "precision_gaps": {
            "by_gate": false_positives,
        },

        # ----------------------------------------------------------------
        # Section 4: New skill candidates
        # Primary input for: deciding what new skill scripts to build.
        # Ranked by signal_strength (number of sites where the gap appeared).
        # Only build if signal_strength >= 2.
        # ----------------------------------------------------------------
        "new_skill_candidates": new_skill_candidates,

        # ----------------------------------------------------------------
        # Section 5: Severity recalibration rubric
        # Primary input for: adjusting severity assignments in skill scripts.
        # transition_matrix shows (skill_severity -> gt_severity) counts.
        # gate_bias shows which gates over- or under-report severity.
        # ----------------------------------------------------------------
        "severity_recalibration": severity_recalibration,

        # ----------------------------------------------------------------
        # Section 6: Hardcoded assumptions
        # Primary input for: generalizing checks that only work on specific
        # site structures. Ranked by occurrence_count across sites.
        # ----------------------------------------------------------------
        "hardcoded_assumptions": hardcoded_assumptions,
    }

    os.makedirs(AUDITS_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # --- Terminal summary ---
    print()
    print("=" * 70)
    print("AGGREGATE REPORT SUMMARY")
    print("=" * 70)
    print(f"  Sites evaluated : {len(scorecards)}")
    print(f"  Health breakdown: {health_counts}")
    print()
    print("  Average scores across all sites:")
    for d in SCORE_DIMS + ["composite"]:
        bar_val = int(avg_scores.get(d, 0) / 5)  # scale 0-100 to 0-20 chars
        bar = "█" * bar_val + "░" * (20 - bar_val)
        print(f"    {d:<25} {bar} {avg_scores.get(d, 0):>5.1f}/100")
    print()

    if top_fix_locations:
        print("  Top scripts to fix (by missed-finding count):")
        for entry in top_fix_locations[:5]:
            print(f"    {entry['script']:<40} {entry['miss_count']} miss(es)")
    print()

    if new_skill_candidates:
        strong = [c for c in new_skill_candidates if c["signal_strength"] >= 2]
        print(f"  New skill candidates (signal >= 2 sites): {len(strong)}")
        for c in strong[:3]:
            print(f"    → {c['suggested_script_name']}: {c['pattern'][:70]}")
    print()

    print(f"  Full report saved to: {OUTPUT_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()