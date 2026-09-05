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
uvicorn app.api:app --reload
```

`GET /health` returns the **anchor date** — the assistant's "today", taken from
the max date in the data rather than the wall clock.

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
