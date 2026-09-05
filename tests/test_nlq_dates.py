from app.nlq_dates import extract
from app.dates import resolve
import datetime

ANCHOR = datetime.date(2026, 6, 24)


def r(q):
    dr, _ = extract(q)
    return dr


def test_this_month():
    dr = r("where did I spend the most this month")
    assert (dr.unit, dr.offset, dr.periods) == ("month", 0, 1)


def test_last_month():
    dr = r("how much did I spend last month")
    assert (dr.unit, dr.offset, dr.periods) == ("month", -1, 1)


def test_last_n_months_spans_n_periods():
    dr = r("total tax I paid in the last 3 months")
    assert (dr.unit, dr.offset, dr.periods) == ("month", 0, 3)
    assert resolve(dr, ANCHOR) == (datetime.date(2026, 4, 1), datetime.date(2026, 7, 1))


def test_word_numbers():
    dr = r("my spend over the past six weeks")
    assert (dr.unit, dr.periods) == ("week", 6)


def test_absolute_range():
    dr = r("spend between 2026-01-01 and 2026-03-31")
    assert (dr.kind, dr.start, dr.end) == ("absolute", "2026-01-01", "2026-03-31")


def test_named_month_with_year():
    dr = r("what did I spend in May 2026")
    assert (dr.kind, dr.start, dr.end) == ("absolute", "2026-05-01", "2026-05-31")


def test_no_date_phrase_returns_none():
    assert r("where did I spend the most") is None


def test_last_quarter():
    dr = r("total charges last quarter")
    assert (dr.unit, dr.offset) == ("quarter", -1)
