"""Online reviews and negative-feedback scan from public pages and search results."""

from __future__ import annotations

import asyncio
import json
import re

import httpx

from ..utils import fetch, name_matches, soup_of, web_search

NEGATIVE_KEYWORDS = ["scam", "fraud", "complaint", "lawsuit", "sued", "class action", "warning", "ripoff", "rip-off",
                     "penalty", "fine", "bankrupt", "investigation", "indicted", "fake", "avoid", "beware", "cease and desist",
                     "not recommended", "1 star", "one star", "unpaid", "refund", "ponzi", "alert", "enforcement"]


async def reputation_scan(client: httpx.AsyncClient, name: str, domain: str) -> dict:
    tp_task = _trustpilot(client, domain)
    queries = {
        "reviews": f'"{name}" reviews',
        "complaints": f'"{name}" (scam OR fraud OR complaint OR ripoff)',
        "legal": f'"{name}" (lawsuit OR "class action" OR sued OR investigation OR fine)',
        "domain_scam": f'"{domain}" (scam OR legit OR fake OR review)',
        "bbb": f'site:bbb.org "{name}"',
    }
    tp, *search_results = await asyncio.gather(tp_task, *(web_search(client, q, limit=6) for q in queries.values()))
    searches = dict(zip(queries.keys(), search_results, strict=True))

    negative_hits, review_sites, bbb = [], [], []
    seen = set()
    for kind, results in searches.items():
        for r in results:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            blob = (r["title"] + " " + r["snippet"]).lower()
            relevant = name_matches(name, blob) or domain.lower() in blob or domain.lower() in r["url"].lower()
            if not relevant:
                continue
            hits = [k for k in NEGATIVE_KEYWORDS if k in blob]
            if kind == "bbb" or "bbb.org" in r["url"]:
                bbb.append(r)
            if hits and not any(s in r["url"] for s in (domain,)):
                negative_hits.append({**r, "keywords": hits, "query": kind})
            if any(s in r["url"] for s in ("trustpilot", "g2.com", "capterra", "glassdoor", "yelp", "sitejabber", "google.com/maps", "indeed", "bbb.org", "reviews.io", "scamadviser")):
                review_sites.append(r)

    return {
        "trustpilot": tp,
        "review_sites": review_sites[:8],
        "bbb": bbb[:3],
        "negative_hits": negative_hits[:10],
        "negative_count": len(negative_hits),
        "search_unavailable": all(not v for v in searches.values()),
        "queries": queries,
    }


async def _trustpilot(client, domain: str) -> dict:
    url = f"https://www.trustpilot.com/review/{domain}"
    resp = await fetch(client, url)
    if not resp or resp.status_code == 404:
        return {"listed": False, "url": url}
    if resp.status_code != 200:
        return {"listed": None, "url": url, "note": f"Trustpilot not accessible (HTTP {resp.status_code})"}
    soup = soup_of(resp.text)
    rating = count = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:  # noqa: BLE001
            continue
        for it in (data if isinstance(data, list) else [data]):
            if not isinstance(it, dict):
                continue
            for node in it.get("@graph", [it]):
                agg = node.get("aggregateRating") if isinstance(node, dict) else None
                if agg:
                    rating = _num(agg.get("ratingValue"))
                    count = _num(agg.get("reviewCount"))
    if rating is None:
        m = re.search(r"TrustScore\s*([\d.]+)", soup.get_text(" ", strip=True))
        rating = float(m.group(1)) if m else None
    if rating is None and count is None:
        return {"listed": False, "url": url}
    return {"listed": True, "url": url, "rating": rating, "review_count": count}


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None
