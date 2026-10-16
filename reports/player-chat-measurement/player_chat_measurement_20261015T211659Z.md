# Player chat streaming measurement

- Generated: `2026-10-15T21:16:59.297446+00:00`
- Report version: `2` (per-attempt retention; the historical version-1 reports are final-attempt-only and kept in `reports/player-chat-measurement/`)
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `8ff4bd94634ca3b07bd67a5d8b932e31148dfdc4`
- Request timeout: `30.0s`; wall-clock budget: `300.0s`
- Turns: 4 measured / 1 failed / 0 skipped of 5; attempts: 10 total, 6 failed, 0 timed out; model stream calls: 7

## Accounting

- Every attempt of a logical turn is retained with its elapsed time, retry backoff, error and known usage. Latency is split into the end-to-end user wait (all attempts + backoff) and the successful attempt's visible latency (its own first-visible text, not a pure provider/model-stream TTFT). Usage totals sum every known row, including the known rows of partial attempts; only the unreported remainder of a failed attempt is unknown and excluded (never counted as zero), so the known token and cost sums are a lower bound when any usage is unreported. A recorded-token cache share is not a lower bound: it is the fraction among reported tokens, and the overall share is unknown while usage is incomplete.
- Measurement retry policy: Measurement harness: model built with build_player_llm(timeout=..., max_retries=0); up to max_turn_attempts (live: 3) per logical turn, retrying only a transient provider-busy (HTTP 429/overloaded) or timeout failure with a fixed backoff; every attempt is recorded.
- Production retry policy: Production player chat (utils.model_downloader.get_llm): OpenAI SDK retries inside one call (LLM_MAX_RETRIES default 1, request timeout 60 s, stream-chunk timeout 30 s). Those SDK retries are invisible to and uncounted by this harness.

## Per-turn summary

| Turn | Intent | Status | Attempts | End-to-end first text (user wait) | Successful-attempt visible latency | Known cost | Usage |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | coaching_qa | error | 3 | n/a | n/a | $0.000209 | lower bound: 2 partial (known rows included), 1 unknown (no usage recorded) |
| 2 | coaching_qa | ok | 2 | 14.791 s | 10.631 s | $0.000168 | lower bound: 1 unknown (no usage recorded) |
| 3 | coaching_qa | ok | 1 | 17.508 s | 17.508 s | $0.000167 | reported |
| 4 | coaching_qa | ok | 2 | 13.201 s | 9.466 s | $0.000161 | lower bound: 1 unknown (no usage recorded) |
| 5 | coaching_qa | ok | 2 | 18.035 s | 14.348 s | $0.000075 | lower bound: 1 unknown (no usage recorded) |

## Per-attempt detail

| Turn | Attempt | Status | Backoff | Elapsed | First visible | First model chunk | Pre-stream | Input | Cached | Output | Cached share | Cost | Usage | Error |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 1 | error | 0.000 s | 14.051 s | 10.897 s | 10.262 s | 0.007 s | 1555 | 1280 | 60 | 82.3% | $0.000059 | partial | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 1 | 2 | error | 3.000 s | 0.233 s | n/a | n/a | 0.004 s | 0 | 0 | 0 | n/a | n/a | unknown | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 1 | 3 | error | 3.000 s | 12.016 s | 10.050 s | 9.354 s | 0.004 s | 1555 | 0 | 60 | 0.0% | $0.000151 | partial | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 2 | 1 | error | 0.000 s | 1.160 s | n/a | n/a | 0.029 s | 0 | 0 | 0 | n/a | n/a | unknown | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 2 | 2 | ok | 3.000 s | 16.486 s | 10.631 s | 8.291 s | 0.030 s | 1599 | 0 | 132 | 0.0% | $0.000168 | reported | - |
| 3 | 1 | ok | 0.000 s | 20.062 s | 17.508 s | 15.528 s | 0.029 s | 1748 | 0 | 55 | 0.0% | $0.000167 | reported | - |
| 4 | 1 | error | 0.000 s | 0.736 s | n/a | n/a | 0.034 s | 0 | 0 | 0 | n/a | n/a | unknown | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 4 | 2 | ok | 3.000 s | 32.673 s | 9.466 s | 8.284 s | 0.030 s | 3833 | 3072 | 205 | 80.1% | $0.000161 | reported | - |
| 5 | 1 | error | 0.000 s | 0.687 s | n/a | n/a | 0.031 s | 0 | 0 | 0 | n/a | n/a | unknown | OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Model busy, retry later', 'type': 'invalid_request_error', 'param': None, 'code': 'engine_overloaded'}} |
| 5 | 2 | ok | 3.000 s | 21.249 s | 14.348 s | 11.008 s | 0.031 s | 1992 | 1792 | 140 | 90.0% | $0.000075 | reported | - |

## Aggregate

- Median user-visible first text (end-to-end, all attempts + backoff): **16.149 s** (n=4)
- Median successful-attempt visible latency: **12.489 s**
- Median first model chunk: 9.650 s
- Median pre-stream code time: 0.030 s
- Cached input share from turn 2: **53.0%** (4864/9172 input tokens from turn 2 onward; share among recorded tokens; overall share unknown — some usage unreported)
- Known cost across all attempts: **$0.000780** ($0.000156 per turn; known rows from 2 partial attempt(s) included; lower bound — 4 attempt(s) with unreported usage unknown; complete: False)
- Median user-visible first text within 2.0s: **UNMET**
- Median successful-attempt visible latency within 2.0s: **UNMET**

## Acceptance criteria

- Median time to first visible text ≤ 2.0s: **UNMET** (median 16.149 s)
- Nonzero recorded cache reuse on logical turn 2 in a full 5-turn session: **PARTIAL / NOT DEMONSTRATED** (4/5 turns measured; turn 2 recorded 0/1599 cached/input tokens, usage complete: False; aggregate share from turn 2 onward 53.0%)

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
