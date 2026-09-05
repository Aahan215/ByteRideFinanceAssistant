"""Keyword planner for developing WITHOUT a model.

Not part of the product. It exists so the UI, the evidence panel and the export
path can be built and demoed before Ollama is running -- the alternative is
four people idle while one person wires up a model.

Enabled only by FINANCE_STUB_PLANNER=1, and every response it produces carries
a loud warning so it cannot be mistaken for the real thing on stage.
"""
from __future__ import annotations
import re
from app.nlq_dates import extract as extract_dates
from app.spec import QuerySpec, Filters, DateRange

CATEGORY_WORDS = {
    "tax": "TAX", "gst": "TAX", "tds": "TAX",
    "charge": "BANK_CHARGES", "fee": "BANK_CHARGES",
    "emi": "EMI_LOAN", "loan": "EMI_LOAN",
    "rent": "RENT", "salary": "SALARY", "utilit": "UTILITIES",
    "insur": "INSURANCE", "invest": "INVESTMENT", "cash": "CASH",
}
OUT_OF_SCOPE = ("reconcil", "budget", "forecast", "credit score", "tax return",
                "profit", "balance sheet", "p&l", "invoice")


def plan(question: str, prior: QuerySpec | None = None, **_) -> QuerySpec:
    q = question.lower()

    for term in OUT_OF_SCOPE:
        if term in q:
            return QuerySpec(dataset="transactions", unsupported_reason=(
                f"I can only answer from transaction records — spend, receipts, "
                f"counterparties, categories and dates. I have nothing about “{term}”."))

    dr, _ = extract_dates(question)
    filters = Filters()
    for word, cat in CATEGORY_WORDS.items():
        if word in q:
            filters.category = cat
            break

    dataset = "receipts" if re.search(r"\b(received|credit|income|salary)\b", q) else "payouts"
    metric = "count" if re.search(r"\bhow many|number of|count\b", q) else "sum_amount"

    group_by = []
    if re.search(r"\bby category|per category|breakdown|break.*down\b", q):
        group_by = ["category"]
    elif re.search(r"\bby (vendor|merchant|payee)|where .*(spend|spent)|top\b", q):
        group_by = ["counterparty"]
    elif re.search(r"\bby month|monthly|over time|trend\b", q):
        group_by = ["month"]
    elif re.search(r"\bby bank\b", q):
        group_by = ["bank_name"]

    compare = None
    if re.search(r"\bcompare|versus|vs\b|month before|previous (month|period)", q):
        if prior is not None and not dr:
            dr = prior.date_range
            filters = prior.filters
            dataset, metric, group_by = prior.dataset, prior.metric, prior.group_by
        base = dr or DateRange(kind="relative", unit="month", offset=0)
        # Shift by the FULL span: the previous 3 months, not the previous month.
        compare = base.model_copy(update={"offset": base.offset - max(base.periods, 1)})

    spec = QuerySpec(dataset=dataset, metric=metric, filters=filters,
                     group_by=group_by, limit=10 if group_by else 50)
    if dr:
        spec = spec.model_copy(update={"date_range": dr})
    if compare:
        spec = spec.model_copy(update={"compare_to": compare})
    return spec
