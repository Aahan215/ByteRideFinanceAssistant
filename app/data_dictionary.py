"""The organisers' schema, parsed from schema/DATA_DICTIONARY.md.

Single source of truth for column types. Both the loader and the schema check
read it, so they cannot disagree about what the schema is.
"""
from __future__ import annotations
import functools, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DICT = ROOT / "schema" / "DATA_DICTIONARY.md"

# DDL type -> the DuckDB type to force on read.
DUCKDB_TYPE = {
    "VARCHAR": "VARCHAR",
    "ENUM": "VARCHAR",
    "INT": "INTEGER",
    "DECIMAL": "DECIMAL(18,2)",
    "TIMESTAMP": "TIMESTAMP",
}


@functools.lru_cache(maxsize=1)
def declared() -> dict[str, dict[str, str]]:
    """{table: {column: DDL_TYPE}} from the CREATE TABLE blocks."""
    out = {}
    for table, body in re.findall(r"CREATE TABLE\s+(\w+)\s*\((.*?)\n\)",
                                  DICT.read_text(), re.S):
        cols = {}
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY")):
                continue
            parts = line.split()
            if len(parts) >= 2:
                cols[parts[0]] = re.split(r"[(\s]", parts[1])[0].upper()
        out[table] = cols
    return out


def duckdb_types(table: str) -> dict[str, str]:
    """Column types to pass to read_csv, so inference cannot override the schema.

    This matters concretely: account_number is VARCHAR(20) of digits, and CSV
    inference reads it as BIGINT -- which drops leading zeros, overflows on long
    numbers, and silently changes type once the column arrives encrypted.
    """
    return {c: DUCKDB_TYPE.get(t, "VARCHAR") for c, t in declared().get(table, {}).items()}
