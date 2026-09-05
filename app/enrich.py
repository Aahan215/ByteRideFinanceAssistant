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
    ("CHARGES", re.compile(r"\bCHARGES?\b|\bFEE\b|\bGST\b", re.I)),
]

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
LEGAL_SUFFIX = re.compile(
    r"\s+(PRIVATE\s+LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|INC\.?)\s*$", re.I)


@dataclass
class Parsed:
    channel: str | None
    counterparty_raw: str | None
    counterparty: str | None   # normalised key for grouping
    parsed_by: str             # which rule fired -- keep for coverage reporting


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

    if raw is None:
        return Parsed(channel, None, None, "unparsed")
    raw = re.sub(r"\s+", " ", raw.strip())
    return Parsed(channel, raw, normalise(raw), rule)
