## Problem Statement

Arabic-speaking players and coaches can use more tokens than English-speaking users for comparable assistant work. A daily request count alone does not explain the separate resource limit or why an account can be refused while requests remain. A completed stream can also contain an answer cut off by its output limit, so transport completion is not sufficient evidence of a completed answer.

An account with both player and coach capabilities needs independent Lifter and Coach budgets. Spending its Coach resources must not silently remove its ability to use its player assistant. Users need advance disclosure, an approaching-limit warning and an understandable cutoff message in their Display language.

The current closed trial has a shared admission-time soft cap of 200,000 input-plus-output tokens per account per UTC day. That is not a completed-request allowance. The launch request pools are separate planned work, and the proposed 5 Free / 30 Pro daily counts are not yet final. Earlier Qwen input-text token ratios do not establish a complete-conversation DeepSeek multiplier.

## Solution

Keep the implemented DeepSeek-V4-Flash selection for hosted player and coach turns. At launch, give English and Arabic the same completed-request ceiling within the same plan and capability, while separately charging actual token usage to independent Lifter and Coach resource budgets. A resource budget may stop ordinary requests before the completed-request ceiling is reached; disclose this limitation rather than promising every available request can always be used.

Explain the safeguard beside each plan's request allowance, show a persistent assistant warning at 80% of the relevant resource budget, and at cutoff show why further requests are unavailable, the remaining request count and the reset time. Exempt provider-reported output-token truncation from the completed-request allowance while retaining its usage, cost and abuse accounting.

Retain the shared 200,000-token trial cap without an Arabic multiplier until representative paired DeepSeek conversations establish a need to raise the common trial cap. Choose final launch request and resource limits from measured usage, cost and quality before sale.

## User Stories

1. As an Arabic-speaking player, I want the same Lifter request ceiling as an English-speaking player on my plan, so that the published request allowance does not depend on language.
2. As an Arabic-speaking coach, I want the same Coach request ceiling as an English-speaking coach on my plan, so that language does not change my published request allowance.
3. As a player, I want my request allowance described as a ceiling subject to a separate resource limit, so that I understand what my plan provides.
4. As a coach, I want the resource safeguard explained beside my plan's request allowance, so that I can make an informed plan choice.
5. As an Arabic-speaking user, I want to know upfront that Arabic replies may use more resources, so that an earlier cutoff does not surprise me.
6. As an assistant user, I want to know that longer conversations may use more resources, so that the daily resource safeguard is understandable.
7. As an assistant user, I want actual token usage counted without a language multiplier or discount, so that resource accounting follows the work performed.
8. As a player, I want to see my remaining Lifter requests, so that I can understand my daily request allowance.
9. As a coach, I want to see my remaining Coach requests, so that I can understand my daily request allowance.
10. As an assistant user, I want the next reset time shown, so that I know when daily access returns.
11. As an assistant user approaching my resource limit, I want a persistent warning at 80% of my capability's budget, so that I have notice before cutoff.
12. As a player using Android, I want the approaching-limit warning in my assistant, so that the limit is visible while I use it.
13. As a player using the web app, I want the same warning behavior, so that device choice does not change the policy.
14. As a coach using Android or web, I want the warning for my Coach budget, so that I do not confuse it with my Lifter usage.
15. As an assistant user who reaches the resource limit, I want a clear resource-cutoff explanation, so that I understand why the next request is refused.
16. As an assistant user with requests remaining at cutoff, I want that remaining count shown, so that the product does not falsely imply I exhausted my request allowance.
17. As an assistant user at cutoff, I want the reset time shown beside the explanation, so that I know when to return.
18. As an Arabic-version user, I want warning and cutoff messages in my Display language, so that I can understand account limits.
19. As an English-version user, I want the same structured information in English, so that both versions communicate the same policy.
20. As an account holder who changes Display language, I want structured usage messages to follow that choice, so that they remain readable.
21. As an account holder with both capabilities, I want separate completed-request pools, so that coaching does not consume my own training allowance.
22. As an account holder with both capabilities, I want separate resource budgets at launch, so that using one capability cannot exhaust the other's resources.
23. As a coach who exhausts Coach resources, I want unused Lifter resources and requests to remain usable, so that I can still ask about my own training.
24. As a player who exhausts Lifter resources, I want unused Coach resources and requests to remain usable, so that I can still coach my assigned players.
25. As an account holder using several devices, I want usage enforced on my account, so that devices and sessions share the same daily state.
26. As a coach switching selected players, I want my Coach usage to remain unchanged by that switch, so that the allowance belongs to my account rather than an assignment.
27. As an assistant user, I want only completed answers to consume request allowance, so that an admitted attempt is not automatically treated as a completed answer.
28. As an assistant user receiving a provider error, I want no completed-request debit, so that a failed answer does not consume that allowance.
29. As an assistant user whose stream is interrupted, I want no completed-request debit, so that an incomplete delivery does not consume that allowance.
30. As an assistant user whose answer reaches the output-token limit, I want no completed-request debit, so that a truncated answer is not counted as completed.
31. As an assistant user, I want request and resource usage treated separately, so that an allowance exemption does not imply the model call was free of resource usage.
32. As an owner, I want truncated-answer tokens retained in cost and resource accounting, so that real spending remains visible and bounded.
33. As an owner, I want separate abuse limits retained for failed, interrupted and truncated attempts, so that allowance exemptions cannot enable unbounded attempts.
34. As an assistant user whose turn needs several model calls, I want a completed answer counted once, so that internal call structure does not inflate my request count.
35. As a player reaching a Checkpoint, I want its review to remain outside the AI allowance and daily resource sum, so that the established exemption is preserved.
36. As a closed-trial account holder, I want the existing shared trial safeguard retained during measurement, so that unverified Arabic multipliers do not change access.
37. As an Arabic-speaking trial user, I want comparable complete conversations measured against English, so that an ordinary-use disadvantage is supported by evidence.
38. As an owner, I want the common trial cap raised when a reproducible ordinary-use Arabic day hits it while the equivalent English day passes, so that the accepted trial fairness rule is applied.
39. As an owner, I want final launch request and resource limits supported by usage, cost and quality evidence, so that provisional counts are not sold as final entitlements.
40. As an owner, I want Arabic quality gates preserved independently of allowance decisions, so that accepted policy is not mistaken for language-quality approval.

## Implementation Decisions

- **Accepted policy:** implement the contract agreed in #141 and ADR 059. Existing model, privacy, Program authority, assignment and language decisions remain in force. The judge remains Qwen3.5-27B; this spec does not reopen model selection.
- **Account and capability boundary:** use immutable account identity for durable daily usage across sessions and devices. Lifter and Coach completed-request pools remain separate. At launch, resource budgets must also be separate by capability; switching selected players cannot reset Coach usage. Account-wide abuse safeguards remain distinct from these capability budgets.
- **Two independent counters:** the completed-request ceiling limits completed assistant answers. The resource safeguard accounts for input-plus-output usage from model calls. An answer requiring multiple model calls consumes one completed request while all applicable call usage is recorded. The same plan and capability have the same request ceiling in English and Arabic; resource accounting introduces no language multiplier or discount.
- **Completion classification:** a successful transport completion alone is insufficient for a completed-request debit. Provider errors, interrupted streams and provider-reported output-token truncation consume no completed-request allowance. Preserve enough provider outcome information through assistant execution and transport to distinguish truncation from a complete answer. Truncated-call usage remains costed and charged to the resource budget, with attempts subject to abuse safeguards. Preserve the existing marked estimation fallback when usage metadata is missing; do not misrepresent estimates as provider-reported actual usage.
- **Admission and daily state:** enforce server-side request and resource limits before starting inference. A resource cutoff is permitted even with completed requests remaining. Preserve the existing admission-time soft-cap behavior rather than interpreting the resource budget as a promise that an admitted answer is cut off at an exact token boundary. Daily state resets at midnight UTC, and concurrent requests must not bypass allowance accounting. A refusal does not itself become a completed answer.
- **Existing seams and persistence:** extend the existing hosted-model admission/metering, assistant outcome and entitlement surfaces. Keep durable account usage in the shared catalog boundary. Extend the existing allowance contract with the capability's remaining requests, resource-limit state and next reset time, supplying the values needed for the warning and cutoff UI. Do not introduce a parallel usage system or commit to new endpoint names or a specific schema layout in this spec.
- **API and message contract:** expose structured status and typed values that distinguish a resource cutoff from completed-request exhaustion or an abuse refusal. Preserve existing English fallbacks for older clients under ADR 058. Continue refusing streamed player requests before starting the stream when admission fails. Preserve existing coach authorization and feature-gate checks before accessing player data or invoking the model.
- **Disclosure and warning:** disclose the resource safeguard beside the relevant plan's request allowance, with upfront explanation that longer conversations and Arabic replies may consume more resources. Render a persistent assistant warning when the relevant capability reaches at least 80% of its resource budget. At resource cutoff, explain that the daily resource limit was reached and show remaining requests and reset time. Structured messages follow Display language; assistant reply-language rules and historical prose remain unchanged.
- **Trial versus launch:** the closed trial retains the shared 200,000 input-plus-output token safeguard per account per UTC day, without an Arabic multiplier. Capability-isolated launch budgets must not silently replace that trial policy before the launch entitlement work applies. Preserve the Checkpoint review allowance/resource exemption while retaining metering and cost attribution.
- **Measurement contract:** after #190 and #194, run paired complete DeepSeek conversations with equivalent facts and tasks, covering short questions, long histories, Arabic/English mixing, program actions and coach analysis. Measure complete turns, retaining available input/output usage, completion outcomes and the resulting daily admission behavior. A reproducible ordinary-use day that hits the trial cap in Arabic while its English equivalent passes triggers raising the common trial cap. Do not derive a DeepSeek multiplier from the earlier isolated Qwen input-text ratio.
- **Final numeric limits:** determine launch request and capability resource limits from measured usage, cost and quality before public sale. The proposed Free 5 / Pro 30 requests per day remain proposals. Synthetic configurable limits are suitable for implementation tests; they do not establish production limits. The shared 200,000 trial cap and 80% warning threshold are the numeric policy decisions already accepted here.
- **Delivery ownership:** #66 and #67 remain the existing Lifter and Coach entitlement implementation tickets. This spec supplies their complete language/resource contract, not a second implementation queue. #190 and #194 own history/output work; their completion is a prerequisite for the paired measurement portion, not an instruction to duplicate their changes.

## Testing Decisions

- **Confirmed seams:** the owner confirmed existing assistant API contracts for allowance/resource accounting plus focused Flutter widget tests for warnings, cutoff information and reset display. Use these high-level seams rather than exposing new internal helpers just for tests. Paired live DeepSeek runs provide measurement evidence separately.
- **External behavior only:** assert admission results, observable allowance/resource state and displayed information. Do not pin private call order, SQL layout, helper names, widget implementation structure or exact translated prose. Prefer representative boundary cases over repeating every user story as a separate test.
- **Prior art:** extend the existing hosted-model metering/admission API tests, coach assistant contract tests, player chat and coach assistant widget tests, and plan-display tests. Existing Checkpoint review tests cover the established exemption. Reuse the existing fake provider and fake API patterns.
- **Request versus resource outcomes:** use deterministic provider doubles with complete, error, interrupted and output-truncated outcomes. Prove that only completed answers debit requests, that truncation does not, and that applicable usage/cost remains recorded. Include a transport-complete truncated response and a multi-call completed turn to distinguish completion from transport or invocation count.
- **Admission boundary:** demonstrate a resource refusal while requests remain, with refusal before a player stream begins and with correct structured remaining-request/reset information. Preserve the configured soft-cap behavior and distinguish resource, request and abuse refusals.
- **Capability and identity isolation:** verify both directions of Lifter/Coach exhaustion on one dual-capability account, different-account isolation, shared state across sessions/devices, and unchanged Coach usage when the selected player changes. Keep existing assignment-revocation tests relevant to coach requests.
- **Time and concurrency:** use a controlled clock and synthetic small limits for midnight UTC reset and concurrent completed-request accounting. Assert externally visible bounds and fresh daily state, not the locking implementation.
- **Warning and presentation:** focused widget tests cover below 80%, exactly 80%, continued warning above 80%, cutoff with requests remaining and the new day after reset. Cover Lifter and Coach, English and Arabic Display language, plan disclosure and remaining-request/reset display on the shared Android/web UI surfaces.
- **Trial regression and exemptions:** prove that the trial retains a shared account safeguard without a language multiplier and that Checkpoint review calls remain metered/costed without consuming either daily allowance/resource budget.
- **Live evidence:** run equivalent complete Arabic and English conversation workloads after the history/output fixes and retain reproducible measurement results. This evidence selects trial adjustments and final launch numbers; it does not replace deterministic contract tests or certify Arabic language quality.

## Out of Scope

- Reopening the implemented DeepSeek player/coach model choice or changing the judge.
- Choosing final launch request or resource-budget numbers without measurement, or treating the proposed 5 / 30 counts as final.
- Introducing language-specific discounts, token multipliers or extra request ceilings.
- Reimplementing history capacity work in #190 or per-call output work in #194.
- Duplicating the Lifter/Coach entitlement implementation queue in #66/#67, or implementing payments and unrelated plan features.
- Enabling Arabic or roster AI by bypassing quality, privacy, consent or feature gates.
- Altering Program authority, coach access, clinical safeguards, training history or Checkpoint review exemptions.
- Translating historical human/model prose or changing the latest-message assistant reply-language rule.
- Building a separate usage database, public token billing product or new analytics dashboard.

## Further Notes

- Origin: accepted #141 interview under parent map #135. All policy choices and testing seams have been confirmed by the owner.
- ADR 059 records the policy trade-off: equal published request ceilings can coexist with earlier actual-resource cutoff. ADR 038 supplies the existing trial admission/metering baseline; ADR 052 preserves the Checkpoint review exemption; ADR 058 governs structured messages.
- The trial rule to raise the common cap after a demonstrated equivalent-work disadvantage is distinct from the launch rule permitting actual resource usage to stop requests early.
- This is the complete specification for the existing entitlement work. #66/#67 retain their own blockers. Paired measurement depends on #190/#194; public release also retains the separate Arabic gates (#187/#247/#248) and the relevant localization contract (#246).
- Publication as `ready-for-agent` means the accepted spec is ready to use. It does not mean implementation prerequisites have completed, final numeric limits have been selected or public launch is approved.
