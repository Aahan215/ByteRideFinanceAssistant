### Accuracy — planner `qwen3:4b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 47 | 49 | 96% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 3 | 3 | 100% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 8 | 9 | 89% |
| grouped | 9 | 10 | 90% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 8 | 8 | 100% |
| vendor | 1 | 2 | 50% |

planner latency: p50 1372ms, max 2368ms

### Failures

- `grp_by_channel` — spec mismatch: wanted any of [{'dataset': 'payouts', 'metric': 'sum_amount', 'group_by': ['channel']}, {'dataset': 'payouts', 'metric': 'count', 'group_by': ['channel']}]
- `flt_vendor_dmart` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'filters': {'counterparty': 'DMART AVENUE SUPERMARTS'}}
