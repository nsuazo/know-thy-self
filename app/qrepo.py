"""Data access for the Questions page: questions, answers, the queue, and settings."""
import json
import sqlite3
from datetime import date, timedelta

from .days import utc_now_iso
from .db import tx

CATEGORIES: dict[str, str] = {
    "history": "Personal history",
    "identity": "Identity",
    "values": "Values",
    "meaning": "Meaning",
    "strengths": "Strengths",
    "weaknesses": "Weaknesses",
    "others_view": "How others see you",
    "relationships": "Relationships",
    "social_prep": "Social prep",
    "work": "Work",
    "task_breakdown": "Task breakdown",
    "habits": "Habits",
    "fears": "Fears",
    "goals": "Goals",
}
KINDS = ("open", "scale", "choice", "rank", "claim_check")
CLAIM_VERDICTS = {"agree": "Agree", "partly": "Partly", "disagree": "Disagree"}
LATER_DAYS = 30
REASK_AFTER_DAYS = 60


# ---------- settings ----------

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def focus(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "questions_focus").strip()


def muted(conn: sqlite3.Connection) -> list[str]:
    try:
        return [c for c in json.loads(get_setting(conn, "questions_muted", "[]")) if c in CATEGORIES]
    except ValueError:
        return []


# ---------- reading ----------

def get_question(conn: sqlite3.Connection, qid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()


def answers_for(conn: sqlite3.Connection, qid: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM answers WHERE question_id = ? ORDER BY day, id", (qid,)).fetchall()


def followups_of(conn: sqlite3.Connection, qid: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM questions WHERE parent_id = ? ORDER BY id", (qid,)).fetchall()


def _interleave(a: list, b: list) -> list:
    out = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def queue(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    """Questions waiting to be answered today, in asking order.

    Follow-ups first (they belong to something you just answered), then recurring questions that
    have come due again, then the model's questions alternated with the starter set.
    """
    mutes = set(muted(conn))
    rows = [
        r for r in conn.execute(
            "SELECT q.*, (SELECT COUNT(*) FROM answers a WHERE a.question_id = q.id) AS n_answers "
            "FROM questions q WHERE q.status = 'waiting' AND (q.available_from IS NULL OR q.available_from <= ?) "
            "ORDER BY q.sort, q.id",
            (str(today),),
        ).fetchall()
        if r["category"] not in mutes
    ]
    followups = [r for r in rows if r["source"] == "followup"]
    due_again = [r for r in rows if r["source"] != "followup" and r["n_answers"] > 0]
    rest = [r for r in rows if r["source"] != "followup" and r["n_answers"] == 0]
    llm = [r for r in rest if r["source"] == "llm"]
    seed = [r for r in rest if r["source"] != "llm"]
    return followups + due_again + _interleave(llm, seed)


def llm_waiting(conn: sqlite3.Connection, today: date) -> int:
    return sum(1 for r in queue(conn, today) if r["source"] == "llm")


def answered_list(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT q.*, MAX(a.day) AS last_day, COUNT(a.id) AS n_answers FROM questions q "
        "JOIN answers a ON a.question_id = q.id GROUP BY q.id ORDER BY last_day DESC, MAX(a.id) DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def skipped_list(conn: sqlite3.Connection, today: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM questions WHERE status IN ('never', 'bad') "
        "OR (status = 'waiting' AND available_from > ? AND id NOT IN (SELECT question_id FROM answers)) "
        "ORDER BY updated_at DESC LIMIT 100",
        (str(today),),
    ).fetchall()


def category_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {c: 0 for c in CATEGORIES}
    for r in conn.execute(
        "SELECT q.category, COUNT(a.id) AS n FROM questions q JOIN answers a ON a.question_id = q.id GROUP BY q.category"
    ):
        counts[r["category"]] = counts.get(r["category"], 0) + r["n"]
    return counts


def answer_rows(conn: sqlite3.Connection, where: str = "1", params: tuple = ()) -> list[sqlite3.Row]:
    """Answers joined with their question, oldest first."""
    return conn.execute(
        "SELECT a.*, q.text AS q_text, q.category, q.kind, q.options, q.claim "
        f"FROM answers a JOIN questions q ON q.id = a.question_id WHERE {where} ORDER BY a.day, a.id",
        params,
    ).fetchall()


def max_answer_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM answers").fetchone()[0]


# ---------- writing ----------

def save_answer(conn: sqlite3.Connection, qid: int, day: date, text: str, value) -> int:
    q = get_question(conn, qid)
    now = utc_now_iso()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO answers (question_id, day, text, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (qid, str(day), text.strip(), json.dumps(value) if value is not None else None, now, now),
        )
        if q["recurring_days"]:
            conn.execute(
                "UPDATE questions SET status = 'waiting', available_from = ?, updated_at = ? WHERE id = ?",
                (str(day + timedelta(days=q["recurring_days"])), now, qid),
            )
        else:
            conn.execute(
                "UPDATE questions SET status = 'answered', available_from = NULL, updated_at = ? WHERE id = ?",
                (now, qid),
            )
        return cur.lastrowid


def update_answer(conn: sqlite3.Connection, answer_id: int, text: str, value) -> None:
    conn.execute(
        "UPDATE answers SET text = ?, value = ?, updated_at = ? WHERE id = ?",
        (text.strip(), json.dumps(value) if value is not None else None, utc_now_iso(), answer_id),
    )


def mark_later(conn: sqlite3.Connection, qid: int, today: date) -> None:
    conn.execute(
        "UPDATE questions SET available_from = ?, updated_at = ? WHERE id = ? AND status = 'waiting'",
        (str(today + timedelta(days=LATER_DAYS)), utc_now_iso(), qid),
    )


def mark_never(conn: sqlite3.Connection, qid: int) -> None:
    conn.execute("UPDATE questions SET status = 'never', updated_at = ? WHERE id = ?", (utc_now_iso(), qid))


def mark_bad(conn: sqlite3.Connection, qid: int, reason: str) -> None:
    conn.execute(
        "UPDATE questions SET status = 'bad', bad_reason = ?, updated_at = ? WHERE id = ?",
        (reason.strip()[:500] or None, utc_now_iso(), qid),
    )


def restore(conn: sqlite3.Connection, qid: int) -> None:
    """Undo Later / Never / Bad: back into the queue now."""
    conn.execute(
        "UPDATE questions SET status = CASE WHEN EXISTS (SELECT 1 FROM answers WHERE question_id = questions.id) "
        "AND recurring_days IS NULL THEN 'answered' ELSE 'waiting' END, "
        "available_from = NULL, bad_reason = NULL, updated_at = ? WHERE id = ?",
        (utc_now_iso(), qid),
    )


def reask(conn: sqlite3.Connection, qid: int, today: date) -> bool:
    """Put an answered question back in the queue if its last answer is old enough."""
    last = conn.execute("SELECT MAX(day) FROM answers WHERE question_id = ?", (qid,)).fetchone()[0]
    if last is None or date.fromisoformat(last) > today - timedelta(days=REASK_AFTER_DAYS):
        return False
    conn.execute(
        "UPDATE questions SET status = 'waiting', available_from = NULL, updated_at = ? "
        "WHERE id = ? AND status = 'answered'",
        (utc_now_iso(), qid),
    )
    return True


def add_question(
    conn: sqlite3.Connection, *, text: str, category: str, kind: str, options: list | None,
    claim: str | None, why: str | None, source: str, parent_id: int | None = None,
) -> int:
    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 10 FROM questions").fetchone()[0]
    now = utc_now_iso()
    cur = conn.execute(
        "INSERT INTO questions (text, category, kind, options, claim, why, source, parent_id, sort, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (text, category, kind, json.dumps(options) if options else None, claim, why, source, parent_id, sort, now, now),
    )
    return cur.lastrowid


# ---------- display helpers ----------

def options_of(row) -> list:
    try:
        return json.loads(row["options"]) if row["options"] else []
    except ValueError:
        return []


def value_of(row):
    try:
        return json.loads(row["value"]) if row["value"] else None
    except ValueError:
        return None


def describe_value(kind: str, options: list, value) -> str:
    """Plain-text rendering of a structured answer, for the model and the Markdown export."""
    if value is None:
        return ""
    if kind == "scale":
        lo, hi = (options + ["", ""])[:2]
        return f"{value}/5 (1 = {lo}, 5 = {hi})" if lo or hi else f"{value}/5"
    if kind == "rank" and isinstance(value, list):
        return "Ranked: " + " > ".join(str(v) for v in value)
    if kind == "claim_check":
        return f"Verdict: {CLAIM_VERDICTS.get(value, value)}"
    return f"Chose: {value}"
