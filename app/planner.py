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
CATEGORIES = SEMANTIC["spend_categories"]

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


class CoercionError(ValueError):
    """The reply could not be mapped onto the schema with confidence.

    Deliberately NOT forgiving. Silently defaulting an unrecognised dataset to
    "payouts" would turn an incoherent reply into a confident wrong answer --
    the precise failure this system exists to prevent. Raising sends it to the
    repair loop, and a second failure becomes an honest refusal.
    """


def _prompt() -> str:
    return f"""You convert a personal-finance question into a QuerySpec JSON object.

You NEVER compute numbers. You NEVER invent vendor names, categories or dates.
Reply with a JSON object and nothing else.

Fields:
  dataset   one of {DATASETS}
            payouts = money going out (spend). receipts = money coming in.
            transactions = both.
  metric    one of {METRICS}
  group_by  list of {DIMENSIONS}   (use [] when the question wants one number)
  filters   object; include ONLY keys the question actually mentions:
              counterparty  a vendor/merchant name, exactly as the user wrote it
              category      one of {CATEGORIES}
              channel       UPI IMPS NEFT RTGS FT CHEQUE
              transaction_type  "credit" or "debit"
              bank_name, account_id, entity_id, reference_id
              min_amount, max_amount   numbers
  limit     integer, default 50
  unsupported_reason   a short sentence, ONLY when the question cannot be
                       answered from the fields above. Then omit everything else.

Do NOT emit date_range. Dates are handled outside the model.

Tax, fees and charges are CATEGORIES, not vendors.
"Where did I spend the most" means group_by ["counterparty"] on payouts.
If the question asks about budgets, forecasts, reconciliation, or anything not
in the fields above, set unsupported_reason.

Examples:

Q: Where did I spend the most this month?
{{"dataset":"payouts","metric":"sum_amount","group_by":["counterparty"],"filters":{{}},"limit":10}}

Q: Total tax I paid in the last 3 months
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{"category":"TAX"}}}}

Q: How many UPI payments did I make?
{{"dataset":"payouts","metric":"count","group_by":[],"filters":{{"channel":"UPI"}}}}

Q: What did I pay Reliance Digital?
{{"dataset":"payouts","metric":"sum_amount","group_by":[],"filters":{{"counterparty":"Reliance Digital"}}}}

Q: Break my spending down by category
{{"dataset":"payouts","metric":"sum_amount","group_by":["category"],"filters":{{}}}}

Q: What is my credit score?
{{"unsupported_reason":"I only have transaction data for your accounts; I have no credit score information."}}
"""


PATCH_PROMPT = """The user is following up on a previous question. Reply with a
JSON object containing ONLY the fields that CHANGE. Omit everything that stays
the same. Reply {} if nothing changes except the dates.

Previous QuerySpec:
%s

Follow-up: %s
"""

FOLLOWUP_HINTS = ("what about", "how about", "and what", "compare", "vs ",
                  "versus", "same for", "that", "those", "it ", "instead",
                  "break that", "drill")


def looks_like_followup(question: str, prior: QuerySpec | None) -> bool:
    if prior is None:
        return False
    q = question.lower().strip()
    return any(h in q for h in FOLLOWUP_HINTS) or len(q.split()) <= 5


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
        if k == "category":
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
        elif k == "program_id":
            try:
                v = int(v)
            except (ValueError, TypeError):
                continue
        if k in known_filter_keys:
            clean[k] = v
    if clean or not patch:
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


def _call(chat_fn: ChatFn | None, system: str, user: str, temperature: float | None) -> dict:
    fn = chat_fn or chat_json
    return fn("planner", system, user, temperature=temperature)


def plan_detailed(question: str, prior: QuerySpec | None = None, *,
                  chat_fn: ChatFn | None = None,
                  temperature: float | None = None) -> PlanResult:
    dr, matched = extract_dates(question)
    attempts: list[str] = []
    used_patch = False

    if looks_like_followup(question, prior):
        used_patch = True
        raw = _call(chat_fn, PATCH_PROMPT % (prior.model_dump_json(), question),
                    question, temperature)
        attempts.append(json.dumps(raw)[:400])
        try:
            spec = prior.merge_patch(coerce(raw, patch=True) if raw else {})
        except CoercionError:
            # a bad patch must not corrupt a good prior turn
            spec = prior
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
