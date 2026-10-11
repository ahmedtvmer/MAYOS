# Player model output token budgets

Measurement status: **complete with reduced n**.
Measured `deepseek-ai/DeepSeek-V4-Flash` through `https://api.deepinfra.com/v1/openai` using real production prompt builders and call paths.
Structured sites used a temporary `2400`-token cap; chat and Checkpoint review used their previous 200- and 200-token caps. The target was 10 English and 10 Arabic inputs for each language-aware path, plus 20 distinct language-neutral abbreviations; requests ran sequentially to reduce provider overload.

Margin rule: p95 uses nearest-rank. For measured sites, margin = max(16 tokens, ceil(p95 * 25%)); recommended budget is p95 + margin rounded up to the next 8 tokens. Chat remains at 200 by product choice; Checkpoint review retains its prior 200-token budget because EOS responses are not measured output; DynamicSplitPlan uses its own p95 margin rule.

| Call site | n | p50 | p95 | max | finish_reason=length | Failed/unrecorded requests | Previous budget | New budget | p95 + margin recommendation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `chat_reply` | 15 | 95 | 177 | 177 | 0 | 26 | 200 | 200 | 224 |
| `intent_routing` | 14 | 54.5 | 68 | 68 | 0 | 17 | 200 | 112 | 88 |
| `substitution_resolution` | 13 | 29 | 33 | 33 | 0 | 18 | 200 | 56 | 56 |
| `abbreviation_expansion` | 10 | 25.5 | 28 | 28 | 0 | 22 | 200 | 48 | 48 |
| `dynamic_split_plan` | 11 | 697 | 1019 | 1019 | 0 | 20 | 1200 | 1280 | 1280 |
| `checkpoint_review` | 14 (0 usable; EOS) | not measured | not measured | not measured | 0 | 14 | 200 | 200 | not measured |

The report is complete with reduced n after hosted provider overloads and timeouts. The target was 20 samples per call site; actual n and failed or unrecorded request counts are shown above.

Routing uses 112 tokens, conservative given reduced n (Arabic max 68 at n=14). Substitution resolution and abbreviation expansion use p95 + margin, rounded up to 8 tokens. Chat keeps its previous product choice because no sample truncated. DynamicSplitPlan uses 1280 tokens, conservative given reduced n: p95 was 1019 and the Arabic max was 1019 across only 4 samples; its own p95 + 25% margin rounded up to 8 tokens gives 1280. The production resolver clamps 6-day requests to 5 days.

The production `SubstitutionResolution` call resolves exercise references in the substitution flow, so it is measured once as `substitution_resolution`.

Checkpoint review: **not measured — the model returned EOS for every sample; see #402**. Its previous and new budget is 200 tokens. Across 14 response observations, raw content kinds were `deepseek_end_token`: 14; 14 responses became empty after extraction. The exact canonical request body is in the JSON report: one `system` message, `max_completion_tokens=200`, no `stop` or `response_format`, plain text (no structured parser), and `extra_body={'chat_template_kwargs': {'enable_thinking': False}}`. A separate 200-token probe returned the same one-token EOS marker with and without that extra body, so the body is not the cause. The strongest code-level suspect is the system-only message shape: structured player paths send a system and user message. Adding a user turn changes the prompt input/hash, so it was not adopted; the diagnostic request with that turn did not return before interruption. Before the parser fix, the marker passed through as non-empty text and could be stored as review wording. The parser now treats `<｜end▁of▁sentence｜>` as a control token, so the existing read path serves its deterministic template without storing it.

Abbreviation input limitation: The production resolver receives only a 2–6 letter Latin token, with no locale argument. Recorded samples use distinct accepted keys from FITNESS_ABBREVIATIONS and are language-neutral.

The structured suite (#199) and the two-judge gate (#189) are deferred to those open tickets; this change does not build either suite or run judge evaluations.

## Finish reasons

Measurement error at `chat_reply`: 41-request ceiling reached at chat_reply.
Measurement error at `intent_routing`: Provider remained unavailable at intent_routing (en); last error: OpenAIRateLimitError.
Measurement error at `substitution_resolution`: Provider remained unavailable at substitution_resolution (en); last error: OpenAIRateLimitError.
Measurement error at `abbreviation_expansion`: Provider remained unavailable at abbreviation_expansion (language-neutral); last error: OpenAIRateLimitError.
Measurement error at `dynamic_split_plan`: Provider usage metadata missing for dynamic_split_plan sample 1.
Measurement error at `checkpoint_review`: Provider remained unavailable at checkpoint_review (en); last error: OpenAIRateLimitError.

- `chat_reply`: `stop`: 15
- `intent_routing`: `stop`: 14
- `substitution_resolution`: `stop`: 13
- `abbreviation_expansion`: `stop`: 10
- `dynamic_split_plan`: `stop`: 11
- `checkpoint_review`: `stop`: 14
