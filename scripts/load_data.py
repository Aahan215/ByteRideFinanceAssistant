"""Load the real schema into DuckDB, enrich it, and build rollups.

Sources, in order of preference:
  1. a live MySQL database          (DB_HOST env var set -- the organisers' DB)
  2. data/raw/*.csv                     (organisers' full export)
  3. data/sample/seed.sql               (10 rows/table from the data dictionary)

The enrichment step is the important one: it parses a counterparty and a
channel out of each narration ONCE, so the assistant never does text parsing
at answer time.
"""
from __future__ import annotations
import os, pathlib, string, sys, time
import duckdb, pandas as pd, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.enrich import parse, canonical_map     # noqa: E402
from app.data_dictionary import duckdb_types    # noqa: E402

RAW, SAMPLE = ROOT / "data" / "raw", ROOT / "data" / "sample"
# Same override as app/db.py -- honoured here so `make load` (and this script
# directly) can target a scratch database without touching the real one.
DB = pathlib.Path(os.environ["FINANCE_DB_PATH"]) if os.getenv("FINANCE_DB_PATH") \
    else ROOT / "data" / "finance.duckdb"
SEMANTIC = yaml.safe_load((ROOT / "schema" / "semantic_layer.yaml").read_text())
TABLES = ["bank", "account", "transaction"]


def load_from_mysql(con) -> str:
    """Attach the organisers' MySQL database via DuckDB's mysql scanner and
    materialise the three source tables locally -- once, here -- so every
    later step (enrichment, rollups, stats) runs against local DuckDB exactly
    as it did against CSVs, at local-disk speed instead of round-tripping
    10M+ rows over the network per query.
    """
    host, port = os.environ["DB_HOST"], os.environ.get("DB_PORT", "3306")
    name, user, pw = os.environ["DB_NAME"], os.environ["DB_USER"], os.environ["DB_PASSWORD"]
    con.execute("INSTALL mysql")
    con.execute("LOAD mysql")
    conn_str = f"host={host} port={port} user={user} password={pw} database={name}"
    con.execute(f"ATTACH '{conn_str}' AS mysql_src (TYPE mysql)")
    for t in TABLES:
        con.execute(f'CREATE OR REPLACE TABLE "{t}" AS SELECT * FROM mysql_src."{t}"')
    con.execute("DETACH mysql_src")
    return f"mysql://{host}:{port}/{name}"


def load_source(con) -> str:
    if os.getenv("DB_HOST"):
        return load_from_mysql(con)
    csvs = {t: RAW / f"{t}.csv" for t in TABLES}
    if all(p.exists() for p in csvs.values()):
        for t, p in csvs.items():
            # Force the declared types. CSV inference reads the all-digit
            # account_number as BIGINT, which drops leading zeros and changes
            # type again once the column arrives encrypted.
            types = duckdb_types(t)
            cols = ", ".join(f"'{c}': '{ty}'" for c, ty in types.items())
            spec = f", columns={{{cols}}}" if cols else ""
            con.execute(f'CREATE OR REPLACE TABLE "{t}" AS '
                        f"SELECT * FROM read_csv('{p}', header=true{spec})")
        return "data/raw CSVs"
    seed = SAMPLE / "seed.sql"
    if seed.exists():
        con.execute(seed.read_text())
        return "data/sample/seed.sql (10 rows/table)"
    sys.exit("No data found. Put the organisers' CSVs in data/raw/.")


CHUNK = 250_000


def enrich(con, chunk: int = CHUNK) -> dict:
    """Parse narrations -> counterparty + category + channel.

    Chunked deliberately: pulling 20M descriptions into one Python list costs
    several GB and is the first thing that breaks when local row counts become
    production row counts. Throughput is ~95k rows/sec single-threaded, so
    20M is roughly 3.5 minutes of one-time ETL.

    Reports coverage, because an honest coverage number is worth more in the
    deck than an implied 100%.
    """
    total = con.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0]
    con.execute("""CREATE OR REPLACE TABLE txn_parsed (
        transaction_id VARCHAR, channel VARCHAR, counterparty_raw VARCHAR,
        counterparty VARCHAR, parsed_by VARCHAR, category VARCHAR, category_by VARCHAR)""")

    hits, by_rule, done, t0 = 0, {}, 0, time.time()
    while done < total:
        df = con.execute('SELECT transaction_id, description FROM "transaction" '
                         'LIMIT ? OFFSET ?', [chunk, done]).df()
        if df.empty:
            break
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
        con.register("parsed_chunk", out)
        con.execute("INSERT INTO txn_parsed SELECT * FROM parsed_chunk")
        con.unregister("parsed_chunk")

        hits += int(out["counterparty"].notna().sum())
        for k, v in out["parsed_by"].value_counts().items():
            by_rule[k] = by_rule.get(k, 0) + int(v)
        done += len(df)
        print(f"  enriching {done:,}/{total:,} "
              f"({done/max(time.time()-t0, 1e-9):,.0f} rows/s)", end="\r", flush=True)

    print(" " * 70, end="\r")
    return {"rows": done, "counterparty_hits": hits,
            "coverage": round(hits / done, 4) if done else 0.0, "by_rule": by_rule}


B64_ALPHABET = set(string.ascii_letters + string.digits + "+/=")


def looks_encrypted(value: str) -> bool:
    """Structural: a plaintext account number is digits; ciphertext is base64."""
    if not value or value.isdigit():
        return False
    return not (set(value) - B64_ALPHABET) and len(value) >= 20


def mask_account_numbers(con) -> str:
    """Store account_number ALREADY MASKED, so the full number never lands in
    the analytical store at all.

    Masking at query time cannot work once the column is encrypted: the last
    four characters of a base64 ciphertext are not the last four digits of the
    account. Decrypt here, keep only the last four, discard the rest -- there is
    no later step that needs more than that.
    """
    sample = con.execute("SELECT account_number FROM account "
                         "WHERE account_number IS NOT NULL LIMIT 1").fetchone()
    if not sample:
        return "no accounts"

    plain = [str(r[0]) for r in con.execute(
        "SELECT account_number FROM account WHERE account_number IS NOT NULL").fetchall()]
    mode = "plaintext"
    if looks_encrypted(str(sample[0])):
        # No blanket except here. A failed decrypt would silently mask the
        # CIPHERTEXT instead, producing "XXXXXX" plus four base64 characters
        # that look like an account number and are not.
        from app.crypto import decrypt, CryptoNotConfigured
        try:
            plain = [decrypt(v) or "" for v in plain]
            mode = "decrypted"
        except CryptoNotConfigured:
            # No key: store a full redaction. Never a mask built from
            # ciphertext -- "XXXXXX" plus four base64 characters looks like an
            # account number and means nothing, which is worse than showing
            # nothing because it invites the reader to trust it.
            con.execute("UPDATE account SET account_number = '[encrypted]'")
            return "no key -- fully redacted"

    ids = [r[0] for r in con.execute(
        "SELECT account_id FROM account WHERE account_number IS NOT NULL").fetchall()]
    masked = pd.DataFrame({"account_id": ids,
                           "masked": ["XXXXXX" + str(v)[-4:] for v in plain]})
    con.register("masked_df", masked)
    con.execute("""UPDATE account SET account_number = (
                     SELECT masked FROM masked_df m WHERE m.account_id = account.account_id)
                   WHERE account_id IN (SELECT account_id FROM masked_df)""")
    con.unregister("masked_df")
    return mode


def canonicalise(con) -> int:
    """Fold truncated counterparty names into their full form, once."""
    rows = con.execute("""SELECT counterparty, COUNT(*) FROM txn_parsed
                          WHERE counterparty IS NOT NULL GROUP BY 1""").fetchall()
    mapping = canonical_map([(r[0], r[1]) for r in rows])
    if not mapping:
        return 0
    df = pd.DataFrame({"from_name": list(mapping), "to_name": list(mapping.values())})
    con.register("canon_df", df)
    con.execute("CREATE OR REPLACE TABLE counterparty_canonical AS SELECT * FROM canon_df")
    con.unregister("canon_df")
    con.execute("""UPDATE txn_parsed SET counterparty = (
                     SELECT to_name FROM counterparty_canonical c
                     WHERE c.from_name = txn_parsed.counterparty)
                   WHERE counterparty IN (SELECT from_name FROM counterparty_canonical)""")
    return len(mapping)


def build_view(con, with_anomalies: bool = False):
    anomaly_cols = (", a.anomaly_score, a.typical_amount, a.history_n"
                    if with_anomalies else
                    ", NULL AS anomaly_score, NULL AS typical_amount, NULL AS history_n")
    anomaly_join = ("LEFT JOIN txn_anomaly a USING (transaction_id)"
                    if with_anomalies else "")
    con.execute(f"""
        CREATE OR REPLACE VIEW txn_enriched AS
        SELECT t.transaction_id, t.account_id, t.transaction_date, t.transaction_type,
               t.description, t.transaction_amount, t.transaction_reference_id,
               t.utr_number,
               p.channel, p.counterparty, p.counterparty_raw, p.parsed_by,
               p.category, p.category_by,
               acc.entity_id, acc.account_number, acc.program_id, acc.available_balance,
               acc.bank_code, b.bank_name
               {anomaly_cols}
        FROM "transaction" t
        LEFT JOIN txn_parsed p USING (transaction_id)
        LEFT JOIN account acc USING (account_id)
        LEFT JOIN bank    b   ON b.bank_code = acc.bank_code
        {anomaly_join}
    """)


def build_rollups(con):
    # Rollups collapse the 80% case (vendor/category by month) to a few
    # thousand rows, so those answers stay sub-millisecond at any table size.
    con.execute("""
        CREATE OR REPLACE TABLE rollup_counterparty_month AS
        SELECT date_trunc('month', transaction_date) AS month,
               counterparty, category, transaction_type,
               SUM(transaction_amount) AS sum_amount, COUNT(*) AS count
        FROM txn_enriched GROUP BY 1,2,3,4
    """)


def build_stats(con):
    """Per-vendor robust statistics, then the anomaly flags themselves.

    Scoring every row at query time costs ~150ms at 2M and would be seconds at
    20M. Anomalies are ~0.1% of rows, so we score once here and keep only the
    ones that clear the threshold -- a tiny table the query just joins to.
    """
    from app.anomaly import build_stats_sql, score_sql, THRESHOLD
    con.execute(build_stats_sql())
    n_stats = con.execute("SELECT COUNT(*) FROM counterparty_stats").fetchone()[0]

    con.execute(f"""
        CREATE OR REPLACE TABLE txn_anomaly AS
        SELECT * FROM (
            SELECT t.transaction_id, s.typical_amount, s.n AS history_n,
                   {score_sql()} AS anomaly_score
            FROM txn_enriched t JOIN counterparty_stats s USING (counterparty)
            WHERE t.transaction_amount > 0
        ) WHERE anomaly_score >= {THRESHOLD}
    """)
    n_flags = con.execute("SELECT COUNT(*) FROM txn_anomaly").fetchone()[0]
    return n_stats, n_flags


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    src = load_source(con)
    print(f"source: {src}")
    for t in TABLES:
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t:12} {n:>12,} rows")

    mask_mode = mask_account_numbers(con)
    stats = enrich(con)
    n_canon = canonicalise(con)
    build_view(con)
    build_rollups(con)
    nstats, nflags = build_stats(con)
    build_view(con, with_anomalies=True)      # re-declare the view to expose them

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
    print(f"canonicalised {n_canon} truncated vendor names into their full form")
    print(f"account numbers: {mask_mode}; only the last-4 mask is stored")
    total = con.execute("SELECT COUNT(*) FROM txn_enriched").fetchone()[0]
    print(f"\nanomaly detection: {nstats:,} counterparties with enough history, "
          f"{nflags:,} flagged rows ({100*nflags/max(total,1):.2f}%)")
    print(f"\ndate range: {lo} .. {hi}")
    print(f"ANCHOR DATE (the assistant's 'today'): {hi}")
    print(f"\ndone -> {DB}")
    con.close()


if __name__ == "__main__":
    main()
