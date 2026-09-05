"""Deterministic normalisation of Indian numeral shorthand.

"1 lakh", "2.5 cr", "5L" are ordinary English to the user but nothing this
system knows about: the coverage allowlist (app/coverage.py) has no
vocabulary entry for "lakh", so "How many payments over 1 lakh did I make"
is refused as an unknown concept before the model -- which would have
happily converted the number itself -- ever gets a turn. See DECISIONS.md.

This module resolves the SHORTHAND into plain digits in the question TEXT,
before both coverage checking and the planner prompt see it, so "1 lakh"
becomes "100000" and there is no separate vocabulary entry to maintain.

Deterministic, regex-only, testable without a model -- the same principle as
app/nlq_dates.py. Every pattern requires an immediately-adjacent number, so
ordinary English words ("black", "across", "look") never match: there is no
digit for the regex to anchor on.
"""
from __future__ import annotations
import re

# Longest / most specific units first. Each pattern is applied to the
# ORIGINAL text (see normalise()), so a unit converted by an earlier pattern
# is never re-scanned and double-converted by a later, looser one.
_UNITS = (
    # lakh(s) / lac(s) = 100,000
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:lakhs?|lacs?)\b", re.I), 100_000),
    # crore(s) / cr = 10,000,000
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:crores?|cr)\b", re.I), 10_000_000),
    # bare "k" = 1,000 ("5k", "2.5k")
    (re.compile(r"\b(\d+(?:\.\d+)?)\s?[kK]\b"), 1_000),
    # bare "L" = 100,000 ("5L"). Uppercase only -- lowercase "l" collides far
    # more often with stray typos and abbreviations in free text.
    (re.compile(r"\b(\d+(?:\.\d+)?)L\b"), 100_000),
)


def _fmt(value: float) -> str:
    """Plain digits, never scientific notation or a trailing ".0" -- the
    planner prompt and coverage's tokenizer both expect an ordinary number."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def normalise(question: str) -> str:
    """Replace every Indian-numeral shorthand quantity with its digit form.

    "How many payments over 1 lakh did I make" ->
    "How many payments over 100000 did I make"
    """
    out = question
    for pattern, multiplier in _UNITS:
        out = pattern.sub(lambda m, mult=multiplier: _fmt(float(m.group(1)) * mult), out)
    return out
