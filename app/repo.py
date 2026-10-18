"""Data access for entries, sections, tags, todos and search."""
import sqlite3
from datetime import date, timedelta

from .days import utc_now_iso
from .db import tx

VISIBLE_ON_DAY = """
    created_day <= :d
    AND (completed_day IS NULL OR completed_day >= :d)
    AND (dropped_day IS NULL OR dropped_day > :d)
"""


# ---------- sections ----------

CATEGORY_LABELS = {
    "core": "Goals and today",
    "grab_bag": "Grab bag",
    "todo_incubator": "Next actions",
    "social_incubator": "People and stories",
    "psych": "Inner signal",
    "retired": "Retired prompts (older entries)",
}


def get_sections(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The live template: active prompts only."""
    return conn.execute("SELECT * FROM sections WHERE active = 1 ORDER BY sort").fetchall()


def sections_for_entry(conn: sqlite3.Connection, entry_id: int | None) -> list[sqlite3.Row]:
    """Active prompts, then any retired prompt this entry has an answer for.

    Retiring a prompt must never hide what was already written under it.
    """
    if entry_id is None:
        return get_sections(conn)
    return conn.execute(
        "SELECT * FROM sections s WHERE s.active = 1 "
        "OR EXISTS (SELECT 1 FROM entry_sections es WHERE es.entry_id = ? AND es.section_key = s.key "
        "           AND TRIM(es.content) <> '') "
        "ORDER BY s.active DESC, s.sort",
        (entry_id,),
    ).fetchall()


def section_groups(sections: list[sqlite3.Row]) -> list[dict]:
    """Group sections by category, in order of first appearance, for the day page."""
    groups: dict[str, dict] = {}
    for s in sections:
        cat = s["category"] if s["active"] else "retired"
        g = groups.setdefault(cat, {"key": cat, "label": CATEGORY_LABELS.get(cat, cat), "sections": []})
        g["sections"].append(s)
    return list(groups.values())


def section_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    # Retired prompts stay editable: an old day may still show one with an answer in it.
    return conn.execute("SELECT * FROM sections WHERE key = ?", (key,)).fetchone()


# ---------- entries ----------

def get_entry(conn: sqlite3.Connection, day: date | str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM entries WHERE day = ?", (str(day),)).fetchone()


def ensure_entry(conn: sqlite3.Connection, day: date | str) -> int:
    now = utc_now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO entries (day, created_at, updated_at) VALUES (?, ?, ?)",
        (str(day), now, now),
    )
    return conn.execute("SELECT id FROM entries WHERE day = ?", (str(day),)).fetchone()[0]


def touch_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (utc_now_iso(), entry_id))


def entry_contents(conn: sqlite3.Connection, entry_id: int) -> dict[str, str]:
    rows = conn.execute(
        "SELECT section_key, content FROM entry_sections WHERE entry_id = ?", (entry_id,)
    ).fetchall()
    return {r["section_key"]: r["content"] for r in rows}


def entry_tags(conn: sqlite3.Connection, entry_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id "
        "WHERE et.entry_id = ? ORDER BY t.name",
        (entry_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def refresh_fts(conn: sqlite3.Connection, entry_id: int) -> None:
    body = "\n\n".join(
        c for c in entry_contents(conn, entry_id).values() if c.strip()
    )
    tags = " ".join(entry_tags(conn, entry_id))
    if tags:
        body = f"{body}\n\n{tags}"
    conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (entry_id,))
    conn.execute("INSERT INTO entries_fts (rowid, body) VALUES (?, ?)", (entry_id, body))


def save_section(conn: sqlite3.Connection, day: date, key: str, content: str) -> None:
    with tx(conn):
        existing = get_entry(conn, day)
        if existing is None and not content.strip():
            return  # don't create empty entries
        entry_id = existing["id"] if existing else ensure_entry(conn, day)
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO entry_sections (entry_id, section_key, content, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (entry_id, section_key) DO UPDATE SET "
            "content = excluded.content, updated_at = excluded.updated_at",
            (entry_id, key, content, now),
        )
        touch_entry(conn, entry_id)
        refresh_fts(conn, entry_id)


def set_meta(conn: sqlite3.Connection, day: date, mood: int | None, energy: int | None) -> None:
    with tx(conn):
        entry_id = ensure_entry(conn, day)
        conn.execute(
            "UPDATE entries SET mood = ?, energy = ?, updated_at = ? WHERE id = ?",
            (mood, energy, utc_now_iso(), entry_id),
        )


def parse_tags(raw: str) -> list[str]:
    seen: dict[str, str] = {}
    for part in raw.replace("#", "").split(","):
        name = " ".join(part.split()).lower()
        if name and name not in seen:
            seen[name] = name
    return list(seen.values())


def set_tags(conn: sqlite3.Connection, day: date, names: list[str]) -> list[str]:
    with tx(conn):
        existing = get_entry(conn, day)
        if existing is None and not names:
            return []
        entry_id = existing["id"] if existing else ensure_entry(conn, day)
        conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
        for name in names:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?, ?)", (entry_id, tag_id)
            )
        touch_entry(conn, entry_id)
        refresh_fts(conn, entry_id)
        return entry_tags(conn, entry_id)


def all_tags(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT t.name FROM tags t WHERE EXISTS (SELECT 1 FROM entry_tags et WHERE et.tag_id = t.id) "
        "ORDER BY t.name"
    ).fetchall()
    return [r["name"] for r in rows]


# ---------- todos ----------

def todos_for_day(conn: sqlite3.Connection, day: date) -> list[dict]:
    rows = conn.execute(
        f"SELECT * FROM todos WHERE {VISIBLE_ON_DAY} ORDER BY created_day, id",
        {"d": str(day)},
    ).fetchall()
    goal_titles = {r["id"]: r["text"] for r in conn.execute("SELECT id, text FROM goals")}
    out = []
    for r in rows:
        created = date.fromisoformat(r["created_day"])
        out.append(
            {
                "id": r["id"],
                "text": r["text"],
                "done": r["completed_day"] == str(day),
                "carried_days": (day - created).days,
                "created_day": r["created_day"],
                "from_review": r["source_review_id"],
                "goal": goal_titles.get(r["source_goal_id"]) if r["source_goal_id"] else None,
            }
        )
    return out


def yesterday_report(conn: sqlite3.Connection, day: date) -> list[dict]:
    """Todos that were open on the previous day, with what happened to them."""
    y = day - timedelta(days=1)
    rows = conn.execute(
        f"SELECT * FROM todos WHERE {VISIBLE_ON_DAY} ORDER BY created_day, id",
        {"d": str(y)},
    ).fetchall()
    out = []
    for r in rows:
        # Report what was true as of `day`. Something dropped days later was simply not done
        # yesterday; calling it "dropped" here would rewrite every earlier report.
        if r["completed_day"] == str(y):
            status = "done"
        elif r["completed_day"] is not None:
            status = "done_later"
        elif r["dropped_day"] == str(day):
            status = "dropped"
        elif r["dropped_day"] is not None:
            status = "dropped_later"
        else:
            status = "open"
        out.append({"text": r["text"], "status": status, "completed_day": r["completed_day"]})
    return out


def add_todo(conn: sqlite3.Connection, day: date, text: str) -> None:
    text = " ".join(text.split())
    if not text:
        return
    with tx(conn):
        conn.execute(
            "INSERT INTO todos (text, created_day, created_at) VALUES (?, ?, ?)",
            (text, str(day), utc_now_iso()),
        )
        entry_id = ensure_entry(conn, day)
        touch_entry(conn, entry_id)


def add_todo_from_review(conn: sqlite3.Connection, day: date, text: str, review_id: int) -> int | None:
    """A distilled review action put on a (usually future) day's list. No entry row is created for
    that day; it appears once the day comes and you write in it."""
    text = " ".join(text.split())
    if not text:
        return None
    cur = conn.execute(
        "INSERT INTO todos (text, created_day, created_at, source_review_id) VALUES (?, ?, ?, ?)",
        (text, str(day), utc_now_iso(), review_id),
    )
    return cur.lastrowid


def todos_from_review(conn: sqlite3.Connection, review_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM todos WHERE source_review_id = ? ORDER BY id", (review_id,)
    ).fetchall()


def edit_todo(conn: sqlite3.Connection, todo_id: int, day: date, text: str) -> None:
    text = " ".join(text.split())
    if not text:
        return
    with tx(conn):
        conn.execute("UPDATE todos SET text = ? WHERE id = ?", (text, todo_id))
        touch_entry(conn, ensure_entry(conn, day))


def todos_dropped_on(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, text FROM todos WHERE dropped_day = ? ORDER BY id", (str(day),)
    ).fetchall()


def undrop_todo(conn: sqlite3.Connection, todo_id: int, day: date) -> None:
    """Undo only works on the day of the drop, so earlier reports are never rewritten."""
    with tx(conn):
        conn.execute(
            "UPDATE todos SET dropped_day = NULL WHERE id = ? AND dropped_day = ?", (todo_id, str(day))
        )
        touch_entry(conn, ensure_entry(conn, day))


def toggle_todo(conn: sqlite3.Connection, todo_id: int, day: date) -> None:
    with tx(conn):
        row = conn.execute("SELECT completed_day FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if row is None:
            return
        new_value = None if row["completed_day"] == str(day) else str(day)
        conn.execute("UPDATE todos SET completed_day = ? WHERE id = ?", (new_value, todo_id))
        touch_entry(conn, ensure_entry(conn, day))


def drop_todo(conn: sqlite3.Connection, todo_id: int, day: date) -> None:
    with tx(conn):
        conn.execute(
            "UPDATE todos SET dropped_day = ? WHERE id = ? AND completed_day IS NULL",
            (str(day), todo_id),
        )
        touch_entry(conn, ensure_entry(conn, day))


def entry_days(conn: sqlite3.Connection) -> list[str]:
    return [r["day"] for r in conn.execute("SELECT day FROM entries ORDER BY day").fetchall()]


# ---------- history & search ----------

def list_entries(conn: sqlite3.Connection, limit: int = 500) -> list[dict]:
    order = [s["key"] for s in conn.execute("SELECT key FROM sections ORDER BY active DESC, sort")]
    rows = conn.execute(
        "SELECT id, day, mood, energy FROM entries ORDER BY day DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        contents = entry_contents(conn, r["id"])
        ordered = [contents[k] for k in order if contents.get(k, "").strip()]
        body = " ".join(ordered)
        first = next((ln.strip() for c in ordered for ln in c.splitlines() if ln.strip()), "")
        out.append(
            {
                "day": r["day"],
                "mood": r["mood"],
                "energy": r["energy"],
                "words": len(body.split()),
                "snippet": first[:180],
                "tags": entry_tags(conn, r["id"]),
            }
        )
    return out


def _fts_query(q: str) -> str:
    # Each word becomes a quoted prefix match, so "procrastinat" finds "procrastination".
    terms = [t.replace('"', "") for t in q.split()]
    return " ".join(f'"{t}"*' for t in terms if t)


def search(conn: sqlite3.Connection, q: str, limit: int = 200) -> list[dict]:
    query = _fts_query(q)
    if not query:
        return []
    rows = conn.execute(
        """
        SELECT e.day, e.mood, e.energy,
               snippet(entries_fts, 0, char(2), char(3), '…', 24) AS snip
        FROM entries_fts JOIN entries e ON e.id = entries_fts.rowid
        WHERE entries_fts MATCH ?
        ORDER BY e.day DESC LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- profile versions ----------

def latest_profile(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM profile_versions ORDER BY version DESC LIMIT 1").fetchone()


def profile_by_id(conn: sqlite3.Connection, profile_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM profile_versions WHERE id = ?", (profile_id,)).fetchone()


def profile_versions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, version, covers_from, covers_through, entries_count, created_at "
        "FROM profile_versions ORDER BY version DESC"
    ).fetchall()


# ---------- long-term goals ----------
# Same visibility rule as todos: a goal shows on day D from the day it was added until it is
# achieved (shown checked on that day) or dropped.

GOAL_VISIBLE_ON_DAY = """
    created_day <= :d
    AND (done_day IS NULL OR done_day >= :d)
    AND (dropped_day IS NULL OR dropped_day > :d)
"""


def goals_for_day(conn: sqlite3.Connection, day: date) -> list[dict]:
    rows = conn.execute(
        f"SELECT * FROM goals WHERE {GOAL_VISIBLE_ON_DAY} ORDER BY created_day, id", {"d": str(day)}
    ).fetchall()
    return [
        {"id": r["id"], "text": r["text"], "done": r["done_day"] == str(day), "created_day": r["created_day"]}
        for r in rows
    ]


def active_goals(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    """Goals still being pursued as of `day` (not achieved or dropped by then)."""
    return conn.execute(
        "SELECT * FROM goals WHERE created_day <= ? AND (done_day IS NULL OR done_day > ?) "
        "AND (dropped_day IS NULL OR dropped_day > ?) ORDER BY created_day, id",
        (str(day), str(day), str(day)),
    ).fetchall()


def goal_events(conn: sqlite3.Connection, day: date) -> list[str]:
    """What happened to long-term goals on this day, for the model and the export."""
    d = str(day)
    events = []
    for r in conn.execute("SELECT * FROM goals WHERE created_day = ? OR done_day = ? OR dropped_day = ? ORDER BY id",
                          (d, d, d)):
        if r["created_day"] == d:
            events.append(f"added: {r['text']}")
        if r["done_day"] == d:
            events.append(f"achieved: {r['text']}")
        if r["dropped_day"] == d:
            events.append(f"dropped: {r['text']}")
    return events


def goals_dropped_on(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, text FROM goals WHERE dropped_day = ? ORDER BY id", (str(day),)).fetchall()


def add_goal(conn: sqlite3.Connection, day: date, text: str) -> None:
    text = " ".join(text.split())
    if not text:
        return
    with tx(conn):
        conn.execute("INSERT INTO goals (text, created_day, created_at) VALUES (?, ?, ?)",
                     (text, str(day), utc_now_iso()))
        touch_entry(conn, ensure_entry(conn, day))


def toggle_goal(conn: sqlite3.Connection, goal_id: int, day: date) -> None:
    with tx(conn):
        row = conn.execute("SELECT done_day FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            return
        new_value = None if row["done_day"] == str(day) else str(day)
        conn.execute("UPDATE goals SET done_day = ? WHERE id = ?", (new_value, goal_id))
        touch_entry(conn, ensure_entry(conn, day))


def drop_goal(conn: sqlite3.Connection, goal_id: int, day: date) -> None:
    with tx(conn):
        conn.execute("UPDATE goals SET dropped_day = ? WHERE id = ? AND done_day IS NULL", (str(day), goal_id))
        touch_entry(conn, ensure_entry(conn, day))


def undrop_goal(conn: sqlite3.Connection, goal_id: int, day: date) -> None:
    with tx(conn):
        conn.execute("UPDATE goals SET dropped_day = NULL WHERE id = ? AND dropped_day = ?", (goal_id, str(day)))
        touch_entry(conn, ensure_entry(conn, day))


def edit_goal(conn: sqlite3.Connection, goal_id: int, day: date, text: str) -> None:
    text = " ".join(text.split())
    if not text:
        return
    with tx(conn):
        conn.execute("UPDATE goals SET text = ? WHERE id = ?", (text, goal_id))
        touch_entry(conn, ensure_entry(conn, day))


def add_todo_for_goal(conn: sqlite3.Connection, day: date, goal_id: int, text: str) -> None:
    """A step toward a goal, put on that day's list."""
    text = " ".join(text.split())
    if not text:
        return
    with tx(conn):
        conn.execute(
            "INSERT INTO todos (text, created_day, created_at, source_goal_id) VALUES (?, ?, ?, ?)",
            (text, str(day), utc_now_iso(), goal_id),
        )
        touch_entry(conn, ensure_entry(conn, day))
