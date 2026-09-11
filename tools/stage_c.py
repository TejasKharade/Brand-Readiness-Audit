#!/usr/bin/env python3
"""
stage_c.py - Skill Evaluation Comparator (Stage C)

Takes Stage A (skill_findings.json) and Stage B (ground_truth_findings.json)
for a single site, sends both to an LLM judge, and produces a structured
scorecard at:

    audits/{domain}/stage_c_scorecard.json

The scorecard is designed to be read by a coding agent. Every field is
machine-parseable. The judge scores five dimensions per site and, crucially,
identifies exactly which skills/gates are responsible for each gap — so a
coding agent can open the right file and know what to fix.

Model: openrouter/free (OpenRouter's automatic free-model router —
       picks whichever free model is available, so no 404s when
       specific models get pulled. No credit card required.)

Usage (standalone):
    export OPENROUTER_API_KEY="your_key_here"
    python tools/stage_c.py https://www.docker.com

Usage (called from orchestrator):
    from stage_c import run_stage_c
    run_stage_c(domain, root_dir)
"""

import os
import sys
import json
import re
import time
from urllib.parse import urlparse

from openai import OpenAI

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_NAME = "google/gemini-2.5-flash"  # Specific, reliable model with a massive context window

# Rate-limit headroom: free tier is 20 RPM / 50 RPD on OpenRouter free models.
# Stage C makes exactly 1 call per site, so this is only a safeguard.
MAX_RETRIES = 4
RETRY_WAITS = [10, 20, 40, 60]   # seconds, escalating

# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """You are a senior software quality engineer evaluating an
automated AI-discoverability audit tool (the "skill pipeline") against an
independent blind audit (the "ground truth") of the same website.

Your job is to identify exactly where the skill pipeline fails, succeeds,
and could be improved -- so a coding agent can read this report and make
targeted fixes to the skill scripts.

You will receive two JSON finding sets for the same website:

SKILL FINDINGS (Stage A):
{skill_findings}

GROUND TRUTH FINDINGS (Stage B):
{ground_truth_findings}

Evaluate the skill pipeline on these five dimensions. For each dimension,
produce a numeric score AND a list of specific, actionable observations a
coding agent could act on directly.

---

DIMENSION 1 — RECALL (did the skills catch what the ground truth found?)
Score 0-100. 100 = skills caught everything ground truth caught.

For every ground-truth finding NOT matched by any skill finding, output a
missed_finding entry with:
  - gt_id: the ground truth finding id
  - gt_title: the ground truth finding title
  - gt_severity: the ground truth severity
  - responsible_gate: which skill gate SHOULD have caught this
    (one of: ai_crawler_access, js_render_content,
     structured_data_entity, content_quality, none_of_the_above)
  - reason_missed: concise diagnosis — is this a hardcoded check, a
    missing check entirely, wrong threshold, or a logic bug?
  - fix_location: the specific script filename that needs changing
    (e.g. check_render.py, check_access.py, check_schema.py,
     check_content_quality.py, or "new_skill_needed")

DIMENSION 2 — PRECISION (did the skills report things that are not real problems?)
Score 0-100. 100 = no false positives.

For every skill finding that has NO counterpart in ground truth AND
represents a probable false positive (not just a different angle on the
same real issue), output a false_positive entry with:
  - skill_id: the skill finding id
  - skill_title: the skill finding title
  - gate: which gate produced it
  - reason: why this is likely a false positive
  - fix_location: which script to fix

DIMENSION 3 — EVIDENCE QUALITY (is the skill's evidence specific enough for a developer to act on?)
Score 0-100. 100 = all evidence is specific (URL + concrete observation).

For each skill finding where the evidence is vague (no URL, or just a
general statement with no concrete artifact), output an evidence_gap entry:
  - skill_id
  - skill_title
  - gate
  - problem: what is missing from the evidence field
  - fix_location

DIMENSION 4 — FIX QUALITY (are the suggested_action fields actionable?)
Score 0-100. 100 = all suggested actions are concrete and implementable.

For each skill finding where suggested_action.summary is generic ("fix
this", "improve this"), output a fix_gap entry:
  - skill_id
  - skill_title
  - gate
  - problem: what makes it vague
  - fix_location

DIMENSION 5 — SEVERITY CALIBRATION (are severities appropriate?)
Score 0-100. 100 = all severities match ground truth judgment.

For each finding present in both sets where the severity disagrees by more
than one level (e.g. skill says low, ground truth says critical), output a
miscalibration entry:
  - skill_id
  - gt_id
  - title
  - skill_severity
  - gt_severity
  - gate
  - fix_location

---

After scoring all five dimensions, produce:

new_skill_candidates: list of finding patterns in ground truth that no
existing skill gate covers at all (responsible_gate = none_of_the_above
from dimension 1). For each:
  - pattern: what the new skill would check
  - example_gt_finding: the gt_id that illustrates it
  - suggested_script_name: what to call the new script

hardcoded_assumptions: list of checks in the skills that appear to assume
a specific site structure or value rather than generalizing. For each:
  - description: what the hardcoded assumption is
  - gate: which gate
  - fix_location: which script

overall_health: one of "good" | "needs_work" | "broken"
  - "good": recall >= 70, precision >= 70, no critical misses
  - "broken": recall < 40 OR a critical ground-truth finding was missed
  - "needs_work": everything else

summary_for_agent: a single plain-English paragraph (max 5 sentences)
  that a coding agent should read first before looking at any other field.
  Name specific files, specific checks, and specific fixes. No vague
  language.

---

Respond with ONLY a single JSON object. No markdown, no explanation
outside the JSON. Use exactly this top-level shape:

{{
  "site": "{domain}",
  "evaluated_at": "ISO timestamp",
  "scores": {{
    "recall": 0,
    "precision": 0,
    "evidence_quality": 0,
    "fix_quality": 0,
    "severity_calibration": 0,
    "composite": 0
  }},
  "recall": {{
    "score": 0,
    "missed_findings": []
  }},
  "precision": {{
    "score": 0,
    "false_positives": []
  }},
  "evidence_quality": {{
    "score": 0,
    "evidence_gaps": []
  }},
  "fix_quality": {{
    "score": 0,
    "fix_gaps": []
  }},
  "severity_calibration": {{
    "score": 0,
    "miscalibrations": []
  }},
  "new_skill_candidates": [],
  "hardcoded_assumptions": [],
  "overall_health": "needs_work",
  "summary_for_agent": ""
}}

scores.composite = average of the five dimension scores, rounded to 1
decimal place.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json_file(path):
    """Load a JSON file with UTF-8 / UTF-16 tolerance."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


def extract_json_block(text):
    """Strip ```json fences if present."""
    if text is None:
        raise ValueError("Model returned None for message content.")
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def trim_findings_for_prompt(findings, max_findings=40, max_evidence_chars=300):
    """
    Trim finding lists to fit comfortably inside the context window.
    Keeps id, title, severity, gate/code, evidence (truncated), suggested_action.
    """
    trimmed = []
    for f in findings[:max_findings]:
        ev = f.get("evidence", "")
        if len(ev) > max_evidence_chars:
            ev = ev[:max_evidence_chars] + "…"
        sa = f.get("suggested_action", {})
        if isinstance(sa, dict):
            sa_summary = sa.get("summary", "")[:200]
        else:
            sa_summary = str(sa)[:200]
        trimmed.append({
            "id": f.get("id"),
            "title": f.get("title"),
            "severity": f.get("severity"),
            "gate": f.get("gate") or f.get("code", "unknown"),
            "url": f.get("url", ""),
            "evidence": ev,
            "suggested_action_summary": sa_summary,
        })
    return trimmed


def call_judge(client, skill_findings, ground_truth_findings, domain):
    """Send both finding sets to the LLM judge and return parsed JSON."""
    skill_trimmed = trim_findings_for_prompt(skill_findings)
    gt_trimmed = trim_findings_for_prompt(ground_truth_findings)

    prompt = JUDGE_PROMPT.format(
        domain=domain,
        skill_findings=json.dumps(skill_trimmed, indent=2),
        ground_truth_findings=json.dumps(gt_trimmed, indent=2),
    )

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,   # low temp for structured/deterministic output
                max_tokens=4096,
            )
            # Log which model the free router actually selected
            actual_model = getattr(response, "model", MODEL_NAME)
            if actual_model != MODEL_NAME:
                print(f"  [Stage C] Router selected: {actual_model}")
            raw = response.choices[0].message.content
            return json.loads(extract_json_block(raw))

        except Exception as e:
            last_error = e
            err_str = str(e)
            wait_s = RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)]

            if "404" in err_str:
                # Model not found — no point retrying, fail fast with a clear message
                raise RuntimeError(
                    f"OpenRouter returned 404. This usually means your API key is "
                    f"invalid or the free router has no models available right now. "
                    f"Raw error: {e}"
                )
            elif "429" in err_str or "rate" in err_str.lower():
                print(f"  [Stage C] Rate limited, waiting {wait_s}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_s)
            elif "503" in err_str or "unavailable" in err_str.lower():
                print(f"  [Stage C] Model overloaded, waiting {wait_s}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_s)
            elif isinstance(e, (json.JSONDecodeError, ValueError)):
                # Bad JSON or empty output from model — retry with a nudge
                print(f"  [Stage C] Output error on attempt {attempt + 1} ({e}), retrying...")
                time.sleep(5)
            else:
                raise

    raise RuntimeError(f"Stage C judge failed after {MAX_RETRIES} retries: {last_error}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_stage_c(domain, root_dir):
    """
    Compare Stage A and Stage B findings for `domain`.
    Writes audits/{domain}/stage_c_scorecard.json.
    Skips gracefully if either input file is missing.
    Returns the output path, or None if skipped.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set.")

    audit_dir = os.path.join(root_dir, "audits", domain)
    skill_path = os.path.join(audit_dir, "skill_findings.json")
    gt_path = os.path.join(audit_dir, "ground_truth_findings.json")

    # Skip if either file is missing — don't crash the whole batch
    if not os.path.isfile(skill_path):
        print(f"  [Stage C] Skipping {domain}: skill_findings.json not found.")
        return None
    if not os.path.isfile(gt_path):
        print(f"  [Stage C] Skipping {domain}: ground_truth_findings.json not found.")
        return None

    print(f"  [Stage C] Loading findings for {domain}...")
    skill_data = load_json_file(skill_path)
    gt_data = load_json_file(gt_path)

    skill_findings = skill_data.get("findings", [])
    gt_findings = gt_data.get("findings", [])

    print(f"  [Stage C] Skill findings: {len(skill_findings)} | Ground truth: {len(gt_findings)}")

    if not skill_findings and not gt_findings:
        print(f"  [Stage C] Both finding sets are empty — nothing to compare.")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
    )

    print(f"  [Stage C] Sending to judge ({MODEL_NAME})...")
    scorecard = call_judge(client, skill_findings, gt_findings, domain)

    # Stamp metadata fields the judge might have left as placeholders
    scorecard["site"] = domain
    scorecard.setdefault("evaluated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    # Recompute composite from the five scores in case the model drifted
    scores = scorecard.get("scores", {})
    dims = ["recall", "precision", "evidence_quality", "fix_quality", "severity_calibration"]
    dim_scores = [scores.get(d, 0) for d in dims]
    if any(dim_scores):
        scores["composite"] = round(sum(dim_scores) / len(dim_scores), 1)
    scorecard["scores"] = scores

    out_path = os.path.join(audit_dir, "stage_c_scorecard.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)

    health = scorecard.get("overall_health", "unknown")
    composite = scores.get("composite", "?")
    print(f"  [Stage C] Saved: {out_path}")
    print(f"  [Stage C] Health: {health.upper()} | Composite score: {composite}/100")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if len(sys.argv) < 2:
        print("Usage: python tools/stage_c.py <url_or_domain>")
        print("  e.g. python tools/stage_c.py https://www.docker.com")
        print("       python tools/stage_c.py www.docker.com")
        sys.exit(1)

    arg = sys.argv[1]
    if arg.startswith("http"):
        target_domain = urlparse(arg).netloc
    else:
        target_domain = arg

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root
    result = run_stage_c(target_domain, root)
    if result is None:
        sys.exit(1)