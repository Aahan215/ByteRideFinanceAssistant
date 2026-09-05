"""FastAPI surface. The UI owner codes against THIS, starting hour one."""
from __future__ import annotations
import os
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import anchor_date, run
from app.spec import QuerySpec
from app.compiler import compile_sql, compile_evidence_sql, compile_null_group_sql
import pandas as pd

from app.dates import resolve, describe
from app import validator, narrator

app = FastAPI(title="Finance Assistant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: dict[str, QuerySpec] = {}


def _clean(df) -> list[dict]:
    """pandas turns SQL NULL into NaN, which serialises as the string 'nan' and
    reaches the user as a fake value. Put real nulls back."""
    import pandas as pd
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


class Ask(BaseModel):
    question: str
    session_id: str = "default"


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
    warnings: list[str] = []
    refused: bool = False
    spec: dict | None = None       # what we actually ran -- powers export + "show your working"


def answer_spec(spec: QuerySpec, question: str = "") -> Answer:
    """Everything downstream of the planner. Testable with hand-written specs,
    which is why the backend team is not blocked on the model team."""
    v = validator.validate(spec)
    if not v.ok:
        return Answer(answer=v.refusal or v.clarification, refused=True, confidence="n/a")

    spec = v.repaired
    sql, params, meta = compile_sql(spec, anchor_date())
    df = run(sql, params)
    ev_sql, ev_params = compile_evidence_sql(spec, anchor_date())
    ev = run(ev_sql, ev_params)

    window = describe(*resolve(spec.date_range, anchor_date()))
    text = narrator.narrate(question, df, spec, window)

    warnings = list(v.warnings)
    nulls = compile_null_group_sql(spec, anchor_date())
    if nulls:
        nrow = run(*nulls)
        excluded, nrows = nrow.iloc[0]["excluded"], int(nrow.iloc[0]["rows"])
        if nrows:
            warnings.append(
                f"{excluded:,.2f} across {nrows:,} transactions has no "
                f"{spec.group_by[0]} we could identify (tax, bank charges and "
                f"cash have no payee) and is not in this breakdown.")

    comparison = None
    if spec.compare_to is not None:
        comparison = _compare(spec, df, warnings)
        text = narrator.with_comparison(text, comparison, spec)

    return Answer(answer=text, sql=sql, window=window,
                  breakdown=_clean(df), evidence=_clean(ev.head(25)),
                  comparison=comparison, warnings=warnings,
                  spec=spec.model_dump(mode="json"))


def _compare(spec: QuerySpec, df, warnings: list[str]) -> Comparison:
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
        prev_sql, prev_params, _ = compile_sql(spec, anchor, date_range=spec.compare_to)
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
    now_df = run(*compile_sql(wide, anchor)[:2])
    prev_df = run(*compile_sql(wide, anchor, date_range=spec.compare_to)[:2])
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
    rows.sort(key=lambda x: abs(x["delta"] or 0), reverse=True)
    return Comparison(window=prev_window, rows=rows[:spec.limit])


@app.get("/health")
def health():
    """The anchor date matters to the UI: it is the assistant's "today", so a
    banner can tell the user what "this month" actually resolves to."""
    return {"ok": True, "anchor_date": str(anchor_date())}


@app.get("/", include_in_schema=False)
def index():
    from fastapi.responses import FileResponse
    return FileResponse(pathlib.Path(__file__).resolve().parent.parent / "ui" / "index.html")


STUB = os.getenv("FINANCE_STUB_PLANNER") == "1"


@app.post("/ask", response_model=Answer)
def ask(req: Ask):
    from app.llm import ModelUnavailable

    prior = SESSIONS.get(req.session_id)

    if STUB:
        # Development aid only -- see app/stub_planner.py.
        from app.stub_planner import plan as stub_plan
        spec = stub_plan(req.question, prior)
        SESSIONS[req.session_id] = spec
        out = answer_spec(spec, req.question)
        out.confidence = "n/a"
        out.warnings.insert(0, "STUB PLANNER — keyword rules, not the language "
                               "model. Unset FINANCE_STUB_PLANNER before demoing.")
        return out

    from app.planner import plan_with_confidence
    try:
        result = plan_with_confidence(req.question, prior)
    except ModelUnavailable as e:
        return Answer(answer=str(e), refused=True, confidence="n/a")

    SESSIONS[req.session_id] = result.spec
    out = answer_spec(result.spec, req.question)
    if not out.refused:
        out.confidence = result.confidence
        if result.matched_date_text:
            out.warnings.append(
                f'Read "{result.matched_date_text}" as {out.window}.')
    return out


@app.post("/export")
def export(spec: QuerySpec, fmt: str = "csv"):
    """The breakdown as a file. 'Good to have' in the problem statement, and
    one of the cheapest points on the board."""
    from fastapi.responses import StreamingResponse
    import io

    v = validator.validate(spec)
    if not v.ok:
        return {"error": v.refusal or v.clarification}
    sql, params, _ = compile_sql(v.repaired, anchor_date())
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


@app.get("/efficiency")
def efficiency():
    """Which model answered what, and how often we escalated. Worth 20%."""
    from app.llm import efficiency_report
    return efficiency_report()


@app.post("/ask_spec", response_model=Answer)
def ask_spec(spec: QuerySpec):
    """Bypasses the LLM entirely. Lets the UI and eval work start on day one."""
    return answer_spec(spec)
