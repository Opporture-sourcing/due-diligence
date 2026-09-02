"""Shared helpers: HTTP client, URL normalisation, public web search (no API keys)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(15.0), follow_redirects=True)


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    if not p.netloc:
        raise ValueError("Invalid URL")
    return f"{p.scheme}://{p.netloc}{p.path or '/'}"


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def registrable_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac", "edu"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


async def fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        return await client.get(url)
    except Exception:
        return None


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def visible_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


# --------------------------------------------------------------------------- search
_search_sem = asyncio.Semaphore(2)
SEARCH_STATUS: dict[str, bool] = {"available": True}


async def web_search(client: httpx.AsyncClient, query: str, limit: int = 6) -> list[dict]:
    """Search public result pages (DuckDuckGo HTML, Bing fallback). Returns [{title,url,snippet}]."""
    async with _search_sem:
        results = await _ddg(client, query, limit)
        if not results:
            results = await _bing(client, query, limit)
        await asyncio.sleep(0.7)
    if results:
        SEARCH_STATUS["available"] = True
    return results


async def _ddg(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await fetch(client, f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
    if not resp or resp.status_code != 200:
        return []
    soup = soup_of(resp.text)
    out = []
    for r in soup.select(".result"):
        a = r.select_one("a.result__a")
        if not a:
            continue
        href = a.get("href", "")
        if "uddg=" in href:
            href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        snip = r.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True), "url": href, "snippet": snip.get_text(" ", strip=True) if snip else ""})
        if len(out) >= limit:
            break
    return out


async def _bing(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await fetch(client, f"https://www.bing.com/search?q={quote_plus(query)}")
    if not resp or resp.status_code != 200:
        return []
    soup = soup_of(resp.text)
    out = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue
        p = li.select_one(".b_caption p") or li.select_one("p")
        out.append({"title": a.get_text(" ", strip=True), "url": a.get("href", ""), "snippet": p.get_text(" ", strip=True) if p else ""})
        if len(out) >= limit:
            break
    return out


def name_matches(name: str, text: str) -> bool:
    tokens = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 2 and t not in {"inc", "llc", "ltd", "the", "and", "corp", "company", "group"}]
    if not tokens:
        return False
    low = text.lower()
    hits = sum(1 for t in tokens if t in low)
    return hits >= max(1, (len(tokens) + 1) // 2)
