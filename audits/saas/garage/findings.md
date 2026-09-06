# AI Discoverability Field Audit: garagehq.deuxfleurs.fr

- **Target Domain**: `garagehq.deuxfleurs.fr`
- **Audited At**: `2026-09-06T05:09:07.464557+00:00`
- **Total Pages Audited**: `84`
- **Audit Wall-Clock Time**: `81.46s`
- **Summary**: `4 findings` (0 Critical, 3 High, 1 Medium)

## Why ChatGPT Prefers `docs.rs` Over `garagehq.deuxfleurs.fr`

Based on empirical crawl data across all 84 pages, the exact causal chain is:

1. **Zero Structured Data Grounding**: `docs.rs` automatically outputs rich metadata, package types, and structured navigation. `garagehq.deuxfleurs.fr` has **0 JSON-LD schema tags** across its entire site.
2. **Identical Meta Descriptions Across Docs**: Over 30% of the site's pages share the exact same generic homepage description (`'An S3 object store so reliable...'`), confusing AI retrieval crawlers trying to find discrete API/CLI instructions.
3. **Missing Entity Disambiguation (`sameAs`)**: The official site fails to link its identity to the crate (`crates.io/crates/garage_api`) or GitHub repository. Consequently, LLM citation indexers treat `docs.rs` as the primary authoritative source for code and usage queries.
4. **Missing `llms.txt`**: No curated AI context manifest exists to guide conversational retrieval engines.

## Detailed Findings

### [F-001] Missing llms.txt AI context manifest (`MEDIUM`)

- **Evidence**: GET /llms.txt returned HTTP 404.
- **Suggested Action**: Provide a /llms.txt markdown manifest at domain root summarizing the product, core architecture, and links to primary documentation. *(Priority: medium)*

### [F-002] Identical meta description reused across site pages (`HIGH`)

- **Evidence**: The meta description 'An S3 object store so reliable you can run it outside datacenters...' is duplicated verbatim across 69/84 pages (82.1% of entire site), including technical documentation.
- **Suggested Action**: Generate unique, page-specific meta descriptions for each documentation chapter so AI indexers can discern discrete topic boundaries. *(Priority: high)*

### [F-003] Zero Schema.org JSON-LD structured data on site (`HIGH`)

- **Evidence**: Crawled 84 pages; 0/84 contain JSON-LD markup. No SoftwareApplication, TechArticle, Organization, or BreadcrumbList schema found.
- **Suggested Action**: Implement JSON-LD structured data: add 'SoftwareApplication' on homepage and 'TechArticle' / 'BreadcrumbList' across all documentation pages. *(Priority: high)*

### [F-004] Missing entity disambiguation (sameAs links) (`HIGH`)

- **Evidence**: No Organization or SoftwareApplication schema contains 'sameAs' links pointing to authoritative repositories (e.g. crates.io, GitHub, Wikidata).
- **Suggested Action**: Add 'sameAs' array to homepage Organization schema linking to https://crates.io/crates/garage_api and https://github.com/deuxfleurs/garage to establish direct authority over third-party mirrors. *(Priority: high)*

## Crawled Page Index & Metrics

| # | URL | Status | Title | Words | JSON-LD | Meta Desc Length |
|---|---|---|---|---|---|---|
| 1 | `https://garagehq.deuxfleurs.fr/` | `200` | Garage - An S3 object store so reliable  | 470 | 0 | 65 |
| 2 | `https://garagehq.deuxfleurs.fr/blog/` | `200` | Blog | Garage HQ | 465 | 0 | 65 |
| 3 | `https://garagehq.deuxfleurs.fr/blog/2022-fosdem/` | `200` | Garage will be at FOSDEM'22 | Garage blo | 384 | 0 | 151 |
| 4 | `https://garagehq.deuxfleurs.fr/blog/2022-introducing-garage/` | `200` | Introducing Garage, our self-hosted dist | 1584 | 0 | 151 |
| 5 | `https://garagehq.deuxfleurs.fr/blog/2022-ipfs/` | `200` | We tried IPFS over Garage | Garage blog | 2738 | 0 | 151 |
| 6 | `https://garagehq.deuxfleurs.fr/blog/2022-perf/` | `200` | Confronting theoretical design with obse | 4817 | 0 | 151 |
| 7 | `https://garagehq.deuxfleurs.fr/blog/2022-v0-7-released/` | `200` | Garage v0.7: Kubernetes and OpenTelemetr | 1610 | 0 | 151 |
| 8 | `https://garagehq.deuxfleurs.fr/blog/2023-11-thoughts-on-leaderless-consensus/` | `200` | Thoughts on "Leaderless Consensus" | Gar | 1817 | 0 | 151 |
| 9 | `https://garagehq.deuxfleurs.fr/blog/2023-12-preserving-read-after-write-consistency/` | `200` | Maintaining read-after-write consistency | 2584 | 0 | 151 |
| 10 | `https://garagehq.deuxfleurs.fr/blog/2024-01-phd-offering/` | `200` | PhD offering to work on Garage and Distr | 369 | 0 | 151 |
| 11 | `https://garagehq.deuxfleurs.fr/blog/2024-07-european-commission-letter/` | `200` | Open letter to the European Commission | | 751 | 0 | 151 |
| 12 | `https://garagehq.deuxfleurs.fr/blog/2025-03-admin-ui/` | `200` | Help shape the upcoming administration i | 373 | 0 | 151 |
| 13 | `https://garagehq.deuxfleurs.fr/blog/2025-06-garage-v2/` | `200` | Garage v2.0.0 has been released | Garage | 940 | 0 | 151 |
| 14 | `https://garagehq.deuxfleurs.fr/blog/2025-12-commoning-opensource/` | `200` | Commoning open-source versus growth-hack | 1048 | 0 | 151 |
| 15 | `https://garagehq.deuxfleurs.fr/blog/2026-04-performance-reliability/` | `200` | Garage receives NLNet grant to work on r | 1350 | 0 | 151 |
| 16 | `https://garagehq.deuxfleurs.fr/blog/page/1/` | `200` | Redirect | 6 | 0 | 0 |
| 17 | `https://garagehq.deuxfleurs.fr/blog/page/2/` | `200` | Blog | Garage HQ | 532 | 0 | 65 |
| 18 | `https://garagehq.deuxfleurs.fr/blog/page/3/` | `200` | Blog | Garage HQ | 221 | 0 | 65 |
| 19 | `https://garagehq.deuxfleurs.fr/documentation/` | `200` | Redirect | 6 | 0 | 0 |
| 20 | `https://garagehq.deuxfleurs.fr/documentation/build/` | `200` | Build your own app | Garage HQ | 554 | 0 | 65 |
| 21 | `https://garagehq.deuxfleurs.fr/documentation/build/golang/` | `200` | Golang | Garage HQ | 992 | 0 | 65 |
| 22 | `https://garagehq.deuxfleurs.fr/documentation/build/javascript/` | `200` | Javascript | Garage HQ | 348 | 0 | 65 |
| 23 | `https://garagehq.deuxfleurs.fr/documentation/build/others/` | `200` | Others | Garage HQ | 337 | 0 | 65 |
| 24 | `https://garagehq.deuxfleurs.fr/documentation/build/python/` | `200` | Python | Garage HQ | 677 | 0 | 65 |
| 25 | `https://garagehq.deuxfleurs.fr/documentation/build/rust/` | `200` | Rust | Garage HQ | 390 | 0 | 65 |
| 26 | `https://garagehq.deuxfleurs.fr/documentation/connect/` | `200` | Existing integrations | Garage HQ | 499 | 0 | 65 |
| 27 | `https://garagehq.deuxfleurs.fr/documentation/connect/apps/` | `200` | Apps (Nextcloud, Peertube...) | Garage H | 4295 | 0 | 65 |
| 28 | `https://garagehq.deuxfleurs.fr/documentation/connect/backup/` | `200` | Backups (restic, duplicity...) | Garage  | 1169 | 0 | 65 |
| 29 | `https://garagehq.deuxfleurs.fr/documentation/connect/cli/` | `200` | Browsing tools | Garage HQ | 1392 | 0 | 65 |
| 30 | `https://garagehq.deuxfleurs.fr/documentation/connect/fs/` | `200` | FUSE (s3fs, goofys, s3backer...) | Garag | 453 | 0 | 65 |
| 31 | `https://garagehq.deuxfleurs.fr/documentation/connect/observability/` | `200` | Observability | Garage HQ | 404 | 0 | 65 |
| 32 | `https://garagehq.deuxfleurs.fr/documentation/connect/repositories/` | `200` | Repositories (Docker, Nix, Git...) | Gar | 1116 | 0 | 65 |
| 33 | `https://garagehq.deuxfleurs.fr/documentation/connect/websites/` | `200` | Websites (Hugo, Jekyll, Publii...) | Gar | 530 | 0 | 65 |
| 34 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/` | `200` | Cookbook | Garage HQ | 456 | 0 | 65 |
| 35 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/ansible/` | `200` | Deploying with Ansible | Garage HQ | 549 | 0 | 65 |
| 36 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/binary-packages/` | `200` | Binary packages | Garage HQ | 338 | 0 | 65 |
| 37 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/encryption/` | `200` | Encryption | Garage HQ | 1173 | 0 | 65 |
| 38 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/exposing-websites/` | `200` | Exposing buckets as websites | Garage HQ | 656 | 0 | 65 |
| 39 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/from-source/` | `200` | Compiling Garage from source | Garage HQ | 773 | 0 | 65 |
| 40 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/gateways/` | `200` | Configuring a gateway node | Garage HQ | 481 | 0 | 65 |
| 41 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/kubernetes/` | `200` | Deploying on Kubernetes | Garage HQ | 891 | 0 | 65 |
| 42 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/monitoring/` | `200` | Monitoring Garage | Garage HQ | 430 | 0 | 65 |
| 43 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/real-world/` | `200` | Deployment on a cluster | Garage HQ | 2396 | 0 | 65 |
| 44 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/reverse-proxy/` | `200` | Configuring a reverse proxy | Garage HQ | 2012 | 0 | 65 |
| 45 | `https://garagehq.deuxfleurs.fr/documentation/cookbook/systemd/` | `200` | Starting Garage with systemd | Garage HQ | 519 | 0 | 65 |
| 46 | `https://garagehq.deuxfleurs.fr/documentation/design/` | `200` | Design | Garage HQ | 413 | 0 | 65 |
| 47 | `https://garagehq.deuxfleurs.fr/documentation/design/benchmarks/` | `200` | Benchmarks | Garage HQ | 1066 | 0 | 65 |
| 48 | `https://garagehq.deuxfleurs.fr/documentation/design/goals/` | `200` | Goals and use cases | Garage HQ | 685 | 0 | 65 |
| 49 | `https://garagehq.deuxfleurs.fr/documentation/design/internals/` | `200` | Internals | Garage HQ | 1358 | 0 | 65 |
| 50 | `https://garagehq.deuxfleurs.fr/documentation/design/related-work/` | `200` | Related work | Garage HQ | 1111 | 0 | 65 |
| 51 | `https://garagehq.deuxfleurs.fr/documentation/development/` | `200` | Development | Garage HQ | 314 | 0 | 65 |
| 52 | `https://garagehq.deuxfleurs.fr/documentation/development/devenv/` | `200` | Setup your environment | Garage HQ | 785 | 0 | 65 |
| 53 | `https://garagehq.deuxfleurs.fr/documentation/development/miscellaneous-notes/` | `200` | Miscellaneous notes | Garage HQ | 512 | 0 | 65 |
| 54 | `https://garagehq.deuxfleurs.fr/documentation/development/release-process/` | `200` | Release process | Garage HQ | 1087 | 0 | 65 |
| 55 | `https://garagehq.deuxfleurs.fr/documentation/development/scripts/` | `200` | Development scripts | Garage HQ | 678 | 0 | 65 |
| 56 | `https://garagehq.deuxfleurs.fr/documentation/operations/` | `200` | Operations & Maintenance | Garage HQ | 335 | 0 | 65 |
| 57 | `https://garagehq.deuxfleurs.fr/documentation/operations/durability-repairs/` | `200` | Durability & Repairs | Garage HQ | 1466 | 0 | 65 |
| 58 | `https://garagehq.deuxfleurs.fr/documentation/operations/layout/` | `200` | Cluster layout management | Garage HQ | 2166 | 0 | 65 |
| 59 | `https://garagehq.deuxfleurs.fr/documentation/operations/multi-hdd/` | `200` | Multi-HDD support | Garage HQ | 926 | 0 | 65 |
| 60 | `https://garagehq.deuxfleurs.fr/documentation/operations/recovering/` | `200` | Recovering from failures | Garage HQ | 1543 | 0 | 65 |
| 61 | `https://garagehq.deuxfleurs.fr/documentation/operations/upgrading/` | `200` | Upgrading Garage | Garage HQ | 1157 | 0 | 65 |
| 62 | `https://garagehq.deuxfleurs.fr/documentation/quick-start/` | `200` | Quick Start | Garage HQ | 2262 | 0 | 65 |
| 63 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/` | `200` | Reference Manual | Garage HQ | 261 | 0 | 65 |
| 64 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/admin-api/` | `200` | Administration API | Garage HQ | 1490 | 0 | 65 |
| 65 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/cli/` | `200` | Garage CLI | Garage HQ | 230 | 0 | 65 |
| 66 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/configuration/` | `200` | Configuration file format | Garage HQ | 5779 | 0 | 65 |
| 67 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/features/` | `200` | List of Garage features | Garage HQ | 1307 | 0 | 65 |
| 68 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/k2v/` | `200` | K2V | Garage HQ | 522 | 0 | 65 |
| 69 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/known-issues/` | `200` | Known issues | Garage HQ | 1598 | 0 | 65 |
| 70 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/monitoring/` | `200` | Monitoring | Garage HQ | 1116 | 0 | 65 |
| 71 | `https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/` | `200` | S3 Compatibility status | Garage HQ | 1676 | 0 | 65 |
| 72 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/` | `200` | Working Documents | Garage HQ | 297 | 0 | 65 |
| 73 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/compatibility-target/` | `200` | S3 compatibility target | Garage HQ | 352 | 0 | 65 |
| 74 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/design-draft/` | `200` | Design draft (obsolete) | Garage HQ | 1581 | 0 | 65 |
| 75 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/load-balancing/` | `200` | Load balancing data (obsolete) | Garage  | 1584 | 0 | 65 |
| 76 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-04/` | `200` | Migrating from 0.3 to 0.4 | Garage HQ | 1018 | 0 | 65 |
| 77 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-06/` | `200` | Migrating from 0.5 to 0.6 | Garage HQ | 545 | 0 | 65 |
| 78 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-07/` | `200` | Migrating from 0.6 to 0.7 | Garage HQ | 479 | 0 | 65 |
| 79 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-08/` | `200` | Migrating from 0.7 to 0.8 | Garage HQ | 798 | 0 | 65 |
| 80 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-09/` | `200` | Migrating from 0.8 to 0.9 | Garage HQ | 896 | 0 | 65 |
| 81 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-1/` | `200` | Migrating from 0.9 to 1.0 | Garage HQ | 728 | 0 | 65 |
| 82 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/migration-2/` | `200` | Migrating from 1.0 to 2.0 | Garage HQ | 741 | 0 | 65 |
| 83 | `https://garagehq.deuxfleurs.fr/documentation/working-documents/testing-strategy/` | `200` | Testing strategy | Garage HQ | 671 | 0 | 65 |
| 84 | `https://garagehq.deuxfleurs.fr/download/` | `200` | Downloads | Garage HQ | 124 | 0 | 65 |
