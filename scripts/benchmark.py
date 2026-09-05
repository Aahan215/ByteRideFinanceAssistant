"""Query latency at whatever scale the database currently holds.

Run after every load so the demo-latency claim in the deck is measured, not
asserted. `make bench`.
"""
from __future__ import annotations
import pathlib, statistics, sys, time
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "finance.duckdb"

QUERIES = [
    ("spend by vendor, one month",
     """SELECT counterparty, SUM(transaction_amount) s FROM txn_enriched
        WHERE transaction_type='debit' AND counterparty IS NOT NULL
          AND transaction_date >= '2026-06-01' AND transaction_date < '2026-07-01'
        GROUP BY 1 ORDER BY s DESC LIMIT 10"""),
    ("total tax, 3 months",
     """SELECT SUM(transaction_amount) FROM txn_enriched WHERE transaction_type='debit'
        AND category='TAX' AND transaction_date >= '2026-04-01'"""),
    ("category breakdown, full table",
     "SELECT category, SUM(transaction_amount) FROM txn_enriched GROUP BY 1"),
    ("drill-down evidence, 200 rows",
     """SELECT transaction_id, transaction_date, description, transaction_amount
        FROM txn_enriched WHERE transaction_type='debit' AND category='TAX'
        ORDER BY transaction_date DESC LIMIT 200"""),
    ("spend by vendor, via rollup",
     """SELECT counterparty, SUM(sum_amount) s FROM rollup_counterparty_month
        WHERE transaction_type='debit' AND month='2026-06-01'
        GROUP BY 1 ORDER BY s DESC LIMIT 10"""),
]


def main():
    if not DB.exists():
        sys.exit("no database -- run `make load` first")
    con = duckdb.connect(str(DB), read_only=True)
    n = con.execute("SELECT COUNT(*) FROM txn_enriched").fetchone()[0]
    print(f"rows: {n:,}\n{'query':34} {'p50':>9} {'max':>9}\n" + "-" * 54)
    for label, sql in QUERIES:
        try:
            con.execute(sql).fetchall()           # warm
            ts = []
            for _ in range(5):
                t = time.perf_counter(); con.execute(sql).fetchall()
                ts.append(1000 * (time.perf_counter() - t))
            print(f"{label:34} {statistics.median(ts):7.1f}ms {max(ts):7.1f}ms")
        except Exception as e:
            print(f"{label:34}   skipped ({str(e)[:40]})")


if __name__ == "__main__":
    main()
