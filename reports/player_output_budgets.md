# Player model output token budgets

Measurement status: **complete with reduced n**.
Measured `deepseek-ai/DeepSeek-V4-Flash` through `https://api.deepinfra.com/v1/openai` using the production prompt builder and call path for `chat_reply`, `intent_routing`, `substitution_resolution`, `abbreviation_expansion`, `dynamic_split_plan`, `checkpoint_review`.
Structured sites used a temporary `2400`-token cap; chat and Checkpoint review used their previous 200- and 200-token caps. The target was 10 English and 10 Arabic inputs for each language-aware path, plus 20 distinct language-neutral abbreviations; requests ran sequentially to reduce provider overload.

Margin rule: p95 uses nearest-rank. For measured sites, margin = max(16 tokens, ceil(p95 * 25%)); recommended budget is p95 + margin rounded up to the next 8 tokens. Chat remains at 200 by product choice; Checkpoint review retains its 200-token product budget while reporting the measured recommendation; DynamicSplitPlan uses its own p95 margin rule.

| Call site | n | p50 | p95 | max | finish_reason=length | Failed/unrecorded requests | Previous budget | New budget | p95 + margin recommendation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `chat_reply` | 15 | 95 | 177 | 177 | 0 | 26 | 200 | 200 | 224 |
| `intent_routing` | 14 | 54.5 | 68 | 68 | 0 | 17 | 200 | 112 | 88 |
| `substitution_resolution` | 13 | 29 | 33 | 33 | 0 | 18 | 200 | 56 | 56 |
| `abbreviation_expansion` | 10 | 25.5 | 28 | 28 | 0 | 22 | 200 | 48 | 48 |
| `dynamic_split_plan` | 11 | 697 | 1019 | 1019 | 0 | 20 | 1200 | 1280 | 1280 |
| `checkpoint_review` | 20 | 75.0 | 130 | 139 | 0 | 0 | 200 | 200 | 168 |

The report is complete with reduced n after hosted provider overloads and timeouts. The target was 20 samples per call site; actual n and failed or unrecorded request counts are shown above.

Routing uses 112 tokens, conservative given reduced n (Arabic max 68 at n=14). Substitution resolution and abbreviation expansion use p95 + margin, rounded up to 8 tokens. Chat keeps its previous product choice because no sample truncated. DynamicSplitPlan uses 1280 tokens, conservative given reduced n: p95 was 1019 and the Arabic max was 1019 across only 4 samples; its own p95 + 25% margin rounded up to 8 tokens gives 1280. The production resolver clamps 6-day requests to 5 days.

The production `SubstitutionResolution` call resolves exercise references in the substitution flow, so it is measured once as `substitution_resolution`.

Checkpoint review: **measured output was available**. The 200-token production budget remains unchanged. Across 20 samples (10 English, 10 Arabic), raw content kinds were `text`: 20 and 0 responses became empty after extraction. The canonical request uses `system` + `user`, `max_completion_tokens=200`, no `stop` or `response_format`, plain text, and `extra_body={'chat_template_kwargs': {'enable_thinking': False}}`. The #194 baseline returned the one-token EOS marker in all 14 system-only samples. The current request separates instructions from the user facts and style data. The parser also treats `<｜end▁of▁sentence｜>` as a control token, so the existing read path serves its deterministic template without storing the marker.

Abbreviation input limitation: The production resolver receives only a 2–6 letter Latin token, with no locale argument. Recorded samples use distinct accepted keys from FITNESS_ABBREVIATIONS and are language-neutral.

The structured suite (#199) and the two-judge gate (#189) are deferred to those open tickets; this change does not build either suite or run judge evaluations.

## Finish reasons

Measurement error at `chat_reply`: 41-request ceiling reached at chat_reply.
Measurement error at `intent_routing`: Provider remained unavailable at intent_routing (en); last error: OpenAIRateLimitError.
Measurement error at `substitution_resolution`: Provider remained unavailable at substitution_resolution (en); last error: OpenAIRateLimitError.
Measurement error at `abbreviation_expansion`: Provider remained unavailable at abbreviation_expansion (language-neutral); last error: OpenAIRateLimitError.
Measurement error at `dynamic_split_plan`: Provider usage metadata missing for dynamic_split_plan sample 1.

- `chat_reply`: `stop`: 15
- `intent_routing`: `stop`: 14
- `substitution_resolution`: `stop`: 13
- `abbreviation_expansion`: `stop`: 10
- `dynamic_split_plan`: `stop`: 11
- `checkpoint_review`: `stop`: 20
