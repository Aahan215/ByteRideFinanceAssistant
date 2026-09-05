import datetime
import pandas as pd
from app.spec import QuerySpec, DateRange, Filters
from app.api import _compare, Comparison


def test_ungrouped_comparison_computes_delta_and_pct(monkeypatch):
    import app.api as api
    monkeypatch.setattr(api, "run", lambda sql, params=None: pd.DataFrame({"sum_amount": [90.0]}))
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=0),
                     compare_to=DateRange(kind="relative", unit="month", offset=-1))
    c = _compare(spec, pd.DataFrame({"sum_amount": [120.0]}), [])
    assert c.value == 120.0 and c.previous == 90.0
    assert c.delta == 30.0 and c.delta_pct == 33.3


def test_missing_group_is_zero_for_additive_metrics(monkeypatch):
    """A vendor absent this period spent nothing -- that is a real -100% move,
    not unknown. Reporting it as unknown hides a vendor that disappeared."""
    import app.api as api
    now = pd.DataFrame({"counterparty": ["A"], "sum_amount": [10.0]})
    prev = pd.DataFrame({"counterparty": ["A", "B"], "sum_amount": [4.0, 50.0]})
    calls = iter([now, prev])
    monkeypatch.setattr(api, "run", lambda *a, **k: next(calls))
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts", group_by=["counterparty"],
                     compare_to=DateRange(kind="relative", unit="month", offset=-1))
    c = _compare(spec, now, [])
    b = next(r for r in c.rows if r["counterparty"] == "B")
    assert b["value"] == 0.0 and b["previous"] == 50.0 and b["delta"] == -50.0
    # the vanished vendor is the biggest move, so it sorts first
    assert c.rows[0]["counterparty"] == "B"


def test_missing_group_is_unknown_for_non_additive_metrics(monkeypatch):
    """An average over zero rows is unknown. Calling it 0 fabricates a number."""
    import app.api as api
    now = pd.DataFrame({"counterparty": ["A"], "avg_amount": [10.0]})
    prev = pd.DataFrame({"counterparty": ["A", "B"], "avg_amount": [4.0, 50.0]})
    calls = iter([now, prev])
    monkeypatch.setattr(api, "run", lambda *a, **k: next(calls))
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts", metric="avg_amount", group_by=["counterparty"],
                     compare_to=DateRange(kind="relative", unit="month", offset=-1))
    c = _compare(spec, now, [])
    b = next(r for r in c.rows if r["counterparty"] == "B")
    assert b["value"] is None and b["delta"] is None


def test_comparison_queries_ignore_the_display_limit(monkeypatch):
    """Diffing two top-N lists reports vendors as vanished merely because they
    fell out of this period's top N."""
    import app.api as api
    seen = []
    def fake_run(sql, params=None):
        seen.append(sql)
        return pd.DataFrame({"counterparty": ["A"], "sum_amount": [1.0]})
    monkeypatch.setattr(api, "run", fake_run)
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts", group_by=["counterparty"], limit=5,
                     compare_to=DateRange(kind="relative", unit="month", offset=-1))
    _compare(spec, pd.DataFrame({"counterparty": ["A"], "sum_amount": [1.0]}), [])
    assert all("LIMIT 5" not in s for s in seen[1:]), seen


def test_mismatched_comparison_periods_are_flagged(monkeypatch):
    """A 3-month window vs a 1-month window yields a confident, meaningless
    percentage. It must be called out, not reported as a change."""
    import app.api as api
    monkeypatch.setattr(api, "run", lambda *a, **k: pd.DataFrame({"sum_amount": [1.0]}))
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=0, periods=3),
                     compare_to=DateRange(kind="relative", unit="month", offset=-1, periods=1))
    warnings = []
    _compare(spec, pd.DataFrame({"sum_amount": [1.0]}), warnings)
    assert any("differ in length" in w for w in warnings)


def test_equal_length_comparison_is_not_flagged(monkeypatch):
    import app.api as api
    monkeypatch.setattr(api, "run", lambda *a, **k: pd.DataFrame({"sum_amount": [1.0]}))
    monkeypatch.setattr(api, "anchor_date", lambda: datetime.date(2026, 6, 24))
    spec = QuerySpec(dataset="payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=0, periods=3),
                     compare_to=DateRange(kind="relative", unit="month", offset=-3, periods=3))
    warnings = []
    _compare(spec, pd.DataFrame({"sum_amount": [1.0]}), warnings)
    assert not any("differ in length" in w for w in warnings)


def test_nan_aggregates_do_not_crash_the_request():
    """`NaN or 0` returns NaN because NaN is truthy, and int(NaN) raises. An
    aggregate over zero excluded rows comes back as NaN, so this fired on any
    question whose breakdown excluded nothing -- a 500, not a wrong answer."""
    import numpy as np
    from app.api import _num
    assert _num(np.nan) == 0.0
    assert _num(None) == 0.0
    assert _num(float("nan")) == 0.0
    assert _num(42.5) == 42.5
    assert int(_num(np.nan)) == 0
