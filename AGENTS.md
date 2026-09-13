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
   — the skill `marketplace.json` marks `"entrypoint": true` — and execute it **literally, step by step, right
   now**, exactly as written. It already specifies the full procedure: which
   scripts to run, in what order, what to pass between them, and when to stop
   early.
2. Do not ask for approval before running the sub-skills' scripts. They are
   all read-only (HTTP GET / HEAD requests and local parsing) and require no
   confirmation — running them is the task, not a step toward the task.
3. Do not write new code, modify any script, or "improve" the marketplace as
   part of fulfilling an audit request. If a script errors, that error is
   itself evidence to report (see the SKILL.md's fallback guidance), not a
   bug to fix mid-audit. Fixing a real bug is a separate, explicit request.
4. **The task is only complete once a JSON file conforming to
   [`skills/audit-orchestrator/references/audit_report_schema.json`](skills/audit-orchestrator/references/audit_report_schema.json)
   has actually been written to disk** — by redirecting each script's output to
   a file and running
   `python skills/audit-orchestrator/scripts/synthesize_report.py --site <url> --set <path>=<file> ... --out report.json`
   (Step 6 of the SKILL.md: pass output files by path, never retype their
   contents into a payload) — and shown to the user. A summary, a plan, or partial findings typed into
   chat do not satisfy the request; only the emitted JSON file does. This
   holds even when the audit goes badly (a script crashes, the site blocks
   bots): `synthesize_report.py` always emits a valid report, including one
   that just says what it could not measure — see the `[!IMPORTANT]` callout
   at Step 6 of the orchestrator's SKILL.md.

## If you are being asked to modify or fix the marketplace itself

That's a normal engineering task — read the relevant `SKILL.md` and script(s),
make the change, and verify with
`python skills/audit-orchestrator/scripts/verify_contracts.py` before
considering it done. Planning is appropriate here.
The distinction that matters: *running an audit* is an operational task with a
fixed procedure already written down; *changing the marketplace* is a
development task like any other.
