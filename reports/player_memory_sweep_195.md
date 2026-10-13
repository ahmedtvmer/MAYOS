# Player conversation memory sweep

Generated: 2026-10-13T12:04:15.794280+00:00
Player model: deepseek-ai/DeepSeek-V4-Flash
Judges: Qwen/Qwen3.5-27B, zai-org/GLM-5.3
Expected runtime: About 25 minutes for the six-setting memory sweep (48 player turns and 96 judge verdicts), based on the previous 45-minute estimate for 87 turns and 174 verdicts. The optional coaching_qa + arabic_replies regression pass adds about 43 minutes (83 player turns and 166 judge verdicts).

## Six-setting memory sweep

TTFT is measured from starting the player chat stream to its first content chunk. Each setting runs the eight synthetic multi-turn memory cases once. Both judges and exact-fact checks are reported separately, along with the combined pass count. Cost and TTFT deltas use the 6-message, 500-character baseline. Provider TTFT has previously been measured around 9 seconds on DeepInfra (#405), so the 2.0-second criterion is reported even when the provider floor exceeds it.

| Window | Earlier reply limit | Judge passes (1 / 2) | Exact facts | All checks | Cost / turn (USD) | Cost change vs baseline | Median TTFT | TTFT delta vs baseline | Cached input share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 6 | 500 | 3/8 / 2/8 | 2/8 | 2/8 | $0.000052 | +0.0% | 1.817s | +0.000s | 48.1% |
| 6 | none | 3/8 / 4/8 | 3/8 | 3/8 | $0.000043 | -17.9% | 1.779s | -0.037s | 63.4% |
| 10 | 500 | 8/8 / 6/8 | 6/8 | 6/8 | $0.000046 | -12.7% | 2.608s | +0.791s | 61.1% |
| 10 | none | 8/8 / 7/8 | 7/8 | 7/8 | $0.000048 | -8.5% | 8.940s | +7.123s | 56.7% |
| 16 | 500 | 7/8 / 6/8 | 6/8 | 6/8 | $0.000050 | -5.0% | 2.503s | +0.686s | 55.8% |
| 16 | none | 8/8 / 7/8 | 8/8 | 7/8 | $0.000057 | +9.5% | 1.856s | +0.039s | 43.7% |

## Setting details

### window-6_truncate-500

- Memory cases: 2/8 passed both judges and the exact-fact check.
- Judge passes: 3/8 / 2/8; exact-fact checks: 2/8.
- Player usage: 10 model calls, 6388 input tokens, 352 output tokens, 0 estimated calls.

### window-6_untruncated

- Memory cases: 3/8 passed both judges and the exact-fact check.
- Judge passes: 3/8 / 4/8; exact-fact checks: 3/8.
- Player usage: 10 model calls, 6456 input tokens, 313 output tokens, 0 estimated calls.

### window-10_truncate-500

- Memory cases: 6/8 passed both judges and the exact-fact check.
- Judge passes: 8/8 / 6/8; exact-fact checks: 6/8.
- Player usage: 10 model calls, 6708 input tokens, 308 output tokens, 0 estimated calls.

### window-10_untruncated

- Memory cases: 7/8 passed both judges and the exact-fact check.
- Judge passes: 8/8 / 7/8; exact-fact checks: 7/8.
- Player usage: 10 model calls, 6776 input tokens, 269 output tokens, 0 estimated calls.

### window-16_truncate-500

- Memory cases: 6/8 passed both judges and the exact-fact check.
- Judge passes: 7/8 / 6/8; exact-fact checks: 6/8.
- Player usage: 10 model calls, 6887 input tokens, 294 output tokens, 0 estimated calls.

### window-16_untruncated

- Memory cases: 7/8 passed both judges and the exact-fact check.
- Judge passes: 8/8 / 7/8; exact-fact checks: 8/8.
- Player usage: 10 model calls, 7029 input tokens, 251 output tokens, 0 estimated calls.

## Regression pass

Status: skipped_by_flag.

