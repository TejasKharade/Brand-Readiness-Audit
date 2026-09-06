import sys
import json
import os
import urllib.parse
from html.parser import HTMLParser

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

def load_generic_alt_values():
    ref_path = os.path.join(os.path.dirname(__file__), '../references/key_fact_patterns.json')
    try:
        if os.path.exists(ref_path):
            with open(ref_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('generic_alt_values', []))
    except Exception:
        pass
    return {'image', 'photo', 'picture', 'banner', 'logo', 'icon', 'graphic', 'img', 'placeholder', 'untitled', 'thumbnail'}

class NonTextContentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = [] # list of dicts: {src, alt, type}
        self.pdf_links = [] # list of href strings

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
        role = attrs_dict.get('role', '').lower()
        
        # 1. <img> tags
        if tag_lower == 'img':
            src = attrs_dict.get('src') or attrs_dict.get('srcset')
            alt = attrs_dict.get('alt') if 'alt' in attrs_dict else attrs_dict.get('aria-label')
            self.images.append({'src': src, 'alt': alt, 'tag': 'img'})
            
        # 2. <source> inside <picture>
        elif tag_lower == 'source':
            srcset = attrs_dict.get('srcset')
            alt = attrs_dict.get('aria-label') if 'aria-label' in attrs_dict else attrs_dict.get('alt')
            if srcset:
                self.images.append({'src': srcset, 'alt': alt, 'tag': 'source'})

        # 3. Elements with role="img" or <svg>
        elif role == 'img' or tag_lower == 'svg':
            alt = attrs_dict.get('aria-label') if 'aria-label' in attrs_dict else attrs_dict.get('alt')
            self.images.append({'src': tag_lower, 'alt': alt, 'tag': tag_lower})

        # 4. Links to PDFs
        if tag_lower == 'a':
            href = attrs_dict.get('href')
            if href:
                parsed_path = urllib.parse.urlparse(href).path.lower()
                if parsed_path.endswith('.pdf'):
                    self.pdf_links.append(href)

def inspect_pdf(pdf_url, timeout=10, max_bytes=10*1024*1024):
    if not REQUESTS_AVAILABLE:
        return {'url': pdf_url, 'error': 'requests library unavailable'}
    if not PYPDF_AVAILABLE:
        return {'url': pdf_url, 'error': 'pypdf library unavailable'}

    try:
        req_headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIAccessibilityAuditor/1.0)'}
        resp = requests.get(pdf_url, headers=req_headers, timeout=timeout, stream=True)
        status_code = resp.status_code
        
        if status_code != 200:
            return {
                'url': pdf_url,
                'http_status': status_code,
                'error': f'HTTP {status_code}'
            }
            
        content_len = resp.headers.get('Content-Length')
        if content_len and int(content_len) > max_bytes:
            return {
                'url': pdf_url,
                'http_status': status_code,
                'error': f'PDF size ({int(content_len)} bytes) exceeds 10MB limit'
            }
            
        buffer = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    return {
                        'url': pdf_url,
                        'http_status': status_code,
                        'error': 'PDF payload stream exceeded 10MB limit'
                    }
                    
        content_bytes = bytes(buffer)
        byte_size = len(content_bytes)
        
        import io
        pdf_file = io.BytesIO(content_bytes)
        reader = pypdf.PdfReader(pdf_file)
        
        page_count = len(reader.pages)
        extracted_text = []
        for p in reader.pages:
            t = p.extract_text() or ''
            extracted_text.append(t)
            
        full_text = ''.join(extracted_text)
        char_count = len(full_text.strip())
        has_text_layer = char_count > 20
        
        return {
            'url': pdf_url,
            'http_status': status_code,
            'byte_size': byte_size,
            'page_count': page_count,
            'extracted_character_count': char_count,
            'pdf_has_text_layer': has_text_layer,
            'error': None
        }
    except Exception as e:
        return {
            'url': pdf_url,
            'error': str(e)
        }

def check_nontext_facts(html_content, url, max_pdfs=3):
    generic_alt_set = load_generic_alt_values()
    parser = NonTextContentParser()
    try:
        parser.feed(html_content or '')
    except Exception:
        pass

    images_total = len(parser.images)
    missing_alt = 0
    decorative_alt = 0
    generic_alt = 0
    descriptive_alt = 0

    for img in parser.images:
        alt_val = img.get('alt')
        if alt_val is None:
            missing_alt += 1
        else:
            clean_alt = alt_val.strip().lower()
            if not clean_alt:
                decorative_alt += 1
            elif clean_alt in generic_alt_set:
                generic_alt += 1
            else:
                descriptive_alt += 1

    unique_pdf_hrefs = []
    seen = set()
    for h in parser.pdf_links:
        if h not in seen:
            seen.add(h)
            unique_pdf_hrefs.append(h)
            
    pdfs_to_process = unique_pdf_hrefs[:max_pdfs]
    pdf_results = []

    for href in pdfs_to_process:
        abs_url = urllib.parse.urljoin(url, href) if url else href
        pdf_res = inspect_pdf(abs_url)
        pdf_results.append(pdf_res)

    return {
        'images': {
            'images_total': images_total,
            'images_missing_alt': missing_alt,
            'images_decorative_alt': decorative_alt,
            'images_generic_alt': generic_alt,
            'images_with_descriptive_alt': descriptive_alt
        },
        'pdf_documents': {
            'pdf_links_found': len(unique_pdf_hrefs),
            'pdf_links_inspected': len(pdf_results),
            'details': pdf_results
        }
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

        result = check_nontext_facts(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
