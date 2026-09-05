### Accuracy — planner `qwen3:1.7b`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 57 | 57 | 100% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 3 | 3 | 100% |
| category | 11 | 11 | 100% |
| channel | 1 | 1 | 100% |
| dates | 18 | 18 | 100% |
| filter | 14 | 14 | 100% |
| grouped | 10 | 10 | 100% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 11 | 11 | 100% |
| vendor | 2 | 2 | 100% |

planner latency: p50 490ms, max 927ms

### Model usage

| model | cases | share | accuracy |
|---|---:|---:|---:|
| qwen3:1.7b | 46 | 81% | 100% |
| none (no model call) | 11 | 19% | 100% |

escalation rate: 0/57 (0%)

### Confidence distribution

| confidence | cases | share |
|---|---:|---:|
| high | 57 | 100% |
