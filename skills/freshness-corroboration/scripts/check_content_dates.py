import sys
import json
import re
import os
from datetime import datetime

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
    current_year = datetime.now().year

    # 1. JSON-LD Dates
    date_published, date_modified = extract_json_ld_dates(html_content)

    # 2. Temporal Anchor Phrases in visible text across full document
    matched_anchors = []
    for pat in anchor_patterns:
        try:
            matches = re.findall(pat, html_content, re.IGNORECASE)
            for m in matches:
                m_str = m if isinstance(m, str) else " ".join(m)
                if m_str and m_str not in matched_anchors:
                    matched_anchors.append(m_str)
        except Exception:
            pass

    # 3. Copyright Footer Year: Search full html_content to avoid tail-slice omissions
    copyright_years = []
    for pat in copyright_patterns:
        try:
            matches = re.finditer(pat, html_content, re.IGNORECASE)
            for match in matches:
                block_text = match.group(0)
                # Find all 4-digit years inside the copyright block (handles ranges like "2019-2026")
                years_in_block = re.findall(r'\b(20\d{2}|19\d{2})\b', block_text)
                for y_str in years_in_block:
                    y_int = int(y_str)
                    if 1990 <= y_int <= current_year + 1:
                        copyright_years.append(y_int)
        except Exception:
            pass

    copyright_year = max(copyright_years) if copyright_years else None
    copyright_age_years = (current_year - copyright_year) if copyright_year is not None else None

    return {
        "url": url,
        "date_published": date_published,
        "date_modified": date_modified,
        "explicit_temporal_anchors_found": matched_anchors,
        "copyright_year": copyright_year,
        "copyright_year_age_years": copyright_age_years
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        html_content = params.get('html', '')
        url = params.get('url', '')

        result = check_content_dates(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "date_published": None,
            "date_modified": None,
            "explicit_temporal_anchors_found": [],
            "copyright_year": None,
            "copyright_year_age_years": None,
            "script_error": str(e)
        }))
