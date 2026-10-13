"""Deterministic rubric for model-written Checkpoint review evaluations."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from service.checkpoint_review_ai import render_review

NUMBER_RE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|\.\d|,\d)")
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
ARABIC_LETTER_RE = re.compile(r"[\u0621-\u063a\u0641-\u064a\u066e-\u06d3\u06fa-\u06fc]")
ARABIC_MARK_RE = re.compile(r"[\u064b-\u065f\u0670\u0640]")
ENGLISH_LETTER_RE = re.compile(r"[A-Za-z]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟۔])\s+|\n+")
ARABIC_NUMBER_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")
MEDICAL_PATTERNS = (
    re.compile(r"\b(?:medical\s+advice|doctor|physician|clinician|injur\w*|pain|diagnos\w*|treatment|medication|rehab\w*)\b", re.I),
    re.compile(r"\b(?:you\s+have|this\s+is|sounds\s+like|diagnosed\s+with)\b[^.!?]{0,60}\b(?:injur\w*|tear|strain|sprain|fracture|tendonitis|tendinitis|bursitis|impingement)\b", re.I),
    re.compile(r"\b(?:should|must|try|take|use|start|stop)\b[^.!?]{0,50}\b(?:medication|medicine|ibuprofen|nsaids?|painkillers?|rehab|rehabilitation|treatment|pain)\b", re.I),
    re.compile(r"\b(?:train|push|work)\s+through\s+(?:the\s+)?(?:sharp\s+)?pain\b", re.I),
    re.compile(r"(?:يجب|ينبغي|خذ|تناول|استخدم|ابدأ|توقف)[^.!?؟]{0,50}(?:دواء|مسكن|إيبوبروفين|علاج|إصابة|ألم)", re.I),
    re.compile(r"(?:لديك|هذا|يبدو)[^.!?؟]{0,50}(?:تمزق|التهاب|إصابة|تشخيص)", re.I),
    re.compile(r"(?:طبيب|طبية|تشخيص|إصابة|ألم|علاج|دواء|تأهيل)"),
)
PART_WORDS = {
    "consistency": re.compile(r"\bconsistency\b|الاتساق|اتساق|الالتزام|التزام", re.I),
    "progression": re.compile(r"\bprogress(?:ion)?\b|التقدم|تقدم", re.I),
    "volume_trend": re.compile(r"\bvolume(?:\s+trend)?\b|الحجم|حجم العمل", re.I),
}
PART_EVIDENCE = {
    "consistency": re.compile(r"\bweeks?\b|weekly target|training target|أسبوع|اسبوع|أسابيع|الأسابيع|هدف التدريب", re.I),
    "progression": re.compile(
        r"personal records?|\bregress(?:ion|ed|ing)?\b|أرقام قياسية شخصية|رقم قياسي شخصي|"
        r"رقمين قياسيين شخصيين|رقمان قياسيان شخصيان|أرقام شخصية|رقم شخصي|تراجع",
        re.I,
    ),
    "volume_trend": re.compile(r"\bvolume\b|\bkg\b|حجم العمل|الحجم|إجمالي الوزن المرفوع", re.I),
}
PART_FACT_EVIDENCE = {
    **PART_EVIDENCE,
    "volume_trend": re.compile(r"\bkg\b|إجمالي الوزن المرفوع", re.I),
}
INSUFFICIENT_LABEL = re.compile(
    r"\b(?:not enough|insufficient|too few|no data|no records?)\b|بيانات غير كافية",
    re.I,
)
INSUFFICIENT_STATUS = re.compile(
    r"\b(?:not enough|(?:do|does|did)n['’]?t have enough|insufficient|too few|no recorded data)\b|"
    r"بيانات غير كافية|لا توجد بيانات كافية",
    re.I,
)
VOLUME_RISE = re.compile(
    r"\b(?:rose|rising|increas\w*|climb\w*|grew|growth|upward|higher|uptick)\b|"
    r"(?:ارتفع|يرتفع|يزداد|ازدياد|زاد|زيادة|تصاعد|ارتفاع|أعلى)",
    re.I,
)
VOLUME_FALL = re.compile(
    r"\b(?:fell|falling|decreas\w*|declin\w*|drop\w*|downward|lower)\b|"
    r"(?:انخفض|ينخفض|انخفاض|تراجع|تراجَع|هبط|أقل)",
    re.I,
)
VOLUME_HOLD = re.compile(
    r"\b(?:holding|held steady|steady|stable|unchanged|flat|level|same)\b|"
    r"(?:مستقر|ثابت|استقرار|ثبات|لم يتغير|لم يتبدل|بقي كما هو)",
    re.I,
)
VOLUME_NON_DIRECTION_RATING = re.compile(
    r"\b(?:strong|needs attention|not enough data|not enough weeks(?: yet)?|improv\w*|"
    r"poor|good|great|excellent|solid|weak)\b|"
    r"(?:قوي|قوية|يحتاج إلى اهتمام|بيانات غير كافية|تحسن|جيد|جيدة|ممتاز|ضعيف)",
    re.I,
)
RATING_CLAIM_WORDS = re.compile(
    r"\b(?:strong|steady|needs attention|improv\w*|poor|good|great|excellent|solid|weak)\b|"
    r"(?:قوي|قوية|ثابت|مستقر|تحسن|جيد|جيدة|ممتاز|ضعيف)",
    re.I,
)
ARABIC_THIRD_PERSON = re.compile(r"اللاعب(?:ة|ين|ات)?", re.I)
ENGLISH_THIRD_PERSON = re.compile(r"\b(?:the player|player|he|him|his|she|her)\b", re.I)
ARABIC_SECOND_PERSON = re.compile(
    r"(?:^|[\s،,.!?؟])(?:أنت|حققت|سجلت|حافظت|أظهرت|التزمت|أنجزت|رفعت|أكملت|بلغت|"
    r"واصلت|واصل|استمررت|استمر|ركزت|ركز|لديك)(?=$|[\s،,.!?؟])|"
    r"(?:التزامك|تقدمك|حجمك|أداؤك|نتائجك|سجلاتك|أهدافك|انتظامك)",
    re.I,
)
ENGLISH_SECOND_PERSON = re.compile(
    r"\b(?:you|your|you're|you've|you'll|yourself)\b|"
    r"(?:^|[.!?]\s*)(?:keep|focus|continue|stay|build|hit|track|celebrate|train|"
    r"work|aim|maintain|review)\b",
    re.I,
)
ARABIC_WORKOUT_TERM = re.compile(r"(?:حصة|حصص)\s+تدريبية")
ARABIC_WORKOUT_REFERENCE = re.compile(r"workouts?|تمرين|تمارين|حصة|حصص|مرات|مرة", re.I)
ARABIC_KG_VARIANT = re.compile(r"كجم|كغ")
WORKOUT_COUNT_WORDS = re.compile(r"\bworkouts?\b|(?:حصة|حصص)\s+تدريبية", re.I)
ARABIC_PRONOUN_SUFFIXES = ("كما", "هما", "هن", "هم", "ها", "كم", "كن", "نا", "ك", "ه", "ي")


def _numbers(text: str) -> set[Decimal]:
    values = set()
    normalized = (text or "").translate(ARABIC_NUMBER_TRANSLATION)
    for token in NUMBER_RE.findall(normalized):
        try:
            values.add(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return values


def _sentence_count(answer: str) -> int:
    return len([part for part in SENTENCE_SPLIT_RE.split((answer or "").strip()) if part.strip()])


def check_uses_supplied_facts(answer: str, expected_terms: list[str]) -> dict[str, Any]:
    lowered = (answer or "").casefold()
    answer_tokens = _arabic_fact_tokens(answer or "")
    observed = [
        term
        for term in expected_terms
        if (ARABIC_RE.search(term) and _arabic_term_matches(term, answer_tokens))
        or (not ARABIC_RE.search(term) and term.casefold() in lowered)
    ]
    return {"name": "uses_supplied_facts", "passed": bool(observed), "matched_terms": observed}


def _arabic_fact_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = ARABIC_MARK_RE.sub("", normalized)
    words = re.findall(r"[\u0621-\u063a\u0641-\u064a\u066e-\u06d3\u06fa-\u06fc]+", normalized)
    return [_arabic_stem(word) for word in words]


def _arabic_stem(word: str) -> str:
    if word.startswith("ال") and len(word) > 4:
        word = word[2:]
    for suffix in ARABIC_PRONOUN_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) > 2:
            return word[: -len(suffix)]
    return word


def _arabic_term_matches(term: str, answer_tokens: list[str]) -> bool:
    term_tokens = _arabic_fact_tokens(term)
    width = len(term_tokens)
    return bool(width) and any(
        answer_tokens[index : index + width] == term_tokens
        for index in range(len(answer_tokens) - width + 1)
    )


def check_no_invented_numbers(answer: str, facts_text: str) -> dict[str, Any]:
    answer_numbers = _numbers(answer)
    allowed = _numbers(facts_text)
    invented = sorted(str(value) for value in answer_numbers - allowed)
    return {"name": "no_invented_numbers", "passed": not invented, "invented": invented}


def check_language(answer: str, language: str) -> dict[str, Any]:
    """English/Arabic script heuristic, not a classifier for arbitrary languages."""
    arabic_count = len(ARABIC_LETTER_RE.findall(answer or ""))
    english_count = len(ENGLISH_LETTER_RE.findall(answer or ""))
    if language == "ar":
        passed = arabic_count >= 10 and arabic_count >= english_count
    else:
        passed = not ARABIC_RE.search(answer or "")
    return {
        "name": "language_match",
        "passed": passed,
        "language": language,
        "arabic_letters": arabic_count,
        "english_letters": english_count,
    }


def check_no_medical_advice(answer: str) -> dict[str, Any]:
    matched = [pattern.pattern for pattern in MEDICAL_PATTERNS if pattern.search(answer or "")]
    return {"name": "no_medical_advice", "passed": not matched, "matched": matched}


def check_sentence_count(answer: str) -> dict[str, Any]:
    count = _sentence_count(answer)
    return {"name": "sentence_count", "passed": 2 <= count <= 4, "count": count}


def check_no_identifiers(answer: str, prompt: str, identifiers: list[str]) -> dict[str, Any]:
    leaked = [value for value in identifiers if value and (value in (answer or "") or value in (prompt or ""))]
    return {"name": "no_identifiers", "passed": not leaked, "leaked": leaked}


def check_style_wording(answer: str, expect: dict[str, Any], coach_tone: str = "") -> dict[str, Any]:
    """Checks explicit brevity/reasoning expectations, not subjective tone quality."""
    word_count = len(answer.split())
    maximum = expect.get("max_words")
    if coach_tone == "concise":
        maximum = min(maximum, 35) if maximum is not None else 35
    terms = expect.get("reasoning_terms_any") or []
    style_terms = expect.get("style_terms_any") or []
    matched = [term for term in terms if term.casefold() in answer.casefold()]
    matched_style = [term for term in style_terms if term.casefold() in answer.casefold()]
    return {
        "name": "style_wording",
        "passed": (maximum is None or word_count <= maximum)
        and (not terms or bool(matched))
        and (not style_terms or bool(matched_style)),
        "word_count": word_count,
        "matched_terms": matched,
        "matched_style_terms": matched_style,
    }


def _shared_status_is_stated(sentence: str, labels: list[str], insufficient: bool) -> bool:
    same_label = len({label.casefold() for label in labels}) == 1
    if same_label and re.search(re.escape(labels[0]), sentence, re.I):
        return True
    return insufficient and bool(INSUFFICIENT_STATUS.search(sentence))


def _has_part_specific_evidence(sentence: str, insufficient: bool) -> bool:
    if NUMBER_RE.search(sentence) or any(
        pattern.search(sentence) for pattern in (VOLUME_RISE, VOLUME_FALL, VOLUME_HOLD)
    ):
        return True
    if PART_FACT_EVIDENCE["progression"].search(sentence):
        return True
    if PART_FACT_EVIDENCE["volume_trend"].search(sentence):
        return True
    return not insufficient and bool(PART_FACT_EVIDENCE["consistency"].search(sentence))


def _shared_status_without_cross_evidence(sentence: str, rating: list[dict[str, Any]]) -> bool:
    mentioned = [part for part, pattern in PART_WORDS.items() if pattern.search(sentence)]
    if len(mentioned) < 2:
        return False
    labels_by_part = {
        str(item.get("part", "")).casefold().replace(" ", "_"): str(item.get("label", "")).strip()
        for item in rating
    }
    labels = [labels_by_part.get(part, "") for part in mentioned]
    if any(not label for label in labels):
        return False

    insufficient = all(INSUFFICIENT_LABEL.search(label) for label in labels)
    if not _shared_status_is_stated(sentence, labels, insufficient):
        return False
    if _has_part_specific_evidence(sentence, insufficient):
        return False

    remaining = sentence
    for label in labels:
        remaining = re.sub(re.escape(label), "", remaining, flags=re.I)
    return not RATING_CLAIM_WORDS.search(remaining)


def _part_evidence_issues(
    sentence: str, sentence_number: int, shared_status: bool = False
) -> list[str]:
    evidence = {part for part, pattern in PART_EVIDENCE.items() if pattern.search(sentence)}
    issues = []
    for part, pattern in PART_WORDS.items():
        misplaced = sorted(evidence - {part}) if pattern.search(sentence) else []
        if misplaced and not shared_status:
            issues.append(f"sentence {sentence_number} attributes {misplaced} evidence to {part}")
    if WORKOUT_COUNT_WORDS.search(sentence) and RATING_CLAIM_WORDS.search(sentence):
        unsupported = [
            part
            for part, pattern in PART_WORDS.items()
            if pattern.search(sentence) and not PART_FACT_EVIDENCE[part].search(sentence)
        ]
        if unsupported:
            issues.append(
                f"sentence {sentence_number} uses the workout count to support {sorted(unsupported)}"
            )
    return issues


def _volume_direction_issue(
    sentence: str, sentence_number: int, volume_label: str, shared_status: bool = False
) -> str | None:
    if not PART_EVIDENCE["volume_trend"].search(sentence):
        return None
    directions = {
        direction
        for direction, pattern in (
            ("rising", VOLUME_RISE),
            ("falling", VOLUME_FALL),
            ("holding", VOLUME_HOLD),
        )
        if pattern.search(sentence)
    }
    expected_direction = volume_label.casefold()
    if expected_direction not in {"rising", "falling", "holding"}:
        expected_direction = ""
    if directions and (len(directions) > 1 or directions != {expected_direction}):
        return f"sentence {sentence_number} states a volume direction inconsistent with {volume_label.title()}"
    rating_word_text = re.sub(
        rf"(?<!\w){re.escape(volume_label)}(?!\w)", "", sentence, flags=re.I
    ) if volume_label else sentence
    if VOLUME_NON_DIRECTION_RATING.search(rating_word_text) and not shared_status:
        return f"sentence {sentence_number} attaches another rating word to volume"
    return None


def check_rating_part_attribution(answer: str, rating: list[dict[str, Any]]) -> dict[str, Any]:
    sentences = [part for part in SENTENCE_SPLIT_RE.split(answer or "") if part.strip()]
    volume_label = next(
        (str(item.get("label", "")).casefold() for item in rating if item.get("part") == "Volume trend"),
        "",
    )
    shared_statuses = [
        _shared_status_without_cross_evidence(sentence, rating) for sentence in sentences
    ]
    issues = [
        issue
        for index, sentence in enumerate(sentences, 1)
        for issue in _part_evidence_issues(sentence, index, shared_statuses[index - 1])
    ]
    issues.extend(
        issue
        for index, sentence in enumerate(sentences, 1)
        if (
            issue := _volume_direction_issue(
                sentence, index, volume_label, shared_statuses[index - 1]
            )
        ) is not None
    )
    return {"name": "rating_part_attribution", "passed": not issues, "issues": issues}


def check_second_person_address(answer: str, language: str) -> dict[str, Any]:
    if language == "ar":
        third_person = bool(ARABIC_THIRD_PERSON.search(answer or ""))
        direct_address = bool(ARABIC_SECOND_PERSON.search(answer or ""))
    else:
        third_person = bool(ENGLISH_THIRD_PERSON.search(answer or ""))
        direct_address = bool(ENGLISH_SECOND_PERSON.search(answer or ""))
    return {
        "name": "second_person_address",
        "passed": direct_address and not third_person,
        "direct_address_found": direct_address,
        "third_person_reference": third_person,
    }


def _workout_count_uses_glossary(answer: str, workouts: Any) -> bool:
    if workouts is None:
        return True
    count = re.compile(rf"(?<!\d){re.escape(str(int(workouts)))}(?!\d)")
    for match in count.finditer(answer or ""):
        surrounding_words = (answer or "")[max(0, match.start() - 18) : match.end() + 24]
        if ARABIC_WORKOUT_REFERENCE.search(surrounding_words) and not ARABIC_WORKOUT_TERM.search(surrounding_words):
            return False
    return True


def check_arabic_glossary(
    answer: str, facts: dict[str, Any], language: str = "ar"
) -> dict[str, Any]:
    if language != "ar":
        return {"name": "arabic_glossary", "passed": True}
    workouts = facts.get("workouts_in_period")
    workout_count_uses_glossary = _workout_count_uses_glossary(answer, workouts)
    bad_unit = bool(ARABIC_KG_VARIANT.search(answer or ""))
    workout_term_present = bool(ARABIC_WORKOUT_TERM.search(answer or ""))
    return {
        "name": "arabic_glossary",
        "passed": workout_count_uses_glossary and not bad_unit,
        "workout_count_uses_glossary": workout_count_uses_glossary,
        "arabic_kg_spelling": bad_unit,
        "workout_term_present": workout_term_present,
    }


def evaluate_case(case: dict[str, Any], prompt: str, answer: str) -> dict[str, Any]:
    expect = case.get("expect") or {}
    language = str(case.get("language", "en"))
    facts = case.get("facts") or {}
    rating = list(case.get("rating") or [])
    facts_text = render_review(
        facts, rating, language
    )
    checks = [
        check_uses_supplied_facts(answer, list(expect.get("fact_terms_any") or [])),
        check_no_invented_numbers(answer, facts_text),
        check_language(answer, language),
        check_rating_part_attribution(answer, rating),
        check_second_person_address(answer, language),
        check_arabic_glossary(answer, facts, language),
        check_no_medical_advice(answer),
        check_sentence_count(answer),
        check_no_identifiers(answer, prompt, list(expect.get("must_not_contain") or [])),
        check_style_wording(answer, expect, str(case.get("coach_tone", ""))),
    ]
    return {
        "case_id": case.get("id", "?"),
        "answer": answer,
        "checks": {check["name"]: check for check in checks},
        "passed": all(check["passed"] for check in checks),
    }


__all__ = [
    "evaluate_case",
    "check_arabic_glossary",
    "check_no_invented_numbers",
    "check_language",
    "check_no_medical_advice",
    "check_rating_part_attribution",
    "check_second_person_address",
]
