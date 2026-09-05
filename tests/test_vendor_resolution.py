"""Vendor name resolution. People say "Zomato", the data holds
"ZOMATO HYPERPURE" -- and the gap between those two was 0% on the vendor
bucket of the golden set."""
from app.validator import resolve_counterparty

KNOWN = ["ZOMATO HYPERPURE", "SWIGGY INSTAMART", "DMART AVENUE SUPERMARTS",
         "EMI BAJAJ FINANCE", "SELECTION ELECTRONICS",
         "SELECTION ELECTRONICS DAHISAR EAST", "SELECTION MOBILE",
         "LIC PREMIUM POLICY"]


def r(q):
    return resolve_counterparty(q, KNOWN)


def test_case_and_punctuation_do_not_matter():
    assert r("Zomato Hyperpure")[0] == "ZOMATO HYPERPURE"
    assert r("zomato hyperpure.")[0] == "ZOMATO HYPERPURE"


def test_a_short_name_resolves_to_the_full_vendor():
    # this is the common case: nobody types the full parsed narration
    assert r("zomato")[0] == "ZOMATO HYPERPURE"
    assert r("DMart")[0] == "DMART AVENUE SUPERMARTS"
    assert r("Swiggy")[0] == "SWIGGY INSTAMART"


def test_a_legal_suffix_is_ignored():
    assert r("Bajaj Finance Ltd")[0] == "EMI BAJAJ FINANCE"


def test_an_ambiguous_name_asks_instead_of_guessing():
    resolved, candidates, how = r("Selection")
    assert resolved is None and how == "ambiguous"
    assert len(candidates) >= 2


def test_an_unknown_vendor_is_refused_not_guessed():
    resolved, candidates, how = r("Northwind Traders")
    assert resolved is None and not candidates and how == "unknown"


def test_a_typo_still_resolves():
    assert r("Zomatoo Hyperpure")[0] == "ZOMATO HYPERPURE"


def test_the_planner_normalises_the_filter_the_same_way_the_data_was():
    from app.planner import coerce
    d = coerce({"dataset": "payouts", "filters": {"counterparty": "Zomato Hyperpure"}})
    assert d["filters"]["counterparty"] == "ZOMATO HYPERPURE"


def test_a_resolved_family_satisfies_a_canonical_expectation():
    """The eval must not mark "DMart -> all 8 DMART branches" as a mismatch
    against an expectation naming the canonical vendor."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "evals"))
    from run_evals import subset_match
    got = {"filters": {"counterparty": ["DMART AVENUE SUPERMARTS",
                                        "DMART AVENUE SUPERMARTS SAKET DELHI"]}}
    assert subset_match(got, {"filters": {"counterparty": "DMART AVENUE SUPERMARTS"}})
    assert not subset_match(got, {"filters": {"counterparty": "SWIGGY INSTAMART"}})
