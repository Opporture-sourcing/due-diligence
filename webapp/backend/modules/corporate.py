"""Corporate database presence via public web pages and search-engine result pages (no API keys)."""

from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import httpx

from ..utils import fetch, name_matches, soup_of, web_search

SOURCES = [
    ("Dun & Bradstreet", "dnb", 'site:dnb.com/business-directory "{name}"'),
    ("Crunchbase", "crunchbase", 'site:crunchbase.com/organization "{name}"'),
    ("LinkedIn Company Page", "linkedin", 'site:linkedin.com/company "{name}"'),
    ("ZoomInfo", "zoominfo", 'site:zoominfo.com "{name}"'),
    ("Wikipedia", "wikipedia", 'site:wikipedia.org "{name}"'),
    ("Government registries", "registry", '"{name}" (site:sec.gov OR site:companieshouse.gov.uk OR site:ic.gc.ca OR site:sos.state OR site:opencorporates.com)'),
]


async def corporate_lookup(client: httpx.AsyncClient, name: str, domain: str) -> dict:
    oc_task = _opencorporates(client, name)
    search_tasks = [_search_source(client, label, key, q.format(name=name), name, domain) for label, key, q in SOURCES]
    oc, *searches = await asyncio.gather(oc_task, *search_tasks)
    sources = [oc, *searches]
    found = [s for s in sources if s["found"]]
    return {
        "company_name_searched": name,
        "sources": sources,
        "found_count": len(found),
        "checked_count": len(sources),
        "search_unavailable": all(s.get("unavailable") for s in searches),
    }


async def _search_source(client, label, key, query, name, domain) -> dict:
    results = await web_search(client, query, limit=5)
    if not results:
        return {"source": label, "key": key, "found": False, "unavailable": True, "matches": [], "note": "Search returned no results (may be rate-limited)."}
    matches = [r for r in results if name_matches(name, r["title"] + " " + r["snippet"]) or domain.lower() in (r["snippet"] + r["url"]).lower()]
    return {"source": label, "key": key, "found": bool(matches), "unavailable": False, "matches": matches[:3]}


async def _opencorporates(client, name) -> dict:
    url = f"https://opencorporates.com/companies?q={quote_plus(name)}"
    resp = await fetch(client, url)
    if not resp or resp.status_code != 200:
        return {"source": "OpenCorporates", "key": "opencorporates", "found": False, "unavailable": True, "matches": [],
                "note": f"OpenCorporates page not accessible (HTTP {resp.status_code if resp else 'error'})", "url": url}
    soup = soup_of(resp.text)
    matches = []
    for a in soup.select("a.company_search_result")[:8]:
        title = a.get_text(" ", strip=True)
        li = a.find_parent("li")
        status = ""
        if li:
            st = li.select_one(".status, .inactive, .active")
            status = st.get_text(" ", strip=True) if st else ""
            juris = li.select_one(".jurisdiction_filter, .jurisdiction")
            if juris:
                status = (status + " " + juris.get_text(" ", strip=True)).strip()
        if name_matches(name, title):
            matches.append({"title": title, "url": "https://opencorporates.com" + a.get("href", ""), "snippet": status})
    return {"source": "OpenCorporates", "key": "opencorporates", "found": bool(matches), "unavailable": False, "matches": matches[:5], "url": url}
