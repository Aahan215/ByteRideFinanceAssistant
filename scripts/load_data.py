"""Load the organisers' flat files into DuckDB + build rollups.
Adjust the FILES map when the real dataset lands -- nothing else should change."""
import pathlib, sys, duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW, DB = ROOT / "data" / "raw", ROOT / "data" / "finance.duckdb"

FILES = {
    "transactions": "transactions.csv",
    "vendor_payouts": "vendor_payouts.csv",
    "vendors": "vendors.csv",
    "chart_of_accounts": "chart_of_accounts.csv",
}

con = duckdb.connect(str(DB))
for table, fname in FILES.items():
    path = RAW / fname
    if not path.exists():
        print(f"  skip {table}: {path} not found"); continue
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")
    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  loaded {table}: {n:,} rows")

# Rollups: sub-millisecond answers for the 80% of questions that are
# vendor-by-month or category-by-month aggregates.
try:
    con.execute("""CREATE OR REPLACE TABLE rollup_vendor_month AS
        SELECT date_trunc('month', txn_date) AS month, vendor_id, status,
               SUM(amount) AS sum_amount, COUNT(*) AS count
        FROM transactions GROUP BY 1,2,3""")
    print("  built rollup_vendor_month")
except Exception as e:
    print(f"  rollup skipped: {e}")
con.close()
print(f"\nDone -> {DB}")
