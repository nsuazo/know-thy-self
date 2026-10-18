"""Generates questions for the Questions page, and follow-ups to an answer.

The model answers in JSON. Parsing is lenient (code fences, stray prose around the JSON); if it still
fails, the model is asked once to repeat its answer as valid JSON.
"""
import json
import logging
import re
import sqlite3
from datetime import date, timedelta

from .. import periods, qrepo, repo
from ..days import logical_today
from . import client
from .client import LLMError
from .context import _build, render_answers
from .prompts import SYSTEM_PROMPT, followup_task, questions_task

log = logging.getLogger(__name__)

BATCH_SIZE = 5
QUESTION_DAYS = 30        # recent entries the generator reads verbatim
ASKED_LIST_MAX = 120      # earlier question texts listed so they are not repeated
BAD_LIST_MAX = 20
TEMPERATURE = 0.8


# ---------- parsing ----------

def _extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    raise ValueError("no JSON found")


def _clean_options(kind: str, options) -> list[str] | None:
    if not isinstance(options, list):
        return None
    opts = [" ".join(str(o).split())[:120] for o in options if str(o).strip()]
    limits = {"scale": (2, 2), "choice": (2, 6), "rank": (3, 7)}
    lo, hi = limits.get(kind, (0, 0))
    return opts if lo <= len(opts) <= hi else None


def validate(item, *, has_profile: bool, muted: set[str], seen: set[str]) -> dict | None:
    """One generated question, cleaned up, or None if unusable."""
    if not isinstance(item, dict):
        return None
    text = " ".join(str(item.get("question") or "").split())
    if not (5 <= len(text) <= 600):
        return None
    norm = text.lower().rstrip("?. ")
    if norm in seen:
        return None
    category = str(item.get("category") or "").strip().lower()
    if category not in qrepo.CATEGORIES:
        category = "identity"
    if category in muted:
        return None
    kind = str(item.get("kind") or "open").strip().lower()
    if kind not in qrepo.KINDS:
        kind = "open"
    claim = " ".join(str(item.get("claim") or "").split())[:600] or None
    options = None
    if kind == "claim_check":
        if not (has_profile and claim):
            return None
    elif kind in ("scale", "choice", "rank"):
        options = _clean_options(kind, item.get("options"))
        if options is None:
            kind = "open"
    why = " ".join(str(item.get("why") or "").split())[:400] or None
    seen.add(norm)
    return {"text": text, "category": category, "kind": kind, "options": options,
            "claim": claim if kind == "claim_check" else None, "why": why}


async def _chat_json(messages: list[dict]):
    """Chat, parse JSON; on a parse failure ask once for the same answer as valid JSON."""
    result = await client.chat(messages, temperature=TEMPERATURE)
    try:
        return _extract_json(result.content)
    except ValueError:
        log.warning("Question output was not valid JSON; asking once more")
    retry = messages + [
        {"role": "assistant", "content": result.content},
        {"role": "user", "content": "That was not valid JSON. Repeat the same content as valid JSON only, "
                                    "with no other text."},
    ]
    result = await client.chat(retry, temperature=0.2)
    try:
        return _extract_json(result.content)
    except ValueError as exc:
        raise LLMError("The model did not return valid JSON for the questions, even after a retry. "
                       "Try again.") from exc


# ---------- batches ----------

def _all_question_texts(conn: sqlite3.Connection) -> list[str]:
    return [r["text"] for r in conn.execute("SELECT text FROM questions ORDER BY id")]


def build_questions_messages(conn: sqlite3.Connection, today: date, category: str | None) -> list[dict]:
    latest = repo.latest_profile(conn)
    profile_text = latest["content"] if latest else None
    since = today - timedelta(days=QUESTION_DAYS - 1)
    answers = qrepo.answer_rows(conn, "1")
    body, *_ = _build(
        conn,
        profile_text=profile_text,
        verbatim_start=periods.monday_of(since),
        end=today,
        today=today,
        include_before=False,
        answers_text=render_answers(answers[-150:]) or None,
    )
    counts = qrepo.category_counts(conn)
    muted = qrepo.muted(conn)
    reaskable = [
        (r["id"], r["text"], r["last_day"]) for r in qrepo.answered_list(conn, 500)
        if r["recurring_days"] is None and r["status"] == "answered"
        and r["last_day"] <= str(today - timedelta(days=qrepo.REASK_AFTER_DAYS))
    ][:15]
    bad = [(r["text"], r["bad_reason"] or "") for r in conn.execute(
        "SELECT text, bad_reason FROM questions WHERE status = 'bad' ORDER BY updated_at DESC LIMIT ?", (BAD_LIST_MAX,))]
    task = questions_task(
        today=today,
        n=BATCH_SIZE,
        focus=qrepo.focus(conn),
        has_profile=latest is not None,
        counts=[(k, v, counts.get(k, 0)) for k, v in qrepo.CATEGORIES.items() if k not in muted],
        pinned=(category, qrepo.CATEGORIES[category]) if category in qrepo.CATEGORIES else None,
        muted=muted,
        asked=_all_question_texts(conn)[-ASKED_LIST_MAX:],
        bad=bad,
        reaskable=reaskable,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body + "\n\n---\n\n" + task},
    ]


async def generate_batch(conn: sqlite3.Connection, category: str | None = None, today: date | None = None) -> int:
    today = today or logical_today()
    messages = build_questions_messages(conn, today, category)
    data = await _chat_json(messages)
    if isinstance(data, dict):
        data = data.get("questions", [data])
    if not isinstance(data, list):
        raise LLMError("The model returned questions in an unexpected shape. Try again.")

    has_profile = repo.latest_profile(conn) is not None
    muted = set(qrepo.muted(conn))
    seen = {t.lower().rstrip("?. ") for t in _all_question_texts(conn)}
    added = reasked = 0
    for item in data[:BATCH_SIZE + 2]:
        if added + reasked >= BATCH_SIZE:
            break
        if isinstance(item, dict) and item.get("repeat_of_id") is not None and not item.get("question"):
            try:
                qid = int(item["repeat_of_id"])
            except (TypeError, ValueError):
                continue
            q = qrepo.get_question(conn, qid)
            if reasked == 0 and q is not None and q["recurring_days"] is None and qrepo.reask(conn, qid, today):
                reasked += 1
            continue
        clean = validate(item, has_profile=has_profile, muted=muted, seen=seen)
        if clean:
            qrepo.add_question(conn, source="llm", **clean)
            added += 1
    if added + reasked == 0:
        raise LLMError("The model's questions were all unusable (duplicates, muted categories or malformed). "
                       "Try again.")
    log.info("Questions: %d new, %d re-asked", added, reasked)
    return added + reasked


async def generate_followup(conn: sqlite3.Connection, qid: int, today: date | None = None) -> int:
    today = today or logical_today()
    q = qrepo.get_question(conn, qid)
    if q is None:
        raise LLMError("That question no longer exists.")
    if not qrepo.answers_for(conn, qid):
        raise LLMError("Answer the question first, then ask for a follow-up.")
    chain = [qid]
    parent = q["parent_id"]
    while parent and len(chain) < 6:   # include the questions this one follows from
        chain.insert(0, parent)
        p = qrepo.get_question(conn, parent)
        parent = p["parent_id"] if p else None
    marks = ",".join("?" * len(chain))
    answers = qrepo.answer_rows(conn, f"a.question_id IN ({marks})", tuple(chain))
    latest = repo.latest_profile(conn)
    since = today - timedelta(days=13)
    body, *_ = _build(
        conn,
        profile_text=latest["content"] if latest else None,
        verbatim_start=periods.monday_of(since),
        end=today,
        today=today,
        include_before=False,
        answers_text=render_answers(answers),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body + "\n\n---\n\n" + followup_task(qid, today)},
    ]
    data = await _chat_json(messages)
    if isinstance(data, list) and data:
        data = data[0]
    clean = validate(
        {**(data if isinstance(data, dict) else {}), "category": q["category"]},
        has_profile=False, muted=set(), seen={t.lower().rstrip("?. ") for t in _all_question_texts(conn)},
    )
    if clean is None:
        raise LLMError("The model's follow-up was unusable. Try again.")
    return qrepo.add_question(conn, source="followup", parent_id=qid, **clean)
