# agent/clinical_guard.py
import heapq
import logging
import re

import numpy as np
from core.embeddings import get_embedding_model
from core.injuries import INJURY_BODY_AREA_LABELS
from core.arabic import normalize_arabic_text

# ONNX Runtime is CPU-only; MODEL_DEVICE remains accepted as a config no-op.
logger = logging.getLogger(__name__)

EMBED_MODEL = get_embedding_model()

ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06ff]")
_ARABIC_LETTERS = "\u0621-\u064a"
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
        "الم", "الام", "اوجاع", "وجع", "يوجع", "يؤلم", "تؤلم", "مؤلم", "يالم", "pain", "painful", "hurt", "hurts", "hurting",
        "ache", "aches", "aching", "headache", "headaches", "backache", "backaches",
        "toothache", "toothaches",
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


# Latin tokens use Latin boundaries so Arabic clitics may touch them without
# matching substrings inside English exercise names such as "Preacher".
def _bounded_clinical_stems(stems, boundary_letters: str, suffixes: str) -> str:
    if not stems:
        return ""
    ordered = sorted(stems, key=lambda stem: (-len(stem), stem))
    alternatives = "|".join(re.escape(stem) for stem in ordered)
    return (
        rf"(?<![{boundary_letters}]){_ARABIC_CLITIC_PREFIX}"
        rf"(?:{alternatives})(?:{suffixes})?(?![{boundary_letters}])"
    )


def _arabic_stem_pattern(stems) -> re.Pattern[str]:
    arabic_stems = {stem for stem in stems if ARABIC_SCRIPT_RE.search(stem)}
    arabic_stems = arabic_stems | {
        stem[:-1] + "ت" for stem in arabic_stems if stem.endswith(("ة", "ه"))
    }
    latin_stems = {stem for stem in stems if not ARABIC_SCRIPT_RE.search(stem)}
    suffixes = "|".join(_ARABIC_PRONOUN_SUFFIXES)
    # Join only non-empty alternatives: an empty one would match every text.
    return re.compile("|".join(part for part in (
        _bounded_clinical_stems(arabic_stems, _ARABIC_LETTERS, suffixes),
        _bounded_clinical_stems(latin_stems, "A-Za-z", suffixes),
    ) if part))


_ARABIC_STEMS = sorted(
    (stem for stems in ARABIC_CLINICAL_STEMS.values() for stem in stems),
    key=lambda stem: (-len(stem), stem),
)
_ARABIC_STEM_PATTERN = _arabic_stem_pattern(_ARABIC_STEMS)
_ARABIC_CATEGORY_PATTERNS = {
    category: _arabic_stem_pattern(stems)
    for category, stems in ARABIC_CLINICAL_STEMS.items()
}

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
    key=lambda word: (-len(word), word),
)
_ARABIC_BODY_PART_PATTERN = "|".join(
    re.escape(word) for word in _ARABIC_BODY_PART_WORDS
)
# A body part near "isn't right", "something's wrong", "can't move" or "is
# bothering me": the keyword-free way Players report an injury (#754). These
# are normalized forms (hamza and taa marbuta folded).
_ARABIC_ABNORMAL_STATE_PATTERN = re.compile(
    r"(?:مش|مو|غير|ليس)\s+(?:مظبوط|مظبوطه|طبيعي|طبيعيه|مريح|مريحه|سليم|سليمه)"
    r"|(?<![\u0621-\u064a])(?:فيه|في|فيها|عندي)?\s*حاجه\s+(?:غلط|مش\s+مظبوطه?|مش\s+طبيعيه?)"
    r"|(?:مش|مو|ما)\s+(?:قادر|قادره|عارف|عارفه)\s+(?:احرك|اتحرك|افرد|اثني|ارفع|انزل|اقف|امشي|ادور|اقعد)"
    r"|(?:لا|لم)\s+(?:استطيع|اقدر|اقدرش)\s+(?:تحريك|ثني|فرد|رفع|الحركه|التحرك|المشي)"
    r"|(?:بيضايقني|بتضايقني|مضايقني|مضايقاني|يزعجني|تزعجني|بيتعبني\s+من\s+ساعه)"
)
_ARABIC_BODY_TOKEN_PATTERN = re.compile(
    rf"{_ARABIC_CLITIC_PREFIX}(?:{_ARABIC_BODY_PART_PATTERN})"
    rf"(?:{'|'.join(_ARABIC_PRONOUN_SUFFIXES)})?"
)
_ARABIC_BODY_WINDOW_TOKENS = 5


_ARABIC_OWN_BODY_SUFFIXES = ("ي", "ه", "ها", "نا", "ك", "ني")
_ARABIC_BODY_PREPOSITIONS = {"في", "ف", "فى", "ب"}


def _is_own_body_token(tokens: list[str], index: int) -> bool:
    """A body part the Player names as their own: "my knee", or "in the knee".

    A bare body noun such as «يوم الرجل» (leg day) is a training label, not
    a report about the Player's body (#754).
    """
    token = tokens[index].strip("،,.؟?!")
    match = _ARABIC_BODY_TOKEN_PATTERN.fullmatch(token)
    if match is None:
        return False
    if token.startswith(("بال", "فال", "وبال", "وفال")):
        return True
    if index > 0 and tokens[index - 1].strip("،,.؟?!") in _ARABIC_BODY_PREPOSITIONS:
        return True
    for word in sorted(_ARABIC_BODY_PART_WORDS, key=len, reverse=True):
        if word in token:
            tail = token[token.index(word) + len(word):]
            return word.endswith("ي") or tail in _ARABIC_OWN_BODY_SUFFIXES
    return False


def _arabic_body_abnormal_hit(normalized: str) -> bool:
    """The Player's own body part within five words of an abnormal-state phrase."""
    tokens = normalized.split()
    body_indexes = [
        index for index in range(len(tokens)) if _is_own_body_token(tokens, index)
    ]
    if not body_indexes:
        return False
    for match in _ARABIC_ABNORMAL_STATE_PATTERN.finditer(normalized):
        start = len(normalized[: match.start()].split())
        end = start + len(match.group(0).split()) - 1
        if any(start - _ARABIC_BODY_WINDOW_TOKENS <= index <= end + _ARABIC_BODY_WINDOW_TOKENS
               for index in body_indexes):
            return True
    return False


# Normal post-training muscle soreness (DOMS): benign only when the message
# names it plainly, its only clinical words are pain words, and it names no
# joint, mirroring the English fatigue bypass (#754).
_ARABIC_SORENESS_PATTERN = re.compile(
    r"\bdoms\b|شد\s+عضلي|تكسير|متكسر|متكسره|تاني\s+يوم|بعد\s+التمرين\s+بيوم"
    r"|زي\s+كل\s+مره|الالم\s+العضلي\s+المتاخر|الم\s+العضلات\s+المتاخر",
    re.IGNORECASE,
)
_ARABIC_JOINT_PATTERN = re.compile(
    rf"(?<![{_ARABIC_LETTERS}]){_ARABIC_CLITIC_PREFIX}"
    r"(?:ركب|ركبه|ركبت|ركبتي|كتف|كتفي|اكتاف|كوع|كوعي|مرفق|رسغ|معصم|كاحل|ضهر|ظهر|ضهري|ظهري"
    r"|رقبه|رقبت|رقبتي|ورك|وركي|حوض|مفصل|مفاصل|عمود\s+فقري)"
    rf"(?:{'|'.join(_ARABIC_PRONOUN_SUFFIXES)})?(?![{_ARABIC_LETTERS}])"
)


def _arabic_lexical_categories(normalized: str) -> set[str]:
    return {
        category
        for category, pattern in _ARABIC_CATEGORY_PATTERNS.items()
        if pattern.search(normalized)
    }


def _arabic_benign_soreness(normalized: str, query: str) -> bool:
    return (
        _arabic_lexical_categories(normalized) <= {"pain"}
        and bool(_ARABIC_SORENESS_PATTERN.search(normalized) or _ARABIC_SORENESS_PATTERN.search(query))
        and not _ARABIC_JOINT_PATTERN.search(normalized)
        and not _ARABIC_UNKNOWN_BODY_SENSATION_PATTERN.search(normalized)
        and not (RE_TRAUMA_SENSATIONS.search(query) or RE_ACUTE_PAIN_SIGNALS.search(query))
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
    r"(?<![A-Za-z0-9_])(?:pain|painful|hurt(?:s|ing)?|(?:(?:head|back|tooth)?ache(?:s)?|ach(?:ing))|sharp|shooting|radiat(?:ing|es|ed)|numb|numbness|"
    r"tingling|pins\s+and\s+needles|pop(?:ping|ped)?|tear(?:ing|s)?|torn|tore|ripping|"
    r"grinding|clicking|pinch(?:ed)?|crunching|crunch(?:es|ed)?\s+(?:sound|noise)|(?:a|the)\s+crunch\s+in|"
    r"dislocat\w*|impingement|giving\s+way|"
    r"electric|shock|glass|swollen|swelling|unstable|instability)(?![A-Za-z0-9_])",
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


def _arabic_lexical_hit(normalized: str) -> bool:
    return bool(
        _ARABIC_UNKNOWN_BODY_SENSATION_PATTERN.search(normalized)
        or _ARABIC_STEM_PATTERN.search(normalized)
        or _arabic_body_abnormal_hit(normalized)
    )


def _arabic_semantic_guard(query: str) -> tuple[bool, float]:
    """The Arabic path: deterministic tiers only (#754).

    Arabic clinical wording (stems, a body part near an abnormal-state phrase,
    an unknown sensation in a body part) or an English acute signal
    intercepts; plainly named muscle soreness with no joint or escalation is
    benign. The multilingual e5 similarity tier no longer intercepts on its
    own: its scores for ordinary training talk (up to 0.896) overlapped
    keyword-free injury reports (0.82-0.89) around its 0.90 cutoff, so it
    produced false triggers and caught nothing the word lists missed. Fails
    closed: any normalization error counts as a possible injury.
    """
    try:
        normalized = normalize_arabic_text(query)
        if _arabic_lexical_hit(normalized):
            if _arabic_benign_soreness(normalized, query):
                return False, 0.0
            return True, 1.0
        if RE_TRAUMA_SENSATIONS.search(query) or RE_ACUTE_PAIN_SIGNALS.search(query):
            return True, 1.0
        return False, 0.0
    except Exception:
        # The Arabic path is required to fail closed on every error; log it so
        # an outage can be told apart from a real hit (#754).
        logger.exception("Arabic clinical guard failed; failing closed")
        return True, 1.0


_CLINICAL_LEXICAL_TOKENS = re.compile(
    r"(?<![A-Za-z0-9_])(?:injur(?:y|ies|ed)|strain(?:ed)?|sprain(?:ed)?|fractur(?:e|ed)|broken|"
    r"pain(?:ful)?|hurt(?:s|ing)?|(?:(?:head|back|tooth)?ache(?:s)?|ach(?:ing))|sharp|pop|popping|tear|tearing|torn|tore|numb|numbness|tingling|"
    r"joint|shoulder|knee|elbow|hip|wrist|pec|tendon|disc|spine|hernia|swollen|swell|swelling|"
    r"shooting|radiating|grinding|clicking|pinch|pinched|crunching|dislocat|impingement|"
    r"glass|giving\s+way|loose|slipping|electric|shock|ripping)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

_ENGLISH_BODY = (
    r"(?:knees?|shoulders?|(?:lower\s+|upper\s+)?back|neck|wrists?|elbows?|hips?|ankles?|"
    r"hamstrings?|quads?|calf|calves|groin|chest|pecs?|biceps?|triceps?|forearms?|feet|foot|"
    r"toes?|fingers?|thumbs?|hands?|arms?|legs?|glutes?|spine|ribs?|traps?|rotator\s+cuff|"
    r"achilles|tendons?|joints?)"
)
#: Keyword-free injury reports: a body part that is "bothering me", "feels
#: off", a tweak, something that "went" in a body part, or a body part the
#: Player can't move (#754).
RE_ENGLISH_INJURY_PHRASES = re.compile(
    rf"\btweak(?:ed|ing)?\s+(?:my\s+)?(?:\w+\s+)?{_ENGLISH_BODY}\b"
    rf"|\b{_ENGLISH_BODY}\b[^.?!]{{0,40}}?\b(?:bothering|bugging|acting\s+up|giving\s+me\s+trouble|"
    rf"feels?\s+(?:off|wrong|weird|strange)|gives?\s+out|giving\s+out)\b"
    rf"|\b(?:something|it)\s+in\s+my\s+{_ENGLISH_BODY}\s+(?:went|gave|snapped|shifted|popped)\b"
    rf"|\bcan['’]?t\s+(?:bend|straighten|lift|raise|turn|rotate|move|put\s+weight\s+on)\s+my\s+{_ENGLISH_BODY}\b",
    re.IGNORECASE,
)

_EXPLICIT_CLINICAL_MENTIONS = re.compile(
    r"\b(injur(?:y|ies|ed)|strain(?:ed)?|sprain(?:ed)?|fractur(?:e|ed)|broken|"
    r"diagnos(?:e|is|ed|ing)|medical|doctor|physician|surgeon|surger(?:y|ies)|"
    r"medication|prescription|physio(?:therapy)?|rehabilitation)\b",
    re.IGNORECASE,
)


def has_deterministic_clinical_signal(query: str) -> bool:
    """Return whether explicit symptoms or medical terms require semantic screening."""
    if ARABIC_SCRIPT_RE.search(query):
        try:
            normalized = normalize_arabic_text(query)
        except TypeError:
            # A failed clinical normalization must retain the semantic screen.
            return True
        return _arabic_lexical_hit(normalized) or bool(
            RE_TRAUMA_SENSATIONS.search(query)
            or RE_ACUTE_PAIN_SIGNALS.search(query)
            or _EXPLICIT_CLINICAL_MENTIONS.search(query)
            or RE_ENGLISH_INJURY_PHRASES.search(query)
        )
    return bool(
        RE_TRAUMA_SENSATIONS.search(query)
        or RE_ACUTE_PAIN_SIGNALS.search(query)
        or _EXPLICIT_CLINICAL_MENTIONS.search(query)
        or RE_ENGLISH_INJURY_PHRASES.search(query)
    )


def _english_semantic_guard(query: str, threshold: float = 0.70) -> tuple[bool, float]:
    if RE_ENGLISH_INJURY_PHRASES.search(query):
        return True, 1.0
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

    Arabic uses its deterministic tiers only (#754).
    Code-switched messages screen both languages: the Arabic result decides, and
    when it reports benign the English tier also runs so trailing English injury
    prose after Arabic text cannot slip through on a technicality.
    """
    if ARABIC_SCRIPT_RE.search(query):
        is_clinical, score = _arabic_semantic_guard(query)
        if is_clinical or not re.search(r"[A-Za-z]", query):
            return is_clinical, score
        try:
            english_is_clinical, english_score = _english_semantic_guard(query, threshold)
        except Exception:
            # The English screen must fail closed exactly like the Arabic one.
            logger.exception("English clinical guard failed on a mixed message; failing closed")
            return True, 1.0
        if english_is_clinical:
            return True, max(score, english_score)
        return False, score
    return _english_semantic_guard(query, threshold)
