"""The data/model boundary is the core architectural claim. Test it."""
import pytest
from app.boundary import assert_no_data, BoundaryViolation, record, report, TRAIL


def test_a_schema_prompt_passes():
    assert_no_data("You convert a question into a QuerySpec. "
                   "Categories: TAX, BANK_CHARGES, RENT.", role="planner")


def test_a_transaction_uuid_is_refused():
    with pytest.raises(BoundaryViolation, match="UUID"):
        assert_no_data("row bf294144-51cd-77a3-d2ff-18ff838e1082 amount 20479",
                       role="planner")


def test_a_masked_account_number_is_refused():
    # even masked PII must not reach the provider
    with pytest.raises(BoundaryViolation, match="account number"):
        assert_no_data("account XXXXXX1425 paid 13579", role="narrator")


def test_a_redacted_utr_is_refused():
    with pytest.raises(BoundaryViolation, match="UTR"):
        assert_no_data("utr [redacted]", role="narrator")


def test_crossings_are_recorded_for_audit():
    TRAIL.clear()
    record("planner", "gemini-2.5-flash", "Where did I spend the most?")
    r = report()
    assert r["crossings"] == 1
    assert r["by_role"]["planner"] == 1
    assert r["chars_sent"] > 0


def test_the_default_narrator_sends_nothing_to_the_model():
    """Templates cannot be wrong and no data leaves. Sending the result table
    to a third-party provider must be a deliberate opt-in."""
    assert report()["narrator_sends_results_to_model"] is False
