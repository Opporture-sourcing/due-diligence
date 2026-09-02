"""FastAPI server: start an investigation, poll progress, serve the frontend."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import Job, run_job
from .utils import normalize_url

app = FastAPI(title="Company Due Diligence")
JOBS: dict[str, Job] = {}


class AnalyzeRequest(BaseModel):
    url: str


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    try:
        normalize_url(req.url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job_id = uuid.uuid4().hex[:12]
    job = Job(req.url.strip())
    JOBS[job_id] = job
    asyncio.create_task(run_job(job))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
