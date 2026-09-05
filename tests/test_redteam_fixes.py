"""Each of these is a fabrication the red-team suite caught."""
from app.planner import plan_detailed, out_of_scope
from app.spec import QuerySpec


def test_an_unknown_concept_cannot_be_laundered_through_description_contains():
    """The model put "warranty" into description_contains; counting the spec's
    own filter values as coverage let it through as an answer."""
    r = plan_detailed("Which vendor gives me the best warranty?",
                      chat_fn=lambda *a, **k: {"dataset": "transactions", "metric": "count",
                                               "group_by": ["counterparty"],
                                               "filters": {"description_contains": "warranty"}})
    assert r.spec.unsupported_reason


def test_a_filter_value_absent_from_the_question_is_invented():
    """In reply to "?" the model emitted a reference id copied verbatim from the
    prompt's own examples. A value not in the question came from nowhere."""
    r = plan_detailed("how much did I spend last month",
                      chat_fn=lambda *a, **k: {"dataset": "payouts", "metric": "sum_amount",
                                               "filters": {"reference_id": "1715499972"}})
    assert r.spec.filters.reference_id is None          # dropped
    assert not r.spec.unsupported_reason                 # the real question survives


def test_a_question_with_no_words_is_refused_before_the_model():
    for q in ["?", "...", "!!", "   "]:
        r = plan_detailed(q, chat_fn=lambda *a, **k: {"dataset": "payouts", "metric": "count"})
        assert r.spec.unsupported_reason and r.attempts == [], q


def test_judgement_questions_are_refused_with_the_fact_offered():
    for q in ["Am I spending too much on food?", "Should I invest more?",
              "Is my rent reasonable?", "Can I afford a new phone?"]:
        assert out_of_scope(q), q
    assert out_of_scope("how much did I spend on food?") is None


def test_requests_for_masked_values_are_refused():
    for q in ["What is the full account number for this account?",
              "show me the unmasked account number", "give me the UTR numbers"]:
        assert out_of_scope(q), q


def test_synonyms_the_red_team_found_now_resolve():
    from app.coverage import unresolved
    for q in ["Total expenditure this quarter", "Which shops do I frequent the most?",
              "Show my disbursements by bank", "What did I fork out on petrol?",
              "Sum of all remittances via NEFT", "which vendor hasn't been paid"]:
        assert unresolved(q) == [], q
