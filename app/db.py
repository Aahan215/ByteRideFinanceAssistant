"""DuckDB connection + the data anchor date. Read-only by construction."""
from __future__ import annotations
import functools, os, pathlib, datetime
import duckdb, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Optional override so tooling/tests can point at a scratch database without
# touching the real one at data/finance.duckdb. Unset in production -- the
# deployed instance just uses the default path built during the Render build.
DB_PATH = pathlib.Path(os.environ["FINANCE_DB_PATH"]) if os.getenv("FINANCE_DB_PATH") \
    else ROOT / "data" / "finance.duckdb"
SEMANTIC = yaml.safe_load((ROOT / "schema" / "semantic_layer.yaml").read_text())


@functools.lru_cache(maxsize=1)
def _root(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    # A fresh cursor per call, not the shared root connection -- threads in
    # FastAPI's threadpool sharing one DuckDB connection get None back (a
    # racing execute() beat them to the result) or, worse, another thread's
    # result silently swapped in. That's a 500 at best, a wrong number at
    # worst. `.cursor()` is an independent connection over the same database.
    return _root(read_only).cursor()


connect.cache_clear = _root.cache_clear


ANCHOR_MODE = os.getenv("FINANCE_ANCHOR_MODE") or SEMANTIC["anchor"].get("mode", "data")


@functools.lru_cache(maxsize=1)
def data_max_date() -> datetime.date:
    """The latest transaction in the dataset."""
    _, col = SEMANTIC["anchor"]["source"].split(".")
    val = connect().execute(f"SELECT MAX({col}) FROM {SEMANTIC['base_view']}").fetchone()[0]
    return val.date() if hasattr(val, "date") else val


@functools.lru_cache(maxsize=1)
def anchor_date() -> datetime.date:
    """'Today' for the assistant. See `anchor.mode` in the semantic layer."""
    return datetime.date.today() if ANCHOR_MODE == "wall_clock" else data_max_date()


def anchor_status() -> dict:
    """Whether the chosen anchor actually has data behind it.

    In wall_clock mode against a historical export, every relative-date question
    silently matches zero rows -- the worst kind of wrong answer. Surfaced at
    /health so the UI can say so rather than letting a demo quietly break.
    """
    latest, today = data_max_date(), datetime.date.today()
    stale = ANCHOR_MODE == "wall_clock" and today > latest
    return {
        "mode": ANCHOR_MODE,
        "anchor_date": str(anchor_date()),
        "data_latest": str(latest),
        "stale": stale,
        "warning": (
            f"Anchor is the wall clock ({today}) but the data ends {latest}. "
            f"Relative dates like 'this month' will match no transactions. "
            f"Set anchor.mode to 'data' in schema/semantic_layer.yaml."
        ) if stale else None,
    }


def run(sql: str, params: list | None = None):
    return connect().execute(sql, params or []).df()


REQUIRED_DERIVED = ("txn_parsed", "counterparty_stats", "txn_anomaly", "txn_enriched")


def etl_problems(con) -> list[str]:
    """What load_data.py owes the query path, checked against a caller-supplied
    connection -- not the module-level `connect()`, since schema_check.py may
    be looking at a different database file.
    """
    problems = []
    have = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    for name in REQUIRED_DERIVED:
        if name not in have:
            problems.append(f"MISSING {name} -- run `make load`")

    # A source table can be reloaded without re-running enrichment, and that
    # mismatch surfaces as wrong answers (stale rows), not an error.
    if "transaction" in have and "txn_parsed" in have:
        n_txn = con.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0]
        n_parsed = con.execute("SELECT COUNT(*) FROM txn_parsed").fetchone()[0]
        if n_txn != n_parsed:
            problems.append(
                f"txn_parsed ({n_parsed:,} rows) is stale relative to "
                f"transaction ({n_txn:,} rows) -- re-run `make load`.")
    return problems


def etl_status() -> dict:
    """For /health. Must never raise -- its entire job is reporting brokenness,
    so it has to still answer when the DB file is missing or corrupt."""
    try:
        problems = etl_problems(connect())
        ready = not problems
        hint = None if ready else (
            "The database has the source tables but not the derived ones. "
            "Run `make load` (about 40s at 2M rows) before asking questions.")
        return {"ready": ready, "problems": problems, "hint": hint}
    except Exception as e:
        # Unlike the missing-derived-objects case above, the DB never opened,
        # so "source tables present" would be a lie -- give a different hint.
        return {"ready": False, "problems": [str(e)], "hint": (
            "No queryable database at data/finance.duckdb. Put the source "
            "CSVs in data/raw/ and run `make load`.")}
