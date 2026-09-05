"""Run this against the REAL export before writing any crypto-dependent code.

Answers the three questions that decide the architecture:

  1. Is the encryption deterministic? -> can we join on ciphertext?
  2. Do transaction.account_id ciphertexts match account.account_id ciphertexts?
     -> can we join WITHOUT the key at all?
  3. What mode is implied by the ciphertext lengths?

Needs no key. Run it, paste the output in the team chat, decide, then build.
"""
from __future__ import annotations
import base64, pathlib, string, sys
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "finance.duckdb"
CANDIDATES = [("transaction", "account_id"), ("transaction", "utr_number"),
              ("account", "account_id"), ("account", "account_number"),
              ("account", "entity_id")]


B64_ALPHABET = set(string.ascii_letters + string.digits + "+/=")


def looks_encrypted(vals) -> bool:
    """Structural, not statistical. A plaintext UUID base64-decodes to 24 bytes
    and would otherwise be misread as ciphertext -- but it contains hyphens,
    which are outside the base64 alphabet."""
    sample = [v for v in vals if v][:50]
    if not sample:
        return False
    if any(set(str(v)) - B64_ALPHABET for v in sample):
        return False
    try:
        return all(len(base64.b64decode(v + "=" * (-len(v) % 4))) >= 16 for v in sample)
    except Exception:
        return False


def probe_column(con, table, col):
    try:
        vals = [r[0] for r in con.execute(f'SELECT "{col}" FROM "{table}"').fetchall()]
    except Exception:
        return
    nonnull = [v for v in vals if v]
    if not nonnull:
        return
    enc = looks_encrypted(nonnull)
    print(f"\n{table}.{col}")
    print(f"  rows {len(vals):,}  distinct {len(set(nonnull)):,}  encrypted-looking: {enc}")
    if not enc:
        print(f"  sample: {nonnull[0][:60]}")
        return

    raw = [base64.b64decode(v + "=" * (-len(v) % 4)) for v in nonnull[:200]]
    lens = sorted(set(len(r) for r in raw))
    block = all(l % 16 == 0 for l in lens)
    print(f"  ciphertext byte lengths: {lens[:6]}{'...' if len(lens) > 6 else ''}")
    print(f"  all multiples of 16: {block}  -> {'padded block mode (CBC/ECB)' if block else 'stream mode (CTR/CFB/GCM)'}")

    dupes = len(nonnull) - len(set(nonnull))
    print(f"  repeated ciphertexts: {dupes}  -> {'DETERMINISTIC (joinable on ciphertext)' if dupes else 'no repeats seen (inconclusive)'}")

    def lcp(a, b):
        n = 0
        while n < min(len(a), len(b)) and a[n] == b[n]: n += 1
        return n
    p = raw[0]
    for r in raw[1:]:
        p = p[:lcp(p, r)]
    if len(p) >= 16:
        print(f"  !! all ciphertexts share a {len(p)}-byte prefix -- fixed IV/nonce, "
              f"keystream reuse. Joinable, but leaks plaintext structure.")


def main():
    if not DB.exists():
        sys.exit("no database -- run `make load` first")
    con = duckdb.connect(str(DB), read_only=True)
    print("=== encrypted-column probe ===")
    for t, c in CANDIDATES:
        probe_column(con, t, c)

    print("\n=== cross-table join on ciphertext ===")
    try:
        n = con.execute("""SELECT COUNT(*) FROM "transaction" t
                           JOIN account a ON a.account_id = t.account_id""").fetchone()[0]
        total = con.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0]
        print(f"  {n:,}/{total:,} transactions join to an account as-is "
              f"({100*n/total:.1f}%)")
        if not any(looks_encrypted([r[0] for r in con.execute(
                'SELECT account_id FROM "transaction" LIMIT 50').fetchall()]) for _ in (0,)):
            print("  (account_id is still plaintext in this dataset -- rerun once "
                  "the encrypted export lands)")
        print("  -> joins work without the key" if n == total else
              "  -> MISMATCH: account_id is encrypted differently per table; decrypt in ETL")
    except Exception as e:
        print(f"  join failed: {e}")


if __name__ == "__main__":
    main()
