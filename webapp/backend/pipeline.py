"""Investigation pipeline: URL in → progress-tracked collection → scored report out."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .modules.address import classify_addresses
from .modules.corporate import corporate_lookup
from .modules.domain_intel import domain_intel
from .modules.people import people_check
from .modules.reputation import reputation_scan
from .modules.scraper import scrape_website
from .modules.social import check_socials
from .scoring import score_report
from .utils import host_of, make_client, normalize_url, registrable_domain

STEPS = [
    ("website", "Scrape website content"),
    ("domain", "Domain age, SSL & DNS"),
    ("address", "Verify address (residential vs commercial)"),
    ("corporate", "Corporate databases (D&B, Crunchbase, OpenCorporates…)"),
    ("social", "Visit social media profiles"),
    ("reputation", "Online reviews & negative feedback"),
    ("people", "People behind the company"),
    ("score", "Compute confidence score"),
]


class Job:
    def __init__(self, url: str):
        self.url = url
        self.created = datetime.now(timezone.utc).isoformat()
        self.status = "queued"
        self.error: str | None = None
        self.steps = [{"key": k, "label": l, "status": "pending", "detail": ""} for k, l in STEPS]
        self.report: dict | None = None

    def set(self, key: str, status: str, detail: str = ""):
        for s in self.steps:
            if s["key"] == key:
                s["status"], s["detail"] = status, detail

    def to_dict(self) -> dict:
        return {"url": self.url, "status": self.status, "error": self.error, "steps": self.steps, "report": self.report, "created": self.created}


async def run_job(job: Job) -> None:
    job.status = "running"
    try:
        url = normalize_url(job.url)
        async with make_client() as client:
            job.set("website", "running")
            site = await scrape_website(client, url)
            if not site.get("reachable"):
                job.set("website", "failed", f"Site unreachable (HTTP {site.get('status')})")
                raise RuntimeError(f"Website could not be loaded (HTTP {site.get('status')}).")
            job.set("website", "done", f"{len(site['pages_crawled'])} pages · {len(site['social_links'])} social links · {len(site['people'])} names")

            host = site["host"]
            domain = registrable_domain(host)
            name = site["name"]

            async def wrap(key, coro, summary):
                job.set(key, "running")
                try:
                    res = await coro
                    job.set(key, "done", summary(res))
                    return res
                except Exception as e:  # noqa: BLE001
                    job.set(key, "failed", str(e)[:120])
                    return {}

            dom, addr, corp, soc, rep = await asyncio.gather(
                wrap("domain", domain_intel(host, domain), lambda r: f"age {r['whois'].get('age_years', '?')}y · SSL {'ok' if r['ssl'].get('ok') else 'issue'}"),
                wrap("address", classify_addresses(client, site["addresses"]), lambda r: r["verdict"]),
                wrap("corporate", corporate_lookup(client, name, domain), lambda r: f"{r['found_count']}/{r['checked_count']} databases"),
                wrap("social", check_socials(client, site["social_links"]), lambda r: f"{r['reachable_count']}/{r['count']} profiles reachable"),
                wrap("reputation", reputation_scan(client, name, domain), lambda r: f"{r['negative_count']} negative hits"),
            )
            ppl = await wrap("people", people_check(client, site["people"], name), lambda r: f"{r['identified']} identified · {r['verified']} verified")

            job.set("score", "running")
            scoring = score_report(site, dom, addr, corp, soc, rep, ppl)
            job.set("score", "done", f"{scoring['score']}/100")
            job.report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "input_url": job.url,
                "company": {"name": name, "url": site["final_url"], "domain": domain, "description": site["description"],
                            "founding_date": site.get("founding_date"), "emails": site["emails"], "phones": site["phones"],
                            "addresses": site["addresses"], "pages_crawled": site["pages_crawled"]},
                "scoring": scoring,
                "domain": dom,
                "address": addr,
                "corporate": corp,
                "social": soc,
                "reputation": rep,
                "people": ppl,
                "website_quality": site["quality"],
                "site_people_raw": site["people"],
            }
        job.status = "done"
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = str(e)
