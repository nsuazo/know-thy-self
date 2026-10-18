"""Profile (versioned, read-only) and the summaries browser, plus their job-starting endpoints."""
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import jobs, periods, repo
from ..days import logical_today
from ..db import get_db
from ..web import templates

router = APIRouter()

NEW_DAYS_SUGGEST_FIRST = 5   # entries with content before we suggest building the first profile
NEW_DAYS_SUGGEST_UPDATE = 7  # new days since the last profile before we suggest an update
NEW_ANSWERS_SUGGEST = 10     # or this many new answers to questions


def _profile_banner(conn: sqlite3.Connection, today: date) -> dict:
    latest = repo.latest_profile(conn)
    yesterday = today - timedelta(days=1)
    if latest:
        start = date.fromisoformat(latest["covers_through"]) + timedelta(days=1)
    else:
        start = date(2000, 1, 1)
    new_days = len(periods.content_entries(conn, start, yesterday)) if start <= yesterday else 0
    threshold = NEW_DAYS_SUGGEST_UPDATE if latest else NEW_DAYS_SUGGEST_FIRST
    after = (latest["answers_through"] or 0) if latest else 0
    new_answers = conn.execute("SELECT COUNT(*) FROM answers WHERE id > ?", (after,)).fetchone()[0]
    return {
        "new_days": new_days,
        "new_answers": new_answers,
        "suggest": new_days >= threshold or new_answers >= NEW_ANSWERS_SUGGEST,
        "first": latest is None,
    }


def _render_profile(request: Request, conn: sqlite3.Connection, row: sqlite3.Row | None, latest_id: int | None):
    today = logical_today()
    plan = periods.plan(conn, today)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "nav": "profile",
            "p": row,
            "is_latest": row is not None and row["id"] == latest_id,
            "versions": repo.profile_versions(conn),
            "banner": _profile_banner(conn, today),
            "pending_summaries": plan.total,
            "active_job": jobs.active_job(conn),
        },
    )


@router.get("/profile", response_class=HTMLResponse)
def profile_latest(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    latest = repo.latest_profile(conn)
    return _render_profile(request, conn, latest, latest["id"] if latest else None)


@router.get("/profile/{profile_id}", response_class=HTMLResponse)
def profile_version(request: Request, profile_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = repo.profile_by_id(conn, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    latest = repo.latest_profile(conn)
    return _render_profile(request, conn, row, latest["id"] if latest else None)


@router.get("/summaries", response_class=HTMLResponse)
def summaries_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    today = logical_today()
    plan = periods.plan(conn, today)
    todo_weeks = {str(m) for m in plan.weeks}
    weeks = conn.execute("SELECT * FROM summaries WHERE period = 'week' ORDER BY start_day DESC").fetchall()
    months = conn.execute("SELECT * FROM summaries WHERE period = 'month' ORDER BY start_day DESC").fetchall()
    return templates.TemplateResponse(
        request,
        "summaries.html",
        {
            "nav": "profile",
            "weeks": weeks,
            "months": months,
            "stale_weeks": todo_weeks,
            "plan": plan,
            "active_job": jobs.active_job(conn),
        },
    )


@router.post("/api/summaries/catch-up")
async def start_catch_up(conn: sqlite3.Connection = Depends(get_db)):
    if periods.plan(conn, logical_today()).total == 0:
        raise HTTPException(status_code=400, detail="All summaries are already up to date.")
    try:
        job_id = await jobs.submit(conn, "catch_up", {})
    except jobs.JobRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"job_id": job_id}


@router.post("/api/profile/update")
async def start_profile_update(conn: sqlite3.Connection = Depends(get_db)):
    try:
        job_id = await jobs.submit(conn, "profile", {})
    except jobs.JobRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"job_id": job_id}
