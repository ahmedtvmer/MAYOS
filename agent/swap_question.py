"""Matches a Player's answer to chat's own swap question (#858).

When chat asks which exercise the Player means («هل تقصد A أو B؟»), the next
message is matched here against the listed candidates, in code: a partial
name, Arabic or Franco spelling, a typo, an ordinal («التاني», "2"), a
distinguishing word, or a correction («لا فرونت»).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

from core.arabic import normalize_arabic_text

# An answer to "which one?" is short; a longer message is a new request.
MAX_ANSWER_WORDS = 6

_ORDINALS = {
    0: {"1", "1st", "first", "awel", "awal", "awwel", "الاول", "اول", "الاولي", "اولاني", "الاولاني", "اولى"},
    1: {"2", "2nd", "second", "tany", "tani", "tanya", "التاني", "الثاني", "تاني", "ثاني", "التانيه", "الثانيه", "التانيه"},
    2: {"3", "3rd", "third", "talet", "talt", "taalet", "التالت", "الثالث", "تالت", "ثالث", "التالته", "الثالثه"},
    -1: {"last", "akher", "a5er", "الاخير", "الاخيره", "اخر", "الاخر"},
}
_ORDINAL_WORDS = {word: index for index, words in _ORDINALS.items() for word in words}

# Leading words of a correction or a pointer: «لا فرونت», "no, the front one".
_FILLER_WORDS = {
    "or", "wala", "walla", "ولا", "او",
    "no", "nope", "nah", "la", "la2", "laa", "لا", "لاء", "لأ",
    "i", "mean", "meant", "قصدي", "اقصد", "يعني", "the", "a", "one", "el", "al",
    "please", "pls", "plz", "بتاع", "اللي", "ده", "دي", "دا", "واحد",
    "رقم", "number", "no.", "option", "choice", "اختيار", "it", "is", "its", "it's",
}

# Exercise words written in Arabic script (Egyptian gym speech and MSA). Keys are
# normalized with core.arabic.normalize_arabic_text.
_ARABIC_EXERCISE_WORDS = {
    "فرونت": "front", "سايد": "side", "جانبي": "side", "امامي": "front",
    "بلانك": "plank", "باور": "power", "بوينت": "point", "بوينط": "point",
    "انكلاين": "incline", "انكلين": "incline", "انكلن": "incline", "مائل": "incline", "مايل": "incline",
    "ديكلاين": "decline", "دكلاين": "decline", "فلات": "flat", "مستوي": "flat",
    "بنش": "bench", "برس": "press", "بريس": "press", "ضغط": "press",
    "دمبل": "dumbbell", "دامبل": "dumbbell", "دامبيل": "dumbbell", "دنبل": "dumbbell",
    "بار": "barbell", "باربل": "barbell", "سميث": "smith", "ماشين": "machine",
    "مكنه": "machine", "مكينه": "machine", "جهاز": "machine", "كابل": "cable", "كيبل": "cable",
    "ويتد": "weighted", "سكوات": "squat", "ديدلفت": "deadlift", "ديدليفت": "deadlift",
    "رو": "row", "كيرل": "curl", "كرل": "curl", "فلاي": "fly", "لاترال": "lateral",
    "ريز": "raise", "ليج": "leg", "اكستنشن": "extension", "هامر": "hammer",
    "شولدر": "shoulder", "اوفرهيد": "overhead", "روماني": "romanian", "بلغاري": "bulgarian",
    "لانج": "lunge", "لانجز": "lunge", "هيب": "hip", "ثرست": "thrust", "كرنش": "crunch",
    "هاي": "high", "لو": "low", "كلوز": "close", "وايد": "wide", "جريب": "grip",
    "ريفيرس": "reverse", "سينجل": "single", "سيتد": "seated", "جالس": "seated", "واقف": "standing",
    "بوش": "push", "بول": "pull", "داون": "down", "اب": "up", "تشست": "chest", "صدر": "chest",
}
# "Not X" rules X out («مش السايد»); «لا X» is a correction that picks X.
_NEGATION_WORDS = {"not", "never", "مش", "msh", "mesh", "mish", "مو", "غير"}
_ARABIC_PREFIXES = ("بال", "وال", "لل", "ال", "ب", "و")
_LATIN_ABBREVIATIONS = {"db": "dumbbell", "bb": "barbell", "kb": "kettlebell", "sm": "smith"}
_FUZZY_THRESHOLD = 0.8


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return normalize_arabic_text(text).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", _normalized(text))


def _arabic_word(word: str) -> str | None:
    if word in _ARABIC_EXERCISE_WORDS:
        return _ARABIC_EXERCISE_WORDS[word]
    for prefix in _ARABIC_PREFIXES:
        stem = word[len(prefix):]
        if word.startswith(prefix) and len(stem) >= 2 and stem in _ARABIC_EXERCISE_WORDS:
            return _ARABIC_EXERCISE_WORDS[stem]
    return None


def _answer_words(answer: str) -> tuple[list[str], list[str]]:
    """Answer words in English, with filler removed, split into named and
    negated words. Arabic-script words that are not exercise words stay as
    written, so they count against the match."""
    words: list[str] = []
    negated: list[str] = []
    # A negation lasts to the end of its clause: "not the side, the front".
    for clause in re.split(r"[,،.;!?؟]|\bbut\b|(?<!\w)بس(?!\w)", answer):
        negating = False
        for word in _words(clause):
            if word in _NEGATION_WORDS:
                negating = True
                continue
            if word in _FILLER_WORDS:
                continue
            word = _arabic_word(word) or _LATIN_ABBREVIATIONS.get(word, word)
            (negated if negating else words).append(word)
    return words, negated


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _word_matches(answer_word: str, name_word: str) -> bool:
    answer_word, name_word = _stem(answer_word), _stem(name_word)
    if answer_word == name_word:
        return True
    if len(answer_word) >= 3 and name_word.startswith(answer_word):
        return True
    return (
        len(answer_word) >= 4
        and SequenceMatcher(None, answer_word, name_word).ratio() >= _FUZZY_THRESHOLD
    )


def _candidate_words(candidate: dict[str, Any]) -> set[str]:
    return {
        word
        for field in ("name", "source_name")
        for word in _words(candidate.get(field) or "")
    }


def _ordinal_choice(words: list[str], candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if len(words) != 1 or words[0] not in _ORDINAL_WORDS:
        return None
    index = _ORDINAL_WORDS[words[0]]
    if index >= len(candidates):
        return []
    return [candidates[index]]


def match_swap_answer(
    answer: str, candidates: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The candidates the answer points to, in their asked order.

    One candidate resumes the swap; several mean chat asks again with those;
    none means the message is not an answer to the question.
    """
    raw_words = _words(answer)
    if not raw_words or len(raw_words) > MAX_ANSWER_WORDS or not candidates:
        return []
    words, negated = _answer_words(answer)
    if negated:
        excluded = _matching(negated, candidates)
        if not excluded:
            return []
        candidates = [candidate for candidate in candidates if candidate not in excluded]
        if not words:
            return candidates
    ordinal = _ordinal_choice(words, candidates)
    if ordinal is not None:
        return ordinal
    if not words:
        return []
    return _matching(words, candidates)


def _matching(words: list[str], candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The candidates that best fit the words, or none when most words name
    no part of any candidate."""
    names = [_candidate_words(candidate) for candidate in candidates]
    joined = " ".join(words)
    exact = [
        candidate for candidate in candidates
        if " ".join(_words(candidate.get("name") or "")) == joined
    ]
    if len(exact) == 1:
        return exact
    hits = [
        {word for word in words if any(_word_matches(word, name) for name in name_words)}
        for name_words in names
    ]
    matched_words = set().union(*hits)
    # Most answer words must name a part of some candidate; otherwise the
    # Player wrote something else («فرونت» answers, «انا تعبان» does not).
    if not matched_words or len(matched_words) * 2 < len(set(words)):
        return []
    best = max(len(hit) for hit in hits)
    return [
        candidate for candidate, hit in zip(candidates, hits)
        if hit and len(hit) == best
    ]
