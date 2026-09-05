# Backlog

Sizing: **S** ≈ 1h · **M** ≈ 2–4h · **L** ≈ half a day.
Copy into GitHub Issues so blockers are visible.

---

## Already done (on `main`)

| Area | State |
|---|---|
| DuckDB loader, 3-table schema, rollups | working, `make load` |
| Sample seed (10 rows/table) | working — team is unblocked before the export lands |
| Counterparty parser (UPI/IMPS/NEFT/FT/…) | working, 6 narration formats |
| Spend-category classifier incl. TAX | working, word-bounded |
| Semantic layer, QuerySpec, SQL compiler | working, parameterised, allow-listed |
| Sensitive-column masking (in SQL) | working |
| Validator: refuse / clarify / closed-vs-open vocab | working |
| Anchor-date resolution | working |
| `POST /ask_spec` — full pipeline, no model | working |
| AES-256 module + crypto probe | written, needs the real export |
| Model shim, committed model config, drift check | working |
| 17 tests | passing |

**Not started: the planner, the narrator's LLM path, the UI, the golden set.**

---

## Stream 1 — Data & crypto

| # | Ticket | Size | Notes |
|---|---|---|---|
| D1 | `make crypto-probe` on the real export, post output to chat | S | **Blocks the crypto design. Do first.** |
| D2 | Profile every column; post distinct values, null rates, date range | M | **Unblocks everyone.** |
| D3 | Wire decryption / tokenisation into the loader per D1's finding | M | ETL only — never at query time |
| D4 | Tune the TAX rules against the real corpus | M | A whole question depends on it; sample has zero tax rows |
| D5 | Vendor name noise — build a place list, stop `X` and `X DAHISAR EAST` splitting | M | Silently corrupts "where did I spend most" |
| D6 | Report UNCATEGORISED % and parse coverage | S | Goes in the deck |
| D7 | Negative `available_balance` — ask the organisers | S | |

## Stream 2 — Engine

| # | Ticket | Size | Notes |
|---|---|---|---|
| E1 | Implement `compare_to` in the API (run twice, diff) | M | Field exists in the spec; API ignores it |
| E2 | Entity scope enforced on every query | S | "my spends" needs an owner |
| E3 | Route to `rollup_counterparty_month` when the grain allows | M | Demo latency |
| E4 | CSV / Excel export endpoint | S | Free "good to have" points |
| E5 | Anomaly z-score flags | M | Bonus |
| E6 | Tests for every date unit × offset × periods | M | Month-boundary off-by-one is the likeliest silent bug |

## Stream 3 — Model

| # | Ticket | Size | Notes |
|---|---|---|---|
| M1 | `make model-build` + `model-lock`, share endpoint | S | **Unblocks everyone's model testing** |
| M2 | `plan()` → valid QuerySpec, few-shot prompts | **L** | The core of the project |
| M3 | Retry/repair on invalid JSON or schema violation | M | Small models need this |
| M4 | Multi-turn patch mode via `merge_patch()` | M | |
| M5 | `narrate()` + numeric guard wired in | M | Regenerate once, then fall back to template |
| M6 | Router tier + escalation | M | Feeds the efficiency report |
| M7 | Self-consistency confidence | M | Bonus |

## Stream 4 — UI

| # | Ticket | Size | Notes |
|---|---|---|---|
| U1 | Chat shell on `POST /ask_spec` | M | **Start here — zero model dependency** |
| U2 | Breakdown table | S | |
| U3 | Collapsible SQL + masked evidence rows | M | Highest-value element you will build |
| U4 | Refusal / clarification / warning states | M | Must look intentional, not like an error |
| U5 | Confidence badge + anomaly flags | S | |
| U6 | Export button | S | |
| U7 | Anchor-date banner: "data through 24 Jun 2026" | S | Stops judges thinking dates are broken |

## Stream 5 — QA & story

| # | Ticket | Size | Notes |
|---|---|---|---|
| Q1 | 50 golden questions (10 per person) | M | **Day one, no dependencies** |
| Q2 | Hand-verify expected answers by writing the SQL yourself | **L** | Tedious; it is the whole point |
| Q3 | Eval runner after every merge | M | `make eval` |
| Q4 | Model comparison: 0.6B vs 8B vs 20B on the golden set | M | **This table is your model-efficiency score** |
| Q5 | Architecture diagram | S | |
| Q6 | Deck: problem, approach, model rationale, demo | M | |
| Q7 | Demo script + two rehearsals | M | Last 2 hours |

---

## Critical path

```
D1 crypto-probe ─┐
D2 column profile ├─> D3 loader wiring ─> everything touching real data
M1 model server ──┴─> M2 planner ─> M5 narrator ─> end-to-end /ask
Q1 golden set ────────────────────> Q3 eval runner ─> Q4 model comparison
U1 chat UI ── depends on nothing (uses /ask_spec)
```

Only **D1, D2, M1 and Q1** are truly blocking. All four are doable in the first
three hours and none depend on each other.
