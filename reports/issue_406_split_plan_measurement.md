# Issue #406: DynamicSplitPlan output measurement

Recorded: 2026-10-13 UTC  
Model: `deepseek-ai/DeepSeek-V4-Flash` through DeepInfra's OpenAI-compatible API.

The five split-plan cases from `tests/eval/datasets/structured_player_cases.json` were invoked with the production `resolve_split` prompt builder and the #199 `DynamicSplitPlan` function-calling schema under a temporary 4,096-token model output cap. The two highest outputs were repeated once. Only case IDs and usage metadata were retained; raw provider response bodies and plan text were not saved. Machine-readable data is in [issue_406_split_plan_measurement.json](issue_406_split_plan_measurement.json).

The prior #194 broad measurement recorded 11 DynamicSplitPlan outputs with a 1,019-token p95 and maximum under the earlier structured-output `.bind(...)` call path, which did not forward the chosen cap to the provider. The targeted #406 set below measured seven outputs (the five suite cases and two repeats), with a maximum of 654 tokens. Both measurements inform the final budget because #406 now enforces the configured cap at `with_structured_output` itself.

| Case | Repeat | Completion tokens | Reasoning tokens | Finish reason | Valid plan |
|---|---:|---:|---:|---|---|
| split-01 | 1 | 507 | not reported | `tool_calls` | yes |
| split-02 | 1 | 440 | not reported | `tool_calls` | yes |
| split-03 | 1 | 604 | not reported | `tool_calls` | yes |
| split-04 | 1 | 654 | not reported | `tool_calls` | yes |
| split-05 | 1 | 442 | not reported | `tool_calls` | yes |
| split-04 | 2 | 574 | not reported | `tool_calls` | yes |
| split-03 | 2 | 595 | not reported | `tool_calls` | yes |

A corrected repeat of split-04 at the proposed 824-token cap returned a valid plan with 545 completion tokens and `finish_reason=tool_calls`. This confirms that case fits at 824; it does not establish that all real requests fit below the earlier 1,019-token maximum.

## Reasoning tokens

The production request sent no explicit thinking-mode override. DeepSeek's [Chat Completions API documentation](https://api-docs.deepseek.com/api/create-chat-completion/) defines `max_tokens` as the maximum number of generated completion tokens and reports `reasoning_tokens` as a breakdown of completion usage. Under that API contract, reasoning shares the output-token cap; applying the same contract to DeepInfra's compatible endpoint is an inference. DeepInfra's responses exposed `output_tokens` but no `reasoning_tokens` detail or reasoning-content field, so the number of hidden reasoning tokens could not be separated from the reported completion count.

## Budget

The targeted #406 maximum was 654 tokens; the earlier #194 maximum was 1,019. To avoid silently falling back on valid prompts that exceed the targeted sample while the cap is now enforced, budget from the larger observed maximum: `ceil(1019 × 25%) = 255`; `1019 + 255 = 1274`; rounding up to the next 8-token boundary gives **1,280 tokens**. This is the smallest budget produced by the existing margin rule for both measurements and is 261 tokens above the #194 maximum. The cap bounds the possible completion length; metered cost follows actual generated usage, so lowering the ceiling below observed valid output buys little and risks default-split fallback.

## Correctly capped structured-output gate

The single allowed post-change `structured_output` live run scored **5/10**. All five split-plan cases parsed at 824 tokens, with no truncations. All five substitution cases truncated at 56 tokens. The suite had previously bound its cap after LangChain's structured-output wrapper; passing `max_completion_tokens` to `with_structured_output` itself ensures that the call uses the intended model output cap. The earlier suite run passed all five substitutions at the model's effective 200-token default; the substitution budget is restored to that previous ceiling. The final 1,280-token split cap was selected after this live run; no live calls were made in the correction round.
