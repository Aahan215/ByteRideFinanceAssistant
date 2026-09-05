.PHONY: setup load test eval run demo checksum clean model-build model-check data-local data-prod bench schema-check deploy-check

setup:
	python3 -m venv .venv
	./.venv/bin/pip install -q -r requirements.txt
	cp -n .env.example .env || true
	@echo "Done. Put the organisers' CSVs in data/raw/ then: make load"

load:
	./.venv/bin/python scripts/load_data.py
	$(MAKE) schema-check

schema-check:
	./.venv/bin/python scripts/schema_check.py

test:
	./.venv/bin/python -m pytest tests/ -q

eval:
	./.venv/bin/python evals/run_evals.py

run:
	./.venv/bin/uvicorn app.api:app --reload --host 127.0.0.1 --port 8765

demo: test
	./.venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8765

checksum:
	@shasum -a 256 data/raw/*.csv 2>/dev/null || echo "no CSVs in data/raw/ yet"

clean:
	rm -rf .pytest_cache app/__pycache__ tests/__pycache__

# --- host only ---
model-build:
	./.venv/bin/python scripts/build_models.py

# --- everyone, before you trust any eval number ---
model-check:
	./.venv/bin/python scripts/model_check.py

model-lock:
	./.venv/bin/python scripts/model_check.py --write

enrich-report:
	./.venv/bin/python scripts/load_data.py

crypto-probe:
	./.venv/bin/python scripts/crypto_probe.py

# --- dataset ---
# Local: small enough to regenerate in seconds and iterate on.
data-local:
	./.venv/bin/python scripts/generate_dataset.py --rows 200000
	$(MAKE) load

# Production-scale: what the prototype is actually judged against.
data-prod:
	./.venv/bin/python scripts/generate_dataset.py --rows 20000000 --format parquet
	$(MAKE) load

bench:
	./.venv/bin/python scripts/benchmark.py

eval-stub:
	./.venv/bin/python evals/run_evals.py --stub


# Settle the model choice with evidence, not opinion.
eval-compare:
	@for m in qwen3:1.7b qwen3:4b qwen3:8b; do \
		./.venv/bin/python evals/run_evals.py --model $$m --out evals/report-$$m.md || true; \
	done

# --- frontend ---
ui-install:
	cd frontend && npm install --no-audit --no-fund

ui-dev:
	cd frontend && npm run dev      # :5173, proxies the API to :8765

ui-build:
	cd frontend && npm run build    # FastAPI then serves frontend/dist at /

redteam:
	LLM_PROVIDER=ollama ./.venv/bin/python evals/run_redteam.py

# --- deploy ---
# Runs the render.yaml buildCommand steps end to end (frontend build, demo
# dataset generation, ETL) plus the /health, /ask and / smoke checks, all
# against a throwaway copy of the repo under $TMPDIR so data/finance.duckdb
# and data/raw are never touched. See docs/deploy.md for the actual Render
# deploy steps -- this only proves the build+serve path works locally.
deploy-check:
	@TMP=$$(mktemp -d "$${TMPDIR:-/tmp}/byteride-deploy-check.XXXXXX"); \
	trap 'kill $$SERVER_PID 2>/dev/null; rm -rf "$$TMP"' EXIT; \
	set -e; \
	echo "== deploy-check: scratch dir $$TMP (real data/finance.duckdb and data/raw untouched) =="; \
	echo "-- 1/4 frontend build --"; \
	(cd frontend && npm ci --no-audit --no-fund && npm run build); \
	echo "-- 2/4 demo dataset (200k rows, unencrypted) + ETL, isolated in $$TMP --"; \
	rsync -a --exclude='.git' --exclude='.venv' --exclude='data/raw' \
	      --exclude='data/finance.duckdb' --exclude='frontend/node_modules' \
	      --exclude='frontend/dist' --exclude='.pytest_cache' . "$$TMP/"; \
	./.venv/bin/python "$$TMP/scripts/generate_dataset.py" --rows 200000 --no-encrypt; \
	./.venv/bin/python "$$TMP/scripts/load_data.py"; \
	echo "-- 3/4 starting the API on :8790 against the scratch DB --"; \
	PORT=8790 FINANCE_DB_PATH="$$TMP/data/finance.duckdb" FINANCE_STUB_PLANNER=1 \
	  ./.venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8790 \
	  > "$$TMP/uvicorn.log" 2>&1 & \
	SERVER_PID=$$!; \
	sleep 2; \
	echo "-- 4/4 curl checks --"; \
	curl -sf http://127.0.0.1:8790/health; echo; \
	curl -sf -X POST http://127.0.0.1:8790/ask -H "Content-Type: application/json" \
	     -d '{"question": "how much did I spend on groceries last month"}' | head -c 300; echo; \
	curl -sf http://127.0.0.1:8790/ | head -c 200; echo; \
	echo "deploy-check OK"
