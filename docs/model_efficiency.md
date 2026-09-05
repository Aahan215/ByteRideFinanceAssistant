# Model efficiency

Evidence for the model-choice bonus: which model to run the finance Q&A
planner on, and whether the 4b→8b escalation tier is pulling its weight.
All numbers below are copied verbatim from the `evals/report-*.md` files
this document links to — nothing here is rounded further or invented.

Golden set: `evals/golden.yaml`, 55 cases. Ollama models `qwen3:1.7b`,
`qwen3:4b`, `qwen3:8b`, all pulled locally. Config: `config/models.yaml`
(`provider: ollama`; roles `planner`/`narrator`/`router` = `qwen3:4b`,
`escalate` = `qwen3:8b`).

## Golden set composition

Tag counts (a case can carry more than one tag, so these do not sum to 55):

| tag | count |
|---|---:|
| aggregate | 8 |
| ambiguous | 3 |
| category | 11 |
| channel | 1 |
| dates | 16 |
| filter | 12 |
| grouped | 10 |
| metric | 4 |
| multiturn | 5 |
| refusal | 11 |
| vendor | 2 |

Verified with:
```
./.venv/bin/python -c "
import yaml, collections
cases = yaml.safe_load(open('evals/golden.yaml'))
c = collections.Counter()
for case in cases:
    for t in case.get('tags', ['untagged']):
        c[t] += 1
print(len(cases), 'cases')
for k, v in sorted(c.items()):
    print(k, v)
"
```

## a) Model comparison table

Ollama-reported parameter size and on-disk size (`ollama list` / `/api/tags`),
which differs slightly from the tag name for the 1.7b model:

| model | Ollama parameter_size | on-disk size |
|---|---|---|
| qwen3:1.7b | 2.0B | 1.36 GB |
| qwen3:4b | 4.0B | 2.5 GB |
| qwen3:8b | 8.2B | 5.23 GB |

Accuracy and latency, from each `evals/report-*.md`:

| config | overall accuracy | refusal correctness | planner latency p50 | planner latency max | model size |
|---|---:|---:|---:|---:|---:|
| qwen3:1.7b (raw, escalation off) | 54/55 (98%) | 11/11 (100%) | 458ms | 3546ms | 2.0B / 1.36GB |
| qwen3:4b (raw, escalation off) | 55/55 (100%) | 11/11 (100%) | 1517ms | 7502ms | 4.0B / 2.5GB |
| qwen3:8b (raw, escalation off) | 54/55 (98%) | 11/11 (100%) | 2014ms | 29013ms | 8.2B / 5.23GB |
| tiered 4b→8b (confidence.samples=1, committed default) | 55/55 (100%) | 11/11 (100%) | 1561ms | 7600ms | 4b + 8b co-resident |
| tiered 4b→8b (confidence.samples=3) | 55/55 (100%) | 11/11 (100%) | 1533ms | 2753ms | 4b + 8b co-resident |

Per-bucket accuracy (correct/total), from the same reports:

| bucket | total | qwen3:1.7b | qwen3:4b | qwen3:8b | tiered (samples 1) | tiered (samples 3) |
|---|---:|---:|---:|---:|---:|---:|
| aggregate | 8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |
| ambiguous | 3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| category | 11 | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 |
| channel | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| dates | 16 | 16/16 | 16/16 | **15/16** | 16/16 | 16/16 |
| filter | 12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 |
| grouped | 10 | **9/10** | 10/10 | 10/10 | 10/10 | 10/10 |
| metric | 4 | **3/4** | 4/4 | 4/4 | 4/4 | 4/4 |
| multiturn | 5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| refusal | 11 | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 |
| vendor | 2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |

The two single misses:

- qwen3:1.7b, `grp_count_by_category` — spec mismatch: wanted
  `{'dataset': 'transactions', 'metric': 'count', 'group_by': ['category']}`.
- qwen3:8b, `dt_absolute_range` — spec mismatch: wanted
  `{'dataset': 'payouts', 'metric': 'sum_amount', 'date_range': {'kind':
  'absolute', 'start': '2026-01-01', 'end': '2026-03-31'}}`.

## b) Efficiency report — tiered runs

Both tiered runs printed identical `app.llm.efficiency_report()` output:

```
{'endpoint': 'http://localhost:11434/v1', 'calls': 44, 'escalations': 0,
 'escalation_rate': 0.0, 'by_model': {'qwen3:4b': 44}}
```

- **Cases answered per model**: 44/55 cases (80%) went to a real model call,
  answered entirely by `qwen3:4b`; 11/55 (20%) were refused before any model
  was consulted (`model_used = "none (no model call)"` — out-of-scope or
  contentless questions, decided deterministically in `app/planner.py`
  before the first LLM call).
- **Escalation count and rate**: 0 escalations, 0/55 (0%), in both the
  samples=1 and samples=3 tiered runs. `qwen3:8b` was never invoked on this
  golden set.
- **Accuracy split escalated vs not**: not reported — `run_evals.py` only
  prints an escalated/non-escalated accuracy split when `esc_tot` is nonzero
  (see the `if esc_tot and plain_tot:` guard), and here `esc_tot == 0`, so
  the line never printed. All 44 model-answered cases were "not escalated,"
  at 100% accuracy (see the accuracy table above).
- **Tokens**: `efficiency_report()` does not report tokens in its returned
  dict (only `calls`, `escalations`, `escalation_rate`, `by_model`) and the
  eval CLI does not print anything else — so no aggregate token figure exists
  to report here. (Per-call `eval_count` is logged internally to
  `app.llm.USAGE` but never surfaced by the runner or the report.)

**Important gap found while producing the samples=3 run**: `evals/run_evals.py`
imports and calls `app.planner.plan_detailed` directly (see its `from
app.planner import plan_detailed` and `planner, label = plan_detailed,
MODELS["planner"]`). The self-consistency / confidence-ratio escalation path
described in the task (`plan_with_confidence`, which samples the planner
`confidence.samples` times and escalates when the agreement ratio is below
`FINANCE_ESCALATE_THRESHOLD`) lives in a *different* function that only
`app/api.py`'s `/ask` endpoint calls — the eval harness never calls it. That
is why the samples=1 and samples=3 tiered reports are identical: both made
exactly 44 model calls (not the ~3x expected if self-consistency sampling
ran), all to `qwen3:4b`, with 0 escalations either way. The escalation this
harness *does* exercise is the other trigger from the task description —
"validation failure after repair" inside `plan_detailed` itself — and on this
55-case golden set that path never fires either (the small model never fails
twice). So on the current golden set, with the current harness, the
escalation tier is untested by `make eval`/`run_evals.py`; it would only be
exercised by hitting `/ask` directly (or by wiring `run_evals.py` to call
`plan_with_confidence` instead).

## c) Reading the table

`qwen3:4b` is a reasonable default: it is the only one of the three raw
models with a clean 55/55 on this golden set, and it's roughly 3.3x faster
at p50 (1517ms) than `qwen3:8b` (2014ms) and about 2.6x the size of
`qwen3:1.7b` on disk for one more correct case. Honestly, though, the margins
here are thin and this is a 55-case set — a "100% vs 98%" difference is one
flipped case, not a statistically strong result. `qwen3:1.7b` is close: 54/55
(98%), missing only one grouping spec, while running roughly 3x faster at
p50 (458ms vs 1517ms) and at little more than half the disk size. If p50
latency mattered more than that one grouping case, 1.7b would be a completely
defensible choice, and it's worth someone's time to look at whether that
one miss is fixable with a better prompt rather than a bigger model. And
`qwen3:8b` is not better here — it actually scored *worse* than `qwen3:4b`
(54/55, missing a date-range case) while being both the largest model and by
far the slowest (max latency 29013ms, roughly 4x qwen3:4b's worst case and
10x its own p50). Nothing here demonstrates that jumping to 8B improves
accuracy; its only demonstrated value in this repo is as a fallback when the
4B model outright fails to produce valid JSON after a repair attempt, which
never happened on this golden set. The tiered configuration (4b with 8b as
an escalation safety net) is the right shape for production because it costs
nothing when the small model behaves and gives you a bigger model to fall
back on when it doesn't — but on this golden set specifically, the tier never
engaged, so the tiered numbers here are just the qwen3:4b numbers with an
unused safety net attached, not evidence that escalation itself helps. That
evidence would have to come from the self-consistency path, which (per the
gap noted above) this harness does not currently exercise.

## d) Commands and date

Run on 2026-09-05, against Ollama running locally (`http://localhost:11434/v1`),
models pulled via `ollama pull qwen3:1.7b|qwen3:4b|qwen3:8b`.

```
./.venv/bin/python evals/run_evals.py --model qwen3:1.7b --out evals/report-qwen3-1.7b.md
./.venv/bin/python evals/run_evals.py --model qwen3:4b   --out evals/report-qwen3-4b.md
./.venv/bin/python evals/run_evals.py --model qwen3:8b   --out evals/report-qwen3-8b.md

# tiered production config, escalation on, confidence.samples: 1 (committed default)
./.venv/bin/python evals/run_evals.py --out evals/report-tiered-qwen3-4b-8b.md

# tiered, confidence.samples temporarily set to 3 in config/models.yaml, then reverted
# (git diff config/models.yaml was empty afterward)
./.venv/bin/python evals/run_evals.py --out evals/report-tiered-qwen3-4b-8b-samples3.md
```

`--model` alone forces `FINANCE_ESCALATE=0` (see `run_evals.py`), so the
three raw-model runs above reflect that model alone, not the tiered
pipeline. The two tiered runs use no `--model`/`--escalate-model` override,
so they run the committed `config/models.yaml` roles as-is (planner/router/
narrator = `qwen3:4b`, escalate = `qwen3:8b`), with escalation on.

## e) Deployed (hosted) comparison — for context, not this table

The Render deployment does not run these Ollama models at all. It uses
`provider: gemini` against Google AI Studio's OpenAI-compatible endpoint,
with `planner`/`narrator`/`router` = `gemini-3.5-flash-lite` and `escalate`
= `gemini-3.6-flash` (see the `base:` fields in `config/models.yaml`). That
is a materially different, hosted-only setup and is not re-run here. The
older run against it is preserved at `evals/report-gemini-3.5-flash-lite.md`
(scored 47/49 on an earlier version of the golden set, with two failures
recorded — one a rate-limit error, one a refusal-case miss). It predates the
55-case golden set used above, so its bucket totals do not match the counts
in this document; it's included only as the prior evidence for the hosted
path, not as a like-for-like comparison.
