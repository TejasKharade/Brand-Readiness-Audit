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
    s = re.sub(r'\s*//\]\]>\s*$', '', s)
    s = re.sub(r'\s*\]\]>\s*$', '', s)
    return s.strip()

def extract_json_ld_blocks(html_content):
    blocks = []
    pattern = re.compile(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html_content or ''):
        raw_inner = match.group(1)
        cleaned = sanitize_json_ld_string(raw_inner)
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
    rendered_types = extract_entity_types_from_blocks(rendered_blocks) if has_rendered else raw_types

    # Identify entities present in rendered DOM but missing from raw initial HTML
    js_trapped_entities = list(rendered_types - raw_types)
    js_injected_blocks_count = max(len(rendered_blocks) - len(raw_blocks), 0) if has_rendered else 0

    has_hydration_barrier = len(js_trapped_entities) > 0 or (has_rendered and len(raw_blocks) == 0 and len(rendered_blocks) > 0)

    return {
        'has_rendered_comparison': has_rendered,
        'initial_raw_html': {
            'json_ld_blocks_count': len(raw_blocks),
            'detected_schema_types': sorted(list(raw_types))
        },
        'rendered_dom': {
            'json_ld_blocks_count': len(rendered_blocks) if has_rendered else None,
            'detected_schema_types': sorted(list(rendered_types)) if has_rendered else None
        },
        'hydration_analysis': {
            'js_trapped_schema_types': sorted(js_trapped_entities),
            'js_injected_blocks_count': js_injected_blocks_count,
            'structured_data_hydration_barrier_detected': has_hydration_barrier
        }
    }

if __name__ == '__main__':
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}
            
        raw_html = params.get('raw_html', '') or params.get('html', '')
        rendered_html = params.get('rendered_html', '')
        url = params.get('url', '')
        
        result = check_structured_data_hydration(raw_html, rendered_html, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
