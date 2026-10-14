"""History list, full-text search, manual export, health check."""
import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import repo
from ..db import get_db
from ..export import export_all
from ..web import templates

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, q: str = "", conn: sqlite3.Connection = Depends(get_db)):
    q = q.strip()
    results = repo.search(conn, q) if q else None
    entries = None if q else repo.list_entries(conn)
    return templates.TemplateResponse(
        request,
        "history.html",
        {"nav": "history", "q": q, "results": results, "entries": entries},
    )


@router.post("/api/export")
def export_now(conn: sqlite3.Connection = Depends(get_db)):
    return {"ok": True, "written": export_all(conn)}


@router.get("/healthz")
def healthz(conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("SELECT 1").fetchone()
    return {"ok": True}
