# Player chat streaming measurement

- Generated: `2026-10-17T13:30:33.847993+00:00`
- Report version: `2` (per-attempt retention; the historical version-1 reports are final-attempt-only and kept in `reports/player-chat-measurement/`)
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `0a78b72680f733cad25423167b7ea76408be8822`
- Request timeout: `60.0s`; wall-clock budget: `300.0s`
- Turns: 5 measured / 0 failed / 0 skipped of 5; attempts: 5 total, 0 failed, 0 timed out; model stream calls: 6

## Accounting

- Every attempt of a logical turn is retained with its elapsed time, retry backoff, error and known usage. Latency is split into the end-to-end user wait (all attempts + backoff) and the successful attempt's visible latency (its own first-visible text, not a pure provider/model-stream TTFT). Usage totals sum every known row, including the known rows of partial attempts; only the unreported remainder of a failed attempt is unknown and excluded (never counted as zero), so the known token and cost sums are a lower bound when any usage is unreported. A recorded-token cache share is not a lower bound: it is the fraction among reported tokens, and the overall share is unknown while usage is incomplete.
- Measurement retry policy: Measurement harness: model built with build_player_llm(timeout=..., max_retries=0); up to max_turn_attempts (live: 3) per logical turn, retrying only a transient provider-busy (HTTP 429/overloaded) or timeout failure with a fixed backoff; every attempt is recorded.
- Production retry policy: Production player chat (utils.model_downloader.get_llm): OpenAI SDK retries inside one call (LLM_MAX_RETRIES default 1, request timeout 60 s, stream-chunk timeout 30 s). Those SDK retries are invisible to and uncounted by this harness.

## Per-turn summary

| Turn | Intent | Status | Attempts | End-to-end first text (user wait) | Successful-attempt visible latency | Known cost | Usage |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | coaching_qa | ok | 1 | 61.679 s | 61.679 s | $0.000230 | reported |
| 2 | coaching_qa | ok | 1 | 2.552 s | 2.552 s | $0.000083 | reported |
| 3 | coaching_qa | ok | 1 | 62.270 s | 62.270 s | $0.000075 | reported |
| 4 | coaching_qa | ok | 1 | 1.545 s | 1.545 s | $0.000083 | reported |
| 5 | coaching_qa | ok | 1 | 2.714 s | 2.714 s | $0.000076 | reported |

## Per-attempt detail

| Turn | Attempt | Status | Backoff | Elapsed | First visible | First model chunk | Pre-stream | Input | Cached | Output | Cached share | Cost | Usage | Error |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 1 | ok | 0.000 s | 128.377 s | 61.679 s | 61.565 s | 0.008 s | 3312 | 1536 | 236 | 46.4% | $0.000230 | reported | - |
| 2 | 1 | ok | 0.000 s | 5.782 s | 2.552 s | 2.374 s | 0.046 s | 1763 | 1536 | 192 | 87.1% | $0.000083 | reported | - |
| 3 | 1 | ok | 0.000 s | 65.681 s | 62.270 s | 61.971 s | 0.035 s | 1972 | 1792 | 145 | 90.9% | $0.000075 | reported | - |
| 4 | 1 | ok | 0.000 s | 8.401 s | 1.545 s | 1.045 s | 0.032 s | 2130 | 2048 | 214 | 96.2% | $0.000083 | reported | - |
| 5 | 1 | ok | 0.000 s | 8.048 s | 2.714 s | 1.735 s | 0.034 s | 2360 | 2304 | 164 | 97.6% | $0.000076 | reported | - |

## Aggregate

- Median user-visible first text (end-to-end, all attempts + backoff): **2.714 s** (n=5)
- Median successful-attempt visible latency: **2.714 s**
- Median first model chunk: 2.374 s
- Median pre-stream code time: 0.034 s
- Cached input share from turn 2: **93.4%** (7680/8225 input tokens from turn 2 onward; share among recorded tokens)
- Known cost across all attempts: **$0.000546** ($0.000109 per turn; known rows from 0 partial attempt(s) included; lower bound — 0 attempt(s) with unreported usage unknown; complete: True)
- Median user-visible first text within 2.0s: **UNMET**
- Median successful-attempt visible latency within 2.0s: **UNMET**

## Acceptance criteria

- Median time to first visible text ≤ 2.0s: **UNMET** (median 2.714 s)
- Nonzero recorded cache reuse on logical turn 2 in a full 5-turn session: **MET** (5/5 turns measured; turn 2 recorded 1536/1763 cached/input tokens, usage complete: True; aggregate share from turn 2 onward 93.4%)

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
