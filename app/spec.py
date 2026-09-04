"""QuerySpec: the contract between the LLM planner and the deterministic engine.

This is the single most important file in the repo. The planner's ONLY job is to
emit a valid QuerySpec. The compiler's ONLY job is to turn one into SQL.
Neither side needs to know how the other works -- that is what lets the team
work in parallel.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Metric = Literal["sum_amount", "count", "avg_amount", "max_amount", "min_amount"]
Dataset = Literal["transactions", "vendor_payouts"]
Dimension = Literal["vendor", "category", "account_code", "status", "month", "quarter"]


class DateRange(BaseModel):
    kind: Literal["relative", "absolute", "all_time"] = "all_time"
    # relative: unit + offset, resolved against the data anchor date.
    # offset 0 = current period, -1 = previous period.
    unit: Optional[Literal["day", "week", "month", "quarter", "year"]] = None
    offset: int = 0
    periods: int = 1               # how many periods back to span
    start: Optional[str] = None    # absolute, ISO yyyy-mm-dd
    end: Optional[str] = None


class Filters(BaseModel):
    vendor: Optional[str] = None
    category: Optional[str] = None
    account_code: Optional[str] = None
    status: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None


class QuerySpec(BaseModel):
    dataset: Dataset
    metric: Metric = "sum_amount"
    filters: Filters = Field(default_factory=Filters)
    date_range: DateRange = Field(default_factory=DateRange)
    group_by: list[Dimension] = Field(default_factory=list)
    order_desc: bool = True
    limit: int = 50
    # Set by the planner when it cannot map the question to this schema.
    # The API must refuse rather than guess when this is populated.
    unsupported_reason: Optional[str] = None

    def merge_patch(self, patch: dict) -> "QuerySpec":
        """Multi-turn: 'how does that compare to last month?' produces a PATCH,
        not a whole new spec. Deterministic merge, no LLM involved."""
        base = self.model_dump()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update({kk: vv for kk, vv in v.items() if vv is not None})
            elif v is not None:
                base[k] = v
        return QuerySpec(**base)
