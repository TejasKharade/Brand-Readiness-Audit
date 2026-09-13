
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import sys
import json
import re
import html
import urllib.parse

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
    
    # 0. Description quality (length only -- no opinion about wording).
    if any(t in DESCRIBABLE_TYPES for t in types_normalized):
        desc = entity.get('description')
        if isinstance(desc, dict):
            desc = desc.get('@value') or desc.get('name')
        if isinstance(desc, list):
            desc = next((d for d in desc if isinstance(d, str) and d.strip()), None)
        desc_text = ' '.join(str(desc).split()) if isinstance(desc, (str, int, float)) else ''
        details['description_quality'] = {
            'has_description': bool(desc_text),
            'length': len(desc_text),
            'too_short': bool(desc_text) and len(desc_text) < DESCRIPTION_MIN_CHARS,
            'text': desc_text[:120],
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
        
        pairs = []
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
                    pairs.append({'question': q_name, 'answer': ans_text})

        details['faq_completeness'] = {
            'main_entity_present': bool(main_entity),
            'questions_detected': questions_detected,
            'questions_complete': questions_complete,
            # Carried through for check_faq_visible_text_match() -- capped
            # length is fine here, the full text still lives in the entity.
            'pairs': pairs,
        }

    # 3. Organization / LocalBusiness Completeness
    if any(t in ['Organization', 'Corporation', 'LocalBusiness', 'Store', 'Restaurant'] for t in types_normalized):
        telephone = entity.get('telephone')
        address_text = flatten_address(entity.get('address'))
        details['organization_completeness'] = {
            'has_name': bool(entity.get('name')),
            'has_url': bool(entity.get('url')),
            'has_logo': bool(entity.get('logo')),
            'has_telephone': bool(telephone),
            # Carried through for check_nap_consistency() -- Name/Address/
            # Phone agreement between schema and the page's own visible text
            # is the on-site instance of "agreement across the web matters".
            'telephone': telephone if isinstance(telephone, str) else None,
            'address_text': address_text,
        }

    # 4. Article Completeness
    if any(t in ['Article', 'NewsArticle', 'BlogPosting'] for t in types_normalized):
        author_names = extract_author_names(entity.get('author'))
        details['article_completeness'] = {
            'has_headline': bool(entity.get('headline') or entity.get('name')),
            'has_author': bool(entity.get('author')),
            'has_date_published': bool(entity.get('datePublished')),
            'has_image': bool(entity.get('image')),
            # E-E-A-T: a byline naming a real person/organization is a cited
            # AI-trust signal; a CMS default left in place ("admin") is not.
            # Deliberately a narrow, high-confidence placeholder list only --
            # "Staff Writer" / "Editorial Team" are legitimate organizational
            # bylines used by real publications and are NOT flagged.
            'author_names': author_names,
            'generic_placeholder_author': (
                bool(author_names)
                and all(n.strip().lower() in GENERIC_AUTHOR_PLACEHOLDERS for n in author_names)
            ),
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

# --- Entity grounding -------------------------------------------------------
# An AI answer engine reading a page needs to know WHO publishes it and WHAT it
# is about. Schema.org markup can be technically valid and still answer neither
# question: a page whose only JSON-LD is a BreadcrumbList + ListItem chain
# describes its own navigation and nothing else. These sets let the orchestrator
# tell that apart from real subject markup without guessing about types nobody
# here classified -- those are reported separately and never used to claim
# something is missing.

# Types that anchor an identity -- "this site/page belongs to X".
IDENTITY_ROOT_TYPES = {
    'Organization', 'Corporation', 'LocalBusiness', 'Store', 'Restaurant',
    'NGO', 'NewsMediaOrganization', 'EducationalOrganization', 'CollegeOrUniversity',
    'School', 'GovernmentOrganization', 'MedicalOrganization', 'SportsOrganization',
    'PerformingGroup', 'Airline', 'OnlineBusiness', 'OnlineStore',
    'Brand', 'Person', 'WebSite',
}

# Types that carry a page's actual subject matter.
SUBJECT_ENTITY_TYPES = {
    'Product', 'IndividualProduct', 'SomeProducts', 'ProductGroup', 'Offer', 'AggregateOffer',
    'Article', 'NewsArticle', 'BlogPosting', 'TechArticle', 'ScholarlyArticle', 'Report',
    'Blog', 'Recipe', 'Event', 'BusinessEvent', 'MusicEvent', 'ExhibitionEvent',
    'SoftwareApplication', 'MobileApplication', 'WebApplication', 'SoftwareSourceCode',
    'Service', 'Course', 'JobPosting', 'VideoObject', 'AudioObject', 'Podcast',
    'PodcastEpisode', 'Book', 'Dataset', 'FAQPage', 'HowTo', 'QAPage', 'Review',
    'MedicalWebPage', 'RealEstateListing', 'Vehicle', 'Place', 'TouristAttraction',
}

# Types that describe page furniture or are pure value objects hanging off a
# parent entity (an address, a rating, an opening-hours block): useful, but
# never a page subject and never an identity on their own. Listing them keeps
# them out of `unclassified`, so a stray PostalAddress cannot mask a homepage
# that genuinely has no identity entity.
STRUCTURAL_ONLY_TYPES = {
    'PostalAddress', 'ContactPoint', 'GeoCoordinates', 'GeoShape',
    'OpeningHoursSpecification', 'QuantitativeValue', 'PropertyValue',
    'AggregateRating', 'Rating', 'MonetaryAmount', 'PriceSpecification',
    'UnitPriceSpecification', 'Duration', 'Distance', 'Language',
    'DefinedTerm', 'Thing',
    'BreadcrumbList', 'ListItem', 'ItemList', 'SiteNavigationElement',
    'WebPage', 'CollectionPage', 'ProfilePage', 'AboutPage', 'ContactPage',
    'SearchResultsPage', 'CheckoutPage', 'WebPageElement', 'WPHeader', 'WPFooter',
    'WPSideBar', 'SearchAction', 'ReadAction', 'EntryPoint', 'ImageObject',
}

# A description shorter than this is a label ("Home", "Acme"), not a summary an
# answer engine can quote. Deliberately a length test only -- no opinion about
# which words a good description should contain.
DESCRIPTION_MIN_CHARS = 25

# Types for which a missing `description` is worth reporting. A BreadcrumbList
# has nothing to describe, so it is not on this list.
DESCRIBABLE_TYPES = (IDENTITY_ROOT_TYPES | SUBJECT_ENTITY_TYPES) - {
    'WebSite', 'Offer', 'AggregateOffer', 'ListItem'}


def looks_like_site_root(url_str):
    """True when the audited URL is the site root (or a locale-prefixed root).

    The homepage is the one page where a missing identity entity is a real
    finding: an interior page may legitimately carry only its own subject
    markup and inherit identity from the homepage.
    """
    try:
        path = urllib.parse.urlparse(url_str or '').path or ''
    except Exception:
        return False
    segs = [s for s in path.split('/') if s]
    if not segs:
        return True
    if len(segs) == 1:
        seg = segs[0].lower()
        if seg in ('index.html', 'index.htm', 'index.php', 'home'):
            return True
        return len(seg) <= 5  # locale prefix such as /en/, /de/, /en-us/
    return False


def assess_entity_grounding(parsed_entities, url):
    """Fact-only summary of what the page's schema actually identifies.

    No verdict is produced here. `structural_only` is asserted only when every
    entity on the page is a classified structural type, so an unrecognised type
    can never be mistaken for "describes nothing".
    """
    identity, subject, structural, unclassified = [], [], [], []
    for ent in parsed_entities:
        types = [t for t in ent.get('types', []) if t]
        if any(t in IDENTITY_ROOT_TYPES for t in types):
            identity.extend(t for t in types if t in IDENTITY_ROOT_TYPES)
        elif any(t in SUBJECT_ENTITY_TYPES for t in types):
            subject.extend(t for t in types if t in SUBJECT_ENTITY_TYPES)
        elif types and all(t in STRUCTURAL_ONLY_TYPES for t in types):
            structural.extend(types)
        else:
            unclassified.extend(types)

    def uniq(seq):
        return sorted(set(seq))

    return {
        'is_site_root': looks_like_site_root(url),
        'identity_entity_types': uniq(identity),
        'subject_entity_types': uniq(subject),
        'structural_entity_types': uniq(structural),
        'unclassified_entity_types': uniq(unclassified),
        'has_identity_entity': bool(identity),
        'has_subject_entity': bool(subject),
        'structural_only': bool(parsed_entities) and not identity and not subject and not unclassified,
    }


def summarize_descriptions(parsed_entities):
    """Which describable entities carry a usable `description`, and which do not."""
    missing, too_short, described = [], [], 0
    for ent in parsed_entities:
        types = [t for t in ent.get('types', []) if t]
        if not any(t in DESCRIBABLE_TYPES for t in types):
            continue
        quality = ent.get('description_quality') or {}
        label = types[0]
        if not quality.get('has_description'):
            missing.append(label)
        elif quality.get('too_short'):
            too_short.append({'type': label, 'length': quality.get('length', 0),
                              'text': quality.get('text', '')})
        else:
            described += 1
    return {
        'describable_entities': len(missing) + len(too_short) + described,
        'with_description': described,
        'missing_description_types': sorted(set(missing)),
        'short_description_entities': too_short[:5],
        'min_useful_chars': DESCRIPTION_MIN_CHARS,
    }


# --- FAQ schema vs. visible text --------------------------------------------
# FAQPage schema is only trustworthy when its answers correspond to something
# a visitor -- and therefore a non-JS crawler reading raw HTML -- can actually
# see. Stale schema left over after a content edit, or FAQ schema written
# purely to game rankings without ever showing the content on the page, both
# produce the same signature: an answer sharing almost no vocabulary with
# anything visible on the page.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "as", "that", "this", "these", "those", "it", "its", "you", "your", "we",
    "our", "they", "their", "he", "she", "his", "her", "do", "does", "did",
    "can", "could", "will", "would", "should", "may", "might", "not", "no",
    "yes", "if", "then", "so", "than", "also", "about", "into", "over", "more",
    "most", "some", "any", "all", "each", "other", "such", "only", "just",
    "very", "up", "down", "out", "off", "have", "has", "had", "there", "here",
    "what", "which", "who", "when", "where", "how", "why",
}

# Too little signal below this to draw any conclusion -- a 2-word answer
# ("Yes indeed") would score near-0% or near-100% overlap almost at random.
FAQ_MIN_SIGNIFICANT_WORDS = 4
# A real paraphrase still shares most of its topic words with the surrounding
# page; this is a low bar specifically so paraphrasing is never mistaken for
# absence -- only near-total vocabulary mismatch is flagged.
FAQ_LOW_OVERLAP_THRESHOLD = 0.25
# Below this, the page itself effectively wasn't fetched/rendered -- flagging
# every FAQ pair as "not found" would blame the schema for a fetch failure.
FAQ_MIN_VISIBLE_WORDS = 20
FAQ_MAX_PAIRS_CHECKED = 50  # bound the pathological case, not the typical one


def _significant_words(text):
    words = re.findall(r"[A-Za-z']+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def extract_visible_text_rough(html_content):
    """A forgiving, regex-based visible-text extraction. Deliberately does
    NOT exclude nav/header/footer the way the render-audit's precise sentence
    parser does for content_parity -- over-including chrome text only makes
    the haystack bigger, which can only reduce a false "not found" below,
    never cause one. That is the opposite bias from what content_parity
    needs, which is why this is a separate, simpler implementation."""
    if not html_content:
        return ""
    text = re.sub(r'<(script|style|noscript)\b[^>]*>.*?</\1>', ' ', html_content,
                 flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    return html.unescape(text)


def check_faq_visible_text_match(html_content, parsed_entities):
    """For each FAQ question/answer pair already extracted from JSON-LD,
    what fraction of the answer's meaningful vocabulary also appears
    somewhere in the page's own visible text. Word-overlap rather than exact
    substring match on purpose: a real answer is often reworded slightly
    between the schema and the visible copy, which is legitimate and must
    not be flagged. Only a near-total mismatch -- suggesting the answer has
    no real counterpart on the page at all -- is reported."""
    visible_words = _significant_words(extract_visible_text_rough(html_content))
    html_provided = isinstance(html_content, str) and len(visible_words) >= FAQ_MIN_VISIBLE_WORDS

    pairs = []
    for ent in parsed_entities:
        for p in (ent.get('faq_completeness') or {}).get('pairs') or []:
            pairs.append(p)
    pairs = pairs[:FAQ_MAX_PAIRS_CHECKED]

    if not html_provided or not pairs:
        return {
            'checked': False,
            'reason': ('page text unavailable or too short to compare against' if not html_provided
                      else 'no complete FAQ question/answer pairs found'),
            'low_overlap_pairs': [],
        }

    low_overlap = []
    for p in pairs:
        answer_words = _significant_words(p.get('answer'))
        if len(answer_words) < FAQ_MIN_SIGNIFICANT_WORDS:
            continue
        overlap = len(answer_words & visible_words) / len(answer_words)
        if overlap < FAQ_LOW_OVERLAP_THRESHOLD:
            low_overlap.append({
                'question': p.get('question'),
                'answer_preview': (p.get('answer') or '')[:160],
                'word_overlap_ratio': round(overlap, 3),
            })

    return {
        'checked': True,
        'pairs_checked': len(pairs),
        'low_overlap_pairs': low_overlap,
        'low_overlap_count': len(low_overlap),
    }


# --- Authorship (E-E-A-T) ----------------------------------------------------
# Repeatedly the single most-cited concrete AI-trust signal in published GEO/
# AEO guidance: a real named byline versus a missing or CMS-default one. This
# is a narrow, high-confidence placeholder list ONLY -- genuinely generic CMS
# defaults and system accounts, never a legitimate organizational byline like
# "Staff Writer" or "Editorial Team", which real publications use deliberately
# and are not a trust problem.
GENERIC_AUTHOR_PLACEHOLDERS = {
    "admin", "administrator", "webmaster", "support", "unknown", "anonymous",
    "n/a", "na", "test", "testuser", "guest", "default", "user", "system",
}


def extract_author_names(author_field):
    """Author can be a string, a Person/Organization dict, or a list of
    either. Returns the flat list of name strings found."""
    names = []

    def add(v):
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
        elif isinstance(v, dict):
            nm = v.get('name')
            if isinstance(nm, str) and nm.strip():
                names.append(nm.strip())

    if isinstance(author_field, list):
        for a in author_field:
            add(a)
    else:
        add(author_field)
    return names


def flatten_address(address_field):
    """PostalAddress is usually a dict (streetAddress, addressLocality,
    addressRegion, postalCode, addressCountry) but a plain string is valid
    schema too. Either way, flatten to one comparable text blob."""
    if isinstance(address_field, str):
        return address_field.strip() or None
    if isinstance(address_field, dict):
        parts = [address_field.get(k) for k in
                ('streetAddress', 'addressLocality', 'addressRegion',
                 'postalCode', 'addressCountry')]
        text = ' '.join(str(p) for p in parts if isinstance(p, str) and p.strip())
        return text or None
    return None


NAP_ADDRESS_MIN_SIGNIFICANT_WORDS = 3
NAP_ADDRESS_LOW_OVERLAP_THRESHOLD = 0.30


def _extract_phone_candidates(text):
    """Plausible phone-number-shaped substrings, kept SEPARATE from each
    other. Digit-stripping the whole page into one concatenated blob would
    let an unrelated number elsewhere (a street number, a zip code) corrupt
    or accidentally complete a match; extracting each number-shaped token on
    its own avoids that entirely."""
    return [re.sub(r'\D', '', m) for m in re.findall(r'[+(]?\d[\d\-.()\s]{6,}\d', text or '')]


def _phone_matches_any(schema_digits, candidates):
    if len(schema_digits) < 7:
        return None  # too short to mean anything -- not checked, not a mismatch
    for c in candidates:
        if len(c) < 7:
            continue
        shorter, longer = sorted([schema_digits, c], key=len)
        if shorter in longer:
            return True
    return False


def check_nap_consistency(html_content, parsed_entities):
    """Does the schema's Name/Address/Phone actually match what the page's
    own visible text shows. Phone numbers are compared as individual digit
    tokens, not the whole page glued into one blob (formatting -- dashes,
    spacing, a country-code prefix -- varies too much for text matching to
    be meaningful otherwise); addresses reuse the same word-overlap approach
    as the FAQ check, tolerant of minor formatting differences, for the same
    reason a real paraphrase must never be mistaken for a mismatch."""
    visible_raw = extract_visible_text_rough(html_content)
    phone_candidates = _extract_phone_candidates(visible_raw)
    visible_words = _significant_words(visible_raw)
    html_provided = isinstance(html_content, str) and len(visible_words) >= FAQ_MIN_VISIBLE_WORDS

    if not html_provided:
        return {'checked': False, 'reason': 'page text unavailable or too short to compare against'}

    checked_any = False
    mismatches = []
    for ent in parsed_entities:
        org = ent.get('organization_completeness')
        if not org:
            continue

        phone = org.get('telephone')
        if phone:
            phone_digits = re.sub(r'\D', '', phone)
            match = _phone_matches_any(phone_digits, phone_candidates)
            if match is not None:
                checked_any = True
                if not match:
                    mismatches.append({'field': 'telephone', 'schema_value': phone})

        address = org.get('address_text')
        if address:
            addr_words = _significant_words(address)
            if len(addr_words) >= NAP_ADDRESS_MIN_SIGNIFICANT_WORDS:
                checked_any = True
                overlap = len(addr_words & visible_words) / len(addr_words)
                if overlap < NAP_ADDRESS_LOW_OVERLAP_THRESHOLD:
                    mismatches.append({'field': 'address', 'schema_value': address,
                                       'word_overlap_ratio': round(overlap, 3)})

    if not checked_any:
        return {'checked': False, 'reason': 'no LocalBusiness/Organization telephone or address to compare'}

    return {'checked': True, 'mismatches': mismatches, 'mismatch_count': len(mismatches)}


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
            # Recoveries a lenient consumer would also apply, so only a block
            # that is broken for everyone lands in parse_errors: HTML-escaped
            # JSON, then raw control characters (a literal newline) inside
            # strings, which strict json.loads rejects but browsers' JSON-LD
            # consumers tolerate.
            recovered = False
            last_error = None
            for candidate, strict in ((html.unescape(block_str), True),
                                      (block_str, False),
                                      (html.unescape(block_str), False)):
                try:
                    data = json.loads(candidate, strict=strict)
                    parsed_blocks_count += 1
                    recovered = True
                    break
                except Exception as e:
                    last_error = e
            if not recovered:
                errors.append({
                    'block_index': idx,
                    'error': f'JSON Parse Error: {str(last_error)}',
                    'snippet': block_str.strip()[:120],
                })

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
        'entity_grounding': assess_entity_grounding(parsed_entities, url),
        'description_coverage': summarize_descriptions(parsed_entities),
        'faq_visible_text_check': check_faq_visible_text_match(html_content, parsed_entities),
        'nap_consistency': check_nap_consistency(html_content, parsed_entities),
        'parse_errors': errors
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

        result = check_structured_data(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
