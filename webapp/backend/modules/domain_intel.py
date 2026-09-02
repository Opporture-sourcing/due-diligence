"""Domain intelligence: WHOIS age, SSL certificate, DNS/MX — all from public network records."""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import datetime, timezone


async def domain_intel(host: str, domain: str) -> dict:
    whois_r, ssl_r, dns_r = await asyncio.gather(
        asyncio.to_thread(_whois, domain),
        asyncio.to_thread(_ssl, host),
        asyncio.to_thread(_dns, domain),
    )
    return {"domain": domain, "whois": whois_r, "ssl": ssl_r, "dns": dns_r}


def _first(v):
    if isinstance(v, list):
        v = v[0] if v else None
    return v


def _iso(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v) if v else None


def _whois(domain: str) -> dict:
    try:
        import whois

        w = whois.whois(domain)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"WHOIS lookup failed: {e.__class__.__name__}"}
    created = _first(w.get("creation_date"))
    expires = _first(w.get("expiration_date"))
    updated = _first(w.get("updated_date"))
    age_days = None
    if isinstance(created, datetime):
        c = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - c).days
    if not created and not w.get("registrar"):
        return {"ok": False, "error": "No WHOIS record returned (privacy-protected or unsupported TLD)"}
    return {
        "ok": True,
        "created": _iso(created),
        "expires": _iso(expires),
        "updated": _iso(updated),
        "age_days": age_days,
        "age_years": round(age_days / 365.25, 1) if age_days is not None else None,
        "registrar": w.get("registrar"),
        "registrant_org": _first(w.get("org")),
        "registrant_country": _first(w.get("country")),
        "privacy_protected": _privacy(w),
        "status": [s.split()[0] for s in (w.get("status") or [])][:5] if isinstance(w.get("status"), list) else w.get("status"),
    }


def _privacy(w) -> bool:
    blob = " ".join(str(w.get(k) or "") for k in ("org", "name", "registrant_name", "emails")).lower()
    return any(k in blob for k in ("privacy", "redacted", "proxy", "protected", "whoisguard", "withheld"))


def _ssl(host: str) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=8) as sock, ctx.wrap_socket(sock, server_hostname=host) as ss:
            cert = ss.getpeercert()
    except ssl.SSLCertVerificationError as e:
        return {"ok": False, "valid": False, "error": f"Certificate not trusted: {e.verify_message}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "valid": False, "error": f"No HTTPS: {e.__class__.__name__}"}
    issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName")
    not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return {
        "ok": True,
        "valid": not_after > datetime.now(timezone.utc),
        "issuer": issuer,
        "valid_from": not_before.date().isoformat(),
        "valid_until": not_after.date().isoformat(),
        "days_left": (not_after - datetime.now(timezone.utc)).days,
        "org_validated": bool(dict(x[0] for x in cert.get("subject", ())).get("organizationName")),
    }


def _dns(domain: str) -> dict:
    try:
        import dns.resolver
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "dnspython unavailable"}
    out: dict = {"ok": True, "a": [], "mx": [], "email_provider": None}
    try:
        out["a"] = [r.to_text() for r in dns.resolver.resolve(domain, "A", lifetime=6)]
    except Exception:  # noqa: BLE001
        pass
    try:
        out["mx"] = sorted(r.exchange.to_text().rstrip(".") for r in dns.resolver.resolve(domain, "MX", lifetime=6))
    except Exception:  # noqa: BLE001
        pass
    mx = " ".join(out["mx"]).lower()
    for key, label in (("google", "Google Workspace"), ("outlook", "Microsoft 365"), ("protection.outlook", "Microsoft 365"),
                       ("zoho", "Zoho Mail"), ("protonmail", "Proton"), ("mail.protection", "Microsoft 365"),
                       ("secureserver", "GoDaddy"), ("mimecast", "Mimecast"), ("pphosted", "Proofpoint")):
        if key in mx:
            out["email_provider"] = label
            break
    if out["mx"] and not out["email_provider"]:
        out["email_provider"] = "Custom / other"
    return out
