"""Deterministic Player data context for hosted chat (ADR 105, ADR 118)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent import player_tools
from agent.player_prompt import (
    HOSTED_PROMPT_MAX_BYTES, HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES,
    get_message_text, message_role,
)
from agent.player_tools import (
    MAX_PLAYER_TOOL_ROUNDS, MAX_TOOL_RESULT_BYTES, run_player_tool_calls,
)
from service.training_status import saturday_week_start
from core.muscle_volume import default_muscle_credits
from core.weak_point_suggestions import WEAK_POINT_ALIASES
from database.shared import _normalize_exercise_name

MAX_ROUTED_CONTEXT_BYTES = 8 * 1024
# Preserve a capped result for each remaining model tool round.
ROUTED_CONTEXT_FALLBACK_RESERVE_BYTES = MAX_TOOL_RESULT_BYTES * MAX_PLAYER_TOOL_ROUNDS
PROGRAM_TOPIC = "program_what_how_many"
NUTRITION_TOPIC = "nutrition"
CARDIO_TOPIC = "cardio_history"
_PROGRAM = re.compile(r"\b(?:program|routine|split|(?:training|workout) plan)\b|برنامج|برنامجي|تقسيم", re.I)
_QUESTION = re.compile(
    r"\b(?:what|how|which|show|list|tell|check|read|retrieve|review|summari[sz]e|compare|"
    r"sets?|reps?|frequency|often|volume)\b|"
    r"ايه|إيه|كام|كم|ازاي|إزاي|وريني|اعرض|ارني|اخبرني|تمارين|سيتات|مجموعات|عدات|تكرار", re.I,
)
_OTHER_TOPIC = re.compile(
    r"\b(?:why|rationale|progress|history|last|yesterday|lifted|ate|calories|nutrition|technique|form|cue|pain|hurts?|injury)\b|"
    r"ليه|السبب|اتحسن|تقدمي|امبارح|اكلت|سعرات|تغذي|وجع|اصاب|\bاخر\b|(?:عملت|رفعت)\s+(?:كام|كم)", re.I,
)
_PROGRAM_MEASURE = re.compile(
    r"\b(?:sets?|reps?|exercises?|frequency|volume|train|workouts?)\b|"
    r"تمارين|سيتات|مجموعات|عدات|تكرار|بتمرن|بتدرب", re.I,
)
_ARABIC_NUTRITION = (
    r"(?<!\w)(?:[بوكل])?(?:ال)?(?:تغذية|سعرات|سعرة|سعر|بروتين|ماكروز|"
    r"كارب|كربوهيدرات|دهون|دهن|غذائي|غذائية)(?:ي|نا|ك|كم|ه|ها|هم)?(?!\w)"
)
_NUTRITION_TERMS = re.compile(
    r"\b(?:nutrition|calories?|kcal|macros?|protein|carbs?|carbohydrates?|fat|intake|diet)\b|"
    + _ARABIC_NUTRITION,
    re.IGNORECASE,
)
_FOOD_LOG_QUESTION = re.compile(
    r"\b(?:eat|ate|eaten|drink|drank|drunk|food|meal\s+log|food\s+entries|meals?|"
    r"breakfast|lunch|dinner|snacks?)\b|"
    r"(?<!\w)(?:[بوكل])?(?:ال)?(?:اكلت|اكل|طعام|وجبة|وجبات|فطور|فطار|غداء|غدا|عشاء|عشا|"
    r"فطرت|اتغديت|اتعشيت|شربت)(?:ي|نا)?(?!\w)", re.IGNORECASE,
)
_PERSONAL_INTAKE = re.compile(
    r"\b(?:i\s+(?:ate|have\s+eaten|ve\s+eaten|consumed|have\s+consumed|ve\s+consumed)|"
    r"i\s+(?:had|drank)|(?:did|have)\s+i\s+(?:not\s+)?(?:eat|eaten|consume|consumed|drink|drunk|have|had)|"
    r"my\s+(?:food|meal|nutrition|calorie|protein)?\s*intake)\b|"
    r"(?<!\w)(?:اكلت|تناولت|سجلت|فطرت|اتغديت|اتعشيت|شربت|استهلكت)(?:ه|ها|هم|ش)?(?!\w)", re.IGNORECASE,
)
_PERSONAL_NUTRITION_LOG = re.compile(
    r"\b(?:did\s+i\s+log|have\s+i\s+logged|i\s+logged)\b|"
    r"(?<!\w)(?:سجلت|سجلتها|سجلتي|سجلي)(?!\w)", re.IGNORECASE,
)
_PERSONAL_NUTRITION_REFERENCE = re.compile(
    r"\bmy\s+(?:(?:daily|logged|saved|total|nutrition|food|meal|protein|calorie|macro)\s+)*"
    r"(?:nutrition|calories?|protein|macros?|carbs?|carbohydrates?|fat|diet|intake|"
    r"targets?|goals?|plan|log|entries|meals?|trend|history)\b|"
    r"(?<!\w)(?:[بوكل])?(?:ال)?(?:سعرات|سعرة|سعر|بروتين|ماكروز|كارب|كربوهيدرات|"
    r"دهون|دهن|تغذية|هدف|اهداف|اكل|وجبات)(?:ي|نا|ك|كم)(?!\w)|"
    r"(?<!\w)(?:بتاعي|بتاعت|بتاعتي|بتوعي|لي|عندي|الخاص(?:ة)?\s+بي)(?!\w)", re.IGNORECASE,
)
_INTAKE_QUANTITY = re.compile(
    r"\b(?:how\s+much|how\s+many|total|amount|intake)\b|"
    r"(?<!\w)(?:كام|كم|قد\s+ايه|اجمالي|مجموع)(?!\w)", re.IGNORECASE,
)
_TARGET_ACHIEVEMENT = re.compile(
    r"\b(?:hit|reach|reached|meet|met|achieve|achieved|remaining|left|short|enough|"
    r"vs|versus|compare|compared|comparison)\b|"
    r"(?<!\w)(?:حققت|حقق|وصلت|وصل|فاضل|متبقي|باقي|لسه|ناقص|احتاج|محتاج|محتاجة|"
    r"مقارنة|مقارن|عامل\s+ازاي|لم\s+(?:احقق|اصل|ابلغ))(?!\w)",
    re.IGNORECASE,
)
_NUTRITION_TARGET = re.compile(
    rf"(?:{_NUTRITION_TERMS.pattern}|{_FOOD_LOG_QUESTION.pattern})\s+"
    r"(?:targets?|goals?|plan)\b|"
    r"\b(?:targets?|goals?|plan)\s+(?:for|of)\s+(?:my\s+)?"
    rf"(?:{_NUTRITION_TERMS.pattern}|{_FOOD_LOG_QUESTION.pattern})|"
    r"(?<!\w)(?:[بوكل])?(?:ال)?(?:هدف|اهداف|خطة)(?:ي|نا|ك|كم)?\s+"
    r"(?:(?:من|في)\s+)?"
    rf"(?:{_NUTRITION_TERMS.pattern}|{_FOOD_LOG_QUESTION.pattern})", re.IGNORECASE,
)
_PERSONAL_TARGET_POSSESSION = re.compile(
    r"\b(?:targets?|goals?|plan)\s+(?:did|do)\s+i\s+have\b", re.I,
)
_NUTRITION_TREND = re.compile(
    r"\b(?:trend|trending|recent|average|over\s+time|day\s+to\s+day)\b|"
    r"(?<!\w)(?:اتجاه|اتجاهات|مؤخرا|متوسط|معدل)(?!\w)", re.IGNORECASE,
)
_PERSONAL_QUESTION = re.compile(
    r"\b(?:do|did|have|am|are|can|could|will)\s+i\b|(?<!\w)(?:هل|ما)(?!\w)", re.IGNORECASE,
)
_FIRST_PERSON_TARGET_QUESTION = re.compile(
    r"\b(?:did|have)\s+i\s+(?:hit|reached?|met|meet|achieved?)\b|"
    r"\bi\s+have\s+left\b|(?<!\w)(?:حققت|وصلت|عامل\s+ازاي|لم\s+(?:احقق|اصل|ابلغ))(?!\w)", re.IGNORECASE,
)
_NUTRITION_VALUE = re.compile(
    r"\bwhat\s+(?:is|are|was|were)\s+my\s+(?:daily\s+)?"
    r"(?:calories?|protein|macros?|carbs?|carbohydrates?|fat|intake)"
    r"(?:\s+(?:today|yesterday|on\b|for\b)|$)", re.IGNORECASE,
)
_OWNED_INTAKE_VALUE = re.compile(
    r"\bmy\s+(?:(?:daily|logged|saved|total)\s+)*"
    r"(?:calories?|protein|macros?|carbs?|carbohydrates?|fat|intake)"
    r"(?=\s+(?:today|yesterday|on|this|for|in|was|were|is|are|total|intake|trend|history)\b|$)|"
    r"(?<!\w)(?:[بوكل])?(?:سعرات|بروتين|ماكروز|كارب|كربوهيدرات|دهون|اكل|وجبات)ي(?!\w)", re.I,
)
_NUTRITION_REMAINING = re.compile(
    r"\b(?:remaining|left|short)\b|(?<!\w)(?:فاضل|متبقي|باقي|ناقص)(?!\w)", re.I,
)
_FOOD_RECORD = re.compile(r"\b(?:log|entries|history)\b|(?<!\w)(?:سجل|سجلي|تاريخ)(?!\w)", re.I)
_SAVED_RECORD_REQUEST = re.compile(
    r"\b(?:show|list|read|retrieve|see|check|summari[sz]e|review|compare|last|recent|"
    r"how\s+(?:much|many)|what\s+(?:is\s+in|was|were)|"
    r"what\s+(?:is|are)\s+my|(?:tell|give)\s+me|empty|recorded|logged)\b|"
    r"(?<!\w)(?:وريني|اعرض|ارني|اخبرني|لخص|راجع|قارن|كام|كم|اجمالي|مجموع|"
    r"اخر|الاخيرة|مؤخرا|عامل\s+ازاي|فيه\s+ايه|موجود|فارغ)(?!\w)", re.I,
)
# Possession alone does not request saved facts: instructions, advice and imagined
# intake must be excluded before past-tense/owned-log signals are considered.
_LOG_GUIDANCE = re.compile(
    r"\b(?:how\s+(?:(?:do|can|could|should|would|may)\s+i\b|i\s+should\b|to\b)|"
    r"should\s+(?:i|my)|(?:can|could|may|must)\s+i\s+(?:use|start|keep|record|log|"
    r"add|edit|delete|track|set|change|calculate|enable|disable|open|eat|drink)|"
    r"what\s+to\s+(?:eat|drink)|"
    r"teach\s+me|explain\s+how|advice|tips|recommend|suggest|best\s+way|used\s+for|useful|benefits?|purpose|"
    r"how\s+(?:does|do)\b.*\bwork|what\s+is\b.*\blog\s+for|"
    r"why\b.*\b(?:log|sessions?|history)\b.*\bimportant)\b|"
    r"(?<!\w)(?:(?:ازاي|كيف)\s+(?:استخدم|استعمل|اسجل|اضيف|احذف|امسح|اعدل|اغير|افتح|ابدا|"
    r"اراجع|اقرا|انظم|يمكنني)|"
    r"(?:استخدم|استعمل|اسجل|اضيف|امسح|اعدل|اغير|افتح|ابدا)(?:ه|ها)?\b.*\bازاي|"
    r"(?:ماذا|ما\s+الذي)\s+(?:ينبغي|يجب)\s+ان\s+(?:اكل|اتناول|اشرب)|"
    r"(?:اكل|اشرب)\s+(?:ايه|ماذا)\s+(?:قبل|بعد)|"
    r"(?:ازاي|كيف)\b.*\b(?:بيشتغل|يعمل)|"
    r"طريقة\s+(?:استخدام|استعمال|مراجعة|تسجيل|اضافة|حذف|تعديل)|نصائح|تنصحني|اقترح)(?!\w)", re.I,
)
_HYPOTHETICAL_CONTEXT = re.compile(
    r"\b(?:if(?!\s+(?:possible|available|you\s+can))|suppose|supposing|imagine|assuming|had\s+i|would\s+i)\b|"
    r"(?<!\w)(?:(?:لو|اذا)(?!\s+سمحت)|بافتراض|افترض|تخيل|في\s+حالة)(?!\w)", re.I,
)
_FACT_CHECK_IF = re.compile(
    r"\b(?:(?:tell|show)(?:\s+me)?|check|see|confirm|verify|know|find\s+out)\s+if\b", re.I,
)
_LOG_READ_DECLINED = re.compile(
    r"\b(?:do\s+not|don\s+t|never)\s+(?:read|load|look\s+up|check|show|use|review|retrieve)\b|"
    r"\bwithout\s+(?:reading|loading|checking|using|looking\s+at)\b|"
    r"(?<!\w)(?:من\s+غير|بدون)\s+(?:قراءة|قراية|فتح|استخدام|مراجعة)|"
    r"(?<!\w)(?:لا\s+(?:تقرا|تستخدم|تعرض|تفتح|تراجع|تحمل)|متقراش|متفتحش|متستخدمش)(?!\w)", re.I,
)
_CARDIO_WORD = re.compile(
    r"\bcardio\b|(?<!\w)(?:لل|[بوكل]?ال|[بوكل])?كارديو(?!\w)", re.IGNORECASE,
)
_CARDIO_PERFORMED = re.compile(
    r"\b(?:did\s+i\s+(?:not\s+)?(?:do|log|perform)|have\s+i\s+(?:not\s+)?(?:done|logged|performed)|"
    r"i\s+(?:did|logged|performed)|logged\s+cardio)\b|"
    r"(?<!\w)(?:(?:عملت|سجلت|اتسجل|لعبت|تمرنت|مارست|اديت|انجزت)(?:ه|ها|هم|ش)?|"
    r"لم\s+(?:امارس|اسجل|العب|اتمرن|اؤد|افعل))(?!\w)", re.IGNORECASE,
)
_CARDIO_HISTORY = re.compile(
    r"\b(?:history|log|sessions?|last|recent)\b|"
    r"(?<!\w)(?:ال)?(?:سجل|جلسات|جلسة|تاريخ|اخر)(?:ي)?(?!\w)", re.IGNORECASE,
)
_PERSONAL_CARDIO = re.compile(
    r"\bmy\s+(?:(?:last|recent|logged)\s+)*cardio\b|"
    r"(?<!\w)(?:بتاعي|بتاعتي|لي|عندي|سجلي|جلساتي|الخاص(?:ة)?\s+بي)(?!\w)", re.IGNORECASE,
)
_PERSONAL_PROGRAM = re.compile(
    r"\bmy\s+(?:training\s+)?program\b|"
    r"(?<!\w)(?:برنامجي|برنامج\s+(?:التدريب\s+)?بتاعي|البرنامج\s+بتاعي)(?!\w)",
    re.IGNORECASE,
)
_FOOD_LOG_YESTERDAY = re.compile(
    r"\b(?:yesterday|last\s+night)\b|(?<!\w)(?:امس|امبارح|البارح|مبارح)(?!\w)",
    re.IGNORECASE,
)
_FOOD_LOG_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FOOD_LOG_TODAY = re.compile(
    r"\b(?:today|tonight)\b|(?<!\w)(?:النهارده|النهاردة|اليوم)(?!\w)", re.IGNORECASE,
)
_FOOD_LOG_THIS_WEEK = re.compile(
    r"\bthis\s+week\b|(?<!\w)(?:الاسبوع\s+(?:ده|هذا|الحالي)|هذا\s+الاسبوع)(?!\w)",
    re.IGNORECASE,
)
_FOOD_LOG_LAST_N_DAYS = re.compile(
    r"\b(?:last|past)\s+(?P<en_days>\d+)\s+days?\b|"
    r"(?<!\w)(?:اخر|خلال\s+اخر|علي\s+مدار\s+اخر)\s+(?P<ar_days>\d+)\s+(?:ايام|يوما?)(?!\w)",
    re.IGNORECASE,
)
_PERSONAL_LOG_ROUTING_TABLE = {
    "intake_recall": {"day": "get_player_food_log", "range": "get_player_nutrition_trend"},
    "target_achievement": {"day": "get_player_food_log", "range": "get_player_nutrition_trend"},
    "targets_only": {"day": "get_player_nutrition", "range": "get_player_nutrition"},
    "nutrition_trend": {"day": "get_player_nutrition_trend", "range": "get_player_nutrition_trend"},
    "cardio_performed": {"day": "get_player_cardio", "range": "get_player_cardio"},
    "cardio_prescribed": {"day": "get_active_program", "range": "get_active_program"},
}
_RANGE_PERIODS = {"this_week", "last_n_days"}
_EXTRA_MUSCLES = {
    "biceps": ("bi", "باي", "الباي"),
    "triceps": ("tri", "تراي", "التراي"),
    "quads": ("كواد", "كوادز", "رجل امامي", "الرجل الامامي"),
    "hamstrings": ("هامسترنج", "رجل خلفي", "الرجل الخلفي"),
}
_REGIONS = {
    "lower": ("leg day", "leg days", "lower day", "lower days", "lower body",
              "يوم الرجل", "ايام الرجل", "يوم الارجل", "الجزء السفلي"),
    "upper": ("upper day", "upper days", "upper body", "يوم الجزء العلوي", "الجزء العلوي"),
}
_DAY_REGIONS = {
    "lower": ("leg", "legs", "lower", "رجل", "الرجل", "ارجل", "الارجل", "سفلي"),
    "upper": ("upper", "push", "pull", "chest", "back", "arms", "علوي", "صدر", "ظهر"),
}
_WEEKDAYS = (
    ("monday", "mon", "الاثنين", "اثنين", "الاتنين", "اتنين"),
    ("tuesday", "tue", "الثلاثاء", "ثلاثاء", "التلات", "تلات"),
    ("wednesday", "wed", "الاربعاء", "اربعاء", "الاربع", "اربع"),
    ("thursday", "thu", "الخميس", "خميس"),
    ("friday", "fri", "الجمعة", "جمعة"),
    ("saturday", "sat", "السبت", "سبت"),
    ("sunday", "sun", "الاحد", "احد", "الحد", "حد"),
)
_EXERCISE_SHORT_NAMES = {
    "bench": ("bench", "بنش", "البنش"),
    "squat": ("squat", "squats", "سكوات", "السكوات"),
    "deadlift": ("deadlift", "ديدليفت"),
    "pulldown": ("pulldown", "lat pulldown"),
    "row": ("row", "rows"),
    "leg curl": ("leg curl", "leg curls"),
}


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    key: str


@dataclass(frozen=True)
class RoutedContext:
    messages: list[BaseMessage]
    topics: tuple[str, ...] = ()
    pieces: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PersonalLogDecision:
    intent: str
    period: str
    reader: str
    args: dict[str, Any]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.translate(str.maketrans("أإآى", "اااي"))
    return re.sub(r"[^\w]+", " ", normalized).strip()


def _mentions(text: str, vocabulary: Sequence[tuple[str, str]]) -> list[_Mention]:
    text = _normalize_exercise_name(text)
    matches = []
    for key, phrase in vocabulary:
        phrase = _normalize_exercise_name(phrase)
        if not phrase:
            continue
        # Arabic articles/conjunctions can attach to gym nicknames.
        prefix = r"(?:و|ف)?(?:لل|[بلك]?ال|[بلك])?" if re.search(r"[\u0600-\u06ff]", phrase) else ""
        for match in re.finditer(rf"(?<!\w){prefix}{re.escape(phrase)}(?!\w)", text):
            matches.append(_Mention(match.start(), match.end(), key))
    return matches


def _overlaps(left: _Mention, right: _Mention) -> bool:
    return left.start < right.end and right.start < left.end


def _longest_mentions(matches: Sequence[_Mention]) -> list[_Mention]:
    selected: list[_Mention] = []
    for match in sorted(matches, key=lambda mention: (-(mention.end - mention.start), mention.start)):
        # Identical spans may name both arm muscles; retain both.
        if not any(_overlaps(match, prior) and (match.start, match.end) != (prior.start, prior.end)
                   for prior in selected):
            selected.append(match)
    return sorted(selected, key=lambda mention: mention.start)


def _muscle_mentions(text: str) -> list[_Mention]:
    vocabulary = [
        (muscle, alias) for muscle, aliases in WEAK_POINT_ALIASES
        for alias in (muscle, muscle.replace("_", " "), *aliases, *_EXTRA_MUSCLES.get(muscle, ()))
    ]
    return _longest_mentions(_mentions(text, vocabulary))


def _active_exercise_short_names(active_names: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(exercise_id, alias) for exercise_id, name in active_names
            for stem, aliases in _EXERCISE_SHORT_NAMES.items()
            if _mentions(_normalize(name), [(stem, stem)]) for alias in aliases]


def _exercise_mentions(text: str, days: Sequence[Any], store: Any) -> list[_Mention]:
    active_names = list(dict.fromkeys(
        (str(exercise.exercise_id), exercise.exercise_name)
        for day in days for exercise in day.exercises
    ))
    vocabulary = store.get_exercise_name_vocabulary() if store is not None else []
    active_ids = {exercise_id for exercise_id, _name in active_names}
    active = _longest_mentions(_mentions(text, active_names + [
        (exercise_id, alias) for exercise_id, alias in vocabulary if exercise_id in active_ids
    ]))
    short_names = _longest_mentions(_mentions(text, _active_exercise_short_names(active_names)))
    catalog = _catalog_exercise_mentions(text, vocabulary, active, short_names)
    selected = active + catalog
    return selected + [match for match in short_names
                       if not any(_overlaps(match, prior) for prior in selected)]


def _catalog_exercise_mentions(text, vocabulary, active, short_names) -> list[_Mention]:
    # Bare library aliases like "bench" must not override the Player's own variant.
    return [match for match in _longest_mentions(_mentions(text, vocabulary))
            if not any(_overlaps(match, prior) for prior in active)
            and not any(_overlaps(match, short) and match.end - match.start <= short.end - short.start
                        for short in short_names)]


_MAIN_GROUP_REGION = {
    "chest": "upper", "lats": "upper", "traps": "upper", "shoulders": "upper",
    "rear delts": "upper", "biceps": "upper",
    "triceps": "upper", "quads": "lower", "hamstrings": "lower",
    "glutes": "lower", "calves": "lower", "core": "neutral",
}


def _day_has_region(day: Any, region: str, credits: dict[str, dict[str, dict[str, Any]]]) -> bool:
    name = _normalize(day.day_name)
    named_regions = {match.key for match in _mentions(name, [
        (key, word) for key, words in _DAY_REGIONS.items() for word in words
    ])}
    if named_regions:
        return region in named_regions
    # Full-body days load both regions; a lower day may also have arm isolations.
    muscles = {
        group
        for exercise in day.exercises
        for group, attribution in credits.get(str(exercise.exercise_id), {}).items()
        if float(attribution["credit"]) > 0
    }
    regions = {_MAIN_GROUP_REGION[muscle] for muscle in muscles if muscle in _MAIN_GROUP_REGION}
    return region in regions


def _weekday_day_names(text: str, days: Sequence[Any]) -> set[str]:
    selected: set[str] = set()
    for aliases in _WEEKDAYS:
        if _mentions(text, [(aliases[0], alias) for alias in aliases]):
            matching_days = [day.day_name for day in days if _mentions(
                _normalize(day.day_name), [(aliases[0], alias) for alias in aliases]
            )]
            selected.update(matching_days or [aliases[0]])
    return selected


def _region_day_names(text: str, days: Sequence[Any], ledger: Any) -> set[str]:
    selected: set[str] = set()
    regions = {match.key for match in _mentions(
        text, [(region, alias) for region, aliases in _REGIONS.items() for alias in aliases]
    )}
    if regions:
        exercise_ids = list(dict.fromkeys(
            str(exercise.exercise_id) for day in days for exercise in day.exercises
        ))
        credit_reader = getattr(ledger, "volume_review_exercise_credits", None)
        if callable(credit_reader):
            credits = credit_reader(exercise_ids)
        else:
            targets = ledger.volume_review_exercise_targets(exercise_ids)
            exercise_names = {
                str(exercise.exercise_id): str(exercise.exercise_name)
                for day in days for exercise in day.exercises
            }
            credits = {
                exercise_id: {
                    group: {"credit": credit}
                    for group, credit in default_muscle_credits(
                        targets.get(exercise_id),
                        exercise_name=exercise_names.get(exercise_id),
                    ).items()
                }
                for exercise_id in exercise_ids
            }
        for region in regions:
            matching_days = [day.day_name for day in days if _day_has_region(day, region, credits)]
            selected.update(matching_days or [_REGIONS[region][0]])
    return selected


def _day_mentions(text: str, days: Sequence[Any], ledger: Any) -> list[str]:
    selected = {match.key for match in _longest_mentions(_mentions(
        text, [(day.day_name, day.day_name) for day in days]
    ))}
    selected.update(_weekday_day_names(text, days))
    selected.update(_region_day_names(text, days, ledger))
    order = {day.day_name: index for index, day in enumerate(days)}
    return sorted(selected, key=lambda name: (order.get(name, len(days)), name))


def _program_days(ledger: Any) -> list[Any]:
    program = ledger.get_active_program()
    if program is None:
        return []
    week = ledger.get_program_position(program).current_week
    return sorted([day for day in program.days if day.week_order == week], key=lambda day: day.day_order)


def _day_words(days: Sequence[Any]) -> list[tuple[str, str]]:
    return ([(day.day_name, day.day_name) for day in days]
            + [(region, alias) for region, aliases in _REGIONS.items() for alias in aliases]
            + [(aliases[0], alias) for aliases in _WEEKDAYS for alias in aliases])


def _without_day_names(text: str, days: Sequence[Any]) -> str:
    # Named muscle days scope the whole day, not only matching exercises.
    text = _normalize_exercise_name(text)
    characters = list(text)
    for match in _mentions(text, _day_words(days)):
        characters[match.start:match.end] = " " * (match.end - match.start)
    return "".join(characters)


def _program_scopes(text: str, ledger: Any, store: Any) -> list[dict[str, str]]:
    days = _program_days(ledger)
    day_names = _day_mentions(text, days, ledger)
    scope_text = _without_day_names(text, days)
    exercises = _exercise_mentions(scope_text, days, store)
    muscles = [match.key for match in _muscle_mentions(scope_text)
               if not any(_overlaps(match, exercise) for exercise in exercises)]
    named_scopes = ([{"exercise_id": key} for key in dict.fromkeys(match.key for match in exercises)]
                    + [{"muscle": muscle} for muscle in dict.fromkeys(muscles)])
    if day_names:
        return [{"day_name": day, **scope} for day in day_names for scope in (named_scopes or [{}])]
    return named_scopes or [{}]


def _program_question(text: str, ledger: Any, store: Any) -> bool:
    if not _QUESTION.search(text) or _OTHER_TOPIC.search(text):
        return False
    if _PROGRAM.search(text) or _muscle_mentions(text):
        return True
    if _PROGRAM_MEASURE.search(text):
        return True
    days = _program_days(ledger)
    return bool(_mentions(text, _day_words(days)) or _exercise_mentions(text, days, store))


def _context_calls(scopes: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"name": "get_active_program", "args": scope,
             "id": f"context-program-{index + 1}", "type": "tool_call"}
            for index, scope in enumerate(scopes)]


def _is_question(text: str, original_text: str) -> bool:
    return bool(
        _QUESTION.search(text) or _PERSONAL_QUESTION.search(text)
        or re.search(r"[?؟]", original_text)
    )


def _resolve_personal_log_period(text: str, original_text: str) -> str:
    # A range may name today, yesterday or a date as its endpoint.
    if _FOOD_LOG_THIS_WEEK.search(text):
        return "this_week"
    if _FOOD_LOG_LAST_N_DAYS.search(text):
        return "last_n_days"
    if _FOOD_LOG_DATE.search(original_text):
        return "explicit_date"
    if _FOOD_LOG_YESTERDAY.search(text):
        return "yesterday"
    if _FOOD_LOG_TODAY.search(text):
        return "today"
    return "today"


def _is_personal_nutrition_query(text: str, original_text: str) -> bool:
    has_nutrition = bool(_NUTRITION_TERMS.search(text))
    has_food = bool(_FOOD_LOG_QUESTION.search(text))
    personal_question = bool(
        _PERSONAL_NUTRITION_REFERENCE.search(text)
        or _PERSONAL_INTAKE.search(text)
        or _PERSONAL_NUTRITION_LOG.search(text)
        or _PERSONAL_TARGET_POSSESSION.search(text)
    )
    first_person_target = bool(_FIRST_PERSON_TARGET_QUESTION.search(text))
    return _is_question(text, original_text) and (has_nutrition or has_food) and (
        personal_question or first_person_target
    )


def _nutrition_history_intent(text: str) -> str | None:
    personal_intake = bool(_PERSONAL_INTAKE.search(text))
    personal_reference = bool(_PERSONAL_NUTRITION_REFERENCE.search(text))
    personal_log = bool(_PERSONAL_NUTRITION_LOG.search(text))
    owned_value = bool(_OWNED_INTAKE_VALUE.search(text))
    if _NUTRITION_TREND.search(text) and (personal_intake or personal_log or owned_value):
        return "nutrition_trend"
    if personal_intake or personal_log:
        return "intake_recall"
    if personal_reference and _FOOD_RECORD.search(text) and _SAVED_RECORD_REQUEST.search(text):
        return "intake_recall"
    if owned_value and (_INTAKE_QUANTITY.search(text) or _SAVED_RECORD_REQUEST.search(text)):
        return "intake_recall"
    if personal_reference and _NUTRITION_VALUE.search(text):
        return "intake_recall"
    return None


def _nutrition_intent(text: str, original_text: str) -> str | None:
    if not _is_personal_nutrition_query(text, original_text):
        return None
    target = bool(_NUTRITION_TARGET.search(text))
    if _TARGET_ACHIEVEMENT.search(text) and (
            target or _NUTRITION_REMAINING.search(text)
            or (_OWNED_INTAKE_VALUE.search(text) and _FIRST_PERSON_TARGET_QUESTION.search(text))):
        return "target_achievement"
    if target and (_PERSONAL_NUTRITION_REFERENCE.search(text) or _PERSONAL_TARGET_POSSESSION.search(text)):
        # Having a target in the past is distinct from having eaten food.
        if not _PERSONAL_INTAKE.search(text) or _PERSONAL_TARGET_POSSESSION.search(text):
            return "targets_only"
    return _nutrition_history_intent(text)


def _personal_log_excluded(text: str) -> bool:
    # "Check if I ate" asks about facts; "if I ate" imagines a calculation.
    hypothetical_intake = _HYPOTHETICAL_CONTEXT.search(_FACT_CHECK_IF.sub("", text)) and (
        _PERSONAL_INTAKE.search(text) or _FOOD_LOG_QUESTION.search(text) or _NUTRITION_TERMS.search(text)
    )
    if hypothetical_intake or _LOG_READ_DECLINED.search(text):
        return True
    prescribed_cardio = (_PERSONAL_PROGRAM.search(text)
                        and re.search(r"\bcardio\s+should\s+i\s+(?:do|perform)\b", text)
                        and not _FOOD_LOG_QUESTION.search(text))
    return bool(_LOG_GUIDANCE.search(text) and not prescribed_cardio)


def _personal_log_intent(text: str, original_text: str) -> str | None:
    if _personal_log_excluded(text):
        return None
    if (_CARDIO_WORD.search(text) and _CARDIO_PERFORMED.search(text)
            and _is_question(text, original_text)):
        return "cardio_performed"
    if (_CARDIO_WORD.search(text) and _CARDIO_HISTORY.search(text)
            and _PERSONAL_CARDIO.search(text) and _SAVED_RECORD_REQUEST.search(text)):
        return "cardio_performed"
    if (_CARDIO_WORD.search(text) and _PERSONAL_PROGRAM.search(text)
            and _is_question(text, original_text)):
        return "cardio_prescribed"
    return _nutrition_intent(text, original_text)


def _personal_log_args(reader: str, period: str, original_text: str, ledger: Any) -> dict[str, Any]:
    text = _normalize(original_text)
    scoped_day = period in {"yesterday", "explicit_date"} or _FOOD_LOG_TODAY.search(text)
    if reader == "get_player_food_log" or (
            reader in {"get_player_cardio", "get_player_nutrition"}
            and period not in _RANGE_PERIODS and scoped_day):
        day = _FOOD_LOG_DATE.search(original_text).group() if period == "explicit_date" else period
        return {"day": day}
    if reader not in {"get_player_nutrition_trend", "get_player_cardio", "get_player_nutrition"}:
        return {}
    # Inclusive windows: one day, a partial Saturday week, or an explicit rolling range.
    if period == "this_week":
        today = player_tools.player_local_date(ledger, ledger.ledger_id)
        return {"days": (today - saturday_week_start(today)).days + 1}
    if period == "last_n_days":
        match = _FOOD_LOG_LAST_N_DAYS.search(_normalize(original_text))
        return {"days": int(match.group("en_days") or match.group("ar_days"))}
    return {"days": 14} if reader == "get_player_nutrition_trend" else {}


def _personal_log_decision(text: str, original_text: str, ledger: Any) -> _PersonalLogDecision | None:
    period = _resolve_personal_log_period(text, original_text)
    intent = _personal_log_intent(text, original_text)
    if intent is None:
        return None
    period_group = "range" if period in _RANGE_PERIODS else "day"
    reader = _PERSONAL_LOG_ROUTING_TABLE[intent][period_group]
    args = _personal_log_args(reader, period, original_text, ledger)
    return _PersonalLogDecision(intent, period, reader, args)


def _route_tool_context(
    messages: Sequence[BaseMessage], calls: Sequence[dict[str, Any]], topic: str,
    tool_context: dict[str, Any],
) -> RoutedContext:
    results, _metrics = run_player_tool_calls(calls, **tool_context)
    return _bounded_context(messages, calls, results, topic=topic)


def _piece_name(call: dict[str, Any]) -> str:
    name = call["name"]
    if name == "get_active_program":
        scope = call["args"]
        fields = [field for field in ("day_name", "exercise_id", "muscle") if field in scope]
        return "program." + ("+".join(fields) if fields else "overview")
    return {
        "get_player_nutrition": "nutrition.targets",
        "get_player_food_log": "nutrition.food_log",
        "get_player_nutrition_trend": "nutrition.trend",
        "get_player_cardio": "cardio.recent",
    }.get(name, "player.read")


def route_player_context(
    messages: Sequence[BaseMessage], ledger: Any, store: Any, tool_context: dict[str, Any],
) -> RoutedContext:
    """Add bounded simulated reads only at hosted-model entry, after deterministic gates."""
    latest = next((get_message_text(message) for message in reversed(messages)
                   if message_role(message) == "user"), "")
    text = _normalize(latest)
    if ledger is None:
        return RoutedContext(list(messages))
    if ((_NUTRITION_TERMS.search(text) or _FOOD_LOG_QUESTION.search(text) or _CARDIO_WORD.search(text))
            and _personal_log_excluded(text)):
        return RoutedContext(list(messages))
    personal_route = _personal_log_decision(text, latest, ledger)
    if personal_route is not None:
        if personal_route.reader == "get_active_program":
            calls = _context_calls(_program_scopes(text, ledger, store))
            return _route_tool_context(messages, calls, PROGRAM_TOPIC, tool_context)
        calls = [{"name": personal_route.reader, "args": personal_route.args,
                  "id": "context-1", "type": "tool_call"}]
        topic = CARDIO_TOPIC if personal_route.reader == "get_player_cardio" else NUTRITION_TOPIC
        return _route_tool_context(messages, calls, topic, tool_context)
    if not _program_question(text, ledger, store):
        return RoutedContext(list(messages))
    scopes = _program_scopes(text, ledger, store)
    calls = _context_calls(scopes)
    results, _metrics = run_player_tool_calls(calls, **tool_context)
    return _bounded_context(messages, calls, results)


def _bounded_context(
    messages: Sequence[BaseMessage], calls: Sequence[dict[str, Any]], results: Sequence[ToolMessage],
    *, topic: str = PROGRAM_TOPIC,
) -> RoutedContext:
    available = _available_context_bytes(messages)
    included = _fit_context_pieces(calls, results, available)
    if not included:
        return RoutedContext(list(messages), (topic,))
    included_calls = [call for call, _result in included]
    included_results = [result for _call, result in included]
    pieces = [_piece_name(call) for call in included_calls]
    simulated = AIMessage(content="", tool_calls=included_calls)
    return RoutedContext([*messages, simulated, *included_results], (topic,), tuple(pieces))


def _fit_context_pieces(
    calls: Sequence[dict[str, Any]], results: Sequence[ToolMessage], available: int,
) -> list[tuple[dict[str, Any], ToolMessage]]:
    # Prescription-bearing results are larger than empty scopes and should get space first.
    prioritized = sorted(
        (
            (index, call, result, _context_piece_bytes(call, result))
            for index, (call, result) in enumerate(zip(calls, results))
        ),
        key=lambda piece: (-piece[3], piece[0]),
    )
    included = []
    for index, call, result, size in prioritized:
        if size <= available:
            included.append((index, call, result))
            available -= size
    included.sort(key=lambda piece: piece[0])
    return [(call, result) for _index, call, result in included]


def _context_piece_bytes(call: dict[str, Any], result: ToolMessage) -> int:
    result_bytes = len(str(result.content).encode("utf-8"))
    call_bytes = len(json.dumps(call, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return result_bytes + call_bytes


def _available_context_bytes(messages: Sequence[BaseMessage]) -> int:
    # Empty/one/many and Unicode results share the content-byte ceiling used by the tool loop.
    return min(
        MAX_ROUTED_CONTEXT_BYTES,
        HOSTED_PROMPT_MAX_BYTES - HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES
        - ROUTED_CONTEXT_FALLBACK_RESERVE_BYTES
        - sum(len(str(message.content).encode("utf-8")) for message in messages),
    )
