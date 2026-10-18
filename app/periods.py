"""Week/month arithmetic, summary planning and staleness. Database logic only; no LLM calls.

Weeks run Monday..Sunday. A "month block" is the set of weeks whose Monday falls in one calendar
month, so blocks never overlap and never leave gaps. Only complete weeks/blocks (ending before
today's logical day) are ever summarized.
"""
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

# An entry row (alias e) counts as having content if it has any text, mood, energy or tags, or if
# a todo or long-term goal was added, finished or dropped that day.
CONTENT_SQL = """(
    e.mood IS NOT NULL OR e.energy IS NOT NULL
    OR EXISTS (SELECT 1 FROM entry_sections s WHERE s.entry_id = e.id AND TRIM(s.content) <> '')
    OR EXISTS (SELECT 1 FROM entry_tags t WHERE t.entry_id = e.id)
    OR EXISTS (SELECT 1 FROM todos td WHERE td.created_day = e.day OR td.completed_day = e.day
               OR td.dropped_day = e.day)
    OR EXISTS (SELECT 1 FROM goals g WHERE g.created_day = e.day OR g.done_day = e.day OR g.dropped_day = e.day)
)"""


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def sunday_of(monday: date) -> date:
    return monday + timedelta(days=6)


def month_block(monday: date) -> tuple[str, date, date]:
    """(key 'YYYY-MM', first Monday, last Sunday) of the block containing this Monday."""
    ym = (monday.year, monday.month)

    def same(d: date) -> bool:
        return (d.year, d.month) == ym

    first = monday
    while same(first - timedelta(days=7)):
        first -= timedelta(days=7)
    last = monday
    while same(last + timedelta(days=7)):
        last += timedelta(days=7)
    return f"{ym[0]}-{ym[1]:02d}", first, last + timedelta(days=6)


def content_entries(conn: sqlite3.Connection, start: date, end: date) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT e.day, e.updated_at FROM entries e WHERE e.day BETWEEN ? AND ? AND {CONTENT_SQL} ORDER BY e.day",
        (str(start), str(end)),
    ).fetchall()


def weeks_with_content(conn: sqlite3.Connection, before: date) -> dict[date, tuple[int, str]]:
    """{monday: (entries with content, newest updated_at)} for entries dated before `before`."""
    rows = conn.execute(
        f"SELECT e.day, e.updated_at FROM entries e WHERE e.day < ? AND {CONTENT_SQL} ORDER BY e.day",
        (str(before),),
    ).fetchall()
    out: dict[date, tuple[int, str]] = {}
    for r in rows:
        monday = monday_of(date.fromisoformat(r["day"]))
        n, newest = out.get(monday, (0, ""))
        out[monday] = (n + 1, max(newest, r["updated_at"]))
    return out


def week_info(conn: sqlite3.Connection, monday: date) -> tuple[int, str]:
    rows = content_entries(conn, monday, sunday_of(monday))
    return len(rows), max((r["updated_at"] for r in rows), default="")


def month_blocks(weeks: dict[date, tuple[int, str]], today: date) -> dict[str, dict]:
    """Complete month blocks (last Sunday before today) built from weeks that have content."""
    blocks: dict[str, dict] = {}
    for monday in sorted(weeks):
        key, start, end = month_block(monday)
        if end >= today:
            continue
        block = blocks.setdefault(key, {"key": key, "start": start, "end": end, "weeks": []})
        block["weeks"].append(monday)
    return blocks


@dataclass
class Plan:
    weeks: list[date]       # Mondays to (re)generate, oldest first
    months: list[str]       # month-block keys to (re)generate, oldest first
    missing_weeks: int
    stale_weeks: int

    @property
    def total(self) -> int:
        return len(self.weeks) + len(self.months)


def plan(conn: sqlite3.Connection, today: date) -> Plan:
    weeks = weeks_with_content(conn, monday_of(today))
    have_w = {r["start_day"]: r for r in conn.execute("SELECT * FROM summaries WHERE period = 'week'")}
    have_m = {r["start_day"]: r for r in conn.execute("SELECT * FROM summaries WHERE period = 'month'")}

    todo_weeks: list[date] = []
    missing = stale = 0
    for monday in sorted(weeks):
        row = have_w.get(str(monday))
        if row is None:
            todo_weeks.append(monday)
            missing += 1
        elif row["source_updated_at"] < weeks[monday][1]:
            todo_weeks.append(monday)
            stale += 1
    todo_set = set(todo_weeks)

    todo_months: list[str] = []
    for key, block in sorted(month_blocks(weeks, today).items()):
        if len(block["weeks"]) < 2:  # a month with one content week is just that week's summary
            continue
        row = have_m.get(str(block["start"]))
        if row is None or any(w in todo_set for w in block["weeks"]):
            todo_months.append(key)
            continue
        newest_week_summary = max(have_w[str(w)]["created_at"] for w in block["weeks"])
        if newest_week_summary > row["source_updated_at"]:
            todo_months.append(key)
    return Plan(todo_weeks, todo_months, missing, stale)


def range_stats(conn: sqlite3.Connection, start: date, end: date) -> str:
    """Facts computed in code (not by the model): entry days, mood/energy, todo flow."""
    s, e = str(start), str(end)
    rows = conn.execute(
        f"SELECT e.mood, e.energy FROM entries e WHERE e.day BETWEEN ? AND ? AND {CONTENT_SQL}", (s, e)
    ).fetchall()
    span = (end - start).days + 1

    def fmt(values: list[int]) -> str:
        if not values:
            return "not recorded"
        return f"average {sum(values) / len(values):.1f} (lowest {min(values)}, highest {max(values)}, on {len(values)} days)"

    def count(column: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM todos WHERE {column} BETWEEN ? AND ?", (s, e)).fetchone()[0]

    open_rows = conn.execute(
        "SELECT text, created_day FROM todos WHERE created_day <= ? "
        "AND (completed_day IS NULL OR completed_day > ?) AND (dropped_day IS NULL OR dropped_day > ?) "
        "ORDER BY created_day LIMIT 8",
        (e, e, e),
    ).fetchall()

    lines = [
        f"- Days with entries: {len(rows)} of {span}",
        f"- Mood (1-5): {fmt([r['mood'] for r in rows if r['mood'] is not None])}",
        f"- Energy (1-5): {fmt([r['energy'] for r in rows if r['energy'] is not None])}",
        f"- Todos during this period: {count('created_day')} added, {count('completed_day')} completed, "
        f"{count('dropped_day')} dropped",
    ]
    if open_rows:
        items = "; ".join(
            f"{r['text']} ({(end - date.fromisoformat(r['created_day'])).days}d)" for r in open_rows
        )
        lines.append(f"- Todos still open at the end of the period, with days since added: {items}")
    else:
        lines.append("- No todos were left open at the end of the period.")
    return "\n".join(lines)
