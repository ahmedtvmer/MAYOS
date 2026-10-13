"""Deterministic rubric for model-written Checkpoint review evaluations."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from service.checkpoint_review_ai import render_review

NUMBER_RE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|\.\d|,\d)")
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
ARABIC_LETTER_RE = re.compile(r"[\u0621-\u063a\u0641-\u064a\u066e-\u06d3\u06fa-\u06fc]")
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
    observed = [term for term in expected_terms if term.casefold() in lowered]
    return {"name": "uses_supplied_facts", "passed": bool(observed), "matched_terms": observed}


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


def check_style_wording(answer: str, expect: dict[str, Any]) -> dict[str, Any]:
    """Checks explicit brevity/reasoning expectations, not subjective tone quality."""
    word_count = len(answer.split())
    maximum = expect.get("max_words")
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


def _part_evidence_issues(sentence: str, sentence_number: int) -> list[str]:
    evidence = {part for part, pattern in PART_EVIDENCE.items() if pattern.search(sentence)}
    issues = []
    for part, pattern in PART_WORDS.items():
        misplaced = sorted(evidence - {part}) if pattern.search(sentence) else []
        if misplaced:
            issues.append(f"sentence {sentence_number} attributes {misplaced} evidence to {part}")
    if WORKOUT_COUNT_WORDS.search(sentence) and any(pattern.search(sentence) for pattern in PART_WORDS.values()):
        issues.append(f"sentence {sentence_number} connects the neutral workout count to a rating part")
    return issues


def _volume_direction_issue(sentence: str, sentence_number: int, volume_label: str) -> str | None:
    if not PART_EVIDENCE["volume_trend"].search(sentence):
        return None
    rising = bool(VOLUME_RISE.search(sentence))
    falling = bool(VOLUME_FALL.search(sentence))
    holding = bool(VOLUME_HOLD.search(sentence))
    if rising or falling or holding:
        return f"sentence {sentence_number} paraphrases the supplied {volume_label.title()} volume rating"
    return None


def check_rating_part_attribution(answer: str, rating: list[dict[str, Any]]) -> dict[str, Any]:
    sentences = [part for part in SENTENCE_SPLIT_RE.split(answer or "") if part.strip()]
    volume_label = next(
        (str(item.get("label", "")).casefold() for item in rating if item.get("part") == "Volume trend"),
        "",
    )
    issues = [issue for index, sentence in enumerate(sentences, 1) for issue in _part_evidence_issues(sentence, index)]
    issues.extend(
        issue
        for index, sentence in enumerate(sentences, 1)
        if (issue := _volume_direction_issue(sentence, index, volume_label)) is not None
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
        check_style_wording(answer, expect),
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
