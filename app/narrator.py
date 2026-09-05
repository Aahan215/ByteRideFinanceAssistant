"""Result table -> plain English. Runs AFTER the numbers are already computed."""
from __future__ import annotations
from app.validator import numeric_guard

SYSTEM = """You explain a finance result table in two sentences.
Use ONLY numbers that appear in the table. Do not estimate, round, or extrapolate."""


def narrate(question: str, df, spec, window_desc: str) -> str:
    """TODO(owner: narrator): call the small model, then run numeric_guard().
    If the guard flags anything, regenerate once, then fall back to template()."""
    return template(df, spec, window_desc)


def template(df, spec, window_desc: str) -> str:
    """Deterministic fallback. Never wrong, occasionally clunky. Ship it as the
    safety net so the assistant degrades gracefully instead of hallucinating."""
    import pandas as pd

    # An aggregate over zero rows comes back as one row of NULL, not an empty
    # frame. Saying "nan" -- or worse, "0.00" -- would be a wrong answer, so
    # treat it as the absence it is.
    value = df.iloc[0, -1] if len(df) else None
    if df.empty or (not spec.group_by and pd.isna(value)):
        what = f" {spec.filters.category.lower()}" if spec.filters.category else ""
        return f"No{what} transactions found for {window_desc}."

    if not spec.group_by:
        return f"{spec.metric.replace('_', ' ')} for {window_desc}: {value:,.2f}"
    top = df.iloc[0]
    return (f"Across {len(df)} {spec.group_by[0]}s for {window_desc}, "
            f"{top[spec.group_by[0]]} is highest at {top[spec.metric]:,.2f}.")
