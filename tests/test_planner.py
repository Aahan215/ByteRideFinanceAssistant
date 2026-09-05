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


def test_the_patch_schema_requires_nothing():
    """A follow-up must be able to emit only what changed. Requiring
    dataset/metric/group_by made every patch a full spec that overwrote the
    prior turn -- multi-turn scored 0/5 because of it."""
    from app.planner import planner_schema, patch_schema
    assert "required" in planner_schema()
    assert "required" not in patch_schema()
    assert patch_schema()["properties"].keys() == planner_schema()["properties"].keys()


def test_dataset_direction_is_decided_deterministically():
    """qwen3:4b answered "unchanged" for every field on "what about receipts?",
    which is safe but useless. Direction words are regular enough to decide
    without the model."""
    from app.planner import dataset_from_words
    assert dataset_from_words("What about receipts?") == "receipts"
    assert dataset_from_words("how much came in instead?") == "receipts"
    assert dataset_from_words("what did I spend?") == "payouts"
    assert dataset_from_words("show me all transactions") == "transactions"
    # says nothing about direction -> leave the prior dataset alone
    assert dataset_from_words("break that down by category") is None
    assert dataset_from_words("what about last month?") is None


def test_refinement_replaces_group_by_rather_than_appending():
    from app.planner import apply_refinement, UNCHANGED
    prior = QuerySpec(dataset="payouts", group_by=["counterparty"])
    out = apply_refinement(prior, {"dataset": UNCHANGED, "metric": UNCHANGED,
                                   "group_by": "category", "category": UNCHANGED,
                                   "counterparty": UNCHANGED})
    assert out.group_by == ["category"]


def test_refinement_leaves_untouched_fields_alone():
    from app.planner import apply_refinement, UNCHANGED
    prior = QuerySpec(dataset="payouts", metric="sum_amount",
                      group_by=["counterparty"], filters=Filters(category="TAX"))
    out = apply_refinement(prior, {k: UNCHANGED for k in
                                   ("dataset", "metric", "group_by", "category", "counterparty")})
    assert out.dataset == "payouts" and out.group_by == ["counterparty"]
    assert out.filters.category == "TAX"


def test_out_of_scope_concepts_are_refused_without_a_model_call():
    """Every term here is genuinely absent from bank/account/transaction, so a
    match is a real refusal rather than a guess."""
    from app.planner import out_of_scope
    for q in ["Which transactions are still unreconciled?", "Am I over budget?",
              "What will I spend next month?", "What is my credit score?",
              "What is my net worth?", "Show me my profit and loss",
              "Show me all invoices from Acme", "How much tax do I owe?"]:
        assert out_of_scope(q), q
    for q in ["Where did I spend the most this month?", "Total tax I paid last quarter",
              "How much did I pay Zomato?", "Break spending down by category"]:
        assert out_of_scope(q) is None, q


def test_a_category_the_user_never_named_is_not_trusted():
    """Constrained decoding forces a choice from the enum, so "groceries"
    landed on CASH and returned a confident Rs 42 crore."""
    from app.planner import category_is_supported
    assert not category_is_supported("How much did I spend on groceries?", "CASH")
    assert not category_is_supported("what did I spend on travel?", "UTILITIES")
    assert category_is_supported("how much cash did I withdraw?", "CASH")
    assert category_is_supported("total tax paid", "TAX")
    assert category_is_supported("my electricity bills", "UTILITIES")
    assert category_is_supported("anything", None)


def test_reconciliation_is_refused_in_every_phrasing():
    """The schema has no reconciliation field. The model must never infer one --
    a 'Count: 0' here reads as 'you have zero unreconciled transactions'."""
    from app.planner import out_of_scope
    for q in ["Which transactions are unreconciled?", "un-reconciled items",
              "show unmatched entries", "what is the settlement status?",
              "which payments are not yet cleared?", "reconcile my account",
              "reconciliation report"]:
        assert out_of_scope(q), q


def test_date_phrases_are_not_treated_as_follow_ups():
    """"How much did I spend last month?" is a standalone question, not a
    refinement of whatever came before."""
    prior = QuerySpec(dataset="payouts", filters=Filters(counterparty="ZOMATO"))
    for q in ["How much did I spend last month?", "this month total?",
              "what did I spend previously"]:
        assert not looks_like_followup(q, prior), q


def test_pronouns_are_follow_ups():
    prior = QuerySpec(dataset="payouts")
    for q in ["how much did I pay him?", "what did I receive from them?"]:
        assert looks_like_followup(q, prior), q


def test_markdown_fenced_json_is_parsed():
    """Small models wrap JSON in fences far more often than large ones."""
    import app.llm as llm
    orig = llm.chat
    llm.chat = lambda *a, **k: '```json\n{"dataset": "payouts", "metric": "count"}\n```'
    try:
        got = llm.chat_json("planner", "s", "u")
    finally:
        llm.chat = orig
    assert got == {"dataset": "payouts", "metric": "count"}


def test_an_invented_category_is_dropped_not_refused():
    """The model attached category=TRANSFER to "what is my spend this quarter?",
    which mentions no category. Refusing threw away an answerable question; the
    right move is to drop the filter the user never asked for."""
    from app.planner import category_verdict
    assert category_verdict("What is my spend this quarter?", "TRANSFER") == "drop"
    assert category_verdict("How much did I spend last month?", "CASH") == "drop"


def test_a_category_the_user_asked_for_but_we_lack_is_refused():
    from app.planner import category_verdict
    assert category_verdict("How much did I spend on groceries?", "CASH") == "refuse"
    assert category_verdict("what did I spend on travel?", "UTILITIES") == "refuse"


def test_a_correctly_named_category_passes():
    from app.planner import category_verdict
    assert category_verdict("How much cash did I withdraw?", "CASH") == "ok"
    assert category_verdict("total tax paid last quarter", "TAX") == "ok"


def test_transactions_plus_a_direction_canonicalises_to_the_dataset():
    """transactions + transaction_type=debit IS payouts -- one query, two
    spellings. Canonical form keeps downstream logic seeing one."""
    d = coerce({"dataset": "transactions", "filters": {"transaction_type": "debit"}})
    assert d["dataset"] == "payouts" and "transaction_type" not in d["filters"]
    d = coerce({"dataset": "transactions", "filters": {"transaction_type": "credit"}})
    assert d["dataset"] == "receipts"


def test_no_op_amount_bounds_are_dropped():
    """A richer prompt makes small models fill every field; min 0 / max 1e15 are
    no-ops that only add noise to the SQL."""
    d = coerce({"dataset": "payouts", "filters": {"min_amount": 0, "max_amount": 1e15}})
    assert d["filters"] == {}
    d = coerce({"dataset": "payouts", "filters": {"min_amount": 5000}})
    assert d["filters"]["min_amount"] == 5000


def test_out_of_scope_is_checked_on_follow_ups_too():
    """It used to be gated on `prior is None`, so asking "which transactions
    are unreconciled?" mid-conversation skipped the check and answered
    "Count: 0" with high confidence."""
    prior = QuerySpec(dataset="payouts", metric="sum_amount")
    r = plan_detailed("Which transactions are unreconciled?", prior,
                      chat_fn=lambda *a, **k: {"dataset": "transactions", "metric": "count"})
    assert r.spec.unsupported_reason and "reconciliation" in r.spec.unsupported_reason


def test_grouping_by_a_pinned_filter_is_dropped():
    """"Trends of Priya Sharma" came back grouped BY counterparty while
    counterparty was filtered to PRIYA SHARMA -- one row, rendered as a
    one-slice pie chart that answers nothing."""
    r = plan_detailed("Give me the trends of Priya Sharma for this quarter",
                      chat_fn=lambda *a, **k: {
                          "dataset": "payouts", "metric": "sum_amount",
                          "group_by": ["counterparty"],
                          "filters": {"counterparty": "Priya Sharma"}})
    assert "counterparty" not in r.spec.group_by
    assert r.spec.group_by == ["month"]          # a trend is about time
    assert r.spec.filters.counterparty == "PRIYA SHARMA"


def test_trend_wording_is_detected_deterministically():
    from app.planner import wants_trend
    for q in ["show me the trend", "spending over time", "month by month",
              "monthly spending", "how has my spending changed"]:
        assert wants_trend(q), q
    for q in ["where did I spend the most", "total tax last quarter"]:
        assert not wants_trend(q), q


def test_a_normal_grouping_is_untouched():
    r = plan_detailed("Where did I spend the most this month?",
                      chat_fn=lambda *a, **k: {
                          "dataset": "payouts", "metric": "sum_amount",
                          "group_by": ["counterparty"], "filters": {}})
    assert r.spec.group_by == ["counterparty"]
