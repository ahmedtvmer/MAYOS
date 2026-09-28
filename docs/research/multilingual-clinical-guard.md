# Multilingual clinical guard: options (#136)

Research for [#136](https://github.com/ahmedtvmer/MAYOS/issues/136), part of the Arabic wayfinder [#135](https://github.com/ahmedtvmer/MAYOS/issues/135). Date: 2026-09-28.

**Scope (revised 2026-09-28):** the guard must detect injury and pain language in **Arabic script, as users naturally type it** (simple/standard Arabic, including Arabic mixed with English gym terms). Franco-Arabic (Arabizi) and Egyptian dialect are no longer targets. For Franco and any other language the guard cannot read, this note covers only **how the guard fails closed**. It does not evaluate how well anything detects Franco.

## TL;DR

1. **Today the guard fails open on Arabic.** `bge-small-en-v1.5` has an English WordPiece vocabulary, so Arabic falls back to single characters (`عندي ألم حاد` → `['ع','##ن','##د','##ي','ا','##ل','##م',…]`). Every Arabic sentence we tried scored 0.52–0.56 against the anchors, whether it described an injury or not. With the 0.70 threshold, **0 of 12 Arabic injury sentences were intercepted**. Arabic input with fewer than six words skips the embedding step completely, because none of the English lexical tokens match (`clinical_guard.py`, `word_count < 6 and not has_clinical_token`).
2. **No single embedding model is enough on its own.** Across all seven models, the Arabic fatigue and "burn" sentences scored as high as the real injuries. The English guard has the same weakness and handles it with regex tiers (Tier 0 plus the benign-fatigue bypass, ADR 002). Arabic needs the same layered design.
3. **Recommended shape:** a deterministic script gate, then an **Arabic Tier-0 lexicon on normalized text**, then an **Arabic benign-fatigue bypass**, then a **multilingual embedding with its own calibrated Arabic threshold**. Uncertain results and errors intercept. Anything the gate cannot read (Franco, other languages) gets a fixed fail-closed reply.
4. **Model choice for the Fly box (shared-cpu-1x, 2 GB):** `intfloat/multilingual-e5-small` is the practical pick. It is 384-dim, so it matches the existing `vec_exercises float[384]` schema. Latency matched bge-small in our run (about 21 ms vs 27 ms, one thread). It uses about 330 MB more RSS than bge-small. It separated Arabic clearly better than bge-small in our probe (AUC 0.90 vs 0.42 without the fatigue items). `bge-m3` separated best (AUC 0.96) but needed about 700 ms per query and about 2 GB of extra RSS, so it cannot run on the current machine.
5. **Translating to English first is not viable.** In a probe with `opus-mt-ar-en`, 6 of 12 Arabic injuries were mistranslated and slipped past the English guard. For example, "طقة" (pop) came out as "necklace", "ضعف" (weakness) as "twice as much", and "تنميل" (numbness) as "squeezing". Each translation cost about 0.5 s. NLLB is licensed CC-BY-NC and is "not intended … for medical domain".

## 1. How the guard works today

- `agent/clinical_guard.py` loads `EMBEDDING_MODEL` (default `BAAI/bge-small-en-v1.5`) once through `HuggingFaceEmbeddings` on CPU. It embeds 8 English anchor descriptions and flags a clause when its max cosine is ≥ 0.70. Before that step it applies an English benign-fatigue bypass (`RE_BENIGN_FATIGUE` without `RE_TRAUMA_SENSATIONS`) and an English short-input bypass (fewer than 6 words and no `_CLINICAL_LEXICAL_TOKENS`).
- `agent/assistant_graph.py` runs Tier 0 first (`RE_ACUTE_INJURY`, `RE_AMBIGUOUS_TRAUMA`, `RE_DIAGNOSIS`), all English regexes, and then calls the semantic guard per clause (`_classify_single_clause`, `_clinical_turn_metadata`). ADR 002 in `DECISIONS.md` records the tiered design and its latency budget (Tier 1 about 15 ms).
- **Coupling:** `EMBED_MODEL` is also imported by `assistant_graph.py` for exercise similarity search (`db.search_similar_exercises(EMBED_MODEL.embed_query(...))`). The vectors in `vec_exercises` are `float[384]` (`database/database_manager.py`, `EMBEDDING_DIM = 384`), seeded by `scripts/seed_vectors.py` with the same model. Swapping the shared model therefore means re-seeding, and a model with a different dimension also needs a schema change.
- **Fly box:** `fly.toml` (on `feat/web-into-app`, commit fcd665b) sets `[[vm]] size = "shared-cpu-1x"`, `memory = "2gb"`, `cpus = 1`, `cpu_kind = "shared"`, `MODEL_DEVICE = "cpu"`. `Dockerfile.fly` installs CPU-only torch and bakes `bge-small-en-v1.5` into the image. Fly documents shared-cpu-1x as a **baseline quota of 5 ms per 80 ms period (6.25%)**, with bursts up to 100% while a burst balance lasts (initial 5 s, max 500 s), and throttling for the rest of the period once the quota is used ([Fly docs: CPU performance](https://docs.fly.io/machines/cpu-performance/)). Sustained CPU is therefore about 1/16 of a core, and a model that costs hundreds of ms per query becomes multiple seconds once the burst balance runs out.

## 2. Candidate embedding models

Facts below come from model cards, HF Hub metadata and papers. The measurements come from our own probe (§3).

| Model | Params | Dim | Max len | Weights on disk (fp32) | Arabic in training? | License | Notes |
|---|---|---|---|---|---|---|---|
| `BAAI/bge-small-en-v1.5` (current) | 33M | 384 | 512 | 134 MB | No (English) | MIT | English vocab; Arabic → character pieces |
| `intfloat/multilingual-e5-small` | 118M | 384 | 512 | 471 MB (int8 ONNX 118 MB in repo) | Yes (xlm-r 100 langs; Mr.TyDi, MIRACL incl. ar) | MIT | Needs `"query: "` prefix; cosine scores cluster around 0.7–1.0 |
| `intfloat/multilingual-e5-base` | 278M | 768 | 512 | 1.11 GB (int8 ONNX 279 MB) | Yes | MIT | Same caveats as small |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 118M | 384 | 128 | 471 MB (int8 ONNX 118 MB) | Yes, "parallel data for 50+ languages" incl. ar | Apache-2.0 | Distilled from an English paraphrase model |
| `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | 278M | 768 | 128 | 1.11 GB | Yes, 50+ languages incl. ar | Apache-2.0 | |
| `sentence-transformers/LaBSE` | 471M | 768 | — | 1.88 GB | Yes, 109 languages | Apache-2.0 | Built for bitext; "works less well for … pairs that are not translations" |
| `BAAI/bge-m3` | 568M (XLM-R large, 24 layers) | 1024 | 8192 | 2.27 GB | Yes, "100+ working languages" | MIT | Also offers sparse and multi-vector modes |

Sources: HF model cards and Hub API for [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small), [multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base), [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [paraphrase-multilingual-mpnet-base-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2), [LaBSE](https://huggingface.co/sentence-transformers/LaBSE), and [bge-m3](https://huggingface.co/BAAI/bge-m3) (dimension, 8192 length and config.json: `hidden_size 1024`, `num_hidden_layers 24`, `XLMRobertaModel`). The e5 prefix rule and the score range are stated in the model card FAQ: "Yes, this is how the model is trained, otherwise you will see a performance degradation", and "Why does the cosine similarity scores distribute around 0.7 to 1.0? … we use a low temperature 0.01 for InfoNCE". The LaBSE limitation and the "trained on parallel data for 50+ languages" wording come from the [Sentence-Transformers pretrained models page](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html). The paraphrase models were trained with multilingual knowledge distillation ([Reimers & Gurevych 2020, arXiv:2004.09813](https://arxiv.org/abs/2004.09813)).

**Published Arabic quality (standard-Arabic retrieval, not injury detection):**

- MIRACL Arabic dev, nDCG@10: mE5-small **71.4**, mE5-base **71.6**, mE5-large 76.0 ([mE5 technical report, arXiv:2402.05672](https://arxiv.org/abs/2402.05672), Table 6). bge-m3 dense scores **78.4** ([M3-Embedding, arXiv:2402.03216](https://arxiv.org/abs/2402.03216), Table 1).
- ArabicMTEB, overall average ([Swan & ArabicMTEB, NAACL Findings 2025, arXiv:2411.01192](https://arxiv.org/abs/2411.01192), Table 5): LaBSE 49.45, Me5-small 55.06, Me5-base 55.29, Me5-large 61.65. The Arabic-specific Swan-Small (164M) reaches 57.33, but we found no public weights under the UBC-NLP HF org, and the GitHub link in the paper returned 404 on 2026-09-28, so it is not usable today.
- MIRACL and ArabicMTEB measure topical retrieval. Neither tests whether "my knee is swollen" sits closer to an injury anchor than "my muscles are tired" does, and that is the guard's actual job. Hence the probe below.

## 3. Our probe: Arabic injury vs. benign training talk

**Method (throwaway, not committed as code).** We wrote 12 Arabic-script injury sentences and 12 benign ones (including hard negatives for fatigue, burn and pump, plus a "best exercise to strengthen my knee" question), and 3 English sentences of each kind as a control. We scored each sentence the way production does: max cosine against the 8 production English anchors. We also tried Arabic renderings of those anchors and found no consistent gain, so they are not reported. Runs used `torch.set_num_threads(1)`, one model per process, on an i7-9850H laptop. **The RSS column is the peak process RSS minus the 805 MB taken by importing torch and sentence-transformers.** The local torch is a CUDA build, so absolute RSS on Fly (CPU torch) will be lower. Latency is the median single-query `encode` over 30 runs. The sentences are listed in the appendix. **Caveats:** n = 12/12, the sentences are author-written and not yet reviewed by the owner, and we never measured on the Fly machine. Treat the numbers as directional only.

| Model | Arabic AUC (all 12 neg) | Arabic AUC (excl. fatigue/burn) | FP at 100% Arabic recall (of 10, excl. fatigue/burn) | At the current 0.70 threshold: AR pos / AR neg / EN pos / EN neg flagged | p50 latency, 1 thread | Extra peak RSS |
|---|---|---|---|---|---|---|
| bge-small-en-v1.5 (current) | 0.43 | 0.42 | 10 | 0/12, 0/12, 2/3, 1/3 | 27 ms | ~160 MB |
| multilingual-e5-small | 0.79 | 0.90 | 4 | 12/12, 12/12, 3/3, 3/3 | 21 ms | ~490 MB |
| multilingual-e5-base | 0.83 | 0.93 | 5 | 12/12, 12/12, 3/3, 3/3 | 78 ms | ~750 MB |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.83 | 0.89 | 7 | 1/12, 1/12, 1/3, 0/3 | 20 ms | ~700 MB |
| paraphrase-multilingual-mpnet-base-v2 | 0.81 | 0.88 | 10 | 1/12, 1/12, 1/3, 0/3 | 58 ms | ~650 MB |
| LaBSE | 0.76 | 0.86 | 10 | 0/12, 0/12, 0/3, 0/3 | 59 ms | ~610 MB |
| bge-m3 | 0.87 | **0.96** | 4 | 0/12, 0/12, 0/3, 0/3 | **700 ms** | **~1,980 MB** |

What this shows:

- **The current guard is blind to Arabic.** bge-small-en's Arabic scores are flat (positives 0.516–0.559, negatives 0.516–0.555), and it does worse than chance.
- **The 0.70 threshold does not carry over.** Keep it with e5 and everything fires, English negatives included, because e5 scores cluster in 0.7–1.0. Keep it with bge-m3, LaBSE or the paraphrase models and almost nothing fires. Any model swap needs a threshold calibrated on labelled data, **per language**.
- **Fatigue and burn are the hardest Arabic negatives for every model.** "أشعر بحرقان في العضلة أثناء آخر التكرارات" (burning in the last reps) was the highest-scoring negative for all six multilingual models, and the fatigue sentence was in the top four for five of them. That mirrors the reason ADR 002 needed `RE_BENIGN_FATIGUE`. An Arabic fatigue bypass, guarded by an Arabic trauma lexicon, is required whichever model is used.
- **Even the best model is not clean.** With every Arabic injury caught, e5-small and bge-m3 still flag 4 of 10 benign sentences. The embedding tier alone cannot be both recall-safe and usable, so the lexicon tier has to carry the unambiguous cases.
- **Fit on the Fly box:** bge-m3 alone uses about 2 GB of extra RSS on a 2 GB machine, and about 700 ms at a full core becomes about 11 s at the 6.25% baseline once bursts run out. It is not viable without a larger VM. e5-small costs about the same latency as today, and about 330 MB more RSS than bge-small. It needs a memory check on the actual machine, but it plausibly fits.

## 4. Arabic-script regex lexicon: feasible, with normalization

It is feasible, and it is the tier that makes the design fail closed. Arabic orthography has specific traps that an English-style `\b word \b` regex gets wrong. We verified each one with Python `re`:

- **Clitics attach to the word.** The conjunction و/ف and the prepositions ب/ل/ك attach as prefixes, and possessive pronouns attach as suffixes (ركبتي = knee + my). `re.search(r"\bركب", "وركبتي")` → **no match**, while an unanchored `ركب` matches. Lexicon entries therefore need an optional-prefix and optional-suffix pattern around a stem, not word boundaries.
- **Diacritics break matches.** `re.search(r"\bركبتي\b", "رُكبتي")` → no match, because the damma is a combining mark and is not `\w` (`'َ'.isalnum()` is `False`). Strip harakat before matching.
- **Tatweel (ـ) breaks matches.** `ركـــبتي` fails to match `ركبتي`. Strip U+0640.
- **Spelling variation is normal.** أ/إ/آ/ا, ى/ي and ة/ه are used interchangeably in typed text. `ألم` (pain) is very often typed `الم`, which is the same string as the definite article "ال" + م and the word "لم". CAMeL Tools provides standard normalizers for exactly these cases (`normalize_alef_ar`, `normalize_alef_maksura_ar`, `normalize_teh_marbuta_ar`, `normalize_unicode`, plus dediacritization; see the [CAMeL Tools normalize docs](https://camel-tools.readthedocs.io/en/latest/api/utils/normalize.html)). Normalize both the lexicon and the input the same way. Collisions such as الم should only intercept alongside a body-part term, the same way Tier 0b gates ambiguous English tokens.
- **Code-switching:** mixed Arabic/English text needs both lexicons run on the same clause, for example "عندي sharp pain في الركبة". The existing English Tier 0 already catches the English part, so the Arabic lexicon only has to cover Arabic tokens.
- **Size:** a starter lexicon is modest. It needs pain and injury verbs and nouns (ألم/وجع/يؤلم/يوجع، تمزق/مزقت/قطع، التواء/ملتوي، خلع، كسر، تورم/منتفخ/ورم، تنميل/خدر/وخز، طقة/فرقعة/طقطقة، حاد، لا أستطيع تحريك), a body-structure list (ركبة، كتف، كوع، رسغ، ظهر، رقبة، ورك، كاحل، وتر، رباط، غضروف، فقرات), and the fatigue bypass terms (تعب/متعب/تعبان، إرهاق، حرقان، بامب، شد عضلي بعد التمرين). Following the #135 process, the owner (a native speaker) should review it and pin it with tests in the same style as `tests/test_clinical_semantic_guard.py`.

## 5. Translating to English first: failure modes

We translated the 24 Arabic sentences with `Helsinki-NLP/opus-mt-ar-en` (Apache-2.0, 308 MB; [model card](https://huggingface.co/Helsinki-NLP/opus-mt-ar-en)), then ran the **current** English Tier 0a regex and semantic guard on the output:

- **6 of 12 injuries missed, i.e. fail-open.** Examples: "شعرت بطقة في ركبتي أثناء السكوات" → "I felt a necklace in my knees during the silence." "سمعت صوت فرقعة في كتفي وبعدها ضعف" → "I heard a pop in my shoulder, and then twice as much." "أحس بوخز كهربائي ينزل في رجلي" → "I feel an electric prick coming down in my leg" (0.698, just under 0.70). "تنميل" (numbness) came out as "squeezing", so Tier 0's `numb|tingling` never saw it.
- **Gym terms get mangled.** "البنش" became "penny" or "pinch", "السكوات" became "silence", "الديدليفت" became "Dudleft", "بامب" became "pulse", and "امبارح" became "cheerleader". Users keep exercise names in English or transliterate them (#135), and a general-domain MT model has never seen these forms.
- **False positives shift instead of disappearing.** "حرقان … آخر التكرارات" → "a couple of muscle burns". The word "burns" slips past `RE_BENIGN_FATIGUE` (`\bburn\b`), so the benign sentence was intercepted.
- **Cost:** a median of **526 ms** per sentence on one thread, over 20× the embedding tier. At the Fly 6.25% baseline it becomes seconds. A hosted LLM translation adds a network dependency, and on timeout that dependency has to fail closed, which blocks every Arabic chat during an outage.
- **NLLB-200** covers `arb_Arab`, but its card says it "is not released for production deployment … not intended to be used with domain specific texts, such as medical domain" and it is licensed **CC-BY-NC-4.0** ([facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M)). That rules it out for this app.
- **The chain compounds errors.** The English guard's own misses carry over. For example "I have a severe pain in my shoulder when I raise my arm" (a correct translation) scored 0.673 and no Tier 0a pattern matched it, because `sharp pain` is covered and `severe pain` is not. Translate-first stacks the MT error rate on top of the English guard's error rate.

## 6. Failing closed on input the guard can't read (Franco and other languages)

Detection quality for Franco is out of scope. The requirement from #135 is that unreadable input must not reach coaching. Mechanisms:

- **Deterministic script gate first.** The gate runs before the guard and classifies the clause as follows:
  - **Arabic script:** any character in the Arabic blocks (U+0600–06FF, 0750–077F, 08A0–08FF, FB50–FDFF, FE70–FEFF). NFKC folds the presentation forms. These clauses take the Arabic path.
  - **English:** Latin text that the English path covers.
  - **Unsupported:** everything else.
- **Franco must not be treated as English.** Franco is Latin text that often mixes with English inside one sentence ([Darwish 2014, ANLP](https://aclanthology.org/W14-3629/): Arabizi "is often … mixed with English" and "uses numerals to represent Arabic letters"). Today it drops through the English path and fails open. A cheap, high-precision signal is a Latin token with an embedded Arabizi digit (`[a-z]*[235789][a-z]+`, as in "ta2et", "3ayez", "7asset"). When that signal fires, or no supported language is recognized, the guard should return a **fixed, non-coaching reply**. For example: it can't read this language, if you are in pain stop training and see a professional, and please write in Arabic or English. It should not pass the text to the model. Fail closed means the fallback leans toward interception.
- **Error paths must intercept.** If the Arabic path raises, or the model isn't loaded, return "clinical" (intercept) rather than letting the clause through. Today the model loads at import time, so a load failure stops the process. That is already closed at boot, but calls that fail at runtime also need the intercept default.
- **Short-input bypass:** the English "< 6 words and no clinical token → not clinical" shortcut is safe only because the English lexicon backs it. Arabic input must bypass it until the Arabic lexicon exists. Otherwise "ركبتي تؤلمني" (2 words) is never evaluated.

## 7. Options compared

| Option | Arabic recall | Fails closed? | Fly fit | Main risk |
|---|---|---|---|---|
| A. Keep bge-small-en (status quo) | ~0 (measured) | **No** | Yes | Arabic injuries reach coaching |
| B. Translate → English guard | ~50% in probe | No (fails open on mistranslation) | Poor (~0.5 s per sentence) | MT domain errors; NLLB licence |
| C. Swap shared model to multilingual-e5-small, recalibrate | Good ranking, noisy threshold | Only with lexicon and gate | Yes (384-dim; reseed vectors) | English threshold regression; fatigue false positives |
| D. bge-m3 | Best ranking | Only with lexicon and gate | **No** on 2 GB shared-cpu-1x | RAM and latency |
| E. Hosted LLM classifier for Arabic | Unmeasured | Only if timeout means intercept | Network-bound | Latency, cost, outage blocks Arabic (ADR 002 rejected per-message LLM evaluation) |
| **F (recommended). Script gate + Arabic lexicon (normalized) + Arabic fatigue bypass + e5-small tier with Arabic-calibrated threshold; unsupported → fixed reply** | Lexicon handles clear cases; embedding catches paraphrase | **Yes** | Yes | Needs a labelled Arabic set (owner-reviewed) for calibration and tests |

For F, one sub-choice is left open for the spec. Option (i) loads e5-small **alongside** bge-small only for the Arabic path: no reseed and no English regression, at roughly 450–500 MB more RAM. Option (ii) swaps the shared model: one model, but it needs a reseed of `vec_exercises` and re-tuning of the English 0.70 threshold and tests. We did not measure memory on the Fly machine for either. Also note the e5 ONNX int8 file (118 MB) in the model repo. The Sentence-Transformers docs describe `backend="onnx"` with dynamic int8 quantization for faster CPU inference ([efficiency docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)), which could shrink the RAM cost. Its effect on accuracy for this task is unmeasured.

## Appendix: probe sentences

Injury (Arabic): شعرت بطقة في ركبتي أثناء السكوات · عندي ألم حاد في كتفي عندما أرفع ذراعي · أشعر بتنميل في أصابعي بعد تمرين الظهر · ظهري يؤلمني جدا ولا أستطيع الحركة · ركبتي منتفخة وتؤلمني بعد التمرين · سمعت صوت فرقعة في كتفي وبعدها ضعف · أحس بوخز كهربائي ينزل في رجلي · أعتقد أنني مزقت عضلة الصدر في البنش · كوعي يوجعني كل ما أعمل باي · الم في الركبة من امبارح · رُكبتي تؤلمني · مفصل الكتف كأنه يخرج من مكانه

Benign (Arabic): أريد زيادة الوزن في البنش هذا الأسبوع · كم مجموعة أعمل للباي؟ · ممكن تغير تمرين الكتف بتمرين آخر؟ · عضلاتي متعبة بعد يوم الرجل لكن هذا طبيعي · أشعر بحرقان في العضلة أثناء آخر التكرارات · أنا تعبان اليوم هل أعمل تمرين خفيف؟ · ما هو أفضل تمرين لتقوية الركبة؟ · كم بروتين أحتاج في اليوم؟ · اعرض لي سجل تمرين الديدليفت · عندي ضغط في الجيم اليوم كان التمرين رائع · أريد برنامج لتضخيم الكتف · عضلة الصدر عندي فيها بامب قوي

"Fatigue/burn" in the tables means the 4th and 5th benign sentences.
