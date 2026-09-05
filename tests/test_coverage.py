"""Concept coverage -- the allowlist that stops the model answering a question
the schema cannot express. "Which vendor gives me the best discount?" came back
as a top-vendors-by-spend ranking, with High confidence."""
from app.coverage import unresolved
from app.planner import plan_detailed
from app.spec import QuerySpec, Filters


def test_a_concept_the_schema_lacks_is_named():
    assert unresolved("Which vendor gives me the best discount") == ["discount"]
    assert unresolved("what is the weather like") == ["weather"]
    assert unresolved("show me my subscriptions") == ["subscriptions"]


def test_everything_we_can_express_is_covered():
    for q in ["Where did I spend the most this month?",
              "Total tax I paid in the last 3 months",
              "How does that compare to the month before?",
              "Break my spending down by category",
              "How much did I spend on groceries last month?",
              "Which payment channel do I use most often?",
              "Show my monthly spending trend",
              "What was my largest payment last month?",
              "if i was to do some savings, where should i control the spend?",
              "Tell me from where all did i buy food?",
              "any unusual payments this month?"]:
        assert unresolved(q) == [], q


def test_a_vendor_name_is_covered_by_the_data_vocabulary():
    # "zomato" and "bajaj" are not schema words; they are covered because they
    # appear in real counterparty names
    assert unresolved("How much did I pay Zomato?") == []
    assert unresolved("what did I pay Bajaj Finance?") == []


def test_the_models_own_filter_values_count_as_coverage():
    # a name the model extracted is a name the model heard
    assert unresolved("how much to Northwind Traders", ["NORTHWIND TRADERS"]) == []


def test_the_planner_refuses_and_names_the_missing_concept():
    """Uses a word the BLOCKLIST has never heard of. "discount" is caught by
    the older blocklist first; this proves the allowlist fires on its own for
    a concept nobody anticipated -- which is the whole point of it."""
    r = plan_detailed("Which vendor gives me the best warranty",
                      chat_fn=lambda *a, **k: {"dataset": "payouts",
                                               "metric": "sum_amount",
                                               "group_by": ["counterparty"]})
    assert r.spec.unsupported_reason and "'warranty'" in r.spec.unsupported_reason


def test_follow_ups_are_not_re_checked():
    """A refinement inherits its subject from the prior turn; its own words
    are short and often pronouns."""
    prior = QuerySpec(dataset="payouts", filters=Filters(category="TAX"))
    r = plan_detailed("what about the month before that?", prior,
                      chat_fn=lambda *a, **k: {})
    assert not r.spec.unsupported_reason
