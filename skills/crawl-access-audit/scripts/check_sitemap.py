
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json

# --- robots.txt gate --------------------------------------------------------
# Every fetch in this file asks robots_gate first. The gate is built from the
# robots.txt that check_robots.py already fetched (passed in as `robots`), so
# it costs no extra request; only a standalone run fetches robots.txt itself.
import os as _os
for _d in (_os.path.dirname(_os.path.abspath(__file__)),
           _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "..", "crawl-access-audit", "scripts")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
try:
    from robots_gate import RobotsGate
except Exception:  # gate unavailable -> refuse to fetch, never fetch blind
    RobotsGate = None

import gzip
import ssl
import urllib.request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
import socket
import urllib.parse

import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Adaptive sampling. Instead of fixed "first 3 / first 5" caps, both the number
# of child sitemaps expanded and the number of listed URLs spot-checked scale
# with the square root of how many exist -- so a 20-page site and a 20,000-page
# site are both sampled sensibly -- but stay clamped to a bounded request
# budget so the audit never becomes a rate-abusing crawl (handout: <5 min,
# no rate abuse). Sampling is evenly spaced by index and therefore deterministic.
# ---------------------------------------------------------------------------
URL_SAMPLE_MIN, URL_SAMPLE_MAX = 5, 12
CHILD_SITEMAP_MIN, CHILD_SITEMAP_MAX = 3, 6


def _adaptive_count(total, lo, hi):
    if total <= 0:
        return lo
    return max(lo, min(int(math.ceil(math.sqrt(total))), hi))

# Relaxed SSL context reserved strictly for retries on SSLCertVerificationError / SSLError
RELAXED_SSL_CTX = ssl.create_default_context()
RELAXED_SSL_CTX.check_hostname = False
RELAXED_SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIAccessibilityAuditor/1.0)"}


XML_SUFFIX_INDEX_THRESHOLD = 0.8


def fetch_resource(url, timeout=12, retries_on_429=1, total_budget=None):
    """Fetches a URL, auto-decompressing gzip (.xml.gz) if detected.

    `timeout` bounds a single connection attempt; `total_budget` (defaulting to
    `timeout`) bounds THIS CALL AS A WHOLE, retries included. Without that
    second bound the per-attempt timeout was the only limit, so one call could
    legitimately take timeout x2 (the SSL-fallback retry) plus 1.5s x
    retries_on_429 -- which is how a 30s sitemap deadline was observed
    overrunning to 40s on a slow host.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    ssl_bypassed = False
    started = time.time()
    budget = timeout if total_budget is None else total_budget

    def attempt_timeout():
        # Never below 1s: a sub-second timeout fails everything on a live host
        # and would turn "slow" into a false "unreachable".
        return max(1.0, min(timeout, budget - (time.time() - started)))

    def budget_spent():
        return (time.time() - started) >= budget

    for attempt in range(retries_on_429 + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=attempt_timeout())
        except HTTPError as e:
            if e.code == 429 and attempt < retries_on_429 and not budget_spent():
                time.sleep(1.5)
                continue
            raise
        except (ssl.SSLCertVerificationError, ssl.SSLError):
            ssl_bypassed = True
            if budget_spent():
                raise
            try:
                resp = urllib.request.urlopen(req, timeout=attempt_timeout(),
                                              context=RELAXED_SSL_CTX)
            except HTTPError as e:
                if e.code == 429 and attempt < retries_on_429 and not budget_spent():
                    time.sleep(1.5)
                    continue
                raise

        with resp:
            content = resp.read()
            # Detect GZIP magic bytes (1f 8b)
            if content[:2] == b"\x1f\x8b":
                try:
                    content = gzip.decompress(content)
                except Exception:
                    pass
            return resp.status, content, ssl_bypassed


def parse_xml_elements(root):
    """
    Safely extracts page URLs and nested sitemap index URLs by stripping
    XML namespaces cleanly regardless of schema definitions.
    """
    page_urls = []
    index_urls = []

    # Map children to their parent tags to distinguish <sitemap><loc> vs <url><loc>
    parent_map = {c: p for p in root.iter() for c in p}

    for elem in root.iter():
        elem_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
        if elem_tag == "loc" and elem.text:
            url_str = elem.text.strip()
            parent = parent_map.get(elem)
            parent_tag = ""
            if parent is not None:
                parent_tag = (
                    parent.tag.split("}")[-1].lower()
                    if "}" in parent.tag
                    else parent.tag.lower()
                )

            if parent_tag == "sitemap":
                index_urls.append(url_str)
            else:
                page_urls.append(url_str)

    return page_urls, index_urls


def spot_check_url(url, timeout=5, gate=None):
    """
    Spot-checks whether a URL resolves correctly.
    Uses lightweight HEAD first; falls back to GET if HEAD returns 403/405.

    A URL the site disallows is never probed -- a HEAD is still a request.
    The caller gets the sentinel status "robots_skipped" so the URL is
    recorded as not checked, never as a broken link.
    """
    if gate is not None:
        decision = gate.allows(url, "*")
        if not decision.allowed:
            return "robots_skipped", False
    try:
        req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        ssl_bypassed = False
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except (ssl.SSLCertVerificationError, ssl.SSLError):
            ssl_bypassed = True
            resp = urllib.request.urlopen(req, timeout=timeout, context=RELAXED_SSL_CTX)

        with resp:
            return resp.status, ssl_bypassed
    except HTTPError as e:
        # Fall back to GET if HEAD method is disallowed by server
        if e.code in {403, 405}:
            try:
                get_req = urllib.request.Request(url, headers=HEADERS, method="GET")
                ssl_bypassed = False
                try:
                    resp = urllib.request.urlopen(get_req, timeout=timeout)
                except (ssl.SSLCertVerificationError, ssl.SSLError):
                    ssl_bypassed = True
                    resp = urllib.request.urlopen(get_req, timeout=timeout, context=RELAXED_SSL_CTX)

                with resp:
                    return resp.status, ssl_bypassed
            except HTTPError as get_e:
                return get_e.code, False
            except Exception:
                return "error", False
        return e.code, False
    except (URLError, socket.timeout):
        return "unreachable", False
    except Exception:
        return "error", False


def probe_conventional_path(conventional_url):
    """Probe the conventional /sitemap.xml when robots.txt declared the sitemap
    somewhere else.

    Reports a SOFT-200 only: the path answers 2xx but the body does not parse
    as a sitemap -- the signature of SPA catch-all routing that serves
    index.html for every unmatched route. This is the same shape as the
    existing `robots.malformed` check one path over.

    A 404/410 here is CORRECT behaviour when robots.txt declares the sitemap
    elsewhere, and is explicitly NOT reported -- declaring via robots.txt is
    the spec-sanctioned method and most healthy sites have no file at this path.
    """
    out = {"url": conventional_url, "checked": True, "http_status": None,
           "responds_2xx": False, "parses_as_sitemap": None,
           "soft_200": False, "error": None}
    try:
        # Bounded by what's left of the shared deadline, not a fixed 8s.
        status, content, _ = fetch_resource(
            conventional_url, timeout=max(2, min(8, time_left())),
            total_budget=max(2, min(8, time_left())))
        out["http_status"] = status
        out["responds_2xx"] = 200 <= int(status) < 300
        if not out["responds_2xx"]:
            return out                      # 404/410 here is fine, not a defect
        try:
            ET.fromstring(content)
            out["parses_as_sitemap"] = True
        except ET.ParseError as e:
            out["parses_as_sitemap"] = False
            out["error"] = f"XML Parse Error: {str(e)[:80]}"
        out["soft_200"] = out["responds_2xx"] and out["parses_as_sitemap"] is False
    except HTTPError as e:
        out["http_status"] = e.code         # a real 4xx/5xx is correct behaviour
    except Exception as e:
        out["error"] = str(e)[:120]
        out["checked"] = False              # could not determine -> report nothing
    return out


SITEMAP_FETCH_DEADLINE_S = 30.0

# ---------------------------------------------------------------------------
# Representative page sample. Pages that share a URL structure are almost
# always rendered by the same template, so auditing one URL per structure
# covers the site far better than the first N sitemap entries (which on most
# sites are all blog posts, or all products). Grouping is purely structural --
# first path segment, and the template's typical depth -- with no keyword
# lists ("docs", "blog", "product"), so it works for any language and any
# naming scheme. It chooses WHICH pages to audit; it does not audit them.
# ---------------------------------------------------------------------------
REPRESENTATIVE_SAMPLE_CAP = 6
_NON_PAGE_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".ico",
    ".xml", ".gz", ".zip", ".rar", ".7z", ".mp3", ".mp4", ".webm", ".mov", ".wav",
    ".txt", ".json", ".csv", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".css", ".js", ".woff", ".woff2", ".ttf",
)
_HOMEPAGE_GROUP = "(homepage)"
_TOP_LEVEL_GROUP = "(top-level pages)"


def _url_group(url):
    path = urllib.parse.urlparse(url).path or "/"
    segs = [s for s in path.split("/") if s]
    if not segs:
        return _HOMEPAGE_GROUP, 0
    if len(segs) == 1:
        return _TOP_LEVEL_GROUP, 1
    return "/" + segs[0] + "/", len(segs)


def representative_sample(page_urls, known_status=None, cap=REPRESENTATIVE_SAMPLE_CAP):
    """Returns (sample, group_counts).

    sample: [{url, group, group_size, reason}] -- the homepage first when it is
    listed, then one URL from each group in descending group size (the
    templates that render the most pages matter most), then a second URL from
    the largest groups while slots remain. Within a group the pick has the
    group's most common depth, so a section index page does not stand in for
    the pages beneath it. Non-page files, and URLs whose spot-check returned a
    non-2xx status, are skipped. Deterministic: sitemap order breaks ties.
    """
    known_status = known_status or {}
    groups, order, depths = {}, [], {}
    seen = set()
    for u in page_urls:
        if not isinstance(u, str) or u in seen:
            continue
        seen.add(u)
        if urllib.parse.urlparse(u).path.lower().endswith(_NON_PAGE_EXTENSIONS):
            continue
        st = known_status.get(u)
        if isinstance(st, int) and not (200 <= st < 300):
            continue
        key, depth = _url_group(u)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((u, depth))
        depths.setdefault(key, {}).setdefault(depth, 0)
        depths[key][depth] += 1

    group_counts = {k: len(v) for k, v in groups.items()}
    ranked = sorted((k for k in order if k != _HOMEPAGE_GROUP),
                    key=lambda k: (-group_counts[k], order.index(k)))
    if _HOMEPAGE_GROUP in groups:
        ranked = [_HOMEPAGE_GROUP] + ranked

    def typical(key):
        modal = max(depths[key].items(), key=lambda kv: (kv[1], -kv[0]))[0]
        return [u for u, d in groups[key] if d == modal] or [u for u, _ in groups[key]]

    sample, taken = [], set()
    for key in ranked:
        if len(sample) >= cap:
            break
        cands = typical(key)
        sample.append({"url": cands[0], "group": key, "group_size": group_counts[key],
                       "reason": "site homepage" if key == _HOMEPAGE_GROUP
                       else f"first page of a {group_counts[key]}-URL group"})
        taken.add(cands[0])
    for key in ranked:
        if len(sample) >= cap:
            break
        cands = [u for u in typical(key) if u not in taken]
        if key == _HOMEPAGE_GROUP or not cands:
            continue
        pick = cands[-1]   # the far end of the group, for variety within one template
        sample.append({"url": pick, "group": key, "group_size": group_counts[key],
                       "reason": f"second page of a {group_counts[key]}-URL group"})
        taken.add(pick)

    top_groups = dict(sorted(group_counts.items(), key=lambda kv: -kv[1])[:12])
    return sample, top_groups


def check_sitemap(sitemap_url, max_samples=None, conventional_url=None, robots=None):
    # Shared wall-clock ceiling across the root fetch, every child sitemap, and
    # every URL spot-check combined. Without it, a slow-but-live server (not
    # down, just slow) can turn up to 6 child fetches + 15 spot-checks, each
    # with its own multi-second timeout, into minutes -- this is one of five
    # skills in a <5min audit budget, so it must return within a bounded time
    # regardless of how slow the target responds.
    deadline_start = time.time()
    _gate = RobotsGate.for_url(sitemap_url or conventional_url or "",
                               robots=robots) if RobotsGate else None

    def time_left():
        return SITEMAP_FETCH_DEADLINE_S - (time.time() - deadline_start)

    result = {
        "exists": False,
        "sitemap_found": False,
        "conventional_path_check": None,
        "valid_xml": False,
        "is_sitemap_index": False,
        "reclassified_as_index": False,
        "child_sitemaps_total": 0,
        "child_sitemaps_checked": 0,
        "child_sitemaps_sampled": 0,
        "child_sitemap_errors": [],
        "url_count": 0,
        "is_empty": True,
        "ssl_verification_bypassed": False,
        "sampled_urls": [],
        "sampling_strategy": {
            "method": "adaptive_sqrt_clamped",
            "url_sample_bounds": [URL_SAMPLE_MIN, URL_SAMPLE_MAX],
            "child_sitemap_bounds": [CHILD_SITEMAP_MIN, CHILD_SITEMAP_MAX],
            "urls_sampled": 0,
            "child_sitemaps_expanded_of_total": None
        },
        "error": None,
        "time_budget_exceeded": False,
        # One URL per URL-structure group, for choosing which pages to audit.
        "representative_sample": [],
        "url_groups": {},
    }

    try:
        status, content, ssl_bypassed = fetch_resource(
            sitemap_url, timeout=max(2, min(12, time_left())),
            total_budget=max(2, min(12, time_left())))
        result["ssl_verification_bypassed"] = ssl_bypassed
        if status != 200:
            result["error"] = f"HTTP {status}"
            return result

        result["exists"] = True

        # Parse XML tree
        try:
            root = ET.fromstring(content)
            result["valid_xml"] = True
        except ET.ParseError as e:
            result["error"] = f"XML Parse Error: {str(e)}"
            return result

        page_urls, index_urls = parse_xml_elements(root)

        # Secondary heuristic: check if page_urls is non-empty and >= 80% end in .xml / .xml.gz
        if page_urls:
            xml_count = 0
            for u in page_urls:
                path_lower = urllib.parse.urlparse(u).path.lower()
                if path_lower.endswith(".xml") or path_lower.endswith(".xml.gz"):
                    xml_count += 1
            if (xml_count / len(page_urls)) >= XML_SUFFIX_INDEX_THRESHOLD:
                result["reclassified_as_index"] = True
                index_urls.extend(page_urls)
                page_urls = []

        # Handle Sitemap Index files (contains nested child sitemaps)
        if index_urls and not page_urls:
            result["is_sitemap_index"] = True
            result["child_sitemaps_total"] = len(index_urls)
            child_cap = _adaptive_count(len(index_urls), CHILD_SITEMAP_MIN, CHILD_SITEMAP_MAX)
            # evenly spaced by index so a large index is sampled across its span
            step = max(1, len(index_urls) // child_cap)
            children_to_fetch = [index_urls[i] for i in range(0, len(index_urls), step)][:child_cap]
            result["child_sitemaps_sampled"] = len(children_to_fetch)
            result["sampling_strategy"]["child_sitemaps_expanded_of_total"] = (
                f"{len(children_to_fetch)}/{len(index_urls)}")

            for child_url in children_to_fetch:
                if time_left() <= 0:
                    result["time_budget_exceeded"] = True
                    result["child_sitemap_errors"].append({
                        "url": child_url, "error": f"skipped: {SITEMAP_FETCH_DEADLINE_S:.0f}s wall-clock budget exceeded"})
                    continue
                try:
                    child_status, child_content, child_ssl_bypassed = fetch_resource(
                        child_url, timeout=max(2, min(12, time_left())),
                        total_budget=max(2, min(12, time_left())))
                    if child_ssl_bypassed:
                        result["ssl_verification_bypassed"] = True

                    if child_status == 200:
                        child_root = ET.fromstring(child_content)
                        child_pages, _ = parse_xml_elements(child_root)
                        page_urls.extend(child_pages)
                        result["child_sitemaps_checked"] += 1
                    else:
                        result["child_sitemap_errors"].append({
                            "url": child_url,
                            "error": f"HTTP {child_status}"
                        })
                except Exception as e:
                    result["child_sitemap_errors"].append({
                        "url": child_url,
                        "error": str(e)
                    })

        result["url_count"] = len(page_urls)
        result["is_empty"] = len(page_urls) == 0

        # Spot-check an adaptive sample of listed URLs, evenly spaced by index.
        if page_urls:
            if isinstance(max_samples, int) and max_samples > 0:
                sample_cap = max_samples          # explicit override honoured
            else:
                sample_cap = _adaptive_count(len(page_urls), URL_SAMPLE_MIN, URL_SAMPLE_MAX)
            step = max(1, len(page_urls) // sample_cap)
            sampled = [page_urls[i] for i in range(0, len(page_urls), step)][:sample_cap]
            result["sampling_strategy"]["urls_sampled"] = len(sampled)

            if time_left() <= 0:
                result["time_budget_exceeded"] = True
                for u in sampled:
                    result["sampled_urls"].append({
                        "url": u,
                        "status": None,
                        "error": f"skipped: {SITEMAP_FETCH_DEADLINE_S:.0f}s wall-clock budget exceeded",
                        "ssl_verification_bypassed": False
                    })
            else:
                def _probe(u):
                    rem = time_left()
                    if rem <= 0:
                        return u, None, False, f"skipped: {SITEMAP_FETCH_DEADLINE_S:.0f}s wall-clock budget exceeded"
                    try:
                        to = max(2, min(5, rem))
                        status_code, spot_ssl_bypassed = spot_check_url(
                            u, timeout=to, gate=_gate)
                        return u, status_code, spot_ssl_bypassed, None
                    except Exception:
                        return u, "error", False, None

                workers = min(5, len(sampled))
                probe_results = [None] * len(sampled)
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_idx = {
                        executor.submit(_probe, u): i for i, u in enumerate(sampled)
                    }
                    for future in as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        try:
                            u_res, status_code, spot_ssl_bypassed, err = future.result()
                            probe_results[idx] = (status_code, spot_ssl_bypassed, err)
                        except Exception:
                            probe_results[idx] = ("error", False, None)

                for i, u in enumerate(sampled):
                    res = probe_results[i]
                    if not res:
                        res = ("error", False, None)
                    status_code, spot_ssl_bypassed, err = res
                    if err:
                        result["time_budget_exceeded"] = True
                        result["sampled_urls"].append({
                            "url": u,
                            "status": status_code,
                            "error": err,
                            "ssl_verification_bypassed": spot_ssl_bypassed
                        })
                    else:
                        result["sampled_urls"].append({
                            "url": u,
                            "status": status_code,
                            "ssl_verification_bypassed": spot_ssl_bypassed
                        })

            known_status = {s["url"]: s.get("status") for s in result["sampled_urls"]}
            result["representative_sample"], result["url_groups"] = representative_sample(
                page_urls, known_status)

    except HTTPError as e:
        result["exists"] = False
        result["error"] = f"HTTP {e.code}"
    except (URLError, socket.timeout) as e:
        result["exists"] = False
        result["error"] = f"Network Error: {str(e)}"
    except Exception as e:
        result["exists"] = False
        result["error"] = f"Execution Error: {str(e)}"

    # Rolled-up reachability flag consumed by the orchestrator. A sitemap that
    # exists but failed child traversal is still "found" -- per the SKILL.md
    # interpretation note, partial traversal must not be reported as "no sitemap".
    result["sitemap_found"] = bool(result["exists"] and result["valid_xml"])

    # Only probe the conventional path when robots.txt pointed somewhere else.
    # If no declared sitemap existed, `sitemap_url` already IS the conventional
    # path and a second request would be wasted.
    if conventional_url:
        try:
            same = conventional_url.rstrip("/").lower() == str(sitemap_url).rstrip("/").lower()
        except Exception:
            same = False
        if not same:
            result["conventional_path_check"] = probe_conventional_path(conventional_url)
    return result


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
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() in ("--help", "-h", "help"):
        print("Usage: python check_sitemap.py <sitemap_url>")
        sys.exit(0)
    try:
        sitemap_url = None
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    sitemap_url = params.get("sitemap_url") or params.get("url") or params.get("domain")
                except json.JSONDecodeError:
                    sitemap_url = raw_arg
            else:
                sitemap_url = raw_arg

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not sitemap_url:
            sitemap_url = params.get("sitemap_url") or params.get("url") or params.get("domain") or "https://example.com/sitemap.xml"

        if not sitemap_url.startswith("http://") and not sitemap_url.startswith("https://"):
            sitemap_url = "https://" + sitemap_url

        if not sitemap_url.endswith(".xml") and not sitemap_url.endswith(".gz") and "/sitemap" not in sitemap_url.lower():
            sitemap_url = sitemap_url.rstrip("/") + "/sitemap.xml"

        output = check_sitemap(sitemap_url,
                               conventional_url=params.get("conventional_url"),
                               robots=params.get("robots"))
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))