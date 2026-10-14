"""Background LLM jobs. Status lives in the llm_jobs table; the UI polls it."""
import asyncio
import json
import logging
import sqlite3

from .config import settings
from .days import utc_now_iso
from .db import connect
from .llm import client
from .llm.client import LLMError
from .llm.context import build_review_context

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def create_job(conn: sqlite3.Connection, kind: str, params: dict) -> int:
    cur = conn.execute(
        "INSERT INTO llm_jobs (kind, status, params, created_at) VALUES (?, 'queued', ?, ?)",
        (kind, json.dumps(params), utc_now_iso()),
    )
    return cur.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM llm_jobs WHERE id = ?", (job_id,)).fetchone()


def active_job(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM llm_jobs WHERE status IN ('queued', 'running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def fail_stale_jobs(conn: sqlite3.Connection) -> None:
    """Called at startup: anything still queued/running was killed by a restart."""
    conn.execute(
        "UPDATE llm_jobs SET status = 'error', error = 'Interrupted by an app restart.', finished_at = ? "
        "WHERE status IN ('queued', 'running')",
        (utc_now_iso(),),
    )


def start(job_id: int) -> None:
    task = asyncio.create_task(_run(job_id))
    _tasks.add(task)  # keep a reference so it isn't garbage-collected mid-run
    task.add_done_callback(_tasks.discard)


def _finish(conn: sqlite3.Connection, job_id: int, *, result_id: int | None = None, error: str | None = None) -> None:
    conn.execute(
        "UPDATE llm_jobs SET status = ?, error = ?, result_id = ?, finished_at = ? WHERE id = ?",
        ("error" if error else "done", error, result_id, utc_now_iso(), job_id),
    )


async def _run(job_id: int) -> None:
    conn = connect()
    try:
        job = get_job(conn, job_id)
        if job is None:
            return
        params = json.loads(job["params"])
        conn.execute("UPDATE llm_jobs SET status = 'running', started_at = ? WHERE id = ?", (utc_now_iso(), job_id))
        try:
            if job["kind"] == "review":
                result_id = await _do_review(conn, params)
            else:
                raise LLMError(f"Unknown job kind: {job['kind']}")
        except LLMError as exc:
            _finish(conn, job_id, error=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the UI
            log.exception("Job %s failed", job_id)
            _finish(conn, job_id, error=f"Unexpected error: {type(exc).__name__}: {exc}")
            return
        _finish(conn, job_id, result_id=result_id)
    finally:
        conn.close()


async def _do_review(conn: sqlite3.Connection, params: dict) -> int:
    scope = params["scope"]
    keys = params["perspectives"]
    ctx = await asyncio.to_thread(build_review_context, conn, scope, keys)
    log.info(
        "Review: scope=%s perspectives=%d entries=%d omitted=%d ~%d tokens",
        scope, len(keys), ctx.entries_included, ctx.entries_omitted, ctx.est_tokens,
    )
    result = await client.chat(ctx.messages, temperature=0.9)
    cur = conn.execute(
        "INSERT INTO reviews (scope, range_start, range_end, perspectives, content, model, "
        "prompt_tokens, completion_tokens, seconds, entries_included, entries_omitted, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            scope, str(ctx.start), str(ctx.end), json.dumps(keys), result.content, settings.llm_model,
            result.prompt_tokens, result.completion_tokens, round(result.seconds, 1),
            ctx.entries_included, ctx.entries_omitted, utc_now_iso(),
        ),
    )
    return cur.lastrowid
