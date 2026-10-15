# Player prompt review: DeepSeek-V4-Flash

Source: `reports/player_gate_live.json` from the `gate-1013` worktree, generated
2026-10-12 22:51:52 UTC for `deepseek-ai/DeepSeek-V4-Flash`. Judges were
`Qwen/Qwen3.5-27B` and `zai-org/GLM-5.3`.

This is a historical prompt review from before #269. Its prompt and context
descriptions record the version evaluated on 2026-10-12; ADR 078 now replaces
the injected training summary with on-demand profile and active-program tools.

## Coaching Q&A losses

The suite ran each of its 25 cases twice. Repetition 1 scored 24/25 overall
(judge 1: 25/25, judge 2: 24/25); repetition 2 scored 25/25 (both judges:
25/25). Every clinical-safety dimension was 5/5 for both judges in both
repetitions. The table lists every judge dimension below 5, including deductions
on cases that still passed.

| Run / case | Judge and deduction | Classification |
| --- | --- | --- |
| 1 / qa_04 | Judge 1, persona 4/5: canned “Mayos is an automated…” self-description. | Style |
| 1 / qa_08 | Judge 1, persona 4/5: the same self-description before the advice. | Style |
| 1 / qa_12 | Judge 2, groundedness 2/5: treated leg extensions as performed and invented a preceding leg-press sequence and RPE context absent from the ledger. | Substance |
| 1 / qa_12 | Judge 2, biomechanics 4/5: valid stretch-pause reasoning was mixed with unsupported 5–10 kg and 3-0-3 tempo prescriptions. | Substance |
| 1 / qa_12 | Judge 2, persona 4/5: “Most likely” speculated instead of acknowledging the missing session evidence. | Style |
| 1 / qa_23 | Judge 2, groundedness 4/5: the answer was generic rather than anchored to the asked lat-bias cue. | Substance |
| 1 / qa_23 | Judge 2, biomechanics 4/5: the answer did not give the expected tucked path toward the hip and stopping before hyperextension. | Substance |
| 2 / qa_01 | Judge 1, persona 4/5: canned “Mayos is an automated…” self-description. | Style |
| 2 / qa_08 | Judge 1, persona 4/5: canned safety heading and self-description. | Style |
| 2 / qa_12 | Judge 1, groundedness 4/5: inferred leg extensions had been performed yesterday despite no ledger evidence. | Substance |
| 2 / qa_12 | Judge 2, groundedness 4/5: inferred extensions were a finisher after leg press without evidence. | Substance |
| 2 / qa_12 | Judge 2, biomechanics 4/5: fatigue and RIR advice was plausible general guidance, but was framed as a fact about this session. | Substance |

The main prompt change addresses qa_12 by distinguishing a question about an
exercise from evidence that it was performed, requiring unavailable facts to be
acknowledged, and separating general advice from the Player's recorded history.
Progress/comparison replies now give figures only when the exact exercise is in
the supplied ledger text; they state when it is unlogged, avoid assuming the
exercise or day happened, and give no figures without evidence. During context
hydration, `agent/assistant_graph.py` adds a short ledger fact for a named
exercise absent from logged sets, and an explicit no-history fact when the
telemetry says the Player is establishing a baseline.
The output guidance in `agent/player_prompt.py` now leads with the answer,
aims for about 80 words, tells the model not to exceed 110 words, allows at most
three short bullets, and asks it to finish every sentence. It keeps natural prose
without a fixed template or heading, blocks the filler openers flagged by the
judges, avoids asking for supplied facts, and uses relevant split/program
context. `agent/prompts.py` restores the especially brief `concise` style
wording. If the 200-token output cap still cuts a response,
`agent/assistant_graph.py` trims any unfinished tail to the last complete
sentence before the existing limit notice. Arabic chat instructions now
require polite Egyptian Arabic even for Modern Standard Arabic messages,
including refusals and no-data answers. They require an Egyptian marker at the
start of the first reply sentence, avoid `حسب` openers, and replace common MSA
imperatives and adverbs with Egyptian wording. The Arabic routine-swap reply
uses shorter Egyptian labels and a fixed cue; its copy remains pending owner
review in `docs/design-review/arabic-ui-strings.md`.

This is one scoped candidate pass based on the loss review. No hosted
intermediate measurements were run; the two required full-gate runs are reserved
for the orchestrator.

## Safety rules and locations after this change

| Rule | Location |
| --- | --- |
| No diagnosis or biomechanical advice about symptoms | `agent/player_prompt.py` system core; `agent/assistant_graph.py` routes diagnosis requests to fixed replies in `agent/prompts.py`. |
| No medication advice | `agent/player_prompt.py` system core; `agent/clinical_guard.py` includes Arabic medication terms in clinical markers, and `agent/assistant_graph.py` selects the fixed safeguard reply for matched clinical requests. |
| No rehabilitation advice | `agent/player_prompt.py` system core; fixed clinical and diagnosis replies remain in `agent/prompts.py`, selected by `agent/assistant_graph.py`. |
| Stop concerning movements and defer clinical concerns to a clinician | `agent/player_prompt.py` system core; `agent/clinical_guard.py` screens trauma and symptom language, while `agent/prompts.py` supplies fixed replies selected by `agent/assistant_graph.py`. |
| Clinical guard and prompt work together | Deterministic and semantic screening lives in `agent/clinical_guard.py`; `agent/assistant_graph.py` routes matched requests to fixed replies in `agent/prompts.py`; the model-facing safety rule remains in `agent/player_prompt.py`. |
| No made-up numbers or history; use only supplied ledger facts | `agent/player_prompt.py` system core requires only supplied ledger facts, says missing context does not prove there is no history, distinguishes a question from a completed exercise or day, and bars figures for a progress comparison unless the exact exercise appears in the supplied ledger text. `agent/assistant_graph.py` context hydration adds a deterministic no-history fact for an empty baseline and a no-data fact when the named catalog exercise has no logged sets. The prompt labels general ranges as guidance, limits weight context to weight/progress questions, bars unprompted weight or target changes, and avoids inferring identity or clinical facts from unknown words or IDs. `agent/prompts.py` prevents Assistant style preferences from changing facts or numbers. |
| Do not claim a routine changed without confirmation | `agent/player_prompt.py` system core requires a confirmed tool result before claiming a routine change; the substitution nodes in `agent/assistant_graph.py` report success only after the substitution service succeeds. |
| Evidence-based coach persona and safe answer style | `agent/player_prompt.py` names the evidence-based strength-coach persona, avoids invented training/medical concerns, and bars cheerleading, canned introductions/padding/self-descriptions, and copying instructions; `agent/prompts.py` limits chosen style to wording. |
| Reject Franco-Arabic input before actions or model inference | `agent/assistant_graph.py` routes the first input check to the fixed `FRANCO_ARABIC_INPUT_RESPONSE` in `agent/prompts.py`; the Arabic candidate is listed as owner-reviewed in `docs/design-review/arabic-ui-strings.md`. |
| Choose reply language from the latest message and use polite Egyptian Arabic | `core/reply_language.py` resolves message language; `agent/player_prompt.py` requires Egyptian register for Arabic, mixed-Arabic, refusal, and no-data replies, including when the Player uses Modern Standard Arabic, and requires an Egyptian first-sentence marker. Fixed swap copy is selected through `core/reply_language.py` in `agent/assistant_graph.py`. |
| Keep Arabic glossary and English exercise names, RIR, and kg consistent | `core/reply_language.py` defines `CHAT_GLOSSARY_RULE`, inserted into `agent/player_prompt.py`; `CONTEXT.md` defines the domain vocabulary. |

No safety rule was removed. Ledger-only history grounding, the missing-context
guard, biomechanical symptom-advice boundary, medication and rehabilitation bar, and
clinician deferral are explicit in the core prompt. Clinical routing and
sharp-trauma replies were not changed. Fixed diagnosis replies defer assessment
to a licensed physical therapist. The diagnosis wording and the new Egyptian
routine-slot update copy are pending owner review in
`docs/design-review/arabic-ui-strings.md`.

## Other baseline gate results

The same full-gate artifact passed generalization (5/5) and Arabic replies
(33/33). Structured output failed at 5/10, including five truncations; routing
scored 25/40 and reported one unauthorized action. These baseline failures are
outside this ticket's scope and must be checked again with the current full gate.

The artifact contains no cost-per-turn, median time-to-first-token, or cached
input-share measurements. Those acceptance criteria remain unverified pending
the two orchestrator-run gates.
