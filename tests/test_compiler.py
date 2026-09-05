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
    # the property under test is that the value never reaches the SQL text
    assert "DROP TABLE" not in sql
    assert "?" in sql and "DROP TABLE" in str(params[0])


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


def test_the_mask_comes_from_the_decrypted_value_not_the_ciphertext():
    """Masking ciphertext yields "XXXXXXN5an" -- the last four base64 chars,
    which look like a masked account number and mean nothing. The mask is built
    once at load time from the decrypted value, and the full number is
    discarded, so the store holds no plaintext account number at all."""
    from app.compiler import evidence_columns
    cols = evidence_columns()
    assert "account_number_masked AS account_number" in cols
    assert "CAST(account_number" not in cols
    assert "utr_number" in cols and "[redacted]" in cols


def test_grouped_queries_exclude_null_group_keys():
    # a NULL counterparty is not a vendor; leaving it in makes tax + charges
    # top every spend ranking as a phantom entry
    sql, _, _ = compile_sql(QuerySpec(dataset="payouts", group_by=["counterparty"]), ANCHOR)
    assert "counterparty IS NOT NULL" in sql


def test_null_group_total_is_reported_not_dropped():
    from app.compiler import compile_null_group_sql
    out = compile_null_group_sql(QuerySpec(dataset="payouts", group_by=["counterparty"]), ANCHOR)
    assert out and "counterparty IS NULL" in out[0]
    assert compile_null_group_sql(QuerySpec(dataset="payouts"), ANCHOR) is None


def test_evidence_rows_match_the_aggregate_row_set():
    """The evidence panel must show the rows the number was computed from.
    Showing rows the aggregate excluded breaks the grounding claim."""
    from app.compiler import compile_evidence_sql
    spec = QuerySpec(dataset="payouts", group_by=["counterparty"])
    agg, _, _ = compile_sql(spec, ANCHOR)
    ev, _ = compile_evidence_sql(spec, ANCHOR)
    assert "counterparty IS NOT NULL" in agg
    assert "counterparty IS NOT NULL" in ev


def test_data_dictionary_types_are_forced_not_inferred():
    """account_number is VARCHAR(20) of digits. CSV inference reads it as
    BIGINT, which drops leading zeros and changes type again once the column
    arrives encrypted."""
    from app.data_dictionary import duckdb_types, declared
    assert declared()["account"]["account_number"] == "VARCHAR"
    assert duckdb_types("account")["account_number"] == "VARCHAR"
    assert duckdb_types("transaction")["transaction_date"] == "TIMESTAMP"
    assert duckdb_types("transaction")["transaction_amount"].startswith("DECIMAL")


def test_every_dictionary_table_is_known_to_the_loader():
    from app.data_dictionary import declared
    assert set(declared()) == {"bank", "account", "transaction"}
