"""Markdown export: one file per day under DATA_DIR/export/YYYY/YYYY-MM-DD.md."""
import logging
import sqlite3
from datetime import date

from . import repo
from .config import settings
from .days import long_date

log = logging.getLogger(__name__)


def _todos_visible(conn: sqlite3.Connection, day: date) -> list[dict]:
    return repo.todos_for_day(conn, day)


def entry_markdown(conn: sqlite3.Connection, entry: sqlite3.Row) -> str:
    day = date.fromisoformat(entry["day"])
    contents = repo.entry_contents(conn, entry["id"])
    tags = repo.entry_tags(conn, entry["id"])

    fm = ["---", f"date: {entry['day']}"]
    if entry["mood"] is not None:
        fm.append(f"mood: {entry['mood']}")
    if entry["energy"] is not None:
        fm.append(f"energy: {entry['energy']}")
    if tags:
        fm.append("tags: [" + ", ".join(tags) + "]")
    fm.append("---")

    parts = ["\n".join(fm), f"# {long_date(day)}"]
    for s in repo.sections_for_entry(conn, entry["id"]):
        body = ""
        if s["kind"] == "goals":
            lines = [f"- [{'x' if g['done'] else ' '}] {g['text']}" + (" _(achieved)_" if g["done"] else "")
                     for g in repo.goals_for_day(conn, day)]
            body = "\n".join(lines)
        elif s["kind"] == "todos":
            lines = []
            for t in _todos_visible(conn, day):
                suffix = f" _(carried {t['carried_days']}d)_" if t["carried_days"] > 0 else ""
                if t["from_review"]:
                    suffix += " _(from a review)_"
                if t["goal"]:
                    suffix += f" _(toward: {t['goal']})_"
                lines.append(f"- [{'x' if t['done'] else ' '}] {t['text']}{suffix}")
            body = "\n".join(lines)
        elif s["kind"] == "yesterday":
            report = repo.yesterday_report(conn, day)
            lines = []
            labels = {"done": "done", "done_later": "finished later", "dropped": "dropped",
                      "dropped_later": "not done, dropped later", "open": "not done"}
            for r in report:
                mark = "x" if r["status"] == "done" else " "
                lines.append(f"- [{mark}] {r['text']} — {labels[r['status']]}")
            text = contents.get(s["key"], "").strip()
            body = "\n".join(lines) + ("\n\n" + text if text and lines else text)
        else:
            body = contents.get(s["key"], "").strip()
        if body:
            parts.append(f"## {s['label']}\n\n{body}")
    return "\n\n".join(parts) + "\n"


def export_all(conn: sqlite3.Connection) -> int:
    """Write every entry; only touches files whose content changed. Returns files written."""
    written = 0
    for entry in conn.execute("SELECT * FROM entries ORDER BY day").fetchall():
        md = entry_markdown(conn, entry)
        path = settings.export_dir / entry["day"][:4] / f"{entry['day']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == md:
            continue
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(path)
        written += 1
    log.info("Markdown export complete: %d file(s) written", written)
    return written
