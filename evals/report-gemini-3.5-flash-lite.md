### Accuracy — planner `gemini-3.5-flash-lite`

| bucket | correct | total | % |
|---|---:|---:|---:|
| ALL | 47 | 49 | 96% |
| aggregate | 8 | 8 | 100% |
| ambiguous | 2 | 3 | 67% |
| category | 8 | 8 | 100% |
| channel | 1 | 1 | 100% |
| dates | 14 | 15 | 93% |
| filter | 9 | 9 | 100% |
| grouped | 10 | 10 | 100% |
| metric | 4 | 4 | 100% |
| multiturn | 5 | 5 | 100% |
| refusal | 8 | 8 | 100% |
| vendor | 2 | 2 | 100% |

planner latency: p50 1413ms, max 34646ms

### Failures

- `dt_yesterday` — planner error: ModelUnavailable: Rate limited by https://generativelanguage.googleapis.com/v1beta/openai. Free tiers throttle quickly -- an eval run is ~150 calls. Wait, or lower confidence.samples in config/models.yaml.
- `amb_unknown_category` — answered when it should have declined
