# agent/clinical_guard.py
import heapq
import re
import threading

import numpy as np
from core.embeddings import get_arabic_embedding_model, get_embedding_model
from core.injuries import INJURY_BODY_AREA_LABELS

# ONNX Runtime is CPU-only; MODEL_DEVICE remains accepted as a config no-op.
EMBED_MODEL = get_embedding_model()

ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06ff]")
_ARABIC_LETTERS = "\u0621-\u064a"
_ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
        **{chr(codepoint): None for codepoint in (*range(0x064B, 0x0660), 0x0670, 0x0640)},
    }
)


def normalize_arabic_text(text: str) -> str:
    return text.translate(_ARABIC_TRANSLATION)


# Arabic lexical Tier-0 guard: normalized stems with optional attached clitics
# (و/ف conjunction, ب/ل prepositions, ال definite article, pronoun suffixes).
ARABIC_CLINICAL_STEMS = {
    "injury": (
        "اصابه", "مصاب", "مصابين", "مصابات", "جرح", "مصدوم", "اتلوي", "تلوي", "التواء", "كسور", "مكسور", "اتكسر", "انكسر", "خلع",
        "تمزق", "ممزق", "اتقطع", "اتقطعت", "انقطع", "انخلع", "اتقصف", "التهاب", "تخون", "يخون",
        "غير ثابت", "غير ثابته", "مش ثابت", "عدم الثبات", "عدم استقرار", "غير مستقر",
        "تفلت", "اتفلت",
    ),
    "pain": (
        "الم", "الام", "اوجاع", "وجع", "يوجع", "يؤلم", "تؤلم", "مؤلم", "يالم", "pain", "hurt", "ache",
        "موجوع", "وجعان", "بتوجع", "بيوجع", "يحرقني",
        "توجع", "تالم", "بتالم", "بيالم", "وجعت", "وجعني",
    ),
    "trauma_sensation": (
        "فرقعه", "فرقع", "طقطق", "يطقطق", "طقطقه", "طقت", "طق", "تطق", "تكتكه",
        "انفصل", "اتمزق",
    ),
    "swelling": (
        "تورم", "تورمت", "متورم", "منتفخ", "انتفخ", "انتفخت", "انتفاخ", "ورم", "وارم",
    ),
    "numbness_or_tingling": (
        "تنميل", "تنمل", "منمل", "خدر", "مخدر", "تخدير", "تخدر", "وخز", "تنغز", "شكشكه",
    ),
    "dizziness": ("دوخه", "دوار", "دايخ", "دوخت", "دوخ"),
    "medication_or_painkillers": (
        "دواء", "دوا", "ادويه", "مسكن", "مسكنات", "بانادول", "ايبوبروفين", "باراسيتامول",
    ),
    "surgery": ("جراحه", "عمليه جراحيه"),
    "doctor_or_physio": (
        "طبيب", "دكتور", "فيزيو", "فيزيوثيرابي", "علاج طبيعي", "علاج فيزيائي",
    ),
}
_ARABIC_PRONOUN_SUFFIXES = ("ني", "كم", "كن", "هم", "هن", "ها", "نا", "ك", "ه", "ي")
_ARABIC_CLITIC_PREFIX = r"(?:[وف]?(?:[بل])?(?:ال)?|ل{1,2}|)"


def _arabic_stem_pattern(stems) -> re.Pattern[str]:
    expanded_stems = set(stems)
    expanded_stems.update(
        stem[:-1] + "ت" for stem in stems if stem.endswith(("ة", "ه"))
    )
    ordered = sorted(expanded_stems, key=len, reverse=True)
    suffixes = "|".join(_ARABIC_PRONOUN_SUFFIXES)
    return re.compile(
        rf"(?<![{_ARABIC_LETTERS}]){_ARABIC_CLITIC_PREFIX}"
        rf"(?:{'|'.join(re.escape(stem) for stem in ordered)})"
        rf"(?:{suffixes})?(?![{_ARABIC_LETTERS}])"
    )


_ARABIC_STEMS = sorted(
    (stem for stems in ARABIC_CLINICAL_STEMS.values() for stem in stems),
    key=len,
    reverse=True,
)
_ARABIC_STEM_PATTERN = _arabic_stem_pattern(_ARABIC_STEMS)

_ARABIC_BODY_PART_WORDS = sorted(
    {
        normalize_arabic_text(label)
        for label in INJURY_BODY_AREA_LABELS["ar"].values()
    }
    | {
        "ركبه", "ركبتي", "ركب", "ورك", "وركي", "حوض", "حوضي",
        "ظهر", "ظهري", "ضهر", "ضهري", "كتف", "كتفي", "اكتاف",
        "كوع", "كوعي", "مرفق", "مرفقي", "رسغ", "رسغي", "معصم",
        "معصمي", "كاحل", "كاحلي", "كعب", "كعبي", "رقبه", "رقبتي",
        "رجل", "رجلي", "ساق", "ساقي", "ذراع", "ذراعي", "دراع",
        "دراعي", "ايد", "ايدي", "يد", "يدي", "قدم", "قدمي", "صدر",
        "صدري",
    },
    key=len,
    reverse=True,
)
_ARABIC_BODY_PART_PATTERN = "|".join(
    re.escape(word) for word in _ARABIC_BODY_PART_WORDS
)
_ARABIC_FEELING_VERB_PATTERN = r"[وف]?(?:حاسس|حاسه|بحس|احس|حسيت)"
_ARABIC_STRANGE_SENSATION_PATTERN = r"(?:حاجه|احساس)\s+(?:غريب|غريبه|مش\s+طبيعيه?|مش\s+مظبوطه?)"
_ARABIC_UNKNOWN_BODY_SENSATION_PATTERN = re.compile(
    rf"(?:(?<![{_ARABIC_LETTERS}]){_ARABIC_FEELING_VERB_PATTERN}\s+)?"
    rf"(?<![{_ARABIC_LETTERS}]){_ARABIC_CLITIC_PREFIX}{_ARABIC_STRANGE_SENSATION_PATTERN}"
    rf"\s*(?<![{_ARABIC_LETTERS}])[وف]?(?:في|ف|ب)\s*"
    rf"{_ARABIC_CLITIC_PREFIX}(?:{_ARABIC_BODY_PART_PATTERN})"
    rf"(?![{_ARABIC_LETTERS}])"
)

_FRANCO_DIGRAPHS = {"sh": ("ش",), "kh": ("خ",), "gh": ("غ",), "th": ("ث",), "dh": ("ذ",)}
_FRANCO_CHARACTERS = {
    "a": ("", "ا", "ع"), "b": ("ب",), "c": ("ك", "س"), "d": ("د",),
    "e": ("", "ا", "ي"), "f": ("ف",), "g": ("ج", "غ"), "h": ("ه", "ح"),
    "i": ("ي", ""), "j": ("ج",), "k": ("ك", "ق"), "l": ("ل",),
    "m": ("م",), "n": ("ن",), "o": ("و", ""), "p": ("ب",),
    "q": ("ق",), "r": ("ر",), "s": ("س", "ص"), "t": ("ت", "ط", ""),
    "u": ("و", ""), "v": ("ف",), "w": ("و",), "y": ("ي",), "z": ("ز", "ذ"),
    "2": ("ء", "ق"), "3": ("ع",), "5": ("خ",), "6": ("ط",),
    "7": ("ح",), "8": ("غ",), "9": ("ص",),
}
_FRANCO_MAX_CANDIDATES = 128
FRANCO_GUARD_VERSION = "419.2"
_FRANCO_TECH_TOKENS = frozenset({
    "b2b", "b2c", "c2b", "c2c", "e2e", "h2o", "m2m", "p2p", "r2d2", "x2x",
})
_FRANCO_UNIT_SUFFIX = re.compile(
    r"^[2356789](?:kgs?|lbs?|km|mi|mins?|secs?|hrs?|am|pm|x|rm|reps?|sets?|days?|wks?|"
    r"st|nd|rd|th|rpe|rir|k|m|s|h|d|w)$",
    re.IGNORECASE,
)


def _franco_token_is_excluded(token: str) -> bool:
    normalized = token.casefold()
    return bool(
        normalized in _FRANCO_TECH_TOKENS
        or _FRANCO_UNIT_SUFFIX.fullmatch(normalized)
        or re.fullmatch(r"\d+[xX]\d+", normalized)
        or re.fullmatch(r"\d+(?:st|nd|rd|th)", normalized)
        or re.fullmatch(r"[a-z]+\d+", normalized)
    )


def has_franco_digit_evidence(token: str) -> bool:
    normalized = token.casefold()
    if _franco_token_is_excluded(normalized):
        return False
    return bool(
        re.fullmatch(r"[2356789][a-z]+", normalized)
        or re.search(r"[a-z][2356789][a-z]", normalized)
    )


def _franco_character_choices(token: str) -> list[tuple[str, ...]]:
    choices = []
    index = 0
    while index < len(token):
        if index == 0 and token.startswith("el"):
            choices.append(("ال",))
            index += 2
            continue
        digraph = token[index:index + 2]
        if digraph in _FRANCO_DIGRAPHS:
            choices.append(_FRANCO_DIGRAPHS[digraph])
            index += 2
            continue
        alternatives = _FRANCO_CHARACTERS.get(token[index])
        if index == 0 and token[index] == "e":
            alternatives = ("ا", "", "ي")
        if alternatives is None:
            return []
        choices.append(alternatives)
        index += 1
    return choices


def _bounded_franco_forms(choices: list[tuple[str, ...]]) -> set[str]:
    first = tuple(0 for _ in choices)
    pending = [(0, first)]
    seen = {first}
    forms = set()
    while pending and len(forms) < _FRANCO_MAX_CANDIDATES:
        cost, indexes = heapq.heappop(pending)
        forms.add("".join(choices[position][choice] for position, choice in enumerate(indexes)))
        for position, choice in enumerate(indexes):
            if choice + 1 >= len(choices[position]):
                continue
            next_indexes = indexes[:position] + (choice + 1,) + indexes[position + 1:]
            if next_indexes not in seen:
                seen.add(next_indexes)
                heapq.heappush(pending, (cost + 1, next_indexes))
    return forms


def _franco_arabic_candidates(token: str) -> set[str]:
    normalized_token = token.casefold()
    choices = _franco_character_choices(normalized_token)
    if not choices:
        return set()
    candidates = _bounded_franco_forms(choices)
    return {normalize_arabic_text(candidate) for candidate in candidates if candidate}


_FRANCO_CLINICAL_WORDS = frozenset({
    "rokba", "rokbety", "rokbeti", "rokbty", "ro2ba", "ro2bety",
    "ketf", "ketfy", "ketfi", "dahr", "dahry", "dahri", "regl", "regly", "regli",
    "ka7l", "ka7ly", "sedr", "sedry", "sedri", "sawab3", "sawab3y", "sawabe3",
    "wag3", "waga3", "waga3ny", "wga3", "wga3ny", "wagani", "bywga3ny",
    "tewga3ny", "btwga3ny", "alam", "waram", "werm", "wermet", "waramet",
    "tanmeel", "tanmil", "nakhz", "et2ata3", "et2ata3et", "etlewet", "et2asfet",
    "etkasar", "2arfa3a", "arfa3a", "masken", "sabab", "bet2alemny", "by2lemny",
    "te2alemny", "betwag3ny",
})


def _eligible_franco_clinical_tokens(text: str):
    for token in re.findall(r"[A-Za-z0-9]+", text):
        lexical_word = token.casefold() in _FRANCO_CLINICAL_WORDS
        if lexical_word or (not _franco_token_is_excluded(token) and has_franco_digit_evidence(token)):
            yield token


def _franco_message_tokens(text: str):
    for token in re.findall(r"[A-Za-z0-9]+", text):
        if token.casefold() in _FRANCO_CLINICAL_WORDS or not _franco_token_is_excluded(token):
            yield token


def _has_franco_clinical_candidate(tokens) -> bool:
    try:
        for token in tokens:
            if any(_ARABIC_STEM_PATTERN.fullmatch(candidate) for candidate in _franco_arabic_candidates(token)):
                return True
        return False
    except Exception:
        # A transliteration failure must never send an unreadable clinical turn to the model.
        return True


def is_franco_clinical(text: str) -> bool:
    return _has_franco_clinical_candidate(_eligible_franco_clinical_tokens(text))


def is_franco_clinical_franco_message(text: str) -> bool:
    return _has_franco_clinical_candidate(_franco_message_tokens(text))

RE_BENIGN_FATIGUE = re.compile(
    r"\b(fatigue|fatigued|tired|exhaustion|exhausted|sluggish|lethargic|drained|wiped|"
    r"run[\s-]?down|sore|soreness|burn|burning|pump|systemic\s+fatigue)\b"
    r"|\blow\s+readiness\b"
    r"|\breadiness\s*(?:is|at|:)?\s*[12]\s*/\s*5\b",
    re.IGNORECASE,
)
RE_TRAUMA_SENSATIONS = re.compile(
    r"\b(tear|tearing|ripping|pins\s+and\s+needles|tingling|numb|numbness|electric|shock|glass|loose|slipping|crunching|grinding|giving\s+way|impingement|sharp|pop|popping|dislocat|hernia)\b",
    re.IGNORECASE,
)
#: Symptom words that must keep the benign-fatigue bypass closed. Body-part nouns
#: (knee, shoulder, joint) are deliberately excluded: "every joint feels cold and
#: sluggish" is systemic fatigue, not an injury. Fail-closed on pain/neural signs.
RE_ACUTE_PAIN_SIGNALS = re.compile(
    r"\b(pain|painful|hurts?|aching|ache|sharp|shooting|radiat(?:ing|es|ed)|numb|numbness|"
    r"tingling|pins\s+and\s+needles|pop(?:ping|ped)?|tear(?:ing|s)?|torn|tore|ripping|"
    r"grinding|clicking|pinch(?:ed)?|crunch(?:ing)?|dislocat\w*|impingement|giving\s+way|"
    r"electric|shock|glass|swollen|swelling|unstable|instability)\b",
    re.IGNORECASE,
)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculates cosine similarity between two dense embedding vectors."""
    if not v1 or not v2:
        return 0.0
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def _validated_embedding(vector, label: str) -> np.ndarray:
    """Return a finite, non-zero 1-D embedding or raise so the path fails closed."""
    array = np.asarray(vector, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"Arabic {label} embedding is not a 1-D vector: shape {array.shape}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"Arabic {label} embedding contains non-finite values.")
    if float(np.linalg.norm(array)) == 0.0:
        raise ValueError(f"Arabic {label} embedding is the zero vector.")
    return array


def _max_anchor_similarity(query_vector, anchors) -> float:
    """Max cosine to the clinical anchors, validating every embedding first.

    A degenerate query (NaN, wrong shape, zero vector) or anchor, or a
    non-finite similarity, raises so ``_arabic_semantic_guard`` fails closed
    instead of returning benign.
    """
    query = _validated_embedding(query_vector, "query")
    if not anchors:
        raise ValueError("No Arabic clinical anchor vectors are available.")
    best = -1.0
    for anchor in anchors:
        anchor_vector = _validated_embedding(anchor, "anchor")
        if anchor_vector.shape[0] != query.shape[0]:
            raise ValueError("Arabic query and anchor embeddings differ in dimension.")
        similarity = float(
            np.dot(query, anchor_vector) / (np.linalg.norm(query) * np.linalg.norm(anchor_vector))
        )
        if not np.isfinite(similarity):
            raise ValueError("Arabic anchor similarity is non-finite.")
        best = max(best, similarity)
    return best


CLINICAL_ANCHOR_DESCRIPTIONS: list[str] = [
    "Felt like velcro tearing or ripping deep inside the muscle fiber during the stretch.",
    "Pins and needles, tingling, or ice cold sensation radiating into fingers or extremities.",
    "Deep searing pain, hot glass sensation, or sharp electric shock inside the joint capsule.",
    "Joint feels loose, unstable, or like the bone is slipping out of its socket.",
    "Dull, persistent toothache-like gnawing ache deep inside the bone or hip capsule.",
    "Audible crunching, grinding, or loud clicking accompanied by immediate joint weakness.",
    "Sudden loss of motor control, limb giving way, or unable to bear load.",
    "Sharp structural joint impingement followed by immediate loss of tension and localized swelling.",
]

CLINICAL_ANCHOR_VECTORS: list[list[float]] = [
    EMBED_MODEL.embed_query(desc) for desc in CLINICAL_ANCHOR_DESCRIPTIONS
]

#: Arabic clinical anchor descriptions for the separate multilingual-e5-small
#: model (ADR 081). These are MAYOS-authored renderings of the English anchors
#: above; they are internal model prompts, not player-facing text, and remain
#: owner-unreviewed until the owner approves the Arabic wording.
ARABIC_CLINICAL_ANCHOR_DESCRIPTIONS: list[str] = [
    "أحسست كأن شيئًا يتمزق أو يتقطع بعمق داخل ألياف العضلة أثناء التمدد.",
    "تنميل أو وخز أو إحساس ببرودة شديدة ينتشر إلى الأصابع أو الأطراف.",
    "ألم حارق عميق أو إحساس بزجاج ساخن أو صعقة كهربائية حادة داخل محفظة المفصل.",
    "المفصل يبدو غير ثابت أو غير مستقر أو كأن العظم ينزلق من مكانه.",
    "ألم خفيف مستمر يشبه وجع الأسنان بعمق داخل العظم أو محفظة الورك.",
    "صوت طحن أو فرقعة أو طقطقة مسموعة مصحوبة بضعف فوري في المفصل.",
    "فقدان مفاجئ للسيطرة على الحركة أو العضو يفلت منك أو عدم القدرة على تحمل الوزن.",
    "انحشار حاد في المفصل يتبعه فقدان فوري للشد وتورم موضعي.",
]

#: The e5 similarity scores for Arabic are compressed, so this tier is a
#: high-precision backstop rather than the carrier of the reviewed intercepts.
#: The reviewed instability case (ar-inj-07, 0.8888) is caught by the lexical
#: tier instead, and ordinary Arabic training talk reaches 0.885 (for example an
#: exercise-swap request at 0.8853 and "bench stretches my shoulder" at 0.8837),
#: so 0.90 sits above the measured benign ceiling with margin. This is a
#: tunable operating point, not a safety certification; extending recall for
#: unseen paraphrases means extending the deterministic tiers.
ARABIC_SEMANTIC_THRESHOLD = 0.90

_ARABIC_ANCHOR_LOCK = threading.Lock()
_ARABIC_ANCHOR_VECTORS: list[list[float]] | None = None


def _arabic_anchor_vectors() -> list[list[float]]:
    """Return the Arabic anchor vectors, loading the e5 model on first use."""
    global _ARABIC_ANCHOR_VECTORS
    if _ARABIC_ANCHOR_VECTORS is None:
        with _ARABIC_ANCHOR_LOCK:
            if _ARABIC_ANCHOR_VECTORS is None:
                model = get_arabic_embedding_model()
                _ARABIC_ANCHOR_VECTORS = [
                    model.embed_query(desc) for desc in ARABIC_CLINICAL_ANCHOR_DESCRIPTIONS
                ]
    return _ARABIC_ANCHOR_VECTORS


def _arabic_lexical_hit(normalized: str) -> bool:
    return bool(
        _ARABIC_UNKNOWN_BODY_SENSATION_PATTERN.search(normalized)
        or _ARABIC_STEM_PATTERN.search(normalized)
    )


def _arabic_semantic_guard(query: str) -> tuple[bool, float]:
    """Layered Arabic path: lexical stems, acute signals, then e5 similarity.

    Every Arabic-script message is screened here; a Latin script or an English
    exercise name must never divert Arabic symptom text to the English tiers.
    Code-switched messages combine the English acute-signal detection with the
    Arabic screening instead of substituting one for the other. Fails closed:
    any normalization, model-load, validation or inference error counts as a
    possible injury so the caller intercepts instead of reaching coaching.
    """
    try:
        normalized = normalize_arabic_text(query)
        if _arabic_lexical_hit(normalized):
            return True, 1.0
        if RE_TRAUMA_SENSATIONS.search(query) or RE_ACUTE_PAIN_SIGNALS.search(query):
            return True, 1.0

        model = get_arabic_embedding_model()
        anchors = _arabic_anchor_vectors()
        query_vector = model.embed_query(query)
        max_similarity = _max_anchor_similarity(query_vector, anchors)
        # Fatigue terms never bypass the semantic threshold to declare benign.
        return (max_similarity >= ARABIC_SEMANTIC_THRESHOLD), max_similarity
    except Exception:
        # The Arabic path is required to fail closed on every error.
        return True, 1.0


_CLINICAL_LEXICAL_TOKENS = re.compile(
    r"\b(pain|hurt|ache|aching|sharp|pop|popping|tear|tearing|torn|tore|numb|numbness|tingling|"
    r"joint|shoulder|knee|elbow|hip|wrist|pec|tendon|disc|spine|hernia|swollen|swell|swelling|"
    r"shooting|radiating|grinding|clicking|pinch|pinched|crunch|crunching|dislocat|impingement|"
    r"glass|giving\s+way|loose|slipping|electric|shock|ripping)\b",
    re.IGNORECASE,
)


def _english_semantic_guard(query: str, threshold: float = 0.70) -> tuple[bool, float]:
    has_acute_signal = bool(RE_TRAUMA_SENSATIONS.search(query) or RE_ACUTE_PAIN_SIGNALS.search(query))
    if RE_BENIGN_FATIGUE.search(query) and not has_acute_signal:
        return False, 0.0

    word_count = len(query.split())
    has_clinical_token = bool(_CLINICAL_LEXICAL_TOKENS.search(query) or RE_TRAUMA_SENSATIONS.search(query))
    if word_count < 6 and not has_clinical_token:
        return False, 0.0

    query_vec = EMBED_MODEL.embed_query(query)
    max_sim = max(cosine_similarity(query_vec, anchor) for anchor in CLINICAL_ANCHOR_VECTORS)
    return (max_sim >= threshold), float(max_sim)


def evaluate_clinical_semantic_guard(query: str, threshold: float = 0.70) -> tuple[bool, float]:
    """Return the clinical decision; ``threshold`` applies only to English.

    Arabic uses ``ARABIC_SEMANTIC_THRESHOLD`` after its lexical and acute tiers.
    """
    if ARABIC_SCRIPT_RE.search(query):
        return _arabic_semantic_guard(query)
    return _english_semantic_guard(query, threshold)
