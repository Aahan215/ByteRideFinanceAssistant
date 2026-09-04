# Git workflow — read this before your first push

## The one rule everything else serves

**`main` always runs.** At any moment, someone must be able to clone `main`,
run `make setup && make demo`, and see a working assistant. If you break `main`,
fixing it outranks whatever you were doing.

## Why we are NOT doing code review

Normal engineering says: branch, PR, review, merge. At hackathon speed, review
latency costs more than review catches — *provided nobody edits anyone else's
files*. That is what the ownership table below buys us.

One exception: **anything touching `app/spec.py` goes through a PR** with one
approval. It is the shared contract; a silent field rename breaks four people
at once. Everything else, self-merge.

## File ownership

| Files | Owner |
|---|---|
| `scripts/load_data.py`, `schema/semantic_layer.yaml` | Stream 1 — Data |
| `app/compiler.py`, `app/validator.py`, `app/dates.py` | Stream 2 — Engine |
| `app/planner.py`, `app/narrator.py`, `app/llm.py`, `config/models.yaml` | Stream 3 — Model |
| `ui/**` | Stream 4 — UI |
| `evals/**`, `README.md`, deck, diagram | Stream 5 — QA & story |
| `app/api.py` | Stream 2, but coordinate — UI and Model both depend on it |
| `app/spec.py` | **Shared contract. PR + one approval.** |

Need a change in a file you don't own? Ask the owner in chat. Do not edit it
yourself. That costs 90 seconds and saves an hour of merge conflicts.

## Branches

Short-lived, one per ticket, named `s<stream>/<slug>`:

```bash
git checkout main && git pull --rebase
git checkout -b s3/planner-prompt
# ... work ...
make test
git checkout main && git pull --rebase
git merge s3/planner-prompt && git push
```

Branches live **hours, not days**. If yours is more than half a day old you are
heading for a painful merge — split it and land what works.

## Merge cadence

Land something on `main` at least every **3 hours**, even if incomplete but
working. The failure mode that kills hackathon teams is four people merging for
the first time with six hours left. There is no "final merge" in this plan —
integration is continuous, and the end of the hackathon is just the last merge.

Before every merge:

```bash
make test      # must pass
make eval      # once the golden set exists — accuracy must not drop
```

## Hard rules

1. **Never `git push --force` to `main`.** Not once, not "just quickly".
2. **Never commit `data/`.** See below.
3. **Tag before anything risky:** `git tag -a safe-1 -m "working: multi-turn"`.
   Tags are free and are your only way back when a refactor goes wrong at 3am.
4. Commit messages: `[s3] planner emits valid spec for date filters`. The prefix
   makes `git log --oneline` readable at a glance.

## One model server — non-negotiable

Nobody runs their own Ollama. Not because you can't, but because five inference
servers means five different accuracy numbers and nobody knows which one the
demo machine will reproduce.

- **`config/models.yaml` is committed.** Model names, temperature, top_p, seed
  and `num_ctx` live in git and are baked into derived models on the host, so a
  client that forgets to send a param still gets the right one.
- **`.env` carries the endpoint and nothing else.** It is the only per-machine file.
- **`make model-check` before you trust any eval number.** It runs a fixed canary
  prompt and compares the output hash to `config/canary.lock`. A mismatch means
  your numbers are not comparable to the team's.
- **Failures are loud.** `ModelUnavailable` is raised rather than falling back to
  another model — a silent substitution is worse than an error.

Host setup, once: `make model-build`, then `make model-lock` and commit the lockfile.

If the venue wifi isolates clients — common, and it will not be obvious — the host
runs `cloudflared tunnel --url http://localhost:11434` and shares the https URL.
Have that ready before you need it.

## The dataset never goes in git

20M records is far past GitHub's limits, and the built `.duckdb` file will be
hundreds of MB. Instead:

- Raw CSVs live in a **shared Drive folder**, linked from the README.
- Everyone downloads to `data/raw/` and runs `make load`.
- Confirm you all have identical data with `make checksum` — it hashes the
  source CSVs, not the database.

`.gitignore` already blocks `data/`. Do not override it.

## Release ritual (the last 4 hours)

| Time left | Do |
|---|---|
| **4h** | Feature freeze. Everyone merges whatever works. `git tag pre-freeze` |
| **3h** | Full eval run. Fix **only** failing questions. No new features. |
| **2h** | `git tag demo`. Check out the `demo` tag on the demo machine. **Stop pulling.** |
| **1h** | Rehearse the demo twice, end to end, on the tagged build. |
| **0h** | Submit. Checklist below. |

Tagging `demo` and freezing the demo machine matters because a last-minute push
that breaks the laptop you are about to present on is the single most common way
good hackathon projects lose.

## Submission checklist

- [ ] Working prototype — chat UI + backend, runs from a clean clone
- [ ] Architecture diagram
- [ ] README with setup instructions (test it on a teammate's machine)
- [ ] Sample questions + the answers the assistant actually produced
- [ ] Deck: problem, approach, **model choice rationale**, demo flow
- [ ] Model efficiency report — which model answered what, escalation rate
- [ ] Accuracy against the golden set, with the model-comparison table
