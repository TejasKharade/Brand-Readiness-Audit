
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import os
from datetime import datetime, timezone


def strip_non_visible(html):
    """Remove <script>/<style>/<noscript> bodies and HTML comments so that
    temporal-anchor and copyright scanning never picks up dates from bundled
    library banners, inline JS vars, or commented-out markup."""
    if not html:
        return ""
    h = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    h = re.sub(r"<script\b[^>]*>.*?</script>", " ", h, flags=re.DOTALL | re.IGNORECASE)
    h = re.sub(r"<style\b[^>]*>.*?</style>", " ", h, flags=re.DOTALL | re.IGNORECASE)
    h = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", h, flags=re.DOTALL | re.IGNORECASE)
    return h


def parse_iso_date(s):
    """Best-effort ISO-8601 parse -> aware datetime (UTC) or None. Handles
    date-only, 'Z', and offset forms; returns None for anything else so the
    caller can flag it as unparseable rather than trusting garbage."""
    if not s or not isinstance(s, str):
        return None
    v = s.strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?)"
                 r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?", v)
    if not m:
        return None
    try:
        iso = m.group(1)
        if m.group(2):
            iso += "T" + m.group(2)
            tz = m.group(4)
            if tz == "Z":
                iso += "+00:00"
            elif tz:
                iso += tz if ":" in tz else tz[:3] + ":" + tz[3:]
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def load_patterns():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ref_path = os.path.join(script_dir, "..", "references", "date_patterns.json")
    
    default_anchors = [
        r"as of (?:20\d{2}|19\d{2})",
        r"updated (?:in|on|as of)?\s*(?:20\d{2}|19\d{2}|[a-zA-Z]+\s+20\d{2})",
        r"current as of\s*(?:20\d{2}|19\d{2}|[a-zA-Z]+\s+20\d{2})?",
        r"last updated (?:on|in)?\s*(?:20\d{2}|19\d{2}|[a-zA-Z]+\s+20\d{2})?",
        r"published (?:on|in)?\s*(?:20\d{2}|19\d{2}|[a-zA-Z]+\s+20\d{2})?"
    ]
    default_copyright = [
        r"(?:copyright|©|\bcopr\b|\&copy\;)\s*([\s\S]{1,120}?)(?=\.|\;|$|<|\n)"
    ]

    try:
        if os.path.exists(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("explicit_temporal_anchors", default_anchors), data.get("copyright_patterns", default_copyright)
    except Exception:
        pass
    return default_anchors, default_copyright

def extract_json_ld_blocks(html_text):
    if not html_text:
        return []
    blocks = []
    for m in re.finditer(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>', html_text, re.IGNORECASE):
        start_idx = m.end()
        obj_start = -1
        for i in range(start_idx, len(html_text)):
            if html_text[i] in '{[':
                obj_start = i
                break
        if obj_start == -1:
            continue
        
        stack = []
        in_string = False
        escape = False
        obj_end = -1
        for i in range(obj_start, len(html_text)):
            ch = html_text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch in '{[':
                    stack.append(ch)
                elif ch in '}]':
                    if stack:
                        stack.pop()
                        if not stack:
                            obj_end = i + 1
                            break
        if obj_end != -1:
            blocks.append(html_text[obj_start:obj_end])
    return blocks

def extract_json_ld_dates(html_content):
    date_pub = None
    date_mod = None
    if not html_content:
        return date_pub, date_mod

    json_blocks = extract_json_ld_blocks(html_content)
    
    def search_obj(obj):
        nonlocal date_pub, date_mod
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = str(k).lower()
                if k_lower in ['datepublished', 'uploaddate'] and isinstance(v, str) and not date_pub:
                    v_str = v.strip()
                    if v_str: date_pub = v_str
                elif k_lower in ['datemodified', 'dateupdated'] and isinstance(v, str) and not date_mod:
                    v_str = v.strip()
                    if v_str: date_mod = v_str
                if isinstance(v, (dict, list)):
                    search_obj(v)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    search_obj(item)

    for block_str in json_blocks:
        try:
            data = json.loads(block_str)
            search_obj(data)
        except Exception:
            pass
            
    return date_pub, date_mod

def check_content_dates(html_content, url):
    if not html_content:
        html_content = ""

    anchor_patterns, copyright_patterns = load_patterns()
    now = datetime.now(timezone.utc)
    current_year = now.year

    # JSON-LD dates come from the FULL html (they live inside <script> tags);
    # everything else is scanned on visible text only.
    date_published, date_modified = extract_json_ld_dates(html_content)
    visible = strip_non_visible(html_content)

    # 1. Temporal anchor phrases (visible text only)
    matched_anchors = []
    for pat in anchor_patterns:
        try:
            for m in re.findall(pat, visible, re.IGNORECASE):
                m_str = m if isinstance(m, str) else " ".join(m)
                m_str = m_str.strip()
                # keep only anchors that actually carry a year
                if m_str and re.search(r"\b(19|20)\d{2}\b", m_str) and m_str not in matched_anchors:
                    matched_anchors.append(m_str)
        except Exception:
            pass

    # 2. Copyright year (visible text only -> no bundled-library / JS-var banners)
    copyright_years = []
    for pat in copyright_patterns:
        try:
            for match in re.finditer(pat, visible, re.IGNORECASE):
                for y_str in re.findall(r"\b(20\d{2}|19\d{2})\b", match.group(0)):
                    y_int = int(y_str)
                    if 1990 <= y_int <= current_year + 1:
                        copyright_years.append(y_int)
        except Exception:
            pass
    copyright_years = sorted(set(copyright_years))
    copyright_year = max(copyright_years) if copyright_years else None
    copyright_age_years = (current_year - copyright_year) if copyright_year is not None else None

    # 3. JSON-LD date sanity + age (the strongest freshness signal)
    pub_dt = parse_iso_date(date_published)
    mod_dt = parse_iso_date(date_modified)
    date_published_age_days = (now - pub_dt).days if pub_dt else None
    date_modified_age_days = (now - mod_dt).days if mod_dt else None

    issues = []
    if date_published and pub_dt is None:
        issues.append(f"datePublished '{date_published}' is not a parseable date")
    if date_modified and mod_dt is None:
        issues.append(f"dateModified '{date_modified}' is not a parseable date")
    if pub_dt and mod_dt and mod_dt < pub_dt:
        issues.append("dateModified is earlier than datePublished (data-quality error)")
    if mod_dt and mod_dt > now:
        issues.append("dateModified is in the future")
    if pub_dt and pub_dt > now:
        issues.append("datePublished is in the future")

    # Effective "last touched" age, preferring dateModified.
    effective_age_days = date_modified_age_days
    if effective_age_days is None:
        effective_age_days = date_published_age_days

    return {
        "url": url,
        "date_published": date_published,
        "date_modified": date_modified,
        "date_published_age_days": date_published_age_days,
        "date_modified_age_days": date_modified_age_days,
        "effective_content_age_days": effective_age_days,
        "content_date_issues": issues,
        "explicit_temporal_anchors_found": matched_anchors,
        "copyright_year": copyright_year,
        "copyright_years_all": copyright_years,
        "copyright_year_age_years": copyright_age_years,
        "scanning_scope": "visible_text_only (script/style/comments stripped)"
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

if __name__ == "__main__":
    try:
        html_content = ""
        url = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    html_content = params.get("html", "")
                    url = params.get("url", "")
                except json.JSONDecodeError:
                    url = raw_arg
            else:
                url = raw_arg

        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass

        if not html_content:
            html_content = params.get('html', '')
        if not url:
            url = params.get('url', '')

        result = check_content_dates(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "date_published": None,
            "date_modified": None,
            "date_published_age_days": None,
            "date_modified_age_days": None,
            "effective_content_age_days": None,
            "content_date_issues": [],
            "explicit_temporal_anchors_found": [],
            "copyright_year": None,
            "copyright_years_all": [],
            "copyright_year_age_years": None,
            "script_error": str(e)
        }))
