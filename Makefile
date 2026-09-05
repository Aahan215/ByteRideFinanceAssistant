.PHONY: setup load test eval run demo checksum clean model-build model-check data-local data-prod bench schema-check

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
	./.venv/bin/uvicorn app.api:app --reload --port 8000

demo: test
	./.venv/bin/uvicorn app.api:app --port 8000

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

eval-freeze:
	./.venv/bin/python evals/run_evals.py --freeze

# Settle the model choice with evidence, not opinion.
eval-compare:
	@for m in qwen2.5:3b llama3.2:3b qwen2.5:7b; do \
		./.venv/bin/python evals/run_evals.py --model $$m --out evals/report-$$m.md || true; \
	done

# --- frontend ---
ui-install:
	cd frontend && npm install --no-audit --no-fund

ui-dev:
	cd frontend && npm run dev      # :5173, proxies the API to :8765

ui-build:
	cd frontend && npm run build    # FastAPI then serves frontend/dist at /
