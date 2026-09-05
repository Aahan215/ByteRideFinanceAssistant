import datetime
from app.spec import QuerySpec, DateRange, Filters
from app.compiler import compile_sql

ANCHOR = datetime.date(2026, 6, 24)   # the sample data's latest transaction


def test_relative_dates_anchor_to_data_not_wall_clock():
    spec = QuerySpec(dataset="payouts", metric="sum_amount",
                     date_range=DateRange(kind="relative", unit="month", offset=-1))
    _, _, meta = compile_sql(spec, ANCHOR)
    assert meta["window"] == (datetime.date(2026, 5, 1), datetime.date(2026, 6, 1))


def test_payouts_dataset_restricts_to_debits():
    sql, _, _ = compile_sql(QuerySpec(dataset="payouts"), ANCHOR)
    assert "transaction_type = 'debit'" in sql


def test_receipts_dataset_restricts_to_credits():
    sql, _, _ = compile_sql(QuerySpec(dataset="receipts"), ANCHOR)
    assert "transaction_type = 'credit'" in sql


def test_filters_are_bound_parameters_not_interpolated():
    spec = QuerySpec(dataset="transactions",
                     filters=Filters(counterparty="'; DROP TABLE transaction;--"))
    sql, params, _ = compile_sql(spec, ANCHOR)
    assert "DROP TABLE" not in sql
    assert params[0] == "'; DROP TABLE TRANSACTION;--"


def test_category_filter_compiles_to_the_derived_column():
    sql, params, _ = compile_sql(QuerySpec(dataset="payouts",
                                           filters=Filters(category="TAX")), ANCHOR)
    assert "category = ?" in sql and params[0] == "TAX"


def test_three_month_window_spans_three_months():
    spec = QuerySpec(dataset="payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=0, periods=3))
    _, _, meta = compile_sql(spec, ANCHOR)
    assert meta["window"] == (datetime.date(2026, 4, 1), datetime.date(2026, 7, 1))


def test_bare_reference_hits_plaintext_column_not_utr():
    # DECISIONS.md #2 -- utr_number is encrypted and cannot be matched with `=`
    sql, _, _ = compile_sql(QuerySpec(dataset="transactions",
                                      filters=Filters(reference_id="S69244711")), ANCHOR)
    assert "transaction_reference_id = ?" in sql and "utr_number" not in sql


def test_multi_turn_patch_keeps_prior_context():
    base = QuerySpec(dataset="payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=-1))
    nxt = base.merge_patch({"date_range": {"offset": -2}})
    assert nxt.dataset == "payouts" and nxt.date_range.offset == -2
