"""Shared Jinja2 templates object and filters."""
import re
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from .days import local_day, long_date, short_date

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["long_date"] = long_date
templates.env.filters["short_date"] = short_date
templates.env.filters["local_day"] = local_day  # UTC timestamp -> local date


def highlight(snippet: str) -> Markup:
    """FTS snippets use \\x02/\\x03 as match markers; escape everything else."""
    safe = str(escape(snippet or ""))
    return Markup(safe.replace("\x02", "<mark>").replace("\x03", "</mark>"))


templates.env.filters["highlight"] = highlight


# ---- LLM output rendering: Markdown (raw HTML disabled) with [YYYY-MM-DD] citations linked ----
_md = MarkdownIt("js-default", {"breaks": True})  # single newlines stay line breaks (**Read:** / **Challenge:** ...)
_DATE = r"\d{4}-\d{2}-\d{2}"
_CITATION = re.compile(rf"\[({_DATE}(?:\s*,\s*{_DATE})*)\]")
_Q_CITATION = re.compile(r"\[Q(\d+)((?:\s*,\s*[^\]\[]*)?)\]")


def _link_citations(text: str) -> str:
    def repl(m: re.Match) -> str:
        dates = [d.strip() for d in m.group(1).split(",")]
        return "[" + ", ".join(f"[{d}](/day/{d})" for d in dates) + "]"

    text = _CITATION.sub(repl, text)
    # Answers to questions: [Q12, 2026-10-15] -> link the Q12 part to the question.
    return _Q_CITATION.sub(lambda m: f"[[Q{m.group(1)}](/questions/{m.group(1)}){m.group(2)}]", text)


def review_md(text: str) -> Markup:
    return Markup(_md.render(_link_citations(text or "")))


templates.env.filters["review_md"] = review_md
