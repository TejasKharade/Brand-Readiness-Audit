"""
Pure Python standard library SSL/TLS certificate validation module.
Zero external dependencies.
"""

import ssl
import socket
from datetime import datetime, timezone

def check_tls_certificate(hostname, port=443, timeout=5):
    """
    Checks SSL/TLS certificate validity, hostname match, and expiration date.
    Pure Python standard library (socket + ssl).
    """
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return {"status": "error", "error": "No certificate presented by server"}
                
                expire_str = cert.get("notAfter")
                expire_dt = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                days_left = (expire_dt - now_dt).days
                
                issuer_parts = []
                for field in cert.get("issuer", ()):
                    for k, v in field:
                        if k in ("organizationName", "commonName"):
                            issuer_parts.append(v)
                issuer = ", ".join(issuer_parts) or "Unknown Issuer"
                
                return {
                    "status": "valid",
                    "expires_at": expire_dt.strftime("%Y-%m-%d"),
                    "days_remaining": days_left,
                    "issuer": issuer,
                    "error": None
                }
    except ssl.SSLCertVerificationError as e:
        return {"status": "verification_failed", "error": str(getattr(e, "verify_message", str(e)))}
    except ssl.CertificateError as e:
        return {"status": "hostname_mismatch", "error": str(e)}
    except socket.timeout:
        return {"status": "timeout", "error": "TLS handshake timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def audit_tls(hostname, collector):
    """
    Performs the TLS audit on the target hostname and records findings to collector.
    Returns the tls_result dictionary.
    """
    tls_result = check_tls_certificate(hostname)
    status = tls_result.get("status")

    if status == "expired":
        collector.add(
            code="TLS_CERT_EXPIRED",
            title="SSL/TLS certificate has expired",
            severity="critical",
            evidence=f"TLS certificate for {hostname} expired at {tls_result.get('expires_at')}.",
            action_summary="Renew the SSL/TLS certificate immediately to restore crawler access."
        )
    elif status == "verification_failed":
        collector.add(
            code="TLS_CERT_INVALID",
            title="SSL/TLS certificate verification failed",
            severity="critical",
            evidence=f"Certificate validation failed: {tls_result.get('error')}.",
            action_summary="Install a valid SSL/TLS certificate from a recognized Certificate Authority (e.g., Let's Encrypt)."
        )
    elif status == "hostname_mismatch":
        collector.add(
            code="TLS_HOSTNAME_MISMATCH",
            title="SSL/TLS certificate hostname mismatch",
            severity="critical",
            evidence=f"Certificate subject does not match hostname '{hostname}': {tls_result.get('error')}.",
            action_summary="Reissue the certificate with the correct Subject Alternative Name (SAN) for this domain."
        )
    elif status == "valid":
        days_rem = tls_result.get("days_remaining", 999)
        if days_rem <= 14:
            collector.add(
                code="TLS_CERT_EXPIRING_SOON",
                title=f"SSL/TLS certificate expires in {days_rem} days",
                severity="medium",
                evidence=f"Certificate expires at {tls_result.get('expires_at')} ({days_rem} days remaining).",
                action_summary="Renew SSL/TLS certificate before expiration to prevent AI crawler disruption."
            )

    return tls_result
