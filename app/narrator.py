"""Result table -> plain English. Runs AFTER the numbers are already computed."""
from __future__ import annotations
from app.validator import numeric_guard

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
    """Call the LLM to narrate, with numeric_guard as safety net.
    Falls back to template if the LLM hallucinates or is unavailable."""
    try:
        from app.llm import chat, ModelUnavailable
        import pandas as pd

        value = df.iloc[0, -1] if len(df) else None
        if df.empty or (not spec.group_by and pd.isna(value)):
            return template(df, spec, window_desc)

        table_str = df.head(20).to_string(index=False)
        user_msg = (
            f"Question: {question}\n"
            f"Time window: {window_desc}\n"
            f"Metric: {spec.metric}\n"
            f"Grouped by: {', '.join(spec.group_by) if spec.group_by else 'none (single value)'}\n"
            f"\nResult table:\n{table_str}"
        )

        text = chat("narrator", SYSTEM, user_msg, max_tokens=200)

        bad = numeric_guard(text, df)
        if bad:
            text2 = chat("narrator", SYSTEM,
                         f"{user_msg}\n\nYour previous answer contained numbers not in the table: {bad}. "
                         f"Rewrite using ONLY numbers from the table.",
                         max_tokens=200)
            bad2 = numeric_guard(text2, df)
            if bad2:
                return template(df, spec, window_desc)
            return text2

        return text

    except Exception:
        return template(df, spec, window_desc)


def template(df, spec, window_desc: str) -> str:
    """Deterministic fallback. Never wrong, occasionally clunky."""
    import pandas as pd

    value = df.iloc[0, -1] if len(df) else None
    if df.empty or (not spec.group_by and pd.isna(value)):
        what = f" {spec.filters.category.lower()}" if spec.filters.category else ""
        return f"No{what} transactions found for {window_desc}."

    if not spec.group_by:
        return f"{spec.metric.replace('_', ' ')} for {window_desc}: {value:,.2f}"
    top = df.iloc[0]
    dim = spec.group_by[0]
    result = (f"Across {len(df)} {dim}s for {window_desc}, "
              f"{top[dim]} is highest at {top[spec.metric]:,.2f}.")
    if len(df) > 1:
        second = df.iloc[1]
        result += f" Followed by {second[dim]} at {second[spec.metric]:,.2f}."
    return result
