# Content Fingerprints

A reference table listing signal strings to match against lowercased HTML to detect access barriers.

**IMPORTANT:** These lists are a starting heuristic based on common current implementations. They must be expanded after Phase 1 field research. Do not treat this list as exhaustive or final. A real deployment should expand these based on specific sites encountered. They are deliberately generic/English-centric as a v1 heuristic.

| Fingerprint | Signal Strings to Match (lowercase) | Rationale |
|---|---|---|
| `cloudflare_challenge` | `"checking your browser"`, `"cf-browser-verification"`, `"cf-chl"`, `"just a moment"`, `"cf-im-under-attack"`, `"enable javascript and cookies to continue"` | Detects Cloudflare anti-bot interstitial pages blocking access. |
| `captcha` | `"recaptcha"`, `"hcaptcha"`, `"g-recaptcha"`, `"verify you are human"`, `"captcha-container"`, `"i'm not a robot"` | Detects CAPTCHA challenges required to proceed. |
| `login_wall` | `"sign in"`, `"log in"`, `"password"` | Detects pages requiring authentication. **Implementation note:** The login_wall check must combine a password-field check (`<input type="password">`) AND a form-tag check AND a thin-content check together. Keyword match alone is insufficient and will cause false positives (e.g., on a "Log In" nav link). |
| `thin_content` | *N/A (Not a string match)* | Implemented via stripped-text length against `THIN_CONTENT_THRESHOLD`. |
