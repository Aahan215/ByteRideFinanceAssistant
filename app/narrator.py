"""Result table -> plain English. Runs AFTER the numbers are already computed."""
from __future__ import annotations
from app.validator import numeric_guard


# Plain "{:,.2f}" formatting disagrees with the en-IN grouping the UI uses, so
# the same figure appears two different ways on one screen.
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


# "counterpartys" is not a word, and it appears on screen next to real numbers.
LABELS = {"counterparty": "vendors", "category": "categories", "channel": "channels",
          "bank_name": "banks", "month": "months", "quarter": "quarters",
          "transaction_type": "transaction types", "account_id": "accounts",
          "entity_id": "entities", "program_id": "programs"}


def _measure(spec, value) -> str:
    return f"{int(value):,}" if spec.metric == "count" else inr(value)


def _group_value(dim: str, value) -> str:
    """A month is "April 2026", not "2026-04-01 00:00:00"."""
    if dim in ("month", "quarter") and value is not None:
        try:
            import pandas as pd
            ts = pd.Timestamp(value)
            if dim == "month":
                return ts.strftime("%B %Y")
            return f"Q{(ts.month - 1) // 3 + 1} {ts.year}"
        except Exception:
            pass
    return str(value)

SYSTEM = """You are a finance assistant narrator. You explain query results in plain English.

STRICT RULES:
1. Use ONLY numbers that appear exactly in the data table below. Never round, estimate, or calculate.
2. Keep it to 2-3 sentences maximum.
3. Mention the time window when provided.
4. For breakdowns, highlight the top entry and mention how many groups exist.
5. For single values, state the metric name and value clearly.
6. Use Indian number formatting with commas (e.g. 1,42,000.00).
7. If the table is empty or has no data, say "No matching transactions found."
8. Never say "approximately" or "about". Be exact.
9. Do not add advice, opinions, or suggestions. Just state the facts.

FORMAT:
- Single number: "Total [metric] for [window]: [value]."
- Breakdown: "Across [N] [dimension]s for [window], [top entry] leads at [value], followed by [second] at [value]."
- Empty: "No [type] transactions found for [window]."
"""


def narrate(question: str, df, spec, window_desc: str) -> str:
    """Phrase the answer.

    Default is the deterministic template: it cannot be wrong, and nothing
    leaves the process. NARRATOR_MODE=model has the model phrase it instead,
    which means sending the aggregate result table to the provider -- a
    deliberate choice, not a default, now the provider is third-party.

    When the model does write the prose, every number in it must appear in the
    result set. If not, we tell the model exactly which numbers were invented
    and let it try once more; a second failure falls back to the template.
    """
    import pandas as pd
    from app.boundary import NARRATOR_MODE

    base = template(df, spec, window_desc)
    if NARRATOR_MODE != "model" or df is None or df.empty:
        return base
    if not spec.group_by and pd.isna(df.iloc[0, -1] if len(df) else None):
        return base

    from app.llm import chat, ModelUnavailable

    user_msg = (
        f"Question: {question}\n"
        f"Time window: {window_desc}\n"
        f"Metric: {spec.metric}\n"
        f"Grouped by: {', '.join(spec.group_by) if spec.group_by else 'none (single value)'}\n"
        f"\nResult table:\n{df.head(20).to_string(index=False)}"
    )

    # A BoundaryViolation must NOT be caught here: it means we were about to
    # send a data row to the provider, and that has to surface, not degrade
    # quietly into template output.
    try:
        text = chat("narrator", SYSTEM, user_msg, max_tokens=200)
    except (ModelUnavailable, ValueError):
        return base

    bad = numeric_guard(text, df)
    if not bad:
        return text

    try:
        retry = chat("narrator", SYSTEM,
                     f"{user_msg}\n\nYour previous answer contained numbers that are "
                     f"not in the table: {bad}. Rewrite using ONLY numbers from the table.",
                     max_tokens=200)
    except (ModelUnavailable, ValueError):
        return base
    return base if numeric_guard(retry, df) else retry


def template(df, spec, window_desc: str) -> str:
    """Deterministic fallback. Never wrong, occasionally clunky."""
    import pandas as pd

    value = df.iloc[0, -1] if len(df) else None
    if df.empty or (not spec.group_by and pd.isna(value)):
        what = f" {spec.filters.category.lower()}" if spec.filters.category else ""
        return f"No{what} transactions found for {window_desc}."

    if not spec.group_by:
        label = {"sum_amount": "Total", "count": "Count", "avg_amount": "Average",
                 "max_amount": "Largest", "min_amount": "Smallest"}[spec.metric]
        return f"{label} for {window_desc}: {_measure(spec, value)}"

    top = df.iloc[0]
    dim = spec.group_by[0]
    result = (f"Across {len(df)} {LABELS.get(dim, dim + 's')} for {window_desc}, "
              f"{_group_value(dim, top[dim])} is highest at "
              f"{_measure(spec, top[spec.metric])}.")
    if len(df) > 1:
        second = df.iloc[1]
        result += (f" Followed by {_group_value(dim, second[dim])} at "
                   f"{_measure(spec, second[spec.metric])}.")
    return result


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
        return f"{text} That is {direction} {inr(abs(comp.delta))}{pct} versus {comp.window}."

    movers = [r for r in comp.rows if r.get("delta") is not None]
    if not movers:
        return f"{text} No overlapping figures for {comp.window}."
    top, key = movers[0], spec.group_by[0]
    top = {**top, key: _group_value(key, top[key])}
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
    """Append the callout. The brief asks for this alongside the original
    answer, not as a separate question."""
    if not flags:
        return text
    joined = "; ".join(f.sentence() for f in flags[:3])
    return f"{text} Worth a look: {joined}."
