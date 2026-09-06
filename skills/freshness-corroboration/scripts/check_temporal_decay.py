import sys
import json
import re
from html.parser import HTMLParser

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}

BOILERPLATE_PATTERNS = [
    r'copyright', r'©', r'\bcopr\b', r'\&copy\;',
    r'founded\s+in', r'established\s+in', r'all\s+rights\s+reserved',
    r'privacy\s+policy', r'terms\s+of\s+service'
]

class ListingDateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.structured_dates = []
        self.text_date_snippets = []
        self.in_time_tag = False
        self.time_datetime_attr = None
        self.in_footer = False

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "footer":
            self.in_footer = True
        elif tag_lower == "time":
            self.in_time_tag = True
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
            self.time_datetime_attr = attrs_dict.get("datetime")

    def handle_data(self, data):
        text = data.strip() if data else ""
        if not text or self.in_footer:
            return

        # Check for boilerplate signals
        text_lower = text.lower()
        if any(re.search(bp, text_lower) for bp in BOILERPLATE_PATTERNS):
            return

        if self.in_time_tag:
            val = (self.time_datetime_attr or text).strip()
            if val and val not in self.structured_dates:
                self.structured_dates.append(val)
        else:
            # Look for 4-digit years or ISO/Text date-like strings in listing text blocks
            if re.search(r'\b(20\d{2}|19\d{2})\b', text):
                if text not in self.text_date_snippets:
                    self.text_date_snippets.append(text)

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "footer":
            self.in_footer = False
        elif tag_lower == "time":
            self.in_time_tag = False
            self.time_datetime_attr = None

def parse_comparable_date(date_str):
    if not date_str:
        return (0, 0, 0, "")
    s = str(date_str).strip()

    # ISO 8601: YYYY-MM-DD
    m_iso = re.search(r'\b(20\d{2}|19\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b', s)
    if m_iso:
        return (int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)), s)

    # Text Date: Month DD, YYYY
    m_txt1 = re.search(r'\b([a-zA-Z]+)\s+([0-3]?\d),\s*(20\d{2}|19\d{2})\b', s)
    if m_txt1:
        mo_num = MONTH_MAP.get(m_txt1.group(1).lower(), 0)
        if mo_num:
            return (int(m_txt1.group(3)), mo_num, int(m_txt1.group(2)), s)

    # Text Date: DD Month YYYY
    m_txt2 = re.search(r'\b([0-3]?\d)\s+([a-zA-Z]+)\s+(20\d{2}|19\d{2})\b', s)
    if m_txt2:
        mo_num = MONTH_MAP.get(m_txt2.group(2).lower(), 0)
        if mo_num:
            return (int(m_txt2.group(3)), mo_num, int(m_txt2.group(1)), s)

    # Fallback year-only extraction
    m_yr = re.search(r'\b(20\d{2}|19\d{2})\b', s)
    if m_yr:
        return (int(m_yr.group(1)), 0, 0, s)

    return (0, 0, 0, s)

def check_temporal_decay(html_content, url):
    if not html_content:
        html_content = ""

    parser = ListingDateParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    structured_dates = parser.structured_dates
    loose_dates = parser.text_date_snippets

    detection_confidence = "low"
    all_dates = []

    if structured_dates:
        detection_confidence = "high"
        all_dates = structured_dates
    elif loose_dates:
        detection_confidence = "low"
        all_dates = loose_dates

    post_count_found = len(all_dates)

    most_recent_post_date_found = None
    if all_dates:
        parsed_dates = [parse_comparable_date(d) for d in all_dates]
        # Sort descending by (year, month, day) tuple
        parsed_dates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        most_recent_post_date_found = parsed_dates[0][3]

    return {
        "url": url,
        "most_recent_post_date_found": most_recent_post_date_found,
        "post_count_found": post_count_found,
        "detection_confidence": detection_confidence if post_count_found > 0 else "low"
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

        result = check_temporal_decay(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "most_recent_post_date_found": None,
            "post_count_found": 0,
            "detection_confidence": "low",
            "script_error": str(e)
        }))
