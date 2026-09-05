### Accuracy — planner `qwen3:4b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 46 | 49 | 94% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 2 | 3 | 67% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 9 | 9 | 100% |
| grouped | 9 | 10 | 90% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 7 | 8 | 88% |
| vendor | 2 | 2 | 100% |

planner latency: p50 1456ms, max 2690ms

### Failures

- `grp_by_channel` — spec mismatch: wanted any of [{'dataset': 'payouts', 'metric': 'sum_amount', 'group_by': ['channel']}, {'dataset': 'payouts', 'metric': 'count', 'group_by': ['channel']}]
- `ref_reconciliation` — answered when it should have declined
- `amb_unknown_category` — answered when it should have declined
