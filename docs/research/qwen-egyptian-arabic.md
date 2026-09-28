# Qwen3.5 Egyptian Arabic & Franco capability (#137)

Research for issue #137 (parent map #135, blocks #139). Researched 2026-09-28.

**Context.** The hosted assistant runs `Qwen/Qwen3.5-9B` (player chat) and
`Qwen/Qwen3.5-27B` (judge and coach) through DeepInfra's OpenAI-compatible
endpoint (`DEFAULT_CLOUD_API_BASE = "https://api.deepinfra.com/v1/openai"` and
`CLOUD_MODEL_REGISTRY` in `utils/model_downloader.py`; ADR in `DECISIONS.md`
names DeepInfra as the reference provider; `scripts/provider_smoke.py` builds
the same registry model). All paths refer to the `feat/web-into-app` branch.

Legend: **[doc]** means the source states it. **[measured]** means I measured it
here (method given). **[inference]** means my reading of the evidence, which no
source states.

## TL;DR

1. **No primary source reports any Egyptian Arabic or Franco result for
   Qwen3.5-9B or 27B.** The model cards claim "201 languages and dialects" and
   give only aggregate multilingual scores. The closest documented evidence is
   for Qwen3 and Qwen2.5 at 4B to 32B. It shows **good Arabic-script
   comprehension, weak Egyptian generation (the models drift to MSA), and
   near-chance results on Franco/Arabizi**.
2. **Token inflation vs English under the Qwen3.5 tokenizer** [measured]:
   Egyptian in Arabic script is about **1.3x**, MSA about **1.3x**, and Franco
   about **1.6x**. Qwen3.5 cut Arabic-script inflation from about 1.6x (Qwen3
   tokenizer) to about 1.3x. It did not help Franco much.
3. **DeepInfra hosts no Arabic-specialised model** (no Jais, ALLaM, Fanar,
   SILMA or Nile-Chat). The only same-provider alternative with **documented**
   better Egyptian results is the **Gemma family**: `google/gemma-3-27b-it` at
   $0.08/$0.16 per 1M tokens (in/out) and `google/gemma-3-12b-it` at $0.05/$0.15.
   Gemma 4 and Gemini are plausible upgrades, but no source documents their
   Egyptian-dialect results.
4. Side finding: DeepInfra's live price for **Qwen3.5-27B output is $2.60/M**,
   but `utils/model_pricing.py` (`DEFAULT_MODEL_PRICING`) and the `fly.toml`
   comment assume **$0.90/M**. Metering therefore under-reports coach and judge
   spend about 2.9x on output. The 9B default ($0.10/$0.30) is higher than the
   live $0.10/$0.15.

## 1. What primary sources say about Egyptian Arabic and Franco

### Qwen3.5 (the deployed models)

- The model cards claim "Expanded support to 201 languages and dialects, enabling
  inclusive, worldwide deployment with nuanced cultural and regional
  understanding." [doc] ([Qwen3.5-9B card][q35-9b], [Qwen3.5-27B card][q35-27b],
  [Qwen3.5 README][q35-readme]). **Neither card names Arabic, Egyptian or any
  dialect**, and neither gives per-language scores.
- Aggregate multilingual scores [doc]:

  | Benchmark | Qwen3.5-9B | Qwen3.5-27B |
  |---|---:|---:|
  | MMMLU | 81.2 | 85.9 |
  | MMLU-ProX | 76.3 | 82.2 |
  | INCLUDE | 75.6 | 81.6 |
  | NOVA-63 | 55.9 | 58.1 |
  | WMT24++ | 72.6 | 77.6 |
  | MAXIFE | 83.4 | 88.0 |

  These tests average over many languages and use MSA-style Arabic. They say
  nothing about dialect or Latin-script Arabic. [inference]
- I found **no third-party dialect benchmark (AraDiCE, DialectalArabicMMLU,
  Nile-Chat's EgyptianBench, ArabCulture-Dialogue) that evaluates any Qwen3.5
  model**. The newest Qwen versions in those papers are Qwen3-4B and Qwen3-8B.

### Qwen3 (closest documented predecessor)

- The Qwen3 language list explicitly includes Egyptian: "Arabic (Standard, Najdi,
  Levantine, Egyptian, Moroccan, Mesopotamian, Ta'izzi-Adeni, Tunisian)" [doc]
  ([Qwen3 blog][q3-blog]). Qwen3.5 extends that coverage from 119 to 201
  languages [doc] ([Qwen3.5-Omni report §tokenizer][q35-omni]).
- **Arabic (MSA) scores**, Qwen3 technical report Table 28 [doc]
  ([arXiv 2505.09388][q3-report]). In non-thinking mode, which is how MAYOS runs
  (`enable_thinking=false`):

  | Model (non-thinking) | MLogiQA | INCLUDE | MMMLU | Avg |
  |---|---:|---:|---:|---:|
  | Qwen3-8B | 45.0 | 58.9 | 64.6 | 39.6 |
  | Qwen3-14B | 52.5 | 60.7 | 69.5 | 45.9 |
  | Qwen3-32B | 55.0 | 69.6 | 75.7 | 49.8 |
  | Gemma-3-27B-IT | 56.2 | 62.5 | 74.4 | 48.5 |

  Thinking mode scores much higher. For example, Qwen3-8B reaches 74.4 on
  MMMLU-ar. The deployed configuration does not get that uplift. [doc numbers;
  applying them to MAYOS is inference]
- **Belebele reading comprehension** covers the Afro-Asiatic group, which
  includes `arb_Arab`, `apc_Arab`, `acm_Arab`, `ary_Arab`, `ars_Arab` and one
  code printed as `erz_Arab`. That code is presumably `arz_Arab`, Egyptian; I
  read it as a typo [inference]. Group averages from Table 37 [doc]: Qwen3-14B
  non-thinking 80.1, Qwen3-32B non-thinking 82.3, **Gemma-3-27B-IT 85.9**. The
  report gives no per-dialect split.
- **DialectalArabicMMLU** (MMLU-Redux translated by hand into five dialects;
  random chance is 25%) [doc] ([arXiv 2510.27543][dammlu], Table 5):
  **Qwen3-4B-Instruct scores EGY 28.7, MSA 31.2, ENG 65.5.** That is
  essentially chance in both Arabic forms, against 65.5 in English. For
  comparison, gemma-3-12b-it scores EGY 61.5 and MSA 62.6. Qwen3-4B is much
  smaller than 9B, and the gap may partly reflect answer-format failures, so
  treat this as a warning sign rather than a verdict on 9B. [inference]
- **ArabCulture-Dialogue** covers 7-9B models across Arab dialects, not only
  Egyptian [doc] ([arXiv 2605.00119][arabculture]):
  - Qwen3-8B "capable of generating valid MSA translations, but fail[s] to
    generate dialectal outputs". Its mean ALDi dialectness on MSA-to-dialect
    translation is 0.10 zero-shot. In dialect steering, GlotLID gives it 0.041
    strict dialect accuracy, against 0.164 for Gemma-2-9B and 0.36 for ALLaM-7B
    (Tables 3 and 4).
  - Cultural MCQ accuracy for Qwen-3-8B is 0.35-0.38, **about random (0.333)**.
    Gemma-2-9B-it scores 0.61-0.71 (Table 2).

  **Inference:** asked to reply in Egyptian, a Qwen3-class 8B model tends to
  answer in MSA or stilted mixed Arabic. That is the most direct documented
  signal on *writing* Egyptian.

### Qwen2.5 (Egyptian and Franco specifically)

- **Nile-Chat / EgyptianBench** (MBZUAI-Paris, ArabicNLP 2025) is the only
  primary source that tests **Egyptian in both Arabic and Latin (Franco)
  script** [doc] ([arXiv 2507.04569][nilechat]). Tables 1 and 2:

  | Model | EgyMMLU (ar) | Belebele_arz | EgyHellaSwag (ar) | EgyAlpacaEval (ar, gen.) | Arabic-to-Franco translit. BLEU | EgyHellaSwag **Latin** | EgyPIQA **Latin** | EgyWinoGrande **Latin** |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|
  | Qwen2.5-7B-Instruct | 45.74 | 64.22 | 45.47 | 58.80 | 2.74 | 30.51 | 51.88 | 50.95 |
  | Qwen2.5-14B-Instruct | 60.81 | 72.33 | 55.84 | 71.35 | 4.07 | 33.49 | 52.87 | 53.41 |
  | gemma-3-12b-it | 61.55 | 77.00 | 49.49 | **92.61** | 2.77 | 37.52 | 53.14 | 51.19 |
  | Nile-Chat-12B | 62.59 | 79.44 | 64.04 | 95.56 | 52.21 | 53.71 | 65.10 | 59.98 |

  The Latin-script tasks have 4 choices for HellaSwag and 2 for PIQA and
  WinoGrande, so chance is 25%, 50% and 50%. **Qwen2.5 is at or near chance on
  every Franco benchmark.** The authors conclude that "existing LLMs
  underrepresent or overlook the Latin script" [doc].
- **AraDiCE** tests MMLU and PIQA in MSA, Egyptian and Levantine [doc]
  ([arXiv 2409.11404][aradice]). "The Qwen2.5 7B model, while less competitive
  in MMLU, performs better on PIQA for Levantine and Egyptian". Arabic-centric
  models such as Fanar and Jais lead on Egyptian MMLU. The paper gives its
  per-model numbers only in a figure (Fig. 10).

### Net assessment for 9B and 27B [inference]

- **Understanding Egyptian in Arabic script is probably adequate** for short
  gym chat. The evidence is strong Belebele results for the Qwen3 family, and
  Qwen2.5-14B already at 72 on Belebele_arz. 27B should be better than 9B.
- **Writing natural Egyptian is the weak point.** Qwen3-8B defaults to MSA,
  and Gemma beats Qwen on Egyptian generation (EgyAlpacaEval 92.6 vs 71.4).
  Running with thinking disabled removes the reasoning uplift the Qwen3 report
  shows.
- **Franco is the weakest point.** Every documented Qwen result on Latin-script
  Egyptian is near chance, and transliteration BLEU is below 5. The Qwen3.5 card
  makes no claim that fixes this. Expect partial comprehension of common Franco
  phrases and poor Franco generation.
- None of this replaces an in-domain eval. A small Egyptian and Franco set
  added to `tests/eval` (see #139) is the only way to confirm the deployed 9B
  and 27B behaviour.

## 2. Token inflation under the Qwen3.5 tokenizer

**Documented:** the Qwen3.5 tokenizer "adopts byte-level byte-pair encoding with
a vocabulary size of 250k (up from 150k), improving encoding and decoding
efficiency by 10–60% across most languages" [doc] ([Qwen3.5-Omni report][q35-omni]).
The 9B and 27B cards list a padded embedding size of 248,320 [doc].

**Method [measured]:**

- Downloaded `tokenizer.json` from `Qwen/Qwen3.5-9B` and `Qwen/Qwen3.5-27B` on
  Hugging Face. The two files are byte-identical (sha256 `5f9e4d49…`, vocab
  248,070 incl. added tokens). For comparison I also downloaded `Qwen/Qwen3-8B`.
- Counted with the `tokenizers` 0.23.2 library, using
  `Tokenizer.encode(text, add_special_tokens=False)`. Counts are raw text
  tokens with no chat template, so real billed prompts add a fixed overhead per
  message. The DeepInfra tokenizer is assumed to be the HF one [inference].
- **Corpus A, domain sample:** 12 gym-assistant sentences that I wrote, each in
  four parallel versions: English, MSA, Egyptian in Arabic script, and Egyptian
  in Franco with the common numeral convention (3=ع, 7=ح, 2=ء). The sentences
  are listed in the appendix. It is a small set written by one author, so
  expect ±10% noise.
- **Corpus B, standard parallel text:** 219 unique Belebele/FLORES passages from
  `facebook/belebele` (test split, first 400 rows via the HF datasets-server)
  that exist in `eng_Latn`, `arb_Arab` and `arz_Arab`. These are professional
  translations. Belebele has no Franco config.

**Results:**

| Text | Qwen3.5 tokens (ratio vs EN) | Qwen3 tokens (ratio vs EN) |
|---|---:|---:|
| A: English | 140 (1.00x) | 141 (1.00x) |
| A: MSA | 185 (**1.32x**) | 216 (1.53x) |
| A: Egyptian, Arabic script | 183 (**1.31x**) | 206 (1.46x) |
| A: Franco/Arabizi | 226 (**1.61x**) | 234 (1.66x) |
| B: English (FLORES) | 21,824 (1.00x) | 21,881 (1.00x) |
| B: MSA `arb_Arab` | 27,923 (**1.28x**) | 35,086 (1.60x) |
| B: Egyptian `arz_Arab` | 28,724 (**1.32x**) | 35,299 (1.61x) |

Tokens per whitespace word on Corpus A with Qwen3.5 [measured]: English 1.20,
MSA 1.80, Egyptian 2.10, Franco 2.22. Arabic words carry clitics, so
tokens per *meaning* (the ratio column) is the fairer figure.

Franco breaks into short Latin fragments with numerals as separate tokens. For
example, `rokbety betewga3ny` becomes `ro|kb|ety| bet|ew|ga|3|ny`. The bigger
vocabulary did not learn Franco word pieces: the Qwen3 to Qwen3.5 gain is 3%
for Franco against about 18% for Arabic script [measured].

**What this means for MAYOS [inference]:**

- An Egyptian turn costs about 1.3x the tokens of the same English turn, and a
  Franco turn about 1.6x. At the 9B's $0.10/$0.15 per 1M tokens, the absolute
  cost stays negligible.
- **The per-account `MODEL_DAILY_TOKEN_LIMIT` runs out about 1.3x (Arabic) or
  1.6x (Franco) faster.**
- **The fixed output budgets hold less content in Arabic.** The player gets 200
  output tokens, about 150 English-equivalent tokens in Egyptian and about 125
  in Franco. Egyptian replies are more likely to be cut off than English ones
  at the same `LLM_MAX_TOKENS`.
- The chars/4 fallback estimator in metering (ADR 038) is biased by language.
  It is used only when the provider omits usage metadata. On Corpus B with the
  Qwen3.5 tokenizer [measured], `arz_Arab` has 3.15 chars per token (MSA
  3.29), so chars/4 undercounts Egyptian by about 21%. English has 4.82 chars
  per token, so chars/4 overcounts English by about 20%.

## 3. Alternatives on DeepInfra that are stronger at Egyptian Arabic

Prices come from DeepInfra's public model catalogue API
(`https://api.deepinfra.com/models/list`, fetched 2026-09-28), in USD per 1M
tokens (input / output) [doc]. Treat them as a snapshot, since DeepInfra
changes prices.

**Not on DeepInfra** [doc, absent from the catalogue]: none of the models that
lead the Egyptian benchmarks above are listed, including Nile-Chat, Jais,
ALLaM, Fanar, SILMA, command-r7b-arabic and AceGPT. The only way to use them is
another provider or self-hosting.

| DeepInfra model | Price in/out | Evidence it beats Qwen on Egyptian | Status |
|---|---|---|---|
| `Qwen/Qwen3.5-9B` (current player) | $0.10 / $0.15 | baseline | — |
| `Qwen/Qwen3.5-27B` (current judge/coach) | $0.26 / **$2.60** | baseline | — |
| `google/gemma-3-27b-it` | $0.08 / $0.16 | Belebele Afro-Asiatic 85.9 vs Qwen3-32B 82.3 ([Qwen3 report][q3-report] T37). Gemma-3 family leads Qwen on Egyptian generation and Belebele_arz ([Nile-Chat][nilechat]) and on DialectalArabicMMLU-EGY ([2510.27543][dammlu], 12B) | **[doc] for the family.** The 27B variant itself is documented only on Belebele |
| `google/gemma-3-12b-it` | $0.05 / $0.15 | EgyAlpacaEval 92.6 vs 71.4 (Qwen2.5-14B), Belebele_arz 77.0 vs 72.3, DialectalArabicMMLU-EGY 61.5 vs 28.7 (Qwen3-4B). **Still near chance on Franco** (Latin EgyHellaSwag 37.5) | **[doc]** |
| `google/gemma-4-31B-it` (also `-turbo`, `26B-A4B`) | $0.13 / $0.38 (turbo $0.09 / $0.34; 26B-A4B $0.07 / $0.34) | Card: pre-trained on 140+ languages, 35+ supported, MMMLU 88.4 (vs 85.9 for Qwen3.5-27B). No Arabic or dialect breakdown ([card][gemma4]) | [inference]: probably at least as good as Gemma 3. Not documented for Egyptian |
| `google/gemini-2.5-pro` | $1.25 / $10.00 | Best overall with GPT-5 on ArabCulture-Dialogue dialect tasks (MSA-to-dialect judge 4.19 overall; dialect steering 0.924 judge) ([2605.00119][arabculture]) | [doc] across all dialects, not Egyptian alone. About 8x the 9B's input price |
| `google/gemini-2.5-flash`, `gemini-3.x`, `anthropic/claude-*`, `Qwen/Qwen3.8-*` | various (e.g. Flash $0.30 / $2.50) | None found in dialect benchmarks. The Qwen3.8-27B card has no multilingual section ([card][q38]) | Unknown |

**Recommendation [inference]:** for #139, run the same small Egyptian and Franco
eval on `Qwen/Qwen3.5-9B`, `Qwen/Qwen3.5-27B`, `google/gemma-3-27b-it` and
`google/gemma-4-31B-it` before switching anything. Gemma 3 27B is cheaper than
the current coach model and is the only DeepInfra option with a documented
Egyptian advantage. Check its tool-calling and structured-output behaviour
against `scripts/provider_smoke.py` first. No documented model on DeepInfra
handles Franco well. If Franco matters, the product may need to steer replies
into Arabic script, or accept Franco input while answering in Arabic script.

## Appendix: Corpus A sentences

| # | English | Egyptian (Arabic script) | Franco |
|---|---|---|---|
| 1 | I missed my workout yesterday because I was tired. | فوّت التمرين امبارح عشان كنت تعبان. | fawet el tamreen embare7 3ashan kont ta3ban. |
| 2 | My knee hurts when I squat, what should I do? | ركبتي بتوجعني لما بعمل سكوات، أعمل إيه؟ | rokbety betewga3ny lama ba3mel squat, a3mel eh? |
| 3 | Can you make today's session shorter? I only have thirty minutes. | ممكن تخلي تمرين النهارده أقصر؟ معايا نص ساعة بس. | momken tkhaly tamreen el naharda a2sar? ma3aya nos sa3a bas. |
| 4 | I finished three sets of bench press at sixty kilos. | خلصت تلات مجاميع بنش بريس على ستين كيلو. | khalast talat magamee3 bench press 3ala setin kilo. |
| 5 | Should I increase the weight next week or stay the same? | أزوّد الوزن الأسبوع الجاي ولا أفضل زي ما أنا؟ | azawed el wazn el esbo3 el gay wala afdal zay ma ana? |
| 6 | I want to build muscle and lose some belly fat. | عايز أبني عضل وأخس شوية من الكرش. | 3ayez abny 3adal w akhos shwaya mn el kersh. |
| 7 | I can't come to the gym on Friday, move it to Saturday please. | مش هقدر آجي الجيم يوم الجمعة، خليها السبت لو سمحت. | msh ha2dar aagy el gym yom el gom3a, khaleeha el sabt law sama7t. |
| 8 | That was a very hard session, I'm exhausted. | التمرينة دي كانت صعبة أوي، أنا مهدود. | el tamreena di kanet sa3ba awy, ana mahdood. |
| 9 | How many rest seconds between sets? | أرتاح كام ثانية بين المجاميع؟ | artah kam sanya bein el magamee3? |
| 10 | I slept badly and I don't feel like training today. | نمت وحش ومليش مزاج أتمرن النهارده. | nemt we7esh w malish mazag atmaran el naharda. |
| 11 | Great job, you hit a new personal record on deadlift! | عاش يا بطل، كسرت رقمك في الديدليفت! | 3ash ya batal, kasart ra2mak fel deadlift! |
| 12 | Drink water and get some sleep, see you tomorrow. | اشرب مية ونام كويس، أشوفك بكرة. | eshrab maya w nam kwayes, ashofak bokra. |

The MSA versions were written the same way and are omitted for brevity.

[q35-9b]: https://huggingface.co/Qwen/Qwen3.5-9B
[q35-27b]: https://huggingface.co/Qwen/Qwen3.5-27B
[q35-readme]: https://github.com/QwenLM/Qwen3.5/blob/main/README.md
[q35-omni]: https://arxiv.org/html/2604.15804v1
[q3-blog]: https://qwenlm.github.io/blog/qwen3/
[q3-report]: https://arxiv.org/html/2505.09388v1
[dammlu]: https://arxiv.org/abs/2510.27543
[arabculture]: https://arxiv.org/abs/2605.00119
[nilechat]: https://arxiv.org/abs/2507.04569
[aradice]: https://arxiv.org/abs/2409.11404
[gemma4]: https://huggingface.co/google/gemma-4-31B-it
[q38]: https://huggingface.co/Qwen/Qwen3.8-27B
