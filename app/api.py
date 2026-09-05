"""FastAPI surface. The UI owner codes against THIS, starting hour one."""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import anchor_date, run
from app.spec import QuerySpec
from app.compiler import compile_sql, compile_evidence_sql, compile_null_group_sql
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


class Answer(BaseModel):
    answer: str
    confidence: str = "high"
    sql: str | None = None
    window: str | None = None
    breakdown: list[dict] = []
    evidence: list[dict] = []
    warnings: list[str] = []
    refused: bool = False


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

    return Answer(answer=text, sql=sql, window=window,
                  breakdown=_clean(df), evidence=_clean(ev.head(25)),
                  warnings=warnings)


@app.get("/health")
def health():
    return {"ok": True, "anchor_date": str(anchor_date())}


@app.post("/ask", response_model=Answer)
def ask(req: Ask):
    from app.planner import plan_with_confidence
    from app.llm import ModelUnavailable

    prior = SESSIONS.get(req.session_id)
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


@app.get("/efficiency")
def efficiency():
    """Which model answered what, and how often we escalated. Worth 20%."""
    from app.llm import efficiency_report
    return efficiency_report()


@app.post("/ask_spec", response_model=Answer)
def ask_spec(spec: QuerySpec):
    """Bypasses the LLM entirely. Lets the UI and eval work start on day one."""
    return answer_spec(spec)
