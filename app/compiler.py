"""QuerySpec -> parameterised SQL against the enriched view.

Nothing from the model is interpolated into SQL as a string: metrics and
dimensions are looked up in the semantic-layer allow-list, and every literal
goes through a bound parameter.
"""
from __future__ import annotations
import re
from app.db import SEMANTIC
from app.dates import resolve
from app.spec import QuerySpec

# Columns the data dictionary marks sensitive. Never selected raw.
SENSITIVE = SEMANTIC["sensitive_columns"]
REF_DEFAULT = SEMANTIC["reference_columns"]["default"]


def _dim_expr(dim: str, date_col: str) -> str:
    d = SEMANTIC["dimensions"][dim]
    return d["expr"].format(date=date_col) if "expr" in d else d["column"]


def _where(spec: QuerySpec, date_col: str, amount_col: str,
           scope=None) -> tuple[list[str], list]:
    """THE choke point. Every query builder goes through here, which is why the
    scope predicate lives here and not in each builder -- one path that forgets
    it would leak another user's transactions."""
    where, params = [], []

    if scope is not None:
        pred, sparams = scope.predicate()
        if pred:
            where.append(pred)
            params.extend(sparams)
    for field, value in spec.filters.model_dump().items():
        if value is None:
            continue
        if field == "min_amount":
            where.append(f"{amount_col} >= ?"); params.append(value)
        elif field == "max_amount":
            where.append(f"{amount_col} <= ?"); params.append(value)
        elif field == "reference_id":
            # DECISIONS.md #2 -- a bare "ref no" hits the plaintext column.
            where.append(f"{REF_DEFAULT} = ?"); params.append(value)
        elif field == "exclude_categories":
            if value:
                where.append(f"category NOT IN ({', '.join('?' * len(value))})")
                params.extend(str(v) for v in value)
        elif field == "description_contains":
            where.append("description ILIKE ?"); params.append(f"%{value}%")
        elif field == "counterparty":
            # already resolved by the validator; a list means one merchant
            # recorded under several branch-suffixed names
            if isinstance(value, (list, tuple)):
                where.append(f"counterparty IN ({', '.join('?' * len(value))})")
                params.extend(str(v) for v in value)
            else:
                where.append("counterparty = ?"); params.append(str(value))
        else:
            where.append(f"{SEMANTIC['dimensions'][field]['column']} = ?")
            params.append(value)
    return where, params


def compile_sql(spec: QuerySpec, anchor, date_range=None, scope=None) -> tuple[str, list, dict]:
    ds = SEMANTIC["datasets"][spec.dataset]
    view, date_col, amt_col = ds["view"], ds["date_column"], ds["amount_column"]

    metric_sql = SEMANTIC["metrics"][spec.metric]["sql"].format(amount=amt_col)

    selects, groups, notnull = [], [], []
    for dim in spec.group_by:
        expr = _dim_expr(dim, date_col)
        selects.append(f"{expr} AS {dim}")
        groups.append(expr)
        # A NULL group key is not a vendor. Left in, the pooled tax/charges/cash
        # rows top every "where did I spend the most" ranking as a phantom
        # entry. Excluded here and reported separately, never silently dropped.
        notnull.append(f"{expr} IS NOT NULL")

    where, params = _where(spec, date_col, amt_col, scope)
    where.extend(notnull)
    if ds.get("fixed_filter"):          # payouts = debits, receipts = credits
        where.insert(0, ds["fixed_filter"])

    start, end = resolve(date_range or spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)

    sql = f"SELECT {', '.join(selects + [f'{metric_sql} AS {spec.metric}'])} FROM {view}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    sql += f" ORDER BY {spec.metric} {'DESC' if spec.order_desc else 'ASC'}"
    sql += f" LIMIT {int(spec.limit)}"
    return sql, params, {"window": (start, end), "view": view}


def compile_null_group_sql(spec: QuerySpec, anchor, scope=None) -> tuple[str, list] | None:
    """How much of the total is in rows the group dimension cannot name.
    Surfaced as a warning so a ranking never quietly omits real money."""
    if not spec.group_by:
        return None
    ds = SEMANTIC["datasets"][spec.dataset]
    view, date_col, amt_col = ds["view"], ds["date_column"], ds["amount_column"]
    where, params = _where(spec, date_col, amt_col, scope)
    if ds.get("fixed_filter"):
        where.insert(0, ds["fixed_filter"])
    where.append(f"{_dim_expr(spec.group_by[0], date_col)} IS NULL")
    start, end = resolve(spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)
    # Split by cause. A vendor ranking that excludes tax and bank charges is
    # CORRECT -- those have no payee. Only a narration we failed to parse is a
    # real gap, and only that should count against confidence.
    unattributed = ("SUM(CASE WHEN parsed_by IN ('unparsed', 'empty') "
                    f"THEN {amt_col} ELSE 0 END)")
    unattributed_n = "SUM(CASE WHEN parsed_by IN ('unparsed', 'empty') THEN 1 ELSE 0 END)"
    return (f"SELECT SUM({amt_col}) AS excluded, COUNT(*) AS rows, "
            f"{unattributed} AS unattributed, {unattributed_n} AS unattributed_rows "
            f"FROM {view} WHERE {' AND '.join(where)}"), params


def compile_count_sql(spec: QuerySpec, anchor, scope=None) -> tuple[str, list]:
    """How many transactions the answer actually rests on. Feeds the confidence
    signal -- an aggregate over six rows is not a trend."""
    ds = SEMANTIC["datasets"][spec.dataset]
    view, date_col, amt_col = ds["view"], ds["date_column"], ds["amount_column"]
    where, params = _where(spec, date_col, amt_col, scope)
    if ds.get("fixed_filter"):
        where.insert(0, ds["fixed_filter"])
    for dim in spec.group_by:
        where.append(f"{_dim_expr(dim, date_col)} IS NOT NULL")
    start, end = resolve(spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)
    sql = f"SELECT COUNT(*) AS n FROM {view}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return sql, params


def compile_anomaly_sql(spec: QuerySpec, anchor, limit: int = 3, scope=None):
    """Unusual amounts among ALL rows the answer covers.

    Reads the flags materialised at load time, so this is a filter on a sparse
    column rather than a full rescore.
    """
    ds = SEMANTIC["datasets"][spec.dataset]
    view, date_col, amt_col = ds["view"], ds["date_column"], ds["amount_column"]
    where, params = _where(spec, date_col, amt_col, scope)
    if ds.get("fixed_filter"):
        where.insert(0, ds["fixed_filter"])
    start, end = resolve(spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)
    where.append("anomaly_score IS NOT NULL")
    from app.anomaly import HIGH_SIDE_ONLY
    if HIGH_SIDE_ONLY:
        # the brief asks for unusually LARGE payouts; filter in SQL rather than
        # fetching rows only to discard them
        where.append("transaction_amount > typical_amount")
    sql = (f"SELECT counterparty, transaction_amount, transaction_date, "
           f"typical_amount, history_n AS n, anomaly_score AS score FROM {view} "
           f"WHERE {' AND '.join(where)} ORDER BY anomaly_score DESC LIMIT {limit * 4}")
    return sql, params


def render_sql(sql: str, params: list) -> str:
    """Splice bound values back into a `?`-parameterised query, for display
    only -- never for execution. Lets the "show your working" panel read like
    the query that actually ran instead of a wall of question marks."""
    it = iter(params)

    def repl(_):
        val = next(it)
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        if isinstance(val, (int, float)):
            return str(val)
        return "'" + str(val).replace("'", "''") + "'"

    return re.sub(r"\?", repl, sql)


def evidence_columns() -> str:
    """The drill-down projection. Sensitive columns are masked in SQL so raw
    values never reach the API layer, let alone the model or the screen."""
    cols = ["transaction_id", "transaction_date", "transaction_type", "description",
            "transaction_amount", "counterparty", "category", "channel",
            "bank_name", "transaction_reference_id"]
    masked = []
    for col, rule in SENSITIVE.items():
        if rule["mask"] == "last4":
            # Already masked at load time from the DECRYPTED value -- masking
            # here would slice ciphertext and produce a convincing-looking lie.
            masked.append(f"CAST({col} AS VARCHAR) AS {col}")
        else:
            masked.append(f"CASE WHEN {col} IS NULL THEN NULL ELSE '[redacted]' END AS {col}")
    return ", ".join(cols + masked)


def compile_evidence_sql(spec: QuerySpec, anchor, limit: int = 200, scope=None):
    """The rows behind the number. Required by 'verifiable answers'.

    Must apply EVERY predicate the aggregate applies, including the
    IS NOT NULL guards added for grouped queries. Showing rows the aggregate
    excluded is a grounding failure in the panel whose whole job is to prove
    grounding.
    """
    ds = SEMANTIC["datasets"][spec.dataset]
    view, date_col, amt_col = ds["view"], ds["date_column"], ds["amount_column"]
    where, params = _where(spec, date_col, amt_col, scope)
    if ds.get("fixed_filter"):
        where.insert(0, ds["fixed_filter"])
    for dim in spec.group_by:
        where.append(f"{_dim_expr(dim, date_col)} IS NOT NULL")
    start, end = resolve(spec.date_range, anchor)
    if start:
        where.append(f"{date_col} >= ?"); params.append(start)
    if end:
        where.append(f"{date_col} < ?"); params.append(end)

    sql = f"SELECT {evidence_columns()} FROM {view}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {date_col} DESC LIMIT {int(limit)}"
    return sql, params
