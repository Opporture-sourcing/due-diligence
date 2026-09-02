"""Social media presence: visit each public profile link found on the website."""

from __future__ import annotations

import asyncio
import re

import httpx

from ..utils import fetch, soup_of

FOLLOWER_RE = re.compile(r"([\d,.]+\s?[KkMm]?)\s+(followers|Followers|subscribers|likes|Follower)")


async def check_socials(client: httpx.AsyncClient, links: dict[str, str]) -> dict:
    if not links:
        return {"profiles": [], "count": 0, "reachable_count": 0}
    profiles = await asyncio.gather(*(_check(client, p, u) for p, u in links.items()))
    return {
        "profiles": list(profiles),
        "count": len(profiles),
        "reachable_count": sum(1 for p in profiles if p["status"] in ("reachable", "login_gated")),
    }


async def _check(client, platform: str, url: str) -> dict:
    resp = await fetch(client, url)
    out = {"platform": platform, "url": url, "status": "unreachable", "http_status": None, "title": None, "followers": None}
    if resp is None:
        return out
    out["http_status"] = resp.status_code
    if resp.status_code in (999, 403, 429) or (platform in ("linkedin", "facebook", "instagram", "twitter") and resp.status_code in (200, 302) and "login" in str(resp.url).lower()):
        out["status"] = "login_gated"
        return out
    if resp.status_code == 404 or resp.status_code == 410:
        out["status"] = "not_found"
        return out
    if resp.status_code < 400:
        out["status"] = "reachable"
        soup = soup_of(resp.text)
        og = soup.find("meta", attrs={"property": "og:title"})
        out["title"] = (og.get("content") if og else (soup.title.get_text(strip=True) if soup.title else None)) or None
        desc = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
        blob = (desc.get("content") if desc else "") or ""
        m = FOLLOWER_RE.search(blob)
        if m:
            out["followers"] = m.group(0)
    return out
