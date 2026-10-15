"""Background LLM jobs. Status and progress live in the llm_jobs table; the UI polls it.

Kinds: review, catch_up (weekly/monthly summaries), profile.
"""
import asyncio
import json
import logging
import sqlite3

from .config import settings
from .days import utc_now_iso
from .db import connect
from .llm import client, summarize
from .llm.actions import split_actions
from .llm.client import LLMError
from .llm.context import build_review_context

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
_submit_lock = asyncio.Lock()  # the busy check and the insert must not interleave (double clicks, two tabs)


class JobRejected(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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


async def submit(conn: sqlite3.Connection, kind: str, params: dict) -> int:
    """Checks that nothing else is running and the LLM is reachable, then starts the job."""
    async with _submit_lock:
        if active_job(conn):
            raise JobRejected(409, "Another LLM job is already running. Wait for it to finish.")
        ok, detail = await client.check_reachable()
        client.note_status(ok, detail)
        if not ok:
            raise JobRejected(503, client.unreachable_message(detail))
        job_id = create_job(conn, kind, params)
        start(job_id)
        return job_id


def start(job_id: int) -> None:
    task = asyncio.create_task(_run(job_id))
    _tasks.add(task)  # keep a reference so it isn't garbage-collected mid-run
    task.add_done_callback(_tasks.discard)


def next_url(kind: str, result_id: int | None) -> str:
    if kind == "review" and result_id:
        return f"/review/{result_id}"
    if kind == "profile" and result_id:
        return f"/profile/{result_id}"
    if kind == "catch_up":
        return "/summaries"
    return "/"


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

        def progress(done: int, total: int, label: str) -> None:
            conn.execute(
                "UPDATE llm_jobs SET progress_done = ?, progress_total = ?, progress_label = ? WHERE id = ?",
                (done, total, label, job_id),
            )

        try:
            kind = job["kind"]
            if kind == "review":
                result_id = await _do_review(conn, params)
            elif kind == "catch_up":
                await summarize.catch_up(conn, progress)
                result_id = None
            elif kind == "profile":
                result_id = await summarize.update_profile(conn)
            else:
                raise LLMError(f"Unknown job kind: {kind}")
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
    distill = bool(params.get("distill", False))
    ctx = await asyncio.to_thread(build_review_context, conn, scope, keys, None, distill)
    log.info(
        "Review: scope=%s perspectives=%d entries=%d summaries=%d omitted=%d ~%d tokens",
        scope, len(keys), ctx.entries_included, ctx.summaries_used, ctx.entries_omitted, ctx.est_tokens,
    )
    result = await client.chat(ctx.messages, temperature=0.9)
    _, actions = split_actions(result.content) if distill else ("", [])
    cur = conn.execute(
        "INSERT INTO reviews (scope, range_start, range_end, perspectives, content, actions, model, "
        "prompt_tokens, completion_tokens, seconds, entries_included, entries_omitted, summaries_used, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            scope, str(ctx.start), str(ctx.end), json.dumps(keys), result.content,
            json.dumps([{"text": a, "todo_id": None} for a in actions]) if actions else None, settings.llm_model,
            result.prompt_tokens, result.completion_tokens, round(result.seconds, 1),
            ctx.entries_included, ctx.entries_omitted, ctx.summaries_used, utc_now_iso(),
        ),
    )
    return cur.lastrowid
