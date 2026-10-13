# Issue #196: DeepSeek reasoning-mode probe

Recorded: 2026-10-13 UTC  
Model: `deepseek-ai/DeepSeek-V4-Flash` through DeepInfra's OpenAI-compatible Chat Completions API.

## Finding

The request setting that returned complete structured split plans was:

```json
{"thinking":{"type":"enabled"}}
```

It is sent as `extra_body` on the split-plan request. The explicit High/Max candidate `reasoning_effort="high"` / `"max"` each timed out at the 60-second client limit on the same split prompt, with no response usage to measure. The enabled/disabled toggle completed. DeepSeek's API guide says thinking defaults to High effort; therefore the specific **Think High** label for the enabled toggle is an inference, while the exact request shape and successful plan parsing were observed. DeepInfra's public model page lists the three modes but does not document their request parameters. See [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) and the [DeepInfra DeepSeek-V4-Flash model page](https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash).

The provider accepted `thinking.type=enabled` and returned valid split plans, but did not expose a separate reasoning-token count or reasoning text. The toggle did not establish a clear quality improvement; the paired judge comparison is still required. Production therefore keeps the feature off by default until that comparison and the #199 structured-output live gate pass.

## Paired five-case probe

The five #199 split-plan prompts were each run once with thinking disabled and once enabled. Calls used temperature 0, a 2,048-token completion ceiling, the same production prompt/schema, and no retries. The order was alternated between cases. Only usage and validation metadata were retained; generated plan text was not saved. Every completed response parsed as `DynamicSplitPlan` with the requested day count.

| Setting | Parsed | Mean latency | Median latency | Mean output tokens | Mean estimated cost / plan |
| --- | ---: | ---: | ---: | ---: | ---: |
| `thinking.type=disabled` | 5/5 | 26.38 s | 25.54 s | 627.6 | $0.00015712 |
| `thinking.type=enabled` | 5/5 | 26.39 s | 26.74 s | 686.4 | $0.00016771 |

The enabled-minus-disabled latency differences by case were **+6.72, -3.04, -7.10, +10.88, and -7.39 seconds**. Mean latency changed by +0.01 seconds; median latency increased by 1.20 seconds. The largest observed slowdown was 10.88 seconds, below the 15-second limit. Mean estimated cost increased by 6.7% ($0.00001058 per plan); mean output tokens increased by 9.4%.

Cost estimates use DeepInfra's Standard rates shown on the model page at probe time: $0.09 per million input tokens and $0.18 per million output tokens. Cached-input discounts were not applied. The provider's reported `output_tokens` is used as the billable completion count; that may include hidden reasoning, but the provider does not break it out.

## Exact #199 function-calling path and leakage check

The production function-calling schema path was also run once per toggle on `split-04`, at 2,048 completion tokens:

| Setting | Parsed | Latency | Input / output tokens | Estimated cost / plan |
| --- | ---: | ---: | ---: | ---: |
| Enabled | yes, 4 days | 16.96 s | 1,138 / 542 | $0.00019998 |
| Disabled | yes, 4 days | 18.96 s | 1,138 / 592 | $0.00020898 |

In all 13 completed probe responses, usage metadata did not contain `reasoning_tokens`; no response carried a `reasoning_content` field; and no `<think>` marker appeared in visible content or the resolved plan. The function-calling response was parsed from tool arguments, and the resulting plan contained only the `DynamicSplitPlan` fields. The paired comparison script additionally scans each generated player-facing Training program for reasoning markers.

DeepSeek's API documentation defines completion usage to include its reasoning-token breakdown. Applying that billing contract to DeepInfra's compatible endpoint is an inference; the probe could not separately measure hidden reasoning tokens. For comparison, the no-extra-body baseline on `split-04` parsed in 29.93 seconds, used 501 input and 734 output tokens, and cost an estimated $0.00017721.

## Readiness and remaining live gates

- `PROGRAM_GENERATION_REASONING_ENABLED` defaults to `false`. When enabled for DeepSeek-V4-Flash, only `DynamicSplitPlan` generation receives the toggle and 2,048-token cap. Chat replies, routing and the Coach assistant do not.
- The paired judge comparison is implemented at `tests/eval/compare_reasoning_plans.py`. It alternates blind option order, compares the final generated Training programs with both configured judges, validates them against the production schema/catalog, and records per-case generation latency. Run from the repository root:

  ```sh
  set -a && . /mnt/work/MAYOS/.env; set +a && \
    /mnt/work/MAYOS/.venv/bin/python tests/eval/compare_reasoning_plans.py \
      --write-report reports/issue_196_reasoning_comparison.json
  ```

- The #199 structured-output live run should use the reasoning path for split plans. Its isolated suite command is:

  ```sh
  set -a && . /mnt/work/MAYOS/.env; set +a && \
    PROGRAM_GENERATION_REASONING_ENABLED=true \
    /mnt/work/MAYOS/.venv/bin/python tests/eval/run_evaluation.py \
      --suite structured_output --report reports/issue_196_structured_output_live.json
  ```

  The runner marks any single-suite invocation as partial (and exits nonzero for the overall gate); inspect `suite_results.structured_output` for the required 10/10 score. The broader player gate can instead be run without `--suite` if its other live suites are also due.
