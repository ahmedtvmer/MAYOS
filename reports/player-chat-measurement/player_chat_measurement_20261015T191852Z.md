# Player chat streaming measurement

- Generated: `2026-10-15T19:18:52.902204+00:00`
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `8ff4bd94634ca3b07bd67a5d8b932e31148dfdc4`
- Request timeout: `30.0s`; wall-clock budget: `240.0s`
- Samples: 4 measured turns of 5 (0 deterministic, 1 failed, 0 skipped); model stream calls: 5

## Per-turn measurements

| Turn | Intent | Status | First visible text | First model chunk | Pre-stream code | Input | Cached | Output | Cached share | Cost |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | coaching_qa | ok | 9.289 s | 8.621 s | 0.009 s | 3310 | 1280 | 223 | 38.7% | $0.000246 |
| 2 | coaching_qa | ok | 10.110 s | 9.128 s | 0.047 s | 1749 | 1280 | 178 | 73.2% | $0.000097 |
| 3 | coaching_qa | ok | 8.942 s | 8.485 s | 0.042 s | 1944 | 1792 | 166 | 92.2% | $0.000076 |
| 4 | coaching_qa | ok | 10.728 s | 9.162 s | 0.034 s | 2123 | 1280 | 210 | 60.3% | $0.000137 |
| 5 | coaching_qa | error | 0.773 s | 0.760 s | 0.035 s | 0 | 0 | 0 | n/a | n/a |

## Aggregate

- Median first visible text: **9.699 s** (n=4)
- Median first model chunk: 8.875 s
- Median pre-stream code time: 0.038 s
- Cached input share from turn 2: **74.8%** (5632/9126 input tokens)
- Mean cost per turn: **$0.000139** (total $0.000556)
- Median first visible text within 2.0s: **UNMET**

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
