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
