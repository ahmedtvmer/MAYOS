# Player chat streaming measurement

- Generated: `2026-10-15T19:24:46.143698+00:00`
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `8ff4bd94634ca3b07bd67a5d8b932e31148dfdc4`
- Request timeout: `30.0s`; wall-clock budget: `300.0s`
- Samples: 5 measured turns of 5 (0 deterministic, 0 failed, 0 skipped); model stream calls: 7

## Per-turn measurements

| Turn | Intent | Status | Attempts | First visible text | First model chunk | Pre-stream code | Input | Cached | Output | Cached share | Cost |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | coaching_qa | ok | 1 | 6.501 s | 5.972 s | 0.009 s | 3310 | 1280 | 229 | 38.7% | $0.000247 |
| 2 | coaching_qa | ok | 1 | 11.614 s | 10.017 s | 0.059 s | 1755 | 1536 | 191 | 87.5% | $0.000082 |
| 3 | coaching_qa | ok | 2 | 9.740 s | 8.373 s | 0.035 s | 1963 | 1792 | 112 | 91.3% | $0.000068 |
| 4 | coaching_qa | ok | 1 | 9.685 s | 9.462 s | 0.025 s | 4377 | 2048 | 212 | 46.8% | $0.000285 |
| 5 | coaching_qa | ok | 1 | 8.519 s | 7.432 s | 0.034 s | 2270 | 2048 | 123 | 90.2% | $0.000079 |

## Aggregate

- Median first visible text: **9.685 s** (n=5)
- Median first model chunk: 8.373 s
- Median pre-stream code time: 0.034 s
- Cached input share from turn 2: **71.6%** (8704/13675 input tokens)
- Mean cost per turn: **$0.000152** (total $0.000760)
- Median first visible text within 2.0s: **UNMET**

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
