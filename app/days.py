"""Logical-day handling. A 'day' rolls over at DAY_CUTOFF_HOUR local time, not midnight."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .config import settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.tz))


def logical_today() -> date:
    return (now_local() - timedelta(hours=settings.day_cutoff_hour)).date()


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid date")


def local_day(iso_utc: str) -> date:
    """The local calendar date of a stored UTC timestamp (created_at etc.)."""
    return datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(settings.tz)).date()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def long_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def short_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d:%a} {d:%b} {d.day}, {d.year}"
