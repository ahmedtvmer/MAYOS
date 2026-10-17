# Player chat streaming measurement

- Generated: `2026-10-17T20:56:18.962382+00:00`
- Report version: `3` (per-attempt retention; the historical version-1 reports are final-attempt-only and kept in `reports/player-chat-measurement/`)
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `2a2fdd9c2d7687918cc68ad3586b93bc859287f2`
- Request timeout: `60.0s`; wall-clock budget: `300.0s`
- First-token deadline: `6.0s`; total attempts per model call: `2`
- Turns: 5 measured / 0 failed / 0 skipped of 5; attempts: 5 total, 0 failed, 0 timed out; first-token deadline retries: 0; model stream attempts: 7

## Accounting

- Every attempt of a logical turn is retained with its elapsed time, retry backoff, error and known usage. Latency is split into the end-to-end user wait (all attempts + backoff) and the successful attempt's visible latency (its own first-visible text, not a pure provider/model-stream TTFT). Usage totals sum every known row, including the known rows of partial attempts; only the unreported remainder of a failed attempt is unknown and excluded (never counted as zero), so the known token and cost sums are a lower bound when any usage is unreported. A recorded-token cache share is not a lower bound: it is the fraction among reported tokens, and the overall share is unknown while usage is incomplete.
- Measurement retry policy: Measurement harness: model built with build_player_llm(timeout=..., max_retries=0); up to max_turn_attempts (live: 3) per logical turn, retrying only a transient provider-busy (HTTP 429/overloaded) or timeout failure with a fixed backoff; every attempt is recorded.
- Production retry policy: Production player chat (utils.model_downloader.get_llm): first-token deadline LLM_FIRST_TOKEN_TIMEOUT (default 6 s) retries one model call up to LLM_FIRST_TOKEN_MAX_ATTEMPTS total attempts (default 2, maximum 5); this harness records each deadline retry. OpenAI SDK retries remain inside each call (LLM_MAX_RETRIES default 1), with request timeout 60 s and later-chunk timeout 30 s.

## Per-turn summary

| Turn | Intent | Status | Attempts | End-to-end first text (user wait) | Successful-attempt visible latency | Known cost | Usage |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | coaching_qa | ok | 1 | 2.304 s | 2.304 s | $0.000245 | reported |
| 2 | coaching_qa | ok | 1 | 2.889 s | 2.889 s | $0.000088 | reported |
| 3 | coaching_qa | ok | 1 | 2.305 s | 2.305 s | $0.000193 | reported |
| 4 | coaching_qa | ok | 1 | 1.324 s | 1.324 s | $0.000147 | reported |
| 5 | coaching_qa | ok | 1 | 2.435 s | 2.435 s | $0.000094 | reported |

## Per-attempt detail

| Turn | Attempt | Status | Backoff | Elapsed | First visible | First model chunk | Model call attempts | Pre-stream | Input | Cached | Output | Cached share | Cost | Usage | Error |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 1 | ok | 0.000 s | 21.997 s | 2.304 s | 2.139 s | 1: first chunk 2.125 s (3.271 s), 2: first chunk 2.044 s (18.710 s) | 0.014 s | 3494 | 1536 | 226 | 44.0% | $0.000245 | reported | - |
| 2 | 1 | ok | 0.000 s | 8.907 s | 2.889 s | 1.719 s | 1: first chunk 1.681 s (8.868 s) | 0.038 s | 1845 | 1536 | 181 | 83.3% | $0.000088 | reported | - |
| 3 | 1 | ok | 0.000 s | 3.169 s | 2.305 s | 1.265 s | 1: first chunk 1.226 s (3.130 s) | 0.038 s | 2042 | 0 | 52 | 0.0% | $0.000193 | reported | - |
| 4 | 1 | ok | 0.000 s | 12.430 s | 1.324 s | 1.156 s | 1: first chunk 1.121 s (2.690 s), 2: first chunk 1.706 s (9.701 s) | 0.036 s | 4413 | 4096 | 246 | 92.8% | $0.000147 | reported | - |
| 5 | 1 | ok | 0.000 s | 12.581 s | 2.435 s | 1.220 s | 1: first chunk 1.183 s (12.544 s) | 0.036 s | 2324 | 2048 | 178 | 88.1% | $0.000094 | reported | - |

## Aggregate

- Median user-visible first text (end-to-end, all attempts + backoff): **2.305 s** (n=5)
- Worst user-visible first text (end-to-end, all attempts + backoff): **2.889 s**
- Median successful-attempt visible latency: **2.305 s**
- Median first model chunk: 1.265 s
- Median pre-stream code time: 0.036 s
- Cached input share from turn 2: **72.3%** (7680/10624 input tokens from turn 2 onward; share among recorded tokens)
- Known cost across all attempts: **$0.000766** ($0.000153 per turn; known rows from 0 partial attempt(s) included; lower bound — 0 attempt(s) with unreported usage unknown; complete: True)
- Median user-visible first text within 2.0s: **UNMET**
- Median successful-attempt visible latency within 2.0s: **UNMET**

## Acceptance criteria

- Median time to first visible text ≤ 2.0s: **UNMET** (median 2.305 s)
- Nonzero recorded cache reuse on logical turn 2 in a full 5-turn session: **MET** (5/5 turns measured; turn 2 recorded 1536/1845 cached/input tokens, usage complete: True; aggregate share from turn 2 onward 72.3%)

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
