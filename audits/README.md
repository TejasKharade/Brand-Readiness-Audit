# Field Research & Audit Laboratory

This directory stores empirical field audits across various industry verticals. Each audit documents real-world AI discoverability, rendering parity, structured data integrity, and on-site engagement signals without speculation or synthetic shortcuts.

## Vertical Directory Structure

```text
audits/
├── README.md                  ← Index of audits, learnings, and cross-vertical insights
├── saas/                      ← B2B SaaS, developer tools, cloud infrastructure
├── ecommerce/                 ← Retail, D2C brands, product catalogs
├── healthcare-finance/        ← YMYL (Your Money Your Life), high-trust domains
├── services-local/            ← Agencies, professional practices, localized businesses
└── media-editorial/           ← News, digital publications, content blogs
```

## Standard Company Audit Layout

Each audited company folder follows this standard structure:

```text
<vertical>/<company-slug>/
├── report.json                ← Competition schema audit report (site, audited_at, summary, findings)
├── findings.md                ← Detailed technical breakdown, latency benchmarks, raw diffs
└── raw_data/                  ← (Optional) Extracted sitemaps, JSON-LD dumps, console logs
```

## Audit Register

| Date | Company | Vertical | Pages Audited | Critical | High | Medium | Key Failure Mode Identified |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-09-06 | [Garage S3 (Deuxfleurs)](saas/garage/) | SaaS / DevTools | 84 | 0 | 3 | 1 | Zero JSON-LD, duplicate meta descriptions across 82% of docs, missing llms.txt, client-side JS redirects on /documentation/ |
| 2026-09-06 | [Docs.rs](saas/docs-rs/) | DevTools / Docs | 5 | 0 | 0 | 1 | 100% pre-rendered crate docs (Pass B parity: 100%), missing /llms.txt due to dynamic crate route regex collision |
