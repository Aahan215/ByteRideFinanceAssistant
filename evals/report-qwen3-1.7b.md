### Accuracy — planner `qwen3:1.7b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 54 | 55 | 98% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 3 | 3 | 100% |
| category | 11 | 11 | 100% |
| channel | 1 | 1 | 100% |
| dates | 16 | 16 | 100% |
| filter | 12 | 12 | 100% |
| grouped | 9 | 10 | 90% |
| metric | 3 | 4 | 75% |
| multiturn | 5 | 5 | 100% |
| refusal | 11 | 11 | 100% |
| vendor | 2 | 2 | 100% |

planner latency: p50 458ms, max 3546ms

### Failures

- `grp_count_by_category` — spec mismatch: wanted {'dataset': 'transactions', 'metric': 'count', 'group_by': ['category']}

### Model usage

| model | cases | share | accuracy |
|---|---:|---:|---:|
| qwen3:1.7b | 44 | 80% | 98% |
| none (no model call) | 11 | 20% | 100% |

escalation rate: 0/55 (0%)
