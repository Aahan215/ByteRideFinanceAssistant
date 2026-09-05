"""The schema block the planner sees. Generated, so it cannot drift from the
semantic layer -- and it must not carry transaction data to the model."""
import app.schema_context as sc


def schema_context():
    sc.schema_context.cache_clear()
    old, sc.ENABLED = sc.ENABLED, True
    try:
        return sc.schema_context()
    finally:
        sc.ENABLED = old; sc.schema_context.cache_clear()
from app.db import SEMANTIC


def test_every_dimension_and_category_is_described():
    s = schema_context()
    for dim in SEMANTIC["dimensions"]:
        assert dim in s, dim
    for cat in SEMANTIC["spend_categories"]:
        if cat != "UNCATEGORISED":
            assert cat in s, cat


def test_uncategorised_is_never_offered():
    """It is our bucket for narrations we could not classify, not something a
    user can ask for."""
    assert "UNCATEGORISED" not in schema_context()


def test_no_counterparty_values_reach_the_model():
    """Who you pay is transaction-derived data. Closed reference vocabularies
    (channels, banks) are schema; vendor names are not."""
    from app.db import run
    top = run("""SELECT counterparty FROM txn_enriched WHERE counterparty IS NOT NULL
                 GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 25""")
    s = schema_context()
    for name, in top.values:
        assert str(name) not in s, f"vendor name leaked into the prompt: {name}"


def test_it_states_what_is_absent():
    s = schema_context().lower()
    for absent in ("reconciliation", "budget", "forecast", "credit score", "invoice"):
        assert absent in s, absent


def test_the_prompt_passes_the_data_boundary_check():
    from app.planner import _prompt
    from app.boundary import assert_no_data
    assert_no_data(_prompt(), role="planner")


def test_it_is_off_by_default_because_it_cost_accuracy():
    """Measured: qwen3:4b scores 49/49 without it and 47/49 with it. The extra
    ~720 tokens crowd out the few-shots the model learns the shape from."""
    assert sc.ENABLED is False
