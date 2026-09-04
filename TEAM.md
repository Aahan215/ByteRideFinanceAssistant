# Team plan — 5 people

## Streams

| Owner | Stream | Files they own | First task |
|---|---|---|---|
| 1 | **Data & semantics** | `scripts/load_data.py`, `schema/semantic_layer.yaml`, rollups | Load the CSVs, then hand-encode what "unreconciled", each account type, and each status value actually mean |
| 2 | **Deterministic engine** | `app/compiler.py`, `validator.py`, `dates.py` | Refusal + clarification paths, then anomaly z-scores and CSV/Excel export |
| 3 | **Model & planner** | `app/planner.py`, `narrator.py`, `llm.py` | Hosts Ollama. Get `plan()` emitting valid QuerySpecs, then the cascade + self-consistency confidence |
| 4 | **UI** | `ui/` | Chat + breakdown table + collapsible SQL/evidence panel. Build against `POST /ask_spec` from hour one |
| 5 | **QA & story** | `evals/`, deck, architecture diagram, demo script | Own the golden set, run evals after every merge, build the model-comparison table, write the deck |

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

**Phase 1 — foundations (everyone, day one)**
Data loaded · semantic layer hand-written · 50 golden questions · Ollama shared on LAN

**Phase 2 — parallel build**
1 rollups · 2 refusals+export · 3 planner hitting valid specs · 4 chat UI on `/ask_spec` · 5 eval runner

**Phase 3 — integration**
Wire `/ask` end to end · numeric guard on · run the golden set · fix what fails

**Phase 4 — points**
Cascade + escalation rate · confidence signalling · anomaly callouts ·
model-comparison table (8B vs 20B vs 3B accuracy) · deck · demo rehearsal

## Demo script (draft — role 5 owns this)

1. "How much did we spend on vendor payouts last month?" → number + breakdown
2. Expand the SQL panel → "this is the query, these are the rows"
3. "How does that compare to the month before?" → multi-turn, no context repeated
4. "What's our headcount forecast?" → **refuses cleanly**. This is the money shot.
5. Show the efficiency report: which model answered what, escalation rate
