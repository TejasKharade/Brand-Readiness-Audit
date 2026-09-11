
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re

def sanitize_json_ld_string(raw_str):
    if not raw_str:
        return ""
    s = raw_str.strip()
    s = re.sub(r'^<!--\s*', '', s)
    s = re.sub(r'\s*-->$', '', s)
    s = re.sub(r'^//<!\[CDATA\[\s*', '', s)
    s = re.sub(r'^\s*<!\[CDATA\[\s*', '', s)
    s = re.sub(r'^/\*\s*<!\[CDATA\[\s*\*/', '', s)    # /* <![CDATA[ */ variant
    s = re.sub(r'/\*\s*\]\]>\s*\*/$', '', s)           # /* ]]> */ closing variant
    s = re.sub(r'\s*//\]\]>\s*$', '', s)
    s = re.sub(r'\s*\]\]>\s*$', '', s)
    return s.strip()

def extract_json_ld_blocks(html_content):
    if not html_content:
        return []
    blocks = []
    for m in re.finditer(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>', html_content, re.IGNORECASE):
        start_idx = m.end()
        obj_start = -1
        for i in range(start_idx, len(html_content)):
            if html_content[i] in '{[':
                obj_start = i
                break
        if obj_start == -1:
            continue
        
        stack = []
        in_string = False
        escape = False
        obj_end = -1
        for i in range(obj_start, len(html_content)):
            ch = html_content[i]
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
            cleaned = sanitize_json_ld_string(html_content[obj_start:obj_end])
            if cleaned:
                blocks.append(cleaned)
    return blocks

def normalize_type(raw):
    if not raw:
        return ""
    s = str(raw).strip()
    s = re.sub(r'^https?://schema\.org/', '', s, flags=re.IGNORECASE)
    return s.rsplit('/', 1)[-1]

def extract_entity_types_from_blocks(blocks):
    detected_types = set()

    def collect_types(obj, visited=None):
        if visited is None:
            visited = set()
        if isinstance(obj, dict):
            obj_id = id(obj)
            if obj_id in visited:
                return
            visited.add(obj_id)

            if '@type' in obj:
                raw_type = obj['@type']
                types = raw_type if isinstance(raw_type, list) else [raw_type]
                for t in types:
                    norm = normalize_type(t)
                    if norm:
                        detected_types.add(norm)
            for k, v in obj.items():
                collect_types(v, visited)
        elif isinstance(obj, list):
            for item in obj:
                collect_types(item, visited)

    for block_str in blocks:
        try:
            data = json.loads(block_str)
            collect_types(data)
        except Exception:
            pass
    return detected_types

def check_structured_data_hydration(raw_html, rendered_html, url):
    raw_blocks = extract_json_ld_blocks(raw_html)
    has_rendered = bool(rendered_html and rendered_html.strip())
    rendered_blocks = extract_json_ld_blocks(rendered_html) if has_rendered else []

    raw_types = extract_entity_types_from_blocks(raw_blocks)
    # When no rendered_html, do NOT fall back to raw_types — leave as None so
    # we don't falsely report zero trapped entities.
    rendered_types = extract_entity_types_from_blocks(rendered_blocks) if has_rendered else None

    # Identify entities present in rendered DOM but missing from raw initial HTML
    if has_rendered and rendered_types is not None:
        js_trapped_entities = list(rendered_types - raw_types)
        js_injected_blocks_count = max(len(rendered_blocks) - len(raw_blocks), 0)
        has_hydration_barrier = (
            len(js_trapped_entities) > 0
            or (len(raw_blocks) == 0 and len(rendered_blocks) > 0)
        )
    else:
        js_trapped_entities = []
        js_injected_blocks_count = 0
        # Cannot determine hydration barrier without rendered HTML — report unknown (None)
        has_hydration_barrier = None

    return {
        'has_rendered_comparison': has_rendered,
        'initial_raw_html': {
            'json_ld_blocks_count': len(raw_blocks),
            'detected_schema_types': sorted(list(raw_types))
        },
        'rendered_dom': {
            'json_ld_blocks_count': len(rendered_blocks) if has_rendered else None,
            'detected_schema_types': sorted(list(rendered_types)) if has_rendered and rendered_types is not None else None
        },
        'hydration_analysis': {
            'js_trapped_schema_types': sorted(js_trapped_entities),
            'js_injected_blocks_count': js_injected_blocks_count,
            'structured_data_hydration_barrier_detected': has_hydration_barrier
        }
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

if __name__ == '__main__':
    try:
        raw_html = ""
        rendered_html = ""
        url = ""
        params = {}

        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                    raw_html = params.get("raw_html", "") or params.get("html", "")
                    rendered_html = params.get("rendered_html", "")
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

        if not raw_html:
            raw_html = params.get('raw_html', '') or params.get('html', '')
        if not rendered_html:
            rendered_html = params.get('rendered_html', '')
        if not url:
            url = params.get('url', '')

        result = check_structured_data_hydration(raw_html, rendered_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
