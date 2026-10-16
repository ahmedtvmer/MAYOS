# Player chat streaming measurement

- Generated: `2026-10-15T19:20:36.593038+00:00`
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `8ff4bd94634ca3b07bd67a5d8b932e31148dfdc4`
- Request timeout: `30.0s`; wall-clock budget: `240.0s`
- Samples: 2 measured turns of 5 (0 deterministic, 3 failed, 0 skipped); model stream calls: 4

## Per-turn measurements

| Turn | Intent | Status | First visible text | First model chunk | Pre-stream code | Input | Cached | Output | Cached share | Cost |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | coaching_qa | error | 11.592 s | 11.300 s | 0.012 s | 1555 | 1280 | 60 | 82.3% | $0.000059 |
| 2 | coaching_qa | error | 0.354 s | 0.348 s | 0.098 s | 0 | 0 | 0 | n/a | n/a |
| 3 | coaching_qa | ok | 13.100 s | 12.377 s | 0.085 s | 1628 | 1536 | 43 | 94.3% | $0.000044 |
| 4 | coaching_qa | ok | 10.270 s | 10.110 s | 0.040 s | 3562 | 2816 | 163 | 79.1% | $0.000147 |
| 5 | coaching_qa | error | 0.741 s | 0.731 s | 0.058 s | 0 | 0 | 0 | n/a | n/a |

## Aggregate

- Median first visible text: **11.685 s** (n=2)
- Median first model chunk: 11.243 s
- Median pre-stream code time: 0.062 s
- Cached input share from turn 2: **83.9%** (5632/6745 input tokens)
- Mean cost per turn: **$0.000083** (total $0.000249)
- Median first visible text within 2.0s: **UNMET**

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
