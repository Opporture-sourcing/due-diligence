"""People behind the company: names from the website, cross-checked against public search results."""

from __future__ import annotations

import asyncio

import httpx

from ..utils import web_search
from .reputation import NEGATIVE_KEYWORDS


async def people_check(client: httpx.AsyncClient, people: list[dict], company: str) -> dict:
    if not people:
        # Try to discover leadership from public search results.
        found = await web_search(client, f'"{company}" (CEO OR founder OR owner) site:linkedin.com/in', limit=5)
        discovered = [{"name": r["title"].split(" - ")[0].split(" – ")[0].strip(), "role": _role_from(r["title"]), "source": "search", "url": r["url"]}
                      for r in found if " - " in r["title"] or " – " in r["title"]]
        people = discovered[:4]
        if not people:
            return {"people": [], "identified": 0, "verified": 0, "negative_count": 0, "note": "No leadership names found on the website or in public search."}

    subset = people[:4]
    checks = await asyncio.gather(*(_check_person(client, p, company) for p in subset))
    verified = sum(1 for c in checks if c["verified"])
    negative = sum(len(c["negative_hits"]) for c in checks)
    return {"people": list(checks) + people[4:], "identified": len(people), "verified": verified, "negative_count": negative}


async def _check_person(client, person: dict, company: str) -> dict:
    name = person["name"]
    profile, negative = await asyncio.gather(
        web_search(client, f'"{name}" "{company}" (site:linkedin.com/in OR site:crunchbase.com/person OR site:bloomberg.com/profile)', limit=4),
        web_search(client, f'"{name}" "{company}" (fraud OR lawsuit OR scam OR arrested OR charged OR bankruptcy)', limit=5),
    )
    last = name.split()[-1].lower()
    profile_hits = [r for r in profile if last in (r["title"] + r["snippet"]).lower()]
    neg_hits = []
    for r in negative:
        blob = (r["title"] + " " + r["snippet"]).lower()
        kws = [k for k in NEGATIVE_KEYWORDS if k in blob]
        if kws and last in blob:
            neg_hits.append({**r, "keywords": kws})
    return {**person, "verified": bool(profile_hits), "profiles": profile_hits[:3], "negative_hits": neg_hits[:3]}


def _role_from(title: str) -> str:
    parts = [p.strip() for p in title.replace(" – ", " - ").split(" - ")]
    return parts[1] if len(parts) > 1 else "Unknown"
