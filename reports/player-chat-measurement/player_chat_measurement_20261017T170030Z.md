# Player chat streaming measurement

- Generated: `2026-10-17T17:00:30.475956+00:00`
- Report version: `3` (per-attempt retention; the historical version-1 reports are final-attempt-only and kept in `reports/player-chat-measurement/`)
- Streamed path: assistant_graph.stream_assistant_turn (SSE chat route generator)
- Provider: DeepInfra
- Model: `deepseek-ai/DeepSeek-V4-Flash`
- Endpoint: `https://api.deepinfra.com/v1/openai`
- Base commit: `af88a2e3804678974da2de16ed6fb258ad326002`
- Request timeout: `60.0s`; wall-clock budget: `300.0s`
- First-token deadline: `6.0s`; total attempts per model call: `2`
- Turns: 5 measured / 0 failed / 0 skipped of 5; attempts: 5 total, 0 failed, 0 timed out; first-token deadline retries: 0; model stream attempts: 6

## Accounting

- Every attempt of a logical turn is retained with its elapsed time, retry backoff, error and known usage. Latency is split into the end-to-end user wait (all attempts + backoff) and the successful attempt's visible latency (its own first-visible text, not a pure provider/model-stream TTFT). Usage totals sum every known row, including the known rows of partial attempts; only the unreported remainder of a failed attempt is unknown and excluded (never counted as zero), so the known token and cost sums are a lower bound when any usage is unreported. A recorded-token cache share is not a lower bound: it is the fraction among reported tokens, and the overall share is unknown while usage is incomplete.
- Measurement retry policy: Measurement harness: model built with build_player_llm(timeout=..., max_retries=0); up to max_turn_attempts (live: 3) per logical turn, retrying only a transient provider-busy (HTTP 429/overloaded) or timeout failure with a fixed backoff; every attempt is recorded.
- Production retry policy: Production player chat (utils.model_downloader.get_llm): first-token deadline LLM_FIRST_TOKEN_TIMEOUT (default 6 s) retries one model call up to LLM_FIRST_TOKEN_MAX_ATTEMPTS total attempts (default 2, maximum 5); this harness records each deadline retry. OpenAI SDK retries remain inside each call (LLM_MAX_RETRIES default 1), with request timeout 60 s and later-chunk timeout 30 s.

## Per-turn summary

| Turn | Intent | Status | Attempts | End-to-end first text (user wait) | Successful-attempt visible latency | Known cost | Usage |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | coaching_qa | ok | 1 | 1.680 s | 1.680 s | $0.000226 | reported |
| 2 | coaching_qa | ok | 1 | 1.542 s | 1.542 s | $0.000077 | reported |
| 3 | coaching_qa | ok | 1 | 3.833 s | 3.833 s | $0.000066 | reported |
| 4 | coaching_qa | ok | 1 | 11.899 s | 11.899 s | $0.000087 | reported |
| 5 | coaching_qa | ok | 1 | 5.735 s | 5.735 s | $0.000082 | reported |

## Per-attempt detail

| Turn | Attempt | Status | Backoff | Elapsed | First visible | First model chunk | Model call attempts | Pre-stream | Input | Cached | Output | Cached share | Cost | Usage | Error |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 1 | ok | 0.000 s | 9.796 s | 1.680 s | 1.345 s | 1: first chunk 1.329 s (2.479 s), 2: first chunk 1.409 s (7.297 s) | 0.017 s | 3312 | 1536 | 213 | 46.4% | $0.000226 | reported | - |
| 2 | 1 | ok | 0.000 s | 7.680 s | 1.542 s | 1.228 s | 1: first chunk 1.203 s (7.654 s) | 0.026 s | 1741 | 1536 | 171 | 88.2% | $0.000077 | reported | - |
| 3 | 1 | ok | 0.000 s | 7.867 s | 3.833 s | 3.428 s | 1: first chunk 3.395 s (7.834 s) | 0.033 s | 1929 | 1792 | 117 | 92.9% | $0.000066 | reported | - |
| 4 | 1 | ok | 0.000 s | 15.534 s | 11.899 s | 6.024 s | 1: first chunk 6.000 s (15.509 s) | 0.025 s | 2059 | 1792 | 169 | 87.0% | $0.000087 | reported | - |
| 5 | 1 | ok | 0.000 s | 10.194 s | 5.735 s | 4.768 s | 1: first chunk 4.738 s (10.164 s) | 0.030 s | 2243 | 2048 | 154 | 91.3% | $0.000082 | reported | - |

## Aggregate

- Median user-visible first text (end-to-end, all attempts + backoff): **3.833 s** (n=5)
- Worst user-visible first text (end-to-end, all attempts + backoff): **11.899 s**
- Median successful-attempt visible latency: **3.833 s**
- Median first model chunk: 3.428 s
- Median pre-stream code time: 0.026 s
- Cached input share from turn 2: **89.9%** (7168/7972 input tokens from turn 2 onward; share among recorded tokens)
- Known cost across all attempts: **$0.000537** ($0.000107 per turn; known rows from 0 partial attempt(s) included; lower bound — 0 attempt(s) with unreported usage unknown; complete: True)
- Median user-visible first text within 2.0s: **UNMET**
- Median successful-attempt visible latency within 2.0s: **UNMET**

## Acceptance criteria

- Median time to first visible text ≤ 2.0s: **UNMET** (median 3.833 s)
- Nonzero recorded cache reuse on logical turn 2 in a full 5-turn session: **MET** (5/5 turns measured; turn 2 recorded 1536/1741 cached/input tokens, usage complete: True; aggregate share from turn 2 onward 89.9%)

## Baseline comparison

- #265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.
- #192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.
