# ByteRide Finance Assistant — BVP Tech Catalyst Hackathon

A conversational AI assistant that answers plain-language questions about
financial data. Every answer is computed by SQL against real records; the model
translates intent and narrates results, and never produces a number itself.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Generate 1000-row sample dataset (dates up to today)
python scripts/generate_dataset.py --rows 1000 --no-encrypt

# Load data into DuckDB
python scripts/load_data.py

# Start Ollama (separate terminal)
ollama serve
ollama pull qwen3:4b

# Start the API + UI
export LLM_PROVIDER=ollama
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_API_KEY=ollama
uvicorn app.api:app --reload
```

Open **http://localhost:8000** for the chat UI.

## Date Handling

The assistant uses the **current wall clock date** as "today". Relative date
phrases resolve against the real date:
- "this month" = current calendar month
- "last month" = previous calendar month
- "last 3 months" = trailing 3 months from today

`GET /health` returns today's date for the UI to display.

## Model

Uses **Qwen3 4B** via Ollama — a 4-billion parameter open-weights model.
Well under the 20B cap, with published parameter counts for provability.

`config/models.yaml` is the single source of truth for model configuration.
`.env` holds only the endpoint and key.

| Provider | Endpoint | Config key |
|---|---|---|
| `ollama` | local Ollama server | `ollama_base` |
| `gemini` | Google AI Studio | `base` |
| `hosted` | any OpenAI-compatible API | `base` |

## Scaling

Generate larger datasets for testing:

```bash
python scripts/generate_dataset.py --rows 1000000 --no-encrypt   # 1M rows
python scripts/generate_dataset.py --rows 20000000 --format parquet  # 20M rows
```

Then reload: `rm data/finance.duckdb && python scripts/load_data.py`

## Architecture

```
question → nlq_dates (regex) → date range
         → planner (Qwen3 4B) → QuerySpec JSON
         → validator (fuzzy match against real data)
         → compiler → parameterised SQL
         → DuckDB → DataFrame + evidence rows
         → narrator (Qwen3 4B) → numeric guard → English answer
         → JSON response with breakdown, evidence, confidence, anomalies
```

The LLM appears exactly twice and touches no arithmetic in either place.

## Key Design Decisions

- **Grounding**: Every number comes from SQL. The model never computes.
- **Hallucination guard**: `numeric_guard()` verifies every number in the
  narrator's output exists in the result set.
- **Sensitive data**: `account_number` shows last 4 digits only; `utr_number`
  is fully redacted. Masking happens in SQL, never in Python.
- **Counterparty**: Parsed from free-text narration at load time by
  `app/enrich.py`. The model never parses descriptions at query time.
- **Categories**: Derived from narration keywords (TAX, BANK_CHARGES, etc.).
  No category column exists in the raw data.
- **Confidence**: Self-consistency sampling + deterministic assessment based
  on row count, warnings, and data quality.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Chat UI |
| `/health` | GET | Status + current date |
| `/ask` | POST | Natural language question (uses LLM) |
| `/ask_spec` | POST | Hand-written QuerySpec (no LLM) |
| `/export` | POST | Download breakdown as CSV/Excel |
| `/efficiency` | GET | Model usage stats |

## Status

| Module | State |
|---|---|
| `db.py` `dates.py` `compiler.py` `validator.py` | ✅ deterministic core |
| `planner.py` | ✅ LLM-backed with prompt tuning for Qwen3 4B |
| `narrator.py` | ✅ LLM-backed with numeric guard + template fallback |
| `api.py` | ✅ all endpoints working |
| `ui/` | ✅ chat interface with branding, suggestions, export |
| `evals/` | ✅ 35 golden questions |
