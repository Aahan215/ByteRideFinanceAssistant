import datetime
from app.spec import QuerySpec, DateRange, Filters
from app.compiler import compile_sql

ANCHOR = datetime.date(2024, 3, 17)


def test_last_month_window_is_anchored_to_data_not_wall_clock():
    spec = QuerySpec(dataset="vendor_payouts", metric="sum_amount",
                     date_range=DateRange(kind="relative", unit="month", offset=-1))
    sql, params, meta = compile_sql(spec, ANCHOR)
    assert meta["window"] == (datetime.date(2024, 2, 1), datetime.date(2024, 3, 1))


def test_filters_are_bound_parameters_not_interpolated():
    spec = QuerySpec(dataset="transactions", filters=Filters(vendor="'; DROP TABLE t;--"))
    sql, params, _ = compile_sql(spec, ANCHOR)
    assert "DROP TABLE" not in sql and params[0] == "'; DROP TABLE t;--"


def test_multi_turn_patch_keeps_prior_context():
    base = QuerySpec(dataset="vendor_payouts",
                     date_range=DateRange(kind="relative", unit="month", offset=-1))
    nxt = base.merge_patch({"date_range": {"offset": -2}})
    assert nxt.dataset == "vendor_payouts" and nxt.date_range.offset == -2
