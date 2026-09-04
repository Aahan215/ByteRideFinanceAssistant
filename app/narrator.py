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
    if df.empty:
        return f"No matching records for {window_desc}."
    if not spec.group_by:
        return f"{spec.metric.replace('_', ' ')} for {window_desc}: {df.iloc[0, -1]:,.2f}"
    top = df.iloc[0]
    return (f"Across {len(df)} {spec.group_by[0]}s for {window_desc}, "
            f"{top[spec.group_by[0]]} is highest at {top[spec.metric]:,.2f}.")
