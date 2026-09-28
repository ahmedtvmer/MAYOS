# Gemma 3 migration feasibility (#145)

Research for issue #145 (parent map #135, blocks #141). Researched 2026-09-28.
Builds on [#137: Qwen3.5 Egyptian Arabic & Franco capability][p137]
(branch `research/qwen-egyptian-arabic`).

**Scope.** Mid-task, the owner narrowed the language requirement: **plain
(standard/MSA) Arabic in Arabic script is enough**. Egyptian dialect and Franco
output are no longer required. The verdict below therefore rests on
standard-Arabic quality, capabilities, cost and migration effort. Gemma's
documented *Egyptian* advantage from #137 is kept only as background.

All code paths refer to `origin/feat/web-into-app` @ `523a8bb`.

Legend: **[doc]** the source states it. **[measured]** I measured it here
(method given). **[inference]** my reading of the evidence, which no source
states.

## TL;DR

1. **Price.** On DeepInfra, Gemma 3 is cheaper than both Qwen models we use,
   and far cheaper than Qwen3.5-27B on output ($0.16/M against $2.60/M) [doc].
   A typical **player** turn costs about the same on any candidate: $0.08 to
   $0.15 per 1,000 turns. A typical **coach** turn drops from about **$1.04 to
   $0.16 per 1,000 turns** (English) on Gemma 3 27B. Arabic adds 10 to 20% on
   every model [inference from measured tokens]. **The money is in the coach
   role, not the player role, and not in Arabic.**
2. **Standard Arabic.** No primary source gives Qwen3.5 Arabic scores. Against
   the Qwen3 generation, Gemma 3 27B is roughly level on MSA knowledge and
   slightly ahead on Arabic reading comprehension [doc]. In live probes,
   **Qwen3.5-9B and 27B answered Arabic questions in Arabic without being told
   to. Gemma 3 12B and 27B answered the same Arabic question in English under
   our production system prompt** (4/4 runs). An explicit "reply in the user's
   language" line fixed 27B but **not** 12B [measured, small n].
3. **Capabilities on DeepInfra** [measured]: Gemma 3 streams, reports usage,
   accepts multiple or misplaced system messages (DeepInfra folds them into the
   first user turn), silently ignores `enable_thinking`, and supports tool
   calling (named and auto) and `json_object` mode. **But LangChain's default
   `with_structured_output()` path (strict `json_schema`) runs away on Gemma 3
   (and Gemma 4)**: after the fields it knows, it emits whitespace until
   `max_tokens`. That breaks all six production structured-output call sites
   unless they switch to `method="function_calling"` or `"json_mode"`.
4. **Latency.** Gemma 3 12B was about as fast as Qwen3.5-9B. **Gemma 3 27B was
   slow and erratic**: time to first token 1.9 to 10 s and 5 to 16 output
   tokens/s, against 0.4 to 1.3 s and 34 to 94 tok/s for Qwen3.5-27B [measured,
   one session, n≈10 calls per model].
5. **Code change** for a full swap is small: env vars, a structured-output method
   switch, one prompt line, a pricing table, and scrubber tokens. A **per-turn
   Arabic→Gemma split is harder**, because the player model is a module-level
   singleton imported by name in four modules.
6. **Verdict [inference].** With the Egyptian requirement gone, the case for
   moving *Arabic* turns to Gemma 3 is weak. Qwen3.5 already writes standard
   Arabic unprompted, and Gemma 3 needs prompt help and still slipped. The case
   worth testing in #139 is **cost-driven**: the coach role on a Gemma model
   (Gemma 3 27B if its latency holds up, Gemma 3 12B or Gemma 4 otherwise),
   with the structured-output fix.
7. **Side finding (bug, independent of Gemma).** `service/coach_ai.build_messages`
   sends **two** `SystemMessage`s. DeepInfra rejects that for both Qwen3.5-9B
   and Qwen3.5-27B with `400 System message must be at the beginning.`
   [measured], so the hosted coach AI call fails on the current configuration.
   Gemma accepts it. File this separately; it should not wait for a migration
   decision.

## 1. Pricing

### 1.1 Current DeepInfra prices [doc]

Source: DeepInfra's public catalogue API `https://api.deepinfra.com/models/list`
(fetched 2026-09-28; `cents_per_*_token` × 10⁴ = USD per 1M), cross-checked on
the model pages ([gemma-3-27b-it][di-g27], [Qwen3.5-9B][di-q9]). Standard tier.
Priority is 1.5× and flex is 0.8× for all rows below.

| Model | In $/1M | Out $/1M | Context (DeepInfra) | Quant | Catalogue tags |
|---|---:|---:|---:|---|---|
| `Qwen/Qwen3.5-9B` (player, today) | 0.10 | 0.15 | 262,144 | bf16 | tools, json, structured-output |
| `Qwen/Qwen3.5-27B` (judge + coach, today) | 0.26 | **2.60** | 262,144 | fp8 | tools, json, structured-output, reasoning |
| `google/gemma-3-12b-it` | 0.05 | 0.15 | 131,072 | bf16 | tools, json, structured-output, **non-reasoning** |
| `google/gemma-3-27b-it` | 0.08 | 0.16 | 131,072 | fp8 | tools, json, structured-output, **non-reasoning** |
| `google/gemma-4-31B-it` | 0.13 | 0.38 | 262,144 | fp8 | tools, json, structured-output, reasoning, can-disable-reasoning |
| `google/gemma-4-31B-it-turbo` | 0.09 | 0.34 | 262,144 | — | same |
| `google/gemma-4-26B-A4B-it` | 0.07 | 0.34 | 262,144 | — | same |

The [gemma-3-27b-it page][di-g27] also states a maximum of 8,192 generated
tokens per response [doc]. That is far above our budgets of 200, 512 and 700.

**Pricing-table drift (from #137, still true):** `utils/model_pricing.py`
`DEFAULT_MODEL_PRICING` and the `fly.toml` `MODEL_PRICING_JSON` example assume
Qwen3.5-9B at $0.10/$0.30 and Qwen3.5-27B at $0.30/$0.90. The live prices are
$0.10/$0.15 and $0.26/$2.60, so metering **under-reports coach and judge output
about 2.9×**. Neither table has any Gemma entry. An unpriced model meters at $0
with one warning (`price_for`).

### 1.2 Which model each call site uses today

The hosted backend (`LLM_BACKEND=openai`, `fly.toml`) builds one `SafeChatOpenAI`
per role from `CLOUD_MODEL_REGISTRY` (`utils/model_downloader.py`).

| Role / model | Call site | Kind | Output cap |
|---|---|---|---|
| **player**, `LLM_MODEL` = Qwen3.5-9B | `agent/assistant_graph.py` `generation_node` (`llm.invoke`) and the streaming turn loop (`llm.stream`, ~l.1503) | free text, the main cost | `LLM_MAX_TOKENS` 200 |
| player | `assistant_graph.py` LLM router fallback (`with_structured_output(IntentClassification)`, l.487) | structured. Only runs when regex routing fails **and** an action hint is present | 200 |
| player | `assistant_graph.py` `resolve_coreference_with_llm` (`SubstitutionResolution`, l.792) | structured, substitution turns only | 200 |
| player | `agent/fitness_abbreviations.py` `resolve_unknown_abbreviation_with_llm` (l.121) | structured, unknown 2–6 letter tokens only | 200 |
| player | `agent/onboarding_graph.py` `step1..3_extractor` (l.137–139) | structured, onboarding steps (plain-string prompt, no system message) | 200 |
| player | `agent/program_rules.py` `DynamicSplitPlan` (l.226) | structured, program generation | 200 |
| **coach**, `COACH_MODEL` = Qwen3.5-27B | `service/coach_ai.py` `_invoke_coach_model` (`get_coach_llm().invoke`) | free text, coach console | `COACH_MAX_TOKENS` 512 |
| **judge**, `JUDGE_MODEL` = Qwen3.5-27B | `tests/eval/run_evaluation.py` `safe_invoke_judge` (`method="function_calling"`) | eval only, not production traffic | `JUDGE_MAX_TOKENS` 700 |

`agent/debrief.py` and `agent/program_generator.py` make **no** model calls on
this branch. They are deterministic. `agent/prompts.py` holds the player system
prompt (`STATIC_SYSTEM_CORE`). No production path calls `bind_tools`. Tool
calling is exercised only by `scripts/provider_smoke.py`, and function calling
only by the eval judge.

### 1.3 Cost per typical turn

**Method [inference, with measured inputs]:**

- **Turn shapes.** Player generation call: about 900 tokens of fixed English
  context (the `STATIC_SYSTEM_CORE` system prompt, measured at 339 Qwen / 333
  Gemma tokens, plus trainee context and tone), about 300 tokens of
  user-language history and question, and about 120 output tokens. The hosted
  prompt is capped at 8 KiB (`HOSTED_PROMPT_BYTE_BUDGET`) and output at 200.
  Coach call: about 1,300 tokens of fixed English (`SYSTEM_PROMPT` plus
  `[PLAYER TELEMETRY]`), a 200-token question, and 250 output tokens (cap 512).
  These shapes are assumptions. #139 should replace them with the real
  `model_usage` rows.
- **Arabic.** Only the user-language parts (history, question, reply) are
  inflated. System prompts and telemetry stay English.
- **Tokenizer factors [measured].** 219 parallel FLORES passages from Belebele
  (`eng_Latn` vs `arb_Arab`, the #137 corpus), counted with `tokenizers` 0.23.2
  and `add_special_tokens=False`:

  | Tokenizer | English tokens | MSA tokens | MSA/EN | Chars/token EN / AR |
  |---|---:|---:|---:|---:|
  | Qwen3.5 (`Qwen/Qwen3.5-9B`, 248k vocab) | 21,824 | 27,923 | **1.28×** | 4.82 / 3.29 |
  | Gemma 3 (`unsloth/gemma-3-27b-it` mirror of Google's gated tokenizer, 262k vocab) | 21,534 | 30,959 | **1.44×** | 4.88 / 2.97 |

  On 12 gym sentences I wrote (English vs MSA), the ratios are 1.29× (Qwen)
  and 1.34× (Gemma). **Gemma 3's tokenizer is about 1% cheaper on English and
  about 11% more expensive on MSA than Qwen3.5's** [measured]. That contradicts
  the report's "more balanced for non-English languages" claim [doc,
  [Gemma 3 report][g3-report] §2.1] only relative to Qwen3.5. The claim was
  made against Gemma 2. The model used 1.44× in the table below.

**Estimated USD per 1,000 turns** (one generation call each; structured
side-calls add less than $0.04 per 1,000 on any model):

| Role | Model | English | Arabic (MSA) |
|---|---|---:|---:|
| player | Qwen3.5-9B (today) | $0.138 | $0.151 |
| player | Gemma 3 12B | $0.077 | $0.091 |
| player | Gemma 3 27B | $0.114 | $0.132 |
| player | Gemma 4 26B-A4B | $0.123 | $0.150 |
| player | Gemma 4 31B | $0.199 | $0.236 |
| coach | Qwen3.5-27B (today) | **$1.040** | **$1.237** |
| coach | Gemma 3 12B | $0.111 | $0.132 |
| coach | Gemma 3 27B | $0.158 | $0.182 |
| coach | Gemma 4 26B-A4B | $0.188 | $0.231 |
| coach | Gemma 4 31B | $0.286 | $0.339 |

Reading it [inference]:

- **Player:** any swap moves cost by pennies per thousand turns. Gemma 3 12B
  about halves it and Gemma 3 27B is about 15% cheaper. This is not a reason to
  migrate by itself.
- **Coach:** Qwen3.5-27B's $2.60/M output price dominates. Any Gemma is 3.6 to
  9× cheaper per coach turn.
- **Arabic penalty:** +10% on Qwen and +15 to 20% on Gemma per turn, because
  Gemma's tokenizer inflates MSA more.
- **Per-account limit:** the `MODEL_DAILY_TOKEN_LIMIT` (200k/day,
  `service/model_limits.py`) runs out about 1.28× (Qwen) or 1.44× (Gemma)
  faster for Arabic content.
- **Side calls:** a structured call through function calling on Gemma costs
  about 600 input tokens against about 110 to 130 for `json_schema` or
  `json_mode` [measured: 602 vs 125 prompt tokens, same request], because the
  tool schema is injected into the prompt. At $0.05/M this is still negligible.

## 2. Quality and capabilities

### 2.1 English reasoning and instruction following [doc]

| Benchmark | Gemma 3 12B IT | Gemma 3 27B IT | Qwen3.5-9B | Qwen3.5-27B |
|---|---:|---:|---:|---:|
| MMLU-Pro | 60.6 (card) / 56.9 (report T6) | 67.5 | 82.5 | 86.1 |
| GPQA Diamond | 40.9 | 42.4 | 81.7 | 85.5 |
| IFEval | 88.9 | 90.4 | 91.5 | 95.0 |
| IFBench | — | — | 64.5 | 76.5 |
| BFCL-V4 (tool use) | — | — | 66.1 | 68.5 |
| Global-MMLU-Lite / MMMLU | 69.5 (GMMLU-Lite) | 75.1 (GMMLU-Lite) | 81.2 (MMMLU) | 85.9 (MMMLU) |

Sources: [Gemma 3 model card][g3-card]; [Gemma 3 technical report][g3-report]
Table 6 and Appendix Table 18; [Qwen3.5-9B card][q35-9b]; [Qwen3.5-27B
card][q35-27b]. The two Gemma 12B MMLU-Pro figures disagree between card and
report. **The Qwen3.5 numbers are thinking-mode results** (the 27B card says so
explicitly [doc]). MAYOS runs Qwen with thinking **off** (§2.3), so these
numbers overstate what we get. Gemma 3 has no thinking mode, so its numbers
already match how we would run it [inference].

**Inference.** On reasoning-heavy benchmarks, thinking-mode Qwen3.5 is far
ahead. On instruction following (IFEval) the gap is small (about 90 vs 91–95).
With thinking off, Qwen3.5's real lead is unknown and probably much smaller. No
primary source reports non-thinking Qwen3.5 scores. Our workload is short,
rule-bound coaching replies, which depends more on IFEval-style compliance than
on GPQA, so a smaller gap is plausible. Only #139 can settle it.

### 2.2 Standard Arabic (MSA) [doc unless marked]

No primary source gives an Arabic breakdown for Qwen3.5 (see #137 §1). The best
available comparisons use Qwen3:

- **Qwen3 technical report, Table 28** (MSA, non-thinking, our configuration)
  ([arXiv 2505.09388][q3-report], via #137). Average across MLogiQA, INCLUDE
  and MMMLU-ar: Gemma-3-27B-IT **48.5**, Qwen3-32B 49.8, Qwen3-14B 45.9,
  Qwen3-8B 39.6. MMMLU-ar: Gemma 3 27B 74.4, Qwen3-8B 64.6, Qwen3-32B 75.7.
- **Belebele, Afro-Asiatic group** (includes `arb_Arab`), Table 37: Gemma-3-27B-IT
  **85.9**, Qwen3-32B (non-thinking) 82.3, Qwen3-14B 80.1.
- **DialectalArabicMMLU, MSA column** ([arXiv 2510.27543][dammlu]): gemma-3-12b-it
  62.6 against Qwen3-4B-Instruct 31.2. The Qwen model there is much smaller,
  so this is a weak comparison.
- **Gemma 3 claims:** "over 140 languages" and a tokenizer "more balanced for
  non-English languages" ([card][g3-card], [report][g3-report]). There is no
  Arabic-specific number.

**Inference.** On MSA *comprehension*, Gemma 3 27B is at least level with a
Qwen3 model of similar size, and Gemma 3 12B probably beats Qwen3-8B.
Qwen3.5 should improve on Qwen3, since its multilingual scores rise and its
tokenizer is much better on Arabic, so the documented gap likely narrows or
reverses. Nothing documented shows a clear MSA quality win for Gemma 3 over the
deployed Qwen3.5.

**Live behaviour [measured].** Production `STATIC_SYSTEM_CORE`, temperature 0,
question "ما هي أفضل طريقة لزيادة قوة تمرين الضغط على الصدر؟":

| Model | No language instruction | With "Always reply in the same language and script as the trainee's latest message." |
|---|---|---|
| Qwen3.5-9B | Arabic (3/3) | Arabic |
| Qwen3.5-27B | Arabic (1/1) | not run |
| Gemma 3 12B | **English** (3/3) | **English** |
| Gemma 3 27B | **English** (3/3) | Arabic |
| Gemma 4 31B | Arabic (1/1) | not run |

With a different, shorter system prompt that said "Reply in the user's
language", both Gemma 3 models answered the English greeting "Hi, I'm Sam." in
**Spanish or Portuguese** (Gemma 3 12B: "Olá, Sam!", 2/2 runs). The Arabic
replies they did produce were fluent MSA. This is a tiny sample, but it points
at the main standard-Arabic risk: **with our English-only system prompt, Gemma 3
does not reliably answer in the user's language, and a generic "same language"
instruction is not reliably followed either** [inference]. A deterministic fix
exists and is cheap: detect Arabic script in the latest user message and
inject "Reply in Modern Standard Arabic." for that turn.

### 2.3 Capabilities our graph relies on

| Capability | What we rely on | Qwen3.5 on DeepInfra | Gemma 3 on DeepInfra |
|---|---|---|---|
| Thinking toggle | `_build_cloud_llm` always sends `extra_body={"chat_template_kwargs":{"enable_thinking":false}}` (ADR in `DECISIONS.md`). `scripts/provider_smoke.py` fails if it is absent | **Required.** Without it, a 200-token reply came back **empty** (reasoning used the whole budget) [measured]. Thinking is on by default ([card][q35-9b]) | **None needed.** Gemma 3 has no thinking mode (catalogue tag `non-reasoning`). The kwarg is accepted and ignored; no `reasoning_content` returned [measured]. Gemma 4 *has* reasoning (tag `can-disable-reasoning`); with the same kwarg it reported `reasoning_tokens=0` [measured] |
| System role | Every chat call uses `SystemMessage`. Coach sends **two** | Accepts one, first only. **Two → HTTP 400** [measured] | The Gemma template has only `user` and `model` roles: "the `system` role or a system turn is not supported"; put instructions in the first user turn ([Gemma prompt docs][g-prompt]). The HF chat template prepends the first system message to the first user turn and **raises** on non-alternating roles ([template][g3-template]). DeepInfra is more lenient: two system messages, consecutive user messages, and system-then-assistant all returned 200 [measured]. So DeepInfra rewrites the messages; the exact rewrite is undocumented |
| Structured output | Six production sites call `with_structured_output(Schema)` with **no method**. `SafeChatOpenAI` subclasses `ChatOpenAI`, whose default in langchain-openai 1.6.0 (locked in `uv.lock`) is `method="json_schema"`. The OpenAI SDK's `.parse()` sends a **strict** schema (every field `required`, nullable via `anyOf`, `additionalProperties:false`) | Works [measured] | **Fails.** The model writes the fields it wants, then pads with `"\n  "` until `max_tokens` → `LengthFinishReasonError` (Gemma 3 12B, 27B **and** Gemma 4 31B) [measured]. Non-strict `json_schema` from the plain Pydantic schema worked, as did `json_mode` and `function_calling`. DeepInfra documents both `json_object` and `json_schema` modes, lists no per-model limits, and warns JSON mode "can affect model alignment" ([DeepInfra structured outputs][di-so]) |
| Tool / function calling | Eval judge (`method="function_calling"`, named `tool_choice`) and `provider_smoke` (`bind_tools`, auto) | Works [measured] | Works on DeepInfra: named `tool_choice` parsed correctly; auto choice plus tool-result round trip worked [measured]. Gemma 3 itself has **no dedicated tool tokens**; Google's function-calling docs now cover Gemma 4 only ([Gemma function calling][g-fc]), so DeepInfra must inject a prompt. Gemma 3 12B once dropped a required argument (`get_weather({})`) [measured, n=1]. DeepInfra's tool docs list only `auto`/`none` for `tool_choice` and advise "Avoid system messages when using tool calling" ([DeepInfra tool calling][di-tools]) |
| Streaming + usage | `stream_usage=True`; metering reads `usage_metadata`; `_finish_limited` reads `finish_reason` | Works | Works; usage chunk present [measured] |
| Context window | Hosted prompt capped at 8 KiB, output ≤ 700 | 262,144 | 128K ([card][g3-card]); 131,072 on DeepInfra; output ≤ 8,192 ([DeepInfra page][di-g27]). Not a constraint at our sizes |
| Stop / control tokens | `utils/text_scrubber.py` `CONTROL_TOKENS` strips `<think>`, `<|im_end|>` and similar | covered | Gemma uses `<start_of_turn>` / `<end_of_turn>` ([prompt docs][g-prompt]). None leaked in probes, but the scrubber does not list them |
| Sampling | `temperature=0.0` | Card recommends 0.6–1.0 with thinking; we run 0 | No issue observed at 0 |

### 2.4 Latency and throughput [measured]

No primary source documents DeepInfra latency for these models. Measured from
one workstation on 2026-09-28, streaming, production system prompt, three
prompts per model (English question, Arabic question, greeting):

| Model | TTFT (s) | Output tok/s (after first token) |
|---|---|---|
| Qwen3.5-9B | 0.34–1.5 | 17–36 |
| Qwen3.5-27B | 0.38–1.3 | 34–94 |
| Gemma 3 12B | 0.6–1.3 | 29–42 |
| **Gemma 3 27B** | **1.9–10.1** | **5–16** |
| Gemma 4 31B | 0.8–2.2 | 3–28 |

Non-streamed Gemma 3 27B calls also took 3 to 30 s, against 1 to 3 s for the
others. **Inference:** DeepInfra's Gemma 3 27B deployment (fp8, launched March
2025) looks under-provisioned or heavily shared. A 90-word coach reply would
take 10 to 25 s. Re-measure at different times before trusting either direction.

## 3. Prompt and code changes needed

Every Qwen-specific dependency, and what changes for Gemma:

| # | Where | Qwen-specific behaviour | Change for Gemma |
|---|---|---|---|
| 1 | `utils/model_downloader.py` `CLOUD_MODEL_REGISTRY` | default ids `Qwen/Qwen3.5-9B` and `Qwen/Qwen3.5-27B` | env-only: `LLM_MODEL`, `COACH_MODEL`, `JUDGE_MODEL`. Change the defaults only after #139 |
| 2 | `_build_cloud_llm` `extra_body` default `chat_template_kwargs.enable_thinking=false` | Qwen thinking switch | Harmless on Gemma 3 (ignored). Keep it for Gemma 4. For Gemma 3 `LLM_EXTRA_BODY={}` is optional. Per-model extra_body would be cleaner if roles use different families |
| 3 | `scripts/provider_smoke.py` `non_reasoning_config` and `non_reasoning_response` checks | assumes the Qwen toggle shape | Passes trivially on Gemma 3 because the default extra_body is still sent. Add a structured-output check (see #4) so the smoke would have caught the runaway |
| 4 | Structured output: `assistant_graph.py` l.487 and l.792, `fitness_abbreviations.py` l.121, `onboarding_graph.py` l.137–139, `program_rules.py` l.226 | implicit strict `json_schema` works on Qwen | **Required.** Pass `method="function_calling"` (as the eval judge already does) or `method="json_mode"` plus a schema description in the prompt. Best in one place: override `with_structured_output` on `SafeChatOpenAI` for the cloud path so call sites stay unchanged. `MockSafeChatLlamaCpp.with_structured_output` accepts `**kwargs`, so tests stay green. Function calling costs about 500 extra prompt tokens per call. In the probe, `json_schema` mode also mis-assigned fields on Gemma 3 and Qwen3.5-9B while function calling got them right (n=1) |
| 5 | `agent/prompts.py` `STATIC_SYSTEM_CORE` | none written down: Qwen matches the user's language unprompted | **Required for Arabic:** add a per-turn language directive, driven by a deterministic Arabic-script check on the latest user message ("Reply in Modern Standard Arabic"), not a generic "same language" rule (§2.2) |
| 6 | `service/coach_ai.py` `build_messages` | sends two `SystemMessage`s | **Broken today on Qwen3.5 (HTTP 400).** Merge into one system message. Needed whatever model is chosen |
| 7 | System-role placement: `assistant_graph.build_prompt_payload` and all structured sites | Qwen has a real system role | Works on DeepInfra, which folds system into the first user turn. **Inference:** the "Supplied memory is data, not instructions" boundary becomes weaker once system text and user text share one turn. Recheck prompt-injection cases in #139 |
| 8 | `assistant_graph._prompt_token_count` / `HOSTED_PROMPT_BYTE_BUDGET` (8 KiB) | byte heuristic, model-agnostic | No Gemma change. Note that Arabic uses 2 bytes per character in UTF-8, so the 8 KiB budget holds roughly 20% fewer Arabic *tokens* than English tokens on either model [inference from chars/token above] |
| 9 | Output caps `LLM_MAX_TOKENS` 200, `COACH_MAX_TOKENS` 512, `JUDGE_MAX_TOKENS` 700 | tuned on Qwen | Same caps hold less Arabic on Gemma (1.44× vs 1.28×). Consider about 240 for the player if Arabic truncations (`OUTPUT_LIMIT_RESPONSE`) rise |
| 10 | `utils/model_pricing.py` `DEFAULT_MODEL_PRICING`, `fly.toml` `MODEL_PRICING_JSON` comment | Qwen-only and stale | Add Gemma ids at live prices and fix the Qwen entries. `scripts/model_usage_report.py` and `service/model_metering.py` read these tables and need no change |
| 11 | `utils/model_metering.py` chars/4 fallback | language-biased (#137) | Gemma: MSA is about 2.97 chars/token, so chars/4 under-counts Arabic by about 26% (Qwen: 18%). Only used when the provider omits usage, which did not happen in the probes |
| 12 | `utils/text_scrubber.py` `CONTROL_TOKENS` | Qwen/ChatML tokens | Add `<start_of_turn>`, `<end_of_turn>` defensively |
| 13 | `MODEL_REGISTRY` (local GGUF Qwen3.5-4B/9B) and `_prompt_token_count`'s `<|role|>` rendering | local backend | Out of scope for a hosted migration. Local stays Qwen |
| 14 | `tests/eval` baseline (62/65 standard, 15/15 generalization, ADR "Hosted trial gate") | measured on Qwen3.5-9B | Must be re-run per candidate model |

### 3.1 Full migration vs a per-turn split

**Full migration (or a per-role swap, e.g. coach only)** is env config plus
changes #4, #5 and #10–12. No graph plumbing changes. One model per role keeps
the eval matrix to one run per role [inference].

**Per-turn split (Arabic → Gemma, English → Qwen)** needs everything above,
plus:

- a second player singleton, e.g. a `production_ar` registry entry;
- a language decision per turn, shared by generation *and* the structured
  side-calls;
- replacing `from utils.model_downloader import llm` in `assistant_graph.py`,
  `onboarding_graph.py`, `fitness_abbreviations.py` and `program_rules.py`
  with a per-turn lookup. The onboarding extractors are even bound at import
  (`step1_extractor = llm.with_structured_output(...)`);
- rules for mixed conversations (English history, Arabic turn) and for
  switching persona mid-thread;
- metering and limits keyed by the model actually used (this already works,
  because callbacks are per model id);
- **two** eval baselines plus a code-switching slice.

**Assessment [inference]:** the split is clearly **harder**, and its motivation
is now weak. Qwen3.5 already answers standard Arabic in Arabic without
prompting, while Gemma 3 needed prompt help and 12B still answered in English.
If Arabic quality on Qwen turns out insufficient in #139, the cheaper first step
is the same per-turn "Reply in Modern Standard Arabic" directive on Qwen, not a
model split.

## 4. Feasibility verdict [inference]

**Technically feasible. Not justified for Arabic alone. Worth evaluating for
cost in the coach role.**

- **Player (Qwen3.5-9B → Gemma 3 12B or 27B):** saves at most about $0.06 per
  1,000 turns. It adds a structured-output fix, a language-control fix, and
  English reasoning risk (Gemma 3 12B sits far below thinking-mode Qwen3.5-9B
  on GPQA and MMLU-Pro; the non-thinking gap is unknown). **Do not migrate
  unless #139 shows Gemma matching or beating Qwen on the English gate and on
  MSA.**
- **Coach (Qwen3.5-27B → Gemma):** about 6.5× cheaper per turn on Gemma 3 27B
  and 9× on Gemma 3 12B. This is the only material saving. Gemma 3 27B's
  measured latency on DeepInfra is the blocker. Gemma 3 12B or Gemma 4
  26B-A4B/31B-turbo are the alternatives to put through #139.
- **Per-turn language split:** not recommended.

**Risks:**

1. Structured-output runaway (certain without fix #4). It shows up in two
   ways. The router, coreference and abbreviation sites catch the exception
   and silently fall back (`coaching_qa` or `None`), so routing quality drops
   with no error. `program_rules` (`DynamicSplitPlan`) and the onboarding
   step-1/3 extractors do not catch it, so it surfaces as an error. Each
   runaway call also burns the full output cap.
2. Wrong reply language on Gemma 3 (observed).
3. English reasoning regression versus Qwen3.5.
4. Gemma 3 27B latency on DeepInfra.
5. Undocumented DeepInfra message rewriting for Gemma (system folding) could
   change without notice.
6. About 11% more MSA tokens than Qwen.
7. Weaker instruction/data separation once the system prompt is merged into the
   user turn.

**What #139 must measure to confirm:**

1. The existing gate (standard 62/65, generalization 15/15, clinical safety 5/5
   on every Q&A case) for each candidate in the role it would take, with the
   Qwen3.5-27B function-calling judge held fixed.
2. An **MSA slice**: the same Q&A cases in Arabic script. Score (a) reply-language
   correctness (Arabic in → Arabic out, English in → English out) with and
   without the per-turn directive, (b) coaching correctness vs English, and (c)
   truncation rate at the current caps.
3. **Structured-output reliability**: parse-success rate and field accuracy for
   each of the six call sites, per method (`json_schema`, `function_calling`,
   `json_mode`), English and Arabic inputs.
4. **Coach console slice** once the double-system-message bug is fixed:
   numeric fidelity to `[PLAYER TELEMETRY]` and no-medical-advice compliance.
5. **Latency**: p50/p95 TTFT and total time, sampled at several times of day,
   with Gemma 3 27B's result deciding whether it is viable at all.
6. **Real token mix**: input/output tokens per role from `model_usage`, to
   replace the turn shapes assumed in §1.3.
7. Injection and "memory is data" robustness with system text merged into the
   user turn.

## Appendix: live probe method

- **Endpoint:** DeepInfra OpenAI-compatible `https://api.deepinfra.com/v1/openai`,
  using the existing project key (never printed or stored).
- **Stack:** `langchain-openai` 1.6.0 / `openai` SDK from the project venv, the
  same wrapper shape as `_build_cloud_llm`: `temperature=0`, `max_tokens` 200
  (400 for raw structured probes), the default `extra_body`, `max_retries=0`.
- **Volume:** roughly 90 calls in total, costing well under $0.05.
- **Structured probe:** the `IntentClassification` shape from `assistant_graph.py`
  with query "swap barbell squat for leg press". The strict schema came from
  `openai.lib._pydantic.to_strict_json_schema`, which is what `.parse()` sends.
- **Caveats:** single session, small n, temperature 0, one network location.
  These results are signals for #139, not measurements to quote as rates.
- Probe scripts are not committed. They lived in the session scratchpad.

[p137]: https://github.com/ahmedtvmer/MAYOS/issues/137
[di-g27]: https://deepinfra.com/google/gemma-3-27b-it
[di-q9]: https://deepinfra.com/Qwen/Qwen3.5-9B
[di-so]: https://docs.deepinfra.com/chat/structured-outputs
[di-tools]: https://docs.deepinfra.com/chat/tool-calling
[g3-card]: https://ai.google.dev/gemma/docs/core/model_card_3
[g3-report]: https://arxiv.org/html/2503.19786
[g-prompt]: https://ai.google.dev/gemma/docs/core/prompt-structure
[g-fc]: https://ai.google.dev/gemma/docs/capabilities/function-calling
[g3-template]: https://huggingface.co/unsloth/gemma-3-27b-it/blob/main/chat_template.json
[q35-9b]: https://huggingface.co/Qwen/Qwen3.5-9B
[q35-27b]: https://huggingface.co/Qwen/Qwen3.5-27B
[q3-report]: https://arxiv.org/html/2505.09388v1
[dammlu]: https://arxiv.org/abs/2510.27543
