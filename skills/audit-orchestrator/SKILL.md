---
name: audit-orchestrator
description: Entrypoint master orchestrator skill that coordinates execution across all 5 specialized sub-skills (crawl-access-audit, crawl-render-audit, readability-audit, freshness-corroboration, engagement-audit) and synthesizes the final Brand AI Readiness Audit Report.
license: MIT
compatibility: Requires Python 3 and outbound network access
allowed-tools: Bash Read WebFetch WebSearch
---

# `audit-orchestrator` Skill

Serves as the entrypoint master orchestrator for conducting complete end-to-end Brand AI Readiness Audits across target website domains and URLs.

> [!NOTE]
> **Orchestrator Role**:
> The `audit-orchestrator` skill coordinates the sequential execution of all 5 specialized sub-skills (`crawl-access-audit`, `crawl-render-audit`, `readability-audit`, `freshness-corroboration`, `engagement-audit`) and synthesizes their raw JSON findings into a unified, authoritative Brand AI Readiness Audit Report.

---

## Inputs

The orchestrator receives target audit parameters:

- `site` *(string)*: Canonical target website domain or URL (e.g. `"https://example.com"`).
- `skill_outputs` *(object, optional)*: Key-value map of sub-skill JSON output objects (`crawl_access`, `crawl_render`, `readability`, `freshness_corroboration`, `engagement`).
- `findings` *(list of objects, optional)*: Additional explicit findings to inject.
- `proactive_recommendations` *(list of strings, optional)*: Custom remediation recommendations.

---

## Workflow & Sub-Skill Execution Procedure

> [!IMPORTANT]
> **Runtime budget (<5 minutes total, per the handout constraint)**: "sequential
> execution of all 5 sub-skills" above describes the DEPENDENCY order (access
> before render, render before readability, ...), not that every script call
> must be issued one at a time. Within a step, the scripts hit independent
> endpoints and DO NOT depend on each other's live output — issue
> `check_robots.py`, `check_sitemap.py`, and `check_crawl_depth.py` (Step 1),
> or the per-page dual-identity fetches for several sampled pages, as parallel
> tool calls in the same turn rather than one after another; sequential
> network-bound calls are the main way an audit overruns 5 minutes on a
> slow-but-reachable site. Cap `sampled_pages` to the homepage plus at most 1-2
> other key pages for a standard run — each additional page repeats the
> dual-identity fetch and the engagement per-page checks. The network-bound
> scripts (`check_robots.py`, `check_sitemap.py`, `check_page_speed_signals.py`)
> each enforce their own internal wall-clock ceiling and return partial results
> with `fetch_deadline_exceeded` / `time_budget_exceeded: true` on a
> pathologically slow target rather than hanging — treat that as a finding
> ("this page/resource is too slow to reliably serve a crawler"), not as a
> signal to retry the same call.

### Step 1: Crawl Access Audit (`crawl-access-audit`)
Run specialized access scripts to evaluate bot accessibility:
- `scripts/check_robots.py`: Evaluate `robots.txt` for AI crawlers (`GPTBot`, `PerplexityBot`, `ClaudeBot`, `Google-Extended`, …) per RFC 9309 (longest match wins, wildcards honoured) against `/` and every audited page URL; reports the deciding rule per path and agent.
- `scripts/fetch_dual_identity.py`: Compare HTTP responses for User-Agent browser vs. AI bot identity.
- `scripts/check_sitemap.py`: Validate XML sitemap presence and reachability.
- `scripts/check_page_signals.py`: Inspect indexing meta tags (`noindex`, `nofollow`, canonicals).
- `scripts/check_crawl_depth.py`: Evaluate internal link structure and URL depth.

### Step 2: Crawl Render Audit (`crawl-render-audit`)
Run rendering barrier scripts:
- `scripts/check_rendering_barriers.py`: Compare initial raw HTML vs. rendered DOM text word counts.
- `scripts/check_structured_data_hydration.py`: Detect JSON-LD schema trapped behind client-side JS execution.
- `scripts/check_client_side_redirects.py`: Detect client-side JS and meta refresh redirects.

### Step 3: Readability Audit (`readability-audit`)
Run structural and semantic audit scripts:
- `scripts/check_structured_data.py`: Validate Schema.org JSON-LD completeness across 9 schema types.
- `scripts/check_semantic_structure.py`: Validate heading hierarchy (`<h1>`, `<h2>`) and outline structure.
- `scripts/check_nontext_facts.py`: Verify machine-readable alternatives for non-text facts.
- `scripts/check_content_consistency.py`: Detect contradiction between tabular markup and prose.

### Step 4: Freshness & Corroboration Audit (`freshness-corroboration`)
Run temporal and corroboration scripts:
- `scripts/check_content_dates.py`: Extract publication, modification, and copyright dates.
- `scripts/check_temporal_decay.py`: Detect post recency decay on blog/listing pages.
- `scripts/check_citation_consistency.py`: Corroborate on-site facts against external web search snippets.
- `scripts/check_entity_disambiguation.py`: Evaluate `sameAs` entity links (Wikidata, Wikipedia).

### Step 5: On-Site Engagement Audit (`engagement-audit`)
Run visitor orientation and engagement scripts:
- `scripts/check_navigation_reachability.py`: Audit 1-level homepage navigation reachability for key URLs.
- `scripts/check_content_depth.py`: Detect page intent, then assess content depth against advisory bands for content-bearing intents only; extract heading/paragraph text pairs.
- `scripts/check_mobile_responsive_signals.py`: Check `<meta viewport>` and inline media queries.
- `scripts/check_descriptor_consistency.py`: Audit cross-page brand phrase consistency in titles/H1s.
- `scripts/check_page_speed_signals.py`: Measure HTML byte size, CSS/JS resource bytes, and image counts.
- `scripts/check_landing_readiness.py`: Per sampled page, evaluate cold AI-referral entry — orientation (brand / description / `<h1>`), a forward action (CTA / nav / contact), hygiene (placeholder text, default `<title>`, dead links, mixed content), and reported friction signals.

### Step 6: Master Synthesis (`scripts/synthesize_report.py`)

Run `scripts/synthesize_report.py` to aggregate all sub-skill findings:

```bash
echo '{
  "site": "https://example.com",
  "skill_outputs": {
    "crawl_access": { ... },
    "crawl_render": { ... },
    "readability": { ... },
    "freshness_corroboration": { ... },
    "engagement": { ... }
  }
}' | python skills/audit-orchestrator/scripts/synthesize_report.py
```

The script extracts findings across all 5 skills, formats IDs (`F-001`, `F-002`), assigns severities (`critical`, `high`, `medium`, `low`), calculates per-category scores and the overall **Brand AI Readiness Score** (0.0 to 100.0), and outputs a structured JSON report.

---

## Output Schema

Produces the master audit report conforming to `references/audit_report_schema.json`:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-06T21:28:45Z",
  "brand_ai_readiness_score": 40.0,
  "category_scores": {
    "crawl_access": 80.0,
    "crawl_render": 90.0,
    "readability": 85.0,
    "freshness_corroboration": 95.0,
    "engagement": 85.0
  },
  "scoring_model": {
    "method": "weighted_with_foundational_gates",
    "weights": { "crawl_access": 0.30, "crawl_render": 0.25, "readability": 0.20, "engagement": 0.15, "freshness_corroboration": 0.10 },
    "weighted_subtotal": 85.8,
    "gates_applied": [
      { "category": "crawl_access", "cap": 40.0, "trigger_finding": "F-001", "confidence": 1.0, "reason": "critical 'crawl_access' finding caps overall readiness at 40.0" }
    ],
    "category_deduction_detail": {
      "crawl_access": { "critical": { "count": 1, "deducted": 20.0, "flat_equivalent": 20.0 } },
      "freshness_corroboration": { "low": { "count": 1, "deducted": 0.7, "flat_equivalent": 2.0 } }
    }
  },
  "summary": {
    "total_findings": 3,
    "critical": 1,
    "high": 0,
    "medium": 1,
    "low": 1
  },
  "findings": [
    {
      "id": "F-001",
      "category": "crawl_access",
      "title": "AI Crawler 'GPTBot' is completely blocked by robots.txt",
      "severity": "critical",
      "evidence": "robots.txt contains Disallow: / for User-agent: GPTBot.",
      "suggested_action": {
        "summary": "Update robots.txt to allow GPTBot access to public brand content.",
        "priority": "critical"
      },
      "confidence": 1.0
    }
  ],
  "proactive_recommendations": [
    "Ensure robots.txt allows access to AI crawler user-agents (GPTBot, PerplexityBot, ClaudeBot).",
    "Implement Server-Side Rendering (SSR) so raw HTML responses contain full text and JSON-LD schema.",
    "Add authoritative sameAs references (Wikidata, Wikipedia, LinkedIn) to Organization schema markup."
  ],
  "audit_metadata": {
    "audited_pages_count": 5,
    "skills_invoked_count": 5,
    "marketplace_version": "1.0.0"
  }
}
```

`audited_pages_count` counts distinct URLs found in `crawl_access.sampled_pages` and `engagement...key_content_reachability` (the two named containers that represent "pages this audit actually looked at" — a page fully sampled, or a key URL checked for nav reachability), wherever those containers are nested, plus each skill's own top-level `url`/`homepage_url`/`site` field. It deliberately does NOT sweep every dict with a `url`-shaped key anywhere in `skill_outputs` — that also picks up sitemap spot-checks (a single HEAD request, not full analysis) and raw on-page link lists (a URL merely noticed as an href target, never fetched), wildly overcounting. If you add a new per-page container to a sub-skill, name it (or register it) the same way rather than assuming a generic URL sweep will find it.

---

## Guardrails

> [!IMPORTANT]
> **Contract self-check**:
> `scripts/verify_contracts.py` cross-checks every output key `synthesize_report.py`
> reads against the keys the sub-skill scripts actually emit, and exits non-zero on
> drift. Run it after changing any sub-skill's output shape — a renamed field would
> otherwise silently disable the matching finding and make a broken site look clean.
> ```bash
> python skills/audit-orchestrator/scripts/verify_contracts.py
> ```
> `normalize_crawl_access()` and `pick()` in `synthesize_report.py` additionally
> absorb known shape/alias differences (`sampled_pages` vs flat `dual_identity`,
> `nontext_facts` vs `nontext_content`, `content_consistency` vs `context_consistency`,
> `sitemap_found` vs `exists`).

> [!IMPORTANT]
> **Deterministic Synthesis**:
> `synthesize_report.py` calculates per-category severity deductions deterministically from base weights (`critical`: -20.0, `high`: -10.0, `medium`: -5.0, `low`: -2.0), capped to 0.0-100.0. Two refinements on top of the flat model:
> - **Diminishing returns per severity, per category.** Repeated findings of the SAME severity in one category are usually one underlying gap surfacing more than once (11 missing `<img alt>` is one root cause, not 11 independent failures) — under a flat model, quantity alone could crush a category out of proportion to severity (6 "low" findings used to outscore a single "high"). Now each additional same-severity finding counts for less (`DEDUCTION_DECAY = 0.6` geometric decay; the single MOST CONFIDENT finding of a severity is always charged first, so which one "goes first" reflects certainty, not generation order); different severities still stack fully additively, and damage from repetition alone is bounded (asymptote = base weight / (1 - decay)).
> - **Confidence-weighted deductions.** A finding may carry `confidence` in [0, 1] — how sure the check is the finding is real, distinct from severity (how bad it'd be if true). Missing/invalid confidence defaults to 1.0 (full weight, matching every finding that predates this field). A handful of already-uncertain finding types set it explicitly: a temporal-decay signal with `detection_confidence: "low"` (often a stray year mention, not a real post date), a structured-data-vs-visible-text mismatch not confirmed by agent judgment (only the raw string-match heuristic), and a name-ambiguity flag not confirmed by agent judgment. A critical finding's confidence also **softens (not just triggers) its foundational gate** — a fully-confident critical (the default) still slams to the hard cap exactly as before, but one the check itself isn't fully sure of pulls the cap back toward the uncapped weighted score instead of always applying the harshest penalty for a maybe.
> - The overall **Brand AI Readiness Score** is still a *prerequisite-weighted* mean of the category scores — `crawl_access` 0.30, `crawl_render` 0.25, `readability` 0.20, `engagement` 0.15, `freshness_corroboration` 0.10 (freshness lowest because it is the only non-deterministic, web-search category) — **plus foundational gates**: a single `critical` finding in `crawl_access` caps the overall score at 40, and in `crawl_render` at 55 (subject to the confidence-softening above), because an uncrawlable or unreadable site is not "80% AI-ready" no matter how clean the other categories look. The exact weights, any gates that fired, and a per-category `category_deduction_detail` breakdown (count / decayed total / what a flat model would have charged, per severity) are emitted in the report's `scoring_model` object. All findings are renumbered sequentially (`F-001`, `F-002`, ...) after assembly, so caller-supplied explicit findings that carry their own ids cannot leave gaps in the sequence; every id matches `^F-[0-9]{3,}$`.
