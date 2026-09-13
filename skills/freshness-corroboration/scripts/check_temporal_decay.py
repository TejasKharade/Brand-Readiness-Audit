
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser


def _strip_non_visible(html):
    """Remove <script>/<style>/<noscript> bodies and HTML comments before
    date-pattern scanning. Reuses check_content_dates.py's own
    strip_non_visible() (same directory) rather than a second copy that could
    drift from it -- without this, a jQuery slider's `pause: 2000` or a
    `setTimeout(fn, 2000)` inside a <script> block reads as a plausible year
    to the \\b(19|20)\\d{2}\\b pattern below, exactly like it would on any
    other page with inline JS (this is not specific to one site's markup)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from check_content_dates import strip_non_visible
        return strip_non_visible(html)
    except Exception:
        if not html:
            return ""
        h = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
        h = re.sub(r"<script\b[^>]*>.*?</script>", " ", h, flags=re.DOTALL | re.IGNORECASE)
        h = re.sub(r"<style\b[^>]*>.*?</style>", " ", h, flags=re.DOTALL | re.IGNORECASE)
        h = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", h, flags=re.DOTALL | re.IGNORECASE)
        return h

RELATIVE_RECENT_RX = re.compile(
    r"\b(just now|today|yesterday|\d+\s*(second|minute|hour|day|week)s?\s+ago|"
    r"an?\s+(hour|day|week)\s+ago)\b", re.IGNORECASE)
DECAY_THRESHOLD_DAYS = 365

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
        self.structured_dates = []        # datetime="" values from <time>
        self.relative_time_texts = []     # <time> bodies like "2 days ago"
        self.text_date_snippets = []
        self.in_time_tag = False
        self.time_datetime_attr = None
        self._time_text = []
        # depth counters: a page-level <footer> is boilerplate, but a
        # per-post <article><footer class="post-meta"> holds the publish date.
        self._page_footer_depth = 0
        self._article_depth = 0

    def _suppressed(self):
        return self._page_footer_depth > 0 and self._article_depth == 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "article":
            self._article_depth += 1
        elif t == "footer":
            self._page_footer_depth += 1
        elif t == "time":
            self.in_time_tag = True
            self._time_text = []
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
            self.time_datetime_attr = attrs_dict.get("datetime")

    def handle_data(self, data):
        text = data.strip() if data else ""
        if not text:
            return
        if self.in_time_tag:
            self._time_text.append(text)
            return
        if self._suppressed():
            return
        text_lower = text.lower()
        if any(re.search(bp, text_lower) for bp in BOILERPLATE_PATTERNS):
            return
        if re.search(r"\b(20\d{2}|19\d{2})\b", text):
            if text not in self.text_date_snippets:
                self.text_date_snippets.append(text)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "article" and self._article_depth > 0:
            self._article_depth -= 1
        elif t == "footer" and self._page_footer_depth > 0:
            self._page_footer_depth -= 1
        elif t == "time":
            self.in_time_tag = False
            body = " ".join(self._time_text).strip()
            dt_attr = (self.time_datetime_attr or "").strip()
            if self._suppressed():
                # a <time> inside a page-level footer (not a post card) is
                # site chrome, not a post date
                self.time_datetime_attr = None
                self._time_text = []
                return
            if dt_attr and re.search(r"\d{4}-\d{2}-\d{2}", dt_attr):
                if dt_attr not in self.structured_dates:
                    self.structured_dates.append(dt_attr)
            elif RELATIVE_RECENT_RX.search(body) or RELATIVE_RECENT_RX.search(dt_attr):
                self.relative_time_texts.append(body or dt_attr)
            elif body and re.search(r"\b(20\d{2}|19\d{2})\b", body):
                if body not in self.structured_dates:
                    self.structured_dates.append(body)
            self.time_datetime_attr = None
            self._time_text = []

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

def check_temporal_decay(html_content, url, status=None):
    # Same reasoning as check_content_dates.py: a 404/410/5xx page still
    # often returns a body (a custom error template, or the site's shared
    # chrome carrying a stale footer date), and scanning it for "the most
    # recent post date" would report a fabricated staleness claim in place
    # of the real defect -- this page doesn't load. When the caller supplies
    # the fetch's status, a non-2xx short-circuits straight to an honest
    # "not analyzed" result instead of a low-confidence guess.
    if status is not None and not (isinstance(status, int) and 200 <= status < 300):
        return {
            "url": url, "checked": False, "fetch_status": status,
            "skip_reason": f"page fetch returned HTTP {status}, not real content -- listing not scanned",
            "most_recent_post_date_found": None, "most_recent_post_date_iso": None,
            "date_precision": None, "days_since_last_post": None, "is_decayed": False,
            "decay_threshold_days": DECAY_THRESHOLD_DAYS, "post_count_found": 0,
            "has_relative_recent_timestamps": False, "detection_confidence": "low",
            "text_date_snippets": []
        }
    if not html_content:
        html_content = ""

    parser = ListingDateParser()
    try:
        parser.feed(_strip_non_visible(html_content))
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    cur_year = now.year
    structured_dates = parser.structured_dates
    loose_dates = parser.text_date_snippets
    has_relative_recent = len(parser.relative_time_texts) > 0

    if structured_dates:
        detection_confidence = "high"
        all_dates = structured_dates
    elif loose_dates:
        detection_confidence = "low"
        all_dates = loose_dates
    else:
        detection_confidence = "low"
        all_dates = []

    post_count_found = len(all_dates) + len(parser.relative_time_texts)

    # Rank: full (year+month+day) dates first, then year-only; drop
    # implausible future years so "Roadmap 2027" can't win.
    parsed = [parse_comparable_date(d) for d in all_dates]
    parsed = [p for p in parsed if p[0] == 0 or p[0] <= cur_year + 1]
    full = sorted([p for p in parsed if p[1] and p[2]],
                  key=lambda x: (x[0], x[1], x[2]), reverse=True)
    year_only = sorted([p for p in parsed if not (p[1] and p[2])],
                       key=lambda x: x[0], reverse=True)
    ranked = full + year_only

    most_recent_post_date_found = None
    most_recent_iso = None
    days_since_last_post = None
    date_precision = None

    if has_relative_recent:
        # A relative "N days/hours ago" <time> means a very recent post.
        most_recent_post_date_found = parser.relative_time_texts[0]
        days_since_last_post = 0
        date_precision = "relative_recent"
        detection_confidence = "high"
    elif ranked:
        y, mo, d, raw = ranked[0]
        most_recent_post_date_found = raw
        if y:
            try:
                if mo and d:
                    dt = datetime(y, mo, d, tzinfo=timezone.utc)
                    date_precision = "day"
                else:
                    # Only a year was recoverable (e.g. a non-English month name
                    # the English MONTH_MAP cannot parse). Do NOT invent Jan 1 --
                    # that can overstate age by up to 11 months and flip the
                    # 365-day decay verdict. Assume the LATEST possible date in
                    # that year (capped at today), so the age is the minimum the
                    # evidence supports and decay can never be a false positive.
                    dt = min(datetime(y, 12, 31, tzinfo=timezone.utc), now)
                    date_precision = "year_only"
                most_recent_iso = dt.date().isoformat()
                days_since_last_post = (now - dt).days
            except Exception:
                pass

    # With year-only precision the day count is a lower bound on age, so
    # `is_decayed` is only asserted when even that lower bound exceeds the
    # threshold. It is never asserted on a bare year for the current or
    # previous year, where the true date is unknowable from the evidence.
    is_decayed = (days_since_last_post is not None
                  and days_since_last_post > DECAY_THRESHOLD_DAYS)

    return {
        "url": url,
        "checked": True,
        "fetch_status": status,
        "most_recent_post_date_found": most_recent_post_date_found,
        "most_recent_post_date_iso": most_recent_iso,
        "date_precision": date_precision,
        "days_since_last_post": days_since_last_post,
        "is_decayed": is_decayed,
        "decay_threshold_days": DECAY_THRESHOLD_DAYS,
        "post_count_found": post_count_found,
        "has_relative_recent_timestamps": has_relative_recent,
        "detection_confidence": detection_confidence if post_count_found > 0 else "low",
        "text_date_snippets": loose_dates[:15],
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
    return res[0].lstrip("\ufeff") if res else ""

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

        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
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

        result = check_temporal_decay(html_content, url, status=params.get("status"))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "url": None,
            "checked": False,
            "most_recent_post_date_found": None,
            "most_recent_post_date_iso": None,
            "date_precision": None,
            "days_since_last_post": None,
            "is_decayed": False,
            "post_count_found": 0,
            "has_relative_recent_timestamps": False,
            "detection_confidence": "low",
            "text_date_snippets": [],
            "script_error": str(e)
        }))
