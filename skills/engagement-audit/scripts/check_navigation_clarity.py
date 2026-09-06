import sys
import json
import re
import html.parser

class NavigationParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_header_nav = False
        self.has_footer_nav = False
        self.has_search = False
        self.has_breadcrumbs = False
        self.has_contact_link = False
        self.has_about_link = False
        self.nav_links_count = 0
        self.in_nav = False
        self.in_footer = False
        self.in_header = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
        class_and_id = f"{attrs_dict.get('class', '')} {attrs_dict.get('id', '')}".lower()
        role = attrs_dict.get('role', '').lower()

        if tag == "nav" or role == "navigation" or "navigation" in class_and_id or "menu" in class_and_id:
            self.has_header_nav = True
            self.in_nav = True
        elif tag == "header":
            self.in_header = True
        elif tag == "footer":
            self.has_footer_nav = True
            self.in_footer = True
        elif tag == "input":
            input_type = attrs_dict.get('type', '').lower()
            name_id = f"{attrs_dict.get('name', '')} {attrs_dict.get('id', '')} {attrs_dict.get('placeholder', '')}".lower()
            if input_type == "search" or "search" in name_id:
                self.has_search = True

        if "breadcrumb" in class_and_id or attrs_dict.get("itemtype", "").endswith("BreadcrumbList"):
            self.has_breadcrumbs = True

        if tag == "a":
            href = attrs_dict.get('href', '').lower()
            if self.in_nav or self.in_header:
                self.nav_links_count += 1
            if 'contact' in href or 'support' in href or 'help' in href:
                self.has_contact_link = True
            if 'about' in href or 'company' in href or 'team' in href:
                self.has_about_link = True

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_nav = False
        elif tag == "header":
            self.in_header = False
        elif tag == "footer":
            self.in_footer = False

def check_navigation_clarity(html_content, url):
    if not html_content:
        html_content = ""

    parser = NavigationParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    # Check for breadcrumbs in plain text if missed by parser
    if not parser.has_breadcrumbs:
        if re.search(r'\bhome\s*[\/\>\»\|]\s*[\w\s]+[\/\>\»\|]', html_content, re.IGNORECASE):
            parser.has_breadcrumbs = True

    navigation_score = 0
    if parser.has_header_nav: navigation_score += 25
    if parser.has_footer_nav: navigation_score += 25
    if parser.has_breadcrumbs: navigation_score += 20
    if parser.has_search: navigation_score += 15
    if parser.has_contact_link or parser.has_about_link: navigation_score += 15

    return {
        "url": url,
        "navigation_clarity_score": navigation_score,
        "navigation_elements": {
            "has_primary_header_nav": parser.has_header_nav,
            "has_footer_nav": parser.has_footer_nav,
            "has_breadcrumbs": parser.has_breadcrumbs,
            "has_search_bar": parser.has_search,
            "has_contact_or_support_link": parser.has_contact_link,
            "has_about_or_company_link": parser.has_about_link,
            "header_nav_link_count": parser.nav_links_count
        },
        "orientation_quality": "Excellent" if navigation_score >= 80 else ("Adequate" if navigation_score >= 50 else "Poor - High Bounce Risk")
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        html_content = params.get('html', '')
        url = params.get('url', '')

        result = check_navigation_clarity(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
