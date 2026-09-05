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


def test_appended_sentences_are_separated():
    """"Rs 1,00,37,55,408 That is up 5.4%" read as one run-on sentence."""
    from app.narrator import _sentence
    assert _sentence("Total for June: ₹100") == "Total for June: ₹100."
    assert _sentence("Already done.") == "Already done."
    assert _sentence("A question?") == "A question?"


def test_the_answer_is_one_headline_not_a_report():
    """Anomalies are a structured field with their own callouts. Appending them
    to the sentence made the answer three times longer and said it twice."""
    import inspect
    import app.api as api
    src = inspect.getsource(api.answer_spec)
    assert "with_anomalies" not in src
