"""Generate a realistic synthetic dataset matching the organisers' schema.

Why generate rather than wait: the export has not landed, the problem statement
allows up to 20M records, and every downstream feature -- tax categorisation,
vendor grouping, anomaly detection, crypto handling -- needs volume and variety
to be worth testing. The ten sample rows contain zero tax transactions.

Deliberately reproduces the awkward parts of the real data:
  * the six narration formats seen in the sample (NEFT/IMPS/UPI/FT/R/ ...)
  * trailing branch/location noise on ~30% of vendor names, so the
    "SELECTION ELECTRONICS" vs "SELECTION ELECTRONICS DAHISAR EAST" grouping
    problem is present and testable
  * AES-256 with a FIXED nonce, matching the determinism observed in the sample
  * NULL reference ids and UTRs at realistic rates
  * a small number of genuine amount outliers, for the anomaly feature

Usage:
    python scripts/generate_dataset.py --rows 1000000
    python scripts/generate_dataset.py --rows 20000000 --format parquet
"""
from __future__ import annotations
import argparse, base64, os, pathlib, sys, time
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "raw"

BANKS = [
    ("HDFC", "HDFC BANK LIMITED"), ("ICIC", "ICICI BANK LIMITED"),
    ("SBIN", "STATE BANK OF INDIA"), ("UTIB", "AXIS BANK LIMITED"),
    ("KKBK", "KOTAK MAHINDRA BANK LIMITED"), ("CNRB", "CANARA BANK"),
    ("UBIN", "UNION BANK OF INDIA"), ("AUBL", "AU SMALL FINANCE BANK LIMITED"),
    ("TMBL", "TAMILNAD MERCANTILE BANK LIMITED"), ("RATN", "RBL BANK LIMITED"),
]

VENDORS = [
    "SELECTION ELECTRONICS", "SELECTION MOBILE", "NAVYUG SELECTION",
    "RELIANCEDIGITAL RETAIL LTD", "SELECTRICITY TWO PRIVATE LIMITED",
    "CROMA A DIVISION OF INFINITI", "VIJAY SALES INDIA PVT LTD",
    "UMANG SELECTION", "SHREE BALAJI TRADERS", "MAHALAXMI ENTERPRISES",
    "GANESH MOBILE WORLD", "SRI VENKATESHWARA AGENCIES", "AMBIKA TRADING CO",
    "NEW INDIA ELECTRONICS", "STAR COMMUNICATION", "DIGITAL WORLD RETAIL",
    "BIG BAZAAR RETAIL", "DMART AVENUE SUPERMARTS", "SPENCERS RETAIL LTD",
    "MORE MEGASTORE", "NILGIRIS SUPERMARKET", "METRO CASH AND CARRY",
    "SWIGGY INSTAMART", "ZOMATO HYPERPURE", "BLINKIT COMMERCE",
    "APOLLO PHARMACY", "MEDPLUS HEALTH SERVICES", "NETMEDS MARKETPLACE",
    "INDIAN OIL PETROL PUMP", "BHARAT PETROLEUM OUTLET", "HP FUEL STATION",
    "KALYAN JEWELLERS", "TANISHQ TITAN COMPANY", "MALABAR GOLD",
    "PANTALOONS FASHION", "WESTSIDE TRENT LTD", "SHOPPERS STOP LTD",
    "DECATHLON SPORTS INDIA", "IKEA INDIA PVT LTD", "HOME CENTRE LIFESTYLE",
    "LENSKART SOLUTIONS", "TITAN EYE PLUS", "BATA INDIA LIMITED",
    "SAI ENTERPRISES", "LAXMI TRADERS", "KRISHNA AGENCIES",
    "BHARAT TRADING COMPANY", "ROYAL ELECTRICALS", "MODERN HARDWARE STORES",
    "ANNAPURNA STORES", "JAI HIND PROVISION", "GUPTA GENERAL STORES",
]
# Attached to ~30% of vendor mentions. This is the grouping trap, on purpose.
BRANCHES = ["DAHISAR EAST", "SAKET DELHI", "ANDHERI WEST", "KORAMANGALA",
            "T NAGAR CHENNAI", "SALT LAKE KOLKATA", "HINJEWADI PUNE"]

# Wide enough that individual payees do not crowd out merchants in a
# spend ranking -- with a handful of names, person transfers dominate
# every "where did I spend the most" answer and the demo looks wrong.
_FIRST = ["GAUTAM", "RAJESH", "ANITA", "MOHAMMED", "PRIYA", "SURESH", "NEHA",
          "VIKRAM", "DEEPA", "ARJUN", "KAVITA", "SANJAY", "MEERA", "ROHIT",
          "SUNITA", "AMIT", "POOJA", "KARTHIK", "REKHA", "NIKHIL"]
_LAST = ["SINGH", "KUMAR", "DESAI", "FAROOQ", "NAIR", "IYER", "AGARWAL",
         "SHARMA", "PATEL", "REDDY", "GHOSH", "MENON", "JOSHI", "VERMA",
         "CHATTERJEE", "PILLAI", "BHATT", "RAO", "MISHRA", "KHAN"]
PEOPLE = [f"{f} {l}" for f in _FIRST for l in _LAST][:200]

# (category, weight, narration builder key, lognormal mu/sigma for amount)
CATEGORY_MIX = [
    ("MERCHANT",     0.34, "vendor",  9.4, 1.1),
    ("TRANSFER",     0.14, "person",  9.8, 1.3),
    ("BANK_CHARGES", 0.09, "charges", 4.6, 0.8),
    ("UTILITIES",    0.08, "utility", 7.4, 0.7),
    ("TAX",          0.07, "tax",    10.4, 1.0),
    ("EMI_LOAN",     0.07, "emi",     9.9, 0.6),
    ("CASH",         0.06, "cash",    8.6, 0.6),
    ("INVESTMENT",   0.05, "invest",  9.6, 0.9),
    ("CHEQUE",       0.04, "cheque", 10.1, 1.2),
    ("INSURANCE",    0.03, "insure",  9.2, 0.7),
    ("RENT",         0.02, "rent",   10.3, 0.4),
    ("SALARY",       0.01, "salary", 11.2, 0.4),
]

TAX_FORMS = ["GST PAYMENT CHALLAN {ref}", "CGST {ref}", "SGST {ref}",
             "IGST INPUT {ref}", "TDS 194C Q{q} FY26", "TCS COLLECTED {ref}",
             "ADVANCE TAX INSTALMENT {ref}", "INCOME TAX SELF ASSESSMENT {ref}"]
CHARGE_FORMS = ["IMPS charges", "NEFT CHARGES {ref}", "AMC FEE {ref}",
                "SMS CHG {ref}", "MIN BAL PENALTY", "COMMISSION ON COLLECTION {ref}"]
UTILITY_FORMS = ["BSES RAJDHANI {ref}", "MSEB ELECTRICITY {ref}", "AIRTEL BROADBAND {ref}",
                 "JIO RECHARGE {ref}", "MAHANAGAR GAS {ref}", "BESCOM ELECTRICITY {ref}"]
INVEST_FORMS = ["ZERODHA BROKING {ref}", "GROWW MUTUAL FUND SIP", "SIP HDFC MF {ref}",
                "DEMAT AMC {ref}", "UPSTOX {ref}"]


def uuids(rs, n):
    """UUID-shaped ids without a Python uuid call per row -- at 20M rows that
    difference is minutes."""
    a, b, c, d = (rs.integers(0, 2**32, n, dtype=np.uint32) for _ in range(4))
    return [f"{x:08x}-{y >> 16:04x}-{y & 0xffff:04x}-{z >> 16:04x}-{z & 0xffff:04x}{w:08x}"
            for x, y, z, w in zip(a, b, c, d)]


def rng_pick(rs, arr, n):
    return np.asarray(arr, dtype=object)[rs.integers(0, len(arr), n)]


def build_descriptions(rs, kinds, n, ifsc, refs):
    """Vectorised-ish narration builder. Formats mirror the real sample."""
    out = np.empty(n, dtype=object)
    vend = rng_pick(rs, VENDORS, n)
    branch = rng_pick(rs, BRANCHES, n)
    with_branch = rs.random(n) < 0.30            # the grouping trap
    people = rng_pick(rs, PEOPLE, n)
    accts = rs.integers(10**11, 10**14, n)
    chan = rng_pick(rs, ["NEFT", "IMPS", "UPI", "FT"], n)
    q = rs.integers(1, 5, n)

    for i in range(n):
        k, r = kinds[i], refs[i]
        if k == "vendor":
            name = f"{vend[i]} {branch[i]}" if with_branch[i] else vend[i]
            c = chan[i]
            if c == "NEFT":
                out[i] = f"NEFT  - {ifsc[i]} - {r} - {accts[i]} - {name}"
            elif c == "UPI":
                out[i] = f"UPI-{name}-XXXXXX{accts[i] % 10000}-{ifsc[i]}-{r}"
            elif c == "IMPS":
                out[i] = f"IMPS/P2A/{r}/{ifsc[i][:4]}/{accts[i]}/00/INET/{name}"
            else:
                out[i] = f"FT -  {r} -  {accts[i]} - {name}"
        elif k == "person":
            out[i] = f"IMPS OW/{r}/{people[i]}/{ifsc[i][:4]}/{accts[i]}"
        elif k == "tax":
            out[i] = TAX_FORMS[i % len(TAX_FORMS)].format(ref=r, q=q[i])
        elif k == "charges":
            out[i] = CHARGE_FORMS[i % len(CHARGE_FORMS)].format(ref=r)
        elif k == "utility":
            out[i] = UTILITY_FORMS[i % len(UTILITY_FORMS)].format(ref=r)
        elif k == "invest":
            out[i] = INVEST_FORMS[i % len(INVEST_FORMS)].format(ref=r)
        elif k == "emi":
            out[i] = f"EMI BAJAJ FINANCE LTD {r}"
        elif k == "cash":
            out[i] = f"ATM CASH WDL {r}"
        elif k == "cheque":
            out[i] = f"Cheque Deposits {r}"
        elif k == "insure":
            out[i] = f"LIC PREMIUM POLICY {r}"
        elif k == "rent":
            out[i] = f"NEFT/{r}/{ifsc[i][:4]}/RENT PAYMENT {people[i]}"
        else:
            out[i] = f"SALARY CREDIT {r}"
    return out


# --- AES-256, fixed nonce (matches the determinism seen in the sample) -------
def make_encryptor(key: bytes, nonce: bytes):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def enc(values):
        out = []
        for v in values:
            if v is None:
                out.append(None); continue
            c = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor()
            out.append(base64.b64encode(nonce + c.update(str(v).encode())).decode())
        return out
    return enc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--accounts", type=int, default=400)
    ap.add_argument("--entities", type=int, default=40)
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--format", choices=["csv", "parquet"], default="csv")
    ap.add_argument("--no-encrypt", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunk", type=int, default=500_000)
    a = ap.parse_args()

    rs = np.random.default_rng(a.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    key = nonce = None
    if not a.no_encrypt:
        raw = os.getenv("FINANCE_AES_KEY")
        key = base64.b64decode(raw) if raw else rs.bytes(32)
        nonce = rs.bytes(16)
        if not raw:
            print("FINANCE_AES_KEY not set -- generated one. Put this in .env:")
            print(f"  FINANCE_AES_KEY={base64.b64encode(key).decode()}")
            print(f"  FINANCE_AES_MODE=ctr\n")
    enc = make_encryptor(key, nonce) if key else (lambda v: list(v))

    # --- bank ---
    pd.DataFrame(BANKS, columns=["bank_code", "bank_name"]).to_csv(OUT / "bank.csv", index=False)

    # --- account ---
    acc_ids = uuids(rs, a.accounts)
    ent_ids = uuids(rs, a.entities)
    acc_entity = rng_pick(rs, ent_ids, a.accounts)
    accounts = pd.DataFrame({
        "account_id": enc(acc_ids),
        "entity_id": enc(acc_entity),
        "account_number": enc([str(x) for x in rs.integers(10**13, 10**14, a.accounts)]),
        "program_id": rs.choice([4, 21, 46], a.accounts),
        "available_balance": np.round(rs.normal(5e6, 4e7, a.accounts), 2),
        "bank_code": rng_pick(rs, [b[0] for b in BANKS], a.accounts),
    })
    accounts.to_csv(OUT / "account.csv", index=False)
    enc_acc_ids = accounts["account_id"].tolist()

    # --- transaction, in chunks so 20M fits in memory ---
    end = pd.Timestamp(a.end)
    start = end - pd.DateOffset(months=a.months)
    span = int((end - start).total_seconds())
    cats = [c[0] for c in CATEGORY_MIX]
    kinds_by_cat = {c[0]: c[2] for c in CATEGORY_MIX}
    weights = np.array([c[1] for c in CATEGORY_MIX]); weights = weights / weights.sum()
    mu = {c[0]: c[3] for c in CATEGORY_MIX}; sig = {c[0]: c[4] for c in CATEGORY_MIX}

    path = OUT / f"transaction.{a.format}"
    if path.exists():
        path.unlink()
    written, first, writer = 0, True, None

    while written < a.rows:
        n = min(a.chunk, a.rows - written)
        cat = rs.choice(cats, n, p=weights)
        kinds = np.array([kinds_by_cat[c] for c in cat], dtype=object)

        amounts = np.round(np.exp(rs.normal([mu[c] for c in cat], [sig[c] for c in cat])), 2)
        outlier = rs.random(n) < 0.0008          # genuine anomalies to detect
        amounts[outlier] *= rs.uniform(8, 25, outlier.sum())

        secs = rs.integers(0, span, n)
        dates = start + pd.to_timedelta(secs, unit="s")

        refs = np.where(rs.random(n) < 0.08, None,
                        np.array([f"S{x}" for x in rs.integers(10**7, 10**9, n)], dtype=object))
        ifsc = np.array([f"{b}0{x:06d}" for b, x in
                         zip(rng_pick(rs, [b[0] for b in BANKS], n), rs.integers(0, 10**6, n))], dtype=object)

        desc = build_descriptions(rs, kinds, n, ifsc,
                                  [r if r is not None else "NA" for r in refs])
        utrs = np.where(rs.random(n) < 0.40, None,
                        np.array([f"UTR{x}" for x in rs.integers(10**11, 10**12, n)], dtype=object))

        df = pd.DataFrame({
            "transaction_id": uuids(rs, n),
            "account_id": rng_pick(rs, enc_acc_ids, n),
            "transaction_date": dates,
            "transaction_type": np.where(np.isin(cat, ["SALARY"]) | (rs.random(n) < 0.22),
                                         "credit", "debit"),
            "description": desc,
            "transaction_amount": amounts,
            "transaction_reference_id": refs,
            "utr_number": enc(utrs),
        })

        if a.format == "csv":
            df.to_csv(path, mode="w" if first else "a", header=first, index=False)
        else:
            import pyarrow as pa, pyarrow.parquet as pq
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema)
            writer.write_table(table)
        first = False
        written += n
        print(f"  {written:,}/{a.rows:,} rows  ({time.time()-t0:.1f}s)", end="\r", flush=True)

    if writer:
        writer.close()
    print(f"\n\nwrote {a.rows:,} transactions, {a.accounts} accounts, {len(BANKS)} banks")
    print(f"  -> {OUT}  ({time.time()-t0:.1f}s, encryption {'off' if a.no_encrypt else 'AES-256-CTR fixed nonce'})")


if __name__ == "__main__":
    main()
