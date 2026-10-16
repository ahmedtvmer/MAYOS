# Player chat streaming measurement

- Generated: `2026-10-15T19:16:12.485006+00:00`
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `8ff4bd94634ca3b07bd67a5d8b932e31148dfdc4`
- Request timeout: `30.0s`; wall-clock budget: `240.0s`
- Samples: 2 measured turns of 5 (0 deterministic, 3 failed, 0 skipped); model stream calls: 3

## Per-turn measurements

| Turn | Intent | Status | First visible text | First model chunk | Pre-stream code | Input | Cached | Output | Cached share | Cost |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | coaching_qa | ok | 11.241 s | 10.852 s | 0.010 s | 3310 | 1536 | 223 | 46.4% | $0.000227 |
| 2 | coaching_qa | error | 0.772 s | 0.752 s | 0.100 s | 0 | 0 | 0 | n/a | n/a |
| 3 | coaching_qa | ok | 7.907 s | 7.369 s | 0.075 s | 1778 | 0 | 122 | 0.0% | $0.000182 |
| 4 | coaching_qa | error | 30.736 s | 30.728 s | 0.047 s | 0 | 0 | 0 | n/a | n/a |
| 5 | coaching_qa | error | 0.300 s | 0.295 s | 0.040 s | 0 | 0 | 0 | n/a | n/a |

## Aggregate

- Median first visible text: **9.574 s** (n=2)
- Median first model chunk: 9.111 s
- Median pre-stream code time: 0.043 s
- Cached input share from turn 2: **0.0%** (1536/5088 input tokens)
- Mean cost per turn: **$0.000205** (total $0.000409)
- Median first visible text within 2.0s: **UNMET**

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
