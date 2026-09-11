
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
from datetime import datetime, timezone

SEVERITY_DEDUCTION = {"critical": 20.0, "high": 10.0, "medium": 5.0, "low": 2.0}

# Repeated findings of the SAME severity in one category are usually the same
# underlying gap surfacing more than once (11 missing <img alt> is one root
# cause -- a missing accessibility pass -- not 11 independent failures), so a
# flat "-N per finding" let sheer quantity crush a category out of proportion
# to severity: 6 "low" findings (-12) used to outscore a single "high" (-10),
# inverting the intended ordering. Each additional finding of the SAME
# severity in the SAME category now counts for less (geometric decay),
# bounding how much repetition alone can do -- asymptote per severity tier is
# SEVERITY_DEDUCTION[sev] / (1 - DEDUCTION_DECAY) -- while the single most
# confident finding of that severity still costs its full, undiminished
# weight, and different severities still stack additively (a critical AND a
# high in the same category both still count in full). See
# calculate_category_score.
DEDUCTION_DECAY = 0.6

# Prerequisite-weighted rollup. Discoverability is sequential: a page must be
# crawlable before render matters, readable before facts can be extracted, and
# so on (handout appendix A). Weights reflect that dependency order; they sum
# to 1.0. Freshness/corroboration is lowest-weighted because it is the only
# non-deterministic, web-search-dependent category.
CATEGORY_WEIGHTS = {
    "crawl_access":            0.30,
    "crawl_render":            0.25,
    "readability":             0.20,
    "engagement":              0.15,
    "freshness_corroboration": 0.10,
}

# A critical failure in a foundational category caps the overall score no
# matter how clean the downstream categories look -- an uncrawlable or
# unreadable site is not "80% AI-ready".
FOUNDATIONAL_GATES = {
    "crawl_access": 40.0,
    "crawl_render": 55.0,
}


def _finding_confidence(f):
    """A finding may declare `confidence` in [0, 1] when the check itself is
    uncertain (a year-only date guess, a string-match heuristic no agent
    confirmed, a moderate rather than elevated ambiguity signal). Missing or
    invalid confidence defaults to 1.0 -- full weight, matching every finding
    that predates this field and every finding a script/agent is fully sure
    of. This is NOT the same as severity: severity says how bad the thing
    would be if true; confidence says how sure we are it's actually true."""
    c = f.get("confidence", 1.0)
    try:
        return max(0.0, min(1.0, float(c)))
    except (TypeError, ValueError):
        return 1.0


def _category_deductions(findings, category_name):
    """Returns (final_score, breakdown) where breakdown lists, per severity
    present, the hit count, the confidence-weighted+decayed total deducted,
    and the undiminished total a flat model would have charged (for
    transparency: the gap between the two IS the diminishing-returns effect).
    The single most-confident finding of a severity is always charged first
    (least decayed), so which finding "goes first" reflects certainty, not
    the arbitrary order findings happened to be generated in."""
    by_severity = {}
    for f in findings:
        if f.get("category") == category_name:
            sev = str(f.get("severity", "medium")).lower()
            by_severity.setdefault(sev, []).append(_finding_confidence(f))

    base_score = 100.0
    breakdown = {}
    for sev, confidences in by_severity.items():
        per_hit = SEVERITY_DEDUCTION.get(sev, 5.0)
        ordered = sorted(confidences, reverse=True)
        decayed_total = sum(per_hit * (DEDUCTION_DECAY ** i) * c for i, c in enumerate(ordered))
        base_score -= decayed_total
        breakdown[sev] = {
            "count": len(ordered),
            "deducted": round(decayed_total, 2),
            "flat_equivalent": round(per_hit * sum(ordered), 2),
        }
    return max(0.0, min(100.0, round(base_score, 1))), breakdown


def calculate_category_score(findings, category_name):
    score, _ = _category_deductions(findings, category_name)
    return score


def calculate_overall_readiness_score(category_scores, findings=None):
    """Returns (overall_score, scoring_model dict). Weighted mean over the
    categories actually present, then clamped down by any foundational gate a
    critical finding trips."""
    findings = findings or []
    deduction_detail = {cat: _category_deductions(findings, cat)[1]
                        for cat in category_scores}

    if not category_scores:
        return 100.0, {
            "method": "weighted_with_foundational_gates",
            "weights": CATEGORY_WEIGHTS,
            "weighted_subtotal": 100.0,
            "gates_applied": [],
            "category_deduction_detail": {},
        }

    total_w = sum(CATEGORY_WEIGHTS.get(c, 0.0) for c in category_scores)
    if total_w <= 0:
        weighted = sum(category_scores.values()) / len(category_scores)
    else:
        weighted = sum(category_scores[c] * CATEGORY_WEIGHTS.get(c, 0.0)
                       for c in category_scores) / total_w
    weighted = max(0.0, min(100.0, round(weighted, 1)))

    gates_applied = []
    capped = weighted
    for f in findings:
        if str(f.get("severity", "")).lower() != "critical":
            continue
        cat = f.get("category")
        if cat in FOUNDATIONAL_GATES and weighted > FOUNDATIONAL_GATES[cat]:
            base_cap = FOUNDATIONAL_GATES[cat]
            confidence = _finding_confidence(f)
            # A critical finding this check is fully sure of (confidence 1.0,
            # the default and the only value any pre-existing critical
            # finding ever set) still slams to the harsh cap exactly as
            # before. One it's NOT fully sure of softens the cap toward the
            # uncapped weighted score instead of always applying the harshest
            # possible penalty for a maybe.
            cap = base_cap + (weighted - base_cap) * (1.0 - confidence)
            capped = min(capped, cap)
            gates_applied.append({
                "category": cat, "cap": round(cap, 1),
                "trigger_finding": f.get("id"),
                "confidence": confidence,
                "reason": (f"critical '{cat}' finding caps overall readiness at {round(cap, 1)}"
                          + ("" if confidence >= 1.0 else
                             f" (softened from {base_cap} at confidence {confidence})")),
            })

    overall = max(0.0, min(100.0, round(capped, 1)))
    return overall, {
        "method": "weighted_with_foundational_gates",
        "weights": CATEGORY_WEIGHTS,
        "weighted_subtotal": weighted,
        "gates_applied": gates_applied,
        "category_deduction_detail": deduction_detail,
    }

# Names of CONTAINERS that hold pages/URLs an audit step substantively
# looked at (matched by name, not by a fixed path -- crawl-access-audit's
# documented `sampled_pages` list can appear nested at any depth depending on
# how the caller structured skill_outputs, and the original path-based lookup
# only checked one exact location and missed it). Each maps to the key that
# names the URL within its items.
#
# Deliberately narrow: a blanket "any dict key named 'url' anywhere in the
# tree" sweep was tried and rejected -- it also pulls in sitemap spot-check
# URLs (single HEAD request, not full content analysis) and raw on-page link
# lists (a URL merely noticed as an href target, never fetched at all),
# wildly overcounting. Only these two named, documented containers represent
# "this URL had the audit pipeline's checks run against it."
AUDITED_URL_CONTAINERS = {
    "sampled_pages": "url",
    "key_content_reachability": "key_content_url",
}
def _find_named_containers(node, container_urls, _depth=0):
    """Depth-agnostic search for keys named in AUDITED_URL_CONTAINERS. Only
    acts on a container found BY NAME; it does not otherwise inspect or
    collect from arbitrary nested dicts/lists (that blanket-sweep approach
    was tried and rejected -- see the comment above -- so this must not
    accidentally reintroduce it while walking past unrelated structures)."""
    if _depth > 15:          # guard against runaway/cyclic structures
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k in AUDITED_URL_CONTAINERS and isinstance(v, list):
                url_key = AUDITED_URL_CONTAINERS[k]
                for item in v:
                    if isinstance(item, dict):
                        val = item.get(url_key)
                        if isinstance(val, str) and val.strip():
                            container_urls.add(val.strip())
                continue    # this list's contents are page/URL records, not more containers to search
            if isinstance(v, (dict, list)):
                _find_named_containers(v, container_urls, _depth + 1)
    elif isinstance(node, list):
        for item in node:
            _find_named_containers(item, container_urls, _depth + 1)


def extract_audited_urls(site_url, skill_outputs):
    urls = set()
    if site_url:
        urls.add(site_url)

    for skill_name, data in skill_outputs.items():
        if not isinstance(data, dict):
            continue
        # Direct URL keys, and the legacy flat "pages" list -- both only at
        # this skill's own top level, matching what callers actually emit
        # there (a nested dict elsewhere with an incidental "url" key -- a
        # JSON-LD ImageObject, an on-page link, a sitemap spot-check entry --
        # is not "a page this audit substantively analyzed").
        for key in ("url", "homepage_url", "site"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                urls.add(val.strip())
        pages = data.get("pages")
        if isinstance(pages, list):
            for p in pages:
                if isinstance(p, dict) and isinstance(p.get("url"), str):
                    urls.add(p["url"].strip())

    _find_named_containers(skill_outputs, urls)
    return max(1, len(urls))

def pick(d, *names, default=None):
    """First present key among `names` (tolerates documented-vs-implemented
    container/field name differences across skills)."""
    if not isinstance(d, dict):
        return default
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def robot_blocks(robots):
    """Return (root_blocked_agents, {path: [agents]} for non-root blocks, rules).

    Accepts the current check_robots.py shape ({path: {agent: bool}} with
    root_blocked_agents / blocked_paths_by_agent / matched_rules) and the legacy
    {agent: [disallowed paths]} shape. Query-string-only blocks are excluded:
    blocking `/page?utm=...` while `/page` stays open is duplicate-URL hygiene."""
    if not isinstance(robots, dict):
        return [], {}, {}
    rules = robots.get("matched_rules") or {}
    dis = robots.get("disallowed") or {}
    root, paths = [], {}

    if "root_blocked_agents" in robots or "blocked_paths_by_agent" in robots:
        root = list(robots.get("root_blocked_agents") or [])
        for agent, plist in (robots.get("blocked_paths_by_agent") or {}).items():
            if agent in root:
                continue
            for p in plist:
                paths.setdefault(p, []).append(agent)
        return root, paths, rules

    for key, val in dis.items():
        if isinstance(val, dict):                     # {path: {agent: bool}}
            for agent, blocked in val.items():
                if blocked is not True:
                    continue
                if rules.get(key, {}).get(agent, {}).get("query_variant_only"):
                    continue
                if key == "/":
                    if agent not in root:
                        root.append(agent)
                else:
                    paths.setdefault(key, []).append(agent)
        elif isinstance(val, list):                   # legacy {agent: [paths]}
            if "/" in val:
                root.append(key)
            for p in val:
                if p != "/":
                    paths.setdefault(p, []).append(key)
    paths = {p: [a for a in ags if a not in root] for p, ags in paths.items()}
    return root, {p: a for p, a in paths.items() if a}, rules


def normalize_crawl_access(access):
    """Accept either the `sampled_pages: [{url, browser_fetch, bot_fetch}]`
    shape documented in crawl-access-audit/SKILL.md, or a flat
    `dual_identity` / `page_signals` shape, and return a dict that always
    exposes both `dual_identity` and `page_signals` for the finding logic.

    Page selection: the first sampled page whose signals show a problem wins,
    so a noindex or a bot block anywhere in the sample is not masked by a
    clean first page."""
    if not isinstance(access, dict):
        return {}
    out = dict(access)
    pages = access.get("sampled_pages")
    if not isinstance(pages, list) or not pages:
        return out

    dual_candidates, sig_candidates = [], []
    for p in pages:
        if not isinstance(p, dict):
            continue
        url = p.get("url")
        bf = p.get("browser_fetch") or {}
        bot = p.get("bot_fetch") or {}
        # A page entry may itself already be a dual_fetch result.
        if "bot_blocked" in p or "comparison_metrics" in p:
            dual_candidates.append(p)
        elif bf or bot:
            br_fp = bf.get("content_fingerprints", {}) or {}
            bot_fp = bot.get("content_fingerprints", {}) or {}
            divergence = any(br_fp.get(k) != bot_fp.get(k) for k in
                             ("cloudflare_challenge", "captcha", "generic_block",
                              "login_wall", "thin_content"))
            dual_candidates.append({
                "url": url,
                "browser_status": bf.get("status"),
                "bot_status": bot.get("status"),
                "bot_blocked": bot.get("status") in (401, 403) or bot_fp.get("generic_block", False),
                "bot_challenged": (
                    (bot_fp.get("cloudflare_challenge") and not br_fp.get("cloudflare_challenge"))
                    or (bot_fp.get("captcha") and not br_fp.get("captcha"))
                ),
                "rate_limited": 429 in (bf.get("status"), bot.get("status")),
                "browser_fetch": bf, "bot_fetch": bot,
                "comparison_metrics": {"fingerprint_divergence": divergence},
            })
        for fetch in (bot, bf):
            sig = fetch.get("page_signals") if isinstance(fetch, dict) else None
            if isinstance(sig, dict):
                sig.setdefault("url", url)
                sig_candidates.append(sig)
        if isinstance(p.get("page_signals"), dict):
            s = dict(p["page_signals"]); s.setdefault("url", url)
            sig_candidates.append(s)

    if "dual_identity" not in out and dual_candidates:
        out["dual_identity"] = next(
            (d for d in dual_candidates
             if d.get("bot_blocked") or d.get("bot_challenged") or d.get("rate_limited")),
            dual_candidates[0])
    if "page_signals" not in out and sig_candidates:
        out["page_signals"] = next(
            (s for s in sig_candidates
             if pick(s, "is_noindex", "noindex_meta") or pick(s, "is_nofollow", "nofollow_meta")),
            sig_candidates[0])
    return out


def add_finding(findings, category, title, severity, evidence, suggested_summary, priority=None,
                explanation=None, plain_english=None, confidence=1.0):
    if priority is None:
        priority = severity
    finding_id = f"F-{len(findings)+1:03d}"
    full_evidence = evidence
    summary_text = explanation or plain_english
    if summary_text:
        full_evidence = f"{evidence} What This Means: {summary_text}"
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 1.0
    findings.append({
        "id": finding_id,
        "category": category,
        "title": title,
        "severity": severity.lower(),
        "evidence": full_evidence,
        "suggested_action": {
            "summary": suggested_summary,
            "priority": priority.lower()
        },
        # How sure this specific finding is, in [0, 1] -- distinct from
        # severity (how bad it would be if true). Scales its scoring weight;
        # see _finding_confidence / calculate_category_score. Defaults to
        # 1.0 (full weight) for the vast majority of findings that are
        # deterministic facts, not heuristic guesses.
        "confidence": confidence,
    })

def synthesize_report(site_url, skill_outputs=None, explicit_findings=None, proactive_recommendations=None):
    if skill_outputs is None:
        skill_outputs = {}
    if explicit_findings is None:
        explicit_findings = []
    if proactive_recommendations is None:
        proactive_recommendations = []

    findings = list(explicit_findings)

    # 1. Crawl Access Skill Findings
    access = skill_outputs.get("crawl_access", {})
    if access:
        # `crawl-access-audit` documents its output as a `sampled_pages` list of
        # browser/bot fetch pairs. Normalise that (and the flat single-page
        # shape) into the `dual_identity` / `page_signals` views used below, so
        # either shape the orchestrator is handed works.
        access = normalize_crawl_access(access)
        robots = access.get("robots", {})
        if robots.get("malformed"):
            add_finding(
                findings, "crawl_access",
                "Malformed robots.txt returning HTML instead of plain text",
                "critical",
                f"URL {robots.get('resolved_url')} returned HTML content instead of plain text directives.",
                "Serve robots.txt with text/plain Content-Type and valid directives.",
                plain_english="AI search engine crawlers cannot read your site's access rules because the robots.txt file returned a web page layout instead of plain text instructions."
            )
        # check_robots.py emits `disallowed` as {path: {agent: bool}} plus the
        # rolled-up `root_blocked_agents` / `blocked_paths_by_agent`. Older
        # output used {agent: [paths]}; normalise both so this can never again
        # silently read nothing.
        root_blocked, path_blocks, rules = robot_blocks(robots)
        if root_blocked:
            ev_rules = "; ".join(
                f"{a}: '{rules.get('/', {}).get(a, {}).get('rule') or 'Disallow: /'}'"
                f" (group '{rules.get('/', {}).get(a, {}).get('group') or '?'}')"
                for a in root_blocked)
            add_finding(
                findings, "crawl_access",
                f"AI Crawler{'s' if len(root_blocked) > 1 else ''} Blocked From the Site Root by robots.txt "
                f"({', '.join(root_blocked)})",
                "critical",
                f"robots.txt disallows the homepage (/) for {root_blocked}. Matching rules: {ev_rules}.",
                f"Update robots.txt so {', '.join(root_blocked)} may fetch public brand content; keep "
                f"disallow rules scoped to genuinely private paths.",
                plain_english="Your robots.txt tells these AI crawlers not to read your homepage, so they "
                "cannot read or cite the site."
            )
        if path_blocks:
            lines = []
            for path, agents in path_blocks.items():
                # Group agents by the (rule, group) that decided them, so an agent
                # with its own robots group is not reported under another's rule.
                by_rule = {}
                for a in agents:
                    rinfo = rules.get(path, {}).get(a, {})
                    by_rule.setdefault((rinfo.get("rule"), rinfo.get("group")), []).append(a)
                parts = [f"{', '.join(ags)} via '{rule}' in group '{group}'"
                         for (rule, group), ags in by_rule.items()]
                lines.append(f"{path} -> " + "; ".join(parts))
            add_finding(
                findings, "crawl_access",
                "Key Pages Disallowed for AI Crawlers in robots.txt",
                "high",
                "robots.txt disallows the following audited paths while the site root stays open: "
                + "; ".join(lines) + ".",
                "Confirm whether these paths should be visible to AI assistants. If yes, narrow or remove "
                "the disallow rules for the AI user-agent groups. If the exclusion is intentional, make sure "
                "the same content is published on a crawlable URL so assistants can still cite it.",
                plain_english="Your robots.txt tells AI crawlers not to read these specific pages, so "
                "assistants cannot use or cite what is on them."
            )

        dual = access.get("dual_identity", {})
        comparison = dual.get("comparison_metrics", {})
        fingerprint_diverged = comparison.get("fingerprint_divergence", False)
        browser_status = dual.get("browser_status")
        bot_status = dual.get("bot_status")
        browser_ok = isinstance(browser_status, int) and 200 <= browser_status < 300
        if dual.get("bot_blocked") or (dual.get("bot_challenged") and fingerprint_diverged):
            # The two fingerprints diverging does not imply the browser identity
            # succeeded -- a WAF can also block a plain browser-UA fetch (e.g. an
            # interactive JS challenge) while giving the bot identity a harder,
            # differently-shaped block (e.g. a static deny with no challenge at
            # all). Word the evidence for whichever actually happened.
            if browser_ok:
                evidence = (f"Browser status {browser_status} succeeded while AI Bot status {bot_status} "
                           f"was blocked/challenged with diverging fingerprints.")
                plain = ("Your web security firewall (e.g. Cloudflare) lets human web browsers view the "
                        "site normally, but blocks automated AI crawlers when they attempt to read your content.")
            else:
                evidence = (f"Neither identity retrieved real content (Browser status {browser_status}, "
                           f"AI Bot status {bot_status}), but their response fingerprints diverge -- the AI "
                           f"Bot identity hits a distinct, harder block than the browser identity (e.g. a "
                           f"static WAF deny vs. an interactive challenge), so fixing whatever blocks the "
                           f"browser identity would not by itself restore AI crawler access.")
                plain = ("Your website blocks both regular browser-style requests and AI crawlers, but by "
                        "different mechanisms -- the AI crawler hits a harder, bot-specific block underneath "
                        "the browser-facing one.")
            add_finding(
                findings, "crawl_access",
                "AI Bot Identity HTTP Fetch Blocked or Challenged",
                "critical",
                evidence,
                "Remove Cloudflare/WAF challenge rules targeting AI bot User-Agents.",
                plain_english=plain
            )
        elif dual.get("bot_challenged") and not fingerprint_diverged:
            add_finding(
                findings, "crawl_access",
                "CAPTCHA/Challenge Script Present on Page (Shared — Not Bot-Specific)",
                "low",
                f"A CAPTCHA or challenge script was detected on the page (Browser: {dual.get('browser_status')}, Bot: {dual.get('bot_status')}), but both browser and bot fingerprints show the same signal — indicating a site-wide challenge (e.g. contact-form reCAPTCHA), not a bot-specific block.",
                "No action required for shared CAPTCHA signals. If you intentionally serve a CAPTCHA to all visitors, this is expected behavior.",
                plain_english="A CAPTCHA or challenge script exists on the page, but it affects all visitors equally (including regular browsers), not just AI crawlers. This is informational only and does not indicate bot blocking."
            )
        elif dual.get("rate_limited") or dual.get("bot_status") == 429 or dual.get("browser_status") == 429:
            add_finding(
                findings, "crawl_access",
                "Auditor Request Rate Limiting Encountered (HTTP 429)",
                "low",
                f"Server returned HTTP 429 Too Many Requests during rapid audit fetches (Browser: {dual.get('browser_status')}, Bot: {dual.get('bot_status')}).",
                "Review server load balancer rate-limiting thresholds to ensure legitimate automated crawlers are not throttled during burst visits.",
                plain_english="Your website server returned a 'Too Many Requests' (HTTP 429) rate limit warning when auditor requests were sent in rapid succession. This is temporary traffic throttling by your load balancer, not a permanent bot block."
            )

        page_sig = access.get("page_signals", {}) or {}
        noindex = pick(page_sig, "is_noindex", "noindex_meta", default=False) or \
            page_sig.get("noindex_header", False)
        nofollow = pick(page_sig, "is_nofollow", "nofollow_meta", default=False) or \
            page_sig.get("nofollow_header", False)
        src = ("X-Robots-Tag header" if page_sig.get("noindex_header") or page_sig.get("nofollow_header")
               else "robots meta tag")
        if noindex:
            add_finding(
                findings, "crawl_access",
                "Page carries a noindex directive",
                "critical",
                f"Page {page_sig.get('url')} is marked noindex via {src}"
                f"{' (directives: ' + str(page_sig.get('robots_directives_seen')) + ')' if page_sig.get('robots_directives_seen') else ''}.",
                "Remove the noindex directive from public brand content pages (both the robots meta tag and any X-Robots-Tag response header).",
                plain_english="Your page contains a directive that instructs search engines and AI assistants to completely omit this page from results — it is the single most damaging discoverability defect."
            )
        elif nofollow:
            add_finding(
                findings, "crawl_access",
                "Page carries a nofollow directive",
                "medium",
                f"Page {page_sig.get('url')} is marked nofollow via {src}.",
                "Remove the nofollow directive so AI crawlers can follow internal links and discover child pages.",
                plain_english="Your page tells crawlers not to follow its links, preventing AI engines from discovering the rest of your site from here."
            )
        if page_sig.get("duplicate_canonical_tags"):
            add_finding(
                findings, "crawl_access",
                "Multiple Conflicting rel=canonical Tags on One Page",
                "medium",
                f"Page {page_sig.get('url')} declares {page_sig.get('canonical_tag_count')} rel=canonical links; "
                f"crawlers may ignore all of them and pick their own canonical.",
                "Emit exactly one rel=canonical link per page.",
                plain_english="Your page declares more than one 'official version' link, so search and AI crawlers may disregard the signal entirely."
            )

        sitemap = access.get("sitemap", {}) or {}

        # Conventional-path soft-200: /sitemap.xml answers 2xx with a body that
        # is not a sitemap (SPA catch-all routing). A 404 there is CORRECT when
        # robots.txt declares the sitemap elsewhere and is never reported.
        conv = sitemap.get("conventional_path_check") or {}
        if conv.get("checked") and conv.get("soft_200"):
            add_finding(
                findings, "crawl_access",
                "Conventional /sitemap.xml Returns 2xx With Non-Sitemap Content",
                "low",
                f"{conv.get('url')} responded HTTP {conv.get('http_status')} but the body does not parse "
                f"as a sitemap ({conv.get('error')}). The valid sitemap is declared in robots.txt at a "
                f"different location. A crawler probing the conventional path receives a page rather than "
                f"a sitemap or a clean 404 -- the same catch-all routing usually also returns 2xx for "
                f"genuinely missing URLs.",
                "Serve the sitemap at /sitemap.xml as well, or return a real 404 there. Keep the robots.txt "
                "Sitemap: directive either way. Check that unmatched routes return 404 rather than 200.",
                plain_english="Asking your site for its sitemap at the standard address returns a web page "
                "instead of a sitemap or a proper 'not found'. Crawlers that check the standard address get "
                "nothing useful, and the same routing behaviour usually means broken URLs also answer 'OK'."
            )

        sitemap_found = pick(sitemap, "sitemap_found", "exists")
        if sitemap_found is False:
            add_finding(
                findings, "crawl_access",
                "Missing or Unreachable XML Sitemap",
                "high",
                f"No valid sitemap found at /sitemap.xml or declared in robots.txt"
                f"{' (' + str(sitemap.get('error')) + ')' if sitemap.get('error') else ''}.",
                "Generate and submit a clean XML sitemap at /sitemap.xml and declare it in robots.txt.",
                plain_english="AI search crawlers do not have a master site directory to easily discover and map all important public pages on your website."
            )

        depth = access.get("crawl_depth", {})
        if depth.get("is_deep_url"):
            add_finding(
                findings, "crawl_access",
                "Excessive URL Folder Depth Detected (Crawl Depth Friction)",
                "low",
                f"Page URL {depth.get('url')} is {depth.get('url_depth')} folder levels deep.",
                "Flatten directory structures so core content URLs are within 2-3 levels of the root domain.",
                plain_english="The page URL is buried deep inside nested subfolders, reducing how frequently search bots crawl and update it."
            )

    # 2. Crawl Render Skill Findings
    render = skill_outputs.get("crawl_render", {})
    if render:
        barriers    = render.get("rendering_barriers", {})
        sd_hydr_raw = render.get("structured_data_hydration", {})
        sd_hydr     = sd_hydr_raw.get("hydration_analysis", {})
        js_redirect = render.get("client_side_redirects", {})

        csr_signals     = barriers.get("client_side_rendering_signals", {})
        waf_info        = barriers.get("waf_interstitial", {})
        hydration_gaps  = barriers.get("hydration_gaps", {})
        word_counts     = barriers.get("word_counts", {})

        # --- F2: WAF interstitial page ---
        if waf_info.get("waf_challenge_detected"):
            waf_sigs = waf_info.get("waf_signals", [])
            add_finding(
                findings, "crawl_render",
                "WAF/Bot-Challenge Interstitial Page Detected (Content Hidden Behind JS Wall)",
                "critical",
                f"Server returned a JavaScript-based browser verification challenge page instead of real content. WAF signals: {waf_sigs}.",
                "Configure your WAF (Cloudflare, Datadome, Akamai) to allow verified AI crawler User-Agents (GPTBot, ClaudeBot, PerplexityBot) without challenge pages.",
                plain_english="Your web security firewall is returning a 'Just a moment' or browser challenge page to AI crawlers instead of your actual website content. AI search engines cannot read content that is locked behind a JavaScript challenge."
            )

        # --- F15 Cross-script correlation: CSR barrier confirmed by BOTH scripts ---
        csr_barrier_rendering = csr_signals.get("likely_client_side_rendering_barrier", False)
        csr_barrier_schema    = sd_hydr.get("structured_data_hydration_barrier_detected")  # may be None

        if csr_barrier_rendering and csr_barrier_schema:
            # Both scripts agree: high-confidence CSR barrier
            trapped        = sd_hydr.get("js_trapped_schema_types", [])
            eff_raw        = word_counts.get("effective_raw_words", "?")
            mounts         = csr_signals.get("spa_mount_points", [])
            frameworks     = csr_signals.get("detected_frameworks", [])
            add_finding(
                findings, "crawl_render",
                "Confirmed Client-Side Rendering Barrier: Content and Schema Both JS-Only",
                "high",
                f"Both content words ({eff_raw} effective raw words) and schema data (JS-trapped types: {trapped}) are loaded exclusively via JavaScript. SPA mount points: {mounts}. Frameworks: {frameworks}.",
                "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG). Embed JSON-LD directly in the static HTML response.",
                plain_english="AI crawlers that read raw HTML see an empty page shell. Both your main content and your structured schema data are loaded by JavaScript after page load, making them completely invisible to non-JS AI search crawlers."
            )
        elif csr_barrier_rendering and not csr_barrier_schema:
            # Rendering barrier confirmed; schema either OK or unknown
            eff_raw    = word_counts.get("effective_raw_words", "?")
            hydro      = word_counts.get("hydration_ratio")
            thin_flag  = hydration_gaps.get("thin_initial_content_detected", False)
            skeleton   = hydration_gaps.get("skeleton_screen_detected", False)
            mounts     = csr_signals.get("spa_mount_points", [])
            frameworks = csr_signals.get("detected_frameworks", [])
            inline_sig = csr_signals.get("inline_framework_signals", [])

            # Build a rich evidence string from all available signals
            # The script now enumerates exactly which signals fired; prefer
            # those over re-deriving evidence from individual fields.
            evidence_parts = list(csr_signals.get("barrier_reasons") or [])
            if not evidence_parts:
                # older script output without barrier_reasons -- derive it
                if thin_flag and hydro is not None:
                    evidence_parts.append(f"Hydration ratio {hydro} (below threshold)")
                if thin_flag and hydro is None:
                    evidence_parts.append(f"Only {eff_raw} effective words in raw HTML content area")
                if mounts:
                    evidence_parts.append(f"SPA mount points detected: {mounts}")
                if frameworks:
                    evidence_parts.append(f"JS frameworks: {frameworks}")
                if inline_sig:
                    evidence_parts.append(f"Inline bootstrap code: {inline_sig}")
                if skeleton:
                    evidence_parts.append("Skeleton/shimmer loader UI detected")

            evidence_str = ". ".join(evidence_parts) or f"CSR signals present: {csr_signals}"

            add_finding(
                findings, "crawl_render",
                "Client-Side Rendering Barrier Detected (SPA / JS-Dependent Content)",
                "high",
                evidence_str + ".",
                "Implement Server-Side Rendering (SSR) or Static Site Generation (SSG) for core content pages.",
                plain_english="Most of your page content is loaded dynamically via JavaScript after the initial page load. AI crawlers that read raw HTML will see very little or no content — they need SSR or SSG to access your information."
            )

        # --- F3: Skeleton screen (standalone, when no full CSR barrier already filed) ---
        if not csr_barrier_rendering and hydration_gaps.get("skeleton_screen_detected"):
            add_finding(
                findings, "crawl_render",
                "Skeleton/Shimmer Loader UI Detected in Initial HTML",
                "medium",
                "Initial HTML contains repeated placeholder heading structures with very low prose density, indicative of a skeleton or shimmer loading screen rather than real content.",
                "Ensure core page content is server-rendered in the initial HTML response rather than loaded via a skeleton placeholder pattern.",
                plain_english="Your initial page HTML appears to contain a loading placeholder (skeleton screen) rather than real content. AI crawlers reading raw HTML will find empty scaffolding instead of actual text."
            )

        # --- Structured data hydration barrier (standalone, when no composite already filed) ---
        if not (csr_barrier_rendering and csr_barrier_schema) and csr_barrier_schema:
            trapped = sd_hydr.get("js_trapped_schema_types", [])
            add_finding(
                findings, "crawl_render",
                "Structured Data JSON-LD Trapped Behind JS Execution",
                "high",
                f"Schema entities {trapped} are injected dynamically via JS and invisible to raw HTML scrapers.",
                "Inject JSON-LD script blocks directly into static raw HTML responses.",
                plain_english="Structured machine-readable data is inserted via JavaScript after page load, making it invisible to AI agents that only read raw HTML."
            )

        # --- Meta-refresh / JS hard redirect ---
        if js_redirect.get("client_side_redirect_detected"):
            meta_targets  = js_redirect.get("meta_http_equiv_refreshes", [])
            js_targets    = js_redirect.get("js_location_redirects", [])
            all_targets   = (meta_targets + js_targets)[:3]
            add_finding(
                findings, "crawl_render",
                "Client-side JavaScript or Meta Refresh Hard Redirect Detected",
                "medium",
                f"Page performs client-side redirect(s). Targets: {all_targets}.",
                "Replace client-side redirects with HTTP 301/302 server redirects.",
                plain_english="The webpage redirects users using browser scripts instead of standard server codes, which can confuse AI crawlers trying to reach the destination page."
            )

        # --- SPA routing informational (Flaw 14 — soft signal) ---
        if js_redirect.get("spa_client_routing_detected") and not csr_barrier_rendering:
            sigs = js_redirect.get("spa_client_routing_signals", [])
            add_finding(
                findings, "crawl_render",
                "SPA Client-Side Navigation Routing Detected",
                "low",
                f"Page scripts contain SPA navigation API calls ({sigs[:3]}), indicating a client-side routing architecture. Without CSR barriers, this may be acceptable.",
                "Ensure all navigable routes are also accessible as server-rendered HTML pages for AI crawlers.",
                plain_english="Your page uses JavaScript-based navigation (SPA routing). This is informational — if your server also returns full HTML for each route, AI crawlers can still access content."
            )

    # 3. Readability Skill Findings
    readability = skill_outputs.get("readability", {})
    if readability:
        struct_data = readability.get("structured_data", {})
        if struct_data and struct_data.get("recognized_entities_count", 0) == 0:
            add_finding(
                findings, "readability",
                "Missing Schema.org JSON-LD Structured Data",
                "high",
                "Zero recognized Schema.org entities detected on target page.",
                "Add Schema.org JSON-LD markup matching page entity (Organization, Product, Article, etc.).",
                plain_english="Your page lacks standardized machine-readable data (Schema.org JSON-LD), which acts like a digital business card telling AI search engines exactly what your brand, product, or organization represents."
            )

        semantic = readability.get("semantic_structure", {}) or {}
        headings_blk = semantic.get("headings", {}) or {}
        h1_missing = semantic.get("h1_missing")
        if h1_missing is None:
            h1_missing = headings_blk.get("h1_count", 1) == 0
        hierarchy_issues = pick(semantic, "heading_hierarchy_issues", default=None)
        if hierarchy_issues is None:
            hierarchy_issues = headings_blk.get("skipped_levels", [])
        if h1_missing:
            # Distinguish "never written" from "written, but injected by JS".
            # If sub-headings are present without an h1, or the render skill
            # flagged a barrier on this page, the h1 almost certainly exists in
            # the rendered DOM and is simply absent from the server response --
            # so the fix is to server-render it, not to author one.
            subs_present = semantic.get("h1_missing_but_subheadings_present")
            render_gap = bool(
                (skill_outputs.get("crawl_render", {}) or {})
                .get("rendering_barriers", {})
                .get("client_side_rendering_signals", {})
                .get("likely_client_side_rendering_barrier")
            )
            levels = semantic.get("subheading_levels_present") or []
            if subs_present or render_gap:
                add_finding(
                    findings, "readability",
                    "Primary <h1> Absent from the Server-Rendered HTML (client-injected)",
                    "medium",
                    f"The raw HTML response contains no <h1>"
                    f"{f', although sub-headings {levels} are server-rendered' if subs_present else ''}"
                    f"{'; this page also shows a client-side rendering barrier' if render_gap else ''}. "
                    f"The heading is present for a JavaScript-executing browser but absent for "
                    f"non-JS AI crawlers (GPTBot, ClaudeBot, PerplexityBot), which read the raw response.",
                    "Server-render the <h1> so it is in the initial HTML response. Do not simply add a "
                    "second <h1> -- the heading already exists in the rendered DOM; move its rendering "
                    "to the server (SSR/SSG) or emit it in the static shell.",
                    plain_english="Your page does have a main heading, but it is drawn by JavaScript after "
                    "the page loads. AI crawlers read the raw server response, where the heading is missing, "
                    "so they cannot see what the page's main topic is."
                )
            else:
                add_finding(
                    findings, "readability",
                    "Missing primary <h1> header tag",
                    "medium",
                    "Page HTML contains no <h1> tag for topic orientation, and no sub-headings that "
                    "would suggest one is being injected client-side.",
                    "Add a clear, topic-defining <h1> tag at the top of the page content.",
                    plain_english="The main heading tag (<h1>) is missing, making it harder for AI readers to instantly identify the primary topic of your page."
                )
        elif hierarchy_issues:
            add_finding(
                findings, "readability",
                "Heading Hierarchy & Outline Structure Issues Detected",
                "low",
                f"Heading structure contains level skips: {hierarchy_issues}.",
                "Structure page headings sequentially (H1 -> H2 -> H3) without skipping levels.",
                plain_english="Your page headings skip structural levels (like jumping from H1 directly to H4), making the logical content outline harder for AI models to parse."
            )

        consistency = pick(readability, "content_consistency", "context_consistency", default={}) or {}
        cons_verdict = consistency.get("agent_verdict")
        cons_flag = (cons_verdict.get("inconsistent") if isinstance(cons_verdict, dict)
                     else consistency.get("contains_inconsistency"))
        if cons_flag:
            summ = consistency.get("overall_summary", {}) or {}
            unver = consistency.get("unverified_facts_for_agent", []) or []
            detail = ", ".join(f"{u.get('field')}={u.get('structured_value')!r}" for u in unver[:5])
            add_finding(
                findings, "readability",
                "Structured Data Contradicts the Page's Visible Text",
                "high",
                f"{summ.get('total_facts_verified')} of {summ.get('total_facts_evaluated')} "
                f"facts declared in Schema.org markup could not be found in the page's visible text"
                f"{' (' + detail + ')' if detail else ''}. "
                f"Basis: {'agent judgment' if isinstance(cons_verdict, dict) else 'string-match heuristic -- agent confirmation recommended'}.",
                "Make the visible page text state the same values as the structured data (price, availability, dates, names), or correct the JSON-LD to match the page.",
                # An agent that actually reviewed the facts and confirmed a
                # real mismatch is fully trustworthy; the raw string-match
                # heuristic alone is prone to false positives (a fact only
                # present in a tel:/mailto: href or a WhatsApp link, not
                # printed as prose, is an omission, not a contradiction --
                # the heuristic can't tell the two apart on its own).
                confidence=1.0 if isinstance(cons_verdict, dict) else 0.5,
                plain_english="Your machine-readable data claims values that a reader cannot find on the page. AI models cross-check the two and distrust pages where they disagree."
            )

        nontext = pick(readability, "nontext_facts", "nontext_content", default={}) or {}
        if nontext:

            # --- Category 1: Standard <img> — missing alt ---
            std_imgs = nontext.get("standard_images", {})
            img_total   = std_imgs.get("total", 0)
            img_missing = std_imgs.get("missing_alt", 0)
            img_generic = std_imgs.get("generic_alt_placeholder", 0)
            img_decorative = std_imgs.get("decorative_alt_empty", 0)
            img_descriptive = std_imgs.get("descriptive_alt", 0)
            miss_snippet = std_imgs.get("first_missing_alt_snippet") or ""
            gen_snippet  = std_imgs.get("first_generic_alt_snippet") or ""

            if img_missing > 0:
                ev = (
                    f"{img_missing} of {img_total} <img> tags are missing the alt attribute entirely "
                    f"(alt not present — distinct from decorative alt=\"\"). "
                )
                if miss_snippet:
                    ev += f"Example detected: {miss_snippet}  →  "
                    ev += f"Recommended: <img src=\"...\" alt=\"Descriptive label of what the image shows\">"
                add_finding(
                    findings, "readability",
                    f"Standard <img> Tags Missing Alt Attribute ({img_missing} of {img_total})",
                    "medium" if img_missing <= 3 else "high",
                    ev,
                    "Add a descriptive alt attribute to every meaningful <img> tag. "
                    "Decorative images that carry no information should use alt=\"\" (empty string).",
                    plain_english=(
                        "AI text crawlers like GPTBot and ClaudeBot cannot see images — they read "
                        "raw HTML text. When an <img> tag has no alt attribute, the image is completely "
                        "invisible and unidentifiable to AI models. "
                        f"Manual check: In DevTools Console → document.querySelectorAll('img:not([alt])').length"
                    )
                )

            if img_generic > 0:
                ev = (
                    f"{img_generic} of {img_total} <img> tags use a generic/placeholder alt text "
                    f"(e.g. 'image', 'logo', 'banner', 'photo') that conveys no real information. "
                )
                if gen_snippet:
                    ev += f"Example: {gen_snippet}"
                add_finding(
                    findings, "readability",
                    f"Standard <img> Tags With Generic/Placeholder Alt Text ({img_generic} of {img_total})",
                    "low",
                    ev,
                    "Replace generic alt values like 'image' or 'logo' with descriptive labels "
                    "specific to what the image depicts (e.g. 'CEO Jane Smith presenting at DevSummit 2025').",
                    plain_english=(
                        "Alt text like 'image', 'logo', or 'banner' is technically present but tells "
                        "AI search models nothing useful. It wastes the opportunity to explain what the "
                        "image shows, reducing AI's ability to understand your page's visual content. "
                        f"Manual check: In DevTools Console → "
                        f"document.querySelectorAll('img[alt]') then inspect alt values."
                    )
                )

            # --- Category 2: Inline SVG accessibility ---
            vec = nontext.get("vector_graphics", {})
            svg_total        = vec.get("total", 0)
            svg_inaccessible = vec.get("inaccessible", 0)
            svg_accessible   = vec.get("accessible", 0)
            bad_svg_snippet  = vec.get("first_inaccessible_snippet") or ""

            if svg_total > 0 and svg_inaccessible > 0:
                ev = (
                    f"{svg_inaccessible} of {svg_total} inline <svg> vector graphics lack any "
                    f"accessible text alternative (<title>, <desc>, aria-label, or aria-labelledby). "
                    f"SVGs that are purely decorative should use aria-hidden=\"true\". "
                )
                if bad_svg_snippet:
                    ev += (
                        f"Example detected: {bad_svg_snippet}  →  "
                        f"Recommended (content SVG): "
                        f"<svg role=\"img\" aria-label=\"Architecture diagram showing three tiers\"><title>Architecture diagram</title>...</svg>  "
                        f"OR (decorative SVG): <svg aria-hidden=\"true\" focusable=\"false\">...</svg>"
                    )
                add_finding(
                    findings, "readability",
                    f"Inline <svg> Vector Graphics Missing Accessible Labels ({svg_inaccessible} of {svg_total})",
                    "medium" if svg_inaccessible <= 5 else "high",
                    ev,
                    "For content SVGs: add a <title> child element and/or aria-label on the <svg> tag. "
                    "For purely decorative SVGs: add aria-hidden=\"true\" to explicitly mark them as decorative. "
                    "This allows AI crawlers to correctly interpret or ignore each graphic.",
                    plain_english=(
                        f"Your page contains {svg_inaccessible} inline SVG graphics with no text label. "
                        "AI text crawlers cannot render or interpret SVG visuals — without a <title> or "
                        "aria-label, these graphics are completely opaque to AI search models. "
                        "This is especially impactful for logos, diagrams, icons, and charts embedded as SVG. "
                        f"Manual check: In DevTools Console → "
                        f"document.querySelectorAll('svg:not([aria-hidden]):not([aria-label])').length"
                    )
                )

            # --- Category 3: Embedded media (video / audio / iframe) ---
            emb = nontext.get("embedded_media", {})
            vid_total    = emb.get("video_total", 0)
            vid_no_cap   = emb.get("video_missing_captions", 0)
            aud_total    = emb.get("audio_total", 0)
            aud_no_cap   = emb.get("audio_missing_captions", 0)
            ifr_total    = emb.get("iframe_video_total", 0)
            ifr_no_title = emb.get("iframe_video_missing_title", 0)
            vid_snippet  = emb.get("first_video_snippet") or ""
            ifr_snippet  = emb.get("first_iframe_snippet") or ""

            if vid_no_cap > 0 or aud_no_cap > 0:
                parts = []
                if vid_no_cap > 0:
                    parts.append(f"{vid_no_cap} of {vid_total} <video> elements missing <track kind='captions'>")
                if aud_no_cap > 0:
                    parts.append(f"{aud_no_cap} of {aud_total} <audio> elements missing captions/transcript link")
                ev = ". ".join(parts) + ". "
                if vid_snippet:
                    ev += (
                        f"Example: {vid_snippet}  →  "
                        f"Recommended: <video ...><track kind=\"captions\" src=\"captions.vtt\" srclang=\"en\" default></video>"
                    )
                add_finding(
                    findings, "readability",
                    "Native Video/Audio Missing Caption Track",
                    "medium",
                    ev,
                    "Add a <track kind='captions'> element inside every <video> and <audio> tag "
                    "pointing to a WebVTT (.vtt) caption file.",
                    plain_english=(
                        "AI crawlers cannot hear or process audio streams. Without a caption track or "
                        "transcript, the spoken content of your videos and audio clips is completely "
                        "invisible to AI models, making it impossible for them to index or cite that information. "
                        f"Manual check: In page source, search for '<video' and verify each has a <track> child."
                    )
                )

            if ifr_no_title > 0:
                ev = (
                    f"{ifr_no_title} of {ifr_total} embedded video iframes (YouTube/Vimeo/etc.) "
                    f"lack both a title attribute and aria-label, making the embedded content unidentifiable. "
                )
                if ifr_snippet:
                    ev += (
                        f"Example: {ifr_snippet}  →  "
                        f"Recommended: <iframe src=\"...\" title=\"Product demo video: How to set up Docker Desktop\" ...></iframe>"
                    )
                add_finding(
                    findings, "readability",
                    f"Embedded Video Iframes Missing Descriptive title Attribute ({ifr_no_title} of {ifr_total})",
                    "low",
                    ev,
                    "Add a descriptive title attribute to every <iframe> embedding a video. "
                    "The title should describe what the video is about, not just say 'video'.",
                    plain_english=(
                        "Embedded YouTube/Vimeo iframes without a title attribute are unidentifiable "
                        "to AI crawlers. The crawlers see an anonymous box with no idea what video content "
                        "it contains. A good title helps AI models understand and surface that content. "
                        f"Manual check: In DevTools → document.querySelectorAll('iframe[src*=\"youtube\"]:not([title])').length"
                    )
                )

            # --- Category 4: Canvas elements ---
            cnv = nontext.get("canvas_and_interactive", {})
            canvas_total      = cnv.get("total", 0)
            canvas_no_fallback = cnv.get("missing_fallback", 0)
            cnv_snippet       = cnv.get("first_snippet") or ""

            if canvas_no_fallback > 0:
                ev = (
                    f"{canvas_no_fallback} of {canvas_total} <canvas> elements have no inner fallback "
                    f"text content visible to non-JS environments. "
                )
                if cnv_snippet:
                    ev += (
                        f"Example: {cnv_snippet}  →  "
                        f"Recommended: <canvas id=\"chart\">Sales chart: Q1 $1.2M, Q2 $1.8M, Q3 $2.1M</canvas>"
                    )
                add_finding(
                    findings, "readability",
                    f"<canvas> Elements Missing Text Fallback Content ({canvas_no_fallback} of {canvas_total})",
                    "low",
                    ev,
                    "Place a text description of the canvas content between <canvas> opening and closing tags. "
                    "This text is shown to non-JS browsers and read by screen readers and AI crawlers.",
                    plain_english=(
                        "HTML5 <canvas> elements render graphics via JavaScript — AI crawlers reading raw HTML "
                        "see only an empty box. Without inner fallback text describing what the canvas displays "
                        "(e.g. a chart or interactive map), the content is completely opaque to AI models. "
                        f"Manual check: In page source, search for '<canvas' and check for descriptive text inside."
                    )
                )

            # --- Category 5: Icon elements ---
            ico = nontext.get("icon_elements", {})
            icon_total      = ico.get("total", 0)
            icon_unlabelled = ico.get("unlabelled", 0)
            ico_snippet     = ico.get("first_bad_snippet") or ""

            if icon_unlabelled > 0:
                ev = (
                    f"{icon_unlabelled} of {icon_total} icon elements (<i class=\"fa-...\">, "
                    f"<span class=\"icon-...\">, or role=\"img\" elements) have neither an accessible "
                    f"label (aria-label / title) nor are marked as decorative (aria-hidden=\"true\"). "
                )
                if ico_snippet:
                    ev += (
                        f"Example: {ico_snippet}  →  "
                        f"If decorative: <i class=\"fa-check\" aria-hidden=\"true\"></i>  "
                        f"If meaningful: <i class=\"fa-phone\" role=\"img\" aria-label=\"Call us\"></i>"
                    )
                add_finding(
                    findings, "readability",
                    f"Icon Elements Without Accessible Label or aria-hidden ({icon_unlabelled} of {icon_total})",
                    "low",
                    ev,
                    "For purely decorative icons: add aria-hidden=\"true\" to hide them from assistive tech. "
                    "For functional icons (phone, email, social media links): add aria-label=\"Description\" "
                    "so AI crawlers and screen readers understand their purpose.",
                    plain_english=(
                        "Icon fonts (Font Awesome, Bootstrap Icons, Material Icons) render as pictures in "
                        "the browser but appear as invisible characters in raw HTML. AI crawlers cannot "
                        "interpret icon meaning. Decorative icons should be hidden with aria-hidden=\"true\"; "
                        "functional icons should have aria-label text explaining their action. "
                        f"Manual check: document.querySelectorAll('[class*=\"fa-\"],[class*=\"icon-\"]').length in DevTools."
                    )
                )

            # --- Category 6: PDF documents ---
            docs = nontext.get("linked_documents", {})
            pdf_found    = docs.get("pdf_links_found", 0)
            pdf_no_text  = docs.get("pdf_missing_text_layer", 0)
            pdf_details  = docs.get("details", [])

            if pdf_no_text > 0:
                bad_pdfs = [d["url"] for d in pdf_details if d.get("has_text_layer") is False][:2]
                ev = (
                    f"{pdf_no_text} of {len(pdf_details)} inspected PDF file(s) appear to be "
                    f"scanned image-only PDFs with no extractable digital text layer. "
                    f"Affected URLs: {bad_pdfs}. "
                    f"Detection method: PDF stream operator byte-header heuristic (/BT /ET /Tj operators absent)."
                )
                add_finding(
                    findings, "readability",
                    f"Linked PDF Documents Missing Digital Text Layer ({pdf_no_text} of {len(pdf_details)} inspected)",
                    "medium",
                    ev,
                    "Re-export PDFs from source documents (Word, InDesign, Google Docs) to ensure digital "
                    "text is embedded. If the PDF originated as a scan, run OCR (Optical Character Recognition) "
                    "using Adobe Acrobat, ABBYY FineReader, or Google Drive to create a searchable text layer.",
                    plain_english=(
                        "Some of your linked PDF files appear to be scanned images saved as PDF. "
                        "AI crawlers cannot read image-only PDFs — there is no text to extract or index. "
                        "The entire document content is invisible to AI search models. "
                        "Re-exporting as a text-based PDF or running OCR makes the content indexable. "
                        f"Manual check: Open the PDF, press Ctrl+A to select all — if nothing highlights, it has no text layer."
                    )
                )
            elif pdf_found > 0 and len(pdf_details) > 0:
                # All inspected PDFs have text — report as informational pass
                pass   # No finding needed; passing PDFs don't generate a negative finding



    # 4. Freshness & Corroboration Skill Findings
    freshness = skill_outputs.get("freshness_corroboration", {})
    if freshness:
        citations = freshness.get("citation_consistency", {})
        if citations.get("contains_contradiction"):
            conflicting = citations.get("conflicting_domains", [])
            add_finding(
                findings, "freshness_corroboration",
                "Off-site Citation Contradiction Detected",
                "high",
                f"For fact '{citations.get('fact_type')}' the on-site value "
                f"'{citations.get('fact_value_on_site')}' is contradicted by "
                f"{conflicting or 'external sources'} "
                f"(match confidence: {citations.get('contradiction_confidence') or 'unrated'}).",
                "Audit external brand mentions and update third-party profiles for accurate citation consistency.",
                plain_english="Information found on external websites contradicts what is stated on your official site, which reduces AI confidence when answering queries about your brand."
            )
        elif citations.get("needs_agent_judgment"):
            # headquarters / custom facts: the script cannot adjudicate; the
            # agent should compare fact_value_on_site against external_mentions_found
            # and inject a finding only if it judges a real conflict.
            pass

        entities = freshness.get("entity_disambiguation", {})
        if entities:
            brand_name_str = entities.get("brand_name") or site_url
            bare_search = entities.get("bare_name_search", {})
            search_domains = bare_search.get("search_result_domains", [])
            target_in_top = bare_search.get("target_domain_in_top_results")

            # Check 1: Target domain missing from top bare brand name search
            # results. `target_in_top is None` means no domain was supplied ->
            # the check could not run, so do NOT raise a finding.
            if entities.get("domain_provided", True) and search_domains and target_in_top is False:
                add_finding(
                    findings, "freshness_corroboration",
                    "Target Website Domain Missing from Top Search Results for Brand Name",
                    "high",
                    f"Search results for brand name '{brand_name_str}' did not include target domain in top results. Top domains found: {search_domains[:5]}.",
                    "Optimize brand SEO and acquire authoritative branded backlinks so search engines rank your official domain #1 for your brand name.",
                    plain_english=f"When searching for your brand name '{brand_name_str}' on search engines, your official website domain did not appear in the top search results. This creates severe brand ambiguity for AI crawlers trying to verify your official domain."
                )

            # Check 2: No off-site Wikipedia page or Wikidata entity found (Optional external authority signal)
            wiki_found = entities.get("wikipedia_page_found")
            data_found = entities.get("wikidata_entry_found")
            if wiki_found is False and data_found is False:
                add_finding(
                    findings, "freshness_corroboration",
                    "No External Wikipedia Article or Wikidata Entry Found (Optional Authority Signal)",
                    "low",
                    f"External web search for brand '{brand_name_str}' found zero Wikipedia articles or Wikidata entries. Note: Wikipedia and Wikidata coverage are optional external authority signals for eligible entities, not mandatory website requirements.",
                    "If your organization meets Wikipedia or Wikidata notability guidelines, consider claiming an official entity entry. Otherwise, focus on linking verified official social profiles (LinkedIn, X/Twitter, Crunchbase) via Organization schema sameAs links.",
                    plain_english=f"No official Wikipedia page or Wikidata entry was found for '{brand_name_str}'. These are optional external authority signals for notable entities, not mandatory website requirements. Do not create Wikidata entries unless your business genuinely meets official notability guidelines; instead, link your official social profiles (LinkedIn, X/Twitter) in your website schema."
                )

            # Check 3a / 3b: sameAs links split. `same_as_links_found: false` on
            # empty html means "never checked" (site unreachable), not
            # "checked and confirmed absent" -- html_provided distinguishes
            # them. Default True so older callers that always supplied real
            # html (and never set this field) keep their existing behavior.
            same_as_links_found = entities.get("same_as_links_found")
            if same_as_links_found is None:
                # Fallback for older script output that lacks the explicit bool field
                same_as_links_found = len(entities.get("same_as_links", [])) > 0

            has_wiki_sameas = entities.get("has_wikidata_or_wikipedia_sameas", False)

            if not entities.get("html_provided", True):
                pass  # no page content was retrieved -- cannot say anything about sameAs
            elif not same_as_links_found:
                # Check 3a: No sameAs links at all in Organization schema
                add_finding(
                    findings, "freshness_corroboration",
                    "Missing sameAs Links in Organization Schema",
                    "medium",
                    "Organization schema has no sameAs links at all. AI search engines rely on sameAs entity links to verify your official brand identity across platforms.",
                    "Add verified sameAs links to your official social profiles (LinkedIn, X/Twitter, YouTube, Crunchbase) in Organization JSON-LD.",
                    plain_english="Your website's structured data (Organization schema) contains no sameAs identity links. Adding links to your official social media profiles (LinkedIn, X/Twitter) helps AI search engines verify that your website belongs to a real, recognized brand."
                )
            elif same_as_links_found and not has_wiki_sameas:
                # Check 3b: Has sameAs links but no Wikipedia or Wikidata authority link
                extra_note = ""
                if wiki_found is False and data_found is False:
                    extra_note = " Off-site search also confirmed no Wikipedia or Wikidata entry was found for this brand."
                add_finding(
                    findings, "freshness_corroboration",
                    "Organization sameAs Links Present but No Wikipedia or Wikidata Authority Link",
                    "low",
                    f"Organization schema contains sameAs links (e.g. social profiles), but none point to Wikipedia or Wikidata.{extra_note} Note: Wikipedia/Wikidata coverage is an optional external authority signal for eligible entities, not a mandatory requirement.",
                    "If your organization meets Wikipedia or Wikidata notability guidelines, consider adding an official entity link in your Organization sameAs. Otherwise, the existing social profile sameAs links are sufficient.",
                    plain_english=f"Your Organization schema has sameAs identity links (e.g. LinkedIn, X/Twitter), but none link to a Wikipedia article or Wikidata entry for '{brand_name_str}'. This is an optional enhancement — only pursue it if your business genuinely meets Wikipedia or Wikidata notability guidelines."
                )

            # Check 4: Name ambiguity / mistaken identity (Round-2 appendix D).
            amb = entities.get("name_ambiguity", {}) or {}
            amb_verdict = amb.get("agent_verdict")  # optional injected {ambiguous: bool, notes}
            amb_flag = (amb_verdict.get("ambiguous") if isinstance(amb_verdict, dict)
                        else amb.get("ambiguity_risk") == "elevated")
            if amb_flag:
                sig = amb.get("ambiguity_signals", [])
                # An injected agent_verdict.notes carries the agent's actual
                # reasoning (which entities collide, why); the raw heuristic
                # signal list is a poor substitute and was silently discarding
                # it. Lead with the notes when present, keep the signal list as
                # supporting evidence either way.
                verdict_notes = amb_verdict.get("notes") if isinstance(amb_verdict, dict) else None
                if verdict_notes:
                    evidence = (f"{verdict_notes} (heuristic signals: {sig or 'none'}; "
                               f"basis: agent judgment).")
                else:
                    evidence = (f"Bare-name search for '{brand_name_str}' shows collision signals: "
                               f"{sig or 'multiple distinct same-named entities'} "
                               f"(basis: {'agent judgment' if isinstance(amb_verdict, dict) else 'search-result heuristic'}).")
                add_finding(
                    findings, "freshness_corroboration",
                    "Brand Name Is Ambiguous in Search / Prone to Mistaken Identity",
                    "medium",
                    evidence,
                    "Strengthen entity disambiguation: add an authoritative sameAs (Wikidata/Wikipedia "
                    "where eligible), keep the official domain ranked #1 for the brand name via branded "
                    "backlinks, and use a consistent full legal/brand name across the site and third-party profiles.",
                    # An agent that actually reviewed the candidate entities
                    # and confirmed real mistaken-identity risk is fully
                    # trustworthy; the raw "elevated" heuristic alone (domain
                    # rank + token-length signals) flags real risk often
                    # enough to act on, but without inspecting the actual
                    # colliding results it can't rule out that they're all
                    # third-party listings of the SAME brand (directories,
                    # social profiles) rather than a different entity.
                    confidence=1.0 if isinstance(amb_verdict, dict) else 0.6,
                    plain_english="When people (and AI assistants) search your brand name, several unrelated "
                    "things with the same name show up, so an assistant can attribute the wrong facts to you."
                )

        dates = freshness.get("content_dates", {})
        if dates:
            if (dates.get("copyright_year_age_years") or 0) >= 2:
                add_finding(
                    findings, "freshness_corroboration",
                    "Outdated Copyright Footer Year",
                    "low",
                    f"The most recent copyright year in the site's visible text is "
                    f"{dates.get('copyright_year')} ({dates.get('copyright_year_age_years')} "
                    f"years behind). All years seen: {dates.get('copyright_years_all')}.",
                    "Update site footer copyright notice to current year.",
                    plain_english=f"Your website displays copyright year {dates.get('copyright_year')}, signaling to AI search bots that content may not be actively maintained."
                )

            # dateModified age -- the single strongest freshness signal, and
            # previously unused. ~18 months without a modification is stale.
            age_days = dates.get("effective_content_age_days")
            if isinstance(age_days, int) and age_days > 540:
                yrs = round(age_days / 365, 1)
                add_finding(
                    findings, "freshness_corroboration",
                    "Structured Content Date (dateModified) Is Stale",
                    "medium",
                    f"JSON-LD reports the page was last modified {age_days} days (~{yrs} years) "
                    f"ago (datePublished: {dates.get('date_published')}, dateModified: "
                    f"{dates.get('date_modified')}).",
                    "Review and refresh the page content, then update datePublished/dateModified in JSON-LD.",
                    plain_english="Your page's machine-readable 'last updated' date is years old, so AI assistants treat the content as outdated and are less likely to cite it for current questions."
                )

            for issue in dates.get("content_date_issues", []):
                add_finding(
                    findings, "freshness_corroboration",
                    "Structured Date Metadata Error",
                    "low",
                    f"JSON-LD date issue: {issue} (datePublished: {dates.get('date_published')}, "
                    f"dateModified: {dates.get('date_modified')}).",
                    "Correct the datePublished / dateModified values in the page's JSON-LD.",
                    plain_english="The page's structured 'published' / 'updated' dates are inconsistent or invalid, which undermines how AI systems judge the content's recency."
                )
                break  # one finding is enough

        decay = freshness.get("temporal_decay", {})
        if decay and decay.get("is_decayed") and not decay.get("has_relative_recent_timestamps"):
            conf = decay.get("detection_confidence", "low")
            add_finding(
                findings, "freshness_corroboration",
                "Blog/News Listing Content Recency Decay Detected",
                "medium" if conf == "high" else "low",
                f"Newest post on the listing page is {decay.get('most_recent_post_date_iso') or decay.get('most_recent_post_date_found')} "
                f"({decay.get('days_since_last_post')} days old; detection confidence: {conf}).",
                "Publish fresh, authoritative articles regularly to maintain topic recency.",
                # A "low" detection_confidence usually means a single loose
                # year-only text mention (often a founding year or a funding
                # timeline, not an actual post date) rather than a real
                # <time datetime> post date -- give it a low SCORING weight
                # to match, not just a lower severity label.
                confidence=1.0 if conf == "high" else 0.35,
                plain_english="Your blog or news listing has not published new content in over a year, causing AI search engines to rank your brand lower for query freshness."
            )

    # 5. Engagement Skill Findings
    engagement = skill_outputs.get("engagement", {})
    if engagement:
        reach = engagement.get("navigation_reachability", {})
        for item in reach.get("key_content_reachability", []):
            if item.get("directly_linked_from_homepage") is False:
                add_finding(
                    findings, "engagement",
                    "Key Content URL Unreachable from Homepage 1-Level Navigation",
                    "medium",
                    f"URL {item.get('key_content_url')} is not directly linked from the homepage.",
                    "Add direct navigation or footer links to key content pages from the homepage.",
                    plain_english="Important content pages are not directly linked in your main homepage navigation menu, making them harder for AI crawlers to discover from the homepage."
                )

        depth = engagement.get("content_depth", {})
        if depth.get("below_reference_range"):
            _intent = depth.get("detected_page_intent") or depth.get("page_type_hint") or "content"
            _reason = depth.get("assessment_reason") or ""
            add_finding(
                findings, "engagement",
                "Thin Content Depth on a Content-Bearing Page",
                "medium",
                (f"Page classified as '{_intent}' has only {depth.get('visible_word_count')} visible words "
                 f"against an advisory band of {depth.get('reference_min_word_count')}, and its structure "
                 f"corroborates thinness ({_reason})."),
                "Expand page content depth with comprehensive details, FAQs, and specs specific to this page's topic.",
                plain_english="The page contains too little written text, giving AI models insufficient detailed information to answer user questions thoroughly."
            )

        mobile = engagement.get("mobile_responsiveness", {})
        if mobile.get("viewport_and_media_query_both_absent"):
            add_finding(
                findings, "engagement",
                "Missing Mobile Viewport Meta Tag",
                "high",
                "Page HTML lacks <meta name='viewport'> tag, causing rendering friction on mobile devices.",
                "Add <meta name='viewport' content='width=device-width, initial-scale=1'> to page <head>.",
                plain_english="Your page HTML is missing mobile layout configuration, which causes display rendering issues on mobile devices and AI visual scrapers."
            )

        descriptor = engagement.get("descriptor_consistency", {})
        if descriptor:
            for p in descriptor.get("pages", []):
                if p.get("brand_phrase_present_in_title") is False:
                    add_finding(
                        findings, "engagement",
                        "Brand Name Omitted from Page Title Tag",
                        "medium",
                        f"Page URL {p.get('url')} title '{p.get('title')}' does not contain candidate brand phrase '{descriptor.get('candidate_brand_phrase')}'.",
                        "Include brand name phrase systematically in title tags (e.g. 'Page Title | Brand Name').",
                        plain_english="Your official brand name is missing from the browser title tag of this page, causing brand orientation friction for AI engines."
                    )
                    break

        speed = engagement.get("page_speed_signals", {})
        if speed:
            if len(speed.get("resource_fetch_errors", [])) > 0:
                add_finding(
                    findings, "engagement",
                    "External CSS/JS Resource Fetch Errors Encountered",
                    "low",
                    f"{len(speed.get('resource_fetch_errors'))} external stylesheet/script resource fetches failed or returned HTTP errors.",
                    "Verify external asset availability and clean up broken resource references.",
                    plain_english="Some external design or script files failed to load, which may prevent AI visual renderers from displaying your site layout properly."
                )
            if speed.get("html_byte_size", 0) > 2000000:
                add_finding(
                    findings, "engagement",
                    "Excessive HTML Document Byte Size",
                    "medium",
                    f"HTML payload size is {round(speed.get('html_byte_size') / 1024 / 1024, 2)} MB, exceeding the 2 MB ceiling.",
                    "Minify HTML source code and inline asset payloads to reduce file size below 2 MB.",
                    plain_english="Your HTML page file is unusually large (>2MB), which slows down AI crawler downloads and risks payload truncation."
                )

        # AI-referral landing readiness -- accepts a single dict or a list of
        # per-page results. Orientation / next-step verdicts come from the
        # agent's semantic judgment of raw_for_agent_judgment when supplied,
        # else the script's keyword-heuristic floor. Hygiene findings
        # (placeholder text, default title) are reliable either way.
        lr_raw = engagement.get("landing_readiness")
        lr_pages = lr_raw if isinstance(lr_raw, list) else ([lr_raw] if isinstance(lr_raw, dict) else [])
        seen_lr_titles = set()
        for lr in lr_pages:
            if not isinstance(lr, dict):
                continue
            lr_url = lr.get("url") or "(page)"
            summ = lr.get("landing_readiness_summary", {})
            orient = lr.get("orientation", {})
            nxt = lr.get("next_step", {})
            hyg = lr.get("hygiene", {})

            # Prefer the agent's semantic verdict over the keyword heuristic when
            # the orchestrator has judged raw_for_agent_judgment and injected it.
            av = summ.get("agent_verdict") if isinstance(summ.get("agent_verdict"), dict) else {}
            orientation_ok = av.get("orientation_ok", orient.get("orientation_ok"))
            has_next_step = av.get("has_next_step", nxt.get("has_next_step"))
            dead_end = (has_next_step is False) if av else nxt.get("dead_end_risk")
            basis = "agent semantic judgment" if av else "keyword heuristic (no agent verdict supplied)"

            if orientation_ok is False and not lr.get("is_utility_context"):
                miss = [lbl for lbl, key in (
                    ("brand/organization name", "brand_name"),
                    ("one-line description of what the brand does", "description"),
                    ("a topic-defining <h1>", "topic_sentence"),
                ) if not orient.get(key, {}).get("present")]
                if "orient" not in seen_lr_titles:
                    seen_lr_titles.add("orient")
                    add_finding(
                        findings, "engagement",
                        "Deep Page Fails Cold AI-Referral Orientation",
                        "high",
                        f"Page {lr_url} is missing {', '.join(miss) or 'core orientation elements'} "
                        f"({basis}). AI assistants cite deep pages, so a referred visitor lands "
                        f"here with no journey context and cannot tell who the brand is or what "
                        f"it offers.",
                        "Ensure every indexable page carries the brand name, a one-line description "
                        "of what the brand does, and a topic-defining <h1> (in visible text or "
                        "Organization JSON-LD).",
                        plain_english="A visitor arriving on this page from an AI assistant sees no "
                        "brand name, no explanation of what you do, and no clear page topic -- so "
                        "they leave."
                    )

            if dead_end and not lr.get("is_utility_context") and "deadend" not in seen_lr_titles:
                seen_lr_titles.add("deadend")
                add_finding(
                    findings, "engagement",
                    "Dead-End Page: No Path Forward for the Visitor",
                    "medium",
                    f"Page {lr_url} offers the visitor no forward action -- no primary "
                    f"call-to-action, no persistent navigation, no contact path, and fewer than "
                    f"5 internal links ({basis}).",
                    "Add a primary call-to-action and persistent site navigation to every "
                    "template so an arriving visitor always has a next step.",
                    plain_english="Someone landing on this page has nowhere to click next -- no "
                    "menu, no button, no links -- so the visit ends here."
                )

            if hyg.get("placeholder_text_found") and "placeholder" not in seen_lr_titles:
                seen_lr_titles.add("placeholder")
                add_finding(
                    findings, "engagement",
                    "Placeholder / Unfinished Text Visible on a Live Page",
                    "medium",
                    f"Page {lr_url} contains placeholder text: {hyg.get('placeholder_text_found')}.",
                    "Remove Lorem Ipsum / 'coming soon' / TODO placeholder text before publishing.",
                    plain_english="The page still has dummy or 'coming soon' text on it, which "
                    "signals to visitors (and to AI models quoting the page) that it is unfinished."
                )

            if hyg.get("default_or_empty_title") and "title" not in seen_lr_titles:
                seen_lr_titles.add("title")
                add_finding(
                    findings, "engagement",
                    "Default or Empty Page <title>",
                    "low",
                    f"Page {lr_url} has the title '{hyg.get('title_value')}', a framework default "
                    f"or empty value.",
                    "Set a descriptive, brand-bearing <title> on every page template "
                    "(e.g. 'Page Topic | Brand Name').",
                    plain_english="The browser tab, the search-result snippet, and shared-link "
                    "previews for this page carry no brand or topic text."
                )

    # Renumber every finding sequentially. `add_finding` derives an id from the
    # running list length, so any caller-supplied explicit finding that already
    # carries its own id leaves a gap (F-000 pre-seeded => first generated id is
    # F-002 and F-001 never exists). Assigning ids once, at the end, keeps the
    # sequence contiguous regardless of how many explicit findings were injected.
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F-{i:03d}"

    # Calculate Category Scores
    category_names = ["crawl_access", "crawl_render", "readability", "freshness_corroboration", "engagement"]
    category_scores = {cat: calculate_category_score(findings, cat) for cat in category_names}
    overall_score, scoring_model = calculate_overall_readiness_score(category_scores, findings)

    # Severity Summary Counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["medium"] += 1

    audited_pages_cnt = extract_audited_urls(site_url, skill_outputs)
    skills_invoked_cnt = max(1, len([k for k in skill_outputs if skill_outputs[k]]))

    default_recs = [
        "Ensure robots.txt allows access to AI crawler user-agents (GPTBot, PerplexityBot, ClaudeBot).",
        "Implement Server-Side Rendering (SSR) so raw HTML responses contain full text and JSON-LD schema.",
        "Add authoritative sameAs references (Wikidata, Wikipedia, LinkedIn) to Organization schema markup.",
        "Ensure key product/service landing pages are directly linked from homepage navigation.",
        "Include <meta name='viewport' content='width=device-width, initial-scale=1'> on all page templates."
    ]

    report = {
        "site": site_url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "brand_ai_readiness_score": overall_score,
        "category_scores": category_scores,
        "scoring_model": scoring_model,
        "summary": {
            "total_findings": len(findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": findings,
        "proactive_recommendations": proactive_recommendations or default_recs,
        "audit_metadata": {
            "audited_pages_count": audited_pages_cnt,
            "skills_invoked_count": skills_invoked_cnt,
            "marketplace_version": "1.0.0"
        }
    }
    return report

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

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params["site"] = raw_arg
            else:
                params["site"] = raw_arg

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        site_url = params.get('site') or params.get('url', 'https://example.com')
        skill_outputs = params.get('skill_outputs', {})
        explicit_findings = params.get('findings', [])
        recommendations = params.get('proactive_recommendations', [])

        report = synthesize_report(site_url, skill_outputs, explicit_findings, recommendations)
        print(json.dumps(report, indent=2))
    except Exception as e:
        print(json.dumps({
            "site": None,
            "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "brand_ai_readiness_score": 0.0,
            "category_scores": {
                "crawl_access": 0.0, "crawl_render": 0.0, "readability": 0.0,
                "freshness_corroboration": 0.0, "engagement": 0.0
            },
            "scoring_model": {
                "method": "weighted_with_foundational_gates",
                "weights": CATEGORY_WEIGHTS,
                "weighted_subtotal": 0.0,
                "gates_applied": []
            },
            "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
            "findings": [],
            "proactive_recommendations": [],
            "audit_metadata": {
                "audited_pages_count": 0,
                "skills_invoked_count": 0,
                "marketplace_version": "1.0.0"
            },
            "script_error": str(e)
        }))
