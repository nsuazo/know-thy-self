"""LLM-backed generation of weekly/monthly summaries and profile versions."""
import logging
import sqlite3
from collections.abc import Callable
from datetime import date

from .. import periods
from ..config import settings
from ..days import logical_today, utc_now_iso
from . import client
from .client import LLMError
from .context import build_profile_context, render_entries
from .prompts import SUMMARY_SYSTEM, monthly_task, weekly_task

log = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]


def _upsert_summary(
    conn: sqlite3.Connection, *, period: str, start: date, end: date, content: str,
    source_updated_at: str, entries_count: int, seconds: float,
) -> None:
    conn.execute(
        "INSERT INTO summaries (period, start_day, end_day, content, source_updated_at, entries_count, "
        "model, seconds, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (period, start_day) DO UPDATE SET end_day = excluded.end_day, "
        "content = excluded.content, source_updated_at = excluded.source_updated_at, "
        "entries_count = excluded.entries_count, model = excluded.model, seconds = excluded.seconds, "
        "created_at = excluded.created_at",
        (period, str(start), str(end), content, source_updated_at, entries_count,
         settings.llm_model, round(seconds, 1), utc_now_iso()),
    )


async def generate_week(conn: sqlite3.Connection, monday: date) -> None:
    sunday = periods.sunday_of(monday)
    count, newest = periods.week_info(conn, monday)  # captured first, so later edits mark it stale
    texts = [t for _, t in render_entries(conn, monday, sunday)]
    if not texts:
        raise LLMError(f"There are no entries to summarize for the week of {monday}.")
    stats = periods.range_stats(conn, monday, sunday)
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": "# JOURNAL ENTRIES\n\n" + "\n\n".join(texts) + "\n\n---\n\n"
         + weekly_task(monday, sunday, stats)},
    ]
    result = await client.chat(messages, temperature=0.3, thinking=settings.summary_thinking)
    _upsert_summary(conn, period="week", start=monday, end=sunday, content=result.content,
                    source_updated_at=newest, entries_count=count, seconds=result.seconds)


async def generate_month(conn: sqlite3.Connection, key: str, today: date) -> None:
    weeks = periods.weeks_with_content(conn, periods.monday_of(today))
    block = periods.month_blocks(weeks, today).get(key)
    if block is None:
        raise LLMError(f"The month {key} is not complete yet.")
    rows = []
    for monday in block["weeks"]:
        row = conn.execute(
            "SELECT * FROM summaries WHERE period = 'week' AND start_day = ?", (str(monday),)
        ).fetchone()
        if row is None:
            raise LLMError(f"The week of {monday} has no summary yet.")
        rows.append(row)
    newest = max(r["created_at"] for r in rows)
    stats = periods.range_stats(conn, block["start"], block["end"])
    body = "\n\n".join(
        f"### Week {r['start_day']} to {r['end_day']} ({r['entries_count']} entries)\n{r['content']}" for r in rows
    )
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": "# WEEKLY SUMMARIES\n\n" + body + "\n\n---\n\n"
         + monthly_task(block["start"], block["end"], stats)},
    ]
    result = await client.chat(messages, temperature=0.3, thinking=settings.summary_thinking)
    _upsert_summary(conn, period="month", start=block["start"], end=block["end"], content=result.content,
                    source_updated_at=newest, entries_count=sum(r["entries_count"] for r in rows),
                    seconds=result.seconds)


async def catch_up(conn: sqlite3.Connection, progress: Progress, today: date | None = None) -> None:
    """Generate every missing or outdated weekly summary, then the monthly ones built from them."""
    today = today or logical_today()
    plan = periods.plan(conn, today)
    total = plan.total
    if total == 0:
        raise LLMError("All summaries are already up to date.")
    done = 0
    progress(done, total, "Starting…")
    try:
        for monday in plan.weeks:
            progress(done, total, f"Summarizing the week of {monday} ({done + 1} of {total})")
            await generate_week(conn, monday)
            done += 1
        for key in plan.months:
            progress(done, total, f"Summarizing the month {key} ({done + 1} of {total})")
            await generate_month(conn, key, today)
            done += 1
    except LLMError as exc:
        if done:
            raise LLMError(f"{exc} {done} of {total} summaries were saved; run it again to continue.") from exc
        raise
    progress(done, total, "Done")


async def update_profile(conn: sqlite3.Connection, today: date | None = None) -> int:
    ctx = build_profile_context(conn, today)
    log.info("Profile v%d: %s to %s, %d entries, %d summaries, ~%d tokens",
             ctx.version, ctx.start, ctx.end, ctx.entries_included, ctx.summaries_used, ctx.est_tokens)
    # Analytical synthesis: use the server's configured thinking mode, not the summary override.
    result = await client.chat(ctx.messages, temperature=0.3)
    cur = conn.execute(
        "INSERT INTO profile_versions (version, content, covers_from, covers_through, entries_count, "
        "summaries_used, model, prompt_tokens, completion_tokens, seconds, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ctx.version, result.content, str(ctx.start), str(ctx.end), ctx.entries_included, ctx.summaries_used,
         settings.llm_model, result.prompt_tokens, result.completion_tokens, round(result.seconds, 1),
         utc_now_iso()),
    )
    return cur.lastrowid
