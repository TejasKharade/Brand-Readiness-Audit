"""
Findings accumulator and telemetry logger for AI Crawler Access Audit.
Standard library only.
"""

class FindingCollector:
    """Collects, deduplicates, and formats audit findings and crawl telemetry."""
    def __init__(self):
        self.findings = []
        self.seen_codes = set()
        self.counter = 1
        self.pages_visited = []

    def add(self, code, title, severity, evidence, action_summary, action_priority=None):
        """Adds a finding if the code has not yet been recorded."""
        if code in self.seen_codes:
            return
        self.seen_codes.add(code)
        f_id = f"ACC-{self.counter:03d}"
        self.counter += 1
        self.findings.append({
            "id": f_id,
            "code": code,
            "title": title,
            "severity": severity,
            "evidence": evidence,
            "suggested_action": {
                "summary": action_summary,
                "priority": action_priority or severity
            }
        })

    def check_redirects(self, res, label_url):
        """Checks for redirect loops and excessive redirect chains."""
        history = res.get("history", [])
        if res.get("loop_detected") or len(history) > 5:
            self.add(
                code="REDIRECT_LOOP_DETECTED",
                title=f"Redirect loop detected on {label_url}",
                severity="critical",
                evidence=f"Request to {label_url} traversed {len(history)} hops with loop detected.",
                action_summary="Fix server redirect loop configuration immediately."
            )
        elif len(history) >= 3:
            self.add(
                code="EXCESSIVE_REDIRECT_CHAIN",
                title=f"Excessive redirect chain on {label_url} ({len(history)} hops)",
                severity="low",
                evidence=f"Redirect hops: {' -> '.join([f'{c} {u}' for u, c, _ in history])}.",
                action_summary="Flatten redirect chain to at most 1 hop to conserve crawler crawl budget and reduce latency."
            )

    def log_page(self, url, depth, purpose, status, elapsed_ms, error):
        """Logs an HTTP request visit to the audit telemetry."""
        self.pages_visited.append({
            "url": url,
            "depth": depth,
            "purpose": purpose,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "error": error
        })

    def get_summary(self):
        """Calculates severity distribution counts."""
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            s = f["severity"].lower()
            if s in summary:
                summary[s] += 1
        return summary
