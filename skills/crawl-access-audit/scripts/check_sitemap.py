import sys
import json
import gzip
import ssl
import urllib.request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
import socket
import urllib.parse

# Relaxed SSL context reserved strictly for retries on SSLCertVerificationError / SSLError
RELAXED_SSL_CTX = ssl.create_default_context()
RELAXED_SSL_CTX.check_hostname = False
RELAXED_SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIAccessibilityAuditor/1.0)"}


XML_SUFFIX_INDEX_THRESHOLD = 0.8


def fetch_resource(url, timeout=12):
    """Fetches a URL, auto-decompressing gzip (.xml.gz) if detected."""
    req = urllib.request.Request(url, headers=HEADERS)
    ssl_bypassed = False
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except (ssl.SSLCertVerificationError, ssl.SSLError):
        ssl_bypassed = True
        resp = urllib.request.urlopen(req, timeout=timeout, context=RELAXED_SSL_CTX)

    with resp:
        content = resp.read()
        # Detect GZIP magic bytes (1f 8b)
        if content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        return resp.status, content, ssl_bypassed


def parse_xml_elements(root):
    """
    Safely extracts page URLs and nested sitemap index URLs by stripping
    XML namespaces cleanly regardless of schema definitions.
    """
    page_urls = []
    index_urls = []

    # Map children to their parent tags to distinguish <sitemap><loc> vs <url><loc>
    parent_map = {c: p for p in root.iter() for c in p}

    for elem in root.iter():
        elem_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
        if elem_tag == "loc" and elem.text:
            url_str = elem.text.strip()
            parent = parent_map.get(elem)
            parent_tag = ""
            if parent is not None:
                parent_tag = (
                    parent.tag.split("}")[-1].lower()
                    if "}" in parent.tag
                    else parent.tag.lower()
                )

            if parent_tag == "sitemap":
                index_urls.append(url_str)
            else:
                page_urls.append(url_str)

    return page_urls, index_urls


def spot_check_url(url, timeout=5):
    """
    Spot-checks whether a URL resolves correctly.
    Uses lightweight HEAD first; falls back to GET if HEAD returns 403/405.
    """
    try:
        req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        ssl_bypassed = False
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except (ssl.SSLCertVerificationError, ssl.SSLError):
            ssl_bypassed = True
            resp = urllib.request.urlopen(req, timeout=timeout, context=RELAXED_SSL_CTX)

        with resp:
            return resp.status, ssl_bypassed
    except HTTPError as e:
        # Fall back to GET if HEAD method is disallowed by server
        if e.code in {403, 405}:
            try:
                get_req = urllib.request.Request(url, headers=HEADERS, method="GET")
                ssl_bypassed = False
                try:
                    resp = urllib.request.urlopen(get_req, timeout=timeout)
                except (ssl.SSLCertVerificationError, ssl.SSLError):
                    ssl_bypassed = True
                    resp = urllib.request.urlopen(get_req, timeout=timeout, context=RELAXED_SSL_CTX)

                with resp:
                    return resp.status, ssl_bypassed
            except HTTPError as get_e:
                return get_e.code, False
            except Exception:
                return "error", False
        return e.code, False
    except (URLError, socket.timeout):
        return "unreachable", False
    except Exception:
        return "error", False


def check_sitemap(sitemap_url, max_samples=5):
    result = {
        "exists": False,
        "valid_xml": False,
        "is_sitemap_index": False,
        "reclassified_as_index": False,
        "child_sitemaps_total": 0,
        "child_sitemaps_checked": 0,
        "child_sitemap_errors": [],
        "url_count": 0,
        "is_empty": True,
        "ssl_verification_bypassed": False,
        "sampled_urls": [],
        "error": None
    }

    try:
        status, content, ssl_bypassed = fetch_resource(sitemap_url)
        result["ssl_verification_bypassed"] = ssl_bypassed
        if status != 200:
            result["error"] = f"HTTP {status}"
            return result

        result["exists"] = True

        # Parse XML tree
        try:
            root = ET.fromstring(content)
            result["valid_xml"] = True
        except ET.ParseError as e:
            result["error"] = f"XML Parse Error: {str(e)}"
            return result

        page_urls, index_urls = parse_xml_elements(root)

        # Secondary heuristic: check if page_urls is non-empty and >= 80% end in .xml / .xml.gz
        if page_urls:
            xml_count = 0
            for u in page_urls:
                path_lower = urllib.parse.urlparse(u).path.lower()
                if path_lower.endswith(".xml") or path_lower.endswith(".xml.gz"):
                    xml_count += 1
            if (xml_count / len(page_urls)) >= XML_SUFFIX_INDEX_THRESHOLD:
                result["reclassified_as_index"] = True
                index_urls.extend(page_urls)
                page_urls = []

        # Handle Sitemap Index files (contains nested child sitemaps)
        if index_urls and not page_urls:
            result["is_sitemap_index"] = True
            result["child_sitemaps_total"] = len(index_urls)
            children_to_fetch = index_urls[:3]

            for child_url in children_to_fetch:
                try:
                    child_status, child_content, child_ssl_bypassed = fetch_resource(child_url)
                    if child_ssl_bypassed:
                        result["ssl_verification_bypassed"] = True

                    if child_status == 200:
                        child_root = ET.fromstring(child_content)
                        child_pages, _ = parse_xml_elements(child_root)
                        page_urls.extend(child_pages)
                        result["child_sitemaps_checked"] += 1
                    else:
                        result["child_sitemap_errors"].append({
                            "url": child_url,
                            "error": f"HTTP {child_status}"
                        })
                except Exception as e:
                    result["child_sitemap_errors"].append({
                        "url": child_url,
                        "error": str(e)
                    })

        result["url_count"] = len(page_urls)
        result["is_empty"] = len(page_urls) == 0

        # Spot-check 3-5 listed URLs as requested by the checklist
        if page_urls:
            step = max(1, len(page_urls) // max_samples)
            sampled = [page_urls[i] for i in range(0, len(page_urls), step)][:max_samples]

            for u in sampled:
                status_code, spot_ssl_bypassed = spot_check_url(u)
                result["sampled_urls"].append({
                    "url": u,
                    "status": status_code,
                    "ssl_verification_bypassed": spot_ssl_bypassed
                })

    except HTTPError as e:
        result["exists"] = False
        result["error"] = f"HTTP {e.code}"
    except (URLError, socket.timeout) as e:
        result["exists"] = False
        result["error"] = f"Network Error: {str(e)}"
    except Exception as e:
        result["exists"] = False
        result["error"] = f"Execution Error: {str(e)}"

    return result


if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            print(json.dumps({"error": "Missing sitemap URL argument"}))
            sys.exit(0)

        sitemap_url = sys.argv[1].strip()
        output = check_sitemap(sitemap_url)
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))