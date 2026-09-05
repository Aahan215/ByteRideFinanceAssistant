"""Planner tests. No model required -- a fake chat function stands in for it,
so these run in CI and on a laptop with no Ollama."""
import pytest
from app.planner import coerce, plan_detailed, looks_like_followup
from app.spec import QuerySpec, DateRange, Filters


def fake(payload):
    """Stand-in for the model: always returns `payload`."""
    def _f(role, system, user, temperature=None):
        return payload
    return _f


def sequence(*payloads):
    """Model that returns a different payload on each call -- for the repair loop."""
    it = iter(payloads)
    def _f(role, system, user, temperature=None):
        return next(it)
    return _f


# --- coerce: the predictable small-model mistakes ---------------------------

def test_unwraps_a_wrapper_key():
    assert coerce({"query": {"dataset": "payouts", "metric": "sum_amount"}})["dataset"] == "payouts"


def test_maps_dataset_and_metric_synonyms():
    d = coerce({"dataset": "spend", "metric": "total"})
    assert d["dataset"] == "payouts" and d["metric"] == "sum_amount"


def test_group_by_string_becomes_a_list_and_vendor_maps_to_counterparty():
    assert coerce({"group_by": "vendor"})["group_by"] == ["counterparty"]


def test_filters_hoisted_to_top_level_are_recovered():
    d = coerce({"dataset": "payouts", "category": "tax"})
    assert d["filters"]["category"] == "TAX"


def test_category_casing_is_normalised():
    assert coerce({"filters": {"category": "bank charges"}})["filters"]["category"] == "BANK_CHARGES"


def test_currency_formatted_amounts_are_parsed():
    assert coerce({"filters": {"min_amount": "₹1,500"}})["filters"]["min_amount"] == 1500.0


def test_model_supplied_dates_are_discarded():
    # dates are resolved deterministically; the model must not override them
    assert "date_range" not in coerce({"date_range": {"kind": "relative", "unit": "week"}})


def test_unknown_keys_are_dropped():
    assert "nonsense" not in coerce({"dataset": "payouts", "nonsense": 1})


def test_unsupported_reason_short_circuits():
    d = coerce({"unsupported_reason": "no credit score data", "dataset": "payouts"})
    assert d["unsupported_reason"] and d.get("group_by") is None


def test_patch_mode_does_not_invent_defaults():
    # the bug this guards: a follow-up wiping the prior turn's dataset/filters
    assert coerce({}, patch=True) == {}
    assert coerce({"metric": "count"}, patch=True) == {"metric": "count"}


# --- plan: end to end with a fake model -------------------------------------

def test_dates_come_from_the_extractor_not_the_model():
    r = plan_detailed("where did I spend the most last month",
                      chat_fn=fake({"dataset": "payouts", "group_by": ["counterparty"]}))
    assert r.date_source == "deterministic"
    assert (r.spec.date_range.unit, r.spec.date_range.offset) == ("month", -1)


def test_tax_question_becomes_a_category_filter():
    r = plan_detailed("total tax I paid in the last 3 months",
                      chat_fn=fake({"dataset": "payouts", "filters": {"category": "TAX"}}))
    assert r.spec.filters.category == "TAX"
    assert (r.spec.date_range.unit, r.spec.date_range.periods) == ("month", 3)


def test_repair_loop_recovers_from_an_invalid_first_reply():
    r = plan_detailed("where did I spend the most",
                      chat_fn=sequence({"dataset": 12345, "metric": ["not", "a", "metric"]},
                                       {"dataset": "payouts", "group_by": ["counterparty"]}))
    assert r.spec.dataset == "payouts" and len(r.attempts) == 2


def test_two_failures_refuse_rather_than_guess():
    bad = {"dataset": {"nested": "garbage"}, "group_by": {"also": "garbage"}}
    r = plan_detailed("something incoherent", chat_fn=sequence(bad, bad))
    assert r.spec.unsupported_reason and r.confidence == "low"


def test_out_of_scope_question_is_refused():
    r = plan_detailed("what is my credit score",
                      chat_fn=fake({"unsupported_reason": "I have no credit score data."}))
    assert r.spec.unsupported_reason


def test_followup_keeps_prior_context():
    prior = QuerySpec(dataset="payouts", metric="sum_amount",
                      filters=Filters(category="TAX"),
                      date_range=DateRange(kind="relative", unit="month", offset=-1))
    r = plan_detailed("what about the month before that?", prior, chat_fn=fake({}))
    assert r.used_patch
    assert r.spec.dataset == "payouts" and r.spec.filters.category == "TAX"


def test_followup_detection():
    prior = QuerySpec(dataset="payouts")
    assert looks_like_followup("what about last month?", prior)
    assert looks_like_followup("compare to May", prior)
    assert not looks_like_followup("how much tax did I pay in the last 3 months", prior)
    assert not looks_like_followup("what about last month?", None)


def test_a_short_unrelated_question_is_not_a_followup():
    """Regression: "Which transactions are unreconciled?" is four words, was
    treated as a refinement, and silently inherited the previous turn's vendor
    filter -- turning a correct refusal into a confident wrong answer."""
    prior = QuerySpec(dataset="payouts", filters=Filters(counterparty="ZOMATO HYPERPURE"))
    assert not looks_like_followup("Which transactions are unreconciled?", prior)
    assert not looks_like_followup("What is my credit score?", prior)
    assert not looks_like_followup("Total tax paid?", prior)


def test_genuine_followups_are_still_detected():
    prior = QuerySpec(dataset="payouts")
    for q in ["what about the month before that?", "And the 3 months before that?",
              "Just show me tax", "Break that down by category instead",
              "How does that compare?", "same for last quarter"]:
        assert looks_like_followup(q, prior), q


def test_uncategorised_is_not_offered_as_a_filterable_category():
    """UNCATEGORISED is our bucket for narrations we could not classify.
    Offering it let "how much on groceries?" become a confident total for a
    category we never tracked."""
    from app.planner import CATEGORIES
    assert "UNCATEGORISED" not in CATEGORIES
    assert "TAX" in CATEGORIES


def test_truncated_json_is_salvaged_not_discarded():
    """qwen3:4b emitted a valid object then padded with whitespace until it hit
    the token limit, truncating before the closing brace. Throwing that away
    costs a whole turn for output that was fine up to the cut."""
    import app.llm as llm
    truncated = ('{\n "dataset": "payouts",\n "metric": "sum_amount",\n'
                 ' "group_by": [],\n "filters": {\n  "category": "TAX"\n }\n   \n  \n')
    orig = llm.chat
    llm.chat = lambda *a, **k: truncated
    try:
        got = llm.chat_json("planner", "sys", "user")
    finally:
        llm.chat = orig
    assert got["dataset"] == "payouts" and got["filters"]["category"] == "TAX"


def test_the_planner_schema_only_allows_real_values():
    from app.planner import planner_schema, DATASETS, METRICS
    s = planner_schema()
    assert s["properties"]["dataset"]["enum"] == DATASETS
    assert s["properties"]["metric"]["enum"] == METRICS
    assert "UNCATEGORISED" not in s["properties"]["filters"]["properties"]["category"]["enum"]
