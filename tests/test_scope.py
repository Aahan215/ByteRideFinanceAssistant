"""Scope isolation.

This is a selector, not auth -- but a query path that forgets the scope shows
one user another user's transactions, so every builder is checked, not just the
one the happy path uses.
"""
import datetime
import pytest

from app.spec import QuerySpec, DateRange
from app import scope as sm
from app.compiler import (compile_sql, compile_evidence_sql, compile_count_sql,
                          compile_null_group_sql, compile_anomaly_sql)

ANCHOR = datetime.date(2026, 6, 30)
SPEC = QuerySpec(dataset="payouts", metric="sum_amount", group_by=["counterparty"],
                 compare_to=DateRange(kind="relative", unit="month", offset=-1))


def _sql(fn, scope):
    out = fn(SPEC, ANCHOR, scope=scope)
    return out[0] if isinstance(out, tuple) else out


ALL_BUILDERS = [compile_sql, compile_evidence_sql, compile_count_sql,
                compile_null_group_sql, compile_anomaly_sql]


@pytest.mark.parametrize("fn", ALL_BUILDERS)
def test_every_query_builder_applies_an_account_scope(fn):
    sql = _sql(fn, sm.parse("account", "acct-1"))
    assert "account_id = ?" in sql, f"{fn.__name__} would leak across accounts"


@pytest.mark.parametrize("fn", ALL_BUILDERS)
def test_every_query_builder_applies_an_entity_scope(fn):
    sql = _sql(fn, sm.parse("entity", "ent-1"))
    assert "entity_id = ?" in sql, f"{fn.__name__} would leak across entities"


@pytest.mark.parametrize("fn", ALL_BUILDERS)
def test_the_all_scope_adds_no_predicate(fn):
    sql = _sql(fn, sm.ALL)
    assert "entity_id = ?" not in sql and "account_id = ?" not in sql


def test_the_scope_value_is_a_bound_parameter():
    _, params, _ = compile_sql(SPEC, ANCHOR, scope=sm.parse("account", "'; DROP TABLE x;--"))
    assert "'; DROP TABLE x;--" in params


def test_an_unknown_level_is_rejected_rather_than_widened():
    """Falling back to `all` on a typo would quietly show one user everyone
    else's data -- the exact failure this exists to prevent."""
    with pytest.raises(ValueError):
        sm.parse("everything", "x")
    with pytest.raises(ValueError):
        sm.parse("account", None)


def test_scope_is_not_part_of_queryspec():
    """The model must not be able to set or widen its own scope."""
    assert "scope" not in QuerySpec.model_fields


def test_scope_never_reaches_the_model():
    from app.planner import _prompt
    assert "entity_id" not in _prompt() or "scope" not in _prompt().lower()
