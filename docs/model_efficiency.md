# Model efficiency

Evidence for the model-choice bonus: which model to run the finance Q&A
planner on, and whether the 4b→8b escalation tier is pulling its weight.
All numbers below are copied verbatim from the `evals/report-*.md` files
this document links to — nothing here is rounded further or invented.

Golden set: `evals/golden.yaml`, **57 cases** (grew from 55 after adding two
amount-filter cases — an absolute-month "1 lakh in May" count case and a
"50k last month" sum case — alongside a deterministic dataset-direction fix
in the planner). Ollama models `qwen3:1.7b`, `qwen3:4b`, `qwen3:8b`, all
pulled locally. Config: `config/models.yaml` (`provider: ollama`; committed
default roles: `planner` = `qwen3:1.7b`, `narrator`/`router` = `qwen3:4b`,
`escalate` = `qwen3:8b`). The comparison rows below run each candidate model
explicitly via `--model`/`--escalate-model`, independent of whatever the
committed default happens to be at the time.

Every non-stub run in this document goes through `app.planner.plan_with_confidence`
— the same function `/ask` calls — via `evals/run_evals.py`, not the raw
per-model `plan_detailed`. That is what makes the escalation and confidence
numbers below real evidence about the production path, not a harness-only
approximation of it.

## Golden set composition

Tag counts (a case can carry more than one tag, so these do not sum to 57):

| tag | count |
|---|---:|
| aggregate | 8 |
| ambiguous | 3 |
| category | 11 |
| channel | 1 |
| dates | 18 |
| filter | 14 |
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
| qwen3:1.7b (raw, escalation off) | 57/57 (100%) | 11/11 (100%) | 467ms | 736ms | 2.0B / 1.36GB |
| qwen3:4b (raw, escalation off) | 57/57 (100%) | 11/11 (100%) | 1378ms | 2480ms | 4.0B / 2.5GB |
| qwen3:8b (raw, escalation off) — **55-case run, before the lakh/month fix** | 54/55 (98%) | 11/11 (100%) | 2014ms | 29013ms | 8.2B / 5.23GB |
| tiered 4b→8b (confidence.samples=1) | 57/57 (100%) | 11/11 (100%) | 1591ms | 16330ms | 4b + 8b co-resident |
| tiered 4b→8b (confidence.samples=3) | 57/57 (100%) | 11/11 (100%) | 4399ms | 32996ms | 4b + 8b co-resident |

`qwen3:8b` was not re-run on the 57-case set (see "Deck numbers" note in the
task — 1.7b and 8b were left alone deliberately to bound the number of
serial Ollama runs). `qwen3:1.7b`'s row above already reflects the 57-case
set: it was re-run as part of the same change that added the two golden
cases and the dataset-direction fix (commit `f8fdf64`), and is not stale.

Per-bucket accuracy (correct/total), from the 57-case reports (`qwen3:1.7b`,
`qwen3:4b`, and both tiered configs all scored 100% in every bucket, so
there is nothing to break out per-bucket for them beyond the totals above):

| bucket | total (57-case) | qwen3:1.7b | qwen3:4b | tiered (samples 1) | tiered (samples 3) |
|---|---:|---:|---:|---:|---:|
| aggregate | 8 | 8/8 | 8/8 | 8/8 | 8/8 |
| ambiguous | 3 | 3/3 | 3/3 | 3/3 | 3/3 |
| category | 11 | 11/11 | 11/11 | 11/11 | 11/11 |
| channel | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| dates | 18 | 18/18 | 18/18 | 18/18 | 18/18 |
| filter | 14 | 14/14 | 14/14 | 14/14 | 14/14 |
| grouped | 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| metric | 4 | 4/4 | 4/4 | 4/4 | 4/4 |
| multiturn | 5 | 5/5 | 5/5 | 5/5 | 5/5 |
| refusal | 11 | 11/11 | 11/11 | 11/11 | 11/11 |
| vendor | 2 | 2/2 | 2/2 | 2/2 | 2/2 |

`qwen3:8b`'s one miss is preserved here for context, on its own (older,
55-case, pre-fix) bucket totals — it is not comparable cell-for-cell with
the 57-case table above because the golden set's `dates` and `filter`
buckets grew by 2 cases each since that run:

| bucket (55-case, pre-fix) | total | qwen3:8b |
|---|---:|---:|
| dates | 16 | 15/16 |
| filter | 12 | 12/12 |
| (all other buckets) | — | clean |

- qwen3:8b, `dt_absolute_range` — spec mismatch: wanted
  `{'dataset': 'payouts', 'metric': 'sum_amount', 'date_range': {'kind':
  'absolute', 'start': '2026-01-01', 'end': '2026-03-31'}}`.

## b) Efficiency report — tiered runs

The two tiered runs are no longer identical, because the harness now calls
`plan_with_confidence` — self-consistency sampling is real when
`confidence.samples > 1`, and it changed the outcome:

```
# samples=1 (committed default): app.llm.efficiency_report()
{'endpoint': 'http://localhost:11434/v1', 'calls': 46, 'escalations': 0,
 'escalation_rate': 0.0, 'by_model': {'qwen3:4b': 46}}

# samples=3: two of the 46 model-answered cases disagreed with themselves
# across 3 samples and escalated to qwen3:8b
```

- **Cases answered per model**: 46/57 cases (81%) went to a real model call;
  11/57 (19%) were refused before any model was consulted
  (`model_used = "none (no model call)"` — out-of-scope or contentless
  questions, decided deterministically in `app/planner.py` before the first
  LLM call). Of the 46 model-answered cases: at samples=1, all 46 were
  answered by `qwen3:4b` alone; at samples=3, 44 were answered by `qwen3:4b`
  and 2 escalated to `qwen3:8b`.
- **Escalation count and rate**: **0/57 (0%) at samples=1, 2/57 (4%) at
  samples=3.** This is the harness actually exercising the self-consistency
  escalation trigger for the first time — at samples=1 there is nothing to
  disagree with (a single sample always "agrees" with itself), so escalation
  can only fire once `confidence.samples` is raised enough for the planner to
  sample itself more than once and occasionally land on two different specs.
- **Accuracy split escalated vs not** (samples=3 only — this line only
  prints when at least one case escalated): escalated 100% (2 cases), not
  escalated 100% (55 cases). The bigger model didn't need to be *more*
  accurate than the small one here to justify the tier — it just needed to
  not regress the 2 cases it caught, and it didn't.
- **Confidence distribution**: both runs report `high: 57/57 (100%)` — this
  is *not* a contradiction with a nonzero escalation rate in the samples=3
  run. Look at `plan_with_confidence` (`app/planner.py`): the label a case
  ends up with is the label of the *result actually returned*, not the
  disagreement score that triggered escalation. When self-consistency
  disagreement drops the agreement score below the escalation threshold
  (`FINANCE_ESCALATE_THRESHOLD`, default 0.6), the function re-plans once on
  `qwen3:8b` and returns that candidate's own `PlanResult`, whose confidence
  is hard-coded to `"high"` for any non-planner role. So the confidence badge
  a user would see on those 2 escalated answers is "high" — the low-agreement
  signal that caused the escalation is consumed internally and never
  surfaces as a "medium"/"low" label on the final answer. That's a real
  finding about the confidence badge, not a reporting bug in the harness: the
  badge answers "how much do I trust the answer you got", and after
  escalating to a bigger model and getting one clean spec back, "high" is an
  arguably honest answer to that question — but it does mean the confidence
  distribution table alone cannot be used to spot how often self-consistency
  disagreed; the escalation-rate line is the number that carries that signal.
- **Tokens**: `efficiency_report()` does not report tokens in its returned
  dict (only `calls`, `escalations`, `escalation_rate`, `by_model`) and the
  eval CLI does not print anything else — so no aggregate token figure exists
  to report here. (Per-call `eval_count` is logged internally to
  `app.llm.USAGE` but never surfaced by the runner or the report.)

**Previous gap, now closed**: earlier versions of this document reported that
`evals/run_evals.py` called `app.planner.plan_detailed` directly, bypassing
`plan_with_confidence` entirely — so the self-consistency / confidence-ratio
escalation path that `/ask` actually uses was untested by the harness, and
the 0%-escalation numbers on record could not distinguish "the tier never
needs to fire" from "the tier was never wired into eval". That gap is closed:
the harness now calls `plan_with_confidence` (see `evals/run_evals.py`'s
`from app.planner import plan_with_confidence` and its `--samples` flag), and
raising `confidence.samples` from 1 to 3 measurably changed the outcome —
2/57 escalations instead of 0/57, using the exact function `/ask` calls, with
no code path unique to the harness. Escalation is demonstrated to work; it is
also demonstrated to be rare (4% even at samples=3, 0% at the committed
default of samples=1) and, on this golden set, harmless to accuracy either
way.

## c) Reading the table

`qwen3:1.7b` and `qwen3:4b` are now tied at 57/57 (100%) on the current
golden set — the dataset-direction fix that shipped alongside the two new
golden cases (commit `f8fdf64`) closed 1.7b's only miss (a "how many
TRANSACTIONS in each category" question read as payouts), and that fix is
in `app/planner.py` itself, not a golden-set patch, so it benefits every
model. With accuracy tied, `qwen3:1.7b` wins on latency by a wide margin:
p50 467ms vs 1378ms for `qwen3:4b`, roughly 3x faster, at little more than
half the disk size — which is why the committed default planner is now
`qwen3:1.7b` (see `config/models.yaml`). `qwen3:8b`'s number on record is
from before that fix (54/55 on the old 55-case set, missing a date-range
case) and was deliberately not re-run for this document; nothing here
suggests it would still be the worst performer if it were, but nothing here
proves otherwise either. What the tiered numbers add on top of that: the
production configuration (small planner, big model as an escalation
fallback) now has *measured* evidence that the fallback engages under
realistic self-consistency disagreement (2/57 at samples=3) and does not
hurt accuracy when it does (100% on the escalated cases). At the committed
default of `confidence.samples: 1`, escalation via self-consistency cannot
fire at all (see above), so the tiered pipeline's day-to-day behavior is
"run `qwen3:1.7b`-or-`qwen3:4b` alone, unless the small model fails validation
twice" — the repair-loop escalation trigger, which remains untriggered on
this golden set at either sample count, same as before. Raising
`confidence.samples` to 3 costs roughly 3x the model calls for the cases
that get sampled multiple times (visible in the latency jump: p50 1591ms
at samples=1 vs 4399ms at samples=3, max 16330ms vs 32996ms) in exchange for
a real, if small, chance of catching a shaky small-model answer before it
reaches the user — a genuine accuracy/latency trade a team could tune
`confidence.samples` for, now that the number on the other side of that
trade is measured rather than assumed.

## d) Commands and date

Run on 2026-09-05, against Ollama running locally (`http://localhost:11434/v1`),
models pulled via `ollama pull qwen3:1.7b|qwen3:4b|qwen3:8b`.

```
./.venv/bin/python evals/run_evals.py --model qwen3:4b --out evals/report-qwen3-4b.md
# qwen3:1.7b and qwen3:8b raw reports were not re-run for this refresh (see
# the "before the lakh/month fix" note on the qwen3:8b row above); their
# existing evals/report-qwen3-1.7b.md and evals/report-qwen3-8b.md are used
# as-is.

# tiered, explicit 4b planner / 8b escalate, confidence.samples=1 (matches
# the report filename; the committed config/models.yaml default planner is
# qwen3:1.7b, not qwen3:4b, as of commit f8fdf64)
./.venv/bin/python evals/run_evals.py --model qwen3:4b --escalate-model qwen3:8b \
    --out evals/report-tiered-qwen3-4b-8b.md

# same tiered config, confidence.samples overridden to 3 for this run only
./.venv/bin/python evals/run_evals.py --model qwen3:4b --escalate-model qwen3:8b \
    --samples 3 --out evals/report-tiered-qwen3-4b-8b-samples3.md
```

`--model` alone forces `FINANCE_ESCALATE=0` (see `run_evals.py`), so the
`qwen3:4b`-only run above reflects that model alone, not the tiered
pipeline. Both tiered runs pass `--escalate-model qwen3:8b` explicitly (an
"explicit tiered comparison", per the harness's own `--help` text) so the
comparison stays qwen3:4b→qwen3:8b regardless of whatever the committed
`config/models.yaml` planner default is at run time. `--samples N` is a new
flag on the harness that sets `FINANCE_CONFIDENCE_SAMPLES`, which
`app.planner.confidence_samples()` reads in preference to
`config/models.yaml`'s `confidence.samples` — it does not touch the
committed file (confirmed via `git diff config/models.yaml`, which is empty
after every run in this document).

## e) Deployed (hosted) comparison — for context, not this table

The Render deployment does not run these Ollama models at all. It uses
`provider: gemini` against Google AI Studio's OpenAI-compatible endpoint,
with `planner`/`narrator`/`router` = `gemini-3.5-flash-lite` and `escalate`
= `gemini-3.6-flash` (see the `base:` fields in `config/models.yaml`). That
is a materially different, hosted-only setup and is not re-run here. The
older run against it is preserved at `evals/report-gemini-3.5-flash-lite.md`
(scored 47/49 on an earlier version of the golden set, with two failures
recorded — one a rate-limit error, one a refusal-case miss). It predates
both the 55-case and 57-case golden sets used above, so its bucket totals
do not match the counts in this document; it's included only as prior
evidence for the hosted path, not as a like-for-like comparison.
