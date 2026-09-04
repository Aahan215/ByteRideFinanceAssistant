"""QuerySpec -> parameterised SQL. Fully deterministic, fully testable.

Nothing the model produces is ever interpolated into SQL as a string: metrics
and dimensions are looked up in the semantic layer allow-list, and all literal
values go through bound parameters.
"""
from __future__ import annotations
from app.db import SEMANTIC
from app.dates import resolve
from app.spec import QuerySpec


def compile_sql(spec: QuerySpec, anchor) -> tuple[str, list, dict]:
    ds = SEMANTIC["datasets"][spec.dataset]
    table, date_col, amt_col = ds["table"], ds["date_column"], ds["amount_column"]

    metric_sql = SEMANTIC["metrics"][spec.metric]["sql"].format(amount=amt_col)

    selects, groups = [], []
    for dim in spec.group_by:
        d = SEMANTIC["dimensions"][dim]
        expr = d["expr"].format(date=date_col) if "expr" in d else d["column"]
        selects.append(f"{expr} AS {dim}")
        groups.append(expr)

    where, params = [], []
    for field, value in spec.filters.model_dump().items():
        if value is None:
            continue
        if field == "min_amount":
            where.append(f"{amt_col} >= ?"); params.append(value)
        elif field == "max_amount":
            where.append(f"{amt_col} <= ?"); params.append(value)
        else:
            col = SEMANTIC["dimensions"][field]["column"]
            where.append(f"{col} = ?"); params.append(value)

    start, end = resolve(spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)

    sql = f"SELECT {', '.join(selects + [f'{metric_sql} AS {spec.metric}'])} FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    sql += f" ORDER BY {spec.metric} {'DESC' if spec.order_desc else 'ASC'}"
    sql += f" LIMIT {int(spec.limit)}"

    return sql, params, {"window": (start, end), "table": table}


def compile_evidence_sql(spec: QuerySpec, anchor, limit: int = 200):
    """The drill-down query: the actual rows behind the number.
    Required by 'verifiable answers' -- every answer ships its receipts."""
    agg, params, meta = compile_sql(spec, anchor)
    body = agg.split(" FROM ", 1)[1].split(" GROUP BY")[0].split(" ORDER BY")[0]
    return f"SELECT * FROM {body} LIMIT {int(limit)}", params
