# ByteRide Finance Assistant — BVP Tech Catalyst Hackathon

Natural-language questions over a financial ledger. Every answer is computed by
SQL against real records; the model translates intent and narrates results, and
never produces a number itself.

**Live deployment:** https://byteride-finance-assistant.onrender.com — hosted
on Render's free tier (cold start up to ~1 min after idling), running the
hosted Gemini models against a synthetic 200k-row dataset.

## Prerequisites

- **Python 3.12+**
- **Node 18+** (only needed to build the React UI — a no-build fallback UI
  ships in `ui/index.html` and works without Node)
- **[Ollama](https://ollama.com)** installed locally, with the models this
  project uses pulled ahead of time:

  ```bash
  ollama pull qwen3:4b     # planner / narrator / router
  ollama pull qwen3:8b     # escalation tier
  ollama pull qwen3:1.7b   # only needed for `make eval-compare`
  ```

  See `config/models.yaml` for exactly which role uses which model, and
  `WORKFLOW.md` for why only one shared Ollama server should run during the
  hackathon.

## Quick start from a clean clone

The shortest path from a fresh checkout to a running UI:

```bash
make setup                    # venv + deps + copies .env.example -> .env
# put the organisers' CSVs in data/raw/, or skip this to use the bundled sample data
make load                     # loads DuckDB, enriches, builds rollups + schema-check
make ui-install && make ui-build
make run                      # http://localhost:8765
```

Then open **http://localhost:8765**.

- `make ui-dev` runs the Vite dev server on **:5173** and proxies API calls to
  the FastAPI backend on **:8765** — use it while actively editing
  `frontend/src`.
- **Fallback:** if the frontend build fails or was never run, FastAPI serves
  `ui/index.html` automatically instead of `frontend/dist` — the app still
  works end to end from a clean clone with zero npm involvement.
- No model yet, or want to develop the UI without one? Run with the keyword
  planner instead:

  ```bash
  FINANCE_STUB_PLANNER=1 make run
  ```

  Every response is then tagged STUB PLANNER on screen. Unset it before
  demoing.

`GET /health` returns the **anchor date** — the assistant's "today", taken from
the max date in the data rather than the wall clock.

## Environment variables

Everyone copies `.env.example` to `.env`. `.env` carries the endpoint and
credentials only; `config/models.yaml` (committed, identical for everyone)
decides which model runs and how it behaves.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | API key for Google AI Studio, used when `provider: gemini` in `config/models.yaml`. Get one at https://aistudio.google.com/apikey. |
| `LLM_TIMEOUT` | Per-request timeout (seconds) for calls to the model endpoint. Defaults to 90. |
| `LLM_PROVIDER` | Optional override of `provider:` in `config/models.yaml` (e.g. force `ollama` locally without editing the committed config). |
| `LLM_BASE_URL` | Optional override of the inferred endpoint URL — set this to point at the shared Ollama host, e.g. `http://192.168.1.XXX:11434/v1`. |
| `LLM_API_KEY` | Optional override of the API key sent to the endpoint (falls back to `GEMINI_API_KEY`, then the literal `ollama`). |
| `FINANCE_AES_KEY` | AES-256 key for decrypting the organisers' encrypted columns at load time. Never commit a real value. |
| `FINANCE_AES_IV` | AES initialization vector paired with `FINANCE_AES_KEY`. Never commit a real value. |
| `FINANCE_AES_MODE` | Block cipher mode: `ctr` \| `cbc` \| `gcm`. Confirm the right mode for a given export with `scripts/crypto_probe.py` before trusting decrypted output. |
| `FINANCE_STUB_PLANNER` | Dev-only escape hatch. Set to `1` to answer with a keyword-rule planner instead of calling a model — useful when no model server is reachable. Unset before demoing. |

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

## API endpoints

| Endpoint | Description |
|---|---|
| `POST /ask` | Full pipeline: question in, planner produces a `QuerySpec`, answer out. Supports multi-turn via `session_id`. |
| `POST /ask_spec` | Runs the deterministic pipeline (validator → compiler → DuckDB → narrator) from a hand-written `QuerySpec`, with no model in the loop. |
| `POST /export` | Returns the breakdown for a given spec as a CSV or XLSX file download. |
| `GET /health` | Readiness check plus the **anchor date** (the assistant's "today", derived from the data, not the wall clock). |
| `GET /scopes` | Lists the valid `scope_level` / `scope_value` options (all / entity / account). |
| `GET /boundary` | Audit trail of what has actually been sent to the LLM — proof the model never sees raw data it shouldn't. |
| `GET /efficiency` | Which model answered each question and the escalation rate, for the model-efficiency report. |

## Running the evals

```bash
make eval            # score the currently configured model against the golden set
make eval-stub       # score the keyword planner (no model) as a baseline
make eval-freeze     # regenerate the frozen expected values from hand-verified specs
make eval-compare    # run qwen3:1.7b / qwen3:4b / qwen3:8b, writing evals/report-<model>.md
make model-check     # confirm you're on the shared model server before trusting any number
```

`evals/run_evals.py` scores three things separately, because they fail for
different reasons:

- **spec match** — did the planner understand the question (does the produced
  `QuerySpec` match the hand-verified `expect_spec`)?
- **value match** — did the pipeline compute the same number the verified spec
  gives? (Expected values are always derived by running `expect_spec` through
  the same engine, never hand-typed, so a human only ever checks the
  interpretation, not the arithmetic.)
- **refusal correctness** — did the assistant decline when the data genuinely
  cannot answer the question, instead of guessing?

`make model-check` runs a fixed canary prompt and compares its output hash to
`config/canary.lock` — a mismatch means you're not talking to the same model
the team's numbers were produced on.

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Create `.venv`, install `requirements.txt`, copy `.env.example` to `.env` if missing. |
| `make load` | Load the DuckDB database from `data/raw/` (or the bundled sample), enrich it, build rollups, then run `schema-check`. |
| `make schema-check` | Verify the loaded schema matches the data dictionary and that derived objects were built. |
| `make test` | Run the pytest suite. |
| `make eval` | Run the accuracy harness against the golden set with the currently configured model. |
| `make eval-stub` | Run the accuracy harness with the keyword planner instead of a model. |
| `make eval-freeze` | Regenerate frozen expected values from hand-verified specs. |
| `make eval-compare` | Run the eval harness across `qwen3:1.7b`, `qwen3:4b`, `qwen3:8b`, writing `evals/report-<model>.md` for each. |
| `make run` | Start the FastAPI app (`uvicorn`, reload on) on `127.0.0.1:8765`. |
| `make demo` | Run tests, then start the FastAPI app without reload — the demo-day command. |
| `make checksum` | Hash the CSVs in `data/raw/` so teammates can confirm they have identical source data. |
| `make clean` | Remove pytest/Python cache directories. |
| `make model-build` | (Host only) Build the derived Ollama models baked with `config/models.yaml`'s sampling params. |
| `make model-check` | Verify you're on the shared model server with the right models, via the canary prompt. |
| `make model-lock` | Write the canary output hash to `config/canary.lock` (host, once, then commit it). |
| `make enrich-report` | Re-runs the loader (alias for inspecting enrichment output). |
| `make crypto-probe` | Profile the encrypted columns in the real export (cipher mode, determinism, joinability) before writing crypto-dependent code. |
| `make data-local` | Generate a 200k-row local dataset and load it. |
| `make data-prod` | Generate the full 20M-row parquet dataset and load it. |
| `make bench` | Measure query latency against whatever is currently loaded. |
| `make ui-install` | `npm install` in `frontend/`. |
| `make ui-dev` | Run the Vite dev server on `:5173`, proxying API calls to `:8765`. |
| `make ui-build` | Build the React app; FastAPI then serves `frontend/dist` at `/`. |
| `make redteam` | Run the adversarial/red-team eval script against an Ollama-served model. |

## Status

| Module | State |
|---|---|
| `app/db.py`, `app/dates.py`, `app/compiler.py`, `app/validator.py` | Deterministic core — fully implemented and tested. |
| `app/api.py` | Live. All endpoints below implemented; `/ask_spec` works with no model in the loop. |
| `app/planner.py` | Implemented — LLM-backed `QuerySpec` planning with confidence/self-consistency and escalation. |
| `app/narrator.py` | Implemented — LLM-backed narration with a numeric guard so the model never states a figure it didn't compute. |
| `ui/index.html` | Implemented — complete no-build fallback chat UI, served automatically if `frontend/dist` isn't built. |
| `frontend/` | React/Vite chat UI — build with `make ui-install && make ui-build`. |
| Tests | **174 passing** (`make test`). |

## Submission artifacts

- `ARCHITECTURE.md` — system graph, request sequence diagram, and design principles
- `docs/architecture.md` — ETL/data path, eval harness, and component table
- `docs/deploy.md` — deployment guide
- `docs/sample_qa.md` — sample questions and the answers the assistant actually
  produced *(generated at submission time)*
- `docs/model_efficiency.md` — which model answered what, escalation rate
  *(generated at submission time)*
- `evals/report-*.md` — per-model accuracy against the golden set, produced by
  `make eval-compare`
- `docs/deck.pptx` — problem, approach, model-choice rationale, demo flow
  *(not yet produced — no deck file exists in this repo or the `feature`
  branch as of this writing; add it here once it's built)*
- **Live deployment:** https://byteride-finance-assistant.onrender.com
  (free tier, cold start up to ~1 min, hosted Gemini models, synthetic
  200k-row dataset)
