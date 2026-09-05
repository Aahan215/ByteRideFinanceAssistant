### Accuracy — planner `gemini-3.5-flash-lite`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 43 | 49 | 88% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 2 | 3 | 67% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 7 | 9 | 78% |
| grouped | 8 | 10 | 80% |
| metric | 3 | 4 | 75% |
| multiturn | 4 | 5 | 80% |
| refusal | 8 | 8 | 100% |
| vendor | 0 | 2 | 0% |

planner latency: p50 2834ms, max 24950ms

### Failures

- `grp_by_channel` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'group_by': ['channel']}
- `grp_count_by_category` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'count', 'group_by': ['category']}
- `flt_vendor_zomato` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'filters': {'counterparty': 'ZOMATO HYPERPURE'}}
- `flt_vendor_dmart` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'filters': {'counterparty': 'DMART AVENUE SUPERMARTS'}}
- `amb_unknown_category` — answered when it should have declined
- `mt_vendor_last_month` — spec mismatch: wanted {'dataset': 'payouts', 'filters': {'counterparty': 'ZOMATO HYPERPURE'}, 'date_range': {'kind': 'relative', 'unit': 'month', 'offset': -1}}
