"""Indian numeral shorthand normalisation. No model required -- every rule is
a regex anchored on an adjacent digit, so it is fully testable on its own."""
from app.nlq_numbers import normalise


def test_lakh_forms():
    assert normalise("1 lakh") == "100000"
    assert normalise("1 lac") == "100000"
    assert normalise("1.5 lakhs") == "150000"
    assert normalise("2 lacs") == "200000"


def test_crore_forms():
    assert normalise("2 cr") == "20000000"
    assert normalise("1 crore") == "10000000"
    assert normalise("2.5 crores") == "25000000"


def test_rupee_symbol_is_preserved():
    assert normalise("₹5 lakh") == "₹500000"
    assert normalise("₹1.5 cr") == "₹15000000"


def test_l_shorthand():
    assert normalise("5L") == "500000"
    assert normalise("1.5L") == "150000"


def test_k_shorthand():
    assert normalise("10k") == "10000"
    assert normalise("2.5k") == "2500"
    assert normalise("10K") == "10000"


def test_in_context_sentence():
    assert (normalise("How many payments over 1 lakh did I make in May?")
            == "How many payments over 100000 did I make in May?")
    assert (normalise("spend more than 2 cr this quarter")
            == "spend more than 20000000 this quarter")


def test_no_false_positives_on_ordinary_words():
    # "black" contains "lac", "across" contains "cr" -- neither has a
    # preceding number for the regex to anchor on, so neither should change.
    for q in ["a black cat crossed the road", "look across the room",
              "the market crashed", "OK, thanks", "I like cricket"]:
        assert normalise(q) == q, q


def test_untouched_when_no_shorthand_present():
    assert normalise("how much did I spend last month") == "how much did I spend last month"
    assert normalise("total tax paid in 2026") == "total tax paid in 2026"
