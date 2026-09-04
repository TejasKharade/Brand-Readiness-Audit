import sys
import json
import urllib.request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
import socket

def check_sitemap(sitemap_url, max_samples=5):
    result = {
        "exists": False,
        "valid_xml": False,
        "url_count": 0,
        "sampled_urls": [],
        "error": None
    }
    
    try:
        req = urllib.request.Request(sitemap_url, headers={'User-Agent': 'Mozilla/5.0 (sitemap-checker)'})
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read()
            
            if response.status == 200:
                result["exists"] = True
                
                try:
                    root = ET.fromstring(content)
                    result["valid_xml"] = True
                    
                    urls = []
                    # Robust XML traversal
                    for child in root:
                        if isinstance(child.tag, str) and 'url' in child.tag.lower():
                            for elem in child:
                                if isinstance(elem.tag, str) and 'loc' in elem.tag.lower():
                                    if elem.text:
                                        urls.append(elem.text.strip())
                    
                    if not urls:
                         for child in root:
                             if isinstance(child.tag, str) and 'sitemap' in child.tag.lower():
                                 for elem in child:
                                     if isinstance(elem.tag, str) and 'loc' in elem.tag.lower():
                                         if elem.text:
                                             urls.append(elem.text.strip())
                                             
                    result["url_count"] = len(urls)
                    
                    if urls:
                        step = max(1, len(urls) // 5)
                        sampled = [urls[i] for i in range(0, len(urls), step)][:max_samples]
                        
                        for u in sampled:
                            status_code = None
                            try:
                                s_req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (sitemap-checker)'})
                                with urllib.request.urlopen(s_req, timeout=5) as s_resp:
                                    status_code = s_resp.status
                            except HTTPError as e:
                                status_code = e.code
                            except URLError:
                                status_code = "error"
                            except Exception:
                                status_code = "error"
                                
                            result["sampled_urls"].append({"url": u, "status": status_code})
                            
                except (ET.ParseError, Exception) as e:
                    result["error"] = f"XML Parse Error: {str(e)}"
            else:
                result["error"] = f"HTTP {response.status}"
    except HTTPError as e:
        result["exists"] = False
        result["error"] = f"HTTP {e.code}"
    except (URLError, socket.timeout) as e:
        result["exists"] = False
        result["error"] = str(e)
    except Exception as e:
        result["exists"] = False
        result["error"] = str(e)
        
    return result

if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            print(json.dumps({"error": "Missing sitemap URL argument"}))
            sys.exit(0)
            
        sitemap_url = sys.argv[1]
        
        output = check_sitemap(sitemap_url)
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Script execution failed: {str(e)}"}))
