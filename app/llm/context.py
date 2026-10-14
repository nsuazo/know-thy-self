"""Builds the prompt: stable prefix first (system prompt, entries oldest-first), task instruction last.

Phase 3 will insert the profile and weekly/monthly summaries ahead of the verbatim entries.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from .. import repo
from ..config import settings
from ..days import logical_today
from .client import LLMError
from .perspectives import BY_KEY
from .prompts import SYSTEM_PROMPT, review_task

YESTERDAY_LABELS = {
    "done": "done",
    "done_later": "not done that day (finished later)",
    "dropped": "dropped",
    "open": "not done",
}

# Space reserved for the task instruction and message framing.
OVERHEAD_CHARS = 5000


@dataclass
class BuiltContext:
    messages: list[dict]
    start: date
    end: date
    entries_included: int
    entries_omitted: int
    est_tokens: int


def scope_range(conn: sqlite3.Connection, scope: str, today: date) -> tuple[date, date]:
    if scope == "today":
        return today, today
    if scope == "7d":
        return today - timedelta(days=6), today
    if scope == "30d":
        return today - timedelta(days=29), today
    if scope == "all":
        first = conn.execute("SELECT MIN(day) FROM entries").fetchone()[0]
        return (date.fromisoformat(first) if first else today), today
    raise ValueError(f"unknown scope {scope!r}")


def render_entry(conn: sqlite3.Connection, entry: sqlite3.Row, sections: list[sqlite3.Row]) -> str:
    day = date.fromisoformat(entry["day"])
    contents = repo.entry_contents(conn, entry["id"])
    tags = repo.entry_tags(conn, entry["id"])

    blocks: list[str] = []
    for s in sections:
        label = s["label"]
        if s["kind"] == "todos":
            todos = repo.todos_for_day(conn, day)
            if todos:
                lines = []
                for t in todos:
                    carried = f" (carried {t['carried_days']}d)" if t["carried_days"] > 0 else ""
                    lines.append(f"- [{'x' if t['done'] else ' '}] {t['text']}{carried}")
                blocks.append(f"**{label}:**\n" + "\n".join(lines))
        elif s["kind"] == "yesterday":
            parts: list[str] = []
            report = repo.yesterday_report(conn, day)
            if report:
                parts.append("\n".join(f"- {r['text']}: {YESTERDAY_LABELS[r['status']]}" for r in report))
            text = contents.get(s["key"], "").strip()
            if text:
                parts.append(text)
            if parts:
                blocks.append(f"**{label}:**\n" + "\n".join(parts))
        else:
            text = contents.get(s["key"], "").strip()
            if text:
                blocks.append(f"**{label}:**\n{text}")

    meta = []
    if entry["mood"] is not None:
        meta.append(f"Mood {entry['mood']}/5")
    if entry["energy"] is not None:
        meta.append(f"Energy {entry['energy']}/5")
    if tags:
        meta.append("Tags: " + ", ".join(tags))

    if not blocks and not meta:
        return ""
    head = f"### {day} ({day:%A})"
    out = [head]
    if meta:
        out.append(" · ".join(meta))
    out.append("")
    out.append("\n\n".join(blocks))
    return "\n".join(out).rstrip()


def build_review_context(
    conn: sqlite3.Connection,
    scope: str,
    perspective_keys: list[str],
    today: date | None = None,
) -> BuiltContext:
    today = today or logical_today()
    perspectives = [BY_KEY[k] for k in perspective_keys if k in BY_KEY]
    if not perspectives:
        raise LLMError("No valid perspectives selected.")

    start, end = scope_range(conn, scope, today)
    context_start = min(start, today - timedelta(days=settings.context_min_days - 1))

    sections = repo.get_sections(conn)
    rows = conn.execute(
        "SELECT * FROM entries WHERE day BETWEEN ? AND ? ORDER BY day",
        (str(context_start), str(end)),
    ).fetchall()
    rendered: list[tuple[str, str]] = []
    for row in rows:
        text = render_entry(conn, row, sections)
        if text:
            rendered.append((row["day"], text))

    if not any(day >= str(start) for day, _ in rendered):
        raise LLMError("There are no journal entries with content in that range yet.")

    # Fit the budget by dropping the oldest entries first (Phase 3 will summarize them instead).
    budget_chars = settings.context_budget_tokens * 4
    total = len(SYSTEM_PROMPT) + OVERHEAD_CHARS + sum(len(t) + 2 for _, t in rendered)
    omitted = 0
    while len(rendered) > 1 and total > budget_chars:
        _, dropped = rendered.pop(0)
        total -= len(dropped) + 2
        omitted += 1

    first_included = date.fromisoformat(rendered[0][0])
    focus_start = max(start, first_included)
    task = review_task(
        perspectives,
        today=today,
        focus_start=focus_start,
        focus_end=end,
        entries_included=len(rendered),
        entries_omitted=omitted,
    )
    entries_text = "# JOURNAL ENTRIES\n\n" + "\n\n".join(text for _, text in rendered)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": entries_text + "\n\n---\n\n" + task},
    ]
    return BuiltContext(
        messages=messages,
        start=focus_start,
        end=end,
        entries_included=len(rendered),
        entries_omitted=omitted,
        est_tokens=total // 4,
    )
