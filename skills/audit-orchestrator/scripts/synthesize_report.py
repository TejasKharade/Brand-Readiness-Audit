"""
Audit Report Schema Synthesizer & Validator
Composes sub-skill outputs into the final audit report compliant with Round 3 schema requirements.
"""

import json
from datetime import datetime

def generate_audit_report(site: str, findings: list, proactive_recommendations: list = None) -> dict:
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    
    for f in findings:
        sev = f.get("severity", "medium").lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["medium"] += 1
            
    report = {
        "site": site,
        "audited_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_findings": len(findings),
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"]
        },
        "findings": findings
    }
    
    if proactive_recommendations:
        report["proactive_recommendations"] = proactive_recommendations
        
    return report

if __name__ == "__main__":
    test_report = generate_audit_report("example.com", [
        {
            "id": "F-001",
            "title": "No JSON-LD structured data on product pages",
            "severity": "high",
            "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
            "suggested_action": {
                "summary": "Add Product/Offer JSON-LD to every product page.",
                "priority": "high"
            }
        }
    ])
    print(json.dumps(test_report, indent=2))
