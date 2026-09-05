### Accuracy — planner `gemini-3.5-flash-lite`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 45 | 49 | 92% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 2 | 3 | 67% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 8 | 9 | 89% |
| grouped | 8 | 10 | 80% |
| metric | 3 | 4 | 75% |
| multiturn | 5 | 5 | 100% |
| refusal | 8 | 8 | 100% |
| vendor | 1 | 2 | 50% |

planner latency: p50 2785ms, max 9745ms

### Failures

- `grp_by_channel` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'group_by': ['channel']}
- `grp_count_by_category` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'count', 'group_by': ['category']}
- `flt_vendor_dmart` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'filters': {'counterparty': 'DMART AVENUE SUPERMARTS'}}
- `amb_unknown_category` — answered when it should have declined
