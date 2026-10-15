"""Builds prompts in a fixed layer order so the server's prefix cache keeps hitting:

    system prompt -> # PROFILE -> # EARLIER PERIODS (summaries) -> # JOURNAL ENTRIES -> # TASK (last)

Recent weeks go in verbatim. Older weeks appear as weekly summaries, much older months as monthly
summaries. When the result is over budget, the oldest verbatim weeks that have a summary are
swapped for it first; only then are the oldest pieces dropped.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from .. import periods, repo
from ..config import settings
from ..days import logical_today
from .client import LLMError
from .perspectives import BY_KEY
from .prompts import SYSTEM_PROMPT, profile_task, review_task

YESTERDAY_LABELS = {
    "done": "done",
    "done_later": "not done that day (finished later)",
    "dropped": "dropped",
    "dropped_later": "not done (dropped on a later day)",
    "open": "not done",
}

OVERHEAD_CHARS = 6000   # room for the task instruction and message framing
WINDOW_WEEKS = 13       # how far back (before the verbatim part) weekly summaries are preferred over monthly


@dataclass
class BuiltContext:
    messages: list[dict]
    start: date
    end: date
    entries_included: int
    entries_omitted: int
    summaries_used: int
    est_tokens: int


@dataclass
class Unit:
    sort: str              # ISO date used for ordering
    kind: str              # "verbatim" | "week_summary" | "month"
    text: str
    alt: str | None = None  # summary that can replace a verbatim week to save space
    entries: int = 0        # verbatim entries inside this unit


# ---------- rendering ----------

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
        head = label if label.rstrip().endswith(("?", ":", ".")) else label + ":"
        if s["kind"] == "todos":
            todos = repo.todos_for_day(conn, day)
            if todos:
                lines = []
                for t in todos:
                    carried = f" (carried {t['carried_days']}d)" if t["carried_days"] > 0 else ""
                    lines.append(f"- [{'x' if t['done'] else ' '}] {t['text']}{carried}")
                blocks.append(f"**{head}**\n" + "\n".join(lines))
        elif s["kind"] == "yesterday":
            parts: list[str] = []
            report = repo.yesterday_report(conn, day)
            if report:
                parts.append("\n".join(f"- {r['text']}: {YESTERDAY_LABELS[r['status']]}" for r in report))
            text = contents.get(s["key"], "").strip()
            if text:
                parts.append(text)
            if parts:
                blocks.append(f"**{head}**\n" + "\n".join(parts))
        else:
            text = contents.get(s["key"], "").strip()
            if text:
                blocks.append(f"**{head}**\n{text}")

    meta = []
    if entry["mood"] is not None:
        meta.append(f"Mood {entry['mood']}/5")
    if entry["energy"] is not None:
        meta.append(f"Energy {entry['energy']}/5")
    if tags:
        meta.append("Tags: " + ", ".join(tags))

    if not blocks and not meta:
        return ""
    out = [f"### {day} ({day:%A})"]
    if meta:
        out.append(" · ".join(meta))
    out.append("")
    out.append("\n\n".join(blocks))
    return "\n".join(out).rstrip()


def render_entries(conn: sqlite3.Connection, start: date, end: date) -> list[tuple[str, str]]:
    """[(day, text)] for entries in the range that render to something."""
    rows = conn.execute(
        "SELECT * FROM entries WHERE day BETWEEN ? AND ? ORDER BY day", (str(start), str(end))
    ).fetchall()
    out = []
    for row in rows:
        # Per entry, so answers under retired prompts still reach the model.
        text = render_entry(conn, row, repo.sections_for_entry(conn, row["id"]))
        if text:
            out.append((row["day"], text))
    return out


def week_summary_text(row: sqlite3.Row) -> str:
    return f"### Week {row['start_day']} to {row['end_day']} (summary)\n{row['content']}"


def month_summary_text(row: sqlite3.Row) -> str:
    return f"### Month {row['start_day'][:7]}, {row['start_day']} to {row['end_day']} (summary)\n{row['content']}"


# ---------- layering ----------

def build_units(
    conn: sqlite3.Connection,
    *,
    verbatim_start: date,
    end: date,
    today: date,
    include_before: bool,
) -> list[Unit]:
    sums = {(r["period"], r["start_day"]): r for r in conn.execute("SELECT * FROM summaries")}
    units: list[Unit] = []

    # 1) The verbatim region, one unit per week.
    by_week: dict[date, list[str]] = {}
    for day, text in render_entries(conn, verbatim_start, end):
        by_week.setdefault(periods.monday_of(date.fromisoformat(day)), []).append(text)
    for monday, texts in sorted(by_week.items()):
        row = sums.get(("week", str(monday)))
        sunday = periods.sunday_of(monday)
        usable = row is not None and sunday < today and monday >= verbatim_start and sunday <= end
        units.append(
            Unit(str(monday), "verbatim", "\n\n".join(texts),
                 alt=week_summary_text(row) if usable else None, entries=len(texts))
        )

    # 2) Everything before it: summaries where they exist, raw entries where they don't.
    if include_before:
        weeks = periods.weeks_with_content(conn, verbatim_start)
        window_start = verbatim_start - timedelta(weeks=WINDOW_WEEKS)
        blocks: dict[str, dict] = {}
        for monday in sorted(weeks):
            key, b_start, b_end = periods.month_block(monday)
            blocks.setdefault(key, {"start": b_start, "end": b_end, "weeks": []})["weeks"].append(monday)
        for key, block in sorted(blocks.items()):
            month_row = sums.get(("month", str(block["start"])))
            if month_row is not None and block["end"] < window_start and block["end"] < verbatim_start:
                units.append(Unit(str(block["start"]), "month", month_summary_text(month_row)))
                continue
            for monday in block["weeks"]:
                row = sums.get(("week", str(monday)))
                if row is not None:
                    units.append(Unit(str(monday), "week_summary", week_summary_text(row)))
                    continue
                texts = [t for _, t in render_entries(conn, monday, periods.sunday_of(monday))]
                if texts:
                    units.append(Unit(str(monday), "verbatim", "\n\n".join(texts), entries=len(texts)))
    return sorted(units, key=lambda u: u.sort)


def fit(units: list[Unit], budget_chars: int, fixed_chars: int) -> tuple[list[Unit], int, int]:
    """Shrink, then drop. Returns (units, entries_omitted, summaries_dropped)."""
    total = fixed_chars + sum(len(u.text) + 2 for u in units)
    # A) swap the oldest verbatim weeks for their summaries (information-preserving)
    for u in units:
        if total <= budget_chars:
            break
        if u.kind == "verbatim" and u.alt:
            total -= len(u.text) - len(u.alt)
            u.text, u.kind, u.alt, u.entries = u.alt, "week_summary", None, 0
    # B) drop the oldest pieces, always keeping at least the newest one
    entries_omitted = summaries_dropped = 0
    units = list(units)
    while len(units) > 1 and total > budget_chars:
        dropped = units.pop(0)
        total -= len(dropped.text) + 2
        if dropped.kind == "verbatim":
            entries_omitted += dropped.entries
        else:
            summaries_dropped += 1
    return units, entries_omitted, summaries_dropped


def assemble(profile_text: str | None, units: list[Unit]) -> str:
    parts: list[str] = []
    if profile_text:
        parts.append("# PROFILE\n\n" + profile_text.strip())
    summaries = [u.text for u in units if u.kind != "verbatim"]
    if summaries:
        parts.append("# EARLIER PERIODS\n\n" + "\n\n".join(summaries))
    verbatim = [u.text for u in units if u.kind == "verbatim"]
    if verbatim:
        parts.append("# JOURNAL ENTRIES\n\n" + "\n\n".join(verbatim))
    else:
        parts.append("# JOURNAL ENTRIES\n\n(No entries are included verbatim; see the summaries above.)")
    return "\n\n".join(parts)


def _build(
    conn: sqlite3.Connection,
    *,
    profile_text: str | None,
    verbatim_start: date,
    end: date,
    today: date,
    include_before: bool,
) -> tuple[str, list[Unit], int, int, int, int]:
    units = build_units(conn, verbatim_start=verbatim_start, end=end, today=today, include_before=include_before)
    fixed = len(SYSTEM_PROMPT) + OVERHEAD_CHARS + (len(profile_text) + 20 if profile_text else 0)
    units, omitted, summaries_dropped = fit(units, settings.context_budget_tokens * 4, fixed)
    body = assemble(profile_text, units)
    est_tokens = (len(SYSTEM_PROMPT) + OVERHEAD_CHARS + len(body)) // 4
    return body, units, omitted, summaries_dropped, sum(1 for u in units if u.kind != "verbatim"), est_tokens


# ---------- public builders ----------

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
    if not periods.content_entries(conn, start, end):
        raise LLMError("There are no journal entries with content in that range yet.")

    # Whole weeks, so no day falls between the summaries and the verbatim part.
    verbatim_start = periods.monday_of(min(start, today - timedelta(days=settings.context_min_days - 1)))
    latest = repo.latest_profile(conn)
    body, units, omitted, summaries_dropped, summaries_used, est_tokens = _build(
        conn,
        profile_text=latest["content"] if latest else None,
        verbatim_start=verbatim_start,
        end=end,
        today=today,
        include_before=True,
    )
    entries_included = sum(u.entries for u in units if u.kind == "verbatim")
    focus_start = max(start, date.fromisoformat(units[0].sort)) if units else start
    task = review_task(
        perspectives,
        today=today,
        focus_start=focus_start,
        focus_end=end,
        entries_included=entries_included,
        omitted_before=date.fromisoformat(units[0].sort) if (omitted or summaries_dropped) else None,
        summaries_used=summaries_used,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body + "\n\n---\n\n" + task},
    ]
    return BuiltContext(messages, focus_start, end, entries_included, omitted, summaries_used, est_tokens)


@dataclass
class ProfileContext:
    messages: list[dict]
    version: int
    start: date
    end: date
    entries_included: int
    summaries_used: int
    est_tokens: int


def build_profile_context(conn: sqlite3.Connection, today: date | None = None) -> ProfileContext:
    """Everything since the last profile (or all history for the first one), through yesterday."""
    today = today or logical_today()
    end = today - timedelta(days=1)
    latest = repo.latest_profile(conn)
    if latest:
        start = date.fromisoformat(latest["covers_through"]) + timedelta(days=1)
    else:
        first = conn.execute(
            f"SELECT MIN(e.day) FROM entries e WHERE {periods.CONTENT_SQL}"
        ).fetchone()[0]
        if first is None:
            raise LLMError("There are no journal entries yet to build a profile from.")
        start = date.fromisoformat(first)
    if start > end or not periods.content_entries(conn, start, end):
        raise LLMError("There are no new journal entries since the last profile update.")

    version = (latest["version"] + 1) if latest else 1
    body, units, _, _, summaries_used, est_tokens = _build(
        conn,
        profile_text=latest["content"] if latest else None,
        verbatim_start=start,
        end=end,
        today=today,
        include_before=False,
    )
    entries_included = sum(u.entries for u in units if u.kind == "verbatim")
    task = profile_task(
        today=today,
        version=version,
        has_previous=latest is not None,
        start=start,
        end=end,
        entries_included=entries_included,
        summaries_used=summaries_used,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body + "\n\n---\n\n" + task},
    ]
    return ProfileContext(messages, version, start, end, entries_included, summaries_used, est_tokens)
