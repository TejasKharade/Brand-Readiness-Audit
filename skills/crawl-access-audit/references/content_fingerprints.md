# Content Fingerprints Reference

A reference table listing signal strings and rules used by `fetch_dual_identity.py` to match lowercased HTML content and detect access barriers. This document is the single source of truth for fingerprint definitions.

> [!WARNING]
> These lists are a starting heuristic based on common current implementations. They must be expanded after field testing. Do not treat this list as exhaustive.

| Fingerprint | Signal Strings to Match (lowercase) | Rationale & Logic |
|---|---|---|
| `cloudflare_challenge` | `"checking your browser"`, `"cf-browser-verification"`, `"cf-chl"`, `"just a moment"`, `"cf-im-under-attack"`, `"enable javascript and cookies to continue"` | Detects Cloudflare anti-bot interstitial pages blocking access via single-keyword match. |
| `captcha` | `"recaptcha"`, `"hcaptcha"`, `"g-recaptcha"`, `"verify you are human"`, `"captcha-container"`, `"i'm not a robot"` | Detects CAPTCHA challenges required to proceed via single-keyword match. |
| `generic_block` | `"access denied"`, `"403 forbidden"`, `"access forbidden"`, `"request blocked"`, `"blocked by security policy"` | Detects plain non-Cloudflare bot/access denial pages via single-keyword match. |
| `login_wall` | `"sign in"`, `"log in"`, `"password"` | Detects mandatory authentication walls. **3-Condition AND Rule:** Unlike single-keyword fingerprints (Cloudflare/CAPTCHA), `login_wall` requires `<input type="password">` AND `<form>` AND `thin_content` (visible text < 300 chars) simultaneously to prevent false positives on pages containing standard "Sign In" header links. |
| `thin_content` | *N/A (Length threshold check)* | Implemented by measuring stripped visible-text character count against `THIN_CONTENT_THRESHOLD` (Default: **300** characters). |

