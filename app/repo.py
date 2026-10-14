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

def get_sections(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sections WHERE active = 1 ORDER BY sort").fetchall()


def section_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sections WHERE key = ? AND active = 1", (key,)).fetchone()


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
        if r["completed_day"] == str(y):
            status = "done"
        elif r["completed_day"] is not None:
            status = "done_later"
        elif r["dropped_day"] is not None:
            status = "dropped"
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
    order = [s["key"] for s in get_sections(conn)]
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
