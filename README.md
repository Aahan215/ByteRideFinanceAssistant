# Finance Assistant — BVP Tech Catalyst Hackathon

Natural-language questions over a financial ledger. Every answer is computed by
SQL against real records; the model translates intent and narrates results, and
never produces a number itself.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/load_data.py  # falls back to data/sample/seed.sql until the
                             # organisers' CSVs land in data/raw/
python scripts/schema_check.py   # verify the load matches the data dictionary
cd frontend && npm install && npm run build && cd ..
uvicorn app.api:app --reload      # UI at http://localhost:8000
```

No model yet? Develop the UI against keyword rules instead:

```bash
FINANCE_STUB_PLANNER=1 uvicorn app.api:app --reload
```

Every response is then tagged STUB PLANNER on screen. Unset it before demoing.

`GET /health` returns the **anchor date** — the assistant's "today", taken from
the max date in the data rather than the wall clock.

## Model

`config/models.yaml` is the single source of truth for which model runs and how
it behaves; `.env` holds only the endpoint and key. Switch providers by changing
`provider:` — no code changes anywhere else.

| provider | endpoint | uses |
|---|---|---|
| `gemini` | Google AI Studio, OpenAI-compatible | `base` (current) |
| `ollama` | your shared local server | `derived` (params baked into a Modelfile) |
| `hosted` | any other OpenAI-compatible API | `base` |

```bash
echo "GEMINI_API_KEY=..." >> .env      # https://aistudio.google.com/apikey
make model-check
```

**On the ≤20B rule:** Google publishes no parameter count for Gemini, so that
claim cannot be demonstrated. Gemma is served from the *same endpoint with the
same key* and does publish its sizes — setting every role's `base` to
`gemma-3-4b-it` makes the cap provable with no other change.

## Local vs production scale

Develop against a small local set; the pipeline is built to run at production
volume unchanged.

```bash
make data-local     # 200k rows, regenerates in ~1s
make data-prod      # 20M rows, parquet
make bench          # measured query latency at whatever is loaded
```

Measured on 2M rows (M-series laptop, DuckDB):

| query | p50 |
|---|---|
| spend by vendor, one month | 34 ms |
| total tax, 3 months | 13 ms |
| category breakdown, full table | 45 ms |
| drill-down evidence, 200 rows | 18 ms |
| spend by vendor, via rollup | **2.7 ms** |

Load is one-time and chunked: 2M rows in ~28s end to end (generate, parse,
join, roll up), so 20M is roughly 5 minutes. Narration parsing runs at ~95k
rows/sec single-threaded and is the bulk of it.

Nothing here scans a table at answer time that a rollup could serve, and the
enrichment never holds more than one chunk in memory — the first thing that
breaks when local row counts become production row counts.

## Who the assistant answers for

No auth system (out of scope per the brief), but a selector: **all accounts**,
one **entity** (a customer, which may own several accounts), or a single
**account**. Every query is constrained to the choice.

The scope is applied in `_where()` in the compiler — the one function all five
query builders go through — so no path can forget it. It is deliberately **not**
part of `QuerySpec`: the model cannot see it, set it, or widen it. An unknown
scope is rejected rather than falling back to `all`, since a silent widening
would show one user everyone else's data.

`GET /scopes` lists the options; `/ask`, `/ask_spec` and `/export` all take
`scope_level` and `scope_value`.

## Architecture

```
question → planner (small LLM) → QuerySpec → validator → compiler → DuckDB
                                                  ↓            ↓
                                          refuse/clarify   result + evidence rows
                                                               ↓
                                                    narrator (small LLM)
                                                               ↓
                                                        numeric guard
```

The LLM appears exactly twice, and touches no arithmetic in either place.

## The contract

`app/spec.py` — `QuerySpec` — is the interface between the model half and the
data half of the system. Both sides can be built and tested independently.
`POST /ask_spec` runs the whole pipeline from a hand-written spec with no model
in the loop.

`schema/semantic_layer.yaml` is the only file that changes when the schema does.
The real schema is in `schema/DATA_DICTIONARY.md`; open judgement calls it does
not settle are tracked in `DECISIONS.md`.

## What the data does and does not contain

Three tables: `bank` -> `account` -> `transaction`. There is **no vendor table,
no category, no chart of accounts, and no reconciliation status column.**

- **Counterparty** is parsed out of the free-text narration at load time by
  `app/enrich.py`, into a real column. The model never parses text at query time.
- **"Vendor payouts"** means debit transactions; **receipts** means credits.
- **Reconciliation state** is a definition we chose, not a field we read. See
  `DECISIONS.md` #1.
- `account_number` and `utr_number` are masked in SQL before results leave the
  database.

## Status

| Module | State |
|---|---|
| `db.py` `dates.py` `compiler.py` `validator.py` | deterministic core, testable now |
| `api.py` | live, `/ask_spec` works without a model |
| `planner.py` `narrator.py` | stubs — model integration pending |
| `ui/` | empty |
