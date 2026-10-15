"""Journal day page plus autosave, metadata, tags and todo APIs."""
import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .. import repo
from ..db import get_db
from ..days import logical_today, parse_day
from ..web import templates

router = APIRouter()


class SectionIn(BaseModel):
    content: str = Field(default="", max_length=200_000)


class MetaIn(BaseModel):
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)


class TagsIn(BaseModel):
    tags: str = Field(default="", max_length=2000)


class TodoIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _check_day(day_str: str):
    day = parse_day(day_str)
    if day > logical_today():
        raise HTTPException(status_code=400, detail="Can't write in the future")
    return day


@router.get("/")
def index():
    return RedirectResponse(f"/day/{logical_today()}", status_code=302)


@router.get("/day/{day_str}", response_class=HTMLResponse)
def day_page(request: Request, day_str: str, conn: sqlite3.Connection = Depends(get_db)):
    day = parse_day(day_str)
    today = logical_today()
    if day > today:
        return RedirectResponse(f"/day/{today}", status_code=302)
    entry = repo.get_entry(conn, day)
    contents = repo.entry_contents(conn, entry["id"]) if entry else {}
    tags = repo.entry_tags(conn, entry["id"]) if entry else []
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "nav": "journal",
            "day": day,
            "today": today,
            "is_today": day == today,
            "prev_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1) if day < today else None,
            "entry": entry,
            "groups": repo.section_groups(repo.sections_for_entry(conn, entry["id"] if entry else None)),
            "contents": contents,
            "tags": tags,
            "all_tags": repo.all_tags(conn),
            "todos": repo.todos_for_day(conn, day),
            "dropped": repo.todos_dropped_on(conn, day),
            "yesterday": repo.yesterday_report(conn, day),
        },
    )


@router.put("/api/day/{day_str}/section/{key}")
def save_section(day_str: str, key: str, body: SectionIn, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    section = repo.section_by_key(conn, key)
    if section is None or section["kind"] == "todos":
        raise HTTPException(status_code=404, detail="Unknown section")
    repo.save_section(conn, day, key, body.content)
    return {"ok": True}


@router.put("/api/day/{day_str}/meta")
def save_meta(day_str: str, body: MetaIn, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.set_meta(conn, day, body.mood, body.energy)
    return {"ok": True}


@router.put("/api/day/{day_str}/tags")
def save_tags(day_str: str, body: TagsIn, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    tags = repo.set_tags(conn, day, repo.parse_tags(body.tags))
    return JSONResponse({"ok": True, "tags": tags})


def _todos_partial(request: Request, conn: sqlite3.Connection, day):
    return templates.TemplateResponse(
        request, "_todos.html",
        {"day": day, "todos": repo.todos_for_day(conn, day), "dropped": repo.todos_dropped_on(conn, day)},
    )


@router.post("/api/day/{day_str}/todos", response_class=HTMLResponse)
def add_todo(request: Request, day_str: str, body: TodoIn, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.add_todo(conn, day, body.text)
    return _todos_partial(request, conn, day)


@router.post("/api/day/{day_str}/todos/{todo_id}/toggle", response_class=HTMLResponse)
def toggle_todo(request: Request, day_str: str, todo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.toggle_todo(conn, todo_id, day)
    return _todos_partial(request, conn, day)


@router.post("/api/day/{day_str}/todos/{todo_id}/drop", response_class=HTMLResponse)
def drop_todo(request: Request, day_str: str, todo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.drop_todo(conn, todo_id, day)
    return _todos_partial(request, conn, day)


@router.post("/api/day/{day_str}/todos/{todo_id}/edit", response_class=HTMLResponse)
def edit_todo(request: Request, day_str: str, todo_id: int, body: TodoIn, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.edit_todo(conn, todo_id, day, body.text)
    return _todos_partial(request, conn, day)


@router.post("/api/day/{day_str}/todos/{todo_id}/undrop", response_class=HTMLResponse)
def undrop_todo(request: Request, day_str: str, todo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    day = _check_day(day_str)
    repo.undrop_todo(conn, todo_id, day)
    return _todos_partial(request, conn, day)
