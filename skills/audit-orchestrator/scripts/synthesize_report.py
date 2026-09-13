
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import io
import os
import json
import urllib.parse
from datetime import datetime, timezone

# check_structured_data.py scores attribute completeness across 9 Schema.org
# types, but for a long time only `article_completeness` was ever read here --
# a Product declaring an Offer with no price and no availability was detected
# in full and then silently dropped, scoring a clean 100. This table turns
# every one of those completeness objects into a finding.
#
# Severity reflects what an answer engine actually loses: price/availability
# and event date/location are the facts an assistant quotes directly, so their
# absence is `medium`; a missing logo or upload date degrades the entity but
# doesn't make it unanswerable, so `low`. Fields no legitimate entity is
# obliged to carry (an Organization's telephone, a Recipe's image) are
# deliberately NOT listed -- flagging those would manufacture findings against
# sites that are perfectly correct.
SCHEMA_COMPLETENESS_RULES = (
    ("product_completeness", "Product", "medium",
     (("has_name", "name"), ("has_offers", "offers"),
      ("has_price", "offers.price"), ("has_availability", "offers.availability")),
     "price and availability are the two facts an assistant quotes most often about a product"),
    ("event_completeness", "Event", "medium",
     (("has_name", "name"), ("has_start_date", "startDate"), ("has_location", "location")),
     "an event with no date or location cannot answer 'when' or 'where'"),
    ("recipe_completeness", "Recipe", "medium",
     (("has_name", "name"), ("has_ingredients", "recipeIngredient"),
      ("has_instructions", "recipeInstructions")),
     "ingredients and instructions are the recipe"),
    ("article_completeness", "Article", "low",
     (("has_headline", "headline"), ("has_author", "author"),
      ("has_date_published", "datePublished")),
     "author and publication date are the two E-E-A-T signals most consistently "
     "cited as affecting whether AI systems trust and quote an article"),
    ("software_completeness", "SoftwareApplication", "low",
     (("has_name", "name"), ("has_operating_system", "operatingSystem")),
     "operatingSystem is what makes a software listing answerable for 'does it run on X'"),
    ("video_completeness", "VideoObject", "low",
     (("has_name", "name"), ("has_thumbnail", "thumbnailUrl"), ("has_upload_date", "uploadDate")),
     "thumbnail and upload date are required for video rich results"),
    ("organization_completeness", "Organization", "low",
     (("has_name", "name"), ("has_url", "url"), ("has_logo", "logo")),
     "name, url and logo are the identity triple other brand facts attach to"),
)


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


def _looks_long_tail_url(url):
    """Heuristic, not a certainty: does this URL structurally look like one of
    many template/combinatorially-generated pages (a specific flight route, a
    product SKU/variant, a real-estate listing, a job posting) rather than a
    hand-curated page a homepage's top-level navigation would reasonably link
    directly? Those pages commonly number in the hundreds or thousands and
    are discovered via internal search or an XML sitemap, not a static nav
    menu -- asserting full confidence that ONE of them specifically belongs
    on the homepage is exactly the false-positive this project's own
    check_sitemap.py representative_sample can otherwise feed straight into
    `key_content_urls` (that field answers "what page represents this
    URL-structure group for content sampling", a different question from
    "what belongs in primary navigation").

    Two independent signals, either sufficient: an unusually long or
    hyphen-dense last path segment (a slug assembled from multiple parameters
    reads very differently from a short, hand-written title), or a path more
    than two segments deep. Returns (bool, reason_or_None)."""
    try:
        path = urllib.parse.urlparse(url).path
    except Exception:
        return False, None
    segments = [s for s in path.split("/") if s]
    if not segments:
        return False, None
    last = segments[-1]
    hyphens = last.count("-")
    if hyphens >= 5 or len(last) >= 40:
        return True, (f"the last path segment ('{last}') has {hyphens} hyphens across {len(last)} "
                      f"characters -- a strong signal of a template/combinatorially-generated page")
    if len(segments) >= 3:
        return True, f"the URL is {len(segments)} path segments deep -- unusually deep for primary navigation"
    return False, None


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


def crawler_class_label(robots, agent):
    info = ((robots or {}).get("agent_classes") or {}).get(agent) or {}
    cls = info.get("class") or "unclassified"
    return f"{cls}: {info['role']}" if info.get("role") and cls in ("retrieval", "training") else cls


def split_blocked_by_crawler_class(robots, blocked_agents, path):
    """Split agents blocked on `path` into
    (retrieval_impacting, other, retrieval_allowed, ineffective).

    retrieval_impacting -- blocks that remove the page from live AI search /
      assistant answers: a 'retrieval' token, any 'unclassified' token (unknown
      purpose, so assume the worst), or '*' when no retrieval crawler was tested
      and found allowed (nothing proves AI search access survives).
    other -- 'training' tokens, and '*' when named retrieval crawlers are
      verifiably still allowed on this path.
    retrieval_allowed -- tested retrieval tokens, that honor robots.txt, NOT
      blocked on this path.
    ineffective -- blocked tokens whose operator documents that robots.txt may
      not apply (user-initiated fetchers such as ChatGPT-User). The rule does
      not actually stop them, so they never count toward either severity bucket.

    robots.txt output without `agent_classes` (older callers) leaves every agent
    'unclassified', which reproduces the previous behavior exactly: every block
    is treated as retrieval-impacting."""
    classes = (robots or {}).get("agent_classes") or {}
    disallowed = ((robots or {}).get("disallowed") or {}).get(path) or {}
    root_blocked = set((robots or {}).get("root_blocked_agents") or [])

    def info(a):
        return classes.get(a) or {}

    ineffective = [a for a in blocked_agents if info(a).get("honors_robots_txt") is False]
    blocked = [a for a in blocked_agents if a not in ineffective]
    retrieval_allowed = [a for a, i in classes.items()
                         if (i or {}).get("class") == "retrieval"
                         and (i or {}).get("honors_robots_txt") is not False
                         and a not in blocked_agents and a not in root_blocked
                         and disallowed.get(a) is not True]
    retrieval_hit, other = [], []
    for a in blocked:
        c = info(a).get("class") or "unclassified"
        if c in ("retrieval", "unclassified") or (c == "wildcard" and not retrieval_allowed):
            retrieval_hit.append(a)
        else:
            other.append(a)
    return retrieval_hit, other, retrieval_allowed, ineffective


def _ineffective_note(ineffective):
    if not ineffective:
        return ""
    return (f" robots.txt also disallows {ineffective}, but their operators document that robots.txt may "
            f"not apply to these user-initiated fetchers, so that rule is not an effective block and is "
            f"not scored.")


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
            bf_status, bot_status_val = bf.get("status"), bot.get("status")
            bot_soft_blocked = bool(
                isinstance(bot_status_val, int) and 200 <= bot_status_val < 300
                and isinstance(bf_status, int) and 200 <= bf_status < 300
                and bot_fp.get("thin_content") and not br_fp.get("thin_content")
            )
            dual_candidates.append({
                "url": url,
                "browser_status": bf_status,
                "bot_status": bot_status_val,
                "bot_blocked": bot_status_val in (401, 403) or bot_fp.get("generic_block", False),
                "bot_soft_blocked": bot_soft_blocked,
                "bot_challenged": (
                    (bot_fp.get("cloudflare_challenge") and not br_fp.get("cloudflare_challenge"))
                    or (bot_fp.get("captcha") and not br_fp.get("captcha"))
                ),
                "rate_limited": 429 in (bf_status, bot_status_val),
                "browser_fetch": bf, "bot_fetch": bot,
                "comparison_metrics": {"fingerprint_divergence": divergence},
                # Not reconstructable from bf/bot alone -- carried forward only
                # when the caller's page item already had it (e.g. it nested
                # dual_fetch()'s full result rather than just the two fetches).
                "robots_decisions": p.get("robots_decisions"),
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
        # severity (how bad it would be if true). Defaults to 1.0 (full
        # weight) for the vast majority of findings that are deterministic
        # facts, not heuristic guesses.
        "confidence": confidence,
    })

# Keys a gated fetcher sets when robots.txt refused the request. Collecting
# them lets the report state plainly what the audit was not permitted to look
# at, so a reader never reads a thin report as "the site has nothing" when the
# truth is "we were told not to look".
ROBOTS_SKIP_KEYS = ("skipped_by_robots", "robots_skipped_bot_fetch",
                    "robots_skipped_browser_fetch")


def collect_robots_restrictions(skill_outputs, _depth=0):
    """Every fetch the audit declined to make because robots.txt disallowed it."""
    found = []

    def walk(node, depth=0):
        if depth > 8:
            return
        if isinstance(node, dict):
            skipped = any(node.get(k) is True for k in ROBOTS_SKIP_KEYS)
            if skipped:
                decision = node.get("robots_decision") or {}
                decisions = node.get("robots_decisions") or {}
                if not decision and isinstance(decisions, dict):
                    decision = next((d for d in decisions.values()
                                     if isinstance(d, dict) and d.get("allowed") is False), {}) or {}
                entry = {
                    "url": node.get("url"),
                    "reason": decision.get("reason") or node.get("error") or "disallowed by robots.txt",
                }
                if decision.get("rule"):
                    entry["rule"] = decision["rule"]
                if decision.get("agent"):
                    entry["user_agent"] = decision["agent"]
                if entry not in found:
                    found.append(entry)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node[:50]:
                walk(item, depth + 1)

    walk(skill_outputs or {})

    # A gated fetch is flagged twice: on the container (robots_skipped_bot_fetch)
    # and on the skipped payload nested inside it (skipped_by_robots). They are
    # one refused request, so the thinner duplicate is dropped rather than
    # counted as a second restriction.
    detailed_urls = {e["url"] for e in found if e.get("rule")}
    return [e for e in found if e.get("rule") or e["url"] not in detailed_urls]


def _build_default_recommendations(skill_outputs, findings, coverage_blocked=False):
    """Fallback `proactive_recommendations` used only when the caller doesn't
    supply its own. Every item here is gated on the actual signal it talks
    about -- this used to be a fixed 5-item list applied unconditionally
    regardless of what the audit found, so a site with zero CSR findings
    still got told to "Implement Server-Side Rendering", and a site whose
    navigation already linked every
    key page still got told to fix its navigation -- directly contradicting
    the findings assembled a few lines above in the same function. Each
    recommendation below survives only if its own underlying signal shows
    it's a genuinely open opportunity, not one already fixed or already
    covered by its own finding+suggested_action above (repeating a finding
    here wouldn't be "proactive", just a duplicate)."""
    skill_outputs = skill_outputs or {}
    finding_titles = " ".join(f.get("title", "") for f in findings).lower()
    recs = []

    access = skill_outputs.get("crawl_access", {}) or {}
    robots = access.get("robots", {}) or {}
    if (robots.get("root_blocked_agents")
            and "robots.txt" not in finding_titles and "blocked" not in finding_titles):
        recs.append("Ensure robots.txt allows access to AI crawler user-agents (GPTBot, PerplexityBot, ClaudeBot).")

    # When AI-bot access is blocked at the infrastructure level, render- and
    # engagement-derived signals below come from a browser-identity (or
    # headless-render) view of pages a real AI crawler never saw --
    # recommending SSR or navigation tweaks from that data would imply a
    # confidence coverage_blocked explicitly says we don't have. The sameAs
    # recommendation is left out of this gate: entity_disambiguation
    # corroborates via external web search, not this site's blocked fetch.
    if coverage_blocked:
        # ...but staying silent is the wrong answer too. These are the
        # recommendations that DON'T depend on reading the blocked pages --
        # they address the block itself, and they are the highest-value advice
        # this whole report can give, since nothing downstream matters until a
        # crawler can actually fetch a page.
        recs.extend([
            "Allowlist verified AI crawlers at the WAF/CDN layer (Cloudflare, Akamai, Fastly, Datadome), "
            "not in robots.txt -- robots.txt is advisory and cannot override an edge block.",
            "Verify crawler identity by reverse DNS + forward-confirmed lookup of the request IP (the method "
            "OpenAI, Anthropic, Perplexity and Google all document), rather than by User-Agent string, which "
            "is trivially spoofed and so is never a safe basis for either allowing or blocking.",
            "Publish the AI-facing content a crawler is currently refused at a path the WAF does not "
            "challenge (a static docs/about/product page), so assistants have at least one reachable, "
            "quotable source for the brand while the edge rules are being fixed.",
            "Re-run this audit once the block is lifted: every content, rendering, freshness and engagement "
            "check was intentionally skipped, so no conclusion about page quality can be drawn from this "
            "report yet.",
        ])

    if not coverage_blocked:
        render = skill_outputs.get("crawl_render", {}) or {}
        csr = (render.get("rendering_barriers", {}) or {}).get("client_side_rendering_signals", {}) or {}
        if (csr.get("likely_client_side_rendering_barrier")
                and "rendering" not in finding_titles and "client-side" not in finding_titles):
            recs.append("Implement Server-Side Rendering (SSR) so raw HTML responses contain full text and JSON-LD schema.")

    freshness = skill_outputs.get("freshness_corroboration", {}) or {}
    entity = freshness.get("entity_disambiguation", {}) or {}
    if entity:  # only comment on this when the check actually ran
        has_wiki = entity.get("has_wikidata_or_wikipedia_sameas")
        has_registry = (entity.get("authority_sameas", {}) or {}).get("has_registry_sameas")
        if not has_wiki and not has_registry and "sameas" not in finding_titles:
            recs.append("Add authoritative sameAs references (Wikidata, Wikipedia, LinkedIn) to Organization schema markup.")

    if not coverage_blocked:
        engagement = skill_outputs.get("engagement", {}) or {}
        nav = engagement.get("navigation_reachability", {}) or {}
        unreachable_key_pages = [r for r in (nav.get("key_content_reachability") or [])
                                 if not r.get("directly_linked_from_homepage")]
        if (unreachable_key_pages
                and "unreachable" not in finding_titles and "navigation" not in finding_titles):
            recs.append("Ensure key product/service landing pages are directly linked from homepage navigation.")

        mobile = engagement.get("mobile_responsiveness", {}) or {}
        if (mobile and mobile.get("viewport_meta_present") is False
                and "viewport" not in finding_titles):
            recs.append("Include <meta name='viewport' content='width=device-width, initial-scale=1'> on all page templates.")

    return recs


FINDING_REQUIRED_FIELDS = ("title", "severity", "evidence", "suggested_action")
VALID_SEVERITIES = ("critical", "high", "medium", "low")


def _sanitize_skill_outputs(skill_outputs):
    """Make a partially-broken `skill_outputs` survivable.

    Every finding section below reads its inputs as `x.get("k", {}).get(...)`,
    which raises AttributeError the moment a value is a non-dict (`42`, a bare
    string) or an explicit `null`. Because the CLI wrapper catches that and
    falls back to the empty error report, ONE malformed sub-skill output used
    to discard every other category's perfectly good findings and emit a
    zero-finding report -- the worst possible failure mode for an audit, since
    it looks like a clean site. A sub-skill that crashed, timed out, or was
    skipped legitimately produces junk here, so this is the expected path, not
    a defensive nicety: coerce what cannot be read into `{}` and keep going on
    everything that can."""
    if not isinstance(skill_outputs, dict):
        return {}
    clean = {}
    for skill, data in skill_outputs.items():
        if not isinstance(data, dict):
            continue                       # a non-dict category has nothing readable in it
        # One level down is where sub-skill sections live (`robots`, `sitemap`,
        # `structured_data`, ...); a null there is the common shape when an
        # agent records "this check did not run".
        clean[skill] = {k: ({} if v is None else v) for k, v in data.items()}
    return clean


def _sanitize_explicit_findings(explicit_findings):
    """Caller-injected findings are part of the contract (the orchestrator may
    add agent-judged findings the scripts cannot produce), so a malformed one
    must not take the whole report down with it -- ids are assigned by
    renumbering later, which does `f["id"] = ...` and dies on a non-dict."""
    out = []
    for f in explicit_findings or []:
        if not isinstance(f, dict):
            continue
        f = dict(f)
        sev = str(f.get("severity", "medium")).lower()
        f["severity"] = sev if sev in VALID_SEVERITIES else "medium"
        f.setdefault("category", "other")
        f.setdefault("title", "Untitled finding")
        f.setdefault("evidence", "No evidence supplied with this injected finding.")
        action = f.get("suggested_action")
        if not isinstance(action, dict):
            action = {"summary": str(action) if action else "No suggested action supplied.",
                      "priority": f["severity"]}
        action.setdefault("summary", "No suggested action supplied.")
        prio = str(action.get("priority", f["severity"])).lower()
        action["priority"] = prio if prio in VALID_SEVERITIES else f["severity"]
        f["suggested_action"] = action
        out.append(f)
    return out


def _synthesize_report_impl(site_url, skill_outputs=None, explicit_findings=None, proactive_recommendations=None):
    skill_outputs = _sanitize_skill_outputs(skill_outputs)
    explicit_findings = _sanitize_explicit_findings(explicit_findings)
    if proactive_recommendations is None:
        proactive_recommendations = []
    if not isinstance(proactive_recommendations, list):
        proactive_recommendations = [str(proactive_recommendations)]

    findings = list(explicit_findings)

    # Set when the bot-identity fetch is blocked/challenged/soft-blocked by
    # live security infrastructure (WAF/CDN) rather than by robots.txt. A
    # non-JS AI crawler reaches 0% of the site in that case, so scoring
    # content readability, schema completeness, or engagement from a
    # browser-identity (or headless-render) view of pages the real crawler
    # never saw would report a false "high quality" site. Stop then and
    # there: crawl_render, readability and engagement (sections 2/3/5) skip
    # building findings entirely when this is set, and freshness_corroboration
    # (section 4) skips only its on-page content_dates/temporal_decay
    # sub-checks -- its citation_consistency/entity_disambiguation checks
    # corroborate via external web search, not this site's blocked fetch, and
    # remain valid.
    coverage_blocked = False

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
            retrieval_hit, other_hit, retrieval_ok, ineffective = split_blocked_by_crawler_class(
                robots, root_blocked, "/")
            effective = [a for a in root_blocked if a not in ineffective]
            ev_rules = "; ".join(
                f"{a} [{crawler_class_label(robots, a)}]: "
                f"'{rules.get('/', {}).get(a, {}).get('rule') or 'Disallow: /'}'"
                f" (group '{rules.get('/', {}).get(a, {}).get('group') or '?'}')"
                for a in effective)
            if not effective:
                pass  # only blocks on fetchers that ignore robots.txt: nothing is actually blocked
            elif retrieval_hit:
                add_finding(
                    findings, "crawl_access",
                    f"AI Crawler{'s' if len(effective) > 1 else ''} Blocked From the Site Root by robots.txt "
                    f"({', '.join(effective)})",
                    "critical",
                    f"robots.txt disallows the homepage (/) for {effective}. Matching rules: {ev_rules}. "
                    f"Blocked crawlers that fetch pages for live AI search / assistant answers: {retrieval_hit}."
                    + _ineffective_note(ineffective),
                    f"Update robots.txt so {', '.join(retrieval_hit)} may fetch public brand content; keep "
                    f"disallow rules scoped to genuinely private paths.",
                    plain_english="Your robots.txt tells AI crawlers not to read your homepage, including ones "
                    "that fetch pages to answer or cite in live AI search, so those assistants cannot read or "
                    "cite the site."
                )
            else:
                # Every tested retrieval crawler is still allowed: the block only
                # withholds content from model training (and, for '*', from
                # crawlers without their own robots group). That is often a
                # deliberate licensing choice, and it does not remove the site
                # from live AI search citations -- so it is not a site-wide
                # access failure and must not trip the crawl_access gate.
                add_finding(
                    findings, "crawl_access",
                    f"Only AI Training / Unlisted Crawlers Blocked From the Site Root by robots.txt "
                    f"({', '.join(other_hit)})",
                    "medium",
                    f"robots.txt disallows the homepage (/) for {other_hit}. Matching rules: {ev_rules}. "
                    f"Crawlers that fetch pages for live AI search / assistant answers were tested and remain "
                    f"allowed: {retrieval_ok}." + _ineffective_note(ineffective),
                    "If keeping content out of model training is intentional, no change is needed. If you want "
                    "the brand represented in AI models' built-in knowledge (answers given without a live web "
                    "search), allow these crawlers on public pages.",
                    plain_english="Your robots.txt keeps these crawlers from collecting your pages to train AI "
                    "models. AI assistants can still find and cite your site when they search the web live, but "
                    "models may know less about your brand when answering from memory."
                )
        if path_blocks:
            hi_lines, lo_lines = [], []
            for path, agents in path_blocks.items():
                retrieval_hit, other_hit, _, ineffective = split_blocked_by_crawler_class(robots, agents, path)
                agents = [a for a in agents if a not in ineffective]
                if not agents:
                    continue  # only fetchers that ignore robots.txt were "blocked" on this path
                # Group agents by the (rule, group) that decided them, so an agent
                # with its own robots group is not reported under another's rule.
                by_rule = {}
                for a in agents:
                    rinfo = rules.get(path, {}).get(a, {})
                    by_rule.setdefault((rinfo.get("rule"), rinfo.get("group")), []).append(a)
                parts = [f"{', '.join(f'{x} [{crawler_class_label(robots, x)}]' for x in ags)} "
                         f"via '{rule}' in group '{group}'"
                         for (rule, group), ags in by_rule.items()]
                (hi_lines if retrieval_hit else lo_lines).append(f"{path} -> " + "; ".join(parts))
            if hi_lines:
                add_finding(
                    findings, "crawl_access",
                    "Key Pages Disallowed for AI Crawlers in robots.txt",
                    "high",
                    "robots.txt disallows the following audited paths while the site root stays open: "
                    + "; ".join(hi_lines) + ".",
                    "Confirm whether these paths should be visible to AI assistants. If yes, narrow or remove "
                    "the disallow rules for the AI user-agent groups. If the exclusion is intentional, make sure "
                    "the same content is published on a crawlable URL so assistants can still cite it.",
                    plain_english="Your robots.txt tells AI crawlers not to read these specific pages, so "
                    "assistants cannot use or cite what is on them."
                )
            if lo_lines:
                add_finding(
                    findings, "crawl_access",
                    "Key Pages Disallowed Only for AI Training / Unlisted Crawlers in robots.txt",
                    "low",
                    "robots.txt disallows the following audited paths only for crawlers that collect content "
                    "for model training (or that lack their own robots group); tested live-search / assistant "
                    "crawlers remain allowed on them: " + "; ".join(lo_lines) + ".",
                    "No change is needed if excluding these pages from model training is intentional.",
                    plain_english="These pages are kept out of AI model training, but AI assistants can still "
                    "find and cite them through live web search."
                )

        # TLS certificate (check_tls.py). A certificate every standards-compliant
        # client refuses makes the site unreachable to crawlers regardless of
        # robots.txt; the dual fetch only sees a bare connection error.
        tls = access.get("tls") or {}
        if tls.get("checked") and tls.get("certificate_valid") is False:
            kind = tls.get("failure_kind") or "other"
            host = tls.get("host")
            reason = tls.get("verify_message") or kind
            if kind in ("expired", "not_yet_valid", "hostname_mismatch", "self_signed", "revoked"):
                add_finding(
                    findings, "crawl_access",
                    f"TLS Certificate Rejected by Standard Clients ({kind.replace('_', ' ')})",
                    "critical",
                    f"TLS handshake with {host}:{tls.get('port')} presented a certificate that fails verification "
                    f"(OpenSSL verify code {tls.get('verify_code')}: {reason}). HTTP clients that verify "
                    f"certificates, including AI crawlers, abort the connection before any page is fetched.",
                    {"expired": "Renew the certificate and enable automatic renewal.",
                     "not_yet_valid": "Check the server clock and the certificate's validity start date; reissue if it was dated in the future.",
                     "hostname_mismatch": f"Issue a certificate whose Subject Alternative Names include {host}, or redirect to the hostname the certificate covers.",
                     "self_signed": "Replace the self-signed certificate with one issued by a publicly trusted CA (e.g. an ACME/Let's Encrypt certificate).",
                     "revoked": "Issue and install a new certificate; the current one has been revoked."}[kind],
                    plain_english="Your website's security certificate is not accepted by standard software, so "
                    "AI crawlers and many visitors are stopped at a security error before they see any content."
                )
            elif kind == "untrusted_chain":
                add_finding(
                    findings, "crawl_access",
                    "TLS Certificate Chain Could Not Be Verified (possible missing intermediate)",
                    "high",
                    f"TLS handshake with {host}:{tls.get('port')} failed chain verification (OpenSSL verify code "
                    f"{tls.get('verify_code')}: {reason}). Most often the server does not send its intermediate "
                    f"certificate: browsers can fetch it on their own, but most non-browser HTTP clients, "
                    f"crawlers included, cannot and refuse the connection. A trust store missing on the auditing "
                    f"machine produces the same error, which is why this is not treated as certain.",
                    "Configure the server to send the full certificate chain (leaf plus intermediates), then "
                    "confirm with an external TLS checker.",
                    confidence=0.6,
                    plain_english="Your website's security certificate appears to be installed without the "
                    "supporting certificate that non-browser software needs, so some crawlers may refuse to connect."
                )
            else:
                add_finding(
                    findings, "crawl_access",
                    "TLS Certificate Failed Verification",
                    "medium",
                    f"TLS handshake with {host}:{tls.get('port')} failed certificate verification "
                    f"(OpenSSL verify code {tls.get('verify_code')}: {reason}).",
                    "Check the certificate chain and validity with an external TLS checker and correct the reported problem.",
                    confidence=0.5,
                    plain_english="Your website's security certificate did not pass a standard check, which can "
                    "stop some crawlers from connecting."
                )
        elif tls.get("checked") and tls.get("certificate_valid") and tls.get("expiring_soon"):
            add_finding(
                findings, "crawl_access",
                f"TLS Certificate Expires in {tls.get('days_remaining')} Days",
                "low",
                f"The certificate for {tls.get('host')} expires on {tls.get('not_after')} "
                f"({tls.get('days_remaining')} days from the audit; issuer: {tls.get('issuer')}). Once it "
                f"lapses, crawlers will refuse to connect.",
                "Renew the certificate now and confirm automatic renewal is working.",
                plain_english="Your website's security certificate is about to expire. If it does, crawlers and "
                "visitors will be blocked by a security error."
            )

        dual = access.get("dual_identity", {})
        comparison = dual.get("comparison_metrics", {})
        fingerprint_diverged = comparison.get("fingerprint_divergence", False)
        browser_status = dual.get("browser_status")
        bot_status = dual.get("bot_status")
        browser_ok = isinstance(browser_status, int) and 200 <= browser_status < 300
        bot_soft_blocked = dual.get("bot_soft_blocked", False)
        enforcement_mismatch = bool(
            dual.get("bot_blocked") or bot_soft_blocked
            or (dual.get("bot_challenged") and fingerprint_diverged)
        )
        if enforcement_mismatch:
            # This request was actually SENT and answered/challenged -- it was
            # not skipped_by_robots -- so whatever stopped it is enforcement
            # infrastructure (WAF/CDN/bot-management), not robots.txt. Try to
            # cite the specific permissive rule so the evidence isn't just an
            # assertion: prefer the exact gate decision recorded for this
            # fetch, falling back to the site-wide root_blocked_agents list
            # already computed above for the robots.txt findings.
            robots_bot_decision = (dual.get("robots_decisions") or {}).get("bot") or {}
            tested_agent = robots_bot_decision.get("agent")
            root_blocked_set = set(root_blocked)
            permit_evidence = None
            if robots_bot_decision.get("allowed") is True:
                permit_evidence = (
                    f"robots.txt permits this exact request (agent "
                    f"'{tested_agent or 'the tested AI bot'}': {robots_bot_decision.get('reason') or 'no matching Disallow rule'}"
                    + (f", rule '{robots_bot_decision['rule']}'" if robots_bot_decision.get("rule") else "")
                    + ") -- the block is not a robots.txt policy, it is enforced by live security "
                      "infrastructure that robots.txt has no authority over.")
            elif not root_blocked_set or (tested_agent and tested_agent not in root_blocked_set):
                permit_evidence = (
                    "robots.txt does not disallow this request at the site root "
                    f"(root_blocked_agents: {sorted(root_blocked_set) or 'none'})"
                    + (f", and the tested agent '{tested_agent}' is not among them" if tested_agent else "")
                    + " -- the block is not a robots.txt policy, it is enforced by live security "
                      "infrastructure that robots.txt has no authority over.")

            if bot_soft_blocked:
                block_desc = (f"Both identities returned an HTTP 2xx status (Browser {browser_status}, "
                             f"AI Bot {bot_status}), but the AI Bot response is a near-empty shell while the "
                             f"Browser response is real content -- a WAF/CDN interstitial served with a "
                             f"healthy status code instead of 401/403, which status-code or block-page-text "
                             f"matching alone would miss.")
            elif browser_ok:
                block_desc = (f"Browser status {browser_status} succeeded while AI Bot status {bot_status} "
                             f"was blocked/challenged with diverging fingerprints.")
            else:
                block_desc = (f"Neither identity retrieved real content (Browser status {browser_status}, "
                             f"AI Bot status {bot_status}), but their response fingerprints diverge -- the AI "
                             f"Bot identity hits a distinct, harder block than the browser identity (e.g. a "
                             f"static WAF deny vs. an interactive challenge), so fixing whatever blocks the "
                             f"browser identity would not by itself restore AI crawler access.")

            if permit_evidence:
                coverage_blocked = True
                add_finding(
                    findings, "crawl_access",
                    "robots.txt Permits Crawling But the Fetch Is Blocked Anyway (Policy/Enforcement Mismatch)",
                    "critical",
                    f"{block_desc} {permit_evidence}",
                    "Your robots.txt already grants access -- the fix belongs in your WAF/CDN/bot-management "
                    "layer (Cloudflare, Akamai, Datadome, etc.), not in robots.txt: add an allow rule or "
                    "exception for verified AI crawler User-Agents (GPTBot, ClaudeBot, PerplexityBot, "
                    "OAI-SearchBot) so enforcement matches the access policy you've already published.",
                    plain_english="Your site's published crawling rules (robots.txt) say AI crawlers are "
                    "welcome here, but your security system blocks or challenges them anyway before they ever "
                    "see a page. This is more serious than a robots.txt disallow: your own stated policy is "
                    "being silently overridden by infrastructure the crawler can't negotiate with, so the "
                    "rest of this audit could not evaluate what a real AI crawler actually sees on this site."
                )
            else:
                # Enforcement blocked the fetch, but nothing in this run lets
                # us affirmatively cite robots.txt as the permitting policy --
                # still critical, just without overclaiming the mismatch framing.
                coverage_blocked = True
                add_finding(
                    findings, "crawl_access",
                    "AI Bot Identity HTTP Fetch Blocked or Challenged",
                    "critical",
                    block_desc,
                    "Remove Cloudflare/WAF challenge rules targeting AI bot User-Agents.",
                    plain_english=("Your web security firewall (e.g. Cloudflare) lets human web browsers view "
                                   "the site normally, but blocks automated AI crawlers when they attempt to "
                                   "read your content." if browser_ok else
                                   "Your website blocks both regular browser-style requests and AI crawlers, "
                                   "but by different mechanisms -- the AI crawler hits a harder, bot-specific "
                                   "block underneath the browser-facing one.")
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
        elif dual.get("bot_fetch_failed_browser_ok"):
            # Never answered as a crawler, answered fine as a browser. Not the
            # same claim as "blocked" (no 403 was served), and one timeout can
            # be ordinary flakiness -- hence medium at reduced confidence -- but
            # silently dropping it hid both a plausible crawler-throttling
            # signature AND the fact that everything downstream in this report
            # was derived from the browser view alone.
            add_finding(
                findings, "crawl_access",
                "AI Bot Identity Fetch Never Completed While Browser Identity Succeeded",
                "medium",
                f"The same URL returned HTTP {dual.get('browser_status')} under a normal browser "
                f"user-agent but never completed under an AI-crawler user-agent "
                f"(bot result: {dual.get('bot_status')}"
                + (f", {dual.get('bot_fetch_error')}" if dual.get("bot_fetch_error") else "")
                + "). Some edge/WAF tiers throttle or blackhole a declared crawler instead of "
                  "answering 403, which looks exactly like this. Note that the rest of this report "
                  "was therefore derived from the browser view of the page only.",
                "Check WAF / CDN / rate-limit rules for user-agent-based throttling of AI crawlers "
                "(GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot), and re-run to confirm the failure "
                "is reproducible rather than a one-off timeout.",
                plain_english="Your site answered normally for a regular browser but never responded "
                "when the request identified itself as an AI crawler. That can mean AI crawlers are "
                "being quietly throttled rather than openly refused.",
                confidence=0.6
            )

        # Redirects, from data fetch_dual_identity.py already records (no new
        # requests). A crawler-identity fetch that ENDS on a 3xx never reached a
        # page: urllib gives up on a loop or after too many hops and hands back
        # the last redirect status. A long chain that does resolve is only a
        # crawl-efficiency cost.
        fetch_pages = [p for p in (access.get("sampled_pages") or []) if isinstance(p, dict)]
        if not fetch_pages and isinstance(dual.get("bot_fetch"), dict):
            fetch_pages = [dual]
        never_resolved, long_chains = [], []
        for p in fetch_pages:
            bot = p.get("bot_fetch") or {}
            status = bot.get("status")
            hops = bot.get("redirect_count") or 0
            page_url = p.get("url") or dual.get("url")
            if isinstance(status, int) and status in (301, 302, 303, 307, 308):
                never_resolved.append(f"{page_url} (stopped on HTTP {status} after {hops} redirect(s))")
            elif isinstance(status, int) and 200 <= status < 300 and hops >= 3:
                long_chains.append(f"{page_url} -> {bot.get('final_url')} ({hops} hops)")
        if never_resolved:
            add_finding(
                findings, "crawl_access",
                "Page Never Resolves for Crawlers (redirect loop or too many redirects)",
                "high",
                "Fetching as an AI crawler followed redirects without ever reaching a page: "
                + "; ".join(never_resolved) + ".",
                "Trace the redirect rules for these URLs (server, CDN and application layers) and remove the "
                "loop, so each URL resolves to a 200 page in at most one or two hops.",
                plain_english="These addresses bounce between redirects and never arrive at a page, so crawlers "
                "give up and cannot read or cite them."
            )
        if long_chains:
            add_finding(
                findings, "crawl_access",
                "Long Redirect Chains Before Reaching Content",
                "low",
                "These audited URLs resolve only after three or more redirects: " + "; ".join(long_chains) + ".",
                "Point links, canonicals and sitemap entries at the final URL, and collapse chained redirect "
                "rules into a single hop.",
                plain_english="These pages are reached only after several redirects, which slows crawlers and "
                "wastes the limited number of pages they fetch from your site."
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

        if sitemap.get("leading_whitespace_before_xml"):
            add_finding(
                findings, "crawl_access",
                "Sitemap Has Whitespace Before the XML Declaration",
                "low",
                "The sitemap was read, but its body starts with whitespace (or a byte-order mark) before "
                "`<?xml ...?>`. The XML specification requires the declaration to come first, so strict "
                "parsers reject the file outright -- this audit's own first parse attempt did.",
                "Remove the leading blank line/whitespace from the sitemap output (usually a stray newline "
                "emitted by a theme or plugin file before the sitemap generator runs).",
                plain_english="Your sitemap works, but it starts with an invisible blank line. Some crawlers "
                "treat that as a broken file and ignore the sitemap completely."
            )

        sitemap_found = pick(sitemap, "sitemap_found", "exists")
        # "The sitemap is missing" and "this auditor's fetch of it was refused"
        # are different claims with different fixes. A 403/429/5xx or a network
        # timeout means THIS request failed -- it says nothing about whether the
        # sitemap exists, and telling a site owner to "generate a sitemap" they
        # already have (and that opens fine in a browser) is wrong, confusing
        # advice. `failure_kind` (from check_sitemap.py) distinguishes them;
        # `skipped_by_robots` is coverage information already reported via
        # `collect_robots_restrictions()` below, never a defect in its own right.
        if sitemap_found is False and not sitemap.get("skipped_by_robots"):
            kind = sitemap.get("failure_kind")
            status = sitemap.get("http_status") or sitemap.get("error")
            if kind == "blocked":
                add_finding(
                    findings, "crawl_access",
                    f"Sitemap Fetch Blocked for This Auditor's Identity (HTTP {status})",
                    "high",
                    f"Requesting the sitemap returned HTTP {status} (Forbidden) rather than its content. "
                    f"This does NOT mean the sitemap is missing -- it means a WAF or bot-management layer "
                    f"refused this specific request. If the sitemap loads normally in a browser, the block "
                    f"is identity-specific (User-Agent, IP reputation, or missing browser fingerprint), and "
                    f"AI crawlers using a similar non-browser identity likely hit the same block.",
                    "Check WAF/CDN rules (Cloudflare, Akamai, etc.) for a block on non-browser requests to "
                    "/sitemap.xml specifically, and confirm declared AI crawlers (GPTBot, ClaudeBot, "
                    "PerplexityBot, Googlebot) are allow-listed there -- do not regenerate a sitemap that "
                    "already exists.",
                    plain_english="Your sitemap file itself may be fine, but your security system is "
                    "blocking automated requests to it -- including from AI crawlers -- while still letting "
                    "regular browsers through, which is why it looks fine when you check it yourself."
                )
            elif kind == "rate_limited":
                add_finding(
                    findings, "crawl_access",
                    "Sitemap Fetch Rate-Limited (HTTP 429)",
                    "low",
                    "The sitemap request was rate-limited (HTTP 429) rather than answered. This is very "
                    "likely transient load-balancer throttling, not evidence the sitemap is missing.",
                    "Review rate-limiting thresholds so a single crawler request isn't throttled; re-run "
                    "the audit to confirm this wasn't a one-off.",
                    plain_english="Your server briefly refused this request for being too frequent. This "
                    "is usually temporary and not a sign anything is actually broken.",
                    confidence=0.6
                )
            elif kind == "server_error":
                add_finding(
                    findings, "crawl_access",
                    f"Sitemap Endpoint Returned a Server Error (HTTP {status})",
                    "high",
                    f"Requesting the sitemap returned HTTP {status}, a server-side failure -- distinct from "
                    f"the sitemap simply not existing (that would be a 404).",
                    "Check server/application logs for the error generating this response; this is a "
                    "server bug to fix, not a sitemap to create.",
                    plain_english="Your server is erroring out when asked for the sitemap, rather than "
                    "serving it or cleanly saying it doesn't exist."
                )
            elif kind == "network_unreachable":
                add_finding(
                    findings, "crawl_access",
                    "Sitemap Could Not Be Reached (Network Error)",
                    "medium",
                    f"The sitemap request failed at the network level ({sitemap.get('error')}) -- a timeout, "
                    f"DNS failure, or connection refusal, not a 404. This may be transient.",
                    "Verify the sitemap URL resolves and responds from outside your own network; re-run "
                    "the audit to rule out a one-off network blip before assuming the sitemap is broken.",
                    plain_english="This audit's connection to your sitemap failed outright (not a clean "
                    "'not found') -- that could be a real hosting/DNS issue or just a temporary blip.",
                    confidence=0.6
                )
            elif kind == "invalid_xml_200":
                add_finding(
                    findings, "crawl_access",
                    "Sitemap URL Responds but Content Is Not Valid XML",
                    "high",
                    f"The sitemap URL answered HTTP 200 but the body does not parse as XML "
                    f"({sitemap.get('error')}). A 200 status with a non-XML body is often the signature of "
                    f"a bot-management challenge/interstitial page intercepting the request before it "
                    f"reaches the real sitemap -- though it can also be a genuinely malformed sitemap file.",
                    "Fetch this URL with a plain non-browser client (curl/wget) and inspect the body: if "
                    "it's an HTML challenge/verification page, fix the WAF rule for this path rather than "
                    "the sitemap; if it's genuinely malformed XML, fix the sitemap generator.",
                    plain_english="Something answers at your sitemap's address, but it isn't a real "
                    "sitemap -- this is frequently a security checkpoint intercepting non-browser visitors, "
                    "not necessarily a broken file.",
                    confidence=0.6
                )
            else:
                # kind in ("not_found", "other", None): no signal that a request
                # was actively refused, so "missing" remains the best-supported claim.
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
    if render and not coverage_blocked:
        barriers    = render.get("rendering_barriers", {})
        sd_hydr_raw = render.get("structured_data_hydration", {})
        sd_hydr     = sd_hydr_raw.get("hydration_analysis", {})
        js_redirect = render.get("client_side_redirects", {})

        csr_signals     = barriers.get("client_side_rendering_signals", {})
        waf_info        = barriers.get("waf_interstitial", {})
        hydration_gaps  = barriers.get("hydration_gaps", {})
        word_counts     = barriers.get("word_counts", {})

        # Disclosure, not a site defect: THIS RUN had no way to obtain a
        # rendered DOM at all (no browser installed / cannot start one in this
        # sandbox), so every check below fell back to raw-HTML-only heuristics
        # for every page, not just this one. A report with zero client-side-
        # rendering findings could mean "genuinely clean site" or "we had no
        # way to check" -- the reader must be told which, rather than a silent
        # fallback that looks identical to a real measured pass.
        dom_avail = pick(render, "dom_render_availability", "render_availability", "dom_render") or {}
        if dom_avail.get("available") is False:
            reason = dom_avail.get("unavailable_reason")
            if reason in ("no_browser_installed", "root_no_sandbox"):
                add_finding(
                    findings, "crawl_render",
                    "No Headless Browser Available for This Audit Environment",
                    "low",
                    "This run had no usable Chrome, Edge, or Chromium browser available ("
                    + ("no browser found on this machine" if reason == "no_browser_installed"
                       else "the browser refused to start without root sandbox privileges")
                    + "), so every client-side-rendering check in this report ran on raw HTML only, "
                      "with no measured comparison against the actual rendered DOM for any page.",
                    "Re-run this audit in an environment with Chrome, Edge, or Chromium installed (or "
                    "with a native headless-browser tool available to the orchestrating agent) to "
                    "directly measure the raw-vs-rendered gap instead of inferring it from static HTML.",
                    plain_english="This specific audit run could not use a browser to see what your "
                    "pages look like after JavaScript runs -- it could only read the raw HTML. Any "
                    "client-side-rendering findings above (or the absence of any) are inferred, not "
                    "directly measured, so genuinely JavaScript-only content may be under-reported.",
                    confidence=1.0
                )
            elif reason in ("timed_out", "render_failed", "launch_failed"):
                add_finding(
                    findings, "crawl_render",
                    "Rendered DOM Could Not Be Captured for This Page",
                    "low",
                    f"Attempting to render this specific page failed ({reason.replace('_', ' ')}), so "
                    f"this page's client-side-rendering checks ran on raw HTML only, without a measured "
                    f"comparison. (A browser was available and other pages may have rendered fine.)",
                    "Re-run the render step for this page; a page that fails consistently may be too "
                    "slow or resource-heavy to render within the audit's time budget.",
                    plain_english="This audit tried to see what this page looks like after JavaScript "
                    "runs, but the attempt failed here specifically, so findings about it are inferred, "
                    "not measured.",
                    confidence=0.8
                )

        # Sentence-level evidence, present only when a rendered DOM was supplied.
        # Counts say how much is missing; this says WHICH text is missing, which
        # is what makes the fix concrete for the site owner.
        parity = barriers.get("content_parity") or {}
        parity_note = ""
        if parity.get("missing_text_samples"):
            samples = "; ".join(f'"{s}"' for s in parity["missing_text_samples"][:2])
            parity_note = (
                f" Compared against the rendered DOM, {parity.get('missing_from_raw_count')} of "
                f"{parity.get('rendered_sentence_count')} sentences are absent from the raw HTML "
                f"({parity.get('content_parity_pct')}% content parity). Text a non-JS crawler cannot "
                f"see includes: {samples}.")

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
                f"Both content words ({eff_raw} effective raw words) and schema data (JS-trapped types: {trapped}) are loaded exclusively via JavaScript. SPA mount points: {mounts}. Frameworks: {frameworks}." + parity_note,
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
                evidence_str + "." + parity_note,
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

        # --- Internal links that exist only after JavaScript runs ---
        # A crawler traverses <a href> in the raw HTML. Navigation built from
        # click handlers or mounted menus is invisible to it, so the interior
        # pages behind that navigation are never discovered from this page.
        #
        # A flat count alone under-flags small sites: 3 JS-only links out of a
        # 4-link page is a severe navigation gap (most of the site is
        # unreachable) but never reaches the absolute floor below. So the
        # trigger is either condition:
        #   - LINK_DISCOVERY_ABSOLUTE_THRESHOLD (5) JS-only links regardless of
        #     page size -- one or two dynamic widgets adding links is
        #     ordinary, but 5+ is a systemic pattern on any size site;
        #   - a share of this page's discoverable links, above
        #     LINK_DISCOVERY_PROPORTION_FLOOR (2, so a single JS-only link out
        #     of a tiny page isn't read as "most of the page"), reaching
        #     LINK_DISCOVERY_PROPORTION_THRESHOLD (25%) -- a quarter or more of
        #     a page's links being JS-only is a real gap even on a small page
        #     that will never accumulate 5 links total.
        LINK_DISCOVERY_ABSOLUTE_THRESHOLD = 5
        LINK_DISCOVERY_PROPORTION_FLOOR = 2
        LINK_DISCOVERY_PROPORTION_THRESHOLD = 0.25

        link_disc = barriers.get("link_discovery") or {}
        js_only_count = link_disc.get("links_only_after_js_count") or 0
        rendered_total = link_disc.get("rendered_internal_links") or 0
        js_only_share = (js_only_count / rendered_total) if rendered_total > 0 else 0.0

        triggered_by_count = js_only_count >= LINK_DISCOVERY_ABSOLUTE_THRESHOLD
        triggered_by_share = (js_only_count >= LINK_DISCOVERY_PROPORTION_FLOOR
                              and js_only_share >= LINK_DISCOVERY_PROPORTION_THRESHOLD)

        if triggered_by_count or triggered_by_share:
            share_note = (f" -- {js_only_share:.0%} of this page's {rendered_total} discoverable internal links"
                         if triggered_by_share else "")
            add_finding(
                findings, "crawl_render",
                "Internal Links Discoverable Only After JavaScript Runs",
                "medium",
                f"{js_only_count} internal links exist in the rendered DOM but not in "
                f"the raw HTML ({link_disc.get('raw_internal_links')} raw vs "
                f"{rendered_total} rendered{share_note}). Examples: "
                f"{link_disc.get('links_only_after_js_samples')}.",
                "Emit navigation as real <a href=\"...\"> anchors in the server-rendered HTML (they can still be "
                "enhanced by JavaScript), so crawlers can reach these pages without executing scripts.",
                plain_english="Your menus and links are built by JavaScript, so crawlers reading the plain page "
                "never see them and cannot find the pages they lead to."
            )

    # 3. Readability Skill Findings
    readability = skill_outputs.get("readability", {})
    if readability and not coverage_blocked:
        struct_data = readability.get("structured_data", {})
        # check_structured_data.py has always reported unparseable JSON-LD in
        # `parse_errors`, but nothing read it: a page whose only JSON-LD block
        # is broken was reported as "Missing" (wrong fix: add schema, when it
        # already exists and only needs its syntax corrected), and a broken
        # block beside a valid one was not reported at all.
        parse_errors = (struct_data or {}).get("parse_errors") or []
        total_blocks = (struct_data or {}).get("total_json_ld_blocks", 0) or 0

        def _parse_error_detail(errs):
            return "; ".join(
                f"block #{e.get('block_index', '?')}: {e.get('error', 'parse error')}"
                + (f" (starts: {e['snippet'][:60]!r})" if e.get("snippet") else "")
                for e in errs[:3])

        if struct_data and struct_data.get("recognized_entities_count", 0) == 0:
            if parse_errors and total_blocks:
                add_finding(
                    findings, "readability",
                    "Schema.org JSON-LD Present but Unparseable",
                    "high",
                    f"The page ships {total_blocks} JSON-LD block(s), {len(parse_errors)} of which fail to parse "
                    f"as JSON, so no Schema.org entity can be read from it: {_parse_error_detail(parse_errors)}.",
                    "Fix the JSON syntax in the existing <script type=\"application/ld+json\"> block(s) -- "
                    "commonly a trailing comma, an unescaped quote, or a template placeholder left unrendered -- "
                    "and re-validate with a structured-data validator.",
                    plain_english="Your page does include machine-readable brand data, but it contains a syntax "
                    "error, so search engines and AI systems discard all of it."
                )
            else:
                add_finding(
                    findings, "readability",
                    "Missing Schema.org JSON-LD Structured Data",
                    "high",
                    "Zero recognized Schema.org entities detected on target page.",
                    "Add Schema.org JSON-LD markup matching page entity (Organization, Product, Article, etc.).",
                    plain_english="Your page lacks standardized machine-readable data (Schema.org JSON-LD), which acts like a digital business card telling AI search engines exactly what your brand, product, or organization represents."
                )
        elif parse_errors:
            add_finding(
                findings, "readability",
                f"{len(parse_errors)} of {total_blocks or '?'} JSON-LD Blocks Could Not Be Parsed",
                "medium",
                f"Some Schema.org data on the page is valid, but {len(parse_errors)} block(s) fail to parse and "
                f"are ignored by consumers: {_parse_error_detail(parse_errors)}.",
                "Fix the JSON syntax in the failing block(s) so the entities they describe are not silently dropped.",
                plain_english="Part of your page's machine-readable data has a syntax error, so that part is "
                "ignored by search engines and AI systems."
            )

        # Schema can be present, valid and still answer neither question an
        # answer engine asks: who publishes this page, and what is it about.
        # `entity_grounding` reports which of the two the markup supplies. It
        # asserts "structural only" solely when every entity is a classified
        # scaffolding/value type, so an unrecognised type never triggers a
        # finding below.
        #
        # `readability.additional_pages` (optional, [{url, structured_data}])
        # lets a run that already parsed an interior page report it here. It
        # costs no extra request -- that page's HTML was fetched by the render
        # or engagement pass -- and it is where this gap usually lives: a
        # homepage carries the Organization block while product and article
        # pages ship nothing but their breadcrumb trail.
        graded_pages = [(site_url, (struct_data or {}).get("entity_grounding") or {})]
        for extra in (readability.get("additional_pages") or []):
            if isinstance(extra, dict):
                extra_sd = extra.get("structured_data") or {}
                if extra_sd.get("recognized_entities_count", 0) > 0:
                    graded_pages.append((extra.get("url") or "(unnamed page)",
                                         extra_sd.get("entity_grounding") or {}))

        navigation_only = [(u, g) for u, g in graded_pages if g.get("structural_only")]
        if navigation_only:
            scaffolding = sorted({t for _, g in navigation_only
                                  for t in (g.get("structural_entity_types") or [])})
            page_list = ", ".join(u for u, _ in navigation_only[:3])
            more = f" (and {len(navigation_only) - 3} more)" if len(navigation_only) > 3 else ""
            add_finding(
                findings, "readability",
                "Structured Data Describes Only Page Navigation, Not the Page's Subject",
                "medium",
                f"On {page_list}{more}, every Schema.org entity is page scaffolding or a value object "
                f"({', '.join(scaffolding) or 'breadcrumb/list types'}) -- there is no entity describing "
                "the product, article, service or organization the page is actually about. The markup "
                "validates, but an AI answer engine learns only the breadcrumb trail from it.",
                "Add a subject entity matching each page (Product, Article, Service, Organization, ...) "
                "alongside the existing BreadcrumbList, carrying at minimum name, description and url.",
                plain_english="Those pages' machine-readable data describes only their breadcrumb trail. "
                "AI systems can see where each page sits in your menu, but not what it is about."
            )

        root_grounding = (struct_data or {}).get("entity_grounding") or {}
        if ((struct_data or {}).get("recognized_entities_count", 0) > 0
                and root_grounding.get("is_site_root")
                and not root_grounding.get("has_identity_entity")
                and not root_grounding.get("unclassified_entity_types")
                and not root_grounding.get("structural_only")):
            subject_types = root_grounding.get("subject_entity_types") or []
            add_finding(
                findings, "readability",
                "Homepage Schema Has No Organization or Brand Identity Entity",
                "medium",
                "The homepage carries Schema.org markup "
                + (f"({', '.join(subject_types)}) " if subject_types else "")
                + "but no Organization, Brand, Person or WebSite entity, so nothing in the structured "
                "data states who the site belongs to. Identity is the anchor every other brand signal "
                "(sameAs, logo, contact points) attaches to.",
                "Add an Organization (or Brand/Person for a personal brand) entity to the homepage "
                "JSON-LD with name, url, logo and sameAs, and reference it as the publisher of the "
                "page's other entities.",
                plain_english="Your homepage has machine-readable data, but none of it names the "
                "organization behind the site. Adding an Organization entry gives AI systems a single "
                "identity to attach your brand facts to.",
                confidence=0.9
            )

        # A `description` is the sentence an answer engine can quote verbatim.
        # This is a presence/length test only -- no judgement about wording.
        desc_cov = (struct_data or {}).get("description_coverage") or {}
        if desc_cov.get("describable_entities", 0) > 0:
            missing_types = desc_cov.get("missing_description_types") or []
            short_entities = desc_cov.get("short_description_entities") or []
            min_chars = desc_cov.get("min_useful_chars", 25)
            if missing_types or short_entities:
                parts = []
                if missing_types:
                    parts.append(f"no description at all on: {', '.join(missing_types)}")
                if short_entities:
                    parts.append("description shorter than "
                                 f"{min_chars} characters on: "
                                 + ", ".join(f"{e.get('type')} ({e.get('length')} chars: "
                                             f"{e.get('text', '')!r})" for e in short_entities))
                add_finding(
                    findings, "readability",
                    "Schema Entities Missing a Usable description Field",
                    "low",
                    f"{len(missing_types) + len(short_entities)} of "
                    f"{desc_cov.get('describable_entities')} describable Schema.org entities lack a "
                    f"quotable description -- {'; '.join(parts)}.",
                    "Add a one- or two-sentence `description` to each entity stating plainly what it is, "
                    "in the same words a person would use when asked.",
                    plain_english="Some of your structured data entries have no summary sentence. That "
                    "sentence is often exactly what an AI assistant quotes when it describes you, so "
                    "leaving it out means the assistant has to invent its own wording."
                )

        # FAQ schema is only trustworthy when its answers correspond to something
        # actually on the page. A near-total vocabulary mismatch between a
        # schema answer and the page's own visible text means either the schema
        # is stale (left over after a content edit) or was never meant to be
        # read by a visitor at all -- both are worth surfacing. This is a
        # word-overlap heuristic, not proof of intent: it is gated to only fire
        # on a near-total mismatch, specifically so a legitimate paraphrase is
        # never mistaken for absence.
        faq_check = (struct_data or {}).get("faq_visible_text_check") or {}
        if faq_check.get("checked") and faq_check.get("low_overlap_count"):
            low_pairs = faq_check.get("low_overlap_pairs") or []
            examples = "; ".join(
                f"{p.get('question')!r} (answer shares {p.get('word_overlap_ratio', 0):.0%} of its "
                f"vocabulary with the visible page)" for p in low_pairs[:3])
            add_finding(
                findings, "readability",
                "FAQ Schema Answer Not Found in Visible Page Content",
                "medium",
                f"{faq_check['low_overlap_count']} of {faq_check.get('pairs_checked')} FAQPage question/answer "
                f"pairs have an answer sharing almost no vocabulary with anything visible on the page: "
                f"{examples}.",
                "Confirm each FAQ answer in the JSON-LD still matches content a visitor can actually see. "
                "Stale schema left over after an edit, or FAQ markup never shown on the page, both give an "
                "AI system a fact that isn't really there.",
                plain_english="Some of your FAQ structured data doesn't match anything visible on the page. "
                "That could be an outdated answer, or FAQ data that was never actually shown to visitors -- "
                "either way, an AI system reading only your visible page won't find that answer.",
                confidence=0.6
            )

        # Schema.org attribute completeness across the 9 audited types. Each
        # rule aggregates every entity of that type on the page into ONE
        # finding, so a listing page with 20 incomplete Products reports one
        # actionable gap rather than twenty copies of it.
        for comp_key, type_label, severity, field_map, why in SCHEMA_COMPLETENESS_RULES:
            incomplete = []
            for ent in ((struct_data or {}).get("entities") or []):
                comp = ent.get(comp_key)
                if not isinstance(comp, dict):
                    continue
                missing = [prop for flag, prop in field_map if comp.get(flag) is False]
                if missing:
                    incomplete.append((ent.get("name") or "(unnamed)", missing))
            if not incomplete:
                continue
            all_missing = sorted({p for _, props in incomplete for p in props})
            examples = "; ".join(f"{nm!r} missing {', '.join(props)}"
                                 for nm, props in incomplete[:3])
            more = f" (and {len(incomplete) - 3} more)" if len(incomplete) > 3 else ""
            add_finding(
                findings, "readability",
                f"Incomplete {type_label} Schema: Missing {', '.join(all_missing)}",
                severity,
                f"{len(incomplete)} {type_label} "
                f"{'entity declares' if len(incomplete) == 1 else 'entities declare'} "
                f"Schema.org markup but {'omits' if len(incomplete) == 1 else 'omit'} "
                f"required properties -- {examples}{more}. "
                f"The markup parses, but {why}.",
                f"Populate {', '.join(all_missing)} on every {type_label} entity, and re-validate "
                f"with a structured-data testing tool.",
                plain_english=f"Your {type_label} structured data is present but incomplete, so an AI "
                f"system reading it still can't answer the questions those missing fields would cover."
            )

        # FAQPage: questions declared but not answerable (a Question node with
        # no acceptedAnswer text is an unanswered question in machine form).
        faq_incomplete = []
        for ent in ((struct_data or {}).get("entities") or []):
            faq = ent.get("faq_completeness")
            if isinstance(faq, dict) and faq.get("questions_detected", 0) > faq.get("questions_complete", 0):
                faq_incomplete.append((faq.get("questions_detected", 0), faq.get("questions_complete", 0)))
        if faq_incomplete:
            detected = sum(d for d, _ in faq_incomplete)
            complete = sum(c for _, c in faq_incomplete)
            add_finding(
                findings, "readability",
                "FAQ Schema Contains Questions Without Usable Answers",
                "medium",
                f"{detected - complete} of {detected} Question entities in FAQPage markup lack a "
                f"question name or an acceptedAnswer with text, so they carry a question an assistant "
                f"cannot answer from the markup.",
                "Give every Question a `name` and an `acceptedAnswer` containing real answer `text` -- "
                "an incomplete pair is worse than no FAQ markup, since it advertises an answer that "
                "isn't there.",
                plain_english="Some entries in your FAQ data have a question but no usable answer "
                "attached, so AI systems see the question and find nothing to quote."
            )

        # BreadcrumbList with zero items is broken markup, not navigation.
        empty_breadcrumbs = sum(
            1 for ent in ((struct_data or {}).get("entities") or [])
            if isinstance(ent.get("breadcrumb_completeness"), dict)
            and ent["breadcrumb_completeness"].get("item_count", 0) == 0)
        if empty_breadcrumbs:
            add_finding(
                findings, "readability",
                "BreadcrumbList Schema Declared With No Items",
                "low",
                f"{empty_breadcrumbs} BreadcrumbList entit{'y' if empty_breadcrumbs == 1 else 'ies'} "
                f"contain an empty or missing itemListElement, so the breadcrumb trail conveys nothing.",
                "Populate itemListElement with the ordered ListItem entries for this page's path, or "
                "remove the empty BreadcrumbList entirely.",
                plain_english="Your page declares breadcrumb navigation data but leaves it empty, which "
                "tells AI systems nothing about where this page sits in your site."
            )

        # E-E-A-T authorship: repeatedly the single most-cited concrete AI-
        # trust signal in published GEO/AEO guidance -- a real named byline
        # versus a missing or CMS-default one. Only the narrow, unambiguous
        # placeholder case is flagged (see GENERIC_AUTHOR_PLACEHOLDERS); a
        # legitimate organizational byline ("Staff Writer") never is.
        # Named readability_entities to avoid colliding with the unrelated
        # "entities" local used later in the freshness_corroboration section.
        readability_entities = (struct_data or {}).get("entities") or []
        generic_author_articles = [e for e in readability_entities
                                   if (e.get("article_completeness") or {}).get("generic_placeholder_author")]
        if generic_author_articles:
            names = sorted({n for e in generic_author_articles
                           for n in (e.get("article_completeness") or {}).get("author_names", [])})
            add_finding(
                findings, "readability",
                "Article Byline Uses a CMS Placeholder Name Instead of a Real Author",
                "low",
                f"{len(generic_author_articles)} article/blog entit(y/ies) credit only a generic "
                f"placeholder byline ({', '.join(names)}), not a real named person or organization.",
                "Credit a real author (or a clearly-named organizational byline like 'Acme Editorial "
                "Team') instead of a CMS default account name.",
                plain_english="This content's author field is a leftover system account name, not a "
                "real byline. A named author is one of the most consistently cited trust signals for "
                "AI systems deciding whether to cite a source.",
                confidence=0.6
            )

        # NAP (Name/Address/Phone) consistency: the on-site instance of "does
        # the web agree on this fact" -- schema and visible text disagreeing
        # on contact details is a concrete, checkable trust problem, not a
        # subjective one. Phone numbers compare as digit tokens; addresses
        # via word-overlap, both tolerant of formatting/paraphrase variance
        # so only a genuine mismatch is reported.
        nap = (struct_data or {}).get("nap_consistency") or {}
        if nap.get("checked") and nap.get("mismatch_count"):
            details = []
            for m in nap.get("mismatches") or []:
                if m.get("field") == "telephone":
                    details.append(f"schema lists phone {m.get('schema_value')!r}, not found anywhere visible")
                else:
                    details.append(f"schema lists address {m.get('schema_value')!r}, sharing only "
                                   f"{m.get('word_overlap_ratio', 0):.0%} of its wording with the visible page")
            add_finding(
                findings, "readability",
                "Business Contact Details Inconsistent Between Schema and Visible Page",
                "medium",
                f"{nap['mismatch_count']} contact detail(s) in Organization/LocalBusiness schema don't "
                f"match the page's own visible text: {'; '.join(details)}.",
                "Confirm the phone number and address in your JSON-LD match what's actually printed "
                "on the page -- inconsistent contact details across sources undermine exactly the "
                "kind of cross-source agreement AI systems use to trust a fact.",
                plain_english="Your structured data lists contact details that don't match what's "
                "visibly printed on the page. AI systems (and customers) checking your phone number "
                "or address against the visible page won't find what the schema claims.",
                confidence=0.6
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
            csr_signals = ((skill_outputs.get("crawl_render", {}) or {})
                           .get("rendering_barriers", {})
                           .get("client_side_rendering_signals", {})) or {}
            render_gap = bool(csr_signals.get("likely_client_side_rendering_barrier"))
            # "The h1 is client-injected" is a claim ABOUT JAVASCRIPT, so it
            # needs javascript evidence. `subs_present` alone (h2s but no h1)
            # used to assert it outright -- which on a static, script-free page
            # produced not just a wrong finding but actively wrong advice
            # ("move its rendering to the server"), when the real fix is simply
            # to author an <h1>. If the render skill ran and found no barrier
            # AND no client-side machinery of any kind, that is positive
            # evidence against client injection, and it wins over the
            # structural hunch.
            render_checked = bool(csr_signals)
            render_rules_out_csr = render_checked and not render_gap and not any((
                csr_signals.get("spa_mount_points"),
                csr_signals.get("detected_frameworks"),
                csr_signals.get("inline_framework_signals"),
                csr_signals.get("data_islands_detected"),
                csr_signals.get("custom_web_elements_count"),
            ))
            levels = semantic.get("subheading_levels_present") or []
            if render_gap or (subs_present and not render_rules_out_csr):
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
                    "so they cannot see what the page's main topic is.",
                    # Measured barrier = certain. Structural hunch with no render
                    # pass to corroborate it = a guess, and priced as one.
                    confidence=1.0 if render_gap else 0.6
                )
            else:
                # Either there were no sub-headings to hint at client injection,
                # or the render pass positively ruled it out (no barrier, no
                # framework, no mount point) -- on a script-free page the h1 was
                # simply never authored, and "author one" is the correct fix.
                why = ("the render pass found no client-side rendering barrier and no framework, "
                       "mount point or data island on this page, so the heading is not being "
                       "injected by JavaScript -- it was never written"
                       if render_rules_out_csr and subs_present else
                       "there are no sub-headings that would suggest one is being injected client-side")
                add_finding(
                    findings, "readability",
                    "Missing primary <h1> header tag",
                    "medium",
                    f"Page HTML contains no <h1> tag for topic orientation, and {why}.",
                    "Add a clear, topic-defining <h1> tag at the top of the page content.",
                    plain_english="The main heading tag (<h1>) is missing, making it harder for AI readers to instantly identify the primary topic of your page."
                )
        elif semantic.get("multiple_h1"):
            # Emitted by check_semantic_structure.py since the beginning and
            # never read until now: a page with several <h1>s has no single
            # declared topic, so an extractor has to guess which one the page
            # is actually about. Kept `low` because HTML5 sectioning technically
            # permits multiple <h1>s -- it is an extraction-clarity problem,
            # not invalid markup.
            h1_count = headings_blk.get("h1_count")
            h1_texts = [h.get("text") for h in (headings_blk.get("sequence") or [])
                        if h.get("level") == 1][:4]
            add_finding(
                findings, "readability",
                f"Multiple <h1> Headings Compete to Define the Page Topic ({h1_count} found)",
                "low",
                f"The page declares {h1_count} separate <h1> headings: "
                + "; ".join(repr(t) for t in h1_texts if t)
                + ". With no single top-level heading, an AI extractor has no unambiguous signal "
                  "for what this page is primarily about.",
                "Keep one <h1> that states the page's topic and demote the rest to <h2>/<h3> so the "
                "outline has a single root.",
                plain_english="Your page has several 'main' headings at the same top level, so there is "
                "no single clear answer to 'what is this page about?' for an AI system reading it."
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

        # Question-phrased headings are the pattern AI answer engines extract
        # most reliably (a heading ending "?" sets up a direct-answer
        # expectation immediately below it). This checks PRESENCE only -- a
        # one-word answer like "No." still counts as answered -- so it only
        # flags a heading with genuinely nothing (or only another heading)
        # underneath it, never a subjective "answer quality" judgment.
        question_headings = semantic.get("question_headings") or {}
        unanswered = [q for q in (question_headings.get("detected") or [])
                     if not q.get("has_content_following")]
        if unanswered:
            examples = ", ".join(repr(q["heading_text"]) for q in unanswered[:3])
            add_finding(
                findings, "readability",
                "Question-Style Heading With No Content Following It",
                "medium",
                f"{len(unanswered)} question-phrased heading(s) have no real text before the next "
                f"heading (or the end of the page): {examples}.",
                "Add at least a short, direct answer immediately after each question-style heading -- "
                "even a single sentence gives an AI system something to extract for that question.",
                plain_english="Some of your headings are phrased as questions but have nothing answering "
                "them right underneath. AI systems that extract question-and-answer pairs from your page "
                "find the question with no answer to pair it with."
            )

        # 44% of AI citations in published studies come from the first 30% of
        # a document -- this checks whether real content is actually near the
        # top, or buried under filler. It is a word-count-position heuristic,
        # not a judgment of what counts as "informative": a page where no
        # single block ever reaches the substantial-length floor, or one with
        # too little main content to measure meaningfully, reports
        # checked=False rather than a guessed verdict either way.
        content_pos = semantic.get("content_positioning") or {}
        if content_pos.get("checked") and content_pos.get("front_loaded") is False:
            add_finding(
                findings, "readability",
                "Substantial Content Buried Deep in the Page",
                "low",
                f"The first substantial block of text doesn't appear until "
                f"{content_pos.get('first_substantial_block_fraction', 0):.0%} of the way through the "
                f"page's main content ({content_pos.get('first_substantial_block_word_offset')} of "
                f"{content_pos.get('total_main_words')} words): "
                f"{content_pos.get('first_substantial_block_preview', '')!r}...",
                "Move the page's core informative content earlier, ahead of introductory or promotional "
                "copy, so both readers and AI systems reach it sooner.",
                plain_english="The real substance of this page doesn't show up until well into it. Readers "
                "and AI systems that only look at the start of a page may miss it entirely.",
                confidence=0.5
            )

        consistency = pick(readability, "content_consistency", "context_consistency", default={}) or {}
        cons_verdict = consistency.get("agent_verdict")
        cons_flag = (cons_verdict.get("inconsistent") if isinstance(cons_verdict, dict)
                     else consistency.get("contains_inconsistency"))
        if cons_flag:
            summ = consistency.get("overall_summary", {}) or {}
            unver = consistency.get("unverified_facts_for_agent", []) or []
            detail = ", ".join(f"{u.get('field')}={u.get('structured_value')!r}" for u in unver[:5])
            evaluated = summ.get("total_facts_evaluated") or 0
            verified = summ.get("total_facts_verified") or 0
            agent_confirmed = isinstance(cons_verdict, dict)
            add_finding(
                findings, "readability",
                "Structured Data Contradicts the Page's Visible Text" if agent_confirmed
                else "Structured Data Values Not Found in the Page's Visible Text",
                # Unconfirmed string matching can't tell a real mismatch from a
                # differently-formatted value, so it doesn't claim a high "contradiction".
                "high" if agent_confirmed else "medium",
                f"{max(evaluated - verified, 0)} of {evaluated} "
                f"facts declared in Schema.org markup could not be found in the page's visible text"
                f"{' (' + detail + ')' if detail else ''}. "
                f"Basis: {'agent judgment' if agent_confirmed else 'string-match heuristic -- agent confirmation recommended'}.",
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
                        "Manual check: use View Page Source (Ctrl+U / Cmd+Option+U) — NOT the DevTools "
                        "Elements panel or Console — and search (Ctrl+F) for '<img'. DevTools/Console "
                        "reflects the page AFTER JavaScript has run and can add, remove, or relabel "
                        "images, and never shows <noscript> content at all (a common home for a tracking "
                        "pixel's fallback <img>, which IS present in the raw HTML crawlers read) — so a "
                        "DevTools count can miss or disagree with what this finding measured. For an "
                        "exact, scriptable count instead of manual scanning: "
                        "curl -s \"<page-url>\" | grep -oE '<img[^>]*>' | grep -vc ' alt='"
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
                        "Manual check: use View Page Source (Ctrl+U), not DevTools/Console (which "
                        "reflects the post-JavaScript DOM, not the raw HTML crawlers read), and search "
                        "for 'alt=\"' to inspect the values. For a full list instead of manual scanning: "
                        "curl -s \"<page-url>\" | grep -oE 'alt=\"[^\"]*\"'"
                    )
                )

            # --- Category 1b: link/button with NO accessible name at all ---
            # Distinct from the missing/decorative-alt counts above: those
            # count EVERY such image, most of which are correctly decorative
            # (a spacer, a background flourish) -- alt="" on those is the
            # CORRECT, W3C-recommended choice and must never be treated as a
            # defect. This is narrower and unambiguous: a link/button whose
            # ONLY content is an unlabeled image has NO accessible name at
            # all, for a screen reader or a non-visual AI crawler trying to
            # understand navigation alike -- an objective WCAG 2.4.4/4.1.2
            # failure, not a judgment call about alt-text quality.
            unlabeled = nontext.get("unlabeled_interactive_images", {})
            unlabeled_count = unlabeled.get("count", 0)
            unlabeled_details = unlabeled.get("details") or []
            if unlabeled_count > 0:
                # No backslash inside an f-string {...} expression -- that is
                # a SyntaxError before Python 3.12, and "Requires Python 3"
                # (per this skill's SKILL.md) does not guarantee 3.12+.
                ALT_EMPTY_LABEL = 'alt=""'
                example_parts = []
                for d in unlabeled_details[:3]:
                    alt_desc = "no alt attribute" if d.get("alt_kind") == "missing" else ALT_EMPTY_LABEL
                    example_parts.append(f"{d.get('tag')} ({alt_desc}): {d.get('snippet')}")
                examples = "; ".join(example_parts)
                add_finding(
                    findings, "readability",
                    f"Link/Button With No Accessible Name ({unlabeled_count} found)",
                    "high",
                    f"{unlabeled_count} <a>/<button> element(s) have no accessible name at all: their "
                    f"only content is an <img> with no alt text (empty or absent) and there is no other "
                    f"text, aria-label, or title on the element. Examples: {examples}.",
                    "Give each of these elements an accessible name: add real text alongside the image, "
                    "set aria-label/title on the link or button, or give the image itself a descriptive "
                    "alt (e.g. alt=\"Shop now\") if it is the only content.",
                    plain_english="Some of your clickable links/buttons contain only an image with no "
                    "text description anywhere -- to a screen reader, and to an AI crawler trying to "
                    "understand your site's navigation, these controls are completely blank and their "
                    "purpose is unknowable.",
                    confidence=1.0
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
                        "Manual check: use View Page Source (Ctrl+U), not DevTools/Console — DevTools "
                        "reflects the post-JavaScript DOM (which can add labels or inject SVGs that "
                        "were never in the raw HTML), not what a non-JS crawler reads. Search for '<svg' "
                        "and check each match for aria-hidden, aria-label, or a <title> child."
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
                        "Manual check: use View Page Source (Ctrl+U), not DevTools/Console (an iframe's "
                        "title can be set by JavaScript after load, which the raw HTML a crawler reads "
                        "never had). Search for 'youtube' or 'vimeo' and check each <iframe> for a title "
                        "attribute."
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
                        "Manual check: use View Page Source (Ctrl+U), not DevTools/Console (a framework "
                        "can add aria-label or aria-hidden to icons after load, which the raw HTML a "
                        "crawler reads never had). Search for 'fa-' or 'icon-' and check each match for "
                        "aria-hidden, aria-label, or a title attribute."
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
                # Check 3b: sameAs links exist, none encyclopedic. Two cases
                # this used to collapse into one generic nudge:
                #  - an entry demonstrably exists off-site and simply is not
                #    linked -- concrete and actionable, so say so directly;
                #  - the brand already links a public identity registry
                #    (package registry, code host, company register). That is
                #    a machine-resolvable identity anchor of the same kind
                #    Wikidata provides, and most such brands will never meet
                #    encyclopedia notability, so the nudge is noise for them.
                authority = entities.get("authority_sameas") or {}
                registry_hosts = authority.get("registry_hosts") or []
                if wiki_found or data_found:
                    where = " and ".join(
                        [w for w in ("a Wikipedia article" if wiki_found else "",
                                     "a Wikidata entry" if data_found else "") if w])
                    add_finding(
                        findings, "freshness_corroboration",
                        "Existing Encyclopedic Entry Not Linked From Organization sameAs",
                        "low",
                        f"Off-site search found {where} for '{brand_name_str}', but the site's Organization "
                        "sameAs links do not point to it, so the page never connects itself to the entity "
                        "record AI systems already hold.",
                        f"Add the existing {where.replace('a ', '')} URL to the Organization sameAs array "
                        "so the on-site entity and the off-site record resolve to the same thing.",
                        plain_english=f"An encyclopedia-style entry for '{brand_name_str}' already exists, but "
                        "your website does not link to it. Adding that link tells AI systems the entry and "
                        "your site describe the same organization.",
                        confidence=0.8
                    )
                elif registry_hosts:
                    pass  # registry-grade identity anchor already present
                else:
                    add_finding(
                        findings, "freshness_corroboration",
                        "Organization sameAs Links Present but No Wikipedia or Wikidata Authority Link",
                        "low",
                        "Organization schema contains sameAs links (e.g. social profiles), but none point to "
                        "Wikipedia, Wikidata, or a public identity registry (company register, package or code "
                        "registry). "
                        + ("Off-site search also found no Wikipedia or Wikidata entry for this brand. "
                           if wiki_found is False and data_found is False else "")
                        + "Note: encyclopedic coverage is an optional external authority signal for eligible "
                        "entities, not a mandatory requirement.",
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

        # content_dates and temporal_decay are extracted from this site's own
        # HTML -- unlike citation_consistency/entity_disambiguation above,
        # which corroborate via external web search and stay valid evidence
        # even when this site's own fetch is blocked. Gated the same as
        # crawl_render/readability/engagement.
        dates = freshness.get("content_dates", {})
        if dates and not coverage_blocked and dates.get("checked", True):
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

            # Content age -- the strongest freshness signal. The source matters:
            # a declared dateModified/datePublished is this page's own claim
            # about itself, while `latest_visible_date` is the newest date
            # merely PRINTED on the page (it may belong to a listed child post,
            # not the page). Both are worth reporting, but only the declared
            # ones are stated as fact, and the visible-text fallback is priced
            # lower because it can legitimately misattribute.
            age_days = dates.get("effective_content_age_days")
            age_source = dates.get("effective_content_age_source")
            if isinstance(age_days, int) and age_days > 540:
                yrs = round(age_days / 365, 1)
                from_visible = age_source == "latest_visible_date"
                if from_visible:
                    evidence = (f"No datePublished/dateModified is declared anywhere on the page. The "
                                f"newest date printed in its visible text is "
                                f"{dates.get('latest_visible_date')} -- {age_days} days (~{yrs} years) ago "
                                f"({dates.get('visible_dates_count')} dated item(s) found in total).")
                    action = ("Add datePublished/dateModified to the page's JSON-LD so recency is a "
                              "machine-readable fact rather than something a crawler has to infer from "
                              "printed text, and refresh the content itself if it really is this old.")
                    title = "No Declared Content Date; Newest Date Visible on the Page Is Years Old"
                else:
                    evidence = (f"JSON-LD reports the page was last modified {age_days} days (~{yrs} years) "
                                f"ago (datePublished: {dates.get('date_published')}, dateModified: "
                                f"{dates.get('date_modified')}).")
                    action = "Review and refresh the page content, then update datePublished/dateModified in JSON-LD."
                    title = "Structured Content Date (dateModified) Is Stale"
                add_finding(
                    findings, "freshness_corroboration",
                    title,
                    "medium",
                    evidence,
                    action,
                    plain_english="Your page's 'last updated' signal is years old, so AI assistants treat the content as outdated and are less likely to cite it for current questions.",
                    confidence=0.6 if from_visible else 1.0
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
        if (decay and not coverage_blocked and decay.get("checked", True)
                and decay.get("is_decayed") and not decay.get("has_relative_recent_timestamps")):
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

        # content_dates / temporal_decay decline to scan a non-2xx fetch
        # (see check_content_dates.py / check_temporal_decay.py) rather than
        # report a fabricated staleness claim scraped off an error page's
        # incidental text (a stale copyright year in a shared 404 template,
        # for example). Surface the real defect instead: the target page
        # doesn't load.
        unreachable = [d for d in (dates, decay) if isinstance(d, dict) and d.get("checked") is False]
        if unreachable and not coverage_blocked:
            status_code = unreachable[0].get("fetch_status")
            skipped = sorted({("content dates" if d is dates else "listing recency")
                              for d in unreachable})
            add_finding(
                findings, "freshness_corroboration",
                f"Target Page Unreachable for Freshness Analysis (HTTP {status_code})",
                "medium",
                f"The page this check was pointed at for {' and '.join(skipped)} returned HTTP "
                f"{status_code} instead of real content, so freshness could not be evaluated -- the "
                f"response is an error page, not the content whose recency was in question.",
                "Fix or remove whatever links to this URL (navigation, sitemap, or an outdated reference "
                "elsewhere on the site), or point this check at the correct current URL.",
                plain_english="The page this check tried to read doesn't actually load -- it returns an "
                "error instead of content, so there's nothing here to judge as fresh or stale. That's "
                "itself worth fixing: something is pointing AI crawlers and visitors at a dead page."
            )

    # 5. Engagement Skill Findings
    engagement = skill_outputs.get("engagement", {})
    if engagement and not coverage_blocked:
        reach = engagement.get("navigation_reachability", {})
        for item in reach.get("key_content_reachability", []):
            if item.get("directly_linked_from_homepage") is False:
                key_url = item.get("key_content_url") or ""
                long_tail, long_tail_reason = _looks_long_tail_url(key_url)
                if long_tail:
                    # check_navigation_reachability.py has no judgment about
                    # WHICH URLs are worth testing -- it tests whatever list
                    # it's handed. That list is commonly the same
                    # representative-sample picks used for content sampling,
                    # which answers "what page represents this URL-structure
                    # group" -- a different question from "what would a
                    # homepage reasonably link directly." On a site with
                    # thousands of combinatorial pages (a specific flight
                    # route, product SKU, listing), the representative pick
                    # is near-guaranteed to be exactly this kind of URL, and
                    # asserting full confidence that IT specifically belongs
                    # on the homepage would be a false positive against
                    # completely normal large-site architecture.
                    add_finding(
                        findings, "engagement",
                        "Key Content URL Unreachable from Homepage Navigation (Possibly Long-Tail)",
                        "low",
                        f"URL {key_url} is not directly linked from the homepage. This URL's structure "
                        f"suggests it may be one of many long-tail, template-generated pages ({long_tail_reason}) "
                        f"rather than a page a homepage would reasonably link directly -- large sites commonly "
                        f"make this kind of page discoverable via internal search or an XML sitemap instead of "
                        f"a static nav link. Verify this was genuinely meant as a primary navigation entry "
                        f"before treating this as a defect.",
                        "If this specific page is meant to be a primary entry point, link it directly or from "
                        "a prominent hub/category page. If it is one of many auto-generated pages (a specific "
                        "product variant, route, or listing), this is likely expected -- instead ensure a hub "
                        "page or sitemap makes the whole group of pages discoverable.",
                        plain_english="This specific page isn't linked from your homepage, but its web "
                        "address looks like it's one of many machine-generated pages (like a specific flight "
                        "route or product variant) rather than a page meant for direct homepage navigation -- "
                        "which is often normal and expected for large sites.",
                        confidence=0.4
                    )
                else:
                    add_finding(
                        findings, "engagement",
                        "Key Content URL Unreachable from Homepage 1-Level Navigation",
                        "medium",
                        f"URL {key_url} is not directly linked from the homepage.",
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
            dupes = descriptor.get("duplicate_meta_descriptions") or []
            if dupes:
                worst = max(dupes, key=lambda d: d.get("page_count", 0))
                add_finding(
                    findings, "engagement",
                    "Same Meta Description Reused Across Different Pages",
                    "medium",
                    f"{worst.get('page_count')} of {descriptor.get('distinct_pages_audited') or descriptor.get('pages_audited')} "
                    f"audited pages share the identical meta description \"{str(worst.get('description'))[:140]}\": "
                    f"{worst.get('urls')}."
                    + (f" {len(dupes) - 1} other description(s) are also shared." if len(dupes) > 1 else ""),
                    "Write a meta description for each page that states what that specific page covers (its "
                    "product, topic or question), instead of a site-wide template default.",
                    plain_english="Several of your pages carry the same summary text, so search results and AI "
                    "answers show identical descriptions and cannot tell what each page is actually about."
                )

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

            # Trust-page presence (Privacy Policy / Terms): a widely-cited AI-
            # trust signal, but its absence means very different things on
            # different site types -- a real gap for a data-collecting
            # commerce/SaaS site, largely moot for a static docs or personal
            # page. Deliberately kept low severity and worded as informational
            # rather than a defect, and reported once per audit (not once per
            # page) since it is a site-wide fact, not a per-page one.
            if (nxt.get("privacy_policy_present") is False and nxt.get("terms_present") is False
                    and not lr.get("is_utility_context") and "trustpages" not in seen_lr_titles):
                seen_lr_titles.add("trustpages")
                add_finding(
                    findings, "engagement",
                    "No Privacy Policy or Terms Page Found",
                    "low",
                    f"Page {lr_url} carries no link to a Privacy Policy or Terms/Conditions page "
                    f"(direct link scan, not a semantic judgment).",
                    "Add a linked Privacy Policy and Terms page, typically in the site footer -- "
                    "a widely-cited baseline trust signal, most relevant for a site collecting "
                    "user data or taking payments.",
                    plain_english="No link to a Privacy Policy or Terms page was found. This is a "
                    "common baseline trust signal, and matters most if this site collects user "
                    "data or handles payments.",
                    confidence=0.5
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

    # Order the report by impact before numbering it. Findings are assembled in
    # pipeline order (access -> render -> readability -> freshness ->
    # engagement), which tells a coherent story but does NOT put the most
    # damaging problem first: a report could open with three `high` findings and
    # a `medium` before reaching its two `critical` ones, so a non-expert
    # reading top-down acts on the wrong thing first. Sorting by severity is
    # what "prioritized by impact" means in a list a human reads in order.
    #
    # The sort is STABLE, so within one severity band the original pipeline
    # order survives -- findings stay grouped by the stage that produced them,
    # and the ordering remains fully deterministic (same input, same report).
    # Every finding still carries its own `category`, so nothing about the
    # grouping is lost by reordering.
    SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: SEVERITY_ORDER.get(str(f.get("severity", "medium")).lower(), 2))

    # Renumber every finding sequentially. `add_finding` derives an id from the
    # running list length, so any caller-supplied explicit finding that already
    # carries its own id leaves a gap (F-000 pre-seeded => first generated id is
    # F-002 and F-001 never exists). Assigning ids once, at the end, keeps the
    # sequence contiguous regardless of how many explicit findings were injected
    # and makes F-001 the highest-impact finding in the report.
    for i, f in enumerate(findings, start=1):
        f["id"] = f"F-{i:03d}"

    # Severity Summary Counts
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = str(f.get("severity", "medium")).lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["medium"] += 1

    audited_pages_cnt = extract_audited_urls(site_url, skill_outputs)
    robots_restrictions = collect_robots_restrictions(skill_outputs)
    skills_invoked_cnt = max(1, len([k for k in skill_outputs if skill_outputs[k]]))

    default_recs = _build_default_recommendations(skill_outputs, findings, coverage_blocked)

    # freshness_corroboration is deliberately not listed here even when
    # coverage_blocked: its citation_consistency/entity_disambiguation checks
    # corroborate via external web search, not this site's own (blocked)
    # fetch, and stay valid evidence -- only its content_dates/temporal_decay
    # sub-checks (this site's own HTML) are skipped, inside section 4 above.
    categories_not_audited = (
        ["crawl_render", "readability", "engagement"]
        if coverage_blocked else []
    )

    report = {
        "site": site_url,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
            "marketplace_version": "1.0.0",
            # What this audit was not permitted to fetch, and why. Empty on a
            # site that allows the audit everywhere it looked. This is coverage
            # information, not a finding: a page disallowed to crawlers is
            # already reported by the robots.txt findings, and repeating it
            # here would double-count it.
            "robots_restricted_fetches": robots_restrictions,
            "robots_compliance": ("all fetches allowed by robots.txt" if not robots_restrictions
                                  else f"{len(robots_restrictions)} fetch(es) skipped to honour robots.txt"),
            # True when the AI-bot fetch was blocked/challenged by live
            # security infrastructure (see the critical crawl_access finding
            # for which). When true, `categories_not_audited` lists the
            # categories whose findings were intentionally not generated
            # rather than built from a browser-identity view the real
            # crawler never gets -- zero findings there reflects "not
            # evaluated", not "verified clean". freshness_corroboration is
            # excluded from that list: its off-site checks (external web
            # search) stay valid regardless, only its on-page sub-checks are
            # skipped.
            "coverage_blocked": coverage_blocked,
            "categories_not_audited": categories_not_audited
        }
    }
    return report


def synthesize_report(site_url, skill_outputs=None, explicit_findings=None, proactive_recommendations=None):
    """Public entrypoint. This function's own core contract -- ALWAYS return a
    schema-valid report -- must hold for every caller, not just the CLI below
    (whose own try/except only protects `__main__`, not a direct Python
    import). `_synthesize_report_impl` assumes every value it reads is
    reasonably well-shaped; `_sanitize_skill_outputs` guards against a wrong
    type at the CATEGORY level (`skill_outputs["crawl_access"]` itself not a
    dict) but cannot know that, say, `crawl_access["robots"]` specifically
    must be a dict and not a list -- many sibling fields (`sampled_pages`,
    `additional_pages`) are LEGITIMATELY lists, so that check can't be pushed
    one level deeper without a maintained per-field type table. A caller
    piecing together `skill_outputs` from several files (`--set`) rather than
    one already-correctly-shaped object is exactly where a mismatched file
    lands at the wrong key and produces this shape of error, so the net goes
    here rather than assuming it can never happen."""
    try:
        return _synthesize_report_impl(site_url, skill_outputs, explicit_findings, proactive_recommendations)
    except Exception as e:
        return {
            "site": site_url if isinstance(site_url, str) and site_url else UNKNOWN_SITE,
            "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {"total_findings": 1, "critical": 1, "high": 0, "medium": 0, "low": 0},
            "findings": [{
                "id": "F-001",
                "category": "audit_input",
                "title": "Report Generation Failed - This Report Is Not a Valid Audit",
                "severity": "critical",
                "evidence": f"synthesize_report() raised {type(e).__name__}: {e} while processing the "
                            f"supplied skill_outputs -- most often a value at some nested key is not the "
                            f"type downstream code expects (e.g. a list where an object was expected). No "
                            f"site was reliably audited; the absence of findings above is not evidence of "
                            f"a healthy site.",
                "suggested_action": {
                    "summary": "Check that each skill_outputs field matches its documented shape (see the "
                               "relevant skill's SKILL.md Output section) -- this is the most common cause "
                               "when skill_outputs was assembled from several files via --set rather than "
                               "supplied as one already-correct object.",
                    "priority": "critical"},
                "confidence": 1.0,
            }],
            "proactive_recommendations": [],
            "audit_metadata": {
                "audited_pages_count": 1,
                "skills_invoked_count": 1,
                "marketplace_version": "1.0.0",
                "robots_restricted_fetches": [],
                "robots_compliance": "not evaluated",
                "coverage_blocked": False,
                "categories_not_audited": [],
                "script_error": f"{type(e).__name__}: {e}",
            },
        }


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

UNKNOWN_SITE = "(unknown - audit input could not be read)"


def _set_nested(container, path, value):
    """Set `value` at a dotted path inside `container` (a dict), creating
    dicts -- or lists, for a purely-numeric path segment like the `0` in
    `crawl_access.sampled_pages.0.url` -- as needed along the way."""
    parts = path.split(".")
    cur = container
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        next_is_index = (not is_last) and parts[i + 1].isdigit()
        if part.isdigit():
            idx = int(part)
            while len(cur) <= idx:
                cur.append(None)
            if is_last:
                cur[idx] = value
            else:
                if cur[idx] is None:
                    cur[idx] = [] if next_is_index else {}
                cur = cur[idx]
        else:
            if is_last:
                cur[part] = value
            else:
                if not isinstance(cur.get(part), (dict, list)):
                    cur[part] = [] if next_is_index else {}
                cur = cur[part]


def _collect_params(argv):
    """Gather the run's parameters from (in precedence order) `--set` file
    references, an `--input` file, a positional path/JSON/URL, and stdin.
    Returns (params, input_errors).

    `--input <file>` solved payload TRANSPORT (a real `skill_outputs` runs
    20 KB - 800 KB, past what a shell command line can carry), but left one
    cost unsolved: something still has to WRITE that file, and if the
    orchestrating agent is an LLM composing its text -- reading each script's
    JSON/HTML output into its own context, then re-emitting the same bytes as
    output tokens to author payload.json -- that regeneration is bounded by
    the model's own token-generation rate, not by disk or network I/O, and is
    frequently the slowest single step in the entire audit ("everything else
    is fast, but creating the payload/report takes forever").

    `--set <dotted.path>=<file>` removes that cost entirely: the agent redirects
    each script's stdout straight to a file with plain shell `>` (the OS moves
    the bytes; no LLM tokens involved), then references those files by PATH --
    a few dozen characters each -- rather than retyping their contents.
        --set crawl_access.robots=out/robots.json
        --set crawl_access.dual_identity=out/dual.json
        --set crawl_render=out/render_all.json          # whole run_all.py output
        --set crawl_access.sampled_pages.0.url=out/p0_url.json
    Each file's JSON content is read here and placed at that path inside
    `skill_outputs` (numeric segments create/index a list). Combine with
    `--site <url>` for a fully file-referenced invocation that never requires
    the agent to write large JSON as its own output at all.

    `--input <file>` remains for a caller (or a smaller, hand-assembled
    payload) that already has the whole object in one place -- both channels
    merge into the same `skill_outputs`, `--set` applied last so it can layer
    on top of a partial `--input` base.

    Every parse failure is COLLECTED, never swallowed. Silently ignoring a
    truncated payload used to leave `site` defaulting to "https://example.com"
    with zero findings -- a clean-looking report about the wrong domain, which
    is far more dangerous than a loud failure."""
    params, errors = {}, []

    def merge(raw, source):
        raw = (raw or "").strip()
        if not raw:
            return
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"{source}: not valid JSON ({e}). "
                          f"{len(raw)} characters were received"
                          + (" -- this looks truncated, which is what happens when a large payload is "
                             "passed on the command line instead of via --input <file>."
                             if not raw.rstrip().endswith(("}", "]")) else "."))
            return
        if isinstance(obj, dict):
            params.update(obj)
        else:
            errors.append(f"{source}: expected a JSON object, got {type(obj).__name__}")

    args = list(argv[1:])
    out_path = None
    set_specs = []          # deferred: applied AFTER --input, so --set can layer on top
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--input", "-i", "--payload") and i + 1 < len(args):
            path = args[i + 1]; i += 2
            try:
                with io.open(path, encoding="utf-8") as fh:
                    merge(fh.read(), f"--input {path}")
            except OSError as e:
                errors.append(f"--input {path}: could not be read ({e})")
            continue
        if a == "--set" and i + 1 < len(args):
            set_specs.append(args[i + 1]); i += 2
            continue
        if a == "--site" and i + 1 < len(args):
            params.setdefault("site", args[i + 1]); i += 2
            continue
        if a in ("--out", "-o") and i + 1 < len(args):
            out_path = args[i + 1]; i += 2
            continue
        positional.append(a); i += 1

    for spec in set_specs:
        if "=" not in spec:
            errors.append(f"--set {spec}: expected <dotted.path>=<file.json>, no '=' found")
            continue
        dotted_path, file_path = spec.split("=", 1)
        dotted_path = dotted_path.strip()
        if not dotted_path:
            errors.append(f"--set {spec}: empty path before '='")
            continue
        try:
            with io.open(file_path, encoding="utf-8") as fh:
                value = json.load(fh)
        except OSError as e:
            errors.append(f"--set {dotted_path}={file_path}: could not be read ({e})")
            continue
        except json.JSONDecodeError as e:
            errors.append(f"--set {dotted_path}={file_path}: not valid JSON ({e})")
            continue
        params.setdefault("skill_outputs", {})
        try:
            _set_nested(params["skill_outputs"], dotted_path, value)
        except Exception as e:
            # One malformed --set path (e.g. clashing with a value already
            # written by a broader --input) must not take the whole run down
            # -- matches _sanitize_skill_outputs's "one broken category never
            # discards the rest" guarantee applied one layer earlier.
            errors.append(f"--set {dotted_path}={file_path}: could not be placed in skill_outputs ({e})")

    for raw_arg in positional:
        raw_arg = raw_arg.strip()
        if raw_arg.startswith("{"):
            merge(raw_arg, "command-line JSON argument")
        elif raw_arg.lower().endswith(".json") and os.path.exists(raw_arg):
            try:
                with io.open(raw_arg, encoding="utf-8") as fh:
                    merge(fh.read(), f"payload file {raw_arg}")
            except OSError as e:
                errors.append(f"payload file {raw_arg}: could not be read ({e})")
        else:
            params.setdefault("site", raw_arg)

    # With the payload already given as arguments, stdin is only an optional
    # extra layer -- don't stall 15s when a harness leaves stdin open forever.
    supplied = bool(set_specs or positional) or any(a in ("--input", "-i", "--payload") for a in args)
    merge(read_stdin_safe(timeout=1.0 if supplied else 15.0), "stdin")
    return params, errors, out_path


if __name__ == "__main__":
    try:
        params, input_errors, out_path = _collect_params(sys.argv)

        site_url = params.get("site") or params.get("url")
        skill_outputs = params.get("skill_outputs", {})
        explicit_findings = list(params.get("findings", []) or [])
        recommendations = params.get("proactive_recommendations", [])

        # An input we could not read must never masquerade as a clean audit.
        # Emitting the report is still mandatory (the audit ALWAYS produces
        # one), but it has to say, in the report itself, that it is invalid.
        if input_errors:
            explicit_findings.append({
                "category": "audit_input",
                "title": "Audit Input Could Not Be Read - This Report Is Not a Valid Audit",
                "severity": "critical",
                "evidence": "The report generator could not parse its input: "
                            + "; ".join(input_errors)
                            + ". No site data reached the synthesizer, so the empty findings list below "
                              "reflects a broken invocation, NOT a healthy site.",
                "suggested_action": {
                    "summary": "Write the payload to a file and pass its path: "
                               "`python skills/audit-orchestrator/scripts/synthesize_report.py "
                               "--input payload.json --out report.json`. A real payload contains the "
                               "fetched HTML of every sampled page and exceeds the shell's command-line "
                               "length limit, so it cannot be passed with `echo '<json>' | ...`.",
                    "priority": "critical"},
            })
        if not site_url:
            site_url = UNKNOWN_SITE if input_errors else "(no site supplied)"

        report = synthesize_report(site_url, skill_outputs, explicit_findings, recommendations)
        if input_errors:
            report["audit_metadata"]["input_error"] = input_errors

        rendered = json.dumps(report, indent=2)
        if out_path:
            try:
                with io.open(out_path, "w", encoding="utf-8") as fh:
                    fh.write(rendered)
            except OSError as e:
                report["audit_metadata"]["output_error"] = f"could not write {out_path}: {e}"
                rendered = json.dumps(report, indent=2)
        print(rendered)
    except Exception as e:
        # Last resort: something unforeseen broke. A report is still emitted --
        # and it must be SCHEMA-VALID, or the one artifact produced when
        # everything else failed gets rejected by the very schema it claims to
        # satisfy (`site` may not be null; the two counts have minimum 1).
        print(json.dumps({
            "site": UNKNOWN_SITE,
            "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {"total_findings": 1, "critical": 1, "high": 0, "medium": 0, "low": 0},
            "findings": [{
                "id": "F-001",
                "category": "audit_input",
                "title": "Report Generation Failed - This Report Is Not a Valid Audit",
                "severity": "critical",
                "evidence": f"synthesize_report.py raised {type(e).__name__}: {e}. "
                            f"No site was audited; the absence of findings is not evidence of a healthy site.",
                "suggested_action": {
                    "summary": "Re-run the synthesis step with the payload supplied as a file "
                               "(`--input payload.json`) and report this error if it repeats.",
                    "priority": "critical"},
                "confidence": 1.0,
            }],
            "proactive_recommendations": [],
            "audit_metadata": {
                "audited_pages_count": 1,
                "skills_invoked_count": 1,
                "marketplace_version": "1.0.0",
                "robots_restricted_fetches": [],
                "robots_compliance": "not evaluated",
                "coverage_blocked": False,
                "categories_not_audited": [],
                "script_error": str(e),
            },
            "script_error": str(e)
        }, indent=2))
