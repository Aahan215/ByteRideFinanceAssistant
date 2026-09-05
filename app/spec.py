"""QuerySpec: the contract between the LLM planner and the deterministic engine.

Written against the real schema: bank -> account -> transaction, with the
counterparty parsed out of the narration at load time (app/enrich.py).
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Metric = Literal["sum_amount", "count", "avg_amount", "max_amount", "min_amount"]
# "payouts" = debits, "receipts" = credits. There is no vendor_payouts table.
Dataset = Literal["transactions", "payouts", "receipts"]
Dimension = Literal[
    "counterparty", "category", "channel", "transaction_type", "bank_name",
    "bank_code", "account_id", "entity_id", "program_id", "month", "quarter",
]


class DateRange(BaseModel):
    kind: Literal["relative", "absolute", "all_time"] = "all_time"
    # relative: resolved against the DATA's latest date, not the wall clock.
    unit: Optional[Literal["day", "week", "month", "quarter", "year"]] = None
    offset: int = 0                # 0 = current period, -1 = previous
    periods: int = 1               # how many periods the window spans
    start: Optional[str] = None    # absolute, ISO yyyy-mm-dd
    end: Optional[str] = None


class Filters(BaseModel):
    # A list after validation: one merchant recorded under several
    # branch-suffixed names ("X" and "X ANDHERI WEST").
    counterparty: Optional[str | list[str]] = None
    category: Optional[str] = None          # TAX / BANK_CHARGES / TRANSFER / ...
    # Set by the planner, never by the model: used to exclude commitments from a
    # "where could I save?" breakdown.
    exclude_categories: Optional[list[str]] = None
    channel: Optional[str] = None           # UPI / IMPS / NEFT / FT / CHEQUE / CHARGES
    transaction_type: Optional[Literal["credit", "debit"]] = None
    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_id: Optional[str] = None
    entity_id: Optional[str] = None
    program_id: Optional[int] = None
    reference_id: Optional[str] = None      # -> transaction_reference_id (DECISIONS.md #2)
    description_contains: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None


class QuerySpec(BaseModel):
    dataset: Dataset
    metric: Metric = "sum_amount"
    filters: Filters = Field(default_factory=Filters)
    date_range: DateRange = Field(default_factory=DateRange)
    group_by: list[Dimension] = Field(default_factory=list)
    # Period-over-period. When set, the API runs the spec twice and diffs.
    compare_to: Optional[DateRange] = None
    order_desc: bool = True
    limit: int = 50
    # Set by the planner when the question cannot be answered from this schema.
    # The API refuses rather than guessing. See DECISIONS.md #5.
    unsupported_reason: Optional[str] = None

    def merge_patch(self, patch: dict) -> "QuerySpec":
        """Multi-turn: 'how does that compare to the month before?' produces a
        PATCH, not a whole new spec. Deterministic merge, no LLM involved."""
        base = self.model_dump()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update({kk: vv for kk, vv in v.items() if vv is not None})
            elif v is not None:
                base[k] = v
        return QuerySpec(**base)
