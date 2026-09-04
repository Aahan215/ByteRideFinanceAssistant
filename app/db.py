"""DuckDB connection + the data anchor date. Read-only by construction."""
from __future__ import annotations
import functools, pathlib, datetime
import duckdb, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "finance.duckdb"
SEMANTIC = yaml.safe_load((ROOT / "schema" / "semantic_layer.yaml").read_text())


@functools.lru_cache(maxsize=1)
def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


@functools.lru_cache(maxsize=1)
def anchor_date() -> datetime.date:
    """'Today' for the assistant = the latest date present in the data."""
    table, col = SEMANTIC["anchor"]["source"].split(".")
    return connect().execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]


def run(sql: str, params: list | None = None):
    return connect().execute(sql, params or []).df()
