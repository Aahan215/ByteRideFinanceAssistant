# Backlog — ticket-level breakdown

Sizing: **S** ≈ 1h · **M** ≈ 2–4h · **L** ≈ half a day.
Copy this into GitHub Issues (or a Projects board) so blockers are visible.

---

## Stream 1 — Data & semantics

| # | Ticket | Size | Notes |
|---|---|---|---|
| D1 | Load CSVs into DuckDB, assert row counts match source | S | `make load` |
| D2 | **Profile every column** and post findings to team chat | M | **Do this first — it unblocks everyone.** Distinct values of `status` and `category`, date min/max, null rates, currency field |
| D3 | Hand-write `semantic_layer.yaml` from the real data dictionary | M | Especially: what *exactly* counts as unreconciled |
| D4 | Sign conventions + data quality note | S | Are refunds/credits negative? Duplicate txn ids? Judges will ask |
| D5 | Rollup tables (vendor×month, category×month, status×month) | M | Pair with E2 |
| D6 | Vendor name → id lookup + alias table for fuzzy matching | M | Feeds the validator |

## Stream 2 — Deterministic engine

| # | Ticket | Size | Notes |
|---|---|---|---|
| E1 | Refusal + clarification paths wired through `/ask` | M | Guardrails are a *scored* requirement, not polish |
| E2 | Route specs to rollup tables when the grain allows | M | Demo latency |
| E3 | **Comparison queries as a first-class feature** | M | See gap note below |
| E4 | CSV / Excel export endpoint | S | Free "good to have" points |
| E5 | Anomaly z-score flags on returned rows | M | Bonus |
| E6 | Evidence drill-down: pagination + row limits | S | |
| E7 | Unit tests for every date unit and offset | M | Off-by-one on month boundaries is the likeliest silent bug |

> **Known gap:** `QuerySpec` today expresses *one* query. "How does that compare
> to the month before?" needs two results and a delta. Decide early: either add a
> `compare_to: DateRange` field to the spec, or have the API run the spec twice
> and diff. Whoever owns E3 makes the call and tells Stream 3 — it changes the
> planner's prompt.

## Stream 3 — Model & planner

| # | Ticket | Size | Notes |
|---|---|---|---|
| M1 | Ollama on the LAN, `.env` distributed to the team | S | Unblocks everyone else's model testing |
| M2 | `plan()` → valid QuerySpec with few-shot examples | **L** | The core of the project |
| M3 | Retry/repair loop on invalid JSON or schema violation | M | Small models need this; do not skip it |
| M4 | Multi-turn patch mode using `merge_patch()` | M | |
| M5 | `narrate()` + numeric guard integration | M | Regenerate once on guard failure, then fall back to template |
| M6 | Router tier + escalation on low confidence | M | Feeds the efficiency report |
| M7 | Self-consistency confidence (sample 3× at temp 0.7) | M | Bonus |

## Stream 4 — UI

| # | Ticket | Size | Notes |
|---|---|---|---|
| U1 | Chat shell wired to `POST /ask_spec` | M | Start here — no model dependency |
| U2 | Breakdown table rendering | S | |
| U3 | **Collapsible SQL + evidence rows panel** | M | The single most valuable UI element you will build |
| U4 | Refusal / clarification / warning states | M | Must look intentional, not like an error |
| U5 | Confidence badge + anomaly flags | S | |
| U6 | Export button | S | |
| U7 | Anchor-date banner: "data through March 2024" | S | Stops judges thinking dates are broken |

## Stream 5 — QA & story

| # | Ticket | Size | Notes |
|---|---|---|---|
| Q1 | Collect 50 golden questions (10 from each teammate) | M | Day one |
| Q2 | Hand-verify expected answers by writing the SQL yourself | **L** | Tedious, and it is the whole point |
| Q3 | Eval runner → accuracy table, run after every merge | M | `make eval` |
| Q4 | Model comparison: 3B vs 8B vs 20B on the golden set | M | This table *is* your model-efficiency score |
| Q5 | Architecture diagram | S | |
| Q6 | Deck: problem, approach, model rationale, demo flow | M | |
| Q7 | Demo script + two full rehearsals | M | Last 2 hours |

---

## Dependency map

```
D2 (profile) ──┬──> D3 (semantic layer) ──> M2 (planner prompt)
               └──> Q1/Q2 (golden set)
M1 (ollama LAN) ─────────────────────────> M2, and everyone's model testing
E3 decision ─────────────────────────────> M2 prompt design
U1 needs nothing but /ask_spec, which already works
```

Only three things are truly blocking: **D2, M1, and the E3 decision.**
Get all three done in the first three hours.
