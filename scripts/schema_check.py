"""Verify the loaded database matches the organisers' data dictionary.

Run it whenever new data arrives. A silently renamed, dropped or retyped column
surfaces as a wrong answer rather than an error, which is the worst way to find
out about it.
"""
from __future__ import annotations
import pathlib, re, sys
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.data_dictionary import declared        # noqa: E402

DB = ROOT / "data" / "finance.duckdb"

TYPE_EQUIV = {
    "VARCHAR": {"VARCHAR", "TEXT", "STRING"},
    "INT": {"INTEGER", "BIGINT", "INT", "HUGEINT"},
    "DECIMAL": {"DECIMAL", "DOUBLE", "FLOAT", "NUMERIC"},
    "TIMESTAMP": {"TIMESTAMP", "TIMESTAMP_NS", "DATETIME"},
    "ENUM": {"VARCHAR", "TEXT", "ENUM"},
}


def actual(con, table) -> dict[str, str]:
    try:
        rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    except Exception:
        return {}
    return {r[1]: re.split(r"[(\s]", r[2])[0].upper() for r in rows}


def compatible(want: str, got: str) -> bool:
    return got in TYPE_EQUIV.get(want, {want})


def main():
    if not DB.exists():
        sys.exit("no database -- run `make load` first")
    con = duckdb.connect(str(DB), read_only=True)
    problems = []

    for table, cols in declared().items():
        have = actual(con, table)
        if not have:
            problems.append(f"MISSING TABLE  {table}")
            print(f"\n{table}  MISSING")
            continue
        print(f"\n{table}  ({len(have)} columns)")
        for col, want in cols.items():
            got = have.get(col)
            if got is None:
                problems.append(f"MISSING COLUMN {table}.{col}")
                print(f"  {'MISSING':8} {col}")
            elif not compatible(want, got):
                problems.append(f"TYPE {table}.{col}: declared {want}, loaded {got}")
                print(f"  {'TYPE':8} {col:26} declared {want}, loaded {got}")
            else:
                print(f"  {'ok':8} {col:26} {got}")
        for extra in sorted(set(have) - set(cols)):
            print(f"  {'extra':8} {extra:26} {have[extra]}  (not in the dictionary)")

    print("\n" + "-" * 62)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Schema matches the data dictionary.")


if __name__ == "__main__":
    main()
