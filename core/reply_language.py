"""Resolve reply language by grammatical markers, then dominant script.

Curated Arabic and English function words and common chat markers decide first.
Arabic diacritics, tatweel and hamza variants are normalized, and attached Arabic
proclitics are recognized on matching function words. When counts tie or are both zero,
retained Latin names after Arabic proclitics are excluded before comparing letter
counts. Near ties and messages without letters use Display language.
"""

import re
import unicodedata

from core.display_language import DisplayLanguage

ARABIC_LETTER_RE = re.compile(r"[\u0621-\u064a\u066e-\u06d3\u06fa-\u06fc]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
ARABIC_WORD_RE = re.compile(r"[\u0621-\u064a\u066e-\u06d3\u06fa-\u06fc]+")
ENGLISH_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]+(?:'[A-Za-z]+)?(?![A-Za-z0-9])"
)
ARABIZI_WORD_RE = re.compile(r"[A-Za-z0-9]+")
LATIN_SPAN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[ \t]+[A-Za-z][A-Za-z0-9]*)*"
)
ARABIC_PROCLITICS = ("ال", "ب", "ل", "و", "ف")
NEAR_TIE_LETTER_MARGIN = 1
ARABIC_VARIANT_TRANSLATION = str.maketrans({"ٱ": "ا", "ى": "ي"})

ARABIC_FUNCTION_WORDS = frozenset(
    {
        "انا", "انت", "انتي", "انتم", "احنا", "هو", "هي", "هم",
        "ده", "دي", "دول", "دا", "في", "من", "على", "عن", "مع",
        "الى", "او", "و", "ف", "ب", "ل", "ال", "يا", "لي", "لك",
        "ليه", "ايه", "ازاي", "عايز", "عاوز", "عايزة", "عاوزة",
        "هل", "كام", "امتى", "ممكن", "بدل", "استبدل", "غير", "قوللي",
        "قول", "اعمل", "اعرف", "ازود", "ارفع", "انزل", "خلي",
        "ظبط", "تمرن", "اللي", "مش", "ما", "ماذا", "متى", "كيف", "كم",
        "هذا", "هذه", "ذلك", "تلك", "كان", "يكون", "الذي", "التي",
    }
)
ARABIC_CHAT_MARKERS = frozenset({"مريح", "مريحة"})
ENGLISH_FUNCTION_WORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "am", "was", "were", "be", "been",
        "being", "do", "does", "did", "how", "what", "when", "where",
        "why", "who", "which", "me", "my", "mine", "we", "they", "he",
        "she", "it", "for", "to", "of", "in", "on", "at", "with", "from",
        "by", "and", "or", "but", "if", "can", "could", "should", "would",
        "will", "please", "doing", "this", "that", "these", "those", "have",
        "has", "had", "about", "between", "after", "before", "ok",
        "swap", "replace", "change", "switch", "call",
    }
)
ARABIZI_FUNCTION_WORDS = frozenset(
    {"3ayez", "3ayza", "a3raf", "eh", "eih", "ezay", "a7san", "lel", "el", "w", "ad"}
)

CHAT_GLOSSARY_RULE = (
    "App features use glossary terms برنامج تدريبي, مكتبة التمارين, محطة تقدم; "
    "otherwise use everyday gym words سيتات, عدّات. Keep exercise names, RIR, "
    "abbreviations. Arabic replies: all numbers use Western digits 0-9, never ٠-٩; "
    "write kg, never كجم; call total weight إجمالي الوزن المرفوع."
)


def _normalize_arabic(text: str) -> str:
    """Remove Arabic marks and normalize hamza forms before word matching."""
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character != "ـ"
    )
    return without_marks.translate(ARABIC_VARIANT_TRANSLATION)


def _arabic_word_function_count(word: str) -> int:
    """Count a function word, including attached preposition/conjunctions."""
    if word in ARABIC_FUNCTION_WORDS:
        return 1

    proclitic_count = 0
    remaining = word
    while remaining:
        if remaining in ARABIC_FUNCTION_WORDS:
            return proclitic_count + 1
        proclitic = next(
            (
                prefix
                for prefix in ARABIC_PROCLITICS
                if remaining.startswith(prefix) and len(remaining) > len(prefix)
            ),
            None,
        )
        if proclitic is None:
            return 0
        proclitic_count += 1
        remaining = remaining[len(proclitic) :]
    return 0


def _function_word_counts(message: str) -> tuple[int, int]:
    normalized_arabic = _normalize_arabic(message)
    arabic_count = sum(
        _arabic_word_function_count(word) + (word in ARABIC_CHAT_MARKERS)
        for word in ARABIC_WORD_RE.findall(normalized_arabic)
    )
    english_count = sum(
        word.lower() in ENGLISH_FUNCTION_WORDS
        for word in ENGLISH_WORD_RE.findall(message)
    )
    arabizi_count = sum(
        word.lower() in ARABIZI_FUNCTION_WORDS
        for word in ARABIZI_WORD_RE.findall(message)
    )
    return arabic_count + arabizi_count, english_count


def _has_arabic_proclitic(word: str) -> bool:
    normalized_word = _normalize_arabic(word)
    return any(
        normalized_word.startswith(prefix)
        and len(normalized_word) > len(prefix)
        for prefix in ARABIC_PROCLITICS
    )


def _previous_word(text: str) -> str:
    match = re.search(r"([^\s]+)\s*$", text)
    if match is None:
        return ""
    return match.group(1).strip(".,:!?؟،؛()[]{}\"'")


def _exclude_retained_latin_names(message: str) -> str:
    """Remove Latin spans directly introduced by Arabic tatweel or proclitics."""
    characters = list(message)
    for match in LATIN_SPAN_RE.finditer(message):
        previous = _previous_word(message[: match.start()])
        if not previous:
            continue
        has_arabic_tatweel = previous.endswith("ـ")
        if has_arabic_tatweel or _has_arabic_proclitic(previous):
            characters[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(characters)


def normalize_display_language(language: object) -> DisplayLanguage:
    """Return one of the supported Display language codes, defaulting to English."""
    return "ar" if language == "ar" else "en"


def resolve_reply_language(
    message: str, display_language: object = "en"
) -> DisplayLanguage:
    """Resolve by function words, then dominant letters, then Display language."""
    arabic_words, english_words = _function_word_counts(message)
    if arabic_words > english_words:
        return "ar"
    if english_words > arabic_words:
        return "en"

    countable_text = _exclude_retained_latin_names(message)
    arabic_letters = len(ARABIC_LETTER_RE.findall(countable_text))
    latin_letters = len(LATIN_LETTER_RE.findall(countable_text))
    if arabic_letters - latin_letters > NEAR_TIE_LETTER_MARGIN:
        return "ar"
    if latin_letters - arabic_letters > NEAR_TIE_LETTER_MARGIN:
        return "en"
    return normalize_display_language(display_language)


def language_label(language: DisplayLanguage) -> str:
    """Return the prompt-facing language name for a normalized language code."""
    return "Arabic" if language == "ar" else "English"
