### Accuracy — planner `qwen3:4b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 48 | 49 | 98% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 2 | 3 | 67% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 15 | 15 | 100% |
| filter | 9 | 9 | 100% |
| grouped | 10 | 10 | 100% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 8 | 8 | 100% |
| vendor | 2 | 2 | 100% |

planner latency: p50 1388ms, max 2468ms

### Failures

- `amb_unknown_category` — answered when it should have declined
