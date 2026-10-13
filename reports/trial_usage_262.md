# Paired Arabic/English DeepSeek trial usage (#262)

## Current disposition

The shared closed-trial setting remains **200,000 input-plus-output tokens per
account per UTC day**. This implementation run made no hosted-model calls, so
there is no measured evidence that meets ADR 059's cap-raise trigger. This is a
pending measurement result, not evidence that Arabic and English consume the
same resources. The workload wording and daily profile are pending owner
review in [`trial-usage-workload-review-262.md`](../docs/design-review/trial-usage-workload-review-262.md).

The paired runner uses the configured production DeepSeek player and Coach
models, production player graph/history behavior, and the production Coach
prompt, transcript assembly, stream, and output scrubber. It reports each
metered model call, provider usage versus marked estimates, turn completion
and provider finish reasons, token totals, and priced cost. Truncated, failed,
empty, or semantically unreviewed turns are not eligible evidence of equivalent
successful work.

The replay profile contains six Player turns and, for the dual-capability day,
two Coach turns on the same account-wide counter. These are provisional
measurement inputs, not accepted launch request allowances. Checkpoint reviews
remain exempt from admission usage while their model costs remain recorded.
UTC reset and admission-time soft-cap behavior follow the existing API seam.

## Reproduction

Validate fixture shape without loading a model:

```sh
/mnt/work/MAYOS/.venv/bin/python tests/eval/run_trial_usage_measurement.py --validate
```

The owner/orchestrator runs the hosted measurement after reviewing the fixture:

```sh
/mnt/work/MAYOS/.venv/bin/python tests/eval/run_trial_usage_measurement.py --live --report reports/trial_usage_262.json
```

Expected runtime is about 10–20 minutes at current provider latency, with a
30-minute target. The script writes a partial/error report if model loading or
provider calls fail. It does not run automatically in tests.

## Launch sizing boundaries

The JSON report retains prompt/configuration identities, per-turn usage and
cost, the replay schedule, and the cap decision for later sizing work. It does
not treat the proposed Free 5 / Pro 30 requests as accepted. Arabic quality and
privacy must still pass their separate gates before sale.
