"""LLM status badge and job polling, shared by every page that runs LLM jobs."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .. import jobs
from ..db import get_db
from ..llm import client

router = APIRouter()


@router.get("/api/llm/status")
async def llm_status():
    ok, detail = await client.cached_status()
    return {"ok": ok, "detail": detail, "host": client.host()}


@router.get("/api/jobs/{job_id}")
def job_status(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    job = jobs.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "status": job["status"],
        "kind": job["kind"],
        "error": job["error"],
        "next": jobs.next_url(job["kind"], job["result_id"]),
        "progress_done": job["progress_done"],
        "progress_total": job["progress_total"],
        "progress_label": job["progress_label"],
    }
