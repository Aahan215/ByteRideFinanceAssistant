"""NaN safety.

An aggregate over zero rows is NaN, not zero, and NaN does not behave like a
falsy value: `nan or 0` is nan, `not nan` is False, `abs(nan)` is nan,
`round(nan)` RAISES. Two 500s and one "sum amount: nan" answer came from this,
so every helper that formats or compares a number from a query is checked here.
"""
import math
import pytest

NAN = float("nan")


def test_currency_formatter_survives_nan():
    from app.narrator import inr
    assert inr(NAN) == "-"
    assert inr(None) == "-"
    assert inr(0) == "₹0"
    assert inr(-50000) == "-₹50,000"


def test_measure_formatter_survives_nan():
    from app.narrator import _measure
    from app.spec import QuerySpec
    for metric in ("sum_amount", "count", "avg_amount"):
        assert _measure(QuerySpec(dataset="payouts", metric=metric), NAN) == "-"


def test_anomaly_sentence_survives_nan():
    """`not nan` is False, so a NaN typical slipped past the zero guard and the
    division produced a NaN multiple."""
    from app.anomaly import Flag
    for amount, typical in [(NAN, 100.0), (100.0, NAN), (NAN, NAN)]:
        s = Flag("ACME", amount, typical, 9.0, "high", 5).sentence()
        assert "nan" not in s.lower()


def test_num_helper_treats_nan_as_missing():
    from app.api import _num
    assert _num(NAN) == 0.0 and _num(None) == 0.0 and _num(7.5) == 7.5
    assert int(_num(NAN)) == 0          # int(nan) would raise


def test_nan_is_not_falsy_the_assumption_that_caused_all_of_this():
    assert (NAN or 0) is not 0          # noqa: F632  -- the whole point
    assert not math.isnan(NAN or 0) is False
    assert bool(NAN) is True
    with pytest.raises(ValueError):
        round(NAN)
