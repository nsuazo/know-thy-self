"""Shared Jinja2 templates object and filters."""
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .days import long_date, short_date

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["long_date"] = long_date
templates.env.filters["short_date"] = short_date


def highlight(snippet: str) -> Markup:
    """FTS snippets use \\x02/\\x03 as match markers; escape everything else."""
    safe = str(escape(snippet or ""))
    return Markup(safe.replace("\x02", "<mark>").replace("\x03", "</mark>"))


templates.env.filters["highlight"] = highlight
