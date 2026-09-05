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


def test_a_truncated_vendor_name_is_the_same_merchant():
    """Field-length limits cut narrations mid-word, producing "ZOMATO H"
    alongside "ZOMATO HYPERPURE". Treating the stub as a separate merchant made
    every lookup for that vendor ambiguous and refuse."""
    known = ["ZOMATO HYPERPURE", "ZOMATO H", "ZOMATO HYPER", "SWIGGY INSTAMART"]
    resolved, candidates, how = resolve_counterparty("zomato", known)
    assert how == "family" and resolved is not None
    assert "ZOMATO HYPERPURE" in resolved and "SWIGGY INSTAMART" not in resolved


def test_an_exact_match_with_branch_variants_resolves_to_the_family():
    """The user typed the exact canonical name, and the data ALSO holds
    several branch-suffixed variants of it (same shape as the production
    ZOMATO HYPERPURE / DMART AVENUE SUPERMARTS vendors, each with a city
    suffix). The exact hit must resolve straight to the whole family --
    asking "which did you mean?" here is the bug this guards against."""
    known = ["ZOMATO HYPERPURE", "ZOMATO HYPERPURE ANDHERI WEST",
             "ZOMATO HYPERPURE BANDRA", "ZOMATO HYPERPURE KORAMANGALA",
             "SWIGGY INSTAMART"]
    resolved, candidates, how = resolve_counterparty("ZOMATO HYPERPURE", known)
    assert how == "family" and not candidates
    assert set(resolved) == set(known) - {"SWIGGY INSTAMART"}


def test_an_exact_match_behind_a_shared_legal_suffix_is_still_one_family():
    """Some vendors carry a legal suffix ("LTD") between the canonical name
    and the branch/city name, so every extension shares the SAME next word.
    A next-word-divergence check alone sees no divergence and was returning
    the base name alone, silently dropping every branch from the total."""
    known = ["WESTSIDE TRENT", "WESTSIDE TRENT LTD ANDHERI WEST",
             "WESTSIDE TRENT LTD DAHISAR EAST", "SWIGGY INSTAMART"]
    resolved, candidates, how = resolve_counterparty("WESTSIDE TRENT", known)
    assert how == "family" and not candidates
    assert set(resolved) == set(known) - {"SWIGGY INSTAMART"}


def test_an_exact_match_that_is_also_a_stem_for_different_entities_still_asks():
    """The exact-match path now shares the family helper with subset-match,
    but a lone word that is itself an exact vendor AND the stem of several
    DIFFERENT people ("RAJESH" -> AGARWAL / BHATT / CHATTERJEE) must still
    ask instead of silently summing across people who are not one merchant."""
    known = ["RAJESH", "RAJESH AGARWAL", "RAJESH BHATT", "RAJESH CHATTERJEE"]
    resolved, candidates, how = resolve_counterparty("Rajesh", known)
    assert resolved is None and how == "ambiguous"
    assert len(candidates) >= 2
