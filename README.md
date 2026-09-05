# ByteRide Finance Assistant

> **BVP Tech Catalyst Hackathon** — A conversational AI that answers plain-language questions about financial transactions. Every number is computed by SQL against real records. The model translates intent and narrates results — it never produces a number itself.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [How It Works](#how-it-works)
3. [Architecture](#architecture)
4. [Module Reference](#module-reference)
5. [What You Can Ask](#what-you-can-ask)
6. [Data Pipeline](#data-pipeline)
7. [Model & Efficiency](#model--efficiency)
8. [Configuration](#configuration)
9. [API Reference](#api-reference)
10. [Evaluation](#evaluation)

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running
- ~4 GB RAM for the Qwen3 4B model

### Setup

```bash
# Clone and enter the project
cd ByteRideFinanceAssistant

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Pull the model
ollama pull qwen3:4b

# Generate sample data (500 rows, dates up to today)
python scripts/generate_dataset.py --rows 500 --no-encrypt --end $(date +%Y-%m-%d)

# Load into DuckDB
python scripts/load_data.py

# Start the server
LLM_PROVIDER=ollama LLM_BASE_URL=http://localhost:11434/v1 LLM_API_KEY=ollama \
  python3 -m uvicorn app.api:app --reload --port 8000
```

Open **http://localhost:8000** — the chat UI is ready.

---

## How It Works

The user asks a question in plain English. The system:

1. **Extracts dates** from the question using regex (deterministic, no LLM)
2. **Converts intent to JSON** using Qwen3 4B — the model outputs a structured `QuerySpec` with dataset, metric, filters, and grouping
3. **Validates** the spec against real data (fuzzy-matches vendor names, checks categories exist)
4. **Compiles to SQL** — parameterised, with sensitive column masking
5. **Executes on DuckDB** — returns a DataFrame
6. **Narrates the result** using Qwen3 4B — turns the table into 2-3 English sentences
7. **Guards the narration** — every number in the response must exist in the result set

**The LLM is used exactly twice**: once to understand the question, once to phrase the answer. It never sees raw data, never computes, and never writes SQL.

---

## Architecture

```
User Question
     │
     ├──► nlq_dates.py (regex)  ──► DateRange (deterministic)
     │
     ├──► planner.py (Qwen3 4B) ──► QuerySpec JSON
     │         │
     │         ├── coerce()      ──► fix small-model mistakes
     │         └── validator.py  ──► fuzzy-match against real data
     │
     ├──► compiler.py            ──► Parameterised SQL
     │
     ├──► DuckDB                 ──► DataFrame + evidence rows
     │
     ├──► narrator.py (Qwen3 4B) ──► English answer
     │         │
     │         └── numeric_guard  ──► verify every number exists in results
     │
     └──► API Response
           ├── answer (text)
           ├── breakdown (table)
           ├── evidence (source rows, masked)
           ├── confidence (high/medium/low + reasons)
           ├── anomalies (unusual amounts)
           ├── sql (resolved, human-readable)
           └── export (CSV/Excel)
```

---

## Module Reference

### Core Pipeline

| Module | Role | Uses LLM? |
|---|---|---|
| `nlq_dates.py` | Regex extraction of date phrases ("this month", "last 3 months") | No |
| `planner.py` | NL → QuerySpec JSON via few-shot prompting | **Yes** |
| `spec.py` | Pydantic model defining QuerySpec schema | No |
| `validator.py` | Fuzzy-match filters against real data, refuse if invalid | No |
| `compiler.py` | QuerySpec → parameterised SQL with sensitive column masking | No |
| `db.py` | DuckDB connection, semantic layer loader, anchor date | No |
| `narrator.py` | Result table → English sentences with numeric guard | **Yes** |
| `dates.py` | Resolve relative DateRange against anchor date | No |

### Supporting Modules

| Module | Role |
|---|---|
| `api.py` | FastAPI endpoints — `/ask`, `/health`, `/export`, `/efficiency` |
| `llm.py` | Provider shim — Ollama (native API), Gemini, or any OpenAI-compatible endpoint |
| `enrich.py` | Parse counterparty, category, channel from transaction descriptions at load time |
| `anomaly.py` | Flag transactions with unusual amounts vs. vendor history |
| `confidence.py` | Deterministic confidence scoring — row count, coverage, self-consistency |
| `boundary.py` | Audit trail — what data crossed to the model |
| `crypto.py` | AES-256 decrypt/surrogate for encrypted datasets |
| `data_dictionary.py` | Schema validation against the organisers' data dictionary |
| `stub_planner.py` | Keyword-based planner for development without a running model |

### Scripts

| Script | Purpose |
|---|---|
| `scripts/generate_dataset.py` | Generate synthetic data with realistic narration formats |
| `scripts/load_data.py` | Load CSVs → enrich → build DuckDB views and rollups |
| `scripts/schema_check.py` | Verify loaded data matches the data dictionary |

---

## What You Can Ask

### Datasets

| Keyword | Dataset | Meaning |
|---|---|---|
| "spend", "paid", "debits" | `payouts` | Money going out |
| "received", "credits", "income" | `receipts` | Money coming in |
| "all transactions" | `transactions` | Both directions |

### Metrics

| Keyword | Metric |
|---|---|
| "how much", "total" | `sum_amount` |
| "how many", "count" | `count` |
| "average" | `avg_amount` |
| "largest", "biggest" | `max_amount` |
| "smallest" | `min_amount` |

### Filters

| Filter | Example Question |
|---|---|
| Category | "Total tax paid", "Show EMI payments" |
| Vendor | "How much did I pay Bajaj Finance?" |
| Bank | "Show HDFC transactions" |
| Channel | "How many UPI payments?" |
| Amount | "Transactions above 50000" |
| Reference | "Find transaction with reference 123456" |

### Categories (derived from descriptions)

`BANK_CHARGES` · `CASH` · `CHEQUE` · `EMI_LOAN` · `INSURANCE` · `INVESTMENT` · `RENT` · `SALARY` · `TAX` · `TRANSFER` · `UTILITIES`

### Channels

`UPI` · `IMPS` · `NEFT` · `RTGS` · `FT` · `CHEQUE`

### Grouping

"by category", "by vendor", "by bank", "by month", "by quarter", "by channel"

### Follow-ups

The system tracks conversation context. After any question, you can say:
- "What about last month?"
- "Break that down by category"
- "Show the count instead"
- "How about receipts?"

---

## Data Pipeline

### 1. Generate (`scripts/generate_dataset.py`)

Creates synthetic CSVs in `data/raw/` with realistic Indian bank narration formats:

```bash
python scripts/generate_dataset.py --rows 500 --accounts 10 --entities 3 --months 6 --no-encrypt
```

### 2. Load & Enrich (`scripts/load_data.py`)

```
data/raw/transaction.csv
     │
     ├──► enrich.py: parse(description)
     │       ├── counterparty: regex extracts vendor name from narration
     │       ├── category: keyword matching (TAX, EMI, SALARY, etc.)
     │       └── channel: prefix detection (UPI/, IMPS/, NEFT-, etc.)
     │
     ├──► txn_parsed table (counterparty, category, channel per row)
     │
     ├──► txn_enriched VIEW = transaction ⟕ txn_parsed ⟕ account ⟕ bank ⟕ anomaly
     │
     ├──► rollup_counterparty_month (pre-aggregated for fast queries)
     │
     └──► counterparty_stats + txn_anomaly (anomaly detection)
```

**Key point**: Categories and counterparties do NOT exist in the raw data. They are extracted deterministically from the free-text `description` field at load time. The LLM never parses descriptions.

### 3. Query (`app/compiler.py`)

The `QuerySpec` is compiled to parameterised SQL:

```sql
-- "How much did I spend on EMI this month?"
SELECT SUM(transaction_amount) AS sum_amount
FROM txn_enriched
WHERE transaction_type = 'debit'
  AND category = 'EMI_LOAN'
  AND transaction_date >= '2026-09-01'
  AND transaction_date < '2026-10-01'
```

Sensitive columns are masked in SQL:
- `account_number` → last 4 digits only
- `utr_number` → fully redacted

---

## Model & Efficiency

### Model Choice

| Role | Model | Parameters | Why |
|---|---|---|---|
| Planner | Qwen3 4B | 4 billion | Smallest model that reliably produces structured JSON |
| Narrator | Qwen3 4B | 4 billion | Same model, different prompt — no extra memory cost |

**Well under the 20B parameter cap.** Open-weights with published parameter counts for provability.

### Efficiency Features

- **Schema-constrained decoding** (Ollama native API) — model can only emit valid field names/values
- **`/no_think` mode** — disables reasoning chain, reduces latency from ~30s to ~3-5s
- **Deterministic date handling** — regex, not LLM
- **Deterministic category/counterparty** — parsed at load time, not query time
- **Self-consistency sampling** — configurable (1-3 samples) for confidence scoring
- **Pre-built rollups** — common aggregations are sub-millisecond

### What the LLM Does NOT Do

- ❌ Compute numbers
- ❌ Write SQL
- ❌ See raw transaction data
- ❌ Parse descriptions
- ❌ Handle dates
- ❌ Make up answers

---

## Configuration

### Environment Variables (`.env`)

```bash
LLM_PROVIDER=ollama          # ollama | gemini | hosted
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
```

### Model Config (`config/models.yaml`)

Single source of truth for model behaviour. Committed to git so all team members get identical results.

```yaml
roles:
  planner:
    ollama_base: qwen3:4b
    temperature: 0
    num_ctx: 8192
  narrator:
    ollama_base: qwen3:4b
    temperature: 0.2    # slight variation for natural prose
    num_ctx: 4096
```

### Semantic Layer (`schema/semantic_layer.yaml`)

Defines datasets, metrics, dimensions, sensitive columns, and synonyms. The planner prompt is generated from this file so it cannot drift from the actual schema.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Chat UI |
| `/health` | GET | Status + current date |
| `/ask` | POST | `{"question": "...", "session_id": "..."}` → full answer with breakdown |
| `/ask_spec` | POST | Hand-written QuerySpec → bypasses LLM entirely |
| `/export` | POST | Download breakdown as CSV or Excel |
| `/efficiency` | GET | Model usage stats (calls, escalations, by-model counts) |

### Response Shape (`/ask`)

```json
{
  "answer": "Total for September 2026: ₹4,52,000",
  "confidence": "high",
  "sql": "SELECT SUM(...) FROM txn_enriched WHERE ...",
  "window": "2026-09-01 to 2026-09-30",
  "breakdown": [{"category": "EMI_LOAN", "sum_amount": 180000}, ...],
  "evidence": [{"transaction_id": "...", "amount": 15000, ...}],
  "anomalies": ["VENDOR X: ₹50,000 is 5.2x the usual ₹9,600"],
  "confidence_reasons": ["based on 42 transactions"],
  "warnings": ["Read \"this month\" as 2026-09-01 to 2026-09-30"],
  "refused": false,
  "spec": {"dataset": "payouts", "metric": "sum_amount", ...}
}
```

---

## Evaluation

### Golden Set (`evals/golden.yaml`)

35 test questions covering:
- Spend totals, tax, channels, vendors, banks
- Amount filters, reference lookups
- Multi-turn follow-ups
- Refusals (credit score, predictions, HR data)
- Edge cases (empty results, ambiguous names)

### Scoring Criteria (from problem statement)

| Criterion | Weight |
|---|---|
| Accuracy & grounding | 30% |
| Model efficiency | 20% |
| Natural language understanding | 15% |
| Functionality | 15% |
| User experience | 10% |
| Presentation | 5% |
| Business impact | 5% |

---

## Date Handling

The assistant uses **wall clock date** (`datetime.date.today()`) as "today". All date resolution is deterministic:

| User says | Resolves to |
|---|---|
| "this month" | Current calendar month |
| "last month" | Previous calendar month |
| "last 3 months" | Trailing 3 months from today |
| "yesterday" | Yesterday's date |
| "today" | Today's date |

The current date is injected into the LLM prompt so it has temporal context, but the LLM never computes dates — `nlq_dates.py` handles all resolution via regex.

---

## Security & Privacy

- **Parameterised queries** — all user input goes through `?` placeholders, never string concatenation
- **Sensitive column masking** — `account_number` shows last 4 digits, `utr_number` is redacted (in SQL, not Python)
- **Boundary audit** — `boundary.py` logs every prompt sent to the model
- **AES-256 support** — `crypto.py` can decrypt encrypted datasets (not active by default)
- **No raw data to LLM** — the model sees only the question and aggregate result tables, never individual transaction rows

---

## Scaling

```bash
# 1K rows (quick test)
python scripts/generate_dataset.py --rows 1000 --no-encrypt

# 1M rows (demo scale)
python scripts/generate_dataset.py --rows 1000000 --no-encrypt

# 20M rows (max from problem statement)
python scripts/generate_dataset.py --rows 20000000 --format parquet
```

Then reload: `rm data/finance.duckdb && python scripts/load_data.py`

DuckDB handles 20M rows comfortably. Pre-built rollups keep common queries sub-millisecond.
