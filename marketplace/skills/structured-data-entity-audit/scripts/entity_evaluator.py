#!/usr/bin/env python3
"""
Entity grounding and fact consistency diagnostic evaluators for structured-data-entity-audit.
Evaluates root entity grounding (the Garage problem), authoritative sameAs links,
atomic fact contradictions (pricing, availability, versioning), and description extractability.
Pure Python Standard Library - Zero External Dependencies.
"""

import re
from urllib.parse import urlparse

try:
    from .constants import ROOT_ENTITY_TYPES, BUZZWORD_PATTERNS
    from .parser import get_schema_types, check_sameas_authorities
except (ImportError, ValueError):
    from constants import ROOT_ENTITY_TYPES, BUZZWORD_PATTERNS
    from parser import get_schema_types, check_sameas_authorities


def evaluate_root_entity(page_url, schema_nodes, add_finding, entity_profile):
    """
    Evaluates homepage Schema.org metadata for root entity grounding and authoritative sameAs disambiguation.
    Addresses the Garage Problem where niche developer tools lack entity disambiguation in AI knowledge graphs.
    """
    if not schema_nodes:
        add_finding(
            code="ENTITY_ROOT_GROUNDING_MISSING",
            title="Homepage lacks root entity Schema.org definition (Organization or SoftwareApplication)",
            severity="HIGH",
            evidence="Zero Schema.org metadata found on homepage. AI search engines cannot establish verified brand identity or associate interior pages with an authoritative entity, risking attribution loss to third-party mirrors.",
            suggested_action="Add a <script type='application/ld+json'> declaring your Organization or SoftwareApplication, including name, url, description, and sameAs links to authoritative code and business registries.",
            url=page_url
        )
        return

    found_root_types = set()
    all_sameas = []

    for node in schema_nodes:
        types = get_schema_types(node)
        for t in types:
            if t in ROOT_ENTITY_TYPES:
                found_root_types.add(t)

        sameas = node.get("sameAs")
        if sameas:
            if isinstance(sameas, list):
                all_sameas.extend(sameas)
            elif isinstance(sameas, str):
                all_sameas.append(sameas)

    if not found_root_types:
        add_finding(
            code="ENTITY_ROOT_GROUNDING_MISSING",
            title="Homepage lacks primary Organization or SoftwareApplication entity",
            severity="MEDIUM",
            evidence=f"Homepage declared generic schema types ({', '.join([list(get_schema_types(n))[0] for n in schema_nodes if get_schema_types(n)]) or 'WebSite'}) but lacks an explicit Organization, Brand, or SoftwareApplication definition.",
            suggested_action="Nest an Organization or SoftwareApplication schema in your homepage JSON-LD to ground your brand in AI Knowledge Graphs.",
            url=page_url
        )
    else:
        entity_profile["root_entity_detected"] = True
        entity_profile["root_entity_types"] = sorted(list(found_root_types))

        # Evaluate sameAs links
        recognized = check_sameas_authorities(all_sameas)
        entity_profile["same_as_authorities"] = [r["url"] for r in recognized]

        if not all_sameas:
            # Differentiate software/tech from general brands
            is_software = any("Software" in t or "Application" in t for t in found_root_types)
            severity = "HIGH" if is_software else "MEDIUM"
            add_finding(
                code="ENTITY_SAMEAS_MISSING",
                title="Root entity lacks authoritative sameAs disambiguation links",
                severity=severity,
                evidence=f"Declared entity ({', '.join(found_root_types)}) has no 'sameAs' property pointing to verified external knowledge graphs or code/package registries.",
                suggested_action="Add 'sameAs' links pointing to your official GitHub repository, Crates.io/npm/PyPI package, LinkedIn company page, or Wikidata entry.",
                url=page_url
            )
        elif not recognized:
            add_finding(
                code="ENTITY_SAMEAS_WEAK",
                title="Declared sameAs links do not reference recognized authority registries",
                severity="LOW",
                evidence=f"Found sameAs links ({', '.join(all_sameas[:3])}) but none match recognized global entity graphs (Wikidata, Wikipedia) or authority registries (GitHub, Crates.io, npm, LinkedIn).",
                suggested_action="Include links to high-authority registries such as GitHub, Crates.io, LinkedIn, or Wikidata in your sameAs array.",
                url=page_url
            )


def evaluate_fact_consistency(page_url, schema_nodes, visible_text, add_finding):
    """Cross-examines pricing, stock availability, and version claims against on-page text."""
    if not schema_nodes or not visible_text:
        return

    for node in schema_nodes:
        # 1. Pricing Contradiction Check (Aggregated across variant offers)
        offers = node.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        schema_prices = set()
        for offer in offer_list:
            if isinstance(offer, dict) and offer.get("price") is not None:
                try:
                    p_val = float(str(offer["price"]).replace("$", "").replace(",", "").strip())
                    if p_val > 0:
                        schema_prices.add(p_val)
                except ValueError:
                    pass

        if schema_prices:
            visible_prices = re.findall(r"(?:[\$€£]\s*(\d+(?:\.\d{2})?)|(\d+(?:\.\d{2})?)\s*(?:USD|EUR|GBP))", visible_text)
            found_numbers = set()
            for p1, p2 in visible_prices:
                val = p1 or p2
                if val:
                    try:
                        found_numbers.add(float(val))
                    except ValueError:
                        pass

            if found_numbers and not any(sp in found_numbers for sp in schema_prices) and len(found_numbers) <= 3:
                sample_schema_p = sorted(list(schema_prices))[0]
                add_finding(
                    code="SCHEMA_PRICE_CONTRADICTION",
                    title=f"Structured data price (${sample_schema_p:g}) contradicts visible page pricing",
                    severity="HIGH",
                    evidence=f"JSON-LD offers.price declares {[f'${p:g}' for p in sorted(list(schema_prices))[:3]]}, but visible on-page text prominently displays {[f'${n:g}' for n in found_numbers]}.",
                    suggested_action="Synchronize the JSON-LD offers.price with the actual visible pricing displayed to users.",
                    url=page_url
                )

        # 2. Availability Contradiction Check (Aggregated across variant offers)
        offer_avails = []
        for offer in offer_list:
            if isinstance(offer, dict) and offer.get("availability") and isinstance(offer["availability"], str):
                offer_avails.append(offer["availability"].split("/")[-1].lower())

        if offer_avails:
            has_instock = any("instock" in a for a in offer_avails)
            has_outofstock = any("outofstock" in a for a in offer_avails)

            if has_instock and not has_outofstock:
                if re.search(r"\b(out of stock|sold out|currently unavailable)\b", visible_text, re.IGNORECASE):
                    add_finding(
                        code="SCHEMA_AVAILABILITY_CONTRADICTION",
                        title="Structured data claims 'InStock' but page displays 'Out of stock'",
                        severity="HIGH",
                        evidence="JSON-LD availability declares InStock across all offers, but visible page text contains 'Out of stock' or 'Sold out'.",
                        suggested_action="Update structured data availability to OutOfStock to prevent AI engines from misleading users on item availability.",
                        url=page_url
                    )
            elif has_outofstock and not has_instock:
                if re.search(r"\b(in stock|available now|ready to ship)\b", visible_text, re.IGNORECASE):
                    add_finding(
                        code="SCHEMA_AVAILABILITY_CONTRADICTION",
                        title="Structured data claims 'OutOfStock' but page displays 'In stock'",
                        severity="HIGH",
                        evidence="JSON-LD availability declares OutOfStock across all offers, but visible page text announces 'In stock' or 'Available now'.",
                        suggested_action="Synchronize structured data availability to InStock.",
                        url=page_url
                    )

        # 3. Software Version Contradiction
        version = node.get("softwareVersion") or node.get("version")
        if version and isinstance(version, str):
            ver_matches = re.findall(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", visible_text)
            if ver_matches and version not in ver_matches:
                clean_v = version.lstrip("v")
                if clean_v not in ver_matches:
                    try:
                        schema_v_tuple = tuple(int(x) for x in clean_v.split(".") if x.isdigit())
                        max_text_v = None
                        for vm in ver_matches[:5]:
                            vt = tuple(int(x) for x in vm.split(".") if x.isdigit())
                            if len(vt) >= 2 and vt > schema_v_tuple:
                                max_text_v = vm
                                break
                        if max_text_v:
                            add_finding(
                                code="SCHEMA_VERSION_STALE",
                                title=f"Structured data softwareVersion ({version}) is stale",
                                severity="MEDIUM",
                                evidence=f"JSON-LD declares softwareVersion '{version}', while visible page text features newer version '{max_text_v}'.",
                                suggested_action=f"Update JSON-LD softwareVersion property to match current release '{max_text_v}'.",
                                url=page_url
                            )
                    except Exception:
                        pass

        # 4. Temporal Anchoring (dateModified / datePublished)
        types = get_schema_types(node)
        if types.intersection({"Article", "TechArticle", "BlogPosting", "NewsArticle"}):
            date_mod = node.get("dateModified") or node.get("datePublished")
            if not date_mod:
                add_finding(
                    code="SCHEMA_DATE_MODIFIED_MISSING",
                    title=f"Article schema ({list(types)[0]}) lacks dateModified property on {urlparse(page_url).path or '/'}",
                    severity="MEDIUM",
                    evidence=f"Declared {list(types)[0]} has no 'dateModified' or 'datePublished' timestamp. Generative AI engines deprioritize undated articles for freshness-sensitive queries.",
                    suggested_action="Add an ISO-8601 'dateModified' timestamp (e.g. '2026-01-15T00:00:00Z') so AI engines can verify content freshness.",
                    url=page_url
                )


def evaluate_description_extractability(page_url, schema_nodes, add_finding):
    """Checks schema descriptions for missing content, extreme brevity, or generic buzzword fluff."""
    if not schema_nodes:
        return

    missing_desc_by_type = {}

    for node in schema_nodes:
        types = get_schema_types(node)
        matching_types = types.intersection({"Organization", "Brand", "SoftwareApplication", "Product", "Service", "WebSite"})
        if not matching_types:
            continue

        primary_type = list(matching_types)[0]
        name = node.get("name")
        desc = node.get("description")

        if desc is None or (isinstance(desc, str) and not desc.strip()):
            if primary_type not in missing_desc_by_type:
                missing_desc_by_type[primary_type] = []
            missing_desc_by_type[primary_type].append(name)
            continue

        if isinstance(desc, str):
            desc_clean = desc.strip()
            entity_label = f"{primary_type} ('{name}')" if name else primary_type
            if len(desc_clean) < 25:
                add_finding(
                    code="SCHEMA_DESCRIPTION_TOO_SHORT",
                    title=f"Schema entity description is too brief ({len(desc_clean)} chars)",
                    severity="MEDIUM",
                    evidence=f"{entity_label} description ('{desc_clean}') provides insufficient semantic context for AI vector embeddings and summarization.",
                    suggested_action="Expand description to 60-150 characters with concrete functional capabilities and domain terms.",
                    url=page_url
                )
                continue

            # Check for vacuous buzzword density
            matches = [p for p in BUZZWORD_PATTERNS if re.search(p, desc_clean, re.IGNORECASE)]
            if len(matches) >= 2:
                cleaned_matches = [m.replace(r"\b", "").replace("(?:", "").replace(")", "") for m in matches]
                buzzwords_str = ", ".join(cleaned_matches)
                add_finding(
                    code="SCHEMA_DESCRIPTION_VACUOUS",
                    title=f"Schema description for {entity_label} contains generic marketing fluff",
                    severity="MEDIUM",
                    evidence=f"Description ('{desc_clean[:100]}...') relies on generic corporate buzzwords ({buzzwords_str}) yielding zero atomic facts for AI RAG citation.",
                    suggested_action="Replace corporate buzzwords with concrete factual capabilities: specific protocols supported, architecture, target users, and key use cases.",
                    url=page_url
                )

    # Emit aggregated missing description findings per type
    for stype, names in missing_desc_by_type.items():
        named_items = [n for n in names if n]
        if len(names) == 1:
            title_item = f"{stype} ('{named_items[0]}')" if named_items else stype
            add_finding(
                code="SCHEMA_DESCRIPTION_MISSING",
                title=f"Schema entity ({title_item}) lacks description property on {urlparse(page_url).path or '/'}",
                severity="MEDIUM",
                evidence=f"The {title_item} entity has no 'description' field. AI summarizers rely on this field for atomic entity synthesis.",
                suggested_action="Provide a factual, 1-2 sentence description explaining what the entity is, who uses it, and its core capabilities.",
                url=page_url
            )
        else:
            names_summary = f" ({', '.join(named_items[:3])}...)" if named_items else ""
            add_finding(
                code="SCHEMA_DESCRIPTION_MISSING",
                title=f"{len(names)} {stype} entities lack description property on {urlparse(page_url).path or '/'}",
                severity="MEDIUM",
                evidence=f"{len(names)} instances of {stype}{names_summary} have no 'description' field. AI summarizers rely on this field for atomic entity synthesis.",
                suggested_action="Provide a factual, 1-2 sentence description for each entity explaining its capabilities and purpose.",
                url=page_url
            )
