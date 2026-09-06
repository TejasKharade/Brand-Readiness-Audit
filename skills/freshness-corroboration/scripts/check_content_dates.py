import sys
import json
import re
from datetime import datetime, timezone
import html.parser

DATE_META_NAMES = {
    'article:published_time', 'article:modified_time', 'og:updated_time',
    'datepublished', 'datemodified', 'dc.date', 'dc.date.issued',
    'dc.date.modified', 'pubdate', 'lastmod', 'date'
}

class DateParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.published_dates = []
        self.modified_dates = []
        self.time_tags = []
        
    def handle_starttag(self, tag, attrs):
        try:
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
            if tag == "meta":
                prop = attrs_dict.get("property", "").lower() or attrs_dict.get("name", "").lower()
                content = attrs_dict.get("content", "").strip()
                if prop in DATE_META_NAMES and content:
                    if "modified" in prop or "updated" in prop or "lastmod" in prop:
                        self.modified_dates.append(content)
                    else:
                        self.published_dates.append(content)
            elif tag == "time":
                dt = attrs_dict.get("datetime", "").strip()
                if dt:
                    self.time_tags.append(dt)
        except Exception:
            pass

def parse_iso_date(date_str):
    if not date_str:
        return None
    s = str(date_str).strip()
    # Match YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    match = re.search(r'(\d{4}-\d{2}-\d{2})(?:[T\s](\d{2}:\d{2}:\d{2}))?', s)
    if not match:
        return None
    
    date_part = match.group(1)
    time_part = match.group(2) or "00:00:00"
    iso_clean = f"{date_part}T{time_part}Z"
    
    try:
        dt = datetime.strptime(iso_clean, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def extract_json_ld_dates(html_content):
    pub_dates = []
    mod_dates = []
    pattern = re.compile(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
    
    def search_obj(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = k.lower()
                if k_lower in ['datepublished', 'uploaddate']:
                    if isinstance(v, str): pub_dates.append(v)
                elif k_lower in ['datemodified', 'dateupdated']:
                    if isinstance(v, str): mod_dates.append(v)
                search_obj(v)
        elif isinstance(obj, list):
            for item in obj:
                search_obj(item)

    for match in pattern.finditer(html_content or ''):
        try:
            data = json.loads(match.group(1))
            search_obj(data)
        except Exception:
            pass
            
    return pub_dates, mod_dates

def check_content_dates(html_content, url, reference_date_str=None):
    parser = DateParser()
    try:
        if html_content:
            parser.feed(html_content)
    except Exception:
        pass

    json_pub, json_mod = extract_json_ld_dates(html_content)
    
    all_published_raw = parser.published_dates + json_pub
    all_modified_raw = parser.modified_dates + json_mod
    all_time_raw = parser.time_tags

    parsed_published = [parse_iso_date(d) for d in all_published_raw if parse_iso_date(d)]
    parsed_modified = [parse_iso_date(d) for d in all_modified_raw if parse_iso_date(d)]
    parsed_time = [parse_iso_date(d) for d in all_time_raw if parse_iso_date(d)]

    # Determine reference date
    ref_dt = parse_iso_date(reference_date_str) if reference_date_str else datetime.now(timezone.utc)
    if not ref_dt:
        ref_dt = datetime.now(timezone.utc)

    # Pick latest modified and earliest/latest published
    latest_modified = max(parsed_modified) if parsed_modified else None
    latest_published = max(parsed_published) if parsed_published else None
    
    # Calculate age in days
    modified_age_days = (ref_dt - latest_modified).days if latest_modified else None
    published_age_days = (ref_dt - latest_published).days if latest_published else None

    effective_age_days = modified_age_days if modified_age_days is not None else published_age_days
    is_outdated = effective_age_days > 730 if effective_age_days is not None else False
    is_stale = effective_age_days > 365 if effective_age_days is not None else False

    return {
        "url": url,
        "has_published_date": bool(parsed_published or parsed_time),
        "has_modified_date": bool(parsed_modified),
        "latest_published_date": latest_published.strftime("%Y-%m-%d") if latest_published else None,
        "latest_modified_date": latest_modified.strftime("%Y-%m-%d") if latest_modified else None,
        "effective_age_days": effective_age_days,
        "is_stale_content_gt_1yr": is_stale,
        "is_outdated_content_gt_2yr": is_outdated,
        "raw_signals": {
            "meta_published": parser.published_dates,
            "meta_modified": parser.modified_dates,
            "json_ld_published": json_pub,
            "json_ld_modified": json_mod,
            "time_tags": parser.time_tags
        }
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
        ref_date = params.get('reference_date')

        result = check_content_dates(html_content, url, ref_date)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
