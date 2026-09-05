"""Load the real schema into DuckDB, enrich it, and build rollups.

Sources, in order of preference:
  1. data/raw/*.csv                     (organisers' full export)
  2. data/sample/seed.sql               (10 rows/table from the data dictionary)

The enrichment step is the important one: it parses a counterparty and a
channel out of each narration ONCE, so the assistant never does text parsing
at answer time.
"""
from __future__ import annotations
import pathlib, sys
import duckdb, pandas as pd, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.enrich import parse   # noqa: E402

RAW, SAMPLE, DB = ROOT / "data" / "raw", ROOT / "data" / "sample", ROOT / "data" / "finance.duckdb"
SEMANTIC = yaml.safe_load((ROOT / "schema" / "semantic_layer.yaml").read_text())
TABLES = ["bank", "account", "transaction"]


def load_source(con) -> str:
    csvs = {t: RAW / f"{t}.csv" for t in TABLES}
    if all(p.exists() for p in csvs.values()):
        for t, p in csvs.items():
            con.execute(f'CREATE OR REPLACE TABLE "{t}" AS SELECT * FROM read_csv_auto(?)', [str(p)])
        return "data/raw CSVs"
    seed = SAMPLE / "seed.sql"
    if seed.exists():
        con.execute(seed.read_text())
        return "data/sample/seed.sql (10 rows/table)"
    sys.exit("No data found. Put the organisers' CSVs in data/raw/.")


def enrich(con) -> dict:
    """Parse narrations -> counterparty + channel. Reports coverage, because an
    honest coverage number is worth more in the deck than an implied 100%."""
    df = con.execute('SELECT transaction_id, description FROM "transaction"').df()
    parsed = [parse(d) for d in df["description"]]
    out = pd.DataFrame({
        "transaction_id": df["transaction_id"],
        "channel": [p.channel for p in parsed],
        "counterparty_raw": [p.counterparty_raw for p in parsed],
        "counterparty": [p.counterparty for p in parsed],
        "parsed_by": [p.parsed_by for p in parsed],
        "category": [p.category for p in parsed],
        "category_by": [p.category_by for p in parsed],
    })
    con.register("parsed_df", out)
    con.execute("CREATE OR REPLACE TABLE txn_parsed AS SELECT * FROM parsed_df")
    hit = int(out["counterparty"].notna().sum())
    return {"rows": len(out), "counterparty_hits": hit,
            "coverage": round(hit / len(out), 4) if len(out) else 0.0,
            "by_rule": out["parsed_by"].value_counts().to_dict()}


def build_view(con):
    con.execute("""
        CREATE OR REPLACE VIEW txn_enriched AS
        SELECT t.transaction_id, t.account_id, t.transaction_date, t.transaction_type,
               t.description, t.transaction_amount, t.transaction_reference_id,
               t.utr_number,
               p.channel, p.counterparty, p.counterparty_raw, p.parsed_by,
               p.category, p.category_by,
               a.entity_id, a.account_number, a.program_id, a.available_balance,
               a.bank_code, b.bank_name
        FROM "transaction" t
        LEFT JOIN txn_parsed p USING (transaction_id)
        LEFT JOIN account a  USING (account_id)
        LEFT JOIN bank    b  ON b.bank_code = a.bank_code
    """)


def build_rollups(con):
    con.execute("""
        CREATE OR REPLACE TABLE rollup_counterparty_month AS
        SELECT date_trunc('month', transaction_date) AS month,
               counterparty, category, transaction_type,
               SUM(transaction_amount) AS sum_amount, COUNT(*) AS count
        FROM txn_enriched GROUP BY 1,2,3,4
    """)


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    src = load_source(con)
    print(f"source: {src}")
    for t in TABLES:
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t:12} {n:>12,} rows")

    stats = enrich(con)
    build_view(con)
    build_rollups(con)

    lo, hi = con.execute("SELECT MIN(transaction_date), MAX(transaction_date) FROM txn_enriched").fetchone()
    print(f"\nenrichment: counterparty parsed for {stats['counterparty_hits']}/{stats['rows']} "
          f"({stats['coverage']:.1%})")
    for rule, n in sorted(stats["by_rule"].items(), key=lambda kv: -kv[1]):
        print(f"  {rule:22} {n:>10,}")
    cats = con.execute("""SELECT category, COUNT(*) n FROM txn_enriched
                          GROUP BY 1 ORDER BY n DESC""").fetchall()
    print("\ncategories:")
    for c, n in cats:
        print(f"  {c:16} {n:>10,}")
    print(f"\ndate range: {lo} .. {hi}")
    print(f"ANCHOR DATE (the assistant's 'today'): {hi}")
    print(f"\ndone -> {DB}")
    con.close()


if __name__ == "__main__":
    main()
