"""Questions page: the queue, answering, skipping, generating new questions and follow-ups."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import jobs, qrepo, repo
from ..days import logical_today
from ..db import get_db
from ..llm import client
from ..web import templates

router = APIRouter()

REFILL_BELOW = 3  # the model's waiting questions; below this, refill automatically (once a profile exists)


class AnswerIn(BaseModel):
    text: str = Field(default="", max_length=50_000)
    value: int | str | list[str] | None = None


class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class GenerateIn(BaseModel):
    category: str | None = None


class SettingsIn(BaseModel):
    focus: str = Field(default="", max_length=5000)
    muted: list[str] = Field(default_factory=list, max_length=30)


def _question_or_404(conn: sqlite3.Connection, qid: int) -> sqlite3.Row:
    q = qrepo.get_question(conn, qid)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return q


def _check_value(q: sqlite3.Row, value):
    """Return the structured part of an answer if it fits the question's format, else raise 400."""
    if value is None or value == "":
        return None
    kind, opts = q["kind"], qrepo.options_of(q)
    ok = (
        (kind == "scale" and isinstance(value, int) and 1 <= value <= 5)
        or (kind == "choice" and value in opts)
        or (kind == "rank" and isinstance(value, list) and sorted(value) == sorted(opts))
        or (kind == "claim_check" and value in qrepo.CLAIM_VERDICTS)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="That answer doesn't fit this question's format.")
    return value


def view_model(conn: sqlite3.Connection, q: sqlite3.Row, answer: sqlite3.Row | None = None) -> dict:
    """What the answer widget needs for one question (and optionally an existing answer to edit)."""
    return {
        "q": q,
        "opts": qrepo.options_of(q),
        "answer": answer,
        "value": qrepo.value_of(answer) if answer else None,
        "category": qrepo.CATEGORIES.get(q["category"], q["category"]),
    }


def day_card(conn: sqlite3.Connection) -> dict | None:
    """Question of the day for the journal page: the head of the queue."""
    waiting = qrepo.queue(conn, logical_today())
    if not waiting:
        return None
    return view_model(conn, waiting[0])


def _describe(q: sqlite3.Row, a: sqlite3.Row) -> str:
    return qrepo.describe_value(q["kind"], qrepo.options_of(q), qrepo.value_of(a))


@router.get("/questions", response_class=HTMLResponse)
def questions_page(request: Request, q: int | None = None, conn: sqlite3.Connection = Depends(get_db)):
    today = logical_today()
    waiting = qrepo.queue(conn, today)
    current = next((r for r in waiting if r["id"] == q), None) or (waiting[0] if waiting else None)
    position = waiting.index(current) + 1 if current else 0
    parent = qrepo.get_question(conn, current["parent_id"]) if current and current["parent_id"] else None
    return templates.TemplateResponse(
        request,
        "questions.html",
        {
            "nav": "questions",
            "current": view_model(conn, current) if current else None,
            "has_history": bool(current and current["n_answers"]),
            "parent": parent,
            "position": position,
            "waiting_count": len(waiting),
            "answered": qrepo.answered_list(conn),
            "skipped": qrepo.skipped_list(conn, today),
            "categories": qrepo.CATEGORIES,
            "focus": qrepo.focus(conn),
            "muted": qrepo.muted(conn),
            "has_profile": repo.latest_profile(conn) is not None,
            "active_job": jobs.active_job(conn),
            "today": today,
        },
    )


@router.get("/questions/{qid}", response_class=HTMLResponse)
def question_view(request: Request, qid: int, saved: int = 0, conn: sqlite3.Connection = Depends(get_db)):
    q = _question_or_404(conn, qid)
    today = logical_today()
    answers = qrepo.answers_for(conn, qid)
    in_queue = any(r["id"] == qid for r in qrepo.queue(conn, today))
    return templates.TemplateResponse(
        request,
        "question_view.html",
        {
            "nav": "questions",
            "qv": view_model(conn, q),
            "answers": [{"row": a, "structured": _describe(q, a), "vm": view_model(conn, q, a)} for a in answers],
            "in_queue": in_queue,
            "parent": qrepo.get_question(conn, q["parent_id"]) if q["parent_id"] else None,
            "followups": qrepo.followups_of(conn, qid),
            "saved": bool(saved),
            "waiting_count": len(qrepo.queue(conn, today)),
            "active_job": jobs.active_job(conn),
            "today": today,
        },
    )


@router.post("/api/questions/{qid}/answer")
def answer(qid: int, body: AnswerIn, conn: sqlite3.Connection = Depends(get_db)):
    q = _question_or_404(conn, qid)
    value = _check_value(q, body.value)
    if not body.text.strip() and value is None:
        raise HTTPException(status_code=400, detail="Write an answer (or pick an option) first.")
    answer_id = qrepo.save_answer(conn, qid, logical_today(), body.text, value)
    return {"ok": True, "answer_id": answer_id, "next": f"/questions/{qid}?saved=1"}


@router.put("/api/answers/{answer_id}")
def edit_answer(answer_id: int, body: AnswerIn, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    q = _question_or_404(conn, row["question_id"])
    value = _check_value(q, body.value)
    if not body.text.strip() and value is None:
        raise HTTPException(status_code=400, detail="An answer can't be empty.")
    qrepo.update_answer(conn, answer_id, body.text, value)
    return {"ok": True, "next": f"/questions/{q['id']}?saved=1"}


@router.post("/api/questions/{qid}/later")
def later(qid: int, conn: sqlite3.Connection = Depends(get_db)):
    _question_or_404(conn, qid)
    qrepo.mark_later(conn, qid, logical_today())
    return {"ok": True}


@router.post("/api/questions/{qid}/never")
def never(qid: int, conn: sqlite3.Connection = Depends(get_db)):
    _question_or_404(conn, qid)
    qrepo.mark_never(conn, qid)
    return {"ok": True}


@router.post("/api/questions/{qid}/bad")
def bad(qid: int, body: ReasonIn, conn: sqlite3.Connection = Depends(get_db)):
    _question_or_404(conn, qid)
    qrepo.mark_bad(conn, qid, body.reason)
    return {"ok": True}


@router.post("/api/questions/{qid}/restore")
def restore(qid: int, conn: sqlite3.Connection = Depends(get_db)):
    _question_or_404(conn, qid)
    qrepo.restore(conn, qid)
    return {"ok": True}


@router.put("/api/questions/settings")
def save_settings(body: SettingsIn, conn: sqlite3.Connection = Depends(get_db)):
    qrepo.set_setting(conn, "questions_focus", body.focus.strip())
    qrepo.set_setting(conn, "questions_muted", json.dumps([c for c in body.muted if c in qrepo.CATEGORIES]))
    return {"ok": True}


@router.get("/api/questions/waiting")
def waiting_count(conn: sqlite3.Connection = Depends(get_db)):
    return {"count": len(qrepo.queue(conn, logical_today()))}


async def _submit(conn: sqlite3.Connection, kind: str, params: dict) -> dict:
    try:
        return {"job_id": await jobs.submit(conn, kind, params)}
    except jobs.JobRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/api/questions/generate")
async def generate(body: GenerateIn | None = None, conn: sqlite3.Connection = Depends(get_db)):
    category = body.category if body and body.category in qrepo.CATEGORIES else None
    return await _submit(conn, "questions", {"category": category})


@router.post("/api/questions/{qid}/followup")
async def followup(qid: int, conn: sqlite3.Connection = Depends(get_db)):
    _question_or_404(conn, qid)
    if not qrepo.answers_for(conn, qid):
        raise HTTPException(status_code=400, detail="Answer the question first.")
    return await _submit(conn, "followup", {"question_id": qid})


@router.post("/api/questions/refill")
async def refill(conn: sqlite3.Connection = Depends(get_db)):
    """Called quietly by the journal and Questions pages. Starts a batch only when it makes sense."""
    if repo.latest_profile(conn) is None:
        return {"started": False, "reason": "no profile yet"}
    if qrepo.llm_waiting(conn, logical_today()) >= REFILL_BELOW:
        return {"started": False, "reason": "enough waiting"}
    if jobs.active_job(conn):
        return {"started": False, "reason": "busy"}
    ok, _ = await client.cached_status()
    if not ok:
        return {"started": False, "reason": "LLM offline"}
    try:
        job_id = await jobs.submit(conn, "questions", {"category": None})
    except jobs.JobRejected as exc:
        return {"started": False, "reason": exc.message}
    return {"started": True, "job_id": job_id}
