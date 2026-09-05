### Accuracy — planner `qwen3:8b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 54 | 55 | 98% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 3 | 3 | 100% |
| category | 11 | 11 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 16 | 94% |
| filter | 12 | 12 | 100% |
| grouped | 10 | 10 | 100% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 11 | 11 | 100% |
| vendor | 2 | 2 | 100% |

planner latency: p50 2014ms, max 29013ms

### Failures

- `dt_absolute_range` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'date_range': {'kind': 'absolute', 'start': '2026-01-01', 'end': '2026-03-31'}}

### Model usage

| model | cases | share | accuracy |
|---|---:|---:|---:|
| qwen3:8b | 44 | 80% | 98% |
| none (no model call) | 11 | 20% | 100% |

escalation rate: 0/55 (0%)
