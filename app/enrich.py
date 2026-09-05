"""Counterparty extraction from free-text transaction descriptions.

THE CENTRAL PROBLEM OF THIS DATASET. There is no vendor table, no category, no
vendor_id. "How much did we spend on vendor payouts last month?" requires
pulling a counterparty name out of strings like:

    NEFT  - ICIC0001241 - 95584112 - 124105002702 - SELECTION MOBILE
    UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-260514201735136
    IMPS OW/507614422198/Gautam singh/SBIN/43292707719

This runs ONCE at load time and writes a real column. It is deterministic ETL,
not per-query inference -- the model never parses a description at answer time.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# --- channel detection -------------------------------------------------------
CHANNELS: list[tuple[str, re.Pattern]] = [
    ("UPI",   re.compile(r"^\s*UPI[-/]", re.I)),
    ("IMPS",  re.compile(r"^\s*IMPS[\s/]", re.I)),
    ("NEFT",  re.compile(r"^\s*NEFT[\s/-]", re.I)),
    ("RTGS",  re.compile(r"^\s*RTGS[\s/-]", re.I)),
    ("FT",    re.compile(r"^\s*FT\s*-", re.I)),
    ("ACH",   re.compile(r"^\s*(ACH|NACH)[\s/-]", re.I)),
    ("CHEQUE", re.compile(r"CHEQUE|\bCHQ\b", re.I)),
]
# NOTE: `channel` is the payment RAIL only. "CHARGES" and "GST" used to live
# here, which tagged every GST payment with channel=CHARGES -- a category
# masquerading as a rail. Fee-vs-transfer is what `category` is for.

# Tokens that are never a counterparty name.
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
BANKCODE = re.compile(r"^[A-Z]{4}$")
MOSTLY_DIGITS = re.compile(r"^[\d\s\-]+$")
NOISE = {"INET", "INWD", "P2A", "P2P", "OW", "IW", "CR", "DR", "NA", "MOB", "TPFT"}

# Trailing reference codes tacked onto the narration. Deliberately NARROW:
# only strip tokens that are unambiguously codes, never words.
#
# TODO(stream 1): Indian narrations also carry a trailing branch/location
# ("... SELECTION ELECTRONICS   DAHISAR EAST"). Stripping those needs the real
# data -- build a place list from the actual corpus rather than guessing from
# ten sample rows, or the same vendor splits across several group keys.
SUFFIX_NOISE = re.compile(r"\s+(DPF\d+|INWD\d+|IN\d{6,})\s*$", re.I)

# A trailing reference/receipt number ("... LTD S32337295"). Left in, one lender
# becomes thousands of one-transaction "vendors" and every ranking is wrong.
# Requires >=5 digits so a real name ending in a small number survives.
TRAILING_REF = re.compile(r"\s+[A-Z]{0,3}\d{5,}\s*$", re.I)
LEGAL_SUFFIX = re.compile(
    r"\s+(PRIVATE\s+LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|INC\.?)\s*$", re.I)


# --- spend categories --------------------------------------------------------
# There is no category column. "Where did I spend the most?" and "total tax I
# paid" both need one, so it is derived here at load time from the narration.
#
# Order matters: TAX and CHARGES must win over TRANSFER, because a tax payment
# is also an NEFT. Word boundaries everywhere -- a vendor called TAXI must not
# match TAX.
CATEGORIES: list[tuple[str, re.Pattern]] = [
    ("TAX",         re.compile(r"\b(C?GST|SGST|IGST|TDS|TCS|INCOME\s*TAX|ADV(ANCE)?\s*TAX|"
                              r"SELF\s*ASSESS\w*|TAX\s*PAY\w*|CHALLAN|\bTAX\b)", re.I)),
    ("BANK_CHARGES", re.compile(r"\b(CHARGE?S?|CHRG|CHGS|FEE|COMMISSION|COMM|PENALTY|"
                              r"AMC|MIN\s*BAL|SMS\s*CHG)\b", re.I)),
    ("INTEREST",    re.compile(r"\b(INTEREST|INT\.?\s*(PAID|CR|DR))\b", re.I)),
    ("EMI_LOAN",    re.compile(r"\b(EMI|LOAN|REPAY\w*|DISBURS\w*|BAJAJ\s*FIN\w*)\b", re.I)),
    ("SALARY",      re.compile(r"\b(SALARY|SAL\s*CR|PAYROLL|STIPEND)\b", re.I)),
    ("UTILITIES",   re.compile(r"\b(ELECTRICITY|BSES|MSEB|BESCOM|GAS|WATER|BROADBAND|"
                              r"RECHARGE|AIRTEL|JIO|VODAFONE|BSNL|DTH)\b", re.I)),
    ("INSURANCE",   re.compile(r"\b(INSURANCE|PREMIUM|POLICY|\bLIC\b)\b", re.I)),
    ("INVESTMENT",  re.compile(r"\b(MUTUAL\s*FUND|\bSIP\b|ZERODHA|GROWW|UPSTOX|DEMAT|"
                              r"\bNSE\b|\bBSE\b)\b", re.I)),
    ("CASH",        re.compile(r"\b(ATM|CASH\s*(WDL|WITHDRAWAL|DEP)|\bCW\b)\b", re.I)),
    ("CHEQUE",      re.compile(r"\b(CHEQUE|CHQ)\b", re.I)),
    ("RENT",        re.compile(r"\bRENT\b", re.I)),
]

# Everything with a payment channel but no category signal is a plain transfer.
TRANSFER_CHANNELS = {"UPI", "IMPS", "NEFT", "RTGS", "FT"}

# Categories where the narration describes an EVENT, not a payee. Without this,
# the fallback rule happily extracts "MIN BAL PENALTY" and "ATM CASH WDL" as
# vendors, and "where did I spend the most" ranks them alongside real shops.
NO_COUNTERPARTY = {"BANK_CHARGES", "TAX", "CASH", "CHEQUE", "INTEREST"}

# "NA" is our own placeholder for a missing reference id leaking into the name.
TRAILING_PLACEHOLDER = re.compile(r"\s+(NA|NULL|NONE)\s*$", re.I)


def categorise(description: str, channel: str | None) -> tuple[str, str]:
    """Returns (category, matched_rule). Never guesses: an unmatched narration
    becomes UNCATEGORISED so the assistant can say so instead of hiding it in
    a bucket."""
    for name, rx in CATEGORIES:
        if rx.search(description):
            return name, f"keyword:{name}"
    if channel in TRANSFER_CHANNELS:
        return "TRANSFER", "channel-default"
    return "UNCATEGORISED", "none"


@dataclass
class Parsed:
    channel: str | None
    counterparty_raw: str | None
    counterparty: str | None   # normalised key for grouping
    parsed_by: str             # which rule fired -- keep for coverage reporting
    category: str = "UNCATEGORISED"
    category_by: str = "none"


def _plausible_name(tok: str) -> bool:
    t = tok.strip()
    if len(t) < 4:
        return False
    if t.upper() in NOISE or IFSC.match(t.upper()) or MOSTLY_DIGITS.match(t):
        return False
    letters = sum(c.isalpha() for c in t)
    return letters >= 4 and letters / len(t) >= 0.5


def _best_token(tokens: list[str]) -> str | None:
    cands = [t.strip() for t in tokens if _plausible_name(t)]
    if not cands:
        return None
    # the counterparty is reliably the longest alphabetic run in these formats
    return max(cands, key=lambda t: sum(c.isalpha() for c in t))


def normalise(name: str) -> str:
    """Group key. 'SELECTRICITY TWO PRIVATE LIMITED' and 'Selectricity Two Ltd'
    must collapse to the same vendor or every aggregate is wrong."""
    n = SUFFIX_NOISE.sub("", name)
    n = TRAILING_REF.sub("", n)
    n = LEGAL_SUFFIX.sub("", n)
    n = re.sub(r"[^A-Za-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip().upper()
    return n


def parse(description: str | None) -> Parsed:
    if not description or not description.strip():
        return Parsed(None, None, None, "empty")
    d = description.strip()

    channel = next((name for name, rx in CHANNELS if rx.search(d)), None)

    # Rule order matters: most specific format first.
    raw, rule = None, "fallback"

    if channel == "UPI":
        parts = d.split("-")
        if len(parts) > 1 and _plausible_name(parts[1]):
            raw, rule = parts[1], "upi-field1"

    elif channel == "IMPS" and re.match(r"^\s*IMPS\s+(OW|IW)/", d, re.I):
        parts = d.split("/")
        if len(parts) > 2 and _plausible_name(parts[2]):
            raw, rule = parts[2], "imps-ow-field2"

    elif channel in ("NEFT", "FT") and " - " in d:
        parts = [p for p in d.split(" - ") if p.strip()]
        if parts and _plausible_name(parts[-1]):
            raw, rule = parts[-1], f"{channel.lower()}-dash-last"

    elif channel in ("NEFT", "RTGS") and "/" in d:
        parts = d.split("/")
        if parts and _plausible_name(parts[-1]):
            raw, rule = parts[-1], f"{channel.lower()}-slash-last"

    if raw is None:
        raw = _best_token(re.split(r"[/\-|]", d))
        rule = "longest-alpha-run" if raw else "unparsed"

    cat, cat_by = categorise(d, channel)

    # A bank charge has no counterparty. Saying "none" is correct; inventing a
    # vendor called IMPS CHARGES corrupts every spend-by-vendor answer.
    if cat in NO_COUNTERPARTY:
        return Parsed(channel, None, None, f"no-counterparty:{cat}", cat, cat_by)

    if raw is None:
        return Parsed(channel, None, None, "unparsed", cat, cat_by)
    raw = TRAILING_PLACEHOLDER.sub("", re.sub(r"\s+", " ", raw.strip()))
    if not _plausible_name(raw):
        return Parsed(channel, None, None, "unparsed", cat, cat_by)
    return Parsed(channel, raw, normalise(raw), rule, cat, cat_by)
