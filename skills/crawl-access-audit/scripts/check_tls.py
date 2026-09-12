
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import json
import socket
import ssl
import threading
import time
import urllib.parse
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# TLS certificate check for the host the audited pages are served from.
#
# An expired, hostname-mismatched, or self-signed certificate makes every
# standards-compliant HTTP client -- AI crawlers included -- refuse the
# connection, so the pages are unreachable no matter what robots.txt says.
# The dual-identity fetch surfaces this only as a generic connection error
# with no content; this script names the cause.
#
# One TLS handshake, no HTTP request. Facts only: the orchestrator decides
# severity. OpenSSL's X509 verify codes are used to classify a failure, so no
# certificate-parsing dependency is needed.
# ---------------------------------------------------------------------------

EXPIRING_SOON_DAYS = 14

# OpenSSL X509_V_ERR_* codes -> failure kind.
VERIFY_CODE_KIND = {
    9: "not_yet_valid",          # X509_V_ERR_CERT_NOT_YET_VALID
    10: "expired",               # X509_V_ERR_CERT_HAS_EXPIRED
    18: "self_signed",           # X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT
    19: "self_signed",           # X509_V_ERR_SELF_SIGNED_CERT_IN_CHAIN
    20: "untrusted_chain",       # X509_V_ERR_UNABLE_TO_GET_ISSUER_CERT_LOCALLY
    21: "untrusted_chain",       # X509_V_ERR_UNABLE_TO_VERIFY_LEAF_SIGNATURE
    23: "revoked",               # X509_V_ERR_CERT_REVOKED
    62: "hostname_mismatch",     # X509_V_ERR_HOSTNAME_MISMATCH
}


def _host_port(target):
    s = str(target or "").strip()
    if "://" not in s:
        s = "https://" + s
    p = urllib.parse.urlparse(s)
    return (p.hostname or "").lower(), (p.port or 443), p.scheme.lower()


def _issuer(cert):
    parts = []
    for rdn in cert.get("issuer", ()):
        for key, val in rdn:
            if key in ("organizationName", "commonName") and val not in parts:
                parts.append(val)
    return ", ".join(parts) or None


def check_tls(target, timeout=6.0):
    host, port, scheme = _host_port(target)
    result = {
        "host": host,
        "port": port,
        "checked": False,
        "https_reachable": None,     # TCP + TLS handshake completed (with or without trust)
        "certificate_valid": None,   # verified chain + hostname + validity window
        "failure_kind": None,        # expired | not_yet_valid | hostname_mismatch | self_signed | untrusted_chain | revoked | other
        "verify_code": None,
        "verify_message": None,
        "not_after": None,
        "days_remaining": None,
        "expiring_soon": None,
        "expiring_soon_threshold_days": EXPIRING_SOON_DAYS,
        "issuer": None,
        "tls_version": None,
        "handshake_ms": None,
        "error": None,
    }
    if not host:
        result["error"] = "No host could be parsed from the target"
        return result
    if scheme == "http":
        result["error"] = "Target is plain http://; no TLS to check"
        return result

    result["checked"] = True
    ctx = ssl.create_default_context()
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                result["handshake_ms"] = round((time.time() - t0) * 1000, 1)
                result["https_reachable"] = True
                result["certificate_valid"] = True
                result["tls_version"] = tls.version()
                result["issuer"] = _issuer(cert)
                not_after = cert.get("notAfter")
                if not_after:
                    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
                    days = (expires - datetime.now(timezone.utc)).days
                    result["not_after"] = expires.date().isoformat()
                    result["days_remaining"] = days
                    result["expiring_soon"] = days <= EXPIRING_SOON_DAYS
    except ssl.SSLCertVerificationError as e:
        # The server answered and presented a certificate; trust failed.
        result["handshake_ms"] = round((time.time() - t0) * 1000, 1)
        result["https_reachable"] = True
        result["certificate_valid"] = False
        code = getattr(e, "verify_code", None)
        result["verify_code"] = code
        result["verify_message"] = getattr(e, "verify_message", None) or str(e)
        result["failure_kind"] = VERIFY_CODE_KIND.get(code, "other")
    except ssl.SSLError as e:
        # Handshake failed before any certificate verdict (protocol/cipher mismatch).
        result["https_reachable"] = False
        result["error"] = f"TLS handshake failed: {e}"
    except (socket.timeout, TimeoutError):
        result["https_reachable"] = False
        result["error"] = f"TLS connection timed out after {timeout}s"
    except OSError as e:
        # DNS failure, connection refused, unreachable: not a certificate fact.
        result["https_reachable"] = False
        result["error"] = f"Connection failed: {e}"
    return result


def read_stdin_safe(timeout=5.0):
    if sys.stdin.isatty():
        return ""
    res = []

    def target():
        try:
            res.append(sys.stdin.read())
        except Exception:
            pass
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return res[0] if res else ""


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() in ("--help", "-h", "help"):
        print("Usage: python check_tls.py <domain_or_url>")
        sys.exit(0)
    try:
        params = {}
        if len(sys.argv) > 1:
            raw_arg = sys.argv[1].strip()
            if raw_arg.startswith("{"):
                try:
                    params = json.loads(raw_arg)
                except json.JSONDecodeError:
                    params = {"url": raw_arg}
            else:
                params = {"url": raw_arg}
        input_data = read_stdin_safe(timeout=5.0)
        if input_data.strip():
            try:
                stdin_params = json.loads(input_data)
                if isinstance(stdin_params, dict):
                    params.update(stdin_params)
            except json.JSONDecodeError:
                pass
        target = params.get("url") or params.get("domain") or ""
        try:
            timeout = max(2.0, min(10.0, float(params.get("timeout", 6.0))))
        except (TypeError, ValueError):
            timeout = 6.0
        print(json.dumps(check_tls(target, timeout=timeout), indent=2))
    except Exception as e:
        print(json.dumps({"checked": False, "certificate_valid": None, "error": f"Script execution failed: {e}"}))
