"""Address classification (residential vs commercial) using OpenStreetMap public data + text heuristics."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

from ..utils import fetch

COMMERCIAL_HINTS = re.compile(r"\b(Suite|Ste\.?|Floor|Fl\.?|Tower|Plaza|Building|Bldg|Unit \d+|Level \d+|Business Park|Office|Centre|Center|Mall)\b", re.I)
RESIDENTIAL_HINTS = re.compile(r"\b(Apt\.?|Apartment|Flat \d+|Basement|Residence|Home)\b", re.I)
POBOX_HINTS = re.compile(r"\b(P\.?\s?O\.?\s?Box|Post Office Box|PMB|Private Mail Bag)\b", re.I)
VIRTUAL_OFFICE_HINTS = re.compile(r"\b(Regus|WeWork|Spaces|Davinci|Opus Virtual|Alliance Virtual|Registered Agent)\b", re.I)

OSM_RESIDENTIAL = {"house", "residential", "apartments", "detached", "semidetached_house", "terrace", "bungalow", "dormitory", "flat", "flats", "houseboat", "static_caravan"}
OSM_COMMERCIAL = {"commercial", "office", "industrial", "retail", "warehouse", "shop", "company", "coworking", "business", "office_building", "supermarket", "hotel", "mall", "government", "bank", "hospital", "clinic", "school", "university", "financial"}


async def classify_addresses(client: httpx.AsyncClient, addresses: list[str]) -> dict:
    if not addresses:
        return {"found": False, "verdict": "unknown", "reasons": ["No physical address found on the website."], "results": []}
    results = []
    for addr in addresses[:3]:
        results.append(await _classify_one(client, addr))
    verdicts = [r["verdict"] for r in results]
    if "commercial" in verdicts:
        overall = "commercial"
    elif "po_box" in verdicts and "residential" not in verdicts:
        overall = "po_box"
    elif "residential" in verdicts:
        overall = "residential"
    else:
        overall = "unknown"
    reasons = [f"{r['address'][:70]} → {r['verdict']}" for r in results]
    return {"found": True, "verdict": overall, "reasons": reasons, "results": results}


async def _classify_one(client: httpx.AsyncClient, addr: str) -> dict:
    reasons: list[str] = []
    text_verdict = None
    if POBOX_HINTS.search(addr):
        text_verdict = "po_box"
        reasons.append("Address is a P.O. Box / mailbox, not a physical premises.")
    elif VIRTUAL_OFFICE_HINTS.search(addr):
        text_verdict = "virtual_office"
        reasons.append("Address text mentions a virtual-office / registered-agent provider.")
    elif COMMERCIAL_HINTS.search(addr):
        text_verdict = "commercial"
        reasons.append("Address text contains office/suite/floor designators typical of commercial premises.")
    elif RESIDENTIAL_HINTS.search(addr):
        text_verdict = "residential"
        reasons.append("Address text contains apartment/flat designators typical of residences.")

    osm = await _osm_lookup(client, addr)
    osm_verdict = None
    if osm:
        cat, typ, addr_type = osm.get("category", ""), osm.get("type", ""), osm.get("addresstype", "")
        land = " ".join([cat, typ, addr_type]).lower()
        if any(k in land.split() for k in OSM_COMMERCIAL) or cat in {"office", "shop", "amenity", "commercial"}:
            osm_verdict = "commercial"
            reasons.append(f"OpenStreetMap classifies this location as {cat}/{typ} (commercial use).")
        elif any(k in land.split() for k in OSM_RESIDENTIAL) or (cat == "building" and typ in OSM_RESIDENTIAL):
            osm_verdict = "residential"
            reasons.append(f"OpenStreetMap classifies this location as {cat}/{typ} (residential use).")
        else:
            reasons.append(f"OpenStreetMap geocoded the address ({cat}/{typ}) but building use is not tagged.")
    else:
        reasons.append("Address could not be geocoded via OpenStreetMap.")

    verdict = osm_verdict or text_verdict or ("unknown" if not osm else "unverified")
    if text_verdict == "po_box":
        verdict = "po_box"
    return {
        "address": addr,
        "verdict": verdict,
        "geocoded": bool(osm),
        "display_name": osm.get("display_name") if osm else None,
        "lat": osm.get("lat") if osm else None,
        "lon": osm.get("lon") if osm else None,
        "osm_type": f"{osm.get('category')}/{osm.get('type')}" if osm else None,
        "reasons": reasons,
    }


async def _osm_lookup(client: httpx.AsyncClient, addr: str) -> dict | None:
    q = re.sub(r"\b(Suite|Ste\.?|Unit|Floor|Fl\.?|#)\s*[\w-]+,?", "", addr, flags=re.I)
    url = f"https://nominatim.openstreetmap.org/search?q={quote_plus(q)}&format=jsonv2&addressdetails=1&limit=1"
    resp = await fetch(client, url)
    if not resp or resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    return data[0] if data else None
