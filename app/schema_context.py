"""The schema description the planner sees.

GENERATED, never hand-written, so it cannot drift from semantic_layer.yaml or
the organisers' data dictionary. Add a dimension or a category in one place and
the model is told about it here.

WHAT IS DELIBERATELY EXCLUDED: counterparty values. Vendor and payee names are
transaction-derived data -- who you pay is exactly the kind of thing that must
not leave the process (see app/boundary.py). The model receives the user's
wording and app/validator.resolve_counterparty() matches it against the real
vocabulary here, after the model has finished. Closed reference vocabularies
(categories, channels, banks) are schema, not data, and are safe to send.
"""
from __future__ import annotations
import functools

from app.db import SEMANTIC, anchor_date, data_max_date, run

# Measured on the 49-question golden set with qwen3:4b:
#   context off  49/49  100%
#   context on   47/49   96%
# More schema is not automatically better for a small model -- the extra ~720
# tokens crowd out the few-shot examples it actually learns the shape from.
# Left ON for larger models via FINANCE_SCHEMA_CONTEXT=1.
import os
ENABLED = os.getenv("FINANCE_SCHEMA_CONTEXT", "0") == "1"

DATASET_MEANING = {
    "payouts": "money going OUT (transaction_type = 'debit'). Use for spending.",
    "receipts": "money coming IN (transaction_type = 'credit'). Use for income.",
    "transactions": "both directions. Use when the question does not specify.",
}

DIMENSION_MEANING = {
    "counterparty": "the merchant or person on the other side, PARSED from the "
                    "free-text narration -- there is no vendor table",
    "category": "spending category, DERIVED from the narration by keyword rules "
                "-- there is no category column in the source data",
    "channel": "the payment rail the money moved over",
    "transaction_type": "credit or debit",
    "bank_name": "the bank holding the account",
    "bank_code": "IFSC-prefix code for the bank",
    "account_id": "one bank account",
    "entity_id": "the customer or business that owns accounts",
    "program_id": "which product/programme the account belongs to",
    "month": "calendar month of the transaction",
    "quarter": "calendar quarter of the transaction",
}

CATEGORY_MEANING = {
    "TAX": "GST, CGST, SGST, IGST, TDS, TCS, advance tax, challans",
    "BANK_CHARGES": "fees, commission, penalties, AMC, SMS charges",
    "INTEREST": "interest paid or received",
    "EMI_LOAN": "loan instalments, EMIs, disbursements",
    "SALARY": "salary and payroll",
    "UTILITIES": "electricity, gas, water, broadband, mobile recharges",
    "INSURANCE": "premiums and policies",
    "INVESTMENT": "mutual funds, SIPs, broking, demat",
    "CASH": "ATM withdrawals and cash deposits",
    "CHEQUE": "cheque deposits and clearings",
    "RENT": "rent payments",
    "TRANSFER": "a plain transfer with no other category signal",
    "FOOD": "restaurants, food delivery, cafes",
    "GROCERIES": "supermarkets, provision and general stores",
    "FUEL": "petrol pumps and fuel stations",
    "HEALTHCARE": "pharmacies, hospitals, clinics, diagnostics",
    "JEWELLERY": "jewellers and gold",
    "APPAREL": "clothing, footwear, eyewear, sportswear",
    "ELECTRONICS": "electronics, mobiles and appliances",
    "HOME": "furniture, hardware, home goods",
    "UNCATEGORISED": "narration matched no rule -- internal only, never filterable",
}


def _distinct(column: str, limit: int = 20) -> list[str]:
    try:
        rows = run(f"SELECT DISTINCT {column} FROM {SEMANTIC['base_view']} "
                   f"WHERE {column} IS NOT NULL ORDER BY 1 LIMIT {limit}")
        return [str(r[0]) for r in rows.values]
    except Exception:
        return []


@functools.lru_cache(maxsize=1)
def schema_context() -> str:
    """A described schema block for the planner prompt."""
    if not ENABLED:
        return ""
    lines: list[str] = []
    add = lines.append

    add("DATA YOU ARE QUERYING")
    add("Indian bank transactions for one company, in INR. Three source tables:")
    add("  bank         one row per bank (code, name)")
    add("  account      one row per bank account; belongs to a bank and an entity")
    add("  transaction  one row per credit or debit; belongs to an account")
    add("They are pre-joined into a single view, so you never write joins.")
    add("")

    try:
        lo = run(f"SELECT MIN(transaction_date) FROM {SEMANTIC['base_view']}").iloc[0, 0]
        add(f"COVERAGE: {str(lo)[:10]} to {data_max_date()}. "
            f'"Today" for relative dates is {anchor_date()}.')
        add("")
    except Exception:
        pass

    add("DATASETS")
    for name, meaning in DATASET_MEANING.items():
        add(f"  {name:14} {meaning}")
    add("")

    add("DIMENSIONS you may group by or filter on")
    for dim in SEMANTIC["dimensions"]:
        add(f"  {dim:16} {DIMENSION_MEANING.get(dim, '')}")
    add("")

    add("CATEGORIES (derived from the narration; this list is exhaustive)")
    for cat in SEMANTIC["spend_categories"]:
        if cat == "UNCATEGORISED":
            continue
        add(f"  {cat:14} {CATEGORY_MEANING.get(cat, '')}")
    add("")

    if channels := _distinct("channel", 12):
        add(f"CHANNELS present in this data: {', '.join(channels)}")
    if banks := _distinct("bank_name", 12):
        add(f"BANKS present in this data: {', '.join(banks)}")
    add("")

    add("NOT IN THIS DATA -- say so rather than approximating:")
    add("  reconciliation or matching status, budgets, forecasts, credit scores,")
    add("  net worth, invoices, accounting statements, tax owed, and any category")
    add("  not listed above (groceries, fuel, travel, dining, ...).")
    add("")
    add("Vendor names are parsed from narrations and may carry branch suffixes")
    add('("ACME TRADERS ANDHERI WEST"). Pass through whatever name the user typed;')
    add("the system matches it to the real vendor afterwards.")
    return "\n".join(lines)
