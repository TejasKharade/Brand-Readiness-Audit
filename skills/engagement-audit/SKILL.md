---
name: engagement-audit
description: Audits on-site visitor engagement, orientation hierarchy, layout friction, page speed indicators, and navigation clarity for visitors referred by AI search engines.
license: MIT
---

# On-Site Engagement Audit Skill

## When to use
Use when auditing on-site user experience, orientation clarity, page speed friction, intrusive popups, and navigation structure for visitors arriving from AI assistant referrals.

## Inputs
- `html`: Page HTML string.
- `url`: Page URL string.

## Procedure & Script Execution Flow

1. **Page Speed & Resource Bloat Signals (`scripts/check_page_speed_signals.py`)**
   ```bash
   echo '{"html": "...", "url": "https://example.com"}' | python skills/engagement-audit/scripts/check_page_speed_signals.py
   ```
   - Measures HTML payload size (KB), DOM node density, script/stylesheet counts, and unoptimized image lazy loading.

2. **Layout Friction & Intrusive Overlays (`scripts/check_layout_friction.py`)**
   ```bash
   echo '{"html": "...", "url": "https://example.com"}' | python skills/engagement-audit/scripts/check_layout_friction.py
   ```
   - Scans for cookie banners, newsletter subscription popups, fixed overlays, and ad container clutter obscuring main content.

3. **Navigation Clarity & Orientation (`scripts/check_navigation_clarity.py`)**
   ```bash
   echo '{"html": "...", "url": "https://example.com"}' | python skills/engagement-audit/scripts/check_navigation_clarity.py
   ```
   - Audits primary `<nav>` headers, footer links, breadcrumbs (`BreadcrumbList`), search input presence, and contact/about links.

## Output Schema
Emits a structured JSON object containing performance friction metrics, overlay/popup friction levels, navigation clarity scores (0-100), and orientation quality ratings.
