import math
import pandas as pd
from app.anomaly import score_row, from_scan, THRESHOLD, MAD_TO_SIGMA, FLAT_TOLERANCE


def test_a_typical_amount_is_not_flagged():
    median_log = math.log(20000)
    s, _ = score_row(21000, median_log, 0.4)
    assert s < THRESHOLD


def test_a_large_outlier_is_flagged():
    median_log = math.log(20000)
    s, d = score_row(1_200_000, median_log, 0.4)
    assert s >= THRESHOLD and d == "high"


def test_log_space_means_scale_does_not_matter():
    """A 60x payment must score the same for a vendor whose typical spend is
    ₹200 as for one at ₹200,000. A raw z-score would not do this."""
    a, _ = score_row(200 * 60, math.log(200), 0.4)
    b, _ = score_row(200_000 * 60, math.log(200_000), 0.4)
    assert abs(a - b) < 1e-9


def test_fixed_amount_vendors_do_not_divide_by_zero():
    # EMI/rent vendors charge the same every month, so MAD is exactly 0
    s, _ = score_row(19895, math.log(19895), 0.0)
    assert s == 0.0
    big, _ = score_row(19895 * 50, math.log(19895), 0.0)
    assert big >= THRESHOLD


def test_low_outliers_are_labelled_as_such():
    _, d = score_row(100, math.log(20000), 0.4)
    assert d == "low"


def test_one_callout_per_vendor():
    df = pd.DataFrame({
        "counterparty": ["ACME", "ACME", "BETA"],
        "transaction_amount": [900.0, 800.0, 700.0],
        "transaction_date": [None] * 3,
        "typical_amount": [10.0] * 3,
        "n": [50] * 3,
        "score": [9.0, 8.0, 7.0],
    })
    flags = from_scan(df)
    assert [f.counterparty for f in flags] == ["ACME", "BETA"]
