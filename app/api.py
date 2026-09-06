"""FastAPI surface. The UI owner codes against THIS, starting hour one."""
from __future__ import annotations
import os
import pathlib
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import anchor_date, run
from app.spec import QuerySpec
from app.compiler import (compile_sql, compile_evidence_sql,
                          compile_null_group_sql, compile_count_sql,
                          compile_anomaly_sql, render_sql)
import duckdb
import pandas as pd

from app.dates import resolve, describe
from app import validator, narrator, anomaly, confidence, scope as scope_mod

app = FastAPI(title="Finance Assistant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: dict[str, QuerySpec] = {}


def _suggest(question: str, spec: QuerySpec, candidates: list[str]) -> list[str]:
    """Turn candidates into questions the user can ask as-is.

    Substituting the ambiguous term back into their own wording beats a bare
    list of names: they click once instead of retyping the whole question.
    """
    if not candidates:
        return []
    term = spec.filters.counterparty
    out = []
    for c in candidates[:5]:
        if term and question and term.lower() in question.lower():
            i = question.lower().index(term.lower())
            out.append(question[:i] + c + question[i + len(term):])
        else:
            out.append(f"{question} — {c}" if question else c)
    return out


def _num(value, default=0.0) -> float:
    """NaN is TRUTHY, so `value or 0` returns NaN and int(NaN) raises.

    An aggregate over zero rows comes back as NaN, which is exactly the case
    that reaches here -- a question whose breakdown excludes nothing.
    """
    import pandas as pd
    return default if value is None or pd.isna(value) else float(value)


def _clean(df) -> list[dict]:
    """pandas turns SQL NULL into NaN, which serialises as the string 'nan' and
    reaches the user as a fake value. Put real nulls back."""
    import pandas as pd
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


class Ask(BaseModel):
    question: str
    session_id: str = "default"
    # Selector, not auth. See app/scope.py.
    scope_level: str = "all"
    scope_value: str | None = None


class Comparison(BaseModel):
    window: str
    value: float | None = None
    previous: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    rows: list[dict] = []          # per-group deltas when the query is grouped


class Answer(BaseModel):
    answer: str
    confidence: str = "high"
    sql: str | None = None
    window: str | None = None
    breakdown: list[dict] = []
    evidence: list[dict] = []
    comparison: Comparison | None = None
    anomalies: list[str] = []          # unusual amounts spotted while answering
    confidence_reasons: list[str] = []  # why the badge says what it says
    warnings: list[str] = []
    refused: bool = False
    # A question back to the user, with concrete options they can click.
    clarification: str | None = None
    suggestions: list[str] = []
    spec: dict | None = None       # what we actually ran -- powers export + "show your working"
    # Model efficiency (BACKLOG M6): which model actually produced this
    # answer's spec, and whether that took a trip to the escalate tier. None
    # only when /ask_spec bypassed the planner entirely.
    model_used: str | None = None
    escalated: bool = False



# `category` is a narration-keyword bucket (TRANSFER, SALARY, EMI_LOAN, CASH...),
# not the "food/rent/utilities" spend categories a plain "break down my
# spending by category" implies. Rather than guess, ask once -- the two
# suggested follow-ups resolve deterministically in app.planner (dataset_from_words
# keeps "payouts", wants_discretionary_only sets the narrower exclude_categories),
# so this never loops.
_ALL_CATEGORIES_RE = re.compile(r"\ball (payout )?categories\b", re.I)
_DISCRETIONARY_ONLY_RE = re.compile(r"\bdiscretionary\b", re.I)


def _needs_category_scope_clarification(spec: QuerySpec, question: str) -> bool:
    if not question or spec.group_by != ["category"] or spec.dataset != "payouts":
        return False
    if spec.filters.category or spec.filters.exclude_categories:
        return False
    return not (_ALL_CATEGORIES_RE.search(question) or _DISCRETIONARY_ONLY_RE.search(question))


def answer_spec(spec: QuerySpec, question: str = "", scope=None) -> Answer:
    """Everything downstream of the planner. Testable with hand-written specs,
    which is why the backend team is not blocked on the model team."""
    if _needs_category_scope_clarification(spec, question):
        return Answer(
            answer="Do you want the full breakdown, including transfers, salary "
                   "payouts and loan EMIs -- or just discretionary spending, like "
                   "food, fuel and shopping?",
            refused=True, confidence="n/a",
            clarification="All categories, or just discretionary spending?",
            suggestions=[
                f"{question} — all categories, including transfers, salary and EMIs",
                f"{question} — just discretionary spending (food, fuel, shopping, etc.)",
            ])

    v = validator.validate(spec)
    if not v.ok:
        return Answer(answer=v.refusal or v.clarification, refused=True, confidence="n/a",
                      clarification=v.clarification,
                      suggestions=_suggest(question, spec, v.candidates))

    spec = v.repaired
    sql, params, meta = compile_sql(spec, anchor_date(), scope=scope)
    df = run(sql, params)
    ev_sql, ev_params = compile_evidence_sql(spec, anchor_date(), scope=scope)
    ev = run(ev_sql, ev_params)

    window = describe(*resolve(spec.date_range, anchor_date()))
    text = narrator.narrate(question, df, spec, window)

    warnings = list(v.warnings)
    excluded_rows = unattributed_rows = 0
    nulls = compile_null_group_sql(spec, anchor_date(), scope=scope)
    if nulls:
        nrow = run(*nulls)
        excluded = _num(nrow.iloc[0]["excluded"])
        nrows = int(_num(nrow.iloc[0]["rows"]))
        unattributed = _num(nrow.iloc[0].get("unattributed"))
        unattributed_rows = int(_num(nrow.iloc[0].get("unattributed_rows")))
        excluded_rows = nrows
        if nrows:
            no_payee_n = nrows - unattributed_rows
            if no_payee_n:
                warnings.append(
                    f"{narrator.inr(excluded - unattributed)} across {no_payee_n:,} "
                    f"transactions has no {spec.group_by[0]} at all (tax, bank "
                    f"charges and cash have no payee), so it is correctly outside "
                    f"a {spec.group_by[0]} breakdown.")
            if unattributed_rows:
                warnings.append(
                    f"{narrator.inr(unattributed)} across {unattributed_rows:,} "
                    f"transactions has a {spec.group_by[0]} we could not extract "
                    f"from the narration, so it is missing from this breakdown.")

    if spec.filters.exclude_categories:
        pretty = ", ".join(c.lower().replace("_", " ")
                           for c in spec.filters.exclude_categories)
        warnings.append(
            f"Showing discretionary spending only. {pretty.capitalize()} are "
            f"commitments rather than choices this month, and investments are "
            f"saving rather than spending, so they are excluded from this "
            f"breakdown. This is what you spent, not a recommendation.")

    comparison = None
    before = len(warnings)
    if spec.compare_to is not None:
        comparison = _compare(spec, df, warnings, scope)
        text = narrator.with_comparison(text, comparison, spec)
    mismatch = any("differ in length" in w for w in warnings[before:])

    # Anomaly callouts, computed on the evidence rows we already fetched, so a
    # callout can only ever name a record the user can see for themselves.
    # No bare `except: pass` here -- a swallowed error looks exactly like
    # "no anomalies found", which hid a broken query through two test rounds.
    flags = []
    try:
        flags = anomaly.from_scan(run(*compile_anomaly_sql(spec, anchor_date(), scope=scope)))
    except duckdb.CatalogException:
        pass                          # stats table not built yet -- fine
    except Exception as e:
        warnings.append(f"Anomaly check unavailable: {type(e).__name__}.")
    # Anomalies are returned as a structured field and rendered as their own
    # callouts. Appending them to the sentence too made the answer three times
    # longer and said the same thing twice.
    #
    # The division of labour: `answer` is ONE headline sentence, and structure
    # lives in the fields built for it -- anomalies, warnings, comparison, the
    # breakdown table, the chart. Prose is a poor container for a list.

    row_count = int(run(*compile_count_sql(spec, anchor_date(), scope=scope)).iloc[0]["n"])
    a = confidence.assess(spec=spec, row_count=row_count, excluded_rows=excluded_rows,
                          unattributed_rows=unattributed_rows,
                          warnings=warnings, comparison_mismatch=mismatch)

    return Answer(answer=text, sql=render_sql(sql, params), window=window,
                  breakdown=_clean(df), evidence=_clean(ev.head(25)),
                  comparison=comparison, warnings=warnings,
                  anomalies=[f.sentence() for f in flags],
                  confidence=a.level, confidence_reasons=a.reasons,
                  spec=spec.model_dump(mode="json"))


def _compare(spec: QuerySpec, df, warnings: list[str], scope=None) -> Comparison:
    """Period-over-period. Runs the SAME spec against a second window and diffs
    the results here -- the model is never asked to subtract two numbers."""
    anchor = anchor_date()
    base_start, base_end = resolve(spec.date_range, anchor)
    cmp_start, cmp_end = resolve(spec.compare_to, anchor)
    prev_window = describe(cmp_start, cmp_end)

    # Comparing a 3-month window against a 1-month window produces a confident,
    # meaningless percentage. Say so rather than reporting it as a change.
    if base_start and base_end and cmp_start and cmp_end:
        base_days = (base_end - base_start).days
        cmp_days = (cmp_end - cmp_start).days
        if base_days and abs(base_days - cmp_days) > 1:
            warnings.append(
                f"Comparison periods differ in length ({base_days} days vs "
                f"{cmp_days} days), so the change is not like-for-like.")

    def _pct(now, before):
        if before in (None, 0) or now is None:
            return None
        return round(100.0 * (now - before) / abs(before), 1)

    if not spec.group_by:
        prev_sql, prev_params, _ = compile_sql(spec, anchor, date_range=spec.compare_to, scope=scope)
        prev = run(prev_sql, prev_params)
        now = float(df.iloc[0, -1]) if len(df) and pd.notna(df.iloc[0, -1]) else None
        was = float(prev.iloc[0, -1]) if len(prev) and pd.notna(prev.iloc[0, -1]) else None
        delta = None if (now is None or was is None) else round(now - was, 2)
        return Comparison(window=prev_window, value=now, previous=was,
                          delta=delta, delta_pct=_pct(now, was))

    key, metric = spec.group_by[0], spec.metric

    # Both sides must be compared UNLIMITED. Diffing two top-N lists reports a
    # vendor as "disappeared" merely because it fell out of this month's top N.
    # `df` is the limited display result, so the current window is re-queried
    # wide here rather than reused.
    wide = spec.model_copy(update={"limit": 10_000})
    now_df = run(*compile_sql(wide, anchor, scope=scope)[:2])
    prev_df = run(*compile_sql(wide, anchor, date_range=spec.compare_to, scope=scope)[:2])
    merged = now_df.merge(prev_df, on=key, how="outer", suffixes=("", "_prev"))

    # A group absent from one window means zero spend there, not unknown --
    # but only for additive metrics. An average over no rows is genuinely
    # unknown, and calling it 0 would be a fabricated number.
    additive = spec.metric in ("sum_amount", "count")

    rows = []
    for _, r in merged.iterrows():
        now = r.get(metric)
        was = r.get(f"{metric}_prev")
        now = (0.0 if additive else None) if pd.isna(now) else float(now)
        was = (0.0 if additive else None) if pd.isna(was) else float(was)
        rows.append({key: r[key], "value": now, "previous": was,
                     "delta": None if (now is None or was is None) else round(now - was, 2),
                     "delta_pct": _pct(now, was)})
    # abs(nan) is nan and nan comparisons are all False, so a NaN delta makes
    # the ordering arbitrary. Treat it as no movement.
    rows.sort(key=lambda x: abs(_num(x["delta"])), reverse=True)
    return Comparison(window=prev_window, rows=rows[:spec.limit])


@app.get("/health")
def health():
    """The anchor date matters to the UI: it is the assistant's "today", so a
    banner can tell the user what "this month" actually resolves to.

    Readiness is checked here, before anchor_date(), rather than left to
    surface as a 500 -- anchor_date() queries txn_enriched, which does not
    exist until load_data.py has run, and a 500 tells the UI nothing it can
    show the user.
    """
    from app.db import anchor_status, etl_status
    etl = etl_status()
    if not etl["ready"]:
        return {"ok": False, "etl_ready": False, "problems": etl["problems"],
                "warning": etl["hint"]}
    return {"ok": True, "etl_ready": True, "anchor_date": str(anchor_date()), **anchor_status()}


ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"


@app.get("/", include_in_schema=False)
def index():
    """Serve the built React app when it exists, else the no-build fallback page.

    The fallback matters: if npm breaks on the demo machine at hour 20, the
    single-file UI still works from a clean clone.
    """
    from fastapi.responses import FileResponse
    built = DIST / "index.html"
    # index.html is NOT content-hashed, so a cached copy keeps pointing at the
    # previous asset filenames and a rebuild appears to change nothing. The
    # assets themselves are hashed and stay cacheable.
    return FileResponse(built if built.exists() else ROOT / "ui" / "index.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


if DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


STUB = os.getenv("FINANCE_STUB_PLANNER") == "1"


@app.post("/ask", response_model=Answer)
def ask(req: Ask):
    from app.llm import ModelUnavailable

    try:
        scope = scope_mod.parse(req.scope_level, req.scope_value)
    except ValueError as e:
        return Answer(answer=str(e), refused=True, confidence="n/a")

    # A scope change starts a new conversation: a follow-up refining the
    # previous user's question would be nonsense, and would carry their filters.
    key = f"{req.session_id}:{scope.level}:{scope.value}"
    prior = SESSIONS.get(key)

    if STUB:
        # Development aid only -- see app/stub_planner.py.
        from app.stub_planner import plan as stub_plan
        spec = stub_plan(req.question, prior)
        out = answer_spec(spec, req.question, scope=scope)
        if not out.refused:
            SESSIONS[key] = spec
        out.confidence = "n/a"
        out.model_used = "stub"
        out.warnings.insert(0, "STUB PLANNER — keyword rules, not the language "
                               "model. Unset FINANCE_STUB_PLANNER before demoing.")
        return out

    from app.planner import plan_with_confidence
    try:
        result = plan_with_confidence(req.question, prior)
    except ModelUnavailable as e:
        return Answer(answer=str(e), refused=True, confidence="n/a")

    out = answer_spec(result.spec, req.question, scope=scope)
    out.model_used = result.model_used
    out.escalated = result.escalated

    # Only a turn we could actually answer becomes context for the next one.
    # Storing a refusal means the follow-up ("how does that compare?") refines
    # the thing we just declined to answer, instead of the last real result.
    if not out.refused:
        SESSIONS[key] = result.spec

    if not out.refused:
        # Fold the model's self-consistency into the deterministic assessment
        # rather than replacing it -- both signals matter.
        a = confidence.assess(spec=result.spec, warnings=out.warnings,
                              planner_confidence=result.confidence)
        order = {"n/a": -1, "high": 0, "medium": 1, "low": 2}
        # "n/a" means the query matched nothing -- there is no answer to be
        # confident about. It must never be upgraded to "high" just because the
        # model was self-consistent about producing an empty result.
        if out.confidence != "n/a" and order[a.level] > order[out.confidence]:
            out.confidence = a.level
        out.confidence_reasons = list(dict.fromkeys(out.confidence_reasons + a.reasons))
        if result.matched_date_text:
            out.warnings.append(
                f'Read "{result.matched_date_text}" as {out.window}.')
    return out


@app.post("/export")
def export(spec: QuerySpec, fmt: str = "csv", scope_level: str = "all",
           scope_value: str | None = None):
    """The breakdown as a file. 'Good to have' in the problem statement, and
    one of the cheapest points on the board."""
    from fastapi.responses import StreamingResponse
    import io

    v = validator.validate(spec)
    if not v.ok:
        return {"error": v.refusal or v.clarification}
    sql, params, _ = compile_sql(v.repaired, anchor_date(),
                                 scope=scope_mod.parse(scope_level, scope_value))
    df = run(sql, params)

    buf = io.BytesIO()
    if fmt == "xlsx":
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="breakdown")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        buf.write(df.to_csv(index=False).encode())
        media = "text/csv"
    buf.seek(0)
    name = f"{spec.dataset}_{spec.metric}.{ 'xlsx' if fmt == 'xlsx' else 'csv' }"
    return StreamingResponse(buf, media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/boundary")
def boundary_report():
    """Audit trail for the data/model boundary: what has been sent to the LLM.

    Worth showing in the demo -- it is the difference between claiming the model
    never sees your data and being able to prove it.
    """
    from app import boundary
    return boundary.report()


@app.get("/efficiency")
def efficiency():
    """Which model answered what, and how often we escalated. Worth 20%."""
    from app.llm import efficiency_report
    return efficiency_report()


@app.post("/ask_spec", response_model=Answer)
def ask_spec(spec: QuerySpec, scope_level: str = "all", scope_value: str | None = None):
    """Bypasses the LLM entirely. Lets the UI and eval work start on day one."""
    return answer_spec(spec, scope=scope_mod.parse(scope_level, scope_value))


@app.get("/scopes")
def scopes():
    """What the selector offers: all accounts, each entity, each account."""
    return scope_mod.available()
