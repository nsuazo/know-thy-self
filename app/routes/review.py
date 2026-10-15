"""Review panel: the page, starting a review job, viewing a finished review."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from datetime import timedelta

from .. import jobs, repo
from ..days import logical_today
from ..db import get_db
from ..llm.actions import split_actions
from ..llm.perspectives import BY_KEY, PERSPECTIVES
from ..web import templates

router = APIRouter()

SCOPES = [("today", "Today"), ("7d", "Last 7 days"), ("30d", "Last 30 days"), ("all", "Everything")]
SCOPE_LABELS = dict(SCOPES)


class ReviewIn(BaseModel):
    scope: str
    perspectives: list[str] = Field(default_factory=list, max_length=20)
    distill: bool = True


class ActionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    index: int | None = Field(default=None, ge=0, le=10)


def _load_actions(raw: str | None) -> list[dict]:
    """reviews.actions: JSON list of {"text", "todo_id"} (todo_id set once you add it to your list)."""
    if not raw:
        return []
    return [a if isinstance(a, dict) else {"text": a, "todo_id": None} for a in json.loads(raw)]


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
    actions = _load_actions(row["actions"])
    body = split_actions(row["content"])[0] if actions else row["content"]
    added = repo.todos_from_review(conn, review_id)
    added_by_id = {t["id"]: t for t in added}
    return templates.TemplateResponse(
        request,
        "review_view.html",
        {
            "nav": "review", "r": row, "scope_label": SCOPE_LABELS.get(row["scope"], row["scope"]),
            "names": names, "body": body, "added": added,
            "actions": [
                {"text": added_by_id[a["todo_id"]]["text"] if a["todo_id"] in added_by_id else a["text"],
                 "added": a["todo_id"] in added_by_id}
                for a in actions
            ],
            "tomorrow": logical_today() + timedelta(days=1),
        },
    )


@router.post("/api/review/{review_id}/todo")
def add_action_todo(review_id: int, body: ActionIn, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT actions FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review not found")
    actions = _load_actions(row["actions"])
    if body.index is not None and body.index < len(actions) and actions[body.index]["todo_id"]:
        raise HTTPException(status_code=409, detail="Already added.")
    day = logical_today() + timedelta(days=1)
    todo_id = repo.add_todo_from_review(conn, day, body.text, review_id)
    if todo_id is None:
        raise HTTPException(status_code=400, detail="Empty todo.")
    if body.index is not None and body.index < len(actions):
        actions[body.index]["todo_id"] = todo_id
        conn.execute("UPDATE reviews SET actions = ? WHERE id = ?", (json.dumps(actions), review_id))
    return {"ok": True, "id": todo_id, "day": str(day)}


@router.post("/api/review")
async def start_review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
    if body.scope not in SCOPE_LABELS:
        raise HTTPException(status_code=400, detail="Unknown scope.")
    wanted = set(body.perspectives)
    keys = [p.key for p in PERSPECTIVES if p.key in wanted]
    if not keys:
        raise HTTPException(status_code=400, detail="Pick at least one perspective.")
    try:
        job_id = await jobs.submit(conn, "review", {"scope": body.scope, "perspectives": keys, "distill": body.distill})
    except jobs.JobRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return {"job_id": job_id}
