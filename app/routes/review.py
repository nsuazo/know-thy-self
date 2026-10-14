"""Review panel: the page, starting a review job, viewing a finished review."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import jobs
from ..db import get_db
from ..llm.perspectives import BY_KEY, PERSPECTIVES
from ..web import templates

router = APIRouter()

SCOPES = [("today", "Today"), ("7d", "Last 7 days"), ("30d", "Last 30 days"), ("all", "Everything")]
SCOPE_LABELS = dict(SCOPES)


class ReviewIn(BaseModel):
    scope: str
    perspectives: list[str] = Field(default_factory=list, max_length=20)


@router.get("/review", response_class=HTMLResponse)
def review_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT id, scope, range_start, range_end, perspectives, seconds, created_at "
        "FROM reviews ORDER BY id DESC LIMIT 100"
    ).fetchall()
    past = [
        {
            "id": r["id"],
            "scope": SCOPE_LABELS.get(r["scope"], r["scope"]),
            "start": r["range_start"],
            "end": r["range_end"],
            "count": len(json.loads(r["perspectives"])),
            "seconds": r["seconds"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "nav": "review",
            "scopes": SCOPES,
            "perspectives": PERSPECTIVES,
            "past": past,
            "active_job": jobs.active_job(conn),
        },
    )


@router.get("/review/{review_id}", response_class=HTMLResponse)
def review_view(request: Request, review_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    names = [BY_KEY[k].name for k in json.loads(row["perspectives"]) if k in BY_KEY]
    return templates.TemplateResponse(
        request,
        "review_view.html",
        {"nav": "review", "r": row, "scope_label": SCOPE_LABELS.get(row["scope"], row["scope"]), "names": names},
    )


@router.post("/api/review")
async def start_review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
    if body.scope not in SCOPE_LABELS:
        raise HTTPException(status_code=400, detail="Unknown scope.")
    wanted = set(body.perspectives)
    keys = [p.key for p in PERSPECTIVES if p.key in wanted]
    if not keys:
        raise HTTPException(status_code=400, detail="Pick at least one perspective.")
    try:
        job_id = await jobs.submit(conn, "review", {"scope": body.scope, "perspectives": keys})
    except jobs.JobRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"job_id": job_id}
