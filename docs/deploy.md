# Deploying to Render

This app is one FastAPI process: it serves the built React app from
`frontend/dist` (falling back to `ui/index.html` if the build is missing),
answers `/ask` by querying `data/finance.duckdb`, and calls an LLM through
`app/llm.py`. `render.yaml` at the repo root is a Render **Blueprint** that
builds all of that with Render's native Python runtime -- no Dockerfile.

Nobody can run `render login` from an unattended/CI session (it opens a
browser), so the steps below are written for a human at a keyboard.

## 1. Commit and push

Render deploys from GitHub, not from your local working copy. Commit your
changes and push the branch you want deployed:

```bash
git push origin main
```

(Or push a feature branch and point Render at that branch instead of `main`.)
The remote is `https://github.com/Aahan215/ByteRideFinanceAssistant.git`.

`data/finance.duckdb` and `data/raw/` are gitignored (confirmed: `git
check-ignore -v data/finance.duckdb data/raw` matches `.gitignore` lines 1-2)
and must **not** be pushed -- they're 224MB/565MB locally and Render builds
its own copy of the demo dataset from scratch anyway (see step 4).

## 2. Log in to Render

```bash
render login
```

This opens your browser to authorize the CLI. It cannot be done headlessly.

## 3. Launch the blueprint

The Render CLI (`render v2.10`, confirmed by running `render --help` and
`render blueprints --help` in this repo) does **not** have a `blueprint
launch` or `blueprints create` subcommand -- the only blueprint command it
ships is:

```bash
render blueprints validate            # validates ./render.yaml locally
```

`render blueprints validate` was run against the real connected Render
workspace while preparing this deploy and returned `"valid": true` for
`render.yaml` as committed (with `plan: free`) -- `plan: starter` fails
validation on that workspace specifically with `need_payment_info` because no
card is on file; it will validate once billing is added (see the plan note
below). Use `validate` any time you edit `render.yaml`, before pushing.

To actually **create and deploy** the service, there is no CLI path in this
version -- use the Render Dashboard:

1. Go to <https://dashboard.render.com>.
2. Click **New +** -> **Blueprint**.
3. Connect the `Aahan215/ByteRideFinanceAssistant` GitHub repo (authorize
   Render's GitHub App if this is the first time).
4. Pick the branch you pushed in step 1. Render finds `render.yaml`
   automatically and shows a preview of the one service it defines
   (`byteride-finance-assistant`, Python runtime).
5. Click **Apply** / **Create New Resources**.

## 4. Set the secret

`render.yaml` declares `GEMINI_API_KEY` with `sync: false`, so Render will
prompt for it (or leave it blank) rather than reading a value from the repo.
Set it in the dashboard: the service's **Environment** tab -> `GEMINI_API_KEY`
-> paste the key from <https://aistudio.google.com/apikey>. Do this **from
your own copy** of the key -- never copy the value out of your local `.env`
into any file that could get committed.

`FINANCE_AES_KEY` / `FINANCE_AES_IV` / `FINANCE_AES_MODE` are also declared
with `sync: false` but can be **left unset**: the build command generates the
demo dataset with `--no-encrypt`, so account numbers arrive as plaintext
digits and get masked to last-4 at load time without ever calling
`app/crypto.py`'s decrypt path. They only matter if you later point the
build at real, AES-encrypted organiser CSVs.

## 5. What the build does

```
pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
python scripts/generate_dataset.py --rows 200000 --no-encrypt
python scripts/load_data.py
```

Render's Python native runtime image bundles Node/npm already (confirmed via
Render's own native-runtimes docs), so the frontend build needs no extra
setup. The dataset step regenerates a fresh, deterministic 200k-row synthetic
demo dataset on every build (seeded, `--seed 42` by default) and runs it
through the same ETL as `make load` -- there is no real customer data on the
deployed instance, ever.

**Local timing** (this machine, Apple Silicon, via a scratch copy of the repo
so the real `data/raw` and `data/finance.duckdb` were never touched):

| step | time | peak RSS |
|---|---|---|
| `generate_dataset.py --rows 200000 --no-encrypt` | 1.4s | 227MB |
| `load_data.py` (ETL: parse, mask, canonicalise, rollups, anomaly stats) | 3.9s | 339MB |
| `frontend && npm ci` | 2.1s | 269MB |
| `frontend && npm run build` | 5.9s | 388MB |

Total dataset+ETL time is under 10 seconds and every step stays comfortably
under 512MB, so the "would 200k rows fit in ~2 minutes / ~1GB RAM" bar from
the plan is cleared with a lot of margin (Render's build machines will not be
identical hardware, but there's no reason to expect anything close to the
2-minute/1GB ceiling). No fallback to `data/sample/seed.sql` was needed.

## 6. Expected first build time

Given the local numbers above, expect first build to be dominated by network
I/O rather than compute: `pip install` (duckdb, pandas, cryptography, etc. --
mostly wheels) and `npm ci` fetching packages. Budget roughly **3-6 minutes**
for a cold build; the dataset+ETL portion itself is single-digit seconds.

## 7. Verify the deploy

Once the service shows **Live** in the dashboard:

```bash
curl https://<your-service>.onrender.com/health
# {"ok":true,"etl_ready":true,"anchor_date":"...", ...}

curl -X POST https://<your-service>.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "how much did I spend on groceries last month"}'
```

and open `https://<your-service>.onrender.com/` in a browser to confirm the
React UI loads (it's served from `frontend/dist`, built during step 5).

`healthCheckPath: /health` is safe regardless of readiness state: `app/api.py`
's `/health` handler never sets a non-200 status code -- it returns
`{"ok": false, "etl_ready": false, ...}` as a normal 200 JSON body when the
ETL hasn't produced the derived tables yet, and Render's health check only
cares about the HTTP status.

## 8. Cost

`render.yaml` currently sets `plan: free` (0.1 CPU, 512MB RAM, spins down
after 15 minutes idle, ~1 minute cold start on the next request -- confirmed
current as of the Render pricing/docs pages checked while preparing this).
That's enough RAM for this app (see the timing table above) and costs
nothing, but the cold start is a bad look if a judge hits the app cold during
a demo window.

If you want the instance to stay warm for a live judging session, add a
payment method to the Render workspace and change `render.yaml`:

```yaml
plan: starter   # $7/mo, 0.5 CPU, 512MB RAM, no spin-down
```

then re-run `render blueprints validate` (it will now pass -- the only reason
it currently fails on `starter` is the missing payment method) and push /
redeploy. Beyond that, LLM calls are billed by Google AI Studio directly
against your `GEMINI_API_KEY`, separate from Render's bill.

## Efficiency numbers will look different in prod

`config/models.yaml` maps the `planner`/`narrator`/`router` roles to
`gemini-3.5-flash-lite` and the `escalate` role to `gemini-3.6-flash` on the
hosted path (`provider: gemini` / `LLM_PROVIDER=gemini`, which is what
`render.yaml` sets). Locally, the team runs everything through Ollama
(`qwen3:4b` for planner/narrator/router, `qwen3:8b` for escalate) against a
shared inference server. Model-efficiency numbers gathered against the local
Ollama setup (latency, escalation rate, tokens/sec) **do not transfer** to
the deployed instance -- Gemini's hosted models have different latency,
throughput and escalation behaviour than the local qwen3 models, so
`/efficiency` on the Render deployment and `make eval-compare` locally are
measuring two different systems, not the same one under different load.

## Why not Vercel

Vercel's Node/Python functions are **serverless**: each invocation gets a
fresh, size-capped (a few hundred MB, depending on plan) function instance
with a request timeout (10s on Hobby, up to 60-300s on paid tiers), and no
guaranteed process continuity between requests. This app needs a **persistent
process**: `app/db.py` holds a cached DuckDB connection
(`functools.lru_cache` on `_root()`) and `app/llm.py` accumulates an
in-memory `USAGE` log across calls for the `/efficiency` endpoint, both of
which assume one long-lived process, not a cold function per request.
Bundling DuckDB plus a 20-200MB `.duckdb` file plus pandas/cryptography into
a serverless function's size budget is also a poor fit compared to a normal
VM-style web service with its own disk. Render's native Python web service
is a persistent process on its own instance, which is what this app is
built around.

Vercel *could* still host the static frontend alone (`frontend/dist` as a
static site) if the FastAPI backend were split into its own service
elsewhere -- that's a legitimate architecture, just not the one used here.
We're deploying the frontend and backend together as one Render web service
instead, so there's nothing to split.

## Local dry-run: `make deploy-check`

`make deploy-check` runs the exact `buildCommand` steps above (frontend
build, dataset generation, ETL) plus `/health`, `/ask` and `/` smoke checks,
entirely inside a throwaway copy of the repo under `$TMPDIR` -- it never
touches the real `data/finance.duckdb` or `data/raw`. Use it to sanity-check
a `render.yaml` or build-step change before pushing:

```bash
make deploy-check
```
