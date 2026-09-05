# Team plan — 5 people

## Streams

| Owner | Stream | Files they own | First task |
|---|---|---|---|
| 1 | **Data & crypto** | `scripts/load_data.py`, `app/enrich.py`, `app/crypto.py`, `schema/semantic_layer.yaml` | Run `make crypto-probe`, profile every column, then tune the TAX and vendor-name rules on the real corpus |
| 2 | **Engine** | `app/compiler.py`, `validator.py`, `dates.py`, `api.py` | `compare_to` for period-over-period, entity scope, then export and anomalies |
| 3 | **Model & planner** | `app/planner.py`, `narrator.py`, `llm.py` | Hosts Ollama. Get `plan()` emitting valid QuerySpecs, then the cascade + self-consistency confidence |
| 4 | **UI** | `ui/` | Chat + breakdown table + collapsible SQL/evidence panel. Build against `POST /ask_spec` from hour one |
| 5 | **QA & story** | `evals/`, deck, diagram, demo script | Own the golden set, run evals after every merge, build the model-comparison table, write the deck |

**Stream 3 owns the shared model server.** Nobody else runs Ollama — see
WORKFLOW.md for why. That machine is also the demo machine, so guard it.

Role 5 is the one teams usually skip and the one that wins. They are the only
person whose job is to find out whether the thing is actually correct, and the
deck is 5% plus they feed the model-choice bonus.

## Rules

1. `app/spec.py` is a shared contract — announce changes in the group chat.
2. Merge to `main` every ~3 hours. One person owns `main`.
3. Nobody waits on the model: `POST /ask_spec` runs the entire pipeline from a
   hand-written spec.
4. Everyone writes 10 golden questions on day one → 50 total. Include
   unanswerable and ambiguous ones; a correct refusal counts as correct.
5. Feature freeze with 4 hours left. Spend them rehearsing the demo.

## Sequence

**Phase 1 — unblock (first 3 hours, everyone)**
`make crypto-probe` · column profile · model server up · 50 golden questions

**Phase 2 — parallel build**
1 crypto wiring + TAX/vendor tuning · 2 `compare_to` + entity scope ·
3 planner emitting valid specs · 4 chat UI on `/ask_spec` · 5 eval runner

**Phase 3 — integration**
`/ask` end to end · numeric guard on · run the golden set · fix what fails

**Phase 4 — points**
Cascade + escalation rate · confidence · anomalies · export ·
model-comparison table · deck · demo rehearsal

## Demo script (draft — role 5 owns this)

1. "Where did I spend the most this month?" → ranked breakdown
2. Expand the SQL panel → "this is the query, these are the rows" (PII masked)
3. "How does that compare to the month before?" → multi-turn, no context repeated
4. "Total tax I paid in the last 3 months" → derived category, shown as derived
5. "Which transactions are unreconciled?" → **refuses cleanly: not in the data.**
   The money shot.
6. Efficiency report: which model answered what, escalation rate
