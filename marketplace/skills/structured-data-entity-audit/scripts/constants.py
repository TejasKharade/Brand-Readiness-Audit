#!/usr/bin/env python3
"""
Constants, authority registries, and entity lexicons for structured-data-entity-audit.
Pure Python Standard Library - Zero External Dependencies.
"""

USER_AGENT = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

# Authoritative Entity Graph domains whitelist
AUTHORITY_REGISTRY = [
    "wikidata.org",
    "wikipedia.org",
    "github.com",
    "gitlab.com",
    "crates.io",
    "npmjs.com",
    "pypi.org",
    "docker.com",
    "pkg.go.dev",
    "linkedin.com",
    "crunchbase.com",
    "opencorporates.com",
    "x.com",
    "twitter.com"
]

ROOT_ENTITY_TYPES = {
    "Organization",
    "Corporation",
    "LocalBusiness",
    "OnlineBusiness",
    "Brand",
    "SoftwareApplication",
    "WebApplication",
    "MobileApplication",
    "NGO"
}

BUZZWORD_PATTERNS = [
    r"leading provider of\b",
    r"innovative (?:solutions|products|technology)\b",
    r"cutting-edge\b",
    r"all-in-one (?:platform|solution)\b",
    r"world-class\b",
    r"seamless (?:end-to-end|integration)\b",
    r"next-generation\b",
    r"empowering businesses\b",
    r"game-changing\b",
    r"transform(?:ing)? your workflow\b",
    r"scalable synergy\b"
]
