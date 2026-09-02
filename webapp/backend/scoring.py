"""Confidence scoring: weighted composite of eight signal categories, each with a traffic-light status."""

from __future__ import annotations

WEIGHTS = {
    "domain": 10,
    "address": 10,
    "corporate": 15,
    "social": 10,
    "reviews": 15,
    "people": 15,
    "negative": 15,
    "website": 10,
}


def _status(score: int) -> str:
    return "green" if score >= 70 else "yellow" if score >= 45 else "red"


def _cat(key: str, label: str, score: int, reasons: list[str]) -> dict:
    score = max(0, min(100, int(score)))
    return {"key": key, "label": label, "weight": WEIGHTS[key], "score": score, "status": _status(score), "reasons": reasons}


def score_report(site: dict, domain: dict, address: dict, corporate: dict, social: dict, reputation: dict, people: dict) -> dict:
    cats = [
        _domain(domain),
        _address(address),
        _corporate(corporate),
        _social(social),
        _reviews(reputation),
        _people(people),
        _negative(reputation, people),
        _website(site),
    ]
    total = round(sum(c["score"] * c["weight"] for c in cats) / sum(WEIGHTS.values()))
    if total >= 75:
        verdict, headline = "High Confidence", "Strong, consistent public footprint. Standard commercial checks recommended before engagement."
    elif total >= 50:
        verdict, headline = "Moderate Confidence", "Company appears real but several signals are thin or unverified. Request documentation before committing."
    else:
        verdict, headline = "Low Confidence", "Multiple red flags or missing public footprint. Proceed only with independent verification."
    red = [c["label"] for c in cats if c["status"] == "red"]
    yellow = [c["label"] for c in cats if c["status"] == "yellow"]
    return {"score": total, "verdict": verdict, "headline": headline, "categories": cats, "red_flags": red, "cautions": yellow}


def _domain(d: dict) -> dict:
    w, s = d.get("whois", {}), d.get("ssl", {})
    reasons, score = [], 50
    if w.get("ok") and w.get("age_years") is not None:
        age = w["age_years"]
        if age >= 5:
            score, msg = 100, "well established"
        elif age >= 2:
            score, msg = 75, "moderately established"
        elif age >= 1:
            score, msg = 50, "relatively new"
        else:
            score, msg = 20, "very new — common for short-lived scam sites"
        reasons.append(f"Domain registered {w['created']} ({age} years old) — {msg}.")
        if w.get("privacy_protected"):
            reasons.append("Registrant identity is hidden behind WHOIS privacy (common, but reduces transparency).")
            score -= 5
        if w.get("registrant_org"):
            reasons.append(f"Registrant organisation on record: {w['registrant_org']}.")
    else:
        reasons.append(w.get("error") or "Domain age could not be determined.")
    if s.get("ok"):
        reasons.append(f"Valid HTTPS certificate from {s.get('issuer')} (expires {s.get('valid_until')}).")
        if s.get("org_validated"):
            reasons.append("Certificate is organisation-validated (company identity verified by the CA).")
            score += 5
    else:
        reasons.append(s.get("error") or "HTTPS certificate problem.")
        score -= 20
    dns = d.get("dns", {})
    if dns.get("mx"):
        reasons.append(f"Business email configured via {dns.get('email_provider')}.")
    else:
        reasons.append("No mail (MX) records — domain cannot receive email.")
        score -= 10
    return _cat("domain", "Domain & Infrastructure", score, reasons)


def _address(a: dict) -> dict:
    v = a.get("verdict")
    score = {"commercial": 100, "unverified": 60, "unknown": 55, "virtual_office": 45, "po_box": 40, "residential": 25}.get(v, 50)
    if not a.get("found"):
        score = 35
    reasons = list(a.get("reasons", []))
    for r in a.get("results", []):
        reasons.extend(r.get("reasons", [])[:2])
    return _cat("address", "Physical Address", score, reasons[:6])


def _corporate(c: dict) -> dict:
    n = c.get("found_count", 0)
    reasons = []
    if c.get("search_unavailable"):
        return _cat("corporate", "Corporate Databases", 50, ["Public search engines were unavailable (rate-limited); database presence could not be confirmed."])
    score = {0: 20, 1: 55, 2: 75}.get(n, 100 if n >= 3 else 20)
    for s in c.get("sources", []):
        if s["found"]:
            top = s["matches"][0]
            reasons.append(f"{s['source']}: found — {top['title'][:80]}")
        elif s.get("unavailable"):
            reasons.append(f"{s['source']}: not checked ({s.get('note', 'unavailable')})")
        else:
            reasons.append(f"{s['source']}: no matching record")
    return _cat("corporate", "Corporate Databases", score, reasons)


def _social(s: dict) -> dict:
    n, reach = s.get("count", 0), s.get("reachable_count", 0)
    score = {0: 25, 1: 55, 2: 75}.get(n, 95)
    reasons = []
    if n == 0:
        reasons.append("No social media profiles linked from the website.")
    for p in s.get("profiles", []):
        status = {"reachable": "live", "login_gated": "exists (login required to view)", "not_found": "BROKEN LINK — profile does not exist", "unreachable": "unreachable"}[p["status"]]
        extra = f" · {p['followers']}" if p.get("followers") else ""
        reasons.append(f"{p['platform'].title()}: {status}{extra}")
        if p["status"] == "not_found":
            score -= 20
    if n and reach == 0:
        score -= 15
    return _cat("social", "Social Media Presence", score, reasons)


def _reviews(r: dict) -> dict:
    tp = r.get("trustpilot", {})
    reasons, score = [], 50
    if tp.get("listed"):
        rating = tp.get("rating") or 0
        score = 90 if rating >= 4 else 65 if rating >= 3 else 30
        reasons.append(f"Trustpilot: {rating}/5 from {int(tp.get('review_count') or 0)} reviews.")
    elif tp.get("listed") is False:
        reasons.append("Not listed on Trustpilot.")
    else:
        reasons.append(tp.get("note", "Trustpilot could not be checked."))
    sites = r.get("review_sites", [])
    if sites:
        reasons.append(f"Found on {len(sites)} review platform(s): " + ", ".join(sorted({_site(x['url']) for x in sites})))
        score += 10
    elif not tp.get("listed"):
        reasons.append("No third-party review presence found — unusual for an active business with customers.")
        score -= 5
    if r.get("bbb"):
        reasons.append("Better Business Bureau profile found.")
        score += 5
    if r.get("search_unavailable"):
        reasons.append("Review coverage could not be fully confirmed in this run.")
    return _cat("reviews", "Online Reviews", score, reasons)


def _people(p: dict) -> dict:
    ident, ver, neg = p.get("identified", 0), p.get("verified", 0), p.get("negative_count", 0)
    reasons = []
    if ident == 0:
        score = 35
        reasons.append(p.get("note", "No leadership names disclosed — anonymous operators are a risk signal."))
    else:
        score = 65 if ver == 0 else 85 if ver == 1 else 95
        reasons.append(f"{ident} leadership name(s) identified; {ver} independently verified via public profiles.")
        for person in p.get("people", [])[:5]:
            flag = " ✓" if person.get("verified") else ""
            reasons.append(f"{person['name']} — {person.get('role', '')}{flag}")
    if neg:
        score -= 30
        reasons.append(f"{neg} negative search result(s) associated with leadership names.")
    return _cat("people", "People Behind the Company", score, reasons)


def _negative(r: dict, p: dict) -> dict:
    n = r.get("negative_count", 0) + p.get("negative_count", 0)
    reasons = []
    if r.get("search_unavailable"):
        return _cat("negative", "Negative Feedback & News", 55, ["Search engines were unavailable; negative-news scan incomplete."])
    score = 100 if n == 0 else 60 if n <= 2 else 25
    if n == 0:
        reasons.append("No scam, fraud, lawsuit or complaint results found tied to the company or its people.")
    for h in r.get("negative_hits", [])[:5]:
        reasons.append(f"[{', '.join(h['keywords'][:3])}] {h['title'][:90]}")
    return _cat("negative", "Negative Feedback & News", score, reasons)


def _website(site: dict) -> dict:
    q = site.get("quality", {})
    if not site.get("reachable"):
        return _cat("website", "Website Quality", 0, ["Website could not be loaded."])
    score, reasons = 40, []
    checks = [
        (q.get("https"), 10, "Served over HTTPS", "Not served over HTTPS"),
        (q.get("has_contact_info"), 15, "Contact details published", "No contact details found"),
        (q.get("has_address"), 5, "Physical address published", "No physical address published"),
        (q.get("has_privacy_policy"), 10, "Privacy policy present", "No privacy policy"),
        (q.get("has_terms"), 5, "Terms of service present", "No terms page"),
        (q.get("pages_found", 0) > 2, 10, f"{q.get('pages_found')} informational pages crawled", "Very few informational pages (thin site)"),
        (q.get("word_count", 0) > 800, 5, f"{q.get('word_count')} words of content", "Very little text content"),
        (q.get("has_meta_description"), 5, "SEO metadata present", "No meta description"),
    ]
    for ok, pts, good, bad in checks:
        if ok:
            score += pts
            reasons.append(good)
        else:
            reasons.append(bad)
    if q.get("placeholder_text"):
        score -= 25
        reasons.append("Placeholder / 'coming soon' text detected")
    if q.get("generic_email_only"):
        score -= 10
        reasons.append("Only free webmail addresses (gmail/yahoo) — no corporate email")
    if q.get("copyright_year"):
        reasons.append(f"Copyright year {q['copyright_year']}")
    return _cat("website", "Website Quality", score, reasons)


def _site(url: str) -> str:
    from urllib.parse import urlparse

    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h
