### Accuracy — planner `gemini-3.5-flash-lite`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 48 | 49 | 98% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 3 | 3 | 100% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 8 | 9 | 89% |
| grouped | 10 | 10 | 100% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 8 | 8 | 100% |
| vendor | 1 | 2 | 50% |

planner latency: p50 2064ms, max 34743ms

### Failures

- `flt_vendor_dmart` — spec mismatch: wanted {'dataset': 'payouts', 'metric': 'sum_amount', 'filters': {'counterparty': 'DMART AVENUE SUPERMARTS'}}
