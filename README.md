# Finance Assistant — BVP Tech Catalyst Hackathon

Natural-language questions over a financial ledger. Every answer is computed by
SQL against real records; the model translates intent and narrates results, and
never produces a number itself.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data/raw            # drop the organisers' CSVs here
python scripts/load_data.py
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

`schema/semantic_layer.yaml` is the only file that should change when the real
data dictionary arrives.

## Status

| Module | State |
|---|---|
| `db.py` `dates.py` `compiler.py` `validator.py` | deterministic core, testable now |
| `api.py` | live, `/ask_spec` works without a model |
| `planner.py` `narrator.py` | stubs — model integration pending |
| `ui/` | empty |
