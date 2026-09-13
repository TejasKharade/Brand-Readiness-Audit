# Agent Instructions — Read This First

This repository is an **Agent Skill Marketplace** (agentskills.io format), not an
application to build, extend, or refactor. It contains no product code of its
own — only skills (`SKILL.md` + `scripts/` + `references/`) meant to be
followed literally by whichever agent is invoking them.

## If you are being asked to audit a website using this marketplace

**Do not analyze this repository and propose an implementation plan.** There is
nothing here to design or build — the marketplace already exists, is fully
implemented, and is meant to be *run*, not *engineered*. Planning is the wrong
mode for this request.

Instead:

1. Open [`skills/audit-orchestrator/SKILL.md`](skills/audit-orchestrator/SKILL.md)
   — the skill `marketplace.json` marks `"entrypoint": true` — and execute it
   **literally, step by step, right now**, exactly as written. It already specifies the full procedure: which
   scripts to run, in what order, what to pass between them, and when to stop
   early.
2. Do not ask for approval before running the sub-skills' scripts. They are
   all read-only (HTTP GET / HEAD requests and local parsing) and require no
   confirmation — running them is the task, not a step toward the task.
3. **Do not modify, delete, move or rename any existing file or folder** in
   this marketplace (`SKILL.md` files, scripts, references, `marketplace.json`,
   this file), and do not write new code or "improve" the marketplace as part
   of fulfilling an audit request. The only files an audit may create are its
   own scratch outputs and the report (see step 4) — never inside `skills/`.
   If a script errors, that error is itself evidence to report (see the
   SKILL.md's fallback guidance), not a bug to fix mid-audit. Fixing a real
   bug is a separate, explicit request.
4. **The task is only complete once `synthesize_report.py` has produced the
   JSON report** (conforming to
   [`skills/audit-orchestrator/references/audit_report_schema.json`](skills/audit-orchestrator/references/audit_report_schema.json))
   **and it has been shown to the user.** A summary, a plan, or partial findings
   typed into chat do not satisfy the request; only the report the script emits
   does. How to produce it depends on what the environment allows:
   - **Files can be written (normal case):** redirect each script's output to a
     scratch file — in `out/`, or in the system temp directory (`$TMPDIR`,
     `/tmp`, `%TEMP%`) if this folder is read-only — and run
     `python skills/audit-orchestrator/scripts/synthesize_report.py --site <url> --set <path>=<file> ... --out report.json`
     (Step 6 of the SKILL.md: pass output files by path, never retype their
     contents into a payload).
   - **Nothing can be written (read-only sandbox):** skip the redirects and
     `--out`. Pipe the payload (`{"site": ..., "skill_outputs": {...}}`) to
     `synthesize_report.py` on stdin with a heredoc — never `echo`, which
     truncates large payloads — and present the report it prints to stdout.
     If only `--out` fails, the report is still printed, with
     `audit_metadata.output_error` saying why.

   Either way, this holds even when the audit goes badly (a script crashes,
   the site blocks bots): `synthesize_report.py` always emits a valid report,
   including one that just says what it could not measure — see the
   `[!IMPORTANT]` callout at Step 6 of the orchestrator's SKILL.md.
