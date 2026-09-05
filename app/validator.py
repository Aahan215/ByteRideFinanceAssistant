"""Reject or clarify BEFORE touching the database.

This module is where 'hallucination guardrails' actually live. If the spec
references a vendor/category/status that does not exist, we never run a query
that would return 0 and get narrated as "you spent nothing".
"""
from __future__ import annotations
from difflib import get_close_matches
from dataclasses import dataclass, field
from app.db import SEMANTIC, run
from app.spec import QuerySpec


@dataclass
class Verdict:
    ok: bool
    refusal: str | None = None
    clarification: str | None = None
    # The actual options, so the UI can offer them instead of making the user
    # retype. A clarification without choices is just a refusal with extra words.
    candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repaired: QuerySpec | None = None


def _known_values(dim: str) -> list[str]:
    """Distinct values straight from the enriched view -- so a filter is only
    accepted if the data actually contains it."""
    col = SEMANTIC["dimensions"][dim]["column"]
    view = SEMANTIC["base_view"]
    rows = run(f"SELECT DISTINCT {col} FROM {view} WHERE {col} IS NOT NULL")
    return [r[0] for r in rows.values]


def _family(names: list[str]) -> list[str] | None:
    """True when every candidate is the shortest one plus extra words -- i.e.
    one merchant recorded with branch/location suffixes, not several merchants.
    """
    from app.enrich import normalise
    if len(names) < 2:
        return None
    norm = {n: normalise(n) for n in names}
    shortest = min(norm.values(), key=len)

    # Same merchant plus extra words: "X" and "X ANDHERI WEST".
    base = shortest.split()
    if all(v.split()[:len(base)] == base for v in norm.values()):
        return sorted(names)

    # Same merchant, one name TRUNCATED: "ZOMATO H" and "ZOMATO HYPERPURE".
    # Real narrations get cut by field-length limits, and treating the stub as a
    # separate merchant made every lookup for that vendor ambiguous.
    if len(shortest) >= 6 and all(v.startswith(shortest) for v in norm.values()):
        return sorted(names)
    return None


def resolve_counterparty(value: str, known: list[str]
                         ) -> tuple[str | list[str] | None, list[str], str]:
    """Resolve what the user typed to a vendor that exists in the data.

    People say "Zomato", not "ZOMATO HYPERPURE", and the parsed names carry
    branch suffixes ("SELECTION ELECTRONICS DAHISAR EAST"). Four passes, most
    confident first. Returns (resolved, candidates, how).
    """
    from app.enrich import normalise
    v = normalise(value)
    if not v:
        return None, [], "empty"

    index = {normalise(k): k for k in known}

    # 1. exact, on the normalised key -- but an exact match on a SHORT name
    #    that several longer names extend is not decisive. "RAJESH" exists (a
    #    truncated narration) and is also the start of RAJESH AGARWAL, RAJESH
    #    BHATT, RAJESH CHATTERJEE. Someone asking for "Rajesh" almost certainly
    #    means one of those, so ask rather than silently pick the stub.
    if v in index:
        toks = v.split()
        ext = [orig for norm, orig in index.items()
               if norm != v and norm.split()[:len(toks)] == toks]
        next_words = {n.split()[len(toks)] for n in index
                      if n != v and n.split()[:len(toks)] == toks}
        if len(ext) > 1 and len(next_words) > 1:
            # Divergent extensions. Whether that means DIFFERENT ENTITIES or
            # BRANCHES OF ONE depends on the base:
            #   "RAJESH"                  + AGARWAL / BHATT   -> different people, ask
            #   "DMART AVENUE SUPERMARTS" + ANDHERI / DAHISAR -> branches, sum them
            # A lone first name plus a surname is a new person; a full multi-word
            # business name plus a suffix is a location. Asking "which DMart?" is
            # pedantry, and it was refusing the exact canonical name.
            if len(toks) == 1:
                return None, sorted([index[v]] + ext)[:5], "ambiguous"
            return sorted([index[v]] + ext), [], "family"
        return index[v], [], "exact"

    # 2. every word the user gave appears in the vendor name. This is the case
    #    that matters most: short names and missing branch suffixes.
    words = set(v.split())
    subset = [orig for norm, orig in index.items() if words <= set(norm.split())]
    if len(subset) == 1:
        return subset[0], [], "all-words"
    if len(subset) > 1:
        fam = _family(subset)
        if fam:
            # "ZOMATO HYPERPURE" and "ZOMATO HYPERPURE ANDHERI WEST" are the
            # same merchant with branch noise on the narration. Summing across
            # them is the answer the user wanted; asking which branch they meant
            # is pedantry, and refusing is wrong.
            return fam, [], "family"
        return None, sorted(subset)[:5], "ambiguous"

    # 3. a vendor name contained in what the user typed, or vice versa
    contains = [orig for norm, orig in index.items() if v in norm or norm in v]
    if len(contains) == 1:
        return contains[0], [], "substring"
    if len(contains) > 1:
        return None, sorted(contains)[:5], "ambiguous"

    # 4. fuzzy, case-insensitive because index keys are already normalised
    near = get_close_matches(v, list(index), n=3, cutoff=0.72)
    if len(near) == 1:
        return index[near[0]], [], "fuzzy"
    if near:
        return None, [index[n] for n in near], "ambiguous"
    return None, [], "unknown"


def _banks() -> list[tuple[str, str]]:
    """(code, name) pairs. Ten rows; the cost is nil."""
    try:
        return [(str(c), str(n)) for c, n in run("SELECT bank_code, bank_name FROM bank").values]
    except Exception:
        return []


def resolve_bank(value: str) -> tuple[str | None, list[str], str]:
    """Resolve what the user typed to a bank that exists. Returns (name, candidates, how).

    People say "SBI", "SBIN", "State Bank", "state bank of india", "Kotak" -- an
    abbreviation, the IFSC code, a prefix of the name, or the name in any case.
    The old path compared the raw string against upper-cased names with a
    case-sensitive fuzzy match, so ALL of those were refused while 273,528 SBI
    transactions sat in the table.
    """
    banks = _banks()
    v = " ".join(str(value).upper().split())
    if not v or not banks:
        return None, [], "unknown"
    v_alnum = "".join(ch for ch in v if ch.isalnum())

    # 1. exact on name or code, case-insensitive
    for code, name in banks:
        if v == name.upper() or v == code.upper():
            return name, [], "exact"
    # 2. abbreviation <-> code prefix either way: SBI ~ SBIN, ICICI ~ ICIC
    hits = [name for code, name in banks
            if code.upper().startswith(v_alnum) or v_alnum.startswith(code.upper())]
    if len(hits) == 1:
        return hits[0], [], "code-prefix"
    # 3. every word the user gave appears in the bank name: "state bank", "kotak"
    words = set(v.replace("BANK", " ").split()) - {"THE", "OF", "LTD", "LIMITED", ""}
    if words:
        hits = [name for _, name in banks if words <= set(name.upper().split())]
        if len(hits) == 1:
            return hits[0], [], "all-words"
        if len(hits) > 1:
            return None, sorted(hits), "ambiguous"
    # 4. the name starts with what they typed
    hits = [name for _, name in banks if name.upper().startswith(v)]
    if len(hits) == 1:
        return hits[0], [], "name-prefix"
    # 5. fuzzy, on upper-cased names so case is never the reason for a miss
    near = get_close_matches(v, [n.upper() for _, n in banks], n=3, cutoff=0.7)
    if len(near) == 1:
        return next(n for _, n in banks if n.upper() == near[0]), [], "fuzzy"
    if near:
        return None, [next(n for _, n in banks if n.upper() == m) for m in near], "ambiguous"
    return None, [], "unknown"


def validate(spec: QuerySpec) -> Verdict:
    if spec.unsupported_reason:
        return Verdict(False, refusal=spec.unsupported_reason)

    warnings, repaired = [], spec.model_copy(deep=True)

    # Closed vocabularies vs open ones behave differently, and conflating them
    # is a real bug: "total tax paid" when the data holds no tax rows should
    # answer "none", not refuse -- TAX is a valid category that happens to be
    # empty. A misspelled VENDOR, by contrast, means we misunderstood, so refuse.
    for dim in ("category", "transaction_type"):
        value = getattr(spec.filters, dim)
        if value is None:
            continue
        if dim == "category":
            # UNCATEGORISED is our own bucket for narrations we could not
            # classify. Accepting it as a filter turns "how much on groceries?"
            # into a confident total for something we never tracked.
            allowed = [c for c in SEMANTIC.get("spend_categories", [])
                       if c != "UNCATEGORISED"]
        else:
            allowed = ["credit", "debit"]
        if str(value).upper() not in [str(a).upper() for a in allowed]:
            near = get_close_matches(str(value).upper(), [str(a) for a in allowed], n=3, cutoff=0.6)
            return Verdict(False, refusal=f"'{value}' is not a {dim} I track."
                           + (f" Did you mean {', '.join(near)}?" if near else ""))
        setattr(repaired.filters, dim, str(value).upper() if dim == "category" else value)

    value = spec.filters.counterparty
    if value is not None:
        known = _known_values("counterparty")
        resolved, candidates, how = resolve_counterparty(str(value), known)
        if resolved is None:
            if candidates:
                return Verdict(False, clarification=(
                    f"I have several vendors matching '{value}'. Which did you mean?"),
                    candidates=candidates)
            return Verdict(False, refusal=
                           f"I have no vendor matching '{value}' in this dataset.")
        repaired.filters.counterparty = resolved
        if how == "family":
            names = ", ".join(resolved)
            warnings.append(f"'{value}' matched {len(resolved)} vendor names that "
                            f"look like the same merchant, and all are included: {names}.")
        elif how != "exact":
            warnings.append(f"Interpreted vendor '{value}' as '{resolved}'.")

    # A reference number is an alphanumeric code. The model put the word
    # "unreconciled" here, the lookup matched nothing, and "Count: 0" read as
    # "you have zero unreconciled transactions" -- a confident wrong answer.
    ref = spec.filters.reference_id
    if ref is not None and not any(ch.isdigit() for ch in str(ref)):
        return Verdict(False, refusal=(
            f"'{ref}' does not look like a transaction reference. Reference "
            f"numbers are codes such as S69244711 or HDFCH01078329532."))

    # Bank: the model may put "SBI" in bank_name or "SBIN" in bank_code.
    # Resolve whichever it set, over both name and code, into a canonical name.
    bank_in = spec.filters.bank_name or spec.filters.bank_code
    if bank_in is not None:
        name, candidates, how = resolve_bank(str(bank_in))
        if name is None:
            if candidates:
                return Verdict(False, clarification=(
                    f"I have several banks matching '{bank_in}'. Which did you mean?"),
                    candidates=candidates)
            return Verdict(False, refusal=f"I have no bank matching '{bank_in}' in this dataset.")
        repaired.filters.bank_name = name
        repaired.filters.bank_code = None
        if how != "exact":
            warnings.append(f"Interpreted bank '{bank_in}' as '{name}'.")

    for dim in ("channel",):
        value = getattr(spec.filters, dim)
        if value is None:
            continue
        known = [str(k) for k in _known_values(dim)]
        if str(value) in known:
            continue
        near = get_close_matches(str(value), known, n=3, cutoff=0.7)
        if len(near) == 1:
            setattr(repaired.filters, dim, near[0])
            warnings.append(f"Interpreted {dim} '{value}' as '{near[0]}'.")
        elif near:
            return Verdict(False, clarification=f"Did you mean one of these?",
                           candidates=near)
        else:
            return Verdict(False, refusal=f"I have no {dim} matching '{value}' in this dataset.")

    return Verdict(True, warnings=warnings, repaired=repaired)


NUMBER_RE = r"-?[\d,]+(?:\.\d+)?"


def numeric_guard(answer: str, result_df) -> list[str]:
    """Every number the model wrote must exist in the result set.
    Cheap, deterministic, and the best 20 seconds of your demo."""
    import re
    allowed = set()
    for col in result_df.columns:
        for v in result_df[col].tolist():
            if isinstance(v, (int, float)):
                allowed |= {f"{v:.2f}", f"{round(v):d}", str(v)}
    bad = []
    for tok in re.findall(NUMBER_RE, answer):
        clean = tok.replace(",", "")
        try:
            f = float(clean)
        except ValueError:
            continue
        if f"{f:.2f}" not in allowed and f"{round(f):d}" not in allowed:
            bad.append(tok)
    return bad
