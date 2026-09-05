.PHONY: setup load test eval run demo checksum clean model-build model-check

setup:
	python3 -m venv .venv
	./.venv/bin/pip install -q -r requirements.txt
	cp -n .env.example .env || true
	@echo "Done. Put the organisers' CSVs in data/raw/ then: make load"

load:
	./.venv/bin/python scripts/load_data.py

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
