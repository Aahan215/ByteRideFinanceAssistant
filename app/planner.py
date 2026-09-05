"""Natural language -> QuerySpec. The only place an LLM sees the user's words.

Three ideas make an 8B model reliable here:

1. **Shrink the job.** Date phrases are resolved deterministically before the
   model runs (app/nlq_dates.py), so the model only has to get dataset, metric,
   filters and group_by right.
2. **Coerce, then validate.** Small models make a small set of predictable
   mistakes -- wrapper keys, synonyms, a string where a list belongs. `coerce`
   fixes those deterministically before pydantic ever sees the payload, and it
   is fully testable without a model.
3. **Repair once, then refuse.** If a coerced payload still fails validation,
   the error goes back to the model once. A second failure is a refusal, never
   a guess.

The model NEVER computes a number and never sees a row of data.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from pydantic import ValidationError

from app.db import SEMANTIC
from app.llm import chat_json, CFG
from app.nlq_dates import extract as extract_dates
from app.spec import QuerySpec, DateRange

ChatFn = Callable[..., dict]

# --- vocabulary, derived from the semantic layer so it cannot drift ----------
DATASETS = list(SEMANTIC["datasets"])
METRICS = list(SEMANTIC["metrics"])
DIMENSIONS = list(SEMANTIC["dimensions"])
# UNCATEGORISED is where narrations we could not classify land. It must never
# be offered to the model as something a user can ask for: "groceries" mapping
# to UNCATEGORISED silently answers a question about a category we do not have.
CATEGORIES = [c for c in SEMANTIC["spend_categories"] if c != "UNCATEGORISED"]

DATASET_ALIASES = {
    "transaction": "transactions", "txn": "transactions", "txns": "transactions",
    "all": "transactions", "spend": "payouts", "spends": "payouts",
    "debit": "payouts", "debits": "payouts", "payout": "payouts",
    "vendor_payouts": "payouts", "expenses": "payouts", "outflow": "payouts",
    "credit": "receipts", "credits": "receipts", "income": "receipts",
    "receipt": "receipts", "inflow": "receipts",
}
METRIC_ALIASES = {
    "total": "sum_amount", "sum": "sum_amount", "amount": "sum_amount",
    "total_amount": "sum_amount", "spend": "sum_amount",
    "number": "count", "num": "count", "n": "count", "how_many": "count",
    "average": "avg_amount", "avg": "avg_amount", "mean": "avg_amount",
    "largest": "max_amount", "biggest": "max_amount", "max": "max_amount",
    "smallest": "min_amount", "min": "min_amount",
}
DIM_ALIASES = {
    "vendor": "counterparty", "merchant": "counterparty", "payee": "counterparty",
    "supplier": "counterparty", "name": "counterparty", "who": "counterparty",
    "type": "transaction_type", "bank": "bank_name", "account": "account_id",
    "entity": "entity_id", "program": "program_id", "cat": "category",
}
WRAPPER_KEYS = ("query", "spec", "queryspec", "query_spec", "result", "output")

# Flattened by hand rather than taken from pydantic: model_json_schema() uses
# $ref/$defs, which grammar-constrained decoders do not resolve. Enum values come
# from the semantic layer, so the model cannot emit a dataset or metric we do not
# have -- the constraint is enforced during decoding, not repaired afterwards.
def planner_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "dataset": {"type": "string", "enum": DATASETS},
            "metric": {"type": "string", "enum": METRICS},
            "group_by": {"type": "array", "items": {"type": "string", "enum": DIMENSIONS}},
            "filters": {
                "type": "object",
                "properties": {
                    "counterparty": {"type": "string"},
                    # NOT_IN_DATA is the escape hatch. Without a way to say
                    # "the category asked for is not one of these", constrained
                    # decoding forces the model to pick the nearest wrong one.
                    "category": {"type": "string", "enum": CATEGORIES + ["NOT_IN_DATA"]},
                    "channel": {"type": "string"},
                    "transaction_type": {"type": "string", "enum": ["credit", "debit"]},
                    "bank_name": {"type": "string"},
                    "bank_code": {"type": "string"},
                    "reference_id": {"type": "string"},
                    "description_contains": {"type": "string"},
                    "min_amount": {"type": "number"},
                    "max_amount": {"type": "number"},
                },
            },
            "limit": {"type": "integer"},
            "unsupported_reason": {"type": "string"},
        },
        "required": ["dataset", "metric", "group_by"],
    }


UNCHANGED = "unchanged"
CLEAR = "none"


def refine_schema() -> dict:
    """A follow-up is a REFINEMENT, not a fresh spec.

    Asking a 4B to "emit only what changed" fails two ways: shown the prior spec
    as JSON it copies the blob verbatim, and told to omit unchanged fields it
    cannot decide what to omit. So every field is REQUIRED and carries an
    explicit "unchanged" sentinel -- the model never makes an omission decision,
    only picks one token per field from a closed set.

    group_by is a single value, not a list: real refinements regroup by one
    thing, and a list invited the model to append rather than replace.
    """
    return {
        "type": "object",
        "properties": {
            "dataset": {"type": "string", "enum": [UNCHANGED] + DATASETS},
            "metric": {"type": "string", "enum": [UNCHANGED] + METRICS},
            "group_by": {"type": "string", "enum": [UNCHANGED, CLEAR] + DIMENSIONS},
            "category": {"type": "string", "enum": [UNCHANGED, CLEAR] + CATEGORIES},
            "counterparty": {"type": "string"},
        },
        "required": ["dataset", "metric", "group_by", "category", "counterparty"],
    }


REFINE_PROMPT = f"""The user asked a question, got an answer, and is now refining it.

WHAT THEY SAW: %s

Decide what their follow-up CHANGES. Every field is required. Use
"{UNCHANGED}" for anything the follow-up does not mention, and "{CLEAR}" to
remove a grouping or filter. Reply with JSON only.

dataset    {UNCHANGED} | payouts (spending) | receipts (income) | transactions (both)
metric     {UNCHANGED} | sum_amount | count | avg_amount | max_amount | min_amount
group_by   {UNCHANGED} | {CLEAR} | counterparty | category | channel | bank_name | month | quarter
category   {UNCHANGED} | {CLEAR} | one of {CATEGORIES}
counterparty  "{UNCHANGED}", "{CLEAR}", or a vendor name

Time periods are handled elsewhere -- ignore any mention of dates.

Examples:
"break that down by category instead" -> {{"dataset":"{UNCHANGED}","metric":"{UNCHANGED}","group_by":"category","category":"{UNCHANGED}","counterparty":"{UNCHANGED}"}}
"just show me tax" -> {{"dataset":"{UNCHANGED}","metric":"{UNCHANGED}","group_by":"{UNCHANGED}","category":"TAX","counterparty":"{UNCHANGED}"}}
"what about receipts?" -> {{"dataset":"receipts","metric":"{UNCHANGED}","group_by":"{UNCHANGED}","category":"{UNCHANGED}","counterparty":"{UNCHANGED}"}}
"show the count instead" -> {{"dataset":"{UNCHANGED}","metric":"count","group_by":"{UNCHANGED}","category":"{UNCHANGED}","counterparty":"{UNCHANGED}"}}
"how does that compare to last month?" -> {{"dataset":"{UNCHANGED}","metric":"{UNCHANGED}","group_by":"{UNCHANGED}","category":"{UNCHANGED}","counterparty":"{UNCHANGED}"}}
"""


def describe_spec(s: QuerySpec) -> str:
    """The prior turn in English. Showing it as JSON makes small models copy the
    blob verbatim -- three different follow-ups returned byte-identical output."""
    parts = [{"payouts": "total money going out", "receipts": "total money coming in",
              "transactions": "all transactions"}[s.dataset]]
    parts[0] = {"sum_amount": parts[0], "count": "the number of " + s.dataset,
                "avg_amount": "the average " + s.dataset,
                "max_amount": "the largest of " + s.dataset,
                "min_amount": "the smallest of " + s.dataset}[s.metric]
    if s.group_by:
        parts.append("broken down by " + ", ".join(s.group_by))
    active = {k: v for k, v in s.filters.model_dump().items() if v is not None}
    if active:
        parts.append("filtered to " + ", ".join(f"{k} {v}" for k, v in active.items()))
    return ", ".join(parts)


def apply_refinement(prior: QuerySpec, r: dict) -> QuerySpec:
    """Deterministic application. REPLACE semantics, never merge -- the model
    appending to group_by instead of replacing it was a real failure."""
    spec = prior.model_copy(deep=True)

    if (v := r.get("dataset")) and v not in (UNCHANGED, CLEAR) and v in DATASETS:
        spec.dataset = v
    if (v := r.get("metric")) and v not in (UNCHANGED, CLEAR) and v in METRICS:
        spec.metric = v

    v = r.get("group_by")
    if v == CLEAR:
        spec.group_by = []
    elif v and v != UNCHANGED and v in DIMENSIONS:
        spec.group_by = [v]

    v = r.get("category")
    if v == CLEAR:
        spec.filters.category = None
    elif v and v != UNCHANGED and v in CATEGORIES:
        spec.filters.category = v

    v = r.get("counterparty")
    if v == CLEAR:
        spec.filters.counterparty = None
    elif v and v not in (UNCHANGED, CLEAR):
        from app.enrich import normalise
        spec.filters.counterparty = normalise(str(v)) or None
    return spec


# Concepts this schema genuinely cannot express. Deliberately HIGH PRECISION --
# every term here is absent from bank/account/transaction, so a match is a real
# refusal, not a guess. A constrained decoder will otherwise map an unknown
# concept to the NEAREST allowed value: "groceries" became category CASH and
# returned Rs 42 crore, "unreconciled" became a reference_id and returned 0.
OUT_OF_SCOPE = (
    # no leading \b: "unreconciled" has no boundary before "reconcil"
    (re.compile(r"\w*[-\s]?reconcil\w*|\bun[-\s]?matched\b|\bsettlement status\b|"
                r"\bnot (yet )?(matched|settled|cleared)\b", re.I),
     "This dataset has no reconciliation status. The transaction table records "
     "id, date, type, description, amount and reference numbers -- there is no "
     "field saying whether a transaction was matched to an external record, and "
     "I will not infer one. I can show transactions with or without a reference "
     "number if that helps."),
    (re.compile(r"\bbudget(s|ed|ing)?\b", re.I),
     "I have no budgets. I can only report what was actually spent."),
    (re.compile(r"\b(forecast|predict|projection|will i spend|next (month|quarter|year))\b", re.I),
     "I can only report transactions that have already happened; I do not forecast."),
    (re.compile(r"\bcredit score\b", re.I), "I have no credit score information."),
    (re.compile(r"\bnet worth\b", re.I),
     "I have transaction and balance data, not assets and liabilities."),
    (re.compile(r"\b(profit|p\s*&\s*l|p and l|balance sheet|income statement)\b", re.I),
     "I have no accounting statements -- only bank transactions."),
    (re.compile(r"\binvoices?\b", re.I),
     "I have bank transactions, not invoices."),
    (re.compile(r"\btax\b.{0,15}\bowe|\bowe\b.{0,15}\btax\b|"
                r"\btax (owed|due|liability|return|refund)\b", re.I),
     "I can show tax payments that were made, but I have nothing about tax owed."),
)


# A category filter is only trustworthy if the user actually named that
# category. Constrained decoding forces a choice from the enum, so an unknown
# concept lands on the nearest value -- "groceries" became CASH and returned
# Rs 42 crore. Requiring a cue word turns an invented mapping into a refusal.
CATEGORY_CUES = {
    "TAX": r"tax|gst|tds|tcs|challan|cess|duty",
    "BANK_CHARGES": r"charge|fee|commission|penalty|amc|levy",
    "INTEREST": r"interest",
    "EMI_LOAN": r"emi|loan|instal?ment|repay|borrow|mortgage",
    "SALARY": r"salary|payroll|wage|stipend|income",
    "UTILITIES": r"utilit|electric|power|gas|water|broadband|internet|recharge|mobile|phone|bill",
    "INSURANCE": r"insur|premium|policy|\blic\b",
    "INVESTMENT": r"invest|mutual fund|\bsip\b|stock|share|equity|demat|broker",
    "CASH": r"\bcash\b|\batm\b|withdraw",
    "CHEQUE": r"cheque|check\b",
    "RENT": r"\brent\b|lease",
    "TRANSFER": r"transfer|\bupi\b|\bimps\b|\bneft\b|\brtgs\b",
    # merchant-derived categories -- the words people actually use
    "FOOD": r"\bfood\b|dining|eat(ing)? out|restaurant|swiggy|zomato|takeaway|order(ed|ing)? in",
    "GROCERIES": r"grocer\w*|supermarket|kirana|provision|dmart|d-mart|big ?bazaar|household shopping",
    "FUEL": r"\bfuel\b|petrol|diesel|\bgas station\b|filling station",
    "HEALTHCARE": r"health\w*|medic\w*|pharmac\w*|chemist|doctor|hospital|clinic|medicine",
    "JEWELLERY": r"jewell?\w*|\bgold\b|ornament",
    "APPAREL": r"apparel|clothe?s|clothing|fashion|footwear|shoes|eyewear|glasses|sportswear",
    "ELECTRONICS": r"electronic\w*|gadget|appliance|mobile phone|laptop|\btv\b",
    "HOME": r"\bhome\b|furnitur\w*|hardware|household goods|interior",
}
CATEGORY_CUE_RE = {k: re.compile(v, re.I) for k, v in CATEGORY_CUES.items()}


# "how much did I spend ON groceries" is a category REQUEST. "what is my spend
# this quarter" is not -- so a category filter appearing there was invented.
CATEGORY_REQUEST_RE = re.compile(
    r"\b(on|for|towards|in)\s+[a-z]", re.I)


def category_is_supported(question: str, category: str | None) -> bool:
    if not category or category not in CATEGORY_CUE_RE:
        return True
    return bool(CATEGORY_CUE_RE[category].search(question))


def category_verdict(question: str, category: str | None) -> tuple[str, str | None]:
    """Returns (verdict, replacement) where verdict is ok | fix | drop | refuse.

    Four outcomes, because they are genuinely different situations:
      ok      the model's category matches what the user named
      fix     the user named a category we DO have and the model picked a
              different one -- correct it rather than discarding the question
      drop    the model attached a category the user never mentioned
      refuse  the user asked for a category we do not derive
    """
    if category_is_supported(question, category):
        return "ok", None
    # did they name some OTHER category we know? then the model simply picked wrong
    named = [k for k, rx in CATEGORY_CUE_RE.items()
             if k != category and rx.search(question)]
    if len(named) == 1:
        return "fix", named[0]
    if named:
        return "drop", None
    return ("refuse", None) if CATEGORY_REQUEST_RE.search(question) else ("drop", None)


def out_of_scope(question: str) -> str | None:
    for rx, reason in OUT_OF_SCOPE:
        if rx.search(question):
            return reason
    return None


# The model answers "unchanged" for everything when it is unsure, which is safe
# but useless. Dataset direction is highly regular in English, so decide it
# deterministically -- the same lever that made dates reliable.
DATASET_CUES = (
    ("receipts", re.compile(r"\b(receipts?|income|credits?|came in|coming in|"
                            r"received|inflow|earn(ed|ings)?|deposits?)\b", re.I)),
    ("payouts", re.compile(r"\b(payouts?|spend(ing)?|spent|paid|pay|debits?|"
                           r"went out|going out|outflow|expenses?)\b", re.I)),
    ("transactions", re.compile(r"\b(all transactions|everything|both|"
                                r"all of them|overall)\b", re.I)),
)


# "Trend" is a question about time, and it is regular enough in English to
# decide without the model -- the same lever as dates and dataset direction.
TREND_RE = re.compile(
    r"\b(trends?|over time|month[- ]by[- ]month|monthly|by month|per month|"
    r"quarterly|by quarter|movement|trajectory|how .{0,20}chang\w+)\b", re.I)


def wants_trend(question: str) -> bool:
    return bool(TREND_RE.search(question))


def dataset_from_words(question: str) -> str | None:
    """Only fires on an explicit cue, so a follow-up that says nothing about
    direction leaves the prior dataset alone."""
    for name, rx in DATASET_CUES:
        if rx.search(question):
            return name
    return None


COMPARE_RE = re.compile(
    r"\b(compare[ds]?|versus|\bvs\b|month before|period before|previous (month|period|quarter|year))",
    re.I)


def patch_schema() -> dict:
    """Same shape, nothing required.

    A follow-up must be able to emit ONLY what changed. Reusing the planner
    schema here forced dataset/metric/group_by into every patch, so each
    follow-up overwrote the prior turn with defaults -- multi-turn scored 0/5
    on qwen3:4b while every other bucket was fine.
    """
    s = planner_schema()
    s.pop("required", None)
    return s


class CoercionError(ValueError):
    """The reply could not be mapped onto the schema with confidence.

    Deliberately NOT forgiving. Silently defaulting an unrecognised dataset to
    "payouts" would turn an incoherent reply into a confident wrong answer --
    the precise failure this system exists to prevent. Raising sends it to the
    repair loop, and a second failure becomes an honest refusal.
    """


def _prompt() -> str:
    from app.schema_context import schema_context
    return f"""You are a JSON converter. Convert a finance question into a QuerySpec JSON object.
Reply with ONLY a JSON object. No text before or after.

{schema_context()}

RULES:
- NEVER compute numbers or invent data.
- NEVER emit date_range. Dates are handled separately.
- Tax, fees, charges = CATEGORIES, not vendors.
- "spend"/"paid"/"payouts" = dataset "payouts" (debits).
- "received"/"credits"/"income" = dataset "receipts" (credits).
- "where did I spend the most" = group_by ["counterparty"] on payouts.
- A "which X ...?" question MUST group_by that X, otherwise the answer is a
  single number that cannot say which. "which channel" -> group_by ["channel"],
  "which bank" -> group_by ["bank_name"], "which vendor" -> ["counterparty"].
- METRIC comes from the wording, independently of grouping:
  "spending", "spend", "how much", "total", "value" -> sum_amount
  "how many", "how often", "number of", "count", "most frequently" -> count
- NEVER copy a vendor name from the examples. Extract the EXACT name the user typed.
- "EMI" before a name means category EMI_LOAN and counterparty = the name after EMI.

FIELDS:
  dataset: {DATASETS}  (payouts=debits, receipts=credits, transactions=both)
  metric: {METRICS}
  group_by: list from {DIMENSIONS}  ([] = one number, no breakdown)
  filters: object with ONLY mentioned keys:
    counterparty: vendor name as user wrote it
    category: one of {CATEGORIES}
    channel: UPI|IMPS|NEFT|RTGS|FT|CHEQUE
    transaction_type: "credit" or "debit"
    bank_name: bank name
    bank_code: HDFC|ICIC|SBIN|UTIB|KKBK|CNRB|UBIN|AUBL|TMBL|RATN
    account_id, entity_id, program_id, reference_id
    description_contains: keyword search in description
    min_amount, max_amount: numbers
  limit: integer (default 50)
  unsupported_reason: ONLY if question cannot be answered from above fields.

EXAMPLES:

Q: How much did we spend on vendor payouts last month?
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{}}}}

Q: Where did I spend the most this month?
{{"dataset":"payouts","metric":"sum_amount","group_by":["counterparty"],"filters":{{}},"limit":10}}

Q: Total tax paid in the last 3 months
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{"category":"TAX"}}}}

Q: Which payment channel do I use most often?
{{"dataset":"payouts","metric":"count","group_by":["channel"],"filters":{{}}}}

Q: Spending by payment channel last month
{{"dataset":"payouts","metric":"sum_amount","group_by":["channel"],"filters":{{}}}}

Q: Which bank do I spend the most through?
{{"dataset":"payouts","metric":"sum_amount","group_by":["bank_name"],"filters":{{}}}}

Q: How many UPI payments did I make?
{{"dataset":"payouts","metric":"count","group_by":[],"filters":{{"channel":"UPI"}}}}

Q: What did I pay Reliance Digital?
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{"counterparty":"Reliance Digital"}}}}

Q: Break my spending down by category
{{"dataset":"payouts","metric":"sum_amount","group_by":["category"],"filters":{{}}}}

Q: Show me all HDFC transactions
{{"dataset":"transactions","metric":"sum_amount","group_by":[],"filters":{{"bank_code":"HDFC"}}}}

Q: Which transactions are above 50000?
{{"dataset":"transactions","metric":"count","group_by":[],"filters":{{"min_amount":50000}}}}

Q: Show spending by bank
{{"dataset":"payouts","metric":"sum_amount","group_by":["bank_name"],"filters":{{}}}}

Q: Monthly spending breakdown
{{"dataset":"payouts","metric":"sum_amount","group_by":["month"],"filters":{{}}}}

Q: How much did I receive via NEFT?
{{"dataset":"receipts","metric":"sum_amount","group_by":[],"filters":{{"channel":"NEFT"}}}}

Q: Find transaction with reference 1715499972
{{"dataset":"transactions","metric":"count","group_by":[],"filters":{{"reference_id":"1715499972"}}}}

Q: What is the largest debit transaction?
{{"dataset":"payouts","metric":"max_amount","group_by":[],"filters":{{}}}}

Q: Top 5 vendors by spend
{{"dataset":"payouts","metric":"sum_amount","group_by":["counterparty"],"filters":{{}},"limit":5}}

Q: Quarterly spending breakdown
{{"dataset":"payouts","metric":"sum_amount","group_by":["quarter"],"filters":{{}}}}

Q: How much did we pay EMI to HDFC Home Loans?
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{"counterparty":"HDFC Home Loans","category":"EMI_LOAN"}}}}

Q: What do you think about this vendor?
{{"unsupported_reason":"I can only report what is in your transactions, not form opinions. Try 'how much did we pay [vendor]?'"}}

Q: Why is this amount so high?
{{"unsupported_reason":"I cannot explain why an amount is high or low. I can show the breakdown -- try 'break down spending by category'."}}

Q: What is my credit score?
{{"unsupported_reason":"I only have transaction data; no credit score information available."}}

Q: What will be my balance next month?
{{"unsupported_reason":"I cannot predict future balances. I can show historical transactions and current data."}}

Q: How many employees do we have?
{{"unsupported_reason":"I only have financial transaction data; no employee or HR information available."}}
"""


PATCH_PROMPT = """The user is following up on a previous question.
Reply with a JSON object containing ONLY the fields that CHANGE.
Omit fields that stay the same. Reply {} if nothing changes except dates.

Previous QuerySpec:
%s

Examples of follow-ups:

Prior: payouts by counterparty
Follow-up: "break that down by category instead"
{"group_by":["category"]}

Prior: payouts sum for HDFC
Follow-up: "what about ICICI?"
{"filters":{"bank_code":"ICIC"}}

Prior: payouts sum by counterparty
Follow-up: "show me the count instead"
{"metric":"count"}

Prior: payouts sum
Follow-up: "how about receipts?"
{"dataset":"receipts"}

Follow-up: %s
"""

# A follow-up must SAY it is one: anaphora, an explicit comparison, or a
# refinement of what was just asked. Each entry is matched with surrounding
# spaces, so "it" cannot fire inside "cred-it score".
FOLLOWUP_HINTS = (
    "what about", "how about", "and what", "and the", "and just",
    "compare", "versus", " vs ", "same for", "the same", "similar",
    " that ", " that?", " those ", " those?", " it ", " it?",
    "instead", "but for", "but with", "just show", "just the",
    "only the", "narrow", "drill", "break it", "break that", "what if",
    # pronouns can only refer to a previous turn
    "pay him", "pay her", "pay them", "paid him", "paid her", "paid them",
    "from him", "from her", "from them", "to him", "to her", "to them",
)
# NOTE: date phrases ("last month", "this month", "previous", "earlier") are
# deliberately NOT hints. They appear in perfectly standalone questions --
# "how much did I spend last month?" is not a refinement of anything.


def looks_like_followup(question: str, prior: QuerySpec | None) -> bool:
    """Deliberately conservative -- a follow-up must announce itself.

    A SHORT question is not a follow-up. "Which transactions are unreconciled?"
    is four words and entirely unrelated to whatever came before; the old
    `len(q.split()) <= 5` rule classified it as a refinement, which silently
    inherited the previous turn's vendor filter and turned a correct refusal
    into a confident wrong answer.

    Erring this way costs a little context the user can restate. Erring the
    other way fabricates an answer, which is the failure this whole system
    exists to prevent.
    """
    if prior is None:
        return False
    q = f" {question.lower().strip()} "
    return any(h in q for h in FOLLOWUP_HINTS)


# --- deterministic repair of predictable small-model mistakes ---------------
def coerce(raw: dict, *, patch: bool = False) -> dict:
    """Fix the errors small models actually make, before validation.

    Every branch here is a real failure mode, not defensive padding: wrapper
    keys, synonyms, a bare string where a list belongs, filters hoisted to the
    top level, wrong casing on a closed vocabulary.

    `patch=True` is for multi-turn follow-ups: only keys the model actually
    returned survive. Filling in defaults there would silently wipe the prior
    turn's dataset or filters -- the exact bug multi-turn is supposed to avoid.
    """
    if not isinstance(raw, dict):
        return {}
    d = dict(raw)
    present = set(d)

    # {"query": {...}} -> {...}
    for k in WRAPPER_KEYS:
        if k in d and isinstance(d[k], dict) and len(d) == 1:
            d = dict(d[k])
            break

    if d.get("unsupported_reason"):
        return {"dataset": "transactions", "unsupported_reason": str(d["unsupported_reason"])}

    if "dataset" in present:
        if not isinstance(d["dataset"], str):
            raise CoercionError(f"dataset must be one of {DATASETS}, got {d['dataset']!r}")
        ds = d["dataset"].lower().strip()
        if ds not in DATASETS and ds not in DATASET_ALIASES:
            raise CoercionError(f"unknown dataset {ds!r}; expected one of {DATASETS}")
        d["dataset"] = DATASET_ALIASES.get(ds, ds)
    elif not patch:
        d["dataset"] = "payouts"

    if "metric" in present:
        if not isinstance(d["metric"], str):
            raise CoercionError(f"metric must be one of {METRICS}, got {d['metric']!r}")
        mt = d["metric"].lower().strip()
        if mt not in METRICS and mt not in METRIC_ALIASES:
            raise CoercionError(f"unknown metric {mt!r}; expected one of {METRICS}")
        d["metric"] = METRIC_ALIASES.get(mt, mt)
    elif not patch:
        d["metric"] = "sum_amount"

    gb = d.get("group_by") or []
    if isinstance(gb, str):
        gb = [g.strip() for g in gb.split(",") if g.strip()]
    if not isinstance(gb, list):
        raise CoercionError(f"group_by must be a list of {DIMENSIONS}, got {gb!r}")
    norm = []
    for g in gb:
        if not isinstance(g, str):
            raise CoercionError(f"group_by entry must be a string, got {g!r}")
        g = g.lower().strip()
        mapped = g if g in DIMENSIONS else DIM_ALIASES.get(g)
        if not mapped:
            # asking to group by something we do not have is a real
            # misunderstanding -- repair or refuse, never quietly drop it
            raise CoercionError(f"cannot group by {g!r}; available: {DIMENSIONS}")
        if mapped not in norm:
            norm.append(mapped)
    if norm or not patch:
        d["group_by"] = norm

    filters = d.get("filters") or {}
    if not isinstance(filters, dict):
        raise CoercionError(f"filters must be an object, got {filters!r}")
    # models often hoist filter keys to the top level
    known_filter_keys = set(QuerySpec.model_fields["filters"].annotation.model_fields)
    for k in list(d):
        if k in known_filter_keys and k not in ("dataset", "metric"):
            filters.setdefault(k, d.pop(k))

    clean = {}
    for k, v in filters.items():
        if v in (None, "", [], {}):
            continue
        k = DIM_ALIASES.get(str(k).lower(), str(k).lower())
        if k == "counterparty":
            # The stored group key was produced by enrich.normalise() -- uppercased,
            # legal suffixes and punctuation stripped. A filter written any other
            # way ("Zomato Hyperpure", "Bajaj Finance Ltd.") cannot match it, so
            # the filter goes through the SAME function the data went through.
            from app.enrich import normalise
            v = normalise(str(v))
            if not v:
                continue
        elif k == "category":
            v = str(v).upper().replace(" ", "_")
        elif k == "transaction_type":
            v = str(v).lower()
        elif k == "channel":
            v = str(v).upper()
        elif k in ("min_amount", "max_amount"):
            try:
                v = float(str(v).replace(",", "").replace("₹", ""))
            except ValueError:
                continue
            # A richer prompt makes small models fill every field: min_amount 0
            # and max_amount 1e15 are no-ops that only add noise to the SQL.
            if (k == "min_amount" and v <= 0) or (k == "max_amount" and v >= 1e12):
                continue
        elif k == "program_id":
            try:
                v = int(v)
            except (ValueError, TypeError):
                continue
        if k in known_filter_keys:
            clean[k] = v
    if clean or not patch:
        d["filters"] = clean

    # transactions + transaction_type=debit IS payouts. Same query, and the
    # canonical form keeps downstream logic (and the eval) from seeing two
    # spellings of one thing.
    ttype = clean.get("transaction_type")
    if d.get("dataset") == "transactions" and ttype in ("debit", "credit"):
        d["dataset"] = "payouts" if ttype == "debit" else "receipts"
        clean.pop("transaction_type", None)
        d["filters"] = clean

    if "limit" in present or not patch:
        try:
            d["limit"] = max(1, min(int(d.get("limit", 50)), 500))
        except (ValueError, TypeError):
            d["limit"] = 50

    # dates are ours, not the model's
    d.pop("date_range", None)
    d.pop("compare_to", None)
    return {k: v for k, v in d.items() if k in QuerySpec.model_fields}


@dataclass
class PlanResult:
    spec: QuerySpec
    confidence: str = "high"          # high | medium | low
    date_source: str = "model"        # deterministic | default
    matched_date_text: str | None = None
    attempts: list[str] = field(default_factory=list)
    used_patch: bool = False


def _call(chat_fn: ChatFn | None, system: str, user: str, temperature: float | None,
          schema: dict | None = None) -> dict:
    if chat_fn is not None:                 # tests inject a stand-in
        return chat_fn("planner", system, user, temperature=temperature)
    return chat_json("planner", system, user, temperature=temperature,
                     schema=schema or planner_schema())


def plan_detailed(question: str, prior: QuerySpec | None = None, *,
                  chat_fn: ChatFn | None = None,
                  temperature: float | None = None) -> PlanResult:
    # Refuse before spending a model call on something the schema cannot answer.
    # NOT gated on `prior is None`. It was, and that meant any out-of-scope
    # question asked mid-conversation skipped the check entirely -- "which
    # transactions are unreconciled?" as a follow-up answered "Count: 0".
    # A follow-up about reconciliation is still about reconciliation.
    if reason := out_of_scope(question):
        return PlanResult(QuerySpec(dataset="transactions", unsupported_reason=reason),
                          confidence="high", attempts=[])

    dr, matched = extract_dates(question)
    attempts: list[str] = []
    used_patch = False

    if looks_like_followup(question, prior):
        used_patch = True
        raw = _call(chat_fn, REFINE_PROMPT % describe_spec(prior), question,
                    temperature, schema=refine_schema())
        attempts.append(json.dumps(raw)[:400])
        try:
            # Legacy patch shape (tests, and any model that ignores the
            # sentinel vocabulary) still merges the old way.
            spec = (apply_refinement(prior, raw) if isinstance(raw, dict)
                    and "dataset" in raw and raw.get("dataset") in
                    ([UNCHANGED] + DATASETS) and "counterparty" in raw
                    else prior.merge_patch(coerce(raw, patch=True) if raw else {}))
        except CoercionError:
            spec = prior            # a bad refinement must not corrupt a good turn

        if (ds := dataset_from_words(question)) and ds != spec.dataset:
            spec = spec.model_copy(update={"dataset": ds})

        # Period-over-period is deterministic: the comparison window is the
        # prior window shifted back by its own span, so the two are always the
        # same length. Asking the model for this only introduced mismatches.
        if COMPARE_RE.search(question) and spec.date_range.kind == "relative":
            base = dr or spec.date_range
            spec = spec.model_copy(update={
                "date_range": base,
                "compare_to": base.model_copy(
                    update={"offset": base.offset - max(base.periods, 1)}),
            })
            dr = None
    else:
        raw = _call(chat_fn, _prompt(), question, temperature)
        attempts.append(json.dumps(raw)[:400])
        try:
            spec = QuerySpec(**coerce(raw))
        except (ValidationError, CoercionError) as e:
            # One repair round-trip with the actual error, then give up honestly.
            raw2 = _call(chat_fn, _prompt(),
                         f"{question}\n\nYour previous reply was invalid:\n{e}\n"
                         f"Reply with corrected JSON only.", temperature)
            attempts.append(json.dumps(raw2)[:400])
            try:
                spec = QuerySpec(**coerce(raw2))
            except (ValidationError, CoercionError):
                return PlanResult(
                    QuerySpec(dataset="transactions",
                              unsupported_reason="I could not turn that into a query I trust. "
                                                 "Could you rephrase it?"),
                    confidence="low", attempts=attempts)

    # Only check a category this turn actually introduced. A follow-up inherits
    # the prior filter and will not re-mention it -- "what about the month
    # before?" says nothing about tax, but tax is still the right filter.
    inherited = (used_patch and prior is not None
                 and spec.filters.category == prior.filters.category)
    if spec.filters.category and not inherited:
        verdict, replacement = category_verdict(question, spec.filters.category)
        if verdict == "fix":
            spec = spec.model_copy(deep=True)
            spec.filters.category = replacement
        elif verdict == "refuse":
            return PlanResult(
                QuerySpec(dataset=spec.dataset, unsupported_reason=(
                    "I do not derive that category from your transactions. I can "
                    f"break spending down by: "
                    f"{', '.join(c.lower().replace('_', ' ') for c in CATEGORIES)}.")),
                confidence="high", attempts=attempts)
        elif verdict == "drop":
            spec = spec.model_copy(deep=True)
            spec.filters.category = None

    if spec.filters.category == "NOT_IN_DATA":
        return PlanResult(
            QuerySpec(dataset=spec.dataset, unsupported_reason=(
                "I do not derive that category from your transactions. I can "
                f"break spending down by: {', '.join(CATEGORIES)}.")),
            confidence="high", attempts=attempts)

    # Grouping by a dimension you have filtered to ONE value is degenerate: it
    # can only ever return a single row, and renders as a one-slice pie chart.
    # "Trends of Priya Sharma" asked for counterparty spending grouped BY
    # counterparty, which answers nothing.
    pinned = {d for d in spec.group_by
              if getattr(spec.filters, d, None) not in (None, [], "")}
    if pinned:
        spec = spec.model_copy(update={
            "group_by": [d for d in spec.group_by if d not in pinned]})

    # A trend question is about time. If nothing meaningful is left to group by,
    # group by month -- that is what "trend" means.
    if wants_trend(question) and not spec.group_by:
        unit = "quarter" if re.search(r"\bquarterly|by quarter\b", question, re.I) else "month"
        spec = spec.model_copy(update={"group_by": [unit]})

    if dr is not None:
        spec = spec.model_copy(update={"date_range": dr})

    return PlanResult(spec, date_source="deterministic" if dr else "default",
                      matched_date_text=matched, attempts=attempts, used_patch=used_patch)


def plan(question: str, prior: QuerySpec | None = None, **kw) -> QuerySpec:
    """Signature the API depends on."""
    return plan_detailed(question, prior, **kw).spec


def _key(spec: QuerySpec) -> str:
    d = spec.model_dump()
    d.pop("limit", None)
    return json.dumps(d, sort_keys=True, default=str)


def plan_with_confidence(question: str, prior: QuerySpec | None = None, *,
                         chat_fn: ChatFn | None = None) -> PlanResult:
    """Self-consistency: sample the plan N times and see whether the model
    agrees with itself. Cheap on a small model, and it is the honest basis for
    the confidence badge -- not a number the model claims about itself."""
    conf_cfg = CFG.get("confidence", {"samples": 3, "temperature": 0.7})
    n, temp = conf_cfg["samples"], conf_cfg["temperature"]

    first = plan_detailed(question, prior, chat_fn=chat_fn, temperature=0.0)
    if first.spec.unsupported_reason:
        return first

    keys = [_key(first.spec)]
    for _ in range(max(n - 1, 0)):
        try:
            keys.append(_key(plan_detailed(question, prior, chat_fn=chat_fn,
                                           temperature=temp).spec))
        except Exception:
            keys.append("__error__")

    agree = keys.count(keys[0])
    first.confidence = "high" if agree == len(keys) else "medium" if agree > len(keys) / 2 else "low"
    return first
