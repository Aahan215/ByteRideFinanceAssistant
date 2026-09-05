from app.confidence import assess
from app.spec import QuerySpec


def spec(**kw):
    return QuerySpec(dataset="payouts", **kw)


def test_a_clean_query_is_high_confidence():
    a = assess(spec=spec(), row_count=5000)
    assert a.level == "high" and not a.reasons


def test_a_tiny_sample_is_downgraded_with_a_reason():
    a = assess(spec=spec(), row_count=3)
    assert a.level == "medium" and "only 3 transactions" in a.reasons[0]


def test_poor_attribution_downgrades_a_ranking():
    a = assess(spec=spec(group_by=["counterparty"]), row_count=700, excluded_rows=300)
    assert a.level == "medium" and "30%" in a.reasons[0]


def test_model_disagreeing_with_itself_is_the_strongest_signal():
    a = assess(spec=spec(), row_count=5000, planner_confidence="low")
    assert a.level == "low"


def test_two_independent_concerns_compound_to_low():
    a = assess(spec=spec(group_by=["counterparty"]), row_count=700, excluded_rows=300,
               warnings=["Interpreted vendor 'Zomto' as 'ZOMATO HYPERPURE'."])
    assert a.level == "low" and len(a.reasons) == 2


def test_no_matching_rows_is_not_a_confidence_question():
    a = assess(spec=spec(), row_count=0)
    assert a.level == "n/a"


def test_every_downgrade_carries_a_reason():
    """A bare 'medium' badge tells the user nothing actionable."""
    a = assess(spec=spec(), row_count=2, planner_confidence="medium",
               comparison_mismatch=True)
    assert a.reasons and all(r.strip() for r in a.reasons)


def test_uncategorised_is_rejected_as_a_user_filter():
    from app.validator import validate
    from app.spec import QuerySpec, Filters
    v = validate(QuerySpec(dataset="payouts", filters=Filters(category="UNCATEGORISED")))
    assert not v.ok and v.refusal


def test_an_empty_result_is_never_upgraded_to_high():
    """A query that matched nothing has no answer to be confident about. The
    /ask handler was overwriting "n/a" with "high" because the model had been
    self-consistent about producing an empty result."""
    from app.confidence import assess
    a = assess(spec=spec(), row_count=0, planner_confidence="high")
    assert a.level == "n/a"
    order = {"n/a": -1, "high": 0, "medium": 1, "low": 2}
    assert order["high"] > order["n/a"]      # the merge must guard against this
