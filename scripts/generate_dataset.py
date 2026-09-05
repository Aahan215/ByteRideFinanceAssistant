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

Second pass adds the things a flat, uniform generator gets wrong:
  * transaction_type actually depends on category (an ATM withdrawal is not
    22% "credit")
  * recurring mandates -- EMI/rent/insurance/SIP/salary/utilities repeat
    month over month on the same account, same counterparty, same day
  * a non-uniform clock: weekday/hour/day-of-month/festive/growth shape
  * round-number amounts (real payments snap to denominations; the sample
    was 99% paise, which is backwards)
  * reversals and duplicate postings, at the rates real ledgers show them
  * genuine self-transfers between one entity's own accounts -- the
    double-counting trap -- with the real account number embedded in the
    narration and nothing else giving it away
  * a long-tailed, skewed portfolio: most entities have one account, a few
    have dozens; most accounts are quiet, a few carry most of the volume

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

# Entities own accounts and, for the self-transfer trap, need a display name
# that shows up in NEFT/IMPS/UPI narrations the way a real beneficiary name
# would.
ENTITY_NAMES = [
    "SHIVAM TEXTILES PVT LTD", "AAKASH TRADING CO", "VARDHAN AGRO EXPORTS",
    "GALAXY FOODS PRIVATE LIMITED", "SUNRISE PLASTICS INDUSTRIES",
    "NAVKAR LOGISTICS PVT LTD", "OMKAR STEEL TRADERS", "RIDDHI SIDDHI ENTERPRISES",
    "BLUE OCEAN GARMENTS LLP", "GREENFIELD AGRO PRODUCTS", "SHREE KRISHNA TRADERS",
    "MAHESH ENGINEERING WORKS", "PARAMOUNT PACKAGING CO", "VINAYAK CHEMICALS PVT LTD",
    "UNITY ELECTRONICS TRADING", "SILVER LEAF HOSPITALITY", "KAVERI RICE MILLS",
    "AMBER CONSTRUCTIONS PVT LTD", "TRIMURTI AUTO SPARES", "NEW HORIZON EXPORTS",
    "GOLDEN GATE APPARELS", "VISHWAKARMA IRON WORKS", "SAPPHIRE INTERIORS LLP",
    "CENTURY PAPER MILLS", "EASTERN SPICE TRADING CO", "NORTHSTAR PHARMA PVT LTD",
    "DIVINE JEWELS AND GEMS", "PRAGATI DAIRY PRODUCTS", "MANGALAM COTTON MILLS",
    "SKYLINE REALTORS PVT LTD", "HARIOM FERTILISERS CO", "CRYSTAL WATER SOLUTIONS",
    "PRIME MOTORS PRIVATE LIMITED", "WELLNESS HERBAL PRODUCTS", "ORIENT CARPETS EXPORT",
    "ANMOL JEWELLERS PVT LTD", "SATYAM PLYWOOD INDUSTRIES", "ROYAL LEATHER GOODS CO",
    "INFINITY SOFTWARE SOLUTIONS", "BHARAT SEEDS AND AGRO", "LOTUS AYURVEDA PVT LTD",
    "STARLIGHT EVENTS AND CATERING", "ADITYA CEMENT TRADERS", "NEW ERA PLASTICS CO",
    "VRINDAVAN SWEETS PVT LTD", "MODERN FOOTWEAR INDUSTRIES", "GLOBAL FREIGHT CARRIERS",
    "SHUBHAM STEEL ROLLING MILLS", "PARIVAR RETAIL CHAIN PVT LTD", "TRUEWORTH FINANCE CO",
    "EMERALD TEXTILE MILLS", "KRISHNA OIL AND OILSEEDS", "NATIONAL TIMBER TRADERS",
    "SAROJINI HANDICRAFTS EXPORT", "PIONEER PRINTING PRESS", "AASTHA MEDICAL SUPPLIES",
    "VASUNDHARA REALTY VENTURES", "CHAMPION SPORTS GOODS CO", "HERITAGE SILK HOUSE",
    "BRIGHTWAY SOLAR ENERGY PVT LTD", "KAMAL AUTO ANCILLARIES", "TRUSTLINE INSURANCE BROKERS",
]

# Per-mandate fixed counterparties for recurring rows (change 2). Small,
# closed pools so the same lender/insurer/employer repeats -- that repetition
# is the point of a "fixed counterparty".
LENDERS = ["BAJAJ FINANCE LTD", "HDFC MFIN", "TATA CAPITAL LTD",
           "L AND T FINANCE LTD", "MUTHOOT FINANCE LTD"]
INSURERS = ["LIC", "HDFC LIFE", "ICICI PRUDENTIAL", "SBI LIFE", "MAX LIFE"]
EMPLOYERS = ["INFOSYS BPO", "TCS LTD", "WIPRO LTD", "ACCENTURE SOLUTIONS",
             "CAPGEMINI INDIA", "BIRLASOFT LTD", "MPHASIS LTD", "CTS INDIA"]

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

# Per-category probability that a row of that category is a credit (change 1).
# An ATM withdrawal is a debit; a cash deposit is the rare exception -- the
# old code flipped 22% of EVERY category to "credit" regardless of what it
# was, which put 26k ATM withdrawals on the credit side.
CREDIT_PROB = {
    "SALARY": 1.00, "TRANSFER": 0.45, "INVESTMENT": 0.20, "CHEQUE": 0.85,
    "CASH": 0.15, "MERCHANT": 0.03, "RENT": 0.02, "TAX": 0.02,
    "UTILITIES": 0.01, "INSURANCE": 0.01, "BANK_CHARGES": 0.01, "EMI_LOAN": 0.005,
}

# Categories eligible to become recurring mandates (change 2).
RECURRING_CATS = ["EMI_LOAN", "RENT", "INSURANCE", "INVESTMENT", "SALARY", "UTILITIES"]

TAX_FORMS = ["GST PAYMENT CHALLAN {ref}", "CGST {ref}", "SGST {ref}",
             "IGST INPUT {ref}", "TDS 194C Q{q} FY26", "TCS COLLECTED {ref}",
             "ADVANCE TAX INSTALMENT {ref}", "INCOME TAX SELF ASSESSMENT {ref}"]
CHARGE_FORMS = ["IMPS charges", "NEFT CHARGES {ref}", "AMC FEE {ref}",
                "SMS CHG {ref}", "MIN BAL PENALTY", "COMMISSION ON COLLECTION {ref}"]
UTILITY_FORMS = ["BSES RAJDHANI {ref}", "MSEB ELECTRICITY {ref}", "AIRTEL BROADBAND {ref}",
                 "JIO RECHARGE {ref}", "MAHANAGAR GAS {ref}", "BESCOM ELECTRICITY {ref}"]
INVEST_FORMS = ["ZERODHA BROKING {ref}", "GROWW MUTUAL FUND SIP", "SIP HDFC MF {ref}",
                "DEMAT AMC {ref}", "UPSTOX {ref}"]

# Denominations real payments snap to (change 4). Largest denom <= amount/2.
DENOMS = np.array([10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000])

# Long-tailed entity size distribution (change 7): (min, max, weight).
SIZE_BUCKETS = [(1, 1, 0.55), (2, 2, 0.20), (3, 3, 0.10),
                (4, 6, 0.08), (7, 12, 0.05), (13, 25, 0.02)]


def uuids(rs, n):
    """UUID-shaped ids without a Python uuid call per row -- at 20M rows that
    difference is minutes."""
    a, b, c, d = (rs.integers(0, 2**32, n, dtype=np.uint32) for _ in range(4))
    return [f"{x:08x}-{y >> 16:04x}-{y & 0xffff:04x}-{z >> 16:04x}-{z & 0xffff:04x}{w:08x}"
            for x, y, z, w in zip(a, b, c, d)]


def rng_pick(rs, arr, n):
    return np.asarray(arr, dtype=object)[rs.integers(0, len(arr), n)]


# --- change 7: long-tailed accounts-per-entity ------------------------------
def draw_entity_sizes(rs, n_accounts, min_entities):
    """Keep drawing entities from the size distribution until all accounts are
    allocated, truncating the last one to fit exactly. --entities is now a
    floor: if the draw naturally produced fewer entities than that, split the
    largest ones down to size-1 until the floor is met (accounts total is
    unchanged either way)."""
    if n_accounts <= 0:
        return []
    p = np.array([b[2] for b in SIZE_BUCKETS]); p = p / p.sum()
    sizes, total = [], 0
    while total < n_accounts:
        lo, hi, _ = SIZE_BUCKETS[rs.choice(len(SIZE_BUCKETS), p=p)]
        sz = lo if lo == hi else int(rs.integers(lo, hi + 1))
        sizes.append(sz)
        total += sz
    overflow = total - n_accounts
    if overflow > 0:
        sizes[-1] -= overflow
    while len(sizes) < min_entities:
        j = int(np.argmax(sizes))
        if sizes[j] <= 1:
            break  # every entity is already single-account; floor unreachable
        sizes[j] -= 1
        sizes.append(1)
    return sizes


# --- change 8: account-biased counterparty sets + volume skew ---------------
def build_home_sets(rs, n_accounts, pool_len, lo, hi):
    """Each account gets a fixed 'home' subset of size lo..hi from the pool.
    Padding slots beyond an account's own size are never indexed (see
    home_biased_pick) so they are left as zeros."""
    k_max = hi
    sizes = rs.integers(lo, hi + 1, n_accounts)
    idx = np.zeros((n_accounts, k_max), dtype=np.int64)
    for acc in range(n_accounts):
        idx[acc, :sizes[acc]] = rs.choice(pool_len, size=sizes[acc], replace=False)
    return idx, sizes


def home_biased_pick(rs, acct_idx, home_idx, home_size, pool):
    """90% of an account's vendor/person rows draw from its home set, 10% from
    the full pool. Vectorised: home_idx[acct_idx, slot] with slot bounded by
    that account's own home size."""
    n = len(acct_idx)
    is_home = rs.random(n) < 0.90
    slot = (rs.random(n) * home_size[acct_idx]).astype(int)
    home_choice = home_idx[acct_idx, slot]
    full_choice = rs.integers(0, len(pool), n)
    chosen = np.where(is_home, home_choice, full_choice)
    return np.asarray(pool, dtype=object)[chosen]


def account_weights(rs, n_accounts):
    """Power-law transaction volume per account (real portfolios are not
    uniform: a handful of accounts carry most of the traffic). ~3% are
    genuinely dormant: weight exactly 0, so rs.choice never selects them for
    a one-off transaction. Guarantees at least one non-dormant account so a
    small --accounts value (e.g. 5) can never zero out the whole portfolio.
    Returns (normalized weights, dormant boolean mask) -- callers that build
    recurring mandates or self-transfer legs need the mask too, since those
    passes don't go through this weight vector at all."""
    w = rs.lognormal(mean=0.0, sigma=1.25, size=n_accounts)
    dormant = rs.random(n_accounts) < 0.03
    if dormant.all():
        dormant[int(rs.integers(0, n_accounts))] = False
    w[dormant] = 0.0
    return w / w.sum(), dormant


# --- change 3: realistic time-of-transaction distribution -------------------
def build_time_distribution(start, end):
    """Per-day and per-hour weight vectors over the full window, instead of
    uniform seconds. Weekday/day-of-month/hour shape plus a slow growth trend
    and an Oct/Nov festive bump."""
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    wd = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.55, 0.25])  # Mon..Sun
    w = wd[days.weekday]
    dom = days.day.to_numpy()
    dim = days.days_in_month.to_numpy()
    mult = np.ones(len(days))
    mult[dom <= 5] = 1.6          # salary/rent cycle
    mult[dom == 20] = 1.9         # GST
    mult[dom > dim - 3] = 1.5     # month close
    w = w * mult
    month_idx = (days.year - start.year) * 12 + (days.month - start.month)
    w = w * (1.015 ** month_idx)  # growth trend
    festive = np.isin(days.month, [10, 11])
    w = np.where(festive, w * 1.25, w)
    w = w / w.sum()

    hour = np.array([
        0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.05,   # 0-6 near-zero
        0.35, 0.55, 0.65,                            # 7-9 ramp
        0.90, 1.00, 1.00, 0.95,                      # 10-13 peak
        0.60,                                        # 14 lull
        0.85, 0.95, 1.00, 1.00, 0.90,                # 15-19 peak
        0.50, 0.30, 0.15, 0.08,                      # 20-23 taper
    ])
    hour = hour / hour.sum()
    return days, w, hour


def sample_datetimes(rs, n, days, day_probs, hour_probs):
    day_idx = rs.choice(len(days), n, p=day_probs)
    hour = rs.choice(24, n, p=hour_probs)
    minute = rs.integers(0, 60, n)
    second = rs.integers(0, 60, n)
    return (days[day_idx] + pd.to_timedelta(hour, unit="h")
            + pd.to_timedelta(minute, unit="m") + pd.to_timedelta(second, unit="s"))


# --- change 4: round-number amounts ------------------------------------------
def realistic_amounts(rs, raw, cats):
    """Real payments are round numbers far more often than not. 15% keep
    paise (preferentially bank charges/tax); of the rest, ~45% snap to the
    largest clean denomination <= amount/2, so a ~1,200 payment can become
    1,000, not 0."""
    n = len(raw)
    paise_prob = np.where(np.isin(cats, ["BANK_CHARGES", "TAX"]), 0.5, 0.10)
    keep_paise = rs.random(n) < paise_prob
    whole = np.round(raw)
    half = whole / 2
    has_denom = half >= DENOMS[0]
    idx = np.clip(np.searchsorted(DENOMS, half, side="right") - 1, 0, len(DENOMS) - 1)
    denom = DENOMS[idx].astype(float)
    snap = (~keep_paise) & has_denom & (rs.random(n) < 0.45)
    out = np.where(keep_paise, raw, whole)
    out = np.where(snap, denom, out)
    return np.round(out, 2)


# --- narration builders -------------------------------------------------------
def build_descriptions(rs, kinds, n, ifsc, refs, types, vend, people):
    """Vectorised-ish narration builder. Formats mirror the real sample.
    `vend`/`people` come in pre-biased toward each row's account's home set
    (change 8). CASH and CHEQUE narrations now depend on `types` (change 1);
    every other category keeps its single template regardless of type."""
    out = np.empty(n, dtype=object)
    branch = rng_pick(rs, BRANCHES, n)
    with_branch = rs.random(n) < 0.30            # the grouping trap
    accts = rs.integers(10**11, 10**14, n)
    chan = rng_pick(rs, ["NEFT", "IMPS", "UPI", "FT"], n)
    q = rs.integers(1, 5, n)

    for i in range(n):
        k, r, t = kinds[i], refs[i], types[i]
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
            out[i] = f"ATM CASH WDL {r}" if t == "debit" else f"CASH DEP {r}"
        elif k == "cheque":
            out[i] = f"Cheque Deposits {r}" if t == "credit" else f"CHQ PAID {r}"
        elif k == "insure":
            out[i] = f"LIC PREMIUM POLICY {r}"
        elif k == "rent":
            out[i] = f"NEFT/{r}/{ifsc[i][:4]}/RENT PAYMENT {people[i]}"
        else:
            out[i] = f"SALARY CREDIT {r}"
    return out


# --- change 2: recurring mandates --------------------------------------------
def build_mandates(rs, n_accounts, months, per_acct, mu, sig, cat_weight, dormant):
    """Each account gets `per_acct` recurring commitments: fixed category,
    fixed counterparty/template, fixed day-of-month, fixed base amount, and a
    start/end month window (~15% truncated so not every mandate spans the
    full history -- new tenants, closed policies, paid-off loans). Dormant
    accounts (see account_weights) are skipped entirely -- otherwise they'd
    still pick up recurring rows and wouldn't be dormant at all."""
    w = np.array([cat_weight[c] for c in RECURRING_CATS]); w = w / w.sum()
    mandates = []
    for acct in range(n_accounts):
        if dormant[acct]:
            continue
        for _ in range(per_acct):
            cat = str(rs.choice(RECURRING_CATS, p=w))
            day = int(rs.integers(1, 29))
            if rs.random() < 0.15:
                start_m = int(rs.integers(0, months))
                end_m = int(rs.integers(start_m, months))
            else:
                start_m, end_m = 0, months - 1
            base = float(np.exp(rs.normal(mu[cat], sig[cat])))
            base = float(realistic_amounts(rs, np.array([base]), np.array([cat]))[0])

            if cat == "EMI_LOAN":
                lender = str(rng_pick(rs, LENDERS, 1)[0])
                ttype = "debit"
                desc_fn = lambda ref, lender=lender: f"EMI {lender} {ref or 'NA'}"
            elif cat == "RENT":
                landlord = str(rng_pick(rs, PEOPLE, 1)[0])
                ifsc4 = str(rng_pick(rs, [b[0] for b in BANKS], 1)[0])
                ttype = "debit"
                desc_fn = (lambda ref, landlord=landlord, ifsc4=ifsc4:
                           f"NEFT/{ref or 'NA'}/{ifsc4}/RENT PAYMENT {landlord}")
            elif cat == "INSURANCE":
                insurer = str(rng_pick(rs, INSURERS, 1)[0])
                ttype = "debit"
                desc_fn = lambda ref, insurer=insurer: f"{insurer} PREMIUM POLICY {ref or 'NA'}"
            elif cat == "INVESTMENT":
                tmpl = str(rng_pick(rs, INVEST_FORMS, 1)[0])
                ttype = "debit"
                desc_fn = lambda ref, tmpl=tmpl: tmpl.format(ref=ref or "NA")
            elif cat == "SALARY":
                employer = str(rng_pick(rs, EMPLOYERS, 1)[0])
                ttype = "credit"
                desc_fn = lambda ref, employer=employer: f"SALARY CREDIT {employer} {ref or 'NA'}"
            else:  # UTILITIES
                tmpl = str(rng_pick(rs, UTILITY_FORMS, 1)[0])
                ttype = "debit"
                desc_fn = lambda ref, tmpl=tmpl: tmpl.format(ref=ref or "NA")

            mandates.append(dict(acct=acct, category=cat, day=day, start_m=start_m,
                                  end_m=end_m, amount=base, type=ttype, desc_fn=desc_fn))
    return mandates


def build_recurring_rows(rs, mandates, start, hour_probs, enc, enc_acc_ids):
    """Explode mandates into one row per active month. Day-of-month is fixed
    by the mandate; only the clock time is drawn from the business-hour
    distribution (change 3 says recurring rows skip the day-level weighting)."""
    accs, dates, types, descs, amounts, refs, utrs = [], [], [], [], [], [], []
    for m in mandates:
        for mi in range(m["start_m"], m["end_m"] + 1):
            total_month = (start.year * 12 + (start.month - 1)) + mi
            year, month = divmod(total_month, 12)
            month += 1
            dim = pd.Timestamp(year=year, month=month, day=1).days_in_month
            day = min(m["day"], dim)
            hour = int(rs.choice(24, p=hour_probs))
            minute, second = int(rs.integers(0, 60)), int(rs.integers(0, 60))
            dates.append(pd.Timestamp(year=year, month=month, day=day,
                                       hour=hour, minute=minute, second=second))
            ref = None if rs.random() < 0.08 else f"S{int(rs.integers(10**7, 10**9))}"
            amount = m["amount"]
            if m["category"] == "UTILITIES":
                amount = round(amount * (1 + float(rs.uniform(-0.12, 0.12))), 2)
            accs.append(enc_acc_ids[m["acct"]])
            types.append(m["type"])
            descs.append(m["desc_fn"](ref))
            amounts.append(amount)
            refs.append(ref)
            utrs.append(None if rs.random() < 0.40 else f"UTR{int(rs.integers(10**11, 10**12))}")
    n = len(dates)
    return pd.DataFrame({
        "transaction_id": uuids(rs, n),
        "account_id": accs,
        "transaction_date": dates,
        "transaction_type": types,
        "description": descs,
        "transaction_amount": amounts,
        "transaction_reference_id": refs,
        "utr_number": enc(utrs),
    })


# --- change 6: self-transfers between one entity's own accounts -------------
def build_self_transfer_chunk(rs, n_pairs, multi_entities, entity_accounts, entity_probs,
                               acct_number_plain, acct_entity_name, enc_acc_ids, acct_bank_codes,
                               mu, sig, days, day_probs, hour_probs, enc):
    """Ordinary NEFT/IMPS/UPI/FT narrations, no special marker -- the only tell
    is that the embedded account number belongs to the same portfolio. Both
    legs land in the same chunk by construction."""
    ent_choice = rs.choice(multi_entities, size=n_pairs, p=entity_probs)
    acc_a = np.empty(n_pairs, dtype=np.int64)
    acc_b = np.empty(n_pairs, dtype=np.int64)
    for i, e in enumerate(ent_choice):
        pick = rs.choice(entity_accounts[e], size=2, replace=False)
        acc_a[i], acc_b[i] = pick[0], pick[1]

    amounts = realistic_amounts(rs, np.exp(rs.normal(mu, sig, n_pairs)),
                                 np.array(["TRANSFER"] * n_pairs))
    date_a = sample_datetimes(rs, n_pairs, days, day_probs, hour_probs)
    delay = rs.integers(0, 121, n_pairs)
    date_b = date_a + pd.to_timedelta(delay, unit="s")

    chan = rng_pick(rs, ["NEFT", "IMPS", "UPI", "FT"], n_pairs)
    refs = np.where(rs.random(n_pairs) < 0.08, None,
                    np.array([f"S{x}" for x in rs.integers(10**7, 10**9, n_pairs)], dtype=object))
    ifsc_for_a = np.array([f"{acct_bank_codes[b]}0{x:06d}" for b, x in
                           zip(acc_b, rs.integers(0, 10**6, n_pairs))], dtype=object)
    ifsc_for_b = np.array([f"{acct_bank_codes[a]}0{x:06d}" for a, x in
                           zip(acc_a, rs.integers(0, 10**6, n_pairs))], dtype=object)
    name = acct_entity_name[acc_a]  # same entity on both legs
    other_number_a = acct_number_plain[acc_b]   # A's narration embeds B's real number
    other_number_b = acct_number_plain[acc_a]   # B's narration embeds A's real number

    def fmt(num, ifsc_arr):
        out = np.empty(n_pairs, dtype=object)
        for i in range(n_pairs):
            c, r, nm, ifs = chan[i], (refs[i] or "NA"), name[i], ifsc_arr[i]
            n_i = num[i]
            if c == "NEFT":
                out[i] = f"NEFT  - {ifs} - {r} - {n_i} - {nm}"
            elif c == "UPI":
                out[i] = f"UPI-{nm}-XXXXXX{int(n_i) % 10000}-{ifs}-{r}"
            elif c == "IMPS":
                out[i] = f"IMPS/P2A/{r}/{ifs[:4]}/{n_i}/00/INET/{nm}"
            else:
                out[i] = f"FT -  {r} -  {n_i} - {nm}"
        return out

    desc_a = fmt(other_number_a, ifsc_for_a)
    desc_b = fmt(other_number_b, ifsc_for_b)

    def utrs(k):
        return np.where(rs.random(k) < 0.40, None,
                        np.array([f"UTR{x}" for x in rs.integers(10**11, 10**12, k)], dtype=object))

    df_a = pd.DataFrame({
        "transaction_id": uuids(rs, n_pairs), "account_id": enc_acc_ids[acc_a],
        "transaction_date": date_a, "transaction_type": "debit", "description": desc_a,
        "transaction_amount": amounts, "transaction_reference_id": refs,
        "utr_number": enc(utrs(n_pairs)),
    })
    df_b = pd.DataFrame({
        "transaction_id": uuids(rs, n_pairs), "account_id": enc_acc_ids[acc_b],
        "transaction_date": date_b, "transaction_type": "credit", "description": desc_b,
        "transaction_amount": amounts, "transaction_reference_id": refs,
        "utr_number": enc(utrs(n_pairs)),
    })
    return pd.concat([df_a, df_b], ignore_index=True)


# --- change 5: reversals and duplicates --------------------------------------
def augment_chunk(rs, df, enc, end_boundary):
    """Applied to every chunk right before writing, from every pass, so
    reversals/duplicates never require holding more than one chunk in memory.
    Reversal keeps the ORIGINAL transaction_reference_id (so the pair is
    matchable) but gets its own transaction_id and UTR. Duplicate copies the
    row verbatim except transaction_id and a small timestamp shift.

    Both the reversal offset (0-5 days) and the duplicate offset (30-180s)
    are clamped to `end_boundary` (end-of-day on --end) so neither pass can
    push transaction_date past the requested window -- otherwise the
    pipeline's anchor date (max(transaction_date)) lands in a near-empty
    trailing month and "this month" queries look broken."""
    n = len(df)
    parts = [df]
    n_rev = n_dup = 0

    debit_pos = np.flatnonzero((df["transaction_type"] == "debit").to_numpy())
    n_rev = int(round(len(debit_pos) * 0.012))
    if n_rev > 0:
        sel = rs.choice(debit_pos, size=n_rev, replace=False)
        base = df.iloc[sel].reset_index(drop=True)
        delay = rs.integers(0, 5 * 86400 + 1, n_rev).astype("timedelta64[s]")
        new_dates = base["transaction_date"].to_numpy() + delay
        new_dates = np.minimum(new_dates, end_boundary)
        ref_txt = base["transaction_reference_id"].fillna("NA").astype(str)
        # Cut at a word boundary. Slicing mid-word produced vendor names like
        # "ZOMATO H" and "ZOMATO HYPER", which the parser then treated as
        # separate merchants and vendor lookups started refusing.
        trunc_desc = (base["description"].astype(str).str.slice(0, 60)
                      .str.replace(r"\s+\S*$", "", regex=True))
        new_desc = "REV/" + ref_txt + "/" + trunc_desc
        new_utr = np.where(rs.random(n_rev) < 0.40, None,
                           np.array([f"UTR{x}" for x in rs.integers(10**11, 10**12, n_rev)], dtype=object))
        rev = pd.DataFrame({
            "transaction_id": uuids(rs, n_rev),
            "account_id": base["account_id"].to_numpy(),
            "transaction_date": new_dates,
            "transaction_type": "credit",
            "description": new_desc.to_numpy(),
            "transaction_amount": base["transaction_amount"].to_numpy(),
            "transaction_reference_id": base["transaction_reference_id"].to_numpy(),
            "utr_number": enc(list(new_utr)),
        })
        parts.append(rev)

    n_dup = int(round(n * 0.0015))
    if n_dup > 0:
        sel = rs.choice(n, size=n_dup, replace=False)
        dup = df.iloc[sel].reset_index(drop=True).copy()
        shift = rs.integers(30, 181, n_dup).astype("timedelta64[s]")
        dup["transaction_id"] = uuids(rs, n_dup)
        dup["transaction_date"] = np.minimum(
            dup["transaction_date"].to_numpy() + shift, end_boundary)
        parts.append(dup)

    out = pd.concat(parts, ignore_index=True) if len(parts) > 1 else df
    return out, n_rev, n_dup


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
    ap.add_argument("--entities", type=int, default=0,
                     help="MINIMUM floor on distinct entities. Entity count is "
                          "otherwise purely derived from the long-tailed "
                          "accounts-per-entity distribution (default 0 = no floor).")
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--format", choices=["csv", "parquet"], default="csv")
    ap.add_argument("--no-encrypt", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunk", type=int, default=500_000)
    ap.add_argument("--recurring-share", type=float, default=0.08,
                     help="target fraction of rows that are recurring mandate "
                          "payments (EMI/rent/insurance/SIP/salary/utilities).")
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

    # --- entities + accounts (change 7) ---
    sizes = draw_entity_sizes(rs, a.accounts, a.entities)
    n_entities = len(sizes)
    sizes_arr = np.array(sizes)
    entity_ids = uuids(rs, n_entities)
    entity_names = rng_pick(rs, ENTITY_NAMES, n_entities)
    account_entity_idx = np.repeat(np.arange(n_entities), sizes_arr)

    n_banks = len(BANKS)
    bank_codes = np.array([b[0] for b in BANKS], dtype=object)
    primary_idx = rs.integers(0, n_banks, n_entities)
    secondary_idx = (primary_idx + 1 + rs.integers(0, n_banks - 1, n_entities)) % n_banks
    has_secondary = (sizes_arr > 1) & (rs.random(n_entities) < 0.6)

    acct_primary_idx = primary_idx[account_entity_idx]
    acct_secondary_idx = secondary_idx[account_entity_idx]
    acct_has_secondary = has_secondary[account_entity_idx]
    use_primary = (~acct_has_secondary) | (rs.random(a.accounts) < 0.70)
    acct_bank_idx = np.where(use_primary, acct_primary_idx, acct_secondary_idx)
    acct_bank_codes = bank_codes[acct_bank_idx]

    acc_ids = uuids(rs, a.accounts)
    acct_number_plain = [str(x) for x in rs.integers(10**13, 10**14, a.accounts)]
    acct_number_plain_arr = np.asarray(acct_number_plain, dtype=object)
    acct_entity_ids_plain = np.asarray(entity_ids, dtype=object)[account_entity_idx].tolist()
    acct_entity_name_arr = np.asarray(entity_names, dtype=object)[account_entity_idx]

    accounts = pd.DataFrame({
        "account_id": enc(acc_ids),
        "entity_id": enc(acct_entity_ids_plain),
        "account_number": enc(acct_number_plain),
        "program_id": rs.choice([4, 21, 46], a.accounts),
        "available_balance": np.round(rs.normal(5e6, 4e7, a.accounts), 2),
        "bank_code": acct_bank_codes,
    })
    accounts.to_csv(OUT / "account.csv", index=False)
    enc_acc_ids = np.asarray(accounts["account_id"].tolist(), dtype=object)

    n_single = int((sizes_arr == 1).sum())
    print(f"entities: {n_entities} derived from {a.accounts} accounts "
          f"({n_single} single-account, {n_entities - n_single} multi-account)")

    # --- change 8: home counterparty sets + volume skew --------------------
    home_vend_idx, home_vend_size = build_home_sets(rs, a.accounts, len(VENDORS), 8, 15)
    home_ppl_idx, home_ppl_size = build_home_sets(rs, a.accounts, len(PEOPLE), 5, 10)
    acct_w, dormant = account_weights(rs, a.accounts)
    n_dormant = int(dormant.sum())
    print(f"dormant accounts: {n_dormant}/{a.accounts} ({100*n_dormant/max(a.accounts,1):.1f}%)")

    # --- change 3: time distribution -----------------------------------------
    end = pd.Timestamp(a.end)
    start = end - pd.DateOffset(months=a.months)
    days, day_probs, hour_probs = build_time_distribution(start, end)
    # end-of-day boundary on --end: reversal/duplicate offsets get clamped to
    # this so they never push transaction_date past the requested window.
    end_boundary = (end + pd.Timedelta(hours=23, minutes=59, seconds=59)).to_datetime64()

    cats_list = [c[0] for c in CATEGORY_MIX]
    kinds_by_cat = {c[0]: c[2] for c in CATEGORY_MIX}
    cat_weights = np.array([c[1] for c in CATEGORY_MIX]); cat_weights = cat_weights / cat_weights.sum()
    mu = {c[0]: c[3] for c in CATEGORY_MIX}; sig = {c[0]: c[4] for c in CATEGORY_MIX}
    cat_weight_lookup = {c[0]: c[1] for c in CATEGORY_MIX}

    # --- change 2: recurring mandates, built once (bounded by accounts x 40 x
    # months regardless of --rows, so this never approaches chunk-scale memory)
    mandates_per_acct = int(np.clip(round(a.rows * a.recurring_share / (a.accounts * a.months)), 3, 40))
    mandates = build_mandates(rs, a.accounts, a.months, mandates_per_acct, mu, sig, cat_weight_lookup, dormant)
    rec_rows_total = sum(m["end_m"] - m["start_m"] + 1 for m in mandates)

    # --- change 6: self-transfer budget --------------------------------------
    # Dormant accounts (change: genuinely-dormant accounts) are excluded from
    # both legs -- an entity only counts as "multi" here if it still has >=2
    # non-dormant accounts to pair up.
    acc_df = pd.DataFrame({"entity": account_entity_idx, "acc_idx": np.arange(a.accounts)})
    acc_df = acc_df[~dormant]
    entity_accounts = {int(e): g.to_numpy() for e, g in acc_df.groupby("entity")["acc_idx"]
                        if len(g) >= 2}
    multi_entities = np.array(sorted(entity_accounts.keys()), dtype=np.int64)
    self_target = 0
    entity_probs = None
    if len(multi_entities):
        self_target = int(round(a.rows * 0.03))
        self_target -= self_target % 2
        entity_probs = np.array([len(entity_accounts[e]) for e in multi_entities], dtype=float)
        entity_probs = entity_probs / entity_probs.sum()

    oneoff_target = max(0, a.rows - rec_rows_total - self_target)

    # --- output plumbing, shared by every pass --------------------------------
    path = OUT / f"transaction.{a.format}"
    if path.exists():
        path.unlink()
    state = {"first": True, "writer": None, "written": 0, "rev": 0, "dup": 0}

    def emit(df):
        df, n_rev, n_dup = augment_chunk(rs, df, enc, end_boundary)
        state["rev"] += n_rev; state["dup"] += n_dup
        if a.format == "csv":
            df.to_csv(path, mode="w" if state["first"] else "a", header=state["first"], index=False)
        else:
            import pyarrow as pa, pyarrow.parquet as pq
            if state["writer"] is None:
                table = pa.Table.from_pandas(df, preserve_index=False)
                state["writer"] = pq.ParquetWriter(path, table.schema)
            else:
                table = pa.Table.from_pandas(df, schema=state["writer"].schema, preserve_index=False)
            state["writer"].write_table(table)
        state["first"] = False
        state["written"] += len(df)
        print(f"  {state['written']:,} rows written  ({time.time()-t0:.1f}s)", end="\r", flush=True)

    # --- pass 1: recurring mandates, own pass, before one-off (change 2) ----
    if mandates:
        rec_df = build_recurring_rows(rs, mandates, start, hour_probs, enc, enc_acc_ids)
        for i in range(0, len(rec_df), a.chunk):
            emit(rec_df.iloc[i:i + a.chunk].reset_index(drop=True))

    # --- pass 2: self-transfer pairs, both legs in the same chunk (change 6) -
    self_written = 0
    while self_written < self_target:
        n_pairs = min(a.chunk // 2, (self_target - self_written) // 2)
        if n_pairs <= 0:
            break
        df = build_self_transfer_chunk(
            rs, n_pairs, multi_entities, entity_accounts, entity_probs,
            acct_number_plain_arr, acct_entity_name_arr, enc_acc_ids, acct_bank_codes,
            mu["TRANSFER"], sig["TRANSFER"], days, day_probs, hour_probs, enc)
        emit(df)
        self_written += len(df)

    # --- pass 3: one-off transactions, fills the remainder -------------------
    written_oneoff = 0
    while written_oneoff < oneoff_target:
        n = min(a.chunk, oneoff_target - written_oneoff)
        cat = rs.choice(cats_list, n, p=cat_weights)
        kinds = np.array([kinds_by_cat[c] for c in cat], dtype=object)
        cprob = np.array([CREDIT_PROB[c] for c in cat])
        types = np.where(rs.random(n) < cprob, "credit", "debit")   # change 1

        raw = np.exp(rs.normal([mu[c] for c in cat], [sig[c] for c in cat]))
        amounts = realistic_amounts(rs, raw, cat)                    # change 4
        outlier = rs.random(n) < 0.0008                              # genuine anomalies
        amounts[outlier] *= rs.uniform(8, 25, outlier.sum())
        amounts = np.round(amounts, 2)

        acct_idx = rs.choice(a.accounts, n, p=acct_w)                 # change 8 skew
        dates = sample_datetimes(rs, n, days, day_probs, hour_probs)  # change 3

        refs = np.where(rs.random(n) < 0.08, None,
                        np.array([f"S{x}" for x in rs.integers(10**7, 10**9, n)], dtype=object))
        ifsc = np.array([f"{b}0{x:06d}" for b, x in
                         zip(rng_pick(rs, [b[0] for b in BANKS], n), rs.integers(0, 10**6, n))], dtype=object)

        vend = home_biased_pick(rs, acct_idx, home_vend_idx, home_vend_size, VENDORS)   # change 8
        people = home_biased_pick(rs, acct_idx, home_ppl_idx, home_ppl_size, PEOPLE)    # change 8

        desc = build_descriptions(rs, kinds, n, ifsc, [r if r is not None else "NA" for r in refs],
                                  types, vend, people)
        utrs = np.where(rs.random(n) < 0.40, None,
                        np.array([f"UTR{x}" for x in rs.integers(10**11, 10**12, n)], dtype=object))

        df = pd.DataFrame({
            "transaction_id": uuids(rs, n),
            "account_id": enc_acc_ids[acct_idx],
            "transaction_date": dates,
            "transaction_type": types,
            "description": desc,
            "transaction_amount": amounts,
            "transaction_reference_id": refs,
            "utr_number": enc(utrs),
        })
        emit(df)
        written_oneoff += n

    if state["writer"]:
        state["writer"].close()

    total = state["written"]
    print(f"\n\nwrote {total:,} transactions, {a.accounts} accounts, {n_entities} entities, {len(BANKS)} banks")
    print(f"  composition: {rec_rows_total:,} recurring + {self_target:,} self-transfer + "
          f"{oneoff_target:,} one-off base rows")
    print(f"  + {state['rev']:,} reversals ({100*state['rev']/max(total,1):.2f}%), "
          f"{state['dup']:,} duplicates ({100*state['dup']/max(total,1):.2f}%)")
    print(f"  target was {a.rows:,} rows -> actual is {100*total/max(a.rows,1):.1f}% of target")
    print(f"  -> {OUT}  ({time.time()-t0:.1f}s, encryption {'off' if a.no_encrypt else 'AES-256-CTR fixed nonce'})")


if __name__ == "__main__":
    main()
