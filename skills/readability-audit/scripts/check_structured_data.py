import sys
import json
import re
import html

def sanitize_json_ld_string(raw_str):
    if not raw_str:
        return ""
    s = raw_str.strip()
    # Strip HTML comments <!-- ... -->
    s = re.sub(r'^<!--\s*', '', s)
    s = re.sub(r'\s*-->$', '', s)
    # Strip CDATA wrappers //<![CDATA[ ... //]]> or <![CDATA[ ... ]]>
    s = re.sub(r'^//<!\[CDATA\[\s*', '', s)
    s = re.sub(r'^\s*<!\[CDATA\[\s*', '', s)
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

def build_id_lookup(raw_entities):
    id_map = {}
    def register(ent):
        if isinstance(ent, dict):
            ent_id = ent.get('@id')
            if ent_id and isinstance(ent_id, str):
                id_map[ent_id] = ent
            for k, v in ent.items():
                if isinstance(v, dict):
                    register(v)
                elif isinstance(v, list):
                    for item in v:
                        register(item)
    for e, _ in raw_entities:
        register(e)
    return id_map

def resolve_entity_ref(ent_or_ref, id_map):
    if isinstance(ent_or_ref, str) and ent_or_ref in id_map:
        return id_map[ent_or_ref]
    if isinstance(ent_or_ref, dict):
        if len(ent_or_ref) == 1 and '@id' in ent_or_ref:
            ref_id = ent_or_ref['@id']
            return id_map.get(ref_id, ent_or_ref)
        if '@id' in ent_or_ref and ent_or_ref['@id'] in id_map:
            target = id_map[ent_or_ref['@id']]
            if isinstance(target, dict):
                merged = dict(target)
                merged.update(ent_or_ref)
                return merged
    return ent_or_ref

def collect_all_entities(obj, block_idx, visited=None):
    if visited is None:
        visited = set()
    entities = []
    if isinstance(obj, dict):
        obj_id = id(obj)
        if obj_id in visited:
            return entities
        visited.add(obj_id)
        
        if '@type' in obj:
            entities.append((obj, block_idx))
            
        for k, v in obj.items():
            if k == '@graph' and isinstance(v, list):
                for item in v:
                    entities.extend(collect_all_entities(item, block_idx, visited))
            else:
                entities.extend(collect_all_entities(v, block_idx, visited))
    elif isinstance(obj, list):
        for item in obj:
            entities.extend(collect_all_entities(item, block_idx, visited))
    return entities

def parse_entity(entity, block_idx, id_map=None):
    if not isinstance(entity, dict):
        return None
    raw_type = entity.get('@type')
    if not raw_type:
        return None
    
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    types_normalized = [normalize_type(t) for t in types]

    extracted_facts = {}
    for k in ['name', 'headline', 'title', 'description', 'telephone', 'email', 'startDate', 'datePublished', 'recipeIngredient', 'operatingSystem', 'url', 'author']:
        v = entity.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip():
            extracted_facts[k] = str(v).strip()
        elif isinstance(v, dict):
            sub_name = v.get('name')
            if isinstance(sub_name, str) and sub_name.strip():
                extracted_facts[k] = sub_name.strip()
        elif isinstance(v, list):
            str_items = []
            for item in v:
                if isinstance(item, (str, int, float)) and str(item).strip():
                    str_items.append(str(item).strip())
                elif isinstance(item, dict) and isinstance(item.get('name'), str):
                    str_items.append(item['name'].strip())
            if str_items:
                extracted_facts[k] = str_items

    details = {
        'block_index': block_idx,
        'types': types_normalized,
        'name': entity.get('name') or entity.get('headline') if isinstance(entity.get('name') or entity.get('headline'), str) else None,
        'extracted_facts': extracted_facts
    }
    
    # 1. Product Completeness
    if any(t in ['Product', 'IndividualProduct', 'SomeProducts'] for t in types_normalized):
        offers = entity.get('offers')
        offer_list = offers if isinstance(offers, list) else ([offers] if isinstance(offers, dict) else [])
        
        has_offers = len(offer_list) > 0
        has_price = False
        has_availability = False
        extracted_price = None
        extracted_availability = None
        
        for off in offer_list:
            off_resolved = resolve_entity_ref(off, id_map or {})
            if isinstance(off_resolved, dict):
                p = off_resolved.get('price') or off_resolved.get('lowPrice') or off_resolved.get('highPrice')
                p_spec = off_resolved.get('priceSpecification')
                if isinstance(p_spec, dict) and p_spec.get('price') is not None:
                    p = p_spec.get('price')
                if p is not None:
                    has_price = True
                    if extracted_price is None:
                        extracted_price = p
                    
                avail = off_resolved.get('availability')
                if avail is not None:
                    has_availability = True
                    if extracted_availability is None:
                        extracted_availability = avail
                    
        missing = []
        if not entity.get('name'):
            missing.append('name')
        if not has_offers:
            missing.append('offers')
        if not has_price:
            missing.append('offers.price')
        if not has_availability:
            missing.append('offers.availability')
            
        details['product_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_offers': has_offers,
            'has_price': has_price,
            'has_availability': has_availability,
            'extracted_price': str(extracted_price) if extracted_price is not None else None,
            'extracted_availability': str(extracted_availability) if extracted_availability is not None else None,
            'missing_fields': missing
        }

    # 2. FAQPage Completeness
    if any(t == 'FAQPage' for t in types_normalized):
        main_entity = entity.get('mainEntity')
        q_list = main_entity if isinstance(main_entity, list) else ([main_entity] if isinstance(main_entity, dict) else [])
        
        questions_detected = 0
        questions_complete = 0
        
        for q in q_list:
            q_res = resolve_entity_ref(q, id_map or {})
            if isinstance(q_res, dict):
                questions_detected += 1
                q_name = q_res.get('name')
                ans = q_res.get('acceptedAnswer')
                ans_res = resolve_entity_ref(ans, id_map or {})
                ans_text = ans_res.get('text') if isinstance(ans_res, dict) else None
                if q_name and ans_text:
                    questions_complete += 1
                    
        details['faq_completeness'] = {
            'main_entity_present': bool(main_entity),
            'questions_detected': questions_detected,
            'questions_complete': questions_complete
        }

    # 3. Organization / LocalBusiness Completeness
    if any(t in ['Organization', 'Corporation', 'LocalBusiness', 'Store', 'Restaurant'] for t in types_normalized):
        details['organization_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_url': bool(entity.get('url')),
            'has_logo': bool(entity.get('logo')),
            'has_telephone': bool(entity.get('telephone'))
        }

    # 4. Article Completeness
    if any(t in ['Article', 'NewsArticle', 'BlogPosting'] for t in types_normalized):
        details['article_completeness'] = {
            'has_headline': bool(entity.get('headline') or entity.get('name')),
            'has_author': bool(entity.get('author')),
            'has_date_published': bool(entity.get('datePublished')),
            'has_image': bool(entity.get('image'))
        }

    # 5. BreadcrumbList Completeness
    if any(t == 'BreadcrumbList' for t in types_normalized):
        items = entity.get('itemListElement', [])
        details['breadcrumb_completeness'] = {
            'item_count': len(items) if isinstance(items, list) else 0
        }

    # 6. Recipe Completeness
    if any(t == 'Recipe' for t in types_normalized):
        details['recipe_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_ingredients': bool(entity.get('recipeIngredient')),
            'has_instructions': bool(entity.get('recipeInstructions')),
            'has_image': bool(entity.get('image'))
        }

    # 7. Event Completeness
    if any(t in ['Event', 'BusinessEvent', 'MusicEvent', 'ExhibitionEvent'] for t in types_normalized):
        details['event_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_start_date': bool(entity.get('startDate')),
            'has_location': bool(entity.get('location'))
        }

    # 8. SoftwareApplication Completeness
    if any(t in ['SoftwareApplication', 'MobileApplication', 'WebApplication'] for t in types_normalized):
        details['software_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_operating_system': bool(entity.get('operatingSystem')),
            'has_offers': bool(entity.get('offers'))
        }

    # 9. VideoObject Completeness
    if any(t == 'VideoObject' for t in types_normalized):
        details['video_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_thumbnail': bool(entity.get('thumbnailUrl')),
            'has_upload_date': bool(entity.get('uploadDate'))
        }

    return details

def check_structured_data(html_content, url):
    raw_blocks = extract_json_ld_blocks(html_content)
    total_blocks = len(raw_blocks)
    parsed_blocks_count = 0
    raw_entities = []
    errors = []

    microdata_detected = bool(re.search(r'\bitemscope\b', html_content or '', re.IGNORECASE))
    rdfa_detected = bool(re.search(r'\b(vocab|typeof)\s*=', html_content or '', re.IGNORECASE))

    for idx, block_str in enumerate(raw_blocks):
        data = None
        try:
            data = json.loads(block_str)
            parsed_blocks_count += 1
        except Exception:
            try:
                unescaped_str = html.unescape(block_str)
                data = json.loads(unescaped_str)
                parsed_blocks_count += 1
            except Exception as e:
                errors.append({'block_index': idx, 'error': f'JSON Parse Error: {str(e)}'})

        if data:
            collected = collect_all_entities(data, idx)
            raw_entities.extend(collected)

    id_map = build_id_lookup(raw_entities)

    parsed_entities = []
    for ent, idx in raw_entities:
        parsed_ent = parse_entity(ent, idx, id_map)
        if parsed_ent:
            parsed_entities.append(parsed_ent)

    return {
        'total_json_ld_blocks': total_blocks,
        'parsed_json_ld_blocks': parsed_blocks_count,
        'microdata_detected': microdata_detected,
        'rdfa_detected': rdfa_detected,
        'recognized_entities_count': len(parsed_entities),
        'entities': parsed_entities,
        'parse_errors': errors
    }

import threading

def read_stdin_safe(timeout=0.2):
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

        input_data = read_stdin_safe(timeout=0.2)
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

        result = check_structured_data(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
