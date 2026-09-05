"""Result table -> plain English. Runs AFTER the numbers are already computed."""
from __future__ import annotations
from app.validator import numeric_guard

SYSTEM = """You explain a finance result table in two sentences.
Use ONLY numbers that appear in the table. Do not estimate, round, or extrapolate."""

# Plain "{:,.2f}" formatting disagrees with the Indian grouping the UI uses,
# so the same figure appears two different ways on one screen.
def inr(x) -> str:
    if x is None:
        return "-"
    neg, n = x < 0, abs(round(float(x)))
    s = str(n)
    if len(s) > 3:                       # 2,02,07,329 -- last 3, then pairs
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{'-' if neg else ''}\u20b9{s}"


# "counterpartys" is not a word, and it is on screen next to real numbers.
LABELS = {"counterparty": "vendors", "category": "categories", "channel": "channels",
          "bank_name": "banks", "month": "months", "quarter": "quarters",
          "transaction_type": "transaction types", "account_id": "accounts",
          "entity_id": "entities", "program_id": "programs"}


def narrate(question: str, df, spec, window_desc: str) -> str:
    """Phrase the answer.

    Default is the deterministic template: it cannot be wrong, and no data
    leaves the process. Set NARRATOR_MODE=model to have the model phrase it
    instead -- which means sending the aggregate result table to the provider.
    That is a deliberate choice, not a default, now the provider is external.
    """
    from app.boundary import NARRATOR_MODE
    base = template(df, spec, window_desc)
    if NARRATOR_MODE != "model" or df is None or df.empty:
        return base

    from app.llm import chat
    from app.validator import numeric_guard
    table = df.head(15).to_string(index=False)
    try:
        text = chat("narrator", SYSTEM, f"Question: {question}\nWindow: {window_desc}\n{table}")
    except Exception:
        return base
    # Every number the model wrote must exist in the result set, or we do not
    # use its wording at all.
    return base if numeric_guard(text, df) else text


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
        label = {"sum_amount": "Total", "count": "Count", "avg_amount": "Average",
                 "max_amount": "Largest", "min_amount": "Smallest"}[spec.metric]
        shown = f"{int(value):,}" if spec.metric == "count" else inr(value)
        return f"{label} for {window_desc}: {shown}"
    top = df.iloc[0]
    key = spec.group_by[0]
    shown = f"{int(top[spec.metric]):,}" if spec.metric == "count" else inr(top[spec.metric])
    return (f"Across {len(df)} {LABELS.get(key, key + 's')} for {window_desc}, "
            f"{top[key]} is highest at {shown}.")


def with_comparison(text: str, comp, spec) -> str:
    """Append the period-over-period sentence. Numbers come from the diff the
    engine computed, never from the model."""
    if comp is None:
        return text
    if not spec.group_by:
        if comp.previous is None or comp.value is None:
            return f"{text} No comparable figure for {comp.window}."
        direction = "up" if comp.delta > 0 else "down" if comp.delta < 0 else "flat"
        pct = f" ({abs(comp.delta_pct):.1f}%)" if comp.delta_pct is not None else ""
        return (f"{text} That is {direction} {inr(abs(comp.delta))}{pct} "
                f"versus {comp.window}.")
    movers = [r for r in comp.rows if r.get("delta") is not None]
    if not movers:
        return f"{text} No overlapping figures for {comp.window}."
    top = movers[0]
    key = spec.group_by[0]
    if top["value"] == 0 and top["previous"]:
        return (f"{text} Compared with {comp.window}, the biggest move is "
                f"{top[key]}: {inr(abs(top['delta']))} last period, nothing this one.")
    if top["previous"] == 0 and top["value"]:
        return (f"{text} Compared with {comp.window}, the biggest move is "
                f"{top[key]}: new this period at {inr(top['value'])}.")
    verb = "up" if top["delta"] > 0 else "down"
    return (f"{text} Compared with {comp.window}, the biggest move is "
            f"{top[key]}, {verb} {inr(abs(top['delta']))}.")


def with_anomalies(text: str, flags) -> str:
    """Append the callout. The problem statement asks for this alongside the
    original answer, not as a separate question."""
    if not flags:
        return text
    if len(flags) == 1:
        return f"{text} Worth a look: {flags[0].sentence()}."
    joined = "; ".join(f.sentence() for f in flags[:3])
    return f"{text} Worth a look: {joined}."
