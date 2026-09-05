"""Deterministic date-phrase extraction.

Date handling is where small models fail most often, and English date phrases
are regular enough to parse with rules. So we resolve them BEFORE the model
sees the question and hand it a solved date_range, which shrinks what the 8B
model has to get right to: dataset, metric, filters, group_by.

Everything here is testable without a model, and every rule is one regex.
"""
from __future__ import annotations
import re
from app.spec import DateRange

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})

UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week",
         "month": "month", "months": "month", "quarter": "quarter",
         "quarters": "quarter", "year": "year", "years": "year"}

WORD_NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}


def _n(tok: str) -> int:
    return int(tok) if tok.isdigit() else WORD_NUM.get(tok.lower(), 1)


# Ordered most-specific first. Each returns (DateRange, matched_text).
def extract(question: str) -> tuple[DateRange | None, str | None]:
    q = question.lower()

    # between 2026-01-01 and 2026-03-31  /  from ... to ...
    m = re.search(r"(?:between|from)\s+(\d{4}-\d{2}-\d{2})\s+(?:and|to|-)\s+(\d{4}-\d{2}-\d{2})", q)
    if m:
        return DateRange(kind="absolute", start=m.group(1), end=m.group(2)), m.group(0)

    m = re.search(r"\bsince\s+(\d{4}-\d{2}-\d{2})\b", q)
    if m:
        return DateRange(kind="absolute", start=m.group(1)), m.group(0)

    # "last 3 months", "past six weeks", "previous 2 quarters"
    m = re.search(r"\b(?:last|past|previous|trailing)\s+(\d+|[a-z]+)\s+(\w+?)s?\b", q)
    if m and m.group(2) + "s" in UNITS or (m and m.group(2) in UNITS):
        unit = UNITS.get(m.group(2), UNITS.get(m.group(2) + "s"))
        n = _n(m.group(1))
        if unit and n >= 1:
            # "last 3 months" = this period plus the 2 before it.
            return DateRange(kind="relative", unit=unit, offset=0, periods=n), m.group(0)

    # "last month", "previous quarter"
    m = re.search(r"\b(?:last|previous|prior)\s+(day|week|month|quarter|year)\b", q)
    if m:
        return DateRange(kind="relative", unit=m.group(1), offset=-1, periods=1), m.group(0)

    # "this month", "current quarter"
    m = re.search(r"\b(?:this|current)\s+(day|week|month|quarter|year)\b", q)
    if m:
        return DateRange(kind="relative", unit=m.group(1), offset=0, periods=1), m.group(0)

    if re.search(r"\byesterday\b", q):
        return DateRange(kind="relative", unit="day", offset=-1, periods=1), "yesterday"
    if re.search(r"\b(today|so far today)\b", q):
        return DateRange(kind="relative", unit="day", offset=0, periods=1), "today"
    if re.search(r"\b(ytd|year to date|this year so far)\b", q):
        return DateRange(kind="relative", unit="year", offset=0, periods=1), "ytd"

    # "in May 2026" / "in May" -> absolute month. Without a year the caller
    # resolves against the anchor, so we leave the year out deliberately.
    m = re.search(r"\b(?:in|during|for)\s+(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?", q)
    if m:
        mon = MONTHS[m.group(1)]
        if m.group(2):
            y = int(m.group(2))
            end = f"{y+1}-01-01" if mon == 12 else f"{y}-{mon+1:02d}-01"
            # end is exclusive at the compiler, so pass the last day of the month
            import datetime
            last = datetime.date.fromisoformat(end) - datetime.timedelta(days=1)
            return DateRange(kind="absolute", start=f"{y}-{mon:02d}-01",
                             end=last.isoformat()), m.group(0)
        return None, None   # bare month name needs the anchor year -- let the model decide

    return None, None
