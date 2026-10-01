# Arabic model and allowance policy: #141 interview

Status: accepted policy, 2026-10-01. The owner agreed to all interview
decisions. Numeric launch limits remain assigned to the existing measurement
and launch work. This document records design, not implementation or launch
approval. Architectural rationale is recorded in ADR 059.

The complete specification and confirmed testing seams are published as
[#261](https://github.com/ahmedtvmer/MAYOS/issues/261), labeled `ready-for-agent`.
The local spec is [Arabic model and allowance spec](arabic-model-and-allowance-spec.md).

## Agreed decisions

- Arabic and English users receive the same completed-request ceiling within
  a given plan and capability. This is a maximum, not a guarantee that every
  request can be used before a separate resource limit is reached.
- At public launch, actual token usage counts toward the resource safeguard,
  including Arabic's additional usage. The safeguard may refuse an ordinary
  request while completed requests remain. There is no Arabic discount or
  normalization of actual usage.
- At launch, Lifter and Coach resource budgets are separate and sized from
  measured usage. Exhausting one capability's resource budget does not exhaust
  the other's. The closed trial keeps its shared cap.
- Disclose the resource safeguard beside the plan's request allowance. Explain
  upfront that longer conversations and Arabic responses can consume more
  resources. Show a persistent assistant warning at 80% of that capability's
  resource budget. At cutoff, explain that the daily resource limit was
  reached, show the remaining requests and the reset time. Display these
  structured messages in the account's Display language (ADR 058).
- Retain the closed-trial daily safeguard of 200,000 input-plus-output tokens
  per account per UTC day, shared across player and coach usage, while
  collecting representative evidence. Introduce no Arabic-specific multiplier.
- If ordinary Arabic use demonstrably reaches that safeguard earlier than
  equivalent English use, raise the common trial cap pending the request-based
  allowance. This trial adjustment is distinct from the accepted launch policy
  allowing actual usage to exhaust a resource safeguard before the request
  ceiling.
- Compare paired DeepSeek conversations with equivalent facts and tasks:
  short questions, long histories, Arabic/English mixing, program actions and
  coach analysis. Measure complete turns after the history and output fixes.
  A reproducible ordinary-use day that reaches the trial cap in Arabic while
  its English equivalent passes triggers raising the common trial cap.
- An answer that the provider reports as cut off by its output-token limit
  consumes no completed-request allowance. Its tokens remain costed and count
  toward the resource safeguard; its attempt remains subject to abuse limits.
  A normal stream completion event alone does not establish allowance eligibility.

## Existing decisions and boundaries

Both hosted player and coach models already default to DeepSeek-V4-Flash;
the judge remains Qwen3.5-27B (ADR 012). This interview does not reopen model
selection. The outstanding Arabic quality work remains necessary.

The launch pricing document proposes separate Lifter and Coach request pools,
resetting at midnight UTC, counting completed answers and exempting provider
errors and interrupted streams. Its 5 Free / 30 Pro daily counts remain
proposals, not newly accepted numbers.

ADR 038 describes the current shared raw-token safeguard as an admission-time
soft cap. ADR 052 exempts Checkpoint reviews from that cap and the AI allowance.
The accepted allowance policy does not mean request pools already exist.

Conversation-history capacity is tracked in #190; per-call output budgets are
tracked in #194. A larger daily cap alone cannot fix either limitation.

The earlier approximate 1.15-times Arabic token ratio used isolated input text
with Qwen's tokenizer. It does not justify a multiplier for complete DeepSeek
conversations. Representative paired complete-turn evidence is still needed.

## Remaining measurement and implementation work

- Numeric launch request and token limits remain subject to measured evidence
  before sale; the 5 / 30 request proposals are not accepted by this interview.
- Apply the launch allowance rules through the existing Lifter and Coach
  entitlement work (#66 and #67), including independent resource budgets,
  truncation exemption and user warnings. The design is agreed; that work is
  not claimed as complete here.
- Complete the history and per-call output work (#190 and #194), then collect
  the paired complete-conversation evidence described above. Record selected
  budget numbers and their measurements before enforcement at public sale.
- Preserve the separate Arabic quality gates. Accepted model selection and
  allowance policy are not evidence that those gates passed.

## Sources

- [Issue #141](https://github.com/ahmedtvmer/MAYOS/issues/141) and its completed
  evaluation blocker [#139](https://github.com/ahmedtvmer/MAYOS/issues/139).
- [ADRs 012, 038, 052, 058 and 059](../../DECISIONS.md).
- [Launch AI context policy](../../plans/MAYOS_LAUNCH_PRICING.md#6-ai-context-policy).
- [Model defaults](../../utils/model_downloader.py),
  [admission limits](../../service/model_limits.py), and
  [token admission sum](../../database/registry/model_usage.py).
- [History budget #190](https://github.com/ahmedtvmer/MAYOS/issues/190) and
  [per-call budgets #194](https://github.com/ahmedtvmer/MAYOS/issues/194).
- [Lifter entitlements #66](https://github.com/ahmedtvmer/MAYOS/issues/66) and
  [Coach entitlements #67](https://github.com/ahmedtvmer/MAYOS/issues/67).
