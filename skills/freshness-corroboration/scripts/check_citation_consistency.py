import sys
import json
import re

AUTHORITATIVE_PLATFORMS = [
    'wikipedia.org', 'wikidata.org', 'linkedin.com', 'crunchbase.com',
    'twitter.com', 'x.com', 'github.com', 'facebook.com', 'youtube.com',
    'instagram.com', 'bloomberg.com', 'reuters.com'
]

def check_citation_consistency(onsite_facts, offsite_claims=None, same_as_urls=None):
    if not isinstance(onsite_facts, dict):
        onsite_facts = {}
    if not isinstance(offsite_claims, list):
        offsite_claims = []
    if not isinstance(same_as_urls, list):
        same_as_urls = []

    # 1. Evaluate sameAs coverage
    authoritative_sources = []
    generic_sources = []
    for url in same_as_urls:
        if not isinstance(url, str): continue
        u_lower = url.lower()
        if any(plat in u_lower for plat in AUTHORITATIVE_PLATFORMS):
            authoritative_sources.append(url)
        else:
            generic_sources.append(url)

    same_as_score = len(authoritative_sources)
    has_wikipedia_or_wikidata = any('wikipedia.org' in u.lower() or 'wikidata.org' in u.lower() for u in same_as_urls)

    # 2. Fact Contradictions & Claims Analysis
    contradictions = []
    verified_facts = []

    for claim in offsite_claims:
        if not isinstance(claim, dict): continue
        fact_key = claim.get('fact_key')
        expected_value = claim.get('expected_value')
        source = claim.get('source', 'external_reference')

        if fact_key in onsite_facts:
            actual_value = str(onsite_facts[fact_key]).strip()
            expected_str = str(expected_value).strip()

            # Compare normalized values
            norm_actual = re.sub(r'[^\w\s]', '', actual_value.lower())
            norm_expected = re.sub(r'[^\w\s]', '', expected_str.lower())

            if norm_actual == norm_expected or norm_expected in norm_actual or norm_actual in norm_expected:
                verified_facts.append({
                    "fact_key": fact_key,
                    "onsite_value": actual_value,
                    "offsite_value": expected_str,
                    "source": source
                })
            else:
                contradictions.append({
                    "fact_key": fact_key,
                    "onsite_value": actual_value,
                    "offsite_value": expected_str,
                    "source": source,
                    "conflict_type": "value_mismatch"
                })

    return {
        "entity_disambiguation": {
            "total_same_as_links": len(same_as_urls),
            "authoritative_same_as_links": authoritative_sources,
            "generic_same_as_links": generic_sources,
            "has_wikipedia_or_wikidata": has_wikipedia_or_wikidata,
            "entity_disambiguation_risk": "High" if len(authoritative_sources) == 0 else ("Medium" if not has_wikipedia_or_wikidata else "Low")
        },
        "fact_corroboration": {
            "total_claims_checked": len(offsite_claims),
            "verified_facts_count": len(verified_facts),
            "verified_facts": verified_facts,
            "contradictions_count": len(contradictions),
            "contradictions": contradictions,
            "corroboration_status": "Contradictions Found" if len(contradictions) > 0 else ("Verified" if len(verified_facts) > 0 else "Unverified/No External Benchmark")
        }
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        onsite_facts = params.get('onsite_facts', {})
        offsite_claims = params.get('offsite_claims', [])
        same_as_urls = params.get('same_as_urls', [])

        result = check_citation_consistency(onsite_facts, offsite_claims, same_as_urls)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
