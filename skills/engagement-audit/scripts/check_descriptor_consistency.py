
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import urllib.parse
from html.parser import HTMLParser

class PageHeaderParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_text = []
        self.h1_text = []
        self.jsonld_scripts = []
        self.meta_description = None
        
        self.in_title = False
        self.in_h1 = False
        self.in_jsonld = False
        self.current_jsonld = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}

        if tag_lower == "title":
            self.in_title = True
        elif tag_lower == "meta" and self.meta_description is None \
                and attrs_dict.get("name", "").strip().lower() == "description":
            self.meta_description = attrs_dict.get("content", "")
        elif tag_lower == "h1":
            self.in_h1 = True
        elif tag_lower == "script":
            type_attr = attrs_dict.get("type", "").lower()
            if type_attr == "application/ld+json":
                self.in_jsonld = True
                self.current_jsonld = []

    def handle_data(self, data):
        if not data:
            return
        if self.in_title:
            self.title_text.append(data)
        elif self.in_h1:
            self.h1_text.append(data)
        elif self.in_jsonld:
            self.current_jsonld.append(data)

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.in_title = False
        elif tag_lower == "h1":
            self.in_h1 = False
        elif tag_lower == "script" and self.in_jsonld:
            self.in_jsonld = False
            raw_script = "".join(self.current_jsonld).strip()
            if raw_script:
                self.jsonld_scripts.append(raw_script)
            self.current_jsonld = []

def extract_brand_from_jsonld(jsonld_scripts):
    for raw_json in jsonld_scripts:
        try:
            data = json.loads(raw_json)
            nodes = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and "@graph" in data and isinstance(data["@graph"], list):
                nodes = data["@graph"]

            for node in nodes:
                if not isinstance(node, dict):
                    continue
                type_val = node.get("@type", "")
                if isinstance(type_val, list):
                    type_strs = [str(t).lower() for t in type_val]
                else:
                    type_strs = [str(type_val).lower()]

                if any(t in ["organization", "brand", "corporation", "localbusiness"] for t in type_strs):
                    name = node.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
        except Exception:
            pass
    return None

def find_candidate_brand_phrase(parsed_pages):
    # 1. Try JSON-LD first
    for page in parsed_pages:
        brand = extract_brand_from_jsonld(page["jsonld_scripts"])
        if brand:
            return brand

    # 2. Extract repeated multi-word phrase or common segment from titles/H1s
    segments = []
    for page in parsed_pages:
        title = page["title"]
        h1 = page["h1"]
        for text in [title, h1]:
            if not text:
                continue
            # Split on common delimiters like |, -, :, —, •
            parts = re.split(r'[\|\-\:—•]', text)
            for p in parts:
                cleaned = p.strip()
                if len(cleaned.split()) >= 1 and len(cleaned) >= 2:
                    segments.append(cleaned)

    # Count occurrences of segments
    counts = {}
    for seg in segments:
        seg_lower = seg.lower()
        counts[seg_lower] = counts.get(seg_lower, 0) + 1

    # Filter for segments appearing >= 2 times (or find most frequent capitalized segment)
    best_candidate = None
    max_count = 1
    for seg, count in counts.items():
        if count > max_count:
            # Pick original casing from segments
            for orig in segments:
                if orig.lower() == seg:
                    best_candidate = orig
                    max_count = count
                    break

    return best_candidate

def check_descriptor_consistency(pages_data):
    if not isinstance(pages_data, list):
        pages_data = []

    parsed_pages = []
    for item in pages_data:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        html = item.get("html", "")
        
        parser = PageHeaderParser()
        try:
            if html:
                parser.feed(html)
        except Exception:
            pass

        title_str = " ".join("".join(parser.title_text).split())
        h1_str = " ".join("".join(parser.h1_text).split())

        desc_str = " ".join((parser.meta_description or "").split())
        parsed_pages.append({
            "url": url,
            "title": title_str if title_str else None,
            "h1": h1_str if h1_str else None,
            "meta_description": desc_str if desc_str else None,
            "jsonld_scripts": parser.jsonld_scripts
        })

    candidate_brand = find_candidate_brand_phrase(parsed_pages)

    # Core brand without legal designators (Inc, LLC, Ltd, Corp, Corporation, Co)
    core_brand = None
    if candidate_brand:
        core_brand = re.sub(r'\b(Inc\.?|LLC|Ltd\.?|Corporation|Corp\.?|Co\.?)\b', '', candidate_brand, flags=re.IGNORECASE).strip()
        if len(core_brand) < 2:
            core_brand = candidate_brand

    results = []
    for p in parsed_pages:
        title_has_brand = False
        h1_has_brand = False

        if candidate_brand:
            cb_lower = candidate_brand.lower()
            core_lower = core_brand.lower() if core_brand else cb_lower

            if p["title"]:
                t_lower = p["title"].lower()
                title_has_brand = (cb_lower in t_lower) or (core_lower in t_lower)
            if p["h1"]:
                h1_lower = p["h1"].lower()
                h1_has_brand = (cb_lower in h1_lower) or (core_lower in h1_lower)

        results.append({
            "url": p["url"],
            "title": p["title"],
            "h1": p["h1"],
            "meta_description": p["meta_description"],
            "brand_phrase_present_in_title": title_has_brand,
            "brand_phrase_present_in_h1": h1_has_brand
        })

    # The same meta description on DIFFERENT pages is a template default: the
    # description stops saying what each page is about, so a search result or
    # AI answer cannot tell the pages apart from their summaries. URLs are
    # compared by host + path (scheme, query, fragment and a trailing slash
    # ignored), so one page sampled twice -- with and without a tracking
    # parameter -- is never reported against itself.
    def _page_key(u):
        try:
            pu = urllib.parse.urlparse(u or "")
            host = pu.netloc.lower()
            host = host[4:] if host.startswith("www.") else host
            return (host, (pu.path or "/").rstrip("/") or "/")
        except Exception:
            return (u or "", "")

    by_desc = {}
    for p in parsed_pages:
        if p["meta_description"]:
            by_desc.setdefault(p["meta_description"].casefold(), {"description": p["meta_description"],
                                                                  "urls": [], "_keys": set()})
            entry = by_desc[p["meta_description"].casefold()]
            key = _page_key(p["url"])
            if key not in entry["_keys"]:
                entry["_keys"].add(key)
                entry["urls"].append(p["url"])
    duplicate_meta_descriptions = [
        {"description": e["description"], "urls": e["urls"], "page_count": len(e["urls"])}
        for e in by_desc.values() if len(e["urls"]) >= 2
    ]
    distinct_pages = len({_page_key(p["url"]) for p in parsed_pages})

    return {
        "candidate_brand_phrase": candidate_brand,
        "pages_audited": len(results),
        "distinct_pages_audited": distinct_pages,
        "pages": results,
        "duplicate_meta_descriptions": duplicate_meta_descriptions,
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
        pages_data = []
        params = {}

        # 1. Parse command line arguments if present
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{") or raw_arg.startswith("["):
                try:
                    parsed = json.loads(raw_arg)
                    if isinstance(parsed, dict):
                        params.update(parsed)
                    elif isinstance(parsed, list):
                        pages_data = parsed
                except json.JSONDecodeError:
                    pass

        # 2. Read stdin safely with non-blocking 0.2s timeout
        input_data = read_stdin_safe(timeout=1.0 if len(sys.argv) > 1 else 5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
                elif isinstance(stdin_params, list):
                    pages_data = stdin_params
            except json.JSONDecodeError:
                pass

        if not pages_data:
            pages_data = params.get("pages", [])
            if not pages_data and ("url" in params or "html" in params):
                pages_data = [params]

        result = check_descriptor_consistency(pages_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({
            "candidate_brand_phrase": None,
            "pages_audited": 0,
            "distinct_pages_audited": 0,
            "pages": [],
            "duplicate_meta_descriptions": [],
            "script_error": str(e)
        }))
