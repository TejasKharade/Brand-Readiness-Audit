#!/usr/bin/env python3
"""
test_pipeline.py - Interactive Multi-Skill Audit Runner

Prompts for a target URL (or accepts it via CLI argument) and executes
the complete AI Readiness Audit pipeline across all available skills in sequence.

Pipeline Chain:
  Skill 1: ai-crawler-access-audit      (Gate 1: Crawl & Protocol Access)
    └──> Skill 2: js-render-content-audit   (Gate 2: Parse & Hydration Parity)
          └──> Skill 3: structured-data-entity-audit (Gate 3: Entity Trust & Grounding)
                └──> (Downstream Skills 4, 5, 6 as they are authored)
"""

import sys
import os
import json
import time
import shutil
import tempfile
import subprocess
from urllib.parse import urlparse

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(ROOT_DIR, "marketplace", "skills")


def print_banner(text, char="="):
    line = char * max(65, len(text) + 4)
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}\n")


def format_url(raw_url):
    raw_url = raw_url.strip()
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = "https://" + raw_url
    return raw_url


def run_command_stream(cmd, step_name):
    """Executes command and returns parsed JSON if stdout is JSON, or raw output."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        elapsed = time.time() - t0

        if proc.returncode != 0:
            print(f"❌ {step_name} failed (code {proc.returncode}) in {elapsed:.2f}s:")
            print(proc.stderr.strip() or proc.stdout.strip())
            return None, elapsed

        # Try to parse json from stdout
        out_text = proc.stdout.strip()
        data = None
        try:
            data = json.loads(out_text)
        except json.JSONDecodeError:
            # Look for JSON between first { and last }
            first_brace = out_text.find("{")
            last_brace = out_text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(out_text[first_brace:last_brace + 1])
                except Exception:
                    pass

        return data if data else out_text, elapsed

    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ Execution error in {step_name}: {str(e)}")
        return None, elapsed


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print_banner("Brand AI-Readiness Audit Pipeline Runner")

    # 1. Get Target URL
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    else:
        try:
            target_url = input("Enter website URL to audit (e.g., https://docker.com): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAudit cancelled.")
            sys.exit(0)

    if not target_url:
        print("Error: No URL provided.")
        sys.exit(1)

    target_url = format_url(target_url)
    parsed = urlparse(target_url)
    domain = parsed.netloc or parsed.path.split("/")[0]

    print(f"\nTarget Domain: {domain}")
    print(f"Target Root:   {target_url}")
    print(f"Started At:    {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Temporary directory for intermediate skill handoffs
    temp_dir = tempfile.mkdtemp(prefix="brand_audit_")
    path_access_json = os.path.join(temp_dir, "access_output.json")
    path_render_json = os.path.join(temp_dir, "render_output.json")
    path_schema_json = os.path.join(temp_dir, "schema_output.json")

    pipeline_results = {}
    total_start_time = time.time()

    try:
        # =====================================================================
        # Skill 1: AI Crawler Access Audit
        # =====================================================================
        print_banner("Step 1/3: AI Crawler Access Audit (Gate 1: Crawlability & Protocol)", "-")
        s1_script = os.path.join(SKILLS_DIR, "ai-crawler-access-audit", "scripts", "check_access.py")

        cmd_s1 = [sys.executable, s1_script, target_url, "--json"]
        s1_data, s1_time = run_command_stream(cmd_s1, "Skill 1 (Crawler Access)")

        if s1_data and isinstance(s1_data, dict):
            pipeline_results["skill_1"] = s1_data
            with open(path_access_json, "w", encoding="utf-8") as f:
                json.dump(s1_data, f, indent=2)

            summ = s1_data.get("summary", {})
            sampled = s1_data.get("sampled_pages", {})
            print(f"[OK] Skill 1 Completed in {s1_time:.2f}s")
            print(f"     - Discovered Pages: {sampled.get('total_discovered', 0)} (Curated sample: {len(sampled.get('curated_sample', []))})")
            print(f"     - Findings: {summ.get('total_findings', 0)} ({summ.get('critical', 0)} Critical, {summ.get('high', 0)} High, {summ.get('medium', 0)} Medium, {summ.get('low', 0)} Low)")
            for f in s1_data.get("findings", []):
                print(f"       * [{f.get('code')}] {f.get('title')} ({f.get('severity')})")
        else:
            print("[!] Skill 1 did not return valid JSON. Proceeding with default parameters.")

        # =====================================================================
        # Skill 2: JS Render & Content Parity Audit
        # =====================================================================
        print_banner("Step 2/3: JavaScript Render & Parity Audit (Gate 2: Parse & Hydration)", "-")
        s2_script = os.path.join(SKILLS_DIR, "js-render-content-audit", "scripts", "check_render.py")

        cmd_s2 = [sys.executable, s2_script, target_url, "--json"]
        if os.path.isfile(path_access_json):
            cmd_s2.extend(["--input-json", path_access_json])

        s2_data, s2_time = run_command_stream(cmd_s2, "Skill 2 (JS Render Parity)")

        if s2_data and isinstance(s2_data, dict):
            pipeline_results["skill_2"] = s2_data
            with open(path_render_json, "w", encoding="utf-8") as f:
                json.dump(s2_data, f, indent=2)

            summ = s2_data.get("summary", {})
            r_prof = s2_data.get("render_profile", {})
            print(f"[OK] Skill 2 Completed in {s2_time:.2f}s (Engine: {r_prof.get('browser_engine', 'Headless Browser')})")
            print(f"     - Pages Audited: {r_prof.get('pages_audited', 0)}")
            for p in r_prof.get("per_page_metrics", []):
                m = p.get("metrics", {})
                print(f"       * {p.get('url')} -> Parity: {m.get('parity_pct', 0.0)}% (Pass A: {m.get('pass_a_latency_ms', 0):.0f}ms, Pass B: {m.get('pass_b_latency_ms', 0):.0f}ms)")
            print(f"     - Findings: {summ.get('total_findings', 0)} ({summ.get('critical', 0)} Critical, {summ.get('high', 0)} High, {summ.get('medium', 0)} Medium)")
            for f in s2_data.get("findings", []):
                print(f"       * [{f.get('code')}] {f.get('title')} ({f.get('severity')})")
        else:
            print("[!] Skill 2 did not return valid JSON.")

        # =====================================================================
        # Skill 3: Structured Data & Entity Grounding Audit
        # =====================================================================
        print_banner("Step 3/3: Structured Data & Entity Audit (Gate 3: Entity Trust & Grounding)", "-")
        s3_script = os.path.join(SKILLS_DIR, "structured-data-entity-audit", "scripts", "check_schema.py")

        cmd_s3 = [sys.executable, s3_script, target_url, "--json"]
        if os.path.isfile(path_access_json):
            cmd_s3.extend(["--input-access", path_access_json])
        if os.path.isfile(path_render_json):
            cmd_s3.extend(["--input-render", path_render_json])

        s3_data, s3_time = run_command_stream(cmd_s3, "Skill 3 (Entity & Schema)")

        if s3_data and isinstance(s3_data, dict):
            pipeline_results["skill_3"] = s3_data
            with open(path_schema_json, "w", encoding="utf-8") as f:
                json.dump(s3_data, f, indent=2)

            summ = s3_data.get("summary", {})
            e_prof = s3_data.get("entity_profile", {})
            root_str = f"Found ({', '.join(e_prof.get('root_entity_types', []))})" if e_prof.get("root_entity_detected") else "Missing"
            print(f"[OK] Skill 3 Completed in {s3_time:.2f}s")
            print(f"     - Root Entity: {root_str}")
            if e_prof.get("same_as_authorities"):
                print(f"     - sameAs Authorities: {', '.join(e_prof.get('same_as_authorities'))}")
            print(f"     - Pages Audited: {e_prof.get('pages_audited', 0)} (Coverage: {e_prof.get('schema_coverage_pct', 0.0)}%)")
            print(f"     - Findings: {summ.get('total_findings', 0)} ({summ.get('critical', 0)} Critical, {summ.get('high', 0)} High, {summ.get('medium', 0)} Medium, {summ.get('low', 0)} Low)")
            for f in s3_data.get("findings", []):
                print(f"       * [{f.get('code')}] {f.get('title')} ({f.get('severity')})")
        else:
            print("[!] Skill 3 did not return valid JSON.")

        # =====================================================================
        # Executive Summary & Report Export
        # =====================================================================
        total_time = time.time() - total_start_time
        print_banner(f"AUDIT COMPLETE - {domain} ({total_time:.2f}s total)")

        # Aggregate finding counts
        total_critical = 0
        total_high = 0
        total_medium = 0
        total_low = 0

        for skill_key, s_data in pipeline_results.items():
            if isinstance(s_data, dict):
                s_sum = s_data.get("summary", {})
                total_critical += s_sum.get("critical", 0)
                total_high += s_sum.get("high", 0)
                total_medium += s_sum.get("medium", 0)
                total_low += s_sum.get("low", 0)

        total_findings = total_critical + total_high + total_medium + total_low

        print("Scorecard:")
        print(f"   - Total Findings: {total_findings}")
        print(f"   - Critical:       {total_critical}")
        print(f"   - High:           {total_high}")
        print(f"   - Medium:         {total_medium}")
        print(f"   - Low/Info:       {total_low}")

        # Gate status
        print("\nAI Citation Pipeline Gates:")
        g1_status = "[FAIL] BLOCKED" if total_critical > 0 else "[WARN] WARNINGS" if any(f.get('severity') == 'HIGH' for f in pipeline_results.get('skill_1', {}).get('findings', [])) else "[PASS] CLEAR"
        g2_status = "[FAIL] BLOCKED" if any(f.get('severity') == 'CRITICAL' for f in pipeline_results.get('skill_2', {}).get('findings', [])) else "[WARN] GAPS" if any(f.get('severity') == 'HIGH' for f in pipeline_results.get('skill_2', {}).get('findings', [])) else "[PASS] CLEAR"
        g3_status = "[WARN] UNGROUNDED" if any(f.get('severity') == 'HIGH' for f in pipeline_results.get('skill_3', {}).get('findings', [])) else "[PASS] GROUNDED"

        print(f"   Gate 1 (Crawl & Protocol Access):   {g1_status}")
        print(f"   Gate 2 (Parse & Content Parity):    {g2_status}")
        print(f"   Gate 3 (Entity Trust & Grounding):  {g3_status}")

        # Save Combined Report to audits/test_runs/
        clean_domain = domain.replace(".", "_").replace(":", "_")
        test_runs_dir = os.path.join(ROOT_DIR, "audits", "test_runs")
        os.makedirs(test_runs_dir, exist_ok=True)
        report_file = os.path.join(test_runs_dir, f"{clean_domain}_audit.json")

        final_report = {
            "target": target_url,
            "domain": domain,
            "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_runtime_seconds": round(total_time, 2),
            "summary": {
                "total_findings": total_findings,
                "critical": total_critical,
                "high": total_high,
                "medium": total_medium,
                "low": total_low
            },
            "skills": pipeline_results
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=2)

        print(f"\n[SAVED] Full audit report saved to:")
        print(f"   {report_file}\n")

    finally:
        # Clean up temporary scratch directory
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
