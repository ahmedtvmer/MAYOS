# MAYOS AI Budget Evaluation Notes

**Status:** Unverified engineering hypotheses for the public subscription design

These limits came from the pricing draft. They are internal starting points,
not customer promises or current application behavior. Evaluate answer quality,
latency, model cost, and privacy before choosing per-tier limits. Keep separate
Lifter and Coach daily request pools as defined in the pricing plan.

The numeric budgets below remain hypotheses. [ADR 059](../DECISIONS.md)
accepts the launch policy: equal completed-request ceilings in English and
Arabic, separate Lifter and Coach resource budgets charged by actual token
usage, and a possible resource cutoff before the request ceiling is reached.
Disclose that safeguard beside plan allowances, warn persistently in the
assistant at 80% of the capability's resource budget, and show remaining
requests and reset time at cutoff. Output-token truncation consumes no
completed-request allowance but its usage remains costed and charged to the
resource budget. Numeric resource limits require measured evidence before sale.

The closed trial retains its shared 200,000-token per-account UTC-day safeguard
without an Arabic multiplier. After #190 and #194, compare equivalent complete
DeepSeek conversations covering short questions, long histories, mixed
Arabic/English, program actions and coach analysis. A reproducible ordinary-use
day that reaches the trial cap in Arabic while its English equivalent passes
triggers raising the common trial cap. This differs from the accepted launch
policy permitting earlier cutoff from actual usage.

| Candidate budget | Lifter Free | Lifter Pro | Coach Free | Coach Pro |
|---|---:|---:|---:|---:|
| Input context ceiling | 8K tokens | 16K tokens | 16K tokens | 32K tokens |
| Output ceiling | 1K tokens | 2K tokens | 2K tokens | 4K tokens |
| Recent relevant turns | ~4 | ~10–12 | ~6 | ~12–16 |

The current player prompt uses a fixed six-message tail and an 8 KiB byte
budget (`agent/assistant_graph.py`); this is not an 8K-token limit. Hosted
player and coach output defaults are environment-level values in
`utils/model_downloader.py`, not tier-specific limits. No current subscription
entitlements implement this table. A launch evaluation must compare the
candidate budgets with actual prompts, completions, cost, and model quality,
then document the selected limits and their enforcement in the API.
