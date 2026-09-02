"""Website scraper: company profile, contact data, addresses, social links, people, quality signals."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import httpx

from ..utils import fetch, host_of, soup_of, visible_text

SOCIAL_PATTERNS = {
    "linkedin": r"linkedin\.com/(company|in|school)/",
    "twitter": r"(twitter\.com|x\.com)/[A-Za-z0-9_]+/?$",
    "facebook": r"facebook\.com/[^/?#]+",
    "instagram": r"instagram\.com/[^/?#]+",
    "youtube": r"(youtube\.com/(channel|c|user|@)|youtu\.be)",
    "tiktok": r"tiktok\.com/@",
    "github": r"github\.com/[^/?#]+",
}
SUBPAGE_KEYWORDS = ["about", "team", "contact", "company", "leadership", "who-we-are", "our-story",
                    "management", "people", "imprint", "impressum", "legal", "founders"]
ROLE_RE = re.compile(
    r"\b(CEO|CTO|CFO|COO|CMO|CIO|Chief [A-Z][a-z]+ Officer|Co-?[Ff]ounder|Founder|President|"
    r"Vice President|VP|Managing Director|Director|Partner|Owner|Head of [A-Z][a-z]+|Chairman|"
    r"Chairwoman|Principal|General Manager|Executive)\b"
)
NAME_RE = re.compile(r"^(?:(?:Dr|Mr|Ms|Mrs)\.?\s)?(?:[A-Z][a-zA-Z'\-\.]+\s){1,3}[A-Z][a-zA-Z'\-\.]+$")
NAME_STOPWORDS = {"contact", "about", "our", "team", "learn", "more", "read", "meet", "us", "the", "privacy",
                  "terms", "join", "get", "view", "all", "board", "leadership", "management", "company", "home",
                  "services", "products", "news", "blog", "careers", "login", "sign"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\d)")
ADDRESS_RE = re.compile(
    r"\b\d{1,6}[A-Za-z]?\s+(?:[A-Z][a-zA-Z0-9'\.\-]*\s){1,5}"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Way|Court|Ct\.?|"
    r"Place|Pl\.?|Highway|Hwy\.?|Parkway|Pkwy\.?|Square|Sq\.?|Terrace|Circle|Trail|Plaza|Crescent|Cres\.?|Broadway)"
    r"\b[^|\n]{0,90}?(?:\b[A-Z]{2}\s?\d{5}(?:-\d{4})?|\b[A-Z]\d[A-Z]\s?\d[A-Z]\d|\b\d{4,6}\b|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})?"
)


async def scrape_website(client: httpx.AsyncClient, url: str) -> dict:
    home = await fetch(client, url)
    if home is None or home.status_code >= 400:
        return {"reachable": False, "status": home.status_code if home else None, "final_url": url}

    final_url = str(home.url)
    base_host = host_of(final_url)
    pages: dict[str, str] = {final_url: home.text}

    soup = soup_of(home.text)
    sub_links = _discover_subpages(soup, final_url, base_host)
    for link in sub_links[:6]:
        r = await fetch(client, link)
        if r is not None and r.status_code < 400 and "text/html" in r.headers.get("content-type", ""):
            pages[str(r.url)] = r.text

    soups = {u: soup_of(h) for u, h in pages.items()}
    texts = {u: visible_text(soup_of(h)) for u, h in pages.items()}
    all_text = " \n ".join(texts.values())

    ld = _jsonld_org(soups.values())
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    meta_desc = _meta(soup, "description") or _meta(soup, "og:description") or ""
    site_name = _meta(soup, "og:site_name") or ld.get("name") or _name_from_title(title) or base_host

    socials = _social_links(soups.values(), ld.get("sameAs", []))
    emails = sorted({e.lower() for e in EMAIL_RE.findall(all_text) if not e.lower().endswith((".png", ".jpg", ".svg", ".gif", ".webp"))})[:8]
    phones = sorted({re.sub(r"\s+", " ", p.group(0)).strip() for p in PHONE_RE.finditer(all_text) if len(re.sub(r"\D", "", p.group(0))) >= 9})[:6]
    addresses = _addresses(soups.values(), all_text, ld)
    people = _people(soups.values(), ld)

    quality = _quality(final_url, pages, soups.values(), all_text, title, meta_desc, emails, phones, addresses)

    return {
        "reachable": True,
        "status": home.status_code,
        "final_url": final_url,
        "host": base_host,
        "name": site_name.strip(),
        "title": title,
        "description": meta_desc[:400],
        "founding_date": ld.get("foundingDate"),
        "pages_crawled": list(pages.keys()),
        "emails": emails,
        "phones": phones,
        "addresses": addresses,
        "social_links": socials,
        "people": people,
        "quality": quality,
    }


# --------------------------------------------------------------------------- helpers
def _meta(soup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
    return (tag.get("content") or "").strip() if tag else ""


def _name_from_title(title: str) -> str:
    parts = re.split(r"\s[|\-–—:]\s", title)
    parts = sorted(parts, key=len)
    return parts[0].strip() if parts else title


def _discover_subpages(soup, base_url: str, base_host: str) -> list[str]:
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].split("#")[0])
        p = urlparse(href)
        if host_of(href) != base_host or not p.scheme.startswith("http"):
            continue
        low = (p.path + " " + a.get_text(" ", strip=True)).lower()
        if any(k in low for k in SUBPAGE_KEYWORDS) and href not in seen and href.rstrip("/") != base_url.rstrip("/"):
            seen.add(href)
            out.append(href)
    return out


def _jsonld_org(soups) -> dict:
    org: dict = {}
    for s in soups:
        for script in s.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            flat = []
            for it in items:
                if isinstance(it, dict):
                    flat.extend(it.get("@graph", [it]) if isinstance(it.get("@graph"), list) else [it])
            for it in flat:
                if not isinstance(it, dict):
                    continue
                t = str(it.get("@type", ""))
                if any(k in t for k in ("Organization", "LocalBusiness", "Corporation", "Store", "Company")):
                    org.setdefault("name", it.get("name"))
                    org.setdefault("foundingDate", it.get("foundingDate"))
                    same = it.get("sameAs")
                    if same:
                        org.setdefault("sameAs", []).extend(same if isinstance(same, list) else [same])
                    addr = it.get("address")
                    if addr:
                        for a in addr if isinstance(addr, list) else [addr]:
                            fmt = _format_postal(a)
                            if fmt:
                                org.setdefault("addresses", []).append(fmt)
                    founders = it.get("founder") or it.get("founders") or it.get("employee") or []
                    for f in founders if isinstance(founders, list) else [founders]:
                        if isinstance(f, dict) and f.get("name"):
                            org.setdefault("people", []).append({"name": f["name"], "role": f.get("jobTitle") or "Founder", "source": "schema.org"})
    return {k: v for k, v in org.items() if v}


def _format_postal(a) -> str:
    if isinstance(a, str):
        return a.strip()
    if not isinstance(a, dict):
        return ""
    parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion"), a.get("postalCode"), a.get("addressCountry")]
    parts = [str(p.get("name") if isinstance(p, dict) else p).strip() for p in parts if p]
    return ", ".join(parts)


def _social_links(soups, same_as: list) -> dict[str, str]:
    found: dict[str, str] = {}
    hrefs = list(same_as)
    for s in soups:
        hrefs.extend(a["href"] for a in s.find_all("a", href=True))
    for href in hrefs:
        if not isinstance(href, str):
            continue
        h = href.strip()
        for platform, pat in SOCIAL_PATTERNS.items():
            if platform in found:
                continue
            if re.search(pat, h, re.I) and not re.search(r"/(share|sharer|intent|plugins|dialog)", h, re.I):
                found[platform] = h if h.startswith("http") else "https://" + h.lstrip("/")
    return found


def _addresses(soups, all_text: str, ld: dict) -> list[str]:
    out: list[str] = list(ld.get("addresses", []))
    for s in soups:
        for tag in s.find_all("address"):
            t = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
            if 10 < len(t) < 200:
                out.append(t)
    for m in ADDRESS_RE.finditer(all_text):
        cand = m.group(0).strip(" ,.")
        if 12 < len(cand) < 180:
            out.append(cand)
    seen, uniq = set(), []
    for a in out:
        key = re.sub(r"\W+", "", a.lower())[:40]
        if key not in seen:
            seen.add(key)
            uniq.append(a)
    return uniq[:5]


def _people(soups, ld: dict) -> list[dict]:
    people: list[dict] = list(ld.get("people", []))
    for s in soups:
        for el in s.find_all(["p", "span", "div", "h3", "h4", "h5", "h6", "li", "small", "em", "strong", "a"]):
            role_text = el.get_text(" ", strip=True)
            if not (2 < len(role_text) < 70) or not ROLE_RE.search(role_text):
                continue
            name = _find_name_near(el, role_text)
            if name:
                people.append({"name": name, "role": role_text, "source": "website"})
    seen, uniq = set(), []
    for p in people:
        k = p["name"].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq[:12]


def _find_name_near(el, role_text: str) -> str | None:
    node = el
    for _ in range(3):
        node = node.parent
        if node is None:
            return None
        for cand in node.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "span", "a", "div"]):
            t = cand.get_text(" ", strip=True)
            if t == role_text or not (4 < len(t) < 45):
                continue
            if NAME_RE.match(t) and not any(w.lower().strip(".") in NAME_STOPWORDS for w in t.split()):
                return t
    return None


def _quality(url, pages, soups, all_text, title, meta_desc, emails, phones, addresses) -> dict:
    low = all_text.lower()
    hrefs_text = " ".join(a.get("href", "") + " " + a.get_text(" ", strip=True) for s in soups for a in s.find_all("a", href=True)).lower()
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", all_text, re.I)]
    return {
        "https": url.startswith("https://"),
        "pages_found": len(pages),
        "word_count": len(all_text.split()),
        "has_title": bool(title),
        "has_meta_description": bool(meta_desc),
        "has_privacy_policy": "privacy" in hrefs_text,
        "has_terms": "terms" in hrefs_text,
        "has_contact_info": bool(emails or phones or addresses),
        "has_email": bool(emails),
        "has_phone": bool(phones),
        "has_address": bool(addresses),
        "copyright_year": max(years) if years else None,
        "placeholder_text": any(k in low for k in ("lorem ipsum", "under construction", "coming soon", "sample text")),
        "generic_email_only": bool(emails) and all(e.split("@")[-1] in {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com"} for e in emails),
    }
