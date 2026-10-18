"""Builds prompts in a fixed layer order so the server's prefix cache keeps hitting:

    system prompt -> # PROFILE -> # LONG-TERM GOALS -> # EARLIER PERIODS (summaries) -> # QUESTION ANSWERS
    -> # JOURNAL ENTRIES -> # TASK (last)

Recent weeks go in verbatim. Older weeks appear as weekly summaries, much older months as monthly
summaries. When the result is over budget, the oldest verbatim weeks that have a summary are
swapped for it first; only then are the oldest pieces dropped.
"""
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from .. import periods, qrepo, repo
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
        if s["kind"] == "goals":
            # Only what changed that day; the current list is given once under # LONG-TERM GOALS.
            events = repo.goal_events(conn, day)
            if events:
                blocks.append(f"**{head}**\n" + "\n".join(f"- {e}" for e in events))
        elif s["kind"] == "todos":
            todos = repo.todos_for_day(conn, day)
            if todos:
                lines = []
                for t in todos:
                    carried = f" (carried {t['carried_days']}d)" if t["carried_days"] > 0 else ""
                    panel = " (suggested by a panel review)" if t["from_review"] else ""
                    goal = f" (step toward goal: {t['goal']})" if t["goal"] else ""
                    lines.append(f"- [{'x' if t['done'] else ' '}] {t['text']}{carried}{goal}{panel}")
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


def render_answers(rows: list) -> str:
    """Answers grouped by question (in the order first answered), cited as [Q12, 2026-10-15]."""
    by_q: dict[int, list] = {}
    for r in rows:
        by_q.setdefault(r["question_id"], []).append(r)
    blocks = []
    for qid, answers in by_q.items():
        first = answers[0]
        lines = [f"### Q{qid} ({qrepo.CATEGORIES.get(first['category'], first['category'])})",
                 f"Question: {first['q_text']}"]
        if first["claim"]:
            lines.append(f'Profile claim being checked: "{first["claim"]}"')
        for a in answers:
            structured = qrepo.describe_value(first["kind"], qrepo.options_of(first), qrepo.value_of(a))
            text = a["text"].strip()
            body = " | ".join(x for x in (structured, text) if x) or "(no text)"
            lines.append(f"Answer [Q{qid}, {a['day']}]: {body}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


GOALS_RECENT_DAYS = 90


def render_goals(conn: sqlite3.Connection, today: date) -> str:
    """Current long-term goals, plus ones achieved or dropped in the last 90 days."""
    lines = [f"- {g['text']} (tracking since {g['created_day']})" for g in repo.active_goals(conn, today)]
    since = str(today - timedelta(days=GOALS_RECENT_DAYS))
    for g in conn.execute("SELECT * FROM goals WHERE done_day >= ? ORDER BY done_day", (since,)):
        lines.append(f"- {g['text']} (achieved {g['done_day']})")
    for g in conn.execute("SELECT * FROM goals WHERE dropped_day >= ? ORDER BY dropped_day", (since,)):
        lines.append(f"- {g['text']} (dropped {g['dropped_day']})")
    return "\n".join(lines)


def assemble(profile_text: str | None, units: list[Unit], answers_text: str | None = None,
             goals_text: str | None = None) -> str:
    parts: list[str] = []
    if profile_text:
        parts.append("# PROFILE\n\n" + profile_text.strip())
    if goals_text:
        parts.append("# LONG-TERM GOALS\n\n" + goals_text)
    summaries = [u.text for u in units if u.kind != "verbatim"]
    if summaries:
        parts.append("# EARLIER PERIODS\n\n" + "\n\n".join(summaries))
    if answers_text:
        parts.append("# QUESTION ANSWERS\n\n" + answers_text)
    verbatim = [u.text for u in units if u.kind == "verbatim"]
    if verbatim:
        parts.append("# JOURNAL ENTRIES\n\n" + "\n\n".join(verbatim))
    else:
        parts.append("# JOURNAL ENTRIES\n\n(No entries are included verbatim; see the material above.)")
    return "\n\n".join(parts)


def _build(
    conn: sqlite3.Connection,
    *,
    profile_text: str | None,
    verbatim_start: date,
    end: date,
    today: date,
    include_before: bool,
    answers_text: str | None = None,
) -> tuple[str, list[Unit], int, int, int, int]:
    units = build_units(conn, verbatim_start=verbatim_start, end=end, today=today, include_before=include_before)
    goals_text = render_goals(conn, today) or None
    fixed = (len(SYSTEM_PROMPT) + OVERHEAD_CHARS + (len(profile_text) + 20 if profile_text else 0)
             + (len(answers_text) + 30 if answers_text else 0) + (len(goals_text) + 30 if goals_text else 0))
    units, omitted, summaries_dropped = fit(units, settings.context_budget_tokens * 4, fixed)
    body = assemble(profile_text, units, answers_text, goals_text)
    est_tokens = (len(SYSTEM_PROMPT) + OVERHEAD_CHARS + len(body)) // 4
    return body, units, omitted, summaries_dropped, sum(1 for u in units if u.kind != "verbatim"), est_tokens


# ---------- answers chosen for each kind of prompt ----------

ANSWERS_MAX_CHARS = 40_000   # answers are compact; this only bites after years of use
REVIEW_ANSWER_DAYS = 30
_Q_CITE = re.compile(r"\[Q(\d+)")


def _cap(rows: list) -> list:
    """Keep the newest answers that fit the cap (rows are oldest first)."""
    total, kept = 0, []
    for r in reversed(rows):
        total += len(r["text"]) + len(r["q_text"]) + 80
        if total > ANSWERS_MAX_CHARS:
            break
        kept.append(r)
    return list(reversed(kept))


def review_answers(conn: sqlite3.Connection, today: date, profile_text: str | None) -> list:
    """The last 30 days of answers, plus any older answer the current profile cites."""
    cited = sorted({int(m) for m in _Q_CITE.findall(profile_text or "")})
    since = str(today - timedelta(days=REVIEW_ANSWER_DAYS - 1))
    if cited:
        marks = ",".join("?" * len(cited))
        rows = qrepo.answer_rows(conn, f"a.day >= ? OR a.question_id IN ({marks})", (since, *cited))
    else:
        rows = qrepo.answer_rows(conn, "a.day >= ?", (since,))
    return _cap(rows)


# ---------- public builders ----------

def build_review_context(
    conn: sqlite3.Connection,
    scope: str,
    perspective_keys: list[str],
    today: date | None = None,
    distill: bool = False,
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
    profile_text = latest["content"] if latest else None
    answers = review_answers(conn, today, profile_text)
    body, units, omitted, summaries_dropped, summaries_used, est_tokens = _build(
        conn,
        profile_text=profile_text,
        verbatim_start=verbatim_start,
        end=end,
        today=today,
        include_before=True,
        answers_text=render_answers(answers) or None,
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
        distill=distill,
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
    answers_included: int = 0
    answers_through: int = 0


def build_profile_context(conn: sqlite3.Connection, today: date | None = None) -> ProfileContext:
    """Everything since the last profile (or all history for the first one): entries through
    yesterday, plus every answer to a direct question that the last profile has not read yet."""
    today = today or logical_today()
    yesterday = today - timedelta(days=1)
    latest = repo.latest_profile(conn)
    if latest:
        start = date.fromisoformat(latest["covers_through"]) + timedelta(days=1)
        answers_after = latest["answers_through"] or 0
    else:
        first = conn.execute(
            f"SELECT MIN(e.day) FROM entries e WHERE {periods.CONTENT_SQL}"
        ).fetchone()[0]
        start = date.fromisoformat(first) if first else yesterday
        answers_after = 0
    has_entries = start <= yesterday and bool(periods.content_entries(conn, start, yesterday))
    answers = qrepo.answer_rows(conn, "a.id > ?", (answers_after,))
    if not has_entries and not answers:
        if latest:
            raise LLMError("There is nothing new since the last profile update: no new entries before today "
                           "and no new answers to questions.")
        raise LLMError("There are no journal entries or answers yet to build a profile from.")

    if has_entries:
        end = yesterday
    else:
        # Answers only: the entry range stays where the last version left it.
        start = end = date.fromisoformat(latest["covers_through"]) if latest else yesterday
    answers = _cap(answers)
    version = (latest["version"] + 1) if latest else 1
    body, units, _, _, summaries_used, est_tokens = _build(
        conn,
        profile_text=latest["content"] if latest else None,
        verbatim_start=start if has_entries else end + timedelta(days=1),  # empty range: no entries re-read
        end=end,
        today=today,
        include_before=False,
        answers_text=render_answers(answers) or None,
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
        answers_included=len(answers),
        has_entries=has_entries,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body + "\n\n---\n\n" + task},
    ]
    through = max((a["id"] for a in answers), default=answers_after)
    return ProfileContext(messages, version, start, end, entries_included, summaries_used, est_tokens,
                          len(answers), through)
