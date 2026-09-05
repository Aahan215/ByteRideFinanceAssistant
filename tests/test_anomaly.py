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


def _flag(amount, typical, direction, n=500):
    from app.anomaly import Flag
    return Flag("ACME TRADERS", amount, typical, 9.0, direction, n)


def test_a_large_outlier_reads_as_a_multiple():
    s = _flag(1_200_000, 20_000, "high").sentence()
    assert "60x the usual" in s and "₹12,00,000" in s


def test_a_small_outlier_is_never_described_as_0x():
    """"₹100 is 0.0x the usual ₹9,553" is not a sentence anyone can act on."""
    s = _flag(100, 9553, "low").sentence()
    assert "0.0x" not in s and "96x smaller" in s


def test_callout_uses_the_same_currency_format_as_the_rest_of_the_app():
    from app.narrator import inr
    s = _flag(4_224_932, 11_897, "high").sentence()
    assert inr(4_224_932) in s          # en-IN grouping, not 4,224,932


def test_low_outliers_are_suppressed_by_default():
    """The brief asks for unusually LARGE payouts; small ones dilute the callout."""
    import pandas as pd
    from app.anomaly import from_scan
    df = pd.DataFrame({
        "counterparty": ["SMALL", "BIG"],
        "transaction_amount": [100.0, 900_000.0],
        "transaction_date": [None, None],
        "typical_amount": [9553.0, 20_000.0],
        "n": [500, 500], "score": [9.5, 9.0],
    })
    assert [f.counterparty for f in from_scan(df)] == ["BIG"]
    assert len(from_scan(df, high_only=False)) == 2


def test_a_statistically_odd_but_small_deviation_is_not_called_out():
    """A robust score alone ranked "3x the usual rent" above a 357x merchant
    payment. "Unusually large" should also look large to the reader."""
    import pandas as pd
    from app.anomaly import from_scan
    df = pd.DataFrame({
        "counterparty": ["RENT DEEPA", "MALABAR GOLD"],
        "transaction_amount": [34_495.0, 2_863_659.0],
        "transaction_date": [None, None],
        "typical_amount": [11_125.0, 8_011.0],       # 3.1x and 357x
        "n": [153, 404], "score": [11.0, 9.0],       # rent scores HIGHER
    })
    assert [f.counterparty for f in from_scan(df)] == ["MALABAR GOLD"]
