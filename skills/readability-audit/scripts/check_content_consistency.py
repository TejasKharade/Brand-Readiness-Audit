
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import os
import re
from html.parser import HTMLParser
from check_structured_data import check_structured_data

def load_patterns():
    ref_path = os.path.join(os.path.dirname(__file__), '../references/key_fact_patterns.json')
    try:
        if os.path.exists(ref_path):
            with open(ref_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {
        'price_patterns': [
            r'[\$\€\£\₹\¥]\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)',
            r'[\$\€\£\₹\¥]?\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)\s*[\$\€\£\₹\¥]?',
            r'[\$\€\£\₹\¥]\s*([0-9]+(?:\.[0-9]{2})?)\s*[\-\–\—]\s*[\$\€\£\₹\¥]?\s*([0-9]+(?:\.[0-9]{2})?)',
            r'([0-9]+(?:\.[0-9]{2})?)\s*(?:USD|EUR|GBP|INR|JPY)'
        ],
        'availability_patterns': [r'\b(in\s*stock|out\s*of\s*stock|pre\s*order|backorder|available|discontinued)\b'],
        'availability_mapping': {
            'http://schema.org/instock': 'in_stock', 'https://schema.org/instock': 'in_stock',
            'instock': 'in_stock', 'in stock': 'in_stock', 'available': 'in_stock',
            'http://schema.org/outofstock': 'out_of_stock', 'https://schema.org/outofstock': 'out_of_stock',
            'outofstock': 'out_of_stock', 'out of stock': 'out_of_stock'
        }
    }

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_fragments = []
        self.skip_tags = {'script', 'style', 'noscript', 'iframe', 'svg'}
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.in_skip = False
        self.current_skip_tag = None
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
        
        style_attr = attrs_dict.get('style', '').lower()
        is_hidden = ('hidden' in attrs_dict or
                     attrs_dict.get('aria-hidden', '').lower() == 'true' or
                     'display:none' in style_attr.replace(' ', '') or
                     'visibility:hidden' in style_attr.replace(' ', ''))
        
        if tag_lower not in self.void_tags:
            if is_hidden or self.hidden_depth > 0:
                self.hidden_depth += 1

        if tag_lower in self.skip_tags and not self.in_skip:
            self.in_skip = True
            self.current_skip_tag = tag_lower

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if self.in_skip and tag_lower == self.current_skip_tag:
            self.in_skip = False
            self.current_skip_tag = None
            
        if tag_lower not in self.void_tags and self.hidden_depth > 0:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.in_skip and self.hidden_depth == 0 and data.strip():
            self.text_fragments.append(data.strip())

    def get_text(self):
        return ' '.join(self.text_fragments)

def parse_price_value(val_str):
    if not val_str:
        return None
    s = str(val_str).strip()
    if re.search(r'\.[0-9]{3},[0-9]{2}$', s):
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '')
    try:
        return float(re.sub(r'[^0-9.]', '', s))
    except ValueError:
        return None

def extract_visible_facts(html_content, patterns):
    parser = TextExtractor()
    try:
        parser.feed(html_content or '')
    except Exception:
        pass
    text = parser.get_text()
    
    price_val = None
    for pat in patterns.get('price_patterns', []):
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            price_val = match.group(1) if match.groups() else match.group(0)
            break
            
    avail_val = None
    for pat in patterns.get('availability_patterns', []):
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            avail_val = match.group(0)
            break
            
    return text, price_val, avail_val

def fuzzy_fact_match(fact_value, visible_text, mapping=None):
    if not fact_value or not visible_text:
        return False
    val_str = str(fact_value).strip().lower()
    text_clean = visible_text.lower()
    
    # Check normalized availability values (e.g. InStock -> in stock)
    if mapping and val_str in mapping:
        mapped_val = mapping[val_str].replace('_', ' ')
        if mapped_val in text_clean:
            return True

    # 1. Substring match (including underscore replacement for schema URLs)
    if val_str in text_clean or val_str.replace('_', ' ') in text_clean:
        return True
        
    # 2. Number / Currency numeric match
    num_match = re.search(r'[0-9]+(?:\.[0-9]+)?', val_str)
    if num_match:
        n_val = num_match.group(0)
        if n_val in text_clean:
            return True

    # 3. Token overlap match for multi-word strings
    stopwords = {'a', 'an', 'the', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'of', 'https', 'http', 'com', 'www', 'schema', 'org'}
    tokens = set(re.findall(r'\w+', val_str)) - stopwords
    if not tokens:
        return False
    text_tokens = set(re.findall(r'\w+', text_clean))
    overlap = tokens.intersection(text_tokens)
    return len(overlap) / len(tokens) >= 0.7

# A page almost never prints its own URL as prose, so a `url` value can never
# "verify" -- counting it swamped the ratio on ordinary CMS markup (every
# WebSite/WPHeader/ImageObject node carries one) and fired on healthy pages.
NON_PROSE_FACT_FIELDS = {'url'}

def extract_entity_facts(entity):
    """
    Extracts key scalar facts from any schema entity (Product, Article, Organization, Event, Recipe, etc.)
    """
    facts = []
    ef = entity.get('extracted_facts', {})
    for k, v in ef.items():
        if k in NON_PROSE_FACT_FIELDS:
            continue
        if isinstance(v, str) and v.strip():
            facts.append({'field': k, 'value': v.strip()})
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    facts.append({'field': k, 'value': item.strip()})

    prod_comp = entity.get('product_completeness', {})
    if prod_comp:
        p = prod_comp.get('extracted_price')
        a = prod_comp.get('extracted_availability')
        if p and not any(f['field'] == 'price' for f in facts):
            facts.append({'field': 'price', 'value': str(p)})
        if a and not any(f['field'] == 'availability' for f in facts):
            facts.append({'field': 'availability', 'value': str(a)})
            
    return facts

def check_content_consistency(html_content, url):
    patterns = load_patterns()
    visible_text, vis_price, vis_avail = extract_visible_facts(html_content, patterns)
    
    sd_res = check_structured_data(html_content, url)
    entities = sd_res.get('entities', [])
    
    entity_consistency_reports = []
    total_facts_evaluated = 0
    total_facts_verified = 0

    struct_product_name = None
    struct_price = None
    struct_avail = None

    for ent_idx, ent in enumerate(entities):
        types = ent.get('types', [])
        ent_name = ent.get('name')
        facts = extract_entity_facts(ent)
        
        evaluated_facts = []
        ent_verified_count = 0
        
        mapping = patterns.get('availability_mapping', {})
        for f in facts:
            field_name = f['field']
            val = f['value']
            is_matched = fuzzy_fact_match(val, visible_text, mapping)
            
            evaluated_facts.append({
                'field': field_name,
                'structured_value': val,
                'verified_in_visible_text': is_matched
            })
            
            total_facts_evaluated += 1
            if is_matched:
                total_facts_verified += 1
                ent_verified_count += 1

        entity_consistency_reports.append({
            'entity_index': ent_idx,
            'types': types,
            'entity_name': ent_name,
            'total_facts': len(facts),
            'verified_facts': ent_verified_count,
            'facts_detail': evaluated_facts
        })

        if any(t in ['Product', 'IndividualProduct', 'SomeProducts'] for t in types):
            if not struct_product_name:
                struct_product_name = ent_name
            prod_comp = ent.get('product_completeness', {})
            if struct_price is None:
                struct_price = prod_comp.get('extracted_price')
            if struct_avail is None:
                struct_avail = prod_comp.get('extracted_availability')

    overall_consistency_ratio = (
        round(total_facts_verified / total_facts_evaluated, 2)
        if total_facts_evaluated > 0 else (1.0 if len(entities) > 0 else None)
    )

    # Rolled-up signal consumed by the orchestrator. Deliberately conservative:
    # the underlying check is string/number matching, which misfires on
    # currency and date formats, synonyms ("in stock" vs "ships today"), unit
    # conversions and any non-English text. So it fires only when a meaningful
    # number of facts was evaluated AND most of them failed to verify -- and it
    # always asks the agent to confirm before the orchestrator treats it as a
    # real contradiction.
    MIN_FACTS_FOR_VERDICT = 3
    LOW_CONSISTENCY_RATIO = 0.5
    contains_inconsistency = bool(
        total_facts_evaluated >= MIN_FACTS_FOR_VERDICT
        and overall_consistency_ratio is not None
        and overall_consistency_ratio < LOW_CONSISTENCY_RATIO
    )
    unverified = [
        {'entity': (r.get('types') or ['?'])[0], 'entity_name': r.get('entity_name'),
         'field': f.get('field'), 'structured_value': f.get('structured_value')}
        for r in entity_consistency_reports
        for f in (r.get('facts_detail') or [])
        if f.get('verified_in_visible_text') is False
    ][:10]

    return {
        'overall_summary': {
            'total_entities_evaluated': len(entities),
            'total_facts_evaluated': total_facts_evaluated,
            'total_facts_verified': total_facts_verified,
            'overall_consistency_ratio': overall_consistency_ratio
        },
        'contains_inconsistency': contains_inconsistency,
        'verdict_basis': 'string_match_heuristic -- confirm with agent judgment',
        'needs_agent_judgment': bool(unverified),
        'unverified_facts_for_agent': unverified,
        'agent_judgment_task': ('For each unverified fact, decide whether the visible '
                                'page text really fails to state the structured value, '
                                'or whether it is merely formatted differently '
                                '(currency/date format, synonym, unit, another language). '
                                'Only a genuine mismatch is a finding.'),
        'entity_consistency_reports': entity_consistency_reports
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

        result = check_content_consistency(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
