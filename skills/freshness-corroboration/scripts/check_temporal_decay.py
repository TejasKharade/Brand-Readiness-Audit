import sys
import json
import re
from datetime import datetime

def check_temporal_decay(html_content, current_year=None):
    if current_year is None:
        current_year = datetime.now().year

    if not html_content:
        html_content = ""

    # 1. Copyright Year Check
    copyright_matches = re.findall(r'(?:copyright|©|\bcopr\b|\&copy\;)\s*(?:[a-zA-Z0-9\s,\.\-]*?)\b(20\d{2}|19\d{2})\b', html_content, re.IGNORECASE)
    copyright_years = [int(y) for y in copyright_matches if 1990 <= int(y) <= current_year + 1]
    
    latest_copyright_year = max(copyright_years) if copyright_years else None
    copyright_decay_years = (current_year - latest_copyright_year) if latest_copyright_year else None
    is_outdated_copyright = copyright_decay_years is not None and copyright_decay_years >= 2

    # 2. Stale Year Mentions in Prose (e.g., "In 2021, we launched...", "Upcoming in 2022")
    stale_year_patterns = []
    for past_year in range(current_year - 5, current_year - 1):
        pattern = re.compile(rf'\b(upcoming|new in|scheduled for|launching in|join us in)\s+{past_year}\b', re.IGNORECASE)
        for match in pattern.finditer(html_content):
            snippet_start = max(0, match.start() - 30)
            snippet_end = min(len(html_content), match.end() + 30)
            stale_year_patterns.append({
                "stale_year": past_year,
                "context_snippet": html_content[snippet_start:snippet_end].strip()
            })

    # 3. Deprecated/Stale Term Markers
    deprecated_terms = ['twitter.com', 'google+', 'macromedia', 'flash player', 'internet explorer']
    detected_deprecated = []
    html_lower = html_content.lower()
    for term in deprecated_terms:
        if term in html_lower:
            detected_deprecated.append(term)

    return {
        "current_year_reference": current_year,
        "copyright_analysis": {
            "copyright_years_found": sorted(list(set(copyright_years))),
            "latest_copyright_year": latest_copyright_year,
            "copyright_decay_years": copyright_decay_years,
            "is_outdated_copyright": is_outdated_copyright
        },
        "stale_future_prompts_count": len(stale_year_patterns),
        "stale_future_prompts": stale_year_patterns[:5],
        "deprecated_tech_or_branding_signals": detected_deprecated,
        "temporal_health": "Healthy" if not is_outdated_copyright and len(stale_year_patterns) == 0 and len(detected_deprecated) == 0 else "Degraded"
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        try:
            params = json.loads(raw_input) if raw_input.strip() else {}
        except json.JSONDecodeError:
            params = {}

        html_content = params.get('html', '')
        current_year = params.get('current_year')

        result = check_temporal_decay(html_content, current_year)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'Script execution failed: {str(e)}'}))
