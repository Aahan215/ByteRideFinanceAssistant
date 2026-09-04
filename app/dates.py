"""Relative date resolution, anchored to the DATA, not the wall clock.

If the fictitious company's ledger ends in March and you demo in September,
wall-clock "last month" returns zero rows for every question. This is the
single most common way this class of demo dies.
"""
from __future__ import annotations
from datetime import date
from dateutil.relativedelta import relativedelta
from app.spec import DateRange

_UNIT = {
    "day": lambda n: relativedelta(days=n),
    "week": lambda n: relativedelta(weeks=n),
    "month": lambda n: relativedelta(months=n),
    "quarter": lambda n: relativedelta(months=3 * n),
    "year": lambda n: relativedelta(years=n),
}


def _floor(d: date, unit: str) -> date:
    if unit == "day":
        return d
    if unit == "week":
        return d - relativedelta(days=d.weekday())
    if unit == "month":
        return d.replace(day=1)
    if unit == "quarter":
        return d.replace(month=3 * ((d.month - 1) // 3) + 1, day=1)
    return d.replace(month=1, day=1)


def resolve(dr: DateRange, anchor: date) -> tuple[date | None, date | None]:
    """Return an inclusive-start, exclusive-end window. None,None = all time."""
    if dr.kind == "all_time":
        return None, None
    if dr.kind == "absolute":
        s = date.fromisoformat(dr.start) if dr.start else None
        e = date.fromisoformat(dr.end) if dr.end else None
        # make end exclusive so BETWEEN-style off-by-one bugs cannot happen
        return s, (e + relativedelta(days=1)) if e else None

    unit = dr.unit or "month"
    end_period = _floor(anchor, unit) + _UNIT[unit](dr.offset + 1)
    start_period = end_period - _UNIT[unit](max(dr.periods, 1))
    return start_period, end_period


def describe(start, end) -> str:
    if not start and not end:
        return "all time"
    return f"{start.isoformat()} to {(end - relativedelta(days=1)).isoformat()}"
