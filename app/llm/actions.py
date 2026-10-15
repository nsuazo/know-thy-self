"""Pulls the "## Distilled actions" section out of a review.

The model is asked for lines like "- ACTION: Email Sam the draft". Small deviations (bold labels,
numbered lists, plain bullets) are tolerated; if nothing usable is found, the review is shown as is.
"""
import re

MAX_ACTIONS = 3
_SECTION = re.compile(r"^#{2,3}\s*Distilled actions\s*:?\s*$", re.M | re.I)
_NEXT_HEADING = re.compile(r"^#{1,3}\s", re.M)
_ACTION = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\*\*|__)?ACTION\s*:?\s*(?:\*\*|__)?\s*:?\s*(.+?)\s*$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")


def _clean(text: str) -> str:
    text = re.sub(r"\s*\[\d{4}-\d{2}-\d{2}(?:\s*,\s*\d{4}-\d{2}-\d{2})*\]", "", text)  # citations don't belong in a todo
    text = text.strip().strip("*_").strip()
    return " ".join(text.split())[:300]


def split_actions(content: str) -> tuple[str, list[str]]:
    """(review text without the actions section, actions). Unchanged text and [] if none found."""
    m = _SECTION.search(content or "")
    if not m:
        return content, []
    tail = content[m.end():]
    nxt = _NEXT_HEADING.search(tail)
    section = tail[: nxt.start()] if nxt else tail
    lines = [ln for ln in section.splitlines() if ln.strip()]
    found = [_clean(mm.group(1)) for ln in lines if (mm := _ACTION.match(ln))]
    if not found:
        found = [_clean(mm.group(1)) for ln in lines if (mm := _BULLET.match(ln))]
    actions = [a for a in found if a][:MAX_ACTIONS]
    if not actions:
        return content, []
    rest = tail[nxt.start():] if nxt else ""
    body = content[: m.start()].rstrip() + ("\n\n" + rest if rest else "")
    return body.rstrip(), actions
