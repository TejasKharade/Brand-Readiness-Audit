import sys
import json
import re
import html.parser

OVERLAY_KEYWORDS = [
    'cookie-banner', 'cookie-consent', 'consent-modal', 'gdpr-banner',
    'newsletter-popup', 'subscribe-modal', 'email-capture', 'popup-overlay',
    'interstitial', 'paywall', 'sign-in-prompt', 'modal-dialog'
]

AD_KEYWORDS = [
    'ad-slot', 'ad-container', 'google-ads', 'banner-ad', 'sponsor-ad',
    'ad-wrapper', 'dfp-ad', 'adsbygoogle'
]

class FrictionParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.detected_overlays = []
        self.detected_ads = []
        self.fixed_elements = 0
        
    def handle_starttag(self, tag, attrs):
        try:
            attrs_dict = {k.lower(): str(v) for k, v in attrs if k and v}
            class_and_id = f"{attrs_dict.get('class', '')} {attrs_dict.get('id', '')}".lower()
            style = attrs_dict.get('style', '').lower()

            if 'position: fixed' in style or 'position:fixed' in style or 'position: sticky' in style:
                self.fixed_elements += 1

            for kw in OVERLAY_KEYWORDS:
                if kw in class_and_id or kw in style:
                    self.detected_overlays.append({"tag": tag, "keyword": kw, "selector": attrs_dict.get('id') or attrs_dict.get('class')})
                    break

            for ad in AD_KEYWORDS:
                if ad in class_and_id:
                    self.detected_ads.append({"tag": tag, "keyword": ad, "selector": attrs_dict.get('id') or attrs_dict.get('class')})
                    break
        except Exception:
            pass

def check_layout_friction(html_content, url):
    if not html_content:
        html_content = ""

    parser = FrictionParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    has_cookie_banner = any(kw in str(parser.detected_overlays).lower() for kw in ['cookie', 'gdpr', 'consent'])
    has_newsletter_popup = any(kw in str(parser.detected_overlays).lower() for kw in ['newsletter', 'subscribe', 'email'])
    has_interstitial = len(parser.detected_overlays) > 0
    has_heavy_ad_slots = len(parser.detected_ads) >= 3

    friction_level = "High" if (has_cookie_banner and has_newsletter_popup) or len(parser.detected_overlays) >= 3 else ("Medium" if has_interstitial or has_heavy_ad_slots else "Low")

    return {
        "url": url,
        "layout_friction_level": friction_level,
        "cookie_consent_banner_detected": has_cookie_banner,
        "newsletter_popup_detected": has_newsletter_popup,
        "total_overlay_elements": len(parser.detected_overlays),
        "detected_overlays": parser.detected_overlays[:5],
        "ad_slots_detected_count": len(parser.detected_ads),
        "sticky_fixed_elements_count": parser.fixed_elements,
        "friction_signals": {
            "obscured_content_risk": has_interstitial,
            "ad_clutter_risk": has_heavy_ad_slots,
            "fixed_viewport_clutter": parser.fixed_elements > 4
        }
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

        result = check_layout_friction(html_content, url)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
