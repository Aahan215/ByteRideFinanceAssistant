"""Reject or clarify BEFORE touching the database.

This module is where 'hallucination guardrails' actually live. If the spec
references a vendor/category/status that does not exist, we never run a query
that would return 0 and get narrated as "you spent nothing".
"""
from __future__ import annotations
from difflib import get_close_matches
from dataclasses import dataclass, field
from app.db import SEMANTIC, run
from app.spec import QuerySpec


@dataclass
class Verdict:
    ok: bool
    refusal: str | None = None
    clarification: str | None = None
    warnings: list[str] = field(default_factory=list)
    repaired: QuerySpec | None = None


def _known_values(dim: str) -> list[str]:
    """Distinct values straight from the enriched view -- so a filter is only
    accepted if the data actually contains it."""
    col = SEMANTIC["dimensions"][dim]["column"]
    view = SEMANTIC["base_view"]
    rows = run(f"SELECT DISTINCT {col} FROM {view} WHERE {col} IS NOT NULL")
    return [r[0] for r in rows.values]


def validate(spec: QuerySpec) -> Verdict:
    if spec.unsupported_reason:
        return Verdict(False, refusal=spec.unsupported_reason)

    warnings, repaired = [], spec.model_copy(deep=True)

    for dim in ("counterparty", "channel", "bank_name", "transaction_type", "reconciliation"):
        value = getattr(spec.filters, dim)
        if value is None:
            continue
        known = _known_values(dim)
        if value in known:
            continue
        near = get_close_matches(str(value), [str(k) for k in known], n=3, cutoff=0.7)
        if len(near) == 1:
            setattr(repaired.filters, dim, near[0])
            warnings.append(f"Interpreted {dim} '{value}' as '{near[0]}'.")
        elif near:
            return Verdict(False, clarification=f"Did you mean {', '.join(near)}?")
        else:
            return Verdict(False, refusal=f"I have no {dim} matching '{value}' in this dataset.")

    return Verdict(True, warnings=warnings, repaired=repaired)


NUMBER_RE = r"-?[\d,]+(?:\.\d+)?"


def numeric_guard(answer: str, result_df) -> list[str]:
    """Every number the model wrote must exist in the result set.
    Cheap, deterministic, and the best 20 seconds of your demo."""
    import re
    allowed = set()
    for col in result_df.columns:
        for v in result_df[col].tolist():
            if isinstance(v, (int, float)):
                allowed |= {f"{v:.2f}", f"{round(v):d}", str(v)}
    bad = []
    for tok in re.findall(NUMBER_RE, answer):
        clean = tok.replace(",", "")
        try:
            f = float(clean)
        except ValueError:
            continue
        if f"{f:.2f}" not in allowed and f"{round(f):d}" not in allowed:
            bad.append(tok)
    return bad
