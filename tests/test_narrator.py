from app.narrator import inr


def test_indian_digit_grouping():
    # the UI formats with en-IN; the narrator must agree or one figure appears
    # two different ways on the same screen
    assert inr(20207328.58) == "₹2,02,07,329"
    assert inr(100000) == "₹1,00,000"
    assert inr(999) == "₹999"
    assert inr(1234) == "₹1,234"
    assert inr(-50000) == "-₹50,000"
    assert inr(None) == "-"


def test_plural_labels_are_real_words():
    from app.narrator import LABELS
    assert LABELS["counterparty"] == "vendors"
    assert LABELS["category"] == "categories"


def test_month_groups_read_as_months_not_timestamps():
    """"2026-04-01 00:00:00 is highest" is not how anyone reads a trend."""
    from app.narrator import _group_value
    assert _group_value("month", "2026-04-01 00:00:00") == "April 2026"
    assert _group_value("quarter", "2026-04-01") == "Q2 2026"
    assert _group_value("counterparty", "ZOMATO HYPERPURE") == "ZOMATO HYPERPURE"
    assert _group_value("month", None) == "None"
