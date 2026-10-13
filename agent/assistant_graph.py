# agent/assistant_graph.py
import logging
import math
import re
import sqlite3
import sys
import time
import unicodedata
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any, Dict, Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.effort import rir_label
from core.deload_choices import DELOAD_CHOICE_APPLY, DELOAD_CHOICE_UNDO, DELOAD_CHOICES
from core.display_language import DisplayLanguage
from core.reply_language import normalize_display_language, resolve_reply_language
from agent.clinical_guard import (
    ARABIC_SCRIPT_RE,
    EMBED_MODEL,
    evaluate_clinical_semantic_guard,
)
from agent.fitness_abbreviations import (
    expand_fitness_abbreviations,
    resolve_unknown_abbreviation_with_llm,
)
from agent.program_generator import (
    extract_frequency_from_text,
    generate_program_pipeline,
    get_biomechanical_cue,
)
from agent.program_blueprints import (
    DEFAULT_SPLIT_BY_FREQUENCY,
    SPLIT_DISPLAY_NAMES,
    experience_level_for_training_age,
)
from agent.program_rules import SPLIT_FREQUENCY_NAMES, get_split_plan, match_split_keyword
from agent.prompts import (
    ARABIC_CLINICAL_SAFEGUARD_RESPONSE,
    ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE,
    CLINICAL_SAFEGUARD_RESPONSE,
    DEFAULT_ASSISTANT_STYLE,
    DIAGNOSIS_SAFEGUARD_RESPONSE,
    FRANCO_ARABIC_INPUT_RESPONSE,
)
from agent.player_prompt import (
    PromptBudgetError,
    HOSTED_PROMPT_TOKEN_BUDGET as HOSTED_PROMPT_TOKEN_BUDGET,
    STATIC_SYSTEM_CORE as STATIC_SYSTEM_CORE,
    TAIL_WINDOW_SIZE,
    build_player_chat_prompt,
    get_message_text as _get_message_text,
    message_role as _message_role,
    prompt_budget as _prompt_budget,
    prompt_token_count as _prompt_token_count,
    valid_preferred_name as _valid_preferred_name,
)
from agent.telemetry_reconciler import (
    clean_movement_stem,
    reconcile_telemetry_query,
)
from database.exercise_library.schema import exercise_library_visible_sql
from service.exercise_context import describe_exercise, describe_exercises
from service.player_weight_context import (
    is_weight_context_relevant,
    render_player_weight_context,
)
from service.weight_history import (
    WeightTrend,
    WeightTrendQuery,
    get_weight_trend,
    player_local_date,
)
from database.exercise_library.names import near_miss_exercise_ids
from service import programs as programs_service
from service.program_requests import MAX_REASON_CHARS
from service.program_substitution import ProgramSubstitution, substitute_program_exercise
from utils.logger import MyosLogger
from utils.equipment_access import COMMERCIAL_GYM, equipment_access_allows, map_equipment_access
from utils.model_downloader import llm
from utils import player_output_budgets
from utils.text_scrubber import CoachOutputScrubber, EMPTY_RESPONSE_FALLBACK, PIPELINE_ERROR_RESPONSE, finalize_coach_output

load_dotenv()
logger = MyosLogger().get_logger(__name__)

OUTPUT_LIMIT_RESPONSE = "I reached the response limit. Ask me to continue if you'd like more."
ARABIC_SWAP_CLARIFICATION_RESPONSE = "أنهي تمرين عايز تغيّره؟"
ARABIC_ACTION_CLARIFICATION_RESPONSE = (
    "مش لاقي اليوم أو التمرين ده في برنامجك. ممكن تحدد يوم أو تمرين موجود؟"
)
ARABIC_PROGRAM_CHANGE_CLARIFICATION_RESPONSE = (
    "مش قادر أحدد تقسيمة البرنامج أو عدد أيامه. تحب البرنامج يبقى كام يوم وبأي تقسيمة؟"
)
ARABIC_HISTORY_CLARIFICATION_RESPONSE = (
    "مش لاقي التمرين ده في برنامجك أو مكتبة التمارين. تقصد أنهي تمرين؟"
)
ARABIC_ONE_AT_A_TIME_NOTE = "هبدّل التمرين ده الأول، وبعدها قولي تحب أساعدك في إيه كمان؟"
ARABIC_PREFERRED_NAME_TRIGGERS = ("اسمي", "ناديني", "قولي يا", "قوللي يا")
_MAX_PREFERRED_NAME_WORDS = 4
_PREFERRED_NAME_CLAUSE_BREAK_RE = re.compile(r"[,،.!?؟…;؛\r\n]")
_PREFERRED_NAME_ARABIC_WAW_RE = re.compile(r"\s+و(?=\s*\w)")
_PREFERRED_NAME_LEADING_PUNCTUATION = "'\"“”‘’([{«"
_PREFERRED_NAME_TRAILING_PUNCTUATION = "'\"“”‘’)]}»"
_NON_NAME_PREFERRED_NAME_PREFIX_RE = re.compile(
    r"^(?:not\b|no\b|never\b|isn't\b|aren't\b|don't\b|doesn't\b|"
    r"do\s+not\b|cannot\b|can't\b|back\b|later\b|tomorrow\b|today\b|"
    r"when\b|whenever\b|if\b|by\b|مش\b|ما\b|لا\b|لم\b|لن\b|ليس\b|مو\b|بكرة\b|"
    r"غدا\b|لاحق\w*\b|بعدين\b|لما\b|لو\b)",
    re.IGNORECASE,
)

CLINICAL_SAFEGUARD_RESPONSES = {
    ("en", "clinical"): CLINICAL_SAFEGUARD_RESPONSE,
    ("en", "diagnosis"): DIAGNOSIS_SAFEGUARD_RESPONSE,
    ("ar", "clinical"): ARABIC_CLINICAL_SAFEGUARD_RESPONSE,
    ("ar", "diagnosis"): ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE,
    ("franco", "input"): FRANCO_ARABIC_INPUT_RESPONSE,
}

IntentType = Literal[
    "clinical_intercept",
    "banned_movement",
    "telemetry_intercept",
    "exercise_history",
    "exercise_history_fallback",
    "exercise_substitution",
    "arabic_swap_clarification",
    "program_mutation",
    "deload_choice",
    "catalog_search",
    "coaching_qa",
    "composite_intent",
]

# Tier-0a: unconditional acute-trauma signals (fail-closed; no fatigue bypass).
RE_ACUTE_INJURY = re.compile(
    r"\b(sharp\s+(?:pain|pop|pull|twinge|pinch)|shooting\s+pain|radiat(?:ing|es|ed)?(?:\s+pain)?|"
    r"numb(?:ness)?|tingling|pinched(?:\s+nerve)?|hernia|dislocat(?:ed|ion)|"
    r"can['']t\s+move\s+my|joint\s+clicking\s+with\s+pain)\b",
    re.IGNORECASE,
)

FRANCO_ARABIC_RE = re.compile(
    r"(?<![A-Za-z0-9])(?!(?:b2b)(?![A-Za-z0-9]))"
    r"(?:[A-Za-z]+[2356789][A-Za-z]+|"
    r"[2356789](?!(?:kgs?|lbs?|km|mi|mins?|secs?|hrs?|am|pm|x|rm|reps?|sets?|days?|wks?|"
    r"st|nd|rd|th|rpe|rir|k|m|s|h|d)\b)"
    r"[A-Za-z]+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
FRANCO_COMMON_WORDS = frozenset(
    {
        "ana", "enta", "enty", "3ayez", "keda", "delwa2ty",
        "ezay", "leh", "awy", "wa3", "waga3ny", "alam",
    }
)


def is_franco_arabic(text: str) -> bool:
    if len(FRANCO_ARABIC_RE.findall(text)) >= 2:
        return True
    words = text.lower().replace("-", " ").split()
    return any(word.strip(".,!?;:()[]{}\"'") in FRANCO_COMMON_WORDS for word in words)

#: Joints and tear-prone structures. Deliberately excludes the big DOMS muscle
#: groups (quads, glutes, hamstrings, chest, lats...) whose slang
#: ("torn up from leg day") must reach the Tier-1 semantic guard instead.
_TRAUMA_STRUCTURES = (
    r"(?:knees?|shoulders?|elbows?|wrists?|ankles?|hips?|backs?|necks?|joints?|tendons?|"
    r"ligaments?|pec(?:toral)?s?|biceps?|rotator(?:\s+cuff)?|meniscus|labrum|acl|groin)"
)

# Tier-0c: directly intensified joint pain during an explicit movement.
_PAIN_WORDS = r"(?:pain(?:ful)?|hurt(?:s|ing)?|ache(?:s|ing)?)"
_PREPAIN_INTENSITY = r"(?:strong|bad|sharp|severe|intense|awful|terrible|excruciating|really\s+bad|a\s+lot(?:\s+of)?)"
_POSTPAIN_INTENSITY = r"(?:really\s+bad|bad|strong|sharp|severe|intense|awful|terrible|excruciating|a\s+lot)"
RE_INTENSIFIED_JOINT_PAIN = re.compile(
    rf"""
    \b{_PREPAIN_INTENSITY}\s+(?:(?:my|the)\s+)?{_TRAUMA_STRUCTURES}\s+{_PAIN_WORDS}\b
    |
    \b{_PREPAIN_INTENSITY}\s+{_PAIN_WORDS}\s+(?:in|around|over)\s+(?:(?:my|the)\s+)?{_TRAUMA_STRUCTURES}\b
    |
    \b{_TRAUMA_STRUCTURES}\s+{_PAIN_WORDS}\s+(?:(?:is|feels|gets|was)\s+)?{_POSTPAIN_INTENSITY}\b
    |
    \b{_TRAUMA_STRUCTURES}\s+(?:is|feels|gets)\s+(?:really|very|so|super)\s+(?:painful|sore)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
RE_MOVEMENT_CONTEXT = re.compile(
    r"""
    \b(?:when|while|every\s+time|during|if)\b\s+
    (?:i\s+)?(?:am\s+)?(?:(?:a|the|my)\s+)?
    (?:raise|lift|press|squat|bend|reach|twist|rotate|push|pull|carry|deadlift|row|bench|dip|curl|lunge)\w*\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Negation counts only when it sits right before the pain or its intensifier, so
# "not sure why, my knee hurts a lot when I squat" still intercepts.
RE_NON_ACUTE_PAIN_CONTEXT = re.compile(
    rf"""
    \b(?:used\s+to|better|helps?|helping|gone|anymore)\b
    |
    \b(?:doesn['’]t|don['’]t|isn['’]t|wasn['’]t|no|not|never|without)\s+(?:\w+\s+){{0,2}}?
    (?:{_PAIN_WORDS}|{_POSTPAIN_INTENSITY})\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
RE_TIER0_CLAUSE_SPLIT = re.compile(
    r"[.!?;\n]+|\b(?:but|although|however|though|yet)\b",
    re.IGNORECASE,
)
RE_JOINT_PAIN_AT_CLAUSE_END = re.compile(
    rf"\b{_TRAUMA_STRUCTURES}\b[^.!?]{{0,16}}\b{_PAIN_WORDS}\b\s*$",
    re.IGNORECASE,
)
RE_REALLY_BAD_FRAGMENT = re.compile(r"^\s*really\s+bad\b", re.IGNORECASE)

# Tier-0b: DOMS-ambiguous tokens (swelling/tear/tore/torn/pop/tweaked) intercept
# only with an explicit injury context; otherwise they fall through to Tier-1.
RE_AMBIGUOUS_TRAUMA = re.compile(
    r"\b("
    r"(?:felt|heard|there\s+was|something)\s+(?:a\s+|something\s+)?(?:pop(?:ped)?|tear(?:ing)?|rip(?:ping)?)"
    r"|(?:tear|tore|torn|pop(?:ped)?|swelling|swollen)\s+(?:in|inside)\s+(?:my\s+)?\w+"
    r"|(?:tore|torn|tear(?:ing)?|tweak(?:ed)?|pop(?:ped)?)(?!\s+up)\s+(?:my\s+|the\s+|a\s+)?"
    + _TRAUMA_STRUCTURES
    + r"|"
    + _TRAUMA_STRUCTURES
    + r"\b[^.!?]{0,30}?\b(?:tore(?!\s+up)|torn(?!\s+up)|tear(?:ing)?|swollen|swelling|tweak(?:ed)?|popped|pop(?!\s+when))"
    r"|(?:swollen|swelling)\s+" + _TRAUMA_STRUCTURES + r"\b"
    r")\b",
    re.IGNORECASE,
)


def _acute_injury_hit(text: str) -> bool:
    """Tier-0: unconditional and contextual trauma plus Tier-0c movement pain."""
    if RE_ACUTE_INJURY.search(text) or RE_AMBIGUOUS_TRAUMA.search(text):
        return True
    clauses = RE_TIER0_CLAUSE_SPLIT.split(text)
    for clause in clauses:
        if RE_NON_ACUTE_PAIN_CONTEXT.search(clause):
            continue
        if RE_INTENSIFIED_JOINT_PAIN.search(clause) and RE_MOVEMENT_CONTEXT.search(clause):
            return True

    for previous_clause, fragment in zip(clauses, clauses[1:]):
        if RE_NON_ACUTE_PAIN_CONTEXT.search(previous_clause + " " + fragment):
            continue
        if (
            RE_JOINT_PAIN_AT_CLAUSE_END.search(previous_clause)
            and RE_REALLY_BAD_FRAGMENT.match(fragment)
            and RE_MOVEMENT_CONTEXT.search(fragment)
        ):
            return True
    return False


RE_DIAGNOSIS = re.compile(
    r"\b(diagnos(?:e|is|ing)|what(?:'s|\s+is)\s+wrong\s+with|why\s+does\s+my\s+\w+\s+(?:hurt|ache))\b",
    re.IGNORECASE,
)
RE_ARABIC_DIAGNOSIS = re.compile(
    r"(?:تشخيص|شخّ?ص|ما\s+(?:الذي\s+)?يسبب\s+(?:ألم|وجع|إصابة)|ما\s+سبب\s+(?:ألم|وجع|إصابة))"
)
RE_BANNED_MOVEMENT = re.compile(
    r"\b(behind[\s-]the[\s-]neck|upright[\s-]rows?|(?:burn|activation)[\s-]sets?|(?:light\s+reps|burn\s+and\s+activation))\b",
    re.IGNORECASE,
)
RE_NUTRITION = re.compile(r"\b(calorie|caloric|macro|nutrition|diet|meal|food|protein|carb|fat)\b", re.IGNORECASE)
RE_EXPLICIT_SWAP = re.compile(
    r"\b(?:swap|replace|substitute|switch(?:\s+out)?|change)\b\s+(?P<source>.+?)\s+\b(?:for|with|instead of|to)\b\s+(?P<target>.+)",
    re.IGNORECASE,
)
RE_ARABIC_SWAP_REQUEST = re.compile(
    r"(?:^|[.!?؟;؛]\s*)(?:من فضلك\s+|لو سمحت\s+)?"
    r"(?:(?:عايز|عاوز|عايزة|عاوزة|محتاج|محتاجة)\s+)?"
    r"(?:أ?بدل|أ?غير|استبدل)(?:\s+لي)?(?:\s|$)"
)
# Unicode \w treats Arabic letters as word characters; diacritics are removed first.
RE_ARABIC_PROGRAM_COMMAND = re.compile(
    r"(?:(?<!\w)(?:ظبط|غير|عدل|بدل|خلي|اعمل|زود|قلل)(?:لي)?(?!\w)|"
    r"(?<!\w)(?:ممكن|لو\s+سمحت|يا\s+ريت|من\s+فضلك)\s+"
    r"ت(?:ظبط|غير|عدل|بدل|خلي|عمل|زود|قلل)(?:لي)?(?!\w))"
    r".{0,50}(?<!\w)(?:البرنامج|برنامج|التقسيمة|تقسيمة|الروتين|روتين|program|routine|split)(?!\w)",
    re.IGNORECASE,
)
# Past-tense wishes and hedges («كنت عايز أغير… بس مش متأكد») are not requests.
RE_ARABIC_HEDGED_PROGRAM_CHANGE = re.compile(
    r"(?<!\w)(?:كنت|كان|كنا|يمكن|مش\s+متأكد|مش\s+متأكدة|مش\s+عارف|مش\s+عارفة|متردد|مترددة)(?!\w)"
)
RE_ARABIC_WANTED_PROGRAM_CHANGE = re.compile(
    r"(?<!\w)(?:عايز|عاوز|عايزة|عاوزة|محتاج|محتاجة)\s+"
    r"(?:أ|ا)?(?:ظبط|غير|عدل|بدل|خلي|عمل|زود|قلل)(?:لي)?(?!\w)"
    r".{0,50}(?<!\w)(?:البرنامج|برنامج|التقسيمة|تقسيمة|الروتين|روتين|program|routine|split)(?!\w)",
    re.IGNORECASE,
)
RE_ARABIC_NEGATED_PROGRAM_CHANGE = re.compile(
    r"(?<!\w)(?:مش|ما|لا)\s+(?:عايز|عاوز|عايزة|عاوزة|محتاج|محتاجة)\s+"
    r"(?:أ|ا)?(?:ظبط|غير|عدل|بدل|خلي|عمل|زود|قلل)(?:لي)?(?!\w)",
    re.IGNORECASE,
)
RE_ARABIC_TRAIN_REST_QUESTION = re.compile(
    r"(?<!\w)(?:أتمرن|اتمرن|أتدرب|اتدرب|ألعب|العب|أروح|اروح)"
    r".{0,40}(?<!\w)(?:ولا|أم)\s*"
    r"(?<!\w)(?:أريح|اريح|أرتاح|ارتاح|أستريح|استريح)(?!\w)|"
    r"(?<!\w)(?:أريح|اريح|أرتاح|ارتاح|أستريح|استريح)"
    r".{0,40}(?<!\w)(?:ولا|أم)\s*"
    r"(?<!\w)(?:أتمرن|اتمرن|أتدرب|اتدرب|ألعب|العب|أروح|اروح)(?!\w)",
    re.IGNORECASE,
)
RE_ARABIC_FREQUENCY_MENTION = re.compile(
    r"(?<!\w)(?P<number>[0-9٠-٩]+|واحد|واحدة|اتنين|اثنين|يومين|تلاتة|ثلاثة|"
    r"أربع|اربع|أربعة|اربعة|أربعين|خمسة|خمس|ستة|ست|سبعة|سبع)"
    r"\s*(?:أيام?|ايام?|يومين|يوم|days?|d/wk)(?!\w)",
    re.IGNORECASE,
)
ARABIC_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ARABIC_FREQUENCY_WORDS = {
    "واحد": 1,
    "واحدة": 1,
    "اتنين": 2,
    "اثنين": 2,
    "يومين": 2,
    "تلاتة": 3,
    "ثلاثة": 3,
    "أربع": 4,
    "اربع": 4,
    "أربعة": 4,
    "اربعة": 4,
    "أربعين": 40,
    "خمسة": 5,
    "خمس": 5,
    "ستة": 6,
    "ست": 6,
    "سبعة": 7,
    "سبع": 7,
}
RE_SINGLE_SWAP = re.compile(
    r"(?:(?:i\s+(?:just\s+)?want|show\s+me|give\s+me)\s+)?\b(?:swap|replace|substitute|alternatives?\s+(?:for|to)|switch(?:\s+out)?)\b\s+(?P<source>[a-zA-Z0-9\s\(\)\-\_]+)",
    re.IGNORECASE,
)
RE_PROGRAM_MUTATION = re.compile(
    r"\b(?:(?:rebuild|regenerate)(?:\s+(?:my|the))?(?:\s+(?:split|routine|program))?|new\s+split|(?:change|switch|update)\s+(?:(?:my|the)\s+)?(?:split(?!\s+squat)|routine|program))\b",
    re.IGNORECASE,
)
RE_DELOAD_ENGLISH_CHOICE = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|will you|i want to|i'd like to)\s+)*"
    r"(?P<verb>undo|skip|cancel|remove|reverse|apply|use|enable)\s+(?:my\s+|the\s+)?deload"
    r"(?:(?:\s+(?:for|until|during))?\s+(?:today|(?:this|my|the)\s+workout|(?:my\s+|the\s+)?next\s+workout))?"
    r"(?:\s+please)?\s*[.!?؟]*\s*$",
    re.IGNORECASE,
)
RE_ARABIC_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u0640]")
ARABIC_DELOAD_UNDO_VERBS = (
    "ألغ", "ألغي", "الغ", "الغي", "الغى", "إلغاء", "الغاء", "لغي", "لغى",
    "تراجع عن", "أوقف", "اوقف", "وقف", "شيل", "شيلي",
)
ARABIC_DELOAD_APPLY_VERBS = ("طبق", "فعل", "اعتمد", "استخدم")
ARABIC_DELOAD_VERB_PATTERN = "|".join(
    (*ARABIC_DELOAD_UNDO_VERBS, *ARABIC_DELOAD_APPLY_VERBS)
)
ARABIC_DELOAD_NOUN = r"(?:ال)?(?:ديلود|تخفيف(?:\s+التدريب)?)"
ARABIC_DELOAD_SCOPE = (
    r"(?:اليوم|النهارده|التمرين\s+(?:ده|دا|الحالي|القادم|الجاي)|"
    r"الحصة\s+(?:دي|ده|الحالية|القادمة|الجاية)|"
    r"للتمرين\s+(?:ده|دا|الحالي|القادم|الجاي)|"
    r"للحصة\s+(?:دي|ده|الحالية|القادمة|الجاية)|"
    r"لهذا\s+التمرين|لهذه\s+الحصة|هذا\s+التمرين|هذه\s+الحصة|"
    r"في\s+(?:التمرين|الحصة)\s+(?:ده|دي|الحالي|الحالية|الجاي|الجاية))"
)
RE_DELOAD_ARABIC_CHOICE = re.compile(
    r"^\s*(?:(?:من فضلك|لو سمحت)\s+)?(?:(?:هل يمكنك|ممكن)\s+)?(?:أن\s+)?"
    rf"(?P<verb>{ARABIC_DELOAD_VERB_PATTERN})\s+"
    rf"{ARABIC_DELOAD_NOUN}(?:\s+{ARABIC_DELOAD_SCOPE}(?:\s+بس)?)?"
    r"(?:\s+(?:من فضلك|لو سمحت))?\s*[.!?؟]*\s*$"
)
RE_ARABIC_DELOAD_AVOID = re.compile(
    rf"^\s*(?:(?:من فضلك|لو سمحت)\s+)?بلاش\s+{ARABIC_DELOAD_NOUN}"
    rf"(?:\s+{ARABIC_DELOAD_SCOPE}(?:\s+بس)?)?\s*[.!?؟]*\s*$"
)
RE_ARABIC_NEGATED_DELOAD_CHOICE = re.compile(
    r"^\s*(?:"
    r"(?:مش|ما|لا|لن|ليس)\s+(?:(?:عايز|عاوز|عايزة|عاوزة)\s+)?"
    rf"(?:{ARABIC_DELOAD_VERB_PATTERN})"
    r"|م(?:ا)?ت(?:شيل|لغي|لغ|طبق|فعل)[\u0600-\u06ff]*ش"
    rf")\s+{ARABIC_DELOAD_NOUN}(?:\s+{ARABIC_DELOAD_SCOPE}(?:\s+بس)?)?\s*[.!?؟]*\s*$"
)
RE_ARABIC_NEGATION = re.compile(r"(?:^|\s)(?:لا|لن|ليس|مش|ما)\s")
DELOAD_NO_CHANGE_CHOICE = "no_change"
DELOAD_NO_CHANGE_RESPONSE = "There is nothing to change."
RE_FREQ_DIGIT = re.compile(r"\b([1-5])\s*(?:days?|d/wk|days\s+a\s+week)\b", re.IGNORECASE)
RE_SEARCH_TOKENS = re.compile(r"\b(search|find|lookup|show me|list exercises)\b", re.IGNORECASE)
RE_ACTION_HINT = re.compile(
    r"\b(swap|replace|substitute|change|split|routine|program|days|rebuild|alternatives?|exercises)\b",
    re.IGNORECASE,
)
RE_INQUISITIVE_PREFIX = re.compile(
    r"^(?:should\s+i|can\s+(?:you|i)|could\s+(?:you|i)|would\s+it|what\s+if|why\s+(?:is|does|did)|is\s+it|how\s+(?:does|do|can|should)|explain|thoughts\s+on)\b",
    re.IGNORECASE,
)
RE_CLAUSE_SPLIT = re.compile(
    r"(?:[;\n]+|(?:\.|\?|\!)\s+|\s+(?:and\s+also|and\s+then|also|plus|then)\s+|\s+and\s+(?=(?:swap|replace|substitute|switch|change|how|what|why|is|can|could|should|rebuild|new\s+split|search|find|behind[\s-]the[\s-]neck|upright[\s-]rows?)\b))",
    re.IGNORECASE,
)
RE_EXERCISE_PERFORMANCE_QUERY = re.compile(
    r"\b(?:how\s+did\s+i\s+do\s+(?:in|on|for)|what\s+did\s+i\s+(?:do|hit|lift)\s+(?:in|on|for)|(?:my\s+last|check\s+(?:my\s+)?last)\s+session\s+(?:for|on|in)?)\s+(.+)",
    re.IGNORECASE,
)


class IntentClassification(BaseModel):
    intent: str = Field(
        description="One of: 'exercise_substitution', 'program_mutation', 'catalog_search', 'coaching_qa'"
    )
    source_exercise: str | None = None
    target_exercise: str | None = None
    target_frequency: int | None = None
    search_query: str | None = None


ROUTER_PROMPT = (
    "Classify the trainee query into EXACTLY one category:\n"
    "- exercise_substitution: Swapping/changing a specific movement in the routine.\n"
    "- program_mutation: Rebuilding the split or altering weekly training days.\n"
    "- catalog_search: Finding or listing movements from the database.\n"
    "- coaching_qa: Biomechanics, technique cues, session reviews, fatigue, or general gym questions.\n\n"
    "Extract entities where present."
)


class ArabicIntentClassification(BaseModel):
    intent: Literal[
        "exercise_substitution",
        "composite_intent",
        "program_change",
        "exercise_history",
        "coaching_qa",
        "other",
    ]
    source_exercise: str | None = None
    target_exercise: str | None = None
    target_day: str | None = None
    target_split_type: str | None = None
    target_frequency: int | None = Field(default=None, strict=True)
    history_exercise: str | None = None
    history_whole_session: bool = False
    has_swap: bool = False
    has_additional_request: bool = False


ARABIC_ROUTER_PROMPT = (
    "Classify this Arabic or Arabic-dominant player message as exactly one of: "
    "exercise_substitution, composite_intent, program_change, exercise_history, "
    "coaching_qa, other. Use program_change for a direct request to change the Training "
    "program, including its split family or weekly frequency. Affirmative Egyptian "
    "desire forms such as عايز/عاوز/محتاج أغيّر are program_change requests even "
    "when their target is missing; "
    "questions or negated requests are not. Set target_split_type to "
    "one of the allowed split family keys listed below, or null if no split was named; "
    "set target_frequency to the requested number of days, or null if none was named. "
    "Use exercise_history only to retrieve logged figures or summarize past workouts. "
    "Questions asking what to do, including whether to train or rest because of fatigue, "
    "are coaching_qa even if they mention yesterday's workout. For a question "
    "about one exercise, set history_exercise to its English Exercise library-style name. "
    "For a whole-session summary, set history_whole_session=true. The server validates "
    "these proposals against the player's Training program and Exercise library. Use "
    "exercise_substitution only when the player explicitly asks to replace or swap an "
    "exercise and names the replacement, such as بدّل/غيّر/استبدل X بـ Y or "
    "'swap X for Y'. Asking for a suggestion, an alternative, advice, or what to do "
    "instead (including اقترح, بديل, إيه البديل, 'suggest', 'alternative', and "
    "'what can I do instead') is coaching_qa, even when an exercise feels uncomfortable. "
    "Never invent a replacement the player did not name. Use composite_intent when the "
    "message combines an explicit named swap with another request, and set has_swap=true "
    "only when it contains that explicit swap. For a swap, copy the source exactly from the current program "
    "exercise names below. Return target_exercise as an English Exercise library-style "
    "exercise name, translating Arabic gym terms instead of copying them. Examples: "
    "بنش means Bench Press, دامبل means Dumbbell, بار means Barbell, ضغط مائل means "
    "Incline Bench Press, ليج برس means Leg Press, سكوات means Squat, and رفرفة means "
    "Fly or Raise. When the player names only equipment or a variant for the same "
    "movement, apply it to the source movement: بالدامبل with Bench Press means "
    "Dumbbell Bench Press; بالبار means Barbell; على السميث means Smith Machine. "
    "Keep source_exercise copied exactly from the current program exercise names. If a "
    "day is named for a swap, copy target_day exactly from the current program day names; "
    "otherwise leave it empty. If the message has no swap, leave source_exercise, "
    "target_exercise, and target_day empty. Return at most one swap."
)


class SubstitutionResolution(BaseModel):
    source_exercise: str | None = None
    target_exercise: str | None = None


SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD = 0.70


class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trainee_id: str
    player_account_id: str | None
    coach_tone: str
    custom_instructions: str
    display_language: NotRequired[DisplayLanguage]
    preferred_name: str | None
    telemetry_context: str | None
    weight_context: NotRequired[str | None]
    intent: IntentType | None
    intent_metadata: dict[str, Any]
    active_intents: list[dict[str, Any]] | None
    program_updated: bool
    program_change: str | None
    response_content: str | None
    request_suggestion: dict[str, Any] | None
    pipeline_error: str | None


def _match_substitution_source(days: list[Any], source_name: str) -> tuple[Any, Any, float]:
    matched_ex, target_day, best_similarity = None, None, 0.0
    source_stem = clean_movement_stem(source_name.lower())
    for day in days:
        for exercise in day.exercises:
            similarity = _substitution_source_similarity(source_name, source_stem, exercise)
            if similarity == 1.0:
                return exercise, day, similarity
            if similarity > best_similarity:
                matched_ex, target_day, best_similarity = exercise, day, similarity
    return matched_ex, target_day, best_similarity


def _substitution_source_similarity(source_name: str, source_stem: str, exercise: Any) -> float:
    exercise_name = exercise.exercise_name.lower()
    exercise_stem = clean_movement_stem(exercise_name)
    if source_stem and exercise_stem and (
        source_stem == exercise_stem
        or len(source_stem) >= 4
        and len(exercise_stem) >= 4
        and (
            re.search(r"\b" + re.escape(source_stem) + r"\b", exercise_stem)
            or re.search(r"\b" + re.escape(exercise_stem) + r"\b", source_stem)
        )
    ):
        return 1.0
    return max(
        SequenceMatcher(None, source_name.lower(), exercise_name).ratio(),
        SequenceMatcher(None, source_stem, exercise_stem).ratio(),
    )


def _normalize_preferred_name_match_text(text: str) -> tuple[str, list[int]]:
    normalized_chars: list[str] = []
    source_offsets: list[int] = []
    for source_index, character in enumerate(text):
        for normalized_character in unicodedata.normalize("NFD", character):
            if unicodedata.category(normalized_character).startswith("M"):
                continue
            if normalized_character == "ى":
                normalized_character = "ي"
            normalized_chars.append(normalized_character)
            source_offsets.append(source_index)
    return "".join(normalized_chars), source_offsets


def _arabic_preferred_name_trigger_pattern() -> str:
    triggers = (
        r"\s+".join(re.escape(word) for word in trigger.split())
        for trigger in ARABIC_PREFERRED_NAME_TRIGGERS
    )
    return "(?:" + "|".join(triggers) + ")"


def _preferred_name_capture_match(
    query: str,
) -> tuple[str, list[int], re.Match[str]] | None:
    normalized, source_offsets = _normalize_preferred_name_match_text(query)
    pattern = re.compile(
        rf"\s*(?:(?P<arabic_trigger>{_arabic_preferred_name_trigger_pattern()})|"
        r"(?P<english_trigger>my\s+name\s+is|call\s+me))\s+(?P<name>[\s\S]+)\Z",
        re.IGNORECASE,
    )
    match = pattern.fullmatch(normalized)
    return (normalized, source_offsets, match) if match else None


def _original_preferred_name_slice(
    query: str, source_offsets: list[int], start: int, end: int
) -> str:
    if start >= end:
        return ""
    source_start = source_offsets[start]
    source_end = source_offsets[end - 1] + 1
    while source_end < len(query) and unicodedata.category(query[source_end]).startswith("M"):
        source_end += 1
    return query[source_start:source_end]


def _explicit_preferred_name(query: str) -> str | None:
    capture = _preferred_name_capture_match(query)
    if capture is None:
        return None
    normalized, source_offsets, match = capture

    start, end = match.span("name")
    trigger = match.group("arabic_trigger")
    if trigger == "اسمي":
        huwa = re.match(r"هو\s+", normalized[start:end])
        if huwa:
            start += huwa.end()

    capture_end = _PREFERRED_NAME_CLAUSE_BREAK_RE.search(normalized, start)
    if capture_end:
        end = min(end, capture_end.start())
    waw_clause = _PREFERRED_NAME_ARABIC_WAW_RE.search(normalized, start, end)
    if waw_clause:
        end = waw_clause.start()

    while start < end and (
        normalized[start].isspace()
        or normalized[start] in _PREFERRED_NAME_LEADING_PUNCTUATION
    ):
        start += 1
    while start < end and (
        normalized[end - 1].isspace()
        or normalized[end - 1] in _PREFERRED_NAME_TRAILING_PUNCTUATION
    ):
        end -= 1

    words = list(re.finditer(r"\S+", normalized[start:end]))
    if len(words) > _MAX_PREFERRED_NAME_WORDS:
        end = start + words[_MAX_PREFERRED_NAME_WORDS - 1].end()

    normalized_name = normalized[start:end].strip()
    if not normalized_name or _NON_NAME_PREFERRED_NAME_PREFIX_RE.match(normalized_name):
        return None

    name = _original_preferred_name_slice(query, source_offsets, start, end)
    name = name.strip().strip(_PREFERRED_NAME_LEADING_PUNCTUATION).strip()
    name = name.strip(_PREFERRED_NAME_TRAILING_PUNCTUATION).strip()
    return _valid_preferred_name(name) if name else None


def _graph_context(config: dict[str, Any] | None) -> tuple[Any, Any]:
    """Resolves the explicit ``(ledger, store)`` handles carried on the run config."""
    configurable = (config or {}).get("configurable", {}) or {}
    return configurable.get("ledger"), configurable.get("store")


def hydrate_context_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    profile = ledger.get_player_profile()
    profile = profile if isinstance(profile, dict) else {}
    display_language = normalize_display_language(state.get("display_language"))
    account_id = state.get("player_account_id")
    account_getter = getattr(store, "get_account", None)
    if account_id and callable(account_getter):
        account = account_getter(account_id)
        if isinstance(account, dict):
            display_language = normalize_display_language(
                account.get("display_language", display_language)
            )
    getter = getattr(ledger, "get_assistant_memory", None)
    memory = getter() if callable(getter) else {}
    name = _valid_preferred_name(memory.get("preferred_name")) if isinstance(memory, dict) else None
    telemetry = state.get("telemetry_context") or ledger.get_compact_telemetry()
    recent = " ".join(_get_message_text(m) for m in state.get("messages", [])[-TAIL_WINDOW_SIZE:])
    needs_comparison = state.get("intent") == "exercise_history_fallback" or re.search(
        r"\b(?:session|workout|performance|compare|comparison|progress|sets?|reps?|rpe|load|heavier|improve)\b",
        recent,
        re.IGNORECASE,
    )
    comparison = _session_comparison_context(ledger) if needs_comparison else None
    if comparison is not None:
        comparison_text = _comparison_text(comparison, compact=True, store=store)
        if not str(telemetry or "").startswith(comparison_text):
            telemetry = comparison_text + "\n" + str(telemetry or "")
    messages = state.get("messages", [])
    latest_user = next(
        (message for message in reversed(messages) if isinstance(message, HumanMessage)),
        None,
    )
    recent_user = _get_message_text(latest_user) if latest_user is not None else ""
    weight_context = None
    if is_weight_context_relevant(recent_user):
        try:
            as_of = player_local_date(ledger, str(state.get("trainee_id", "")))
            weight_trend = get_weight_trend(
                store,
                WeightTrendQuery(
                    ledger_id=str(state.get("trainee_id", "")), weeks=8, as_of=as_of
                ),
                ledger,
            )
        except sqlite3.Error:
            logger.exception("Player weight history could not be loaded for assistant context.")
            weight_trend = WeightTrend(points=(), change_kg=None)
            as_of = None
        weight_context = render_player_weight_context(
            weight_trend, profile.get("target_weight_kg"), as_of=as_of
        )
    return {
        "coach_tone": state.get("coach_tone") or profile.get("coach_tone") or DEFAULT_ASSISTANT_STYLE,
        "custom_instructions": state.get("custom_instructions") or profile.get("custom_instructions", ""),
        "telemetry_context": telemetry,
        "weight_context": weight_context,
        "preferred_name": name,
        "display_language": display_language,
    }


def _name_recall_response(
    state: AssistantState, query: str, language: DisplayLanguage
) -> str | None:
    recall_pattern = r"(?:what(?:'s| is) my name|do you (?:remember|know) my name|what do you call me)[?!.]*"
    if not re.fullmatch(recall_pattern, query, re.IGNORECASE):
        return None
    name = _valid_preferred_name(state.get("preferred_name"))
    if language == "ar":
        return (
            f"إنت طلبت مني أناديك {name}."
            if name
            else "ما قلتليش اسمك المفضل لسه. تحب أناديك إيه؟"
        )
    return f"You asked me to call you {name}." if name else "I don't have your preferred name yet. What should I call you?"


def _name_response(state: AssistantState, ledger: Any = None) -> str | None:
    query = _get_message_text(state["messages"][-1]) if state.get("messages") else ""
    language = resolve_reply_language(query, state.get("display_language", "en"))
    name = _explicit_preferred_name(query)
    if not name:
        return _name_recall_response(state, query, language)
    setter = getattr(ledger, "set_assistant_memory", None)
    if callable(setter):
        setter("preferred_name", name)
    state["preferred_name"] = name
    return f"تمام، هناديك {name}." if language == "ar" else f"Nice to meet you, {name}."


RE_HISTORY_INDICATOR = re.compile(
    r"\b(?:how\s+did\s+(?:my|i)|what\s+did\s+i|history|logged|last\s+(?:session|workout)|"
    r"previous\s+(?:session|workout)|compare|comparison|progress\s+on)\b", re.IGNORECASE
)
RE_FOLLOWUP_EXERCISE = re.compile(r"^\s*(?:what\s+(?:about|of)|how\s+about)\s+(.+?)[?!.]*\s*$", re.IGNORECASE)
RE_HISTORY_SCOPE = re.compile(
    r"\b(?:compar\w*|versus|vs|since|between|before|after|over\s+time|trend\w*|progress\w*|"
    r"yesterday|today|(?:last|this|past|previous)\s+(?:week|month|year)|"
    r"(?:last|past|previous)\s+\d+\s+(?:days?|weeks?|months?|sessions?)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"\d{4}-\d{2}-\d{2})\b", re.IGNORECASE
)
AUTHORIZATION_RESPONSE = "Routine changes require an explicit directive, such as 'switch routine to 3 days' or 'swap bench press for incline press'."


def _extract_frequency(text: str) -> int | None:
    freq = extract_frequency_from_text(text)
    if freq is not None:
        return freq
    lowered = text.lower()
    digit = re.search(r"\b(\d+)\s*(?:days?|d/wk|days\s+a\s+week|day)\b", lowered)
    if digit:
        return int(digit.group(1))
    for word, number in {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}.items():
        if re.search(rf"\b{word}\s*(?:days?\b|-day|d/wk|days\s+a\s+week)", lowered):
            return number
    return None


def _mentioned_arabic_frequency(query: str) -> int | None:
    normalized = query.translate(ARABIC_DIGIT_TRANSLATION)
    match = RE_ARABIC_FREQUENCY_MENTION.search(normalized)
    if not match:
        return None
    number = match.group("number")
    return int(number) if number.isdigit() else ARABIC_FREQUENCY_WORDS.get(number)


def _action_command(query: str) -> str:
    command = query.strip().lower()
    if re.search(r"\b(?:if|unless|should|would|hypothetically|maybe|might)\b|\b(?:do not|don't|not to)\b", command):
        return ""
    command = re.sub(r"^(?:please[, ]+)?(?:(?:can|could|will)\s+you\s+)?(?:please[, ]+)?", "", command)
    command = re.sub(r"^(?:i\s+(?:just\s+)?want\s+(?:you\s+to\s+|to\s+)?|give\s+me\s+|show\s+me\s+)", "", command)
    return "" if RE_INQUISITIVE_PREFIX.search(command) else command


def _clinical_candidate_metadata(candidate: str) -> dict[str, Any] | None:
    if is_franco_arabic(candidate):
        return {"franco": True}
    if _acute_injury_hit(candidate):
        return {}
    if RE_DIAGNOSIS.search(candidate) or (
        ARABIC_SCRIPT_RE.search(candidate) and RE_ARABIC_DIAGNOSIS.search(candidate)
    ):
        return {"mode": "diagnosis"}
    is_clinical, clinical_score = evaluate_clinical_semantic_guard(candidate, threshold=0.70)
    if is_clinical:
        return {"semantic_score": round(clinical_score, 3)}
    return None


def _deload_choice(query: str) -> str | None:
    """Returns an explicit, affirmative one-workout Deload command, if present."""
    english = RE_DELOAD_ENGLISH_CHOICE.fullmatch(query)
    if english:
        return (
            DELOAD_CHOICE_UNDO
            if english.group("verb").lower() in {"undo", "skip", "cancel", "remove", "reverse"}
            else DELOAD_CHOICE_APPLY
        )

    arabic = RE_ARABIC_DIACRITICS.sub("", query).strip()
    if RE_ARABIC_NEGATED_DELOAD_CHOICE.fullmatch(arabic):
        return DELOAD_NO_CHANGE_CHOICE
    if RE_ARABIC_NEGATION.search(arabic):
        return None
    if RE_ARABIC_DELOAD_AVOID.fullmatch(arabic):
        return DELOAD_CHOICE_UNDO
    match = RE_DELOAD_ARABIC_CHOICE.fullmatch(arabic)
    if not match:
        return None
    return (
        DELOAD_CHOICE_UNDO
        if match.group("verb") in ARABIC_DELOAD_UNDO_VERBS
        else DELOAD_CHOICE_APPLY
    )


def _authorized_action(query: str, intent: str) -> bool:
    command = _action_command(query)
    if intent == "program_mutation":
        return bool(RE_PROGRAM_MUTATION.match(command))
    return bool(RE_EXPLICIT_SWAP.match(command) or RE_SINGLE_SWAP.match(command)) and not bool(RE_PROGRAM_MUTATION.match(command))


def _classify_single_clause(clause: str, telemetry: str = "", messages: Sequence[BaseMessage] = ()) -> dict[str, Any] | None:
    c = clause.strip(" ,;?!.")
    if not c:
        return None

    clinical_metadata = _clinical_candidate_metadata(c)
    if clinical_metadata is not None:
        return {
            "intent": "clinical_intercept",
            "intent_metadata": {"raw_query": c, **clinical_metadata},
            "query": c,
        }

    if RE_BANNED_MOVEMENT.search(c):
        return {"intent": "banned_movement", "intent_metadata": {"raw_query": c}, "query": c}

    if _whole_session_query(c) or RE_EXERCISE_PERFORMANCE_QUERY.search(c) or RE_HISTORY_INDICATOR.search(c):
        return {"intent": "exercise_history", "intent_metadata": {"raw_query": c}, "query": c}

    telemetry_resp = reconcile_telemetry_query(c, telemetry)
    if telemetry_resp:
        return {
            "intent": "telemetry_intercept",
            "intent_metadata": {"response_content": telemetry_resp, "raw_query": c},
            "query": c,
        }

    if RE_NUTRITION.search(c):
        return {"intent": "coaching_qa", "intent_metadata": {}, "query": c}

    choice = _deload_choice(c)
    if choice:
        return {"intent": "deload_choice", "intent_metadata": {"choice": choice}, "query": c}

    if _authorized_action(c, "program_mutation"):
        return {
            "intent": "program_mutation",
            "intent_metadata": {"target_frequency": _extract_frequency(c)},
            "query": c,
        }

    command = _action_command(c)
    if not command or RE_INQUISITIVE_PREFIX.search(command):
        return {"intent": "coaching_qa", "intent_metadata": {}, "query": c}

    explicit_match = RE_EXPLICIT_SWAP.match(command)
    if explicit_match:
        data = explicit_match.groupdict()
        src, tgt = data["source"].strip(), data["target"].strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"] and not RE_FREQ_DIGIT.search(tgt):
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {"mode": "direct_swap", "source_exercise": src, "target_exercise": tgt},
                "query": c,
            }

    single_match = RE_SINGLE_SWAP.match(command)
    if single_match:
        src = single_match.group("source").strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"]:
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {"mode": "lookup_candidates", "source_exercise": src, "target_exercise": None},
                "query": c,
            }

    if RE_SEARCH_TOKENS.search(c):
        return {
            "intent": "catalog_search",
            "intent_metadata": {"search_query": RE_SEARCH_TOKENS.sub("", c).strip().rstrip(".!?")},
            "query": c,
        }

    return {"intent": "coaching_qa", "intent_metadata": {}, "query": c}


def _classify_intent_with_llm(query: str) -> IntentClassification:
    structured_llm = llm.with_structured_output(IntentClassification).bind(
        max_completion_tokens=player_output_budgets.player_output_budget("intent_routing")
    )
    return structured_llm.invoke(
        [SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=query)]
    )


def _arabic_program_context(program: Any) -> str:
    return "\n".join(
        f"- {day.day_name}: " + ", ".join(
            exercise.exercise_name for exercise in day.exercises
        )
        for day in getattr(program, "days", [])
    ) or "- None"


def _arabic_router_system_prompt(program: Any) -> str:
    split_types = ", ".join(
        split_type for split_type in ARABIC_SPLIT_PREFERENCES
        if split_type in SPLIT_DISPLAY_NAMES
    )
    return (
        f"{ARABIC_ROUTER_PROMPT}\n\n"
        f"Allowed split family keys: {split_types}.\n"
        f"Current Training program exercise names:\n{_arabic_program_context(program)}"
    )


def _classify_arabic_intent_with_llm(
    query: str, program: Any
) -> ArabicIntentClassification:
    structured_llm = llm.with_structured_output(ArabicIntentClassification).bind(
        max_completion_tokens=player_output_budgets.player_output_budget("intent_routing")
    )
    return structured_llm.invoke(
        [SystemMessage(content=_arabic_router_system_prompt(program)), HumanMessage(content=query)]
    )


def _is_arabic_dominant(query: str) -> bool:
    # Same rule as reply language (#256); ties fall back to English so unclear turns keep the existing route.
    return resolve_reply_language(query, "en") == "ar"


ARABIC_SPLIT_PREFERENCES = {
    split_type: split_type for split_type in SPLIT_DISPLAY_NAMES
}


def _resolve_arabic_day(program: Any, requested_name: str) -> Any | None:
    if not program or not requested_name.strip():
        return None
    requested = requested_name.strip().casefold()
    exact = [day for day in program.days if day.day_name.strip().casefold() == requested]
    if len(exact) == 1:
        return exact[0]
    words = set(re.findall(r"[a-z0-9]+", requested))
    if not words:
        return None
    matches = [
        day
        for day in program.days
        if words <= set(re.findall(r"[a-z0-9]+", day.day_name.casefold()))
    ]
    return matches[0] if len(matches) == 1 else None


def _current_split_family(program: Any) -> str | None:
    if not program:
        return None
    split_name = str(getattr(program, "split_type", "")).strip().casefold()
    frequency = getattr(program, "weekly_frequency", None)
    for (split_type, split_frequency), display_name in SPLIT_FREQUENCY_NAMES.items():
        if split_frequency == frequency and display_name.casefold() == split_name:
            return split_type if split_type in ARABIC_SPLIT_PREFERENCES else None
    for split_type, display_name in SPLIT_DISPLAY_NAMES.items():
        if display_name.casefold() == split_name:
            return split_type if split_type in ARABIC_SPLIT_PREFERENCES else None
    return match_split_keyword(split_name)


def _arabic_split_family(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in ARABIC_SPLIT_PREFERENCES:
        return normalized
    for split_type, display_name in SPLIT_DISPLAY_NAMES.items():
        if display_name.casefold() == normalized:
            return split_type if split_type in ARABIC_SPLIT_PREFERENCES else None
    if "arnold" in normalized and ("upper" in normalized or "lower" in normalized):
        return "arnold_x_ul"
    matched = match_split_keyword(normalized)
    return matched if matched in ARABIC_SPLIT_PREFERENCES else None


def _arabic_program_change_is_directive(query: str) -> bool:
    normalized = RE_ARABIC_DIACRITICS.sub("", query).strip()
    if normalized.endswith(("؟", "?")) or re.match(
        r"^(?:ينفع|إزاي|ازاي|ازاى|كيف|هل|لو(?!\s+سمحت)|مش|ما|لا|تنصحني|ايه رأيك|إيه رأيك)(?=\s|$)",
        normalized,
    ):
        return False
    if RE_ARABIC_NEGATED_PROGRAM_CHANGE.search(normalized) or re.search(
        r"(?<!\w)(?:مش|ما|لا)\s+(?:تغير|تظبط|تعدل|تبدل|تخلي|تعمل|تزود|تقلل)(?:لي)?(?!\w)",
        normalized,
    ):
        return False
    if RE_ARABIC_HEDGED_PROGRAM_CHANGE.search(normalized):
        return False
    return _authorized_action(query, "program_mutation") or bool(
        RE_ARABIC_PROGRAM_COMMAND.search(normalized)
        or RE_ARABIC_WANTED_PROGRAM_CHANGE.search(normalized)
    )


def _arabic_change_frequency(
    query: str, requested_frequency: int | None, current_frequency: Any
) -> int | None:
    mentioned_frequency = _mentioned_arabic_frequency(query)
    if requested_frequency is not None and (
        type(requested_frequency) is not int or not 1 <= requested_frequency <= 5
    ):
        return None
    if mentioned_frequency is not None and requested_frequency != mentioned_frequency:
        return None
    if type(current_frequency) is not int or not 1 <= current_frequency <= 5:
        return None
    return requested_frequency if requested_frequency is not None else current_frequency


def _default_arabic_split(frequency: int, profile: dict[str, Any]) -> str:
    gender = str(profile.get("gender", "male")).lower()
    split_type = DEFAULT_SPLIT_BY_FREQUENCY.get(gender, {}).get(frequency)
    if split_type not in ARABIC_SPLIT_PREFERENCES:
        split_type = DEFAULT_SPLIT_BY_FREQUENCY["male"].get(frequency, "full_body")
    return split_type


def _preserved_arabic_split(program: Any, profile: dict[str, Any], frequency: int) -> str:
    gender = profile.get("gender", "male")
    split_type = _current_split_family(program)
    if split_type not in ARABIC_SPLIT_PREFERENCES:
        return _default_arabic_split(frequency, profile)
    if split_type == "arnold_x_ul" and frequency < 4:
        split_type = "arnold"
    if get_split_plan(split_type, frequency, gender) is None:
        return _default_arabic_split(frequency, profile)
    return split_type


def _validated_arabic_split(
    classification: ArabicIntentClassification,
    program: Any,
    profile: dict[str, Any],
    frequency: int,
) -> str | None:
    requested_split = (
        _arabic_split_family(classification.target_split_type)
        if classification.target_split_type
        else None
    )
    if classification.target_split_type and requested_split is None:
        return None
    gender = profile.get("gender", "male")
    if requested_split == "arnold_x_ul" and frequency < 4:
        return None
    split_type = requested_split or _preserved_arabic_split(program, profile, frequency)
    return split_type if get_split_plan(split_type, frequency, gender) else None


def _validated_arabic_program_change(
    query: str, classification: ArabicIntentClassification, ledger: Any
) -> dict[str, Any] | None:
    if not _arabic_program_change_is_directive(query):
        return None
    if classification.target_frequency is None and not classification.target_split_type:
        return None
    profile = ledger.get_player_profile() or {}
    program = ledger.get_active_program()
    current_frequency = getattr(program, "weekly_frequency", None) or profile.get("weekly_frequency")
    frequency = _arabic_change_frequency(query, classification.target_frequency, current_frequency)
    if frequency is None:
        return None
    split_type = _validated_arabic_split(classification, program, profile, frequency)
    if split_type is None:
        return None
    return _arabic_program_mutation_route(frequency, split_type)


def _arabic_program_mutation_route(frequency: int, split_type: str) -> dict[str, Any]:
    return {
        "intent": "program_mutation",
        "intent_metadata": {
            "target_frequency": frequency,
            "split_preference": SPLIT_DISPLAY_NAMES[split_type],
            "split_family": ARABIC_SPLIT_PREFERENCES[split_type],
            "arabic_data_validated": True,
        },
    }


def _arabic_source_candidates(
    program: Any, source_name: str, requested_day: str | None
) -> list[tuple[Any, Any, float]]:
    source_stem = clean_movement_stem(source_name.lower())
    return [
        (day, exercise, _substitution_source_similarity(source_name, source_stem, exercise))
        for day in program.days
        if requested_day is None or day.day_name == requested_day
        for exercise in day.exercises
    ]


def _resolve_arabic_source(
    program: Any, requested_name: str, requested_day: str | None = None
) -> tuple[Any, Any] | None:
    source_name = expand_fitness_abbreviations(requested_name.strip())
    candidates = _arabic_source_candidates(program, source_name, requested_day)
    if not candidates:
        return None
    best_similarity = max(similarity for _, _, similarity in candidates)
    best_matches = [(day, exercise) for day, exercise, score in candidates if score == best_similarity]
    if best_similarity < SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD or len(best_matches) != 1:
        return None
    return best_matches[0]


def _arabic_name_search_candidates(store: Any, name: str) -> list[dict[str, Any]]:
    exact_resolver = getattr(store, "find_unique_exercise_id_by_exact_name", None)
    exact_id = exact_resolver(name) if callable(exact_resolver) else None
    if exact_id:
        return [
            entry
            for entry in (store.get_exercise_library_entry(str(exact_id)),)
            if entry is not None
        ]

    key_words = set(re.findall(r"[a-z0-9]+", name.casefold()))
    return [
        match
        for match in store.find_exercises_by_name(name, limit=None)
        if key_words
        and key_words.issubset(
            set(re.findall(r"[a-z0-9]+", str(match.get("name", "")).casefold()))
        )
    ]


def _arabic_target_name_matches(
    store: Any, source: Any, name: str
) -> tuple[list[dict[str, Any]], frozenset[str]]:
    near_miss_ids = near_miss_exercise_ids(name)
    matches = [
        match for match in _arabic_name_search_candidates(store, name)
        if str(match["id"]) != str(source.exercise_id)
        and str(match["id"]) not in near_miss_ids
        and store.is_exercise_library_exercise_visible(str(match["id"]))
    ]
    return matches, near_miss_ids


def _resolve_arabic_target(
    store: Any, source: Any, source_day: Any, requested_name: str
) -> tuple[str, dict[str, Any]] | None:
    source_entry = store.get_exercise_library_entry(str(source.exercise_id))
    if source_entry is None:
        return None
    raw_name = requested_name.strip()
    for name in dict.fromkeys((raw_name, expand_fitness_abbreviations(raw_name))):
        matches, near_miss_ids = _arabic_target_name_matches(
            store, source, name
        )
        if not matches:
            if near_miss_ids:
                return None
            continue
        if len(matches) != 1:
            return None
        match = _compatible_name_match(
            matches,
            source_entry.get("target_muscle"),
            source_entry.get("body_part"),
            source_day,
        )
        if match is not None:
            target_id = str(match["id"])
            target = store.get_exercise_library_entry(target_id)
            return (target_id, target) if target is not None else None
        if matches or near_miss_ids:
            return None
    return None


def _arabic_swap_source(
    program: Any, intent: ArabicIntentClassification
) -> tuple[Any, Any] | None:
    if not program or not intent.source_exercise:
        return None
    day = _resolve_arabic_day(program, intent.target_day) if intent.target_day else None
    if intent.target_day and day is None:
        return None
    return _resolve_arabic_source(
        program, intent.source_exercise, requested_day=day.day_name if day else None
    )


def _arabic_swap_metadata(
    source_day: Any, source: Any, target_id: str, target_entry: dict[str, Any]
) -> dict[str, Any]:
    return {
        "mode": "direct_swap",
        "source_exercise": source.exercise_name,
        "source_exercise_id": str(source.exercise_id),
        "source_day": source_day.day_name,
        "target_exercise": target_entry["name"],
        "target_exercise_id": str(target_id),
    }


def _validated_arabic_swap(
    program: Any, store: Any, intent: ArabicIntentClassification
) -> dict[str, Any] | None:
    if not intent.target_exercise:
        return None
    source_match = _arabic_swap_source(program, intent)
    if source_match is None:
        return None
    source_day, source = source_match
    target = _resolve_arabic_target(store, source, source_day, intent.target_exercise)
    if target is None:
        return None
    return _arabic_swap_metadata(source_day, source, *target)


def _arabic_history_program_match(program: Any, requested_name: str) -> tuple[str, str] | None:
    if program:
        requested = expand_fitness_abbreviations(requested_name.strip())
        source_stem = clean_movement_stem(requested.lower())
        candidates = [
            (exercise, _substitution_source_similarity(requested, source_stem, exercise))
            for day in program.days
            for exercise in day.exercises
        ]
        if candidates:
            best_score = max(score for _, score in candidates)
            best = [exercise for exercise, score in candidates if score == best_score]
            best_ids = {str(exercise.exercise_id) for exercise in best}
            if best_score >= SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD and len(best_ids) == 1:
                exercise = best[0]
                return str(exercise.exercise_id), exercise.exercise_name
    return None


def _arabic_history_library_match(store: Any, requested_name: str) -> tuple[str, str] | None:
    requested = expand_fitness_abbreviations(requested_name.strip())
    matches = [
        entry
        for entry in _arabic_name_search_candidates(store, requested)
        if store.is_exercise_library_exercise_visible(str(entry["id"]))
    ]
    by_id = {str(entry["id"]): entry for entry in matches}
    if len(by_id) != 1:
        return None
    exercise_id, entry = next(iter(by_id.items()))
    return exercise_id, str(entry["name"])


def _resolve_arabic_history_exercise(
    program: Any, store: Any, requested_name: str
) -> tuple[str, str] | None:
    return _arabic_history_program_match(program, requested_name) or (
        _arabic_history_library_match(store, requested_name)
    )


def _classify_arabic_program_change(
    query: str, classification: ArabicIntentClassification, ledger: Any
) -> dict[str, Any]:
    proposal = _validated_arabic_program_change(query, classification, ledger)
    if proposal is not None:
        return proposal
    if _arabic_program_change_is_directive(query):
        return _arabic_clarification_route("program_change")
    return {"intent": "coaching_qa", "intent_metadata": {}}


def _arabic_clarification_route(kind: str | None = None) -> dict[str, Any]:
    metadata = {"clarification_kind": kind} if kind else {}
    return {"intent": "arabic_swap_clarification", "intent_metadata": metadata}


def _arabic_history_route(exercise_id: str, exercise_name: str) -> dict[str, Any]:
    return {
        "intent": "exercise_history",
        "intent_metadata": {
            "raw_query": f"how did I do on {exercise_name} last session",
            "arabic_history": True,
            "history_exercise_id": exercise_id,
            "history_exercise_name": exercise_name,
        },
    }


def _classify_arabic_history(
    classification: ArabicIntentClassification, program: Any, store: Any
) -> dict[str, Any]:
    if classification.history_whole_session and not classification.history_exercise:
        return {
            "intent": "exercise_history",
            "intent_metadata": {
                "raw_query": "how did I perform last session",
                "arabic_history": True,
            },
        }
    if not classification.history_exercise or store is None:
        return _arabic_clarification_route("history")
    resolved = _resolve_arabic_history_exercise(program, store, classification.history_exercise)
    if resolved is None:
        return _arabic_clarification_route("history")
    return _arabic_history_route(*resolved)


def _arabic_swap_route(
    classification: ArabicIntentClassification,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if metadata is None:
        return _arabic_clarification_route(
            "program_reference" if classification.target_day else None
        )
    if classification.intent == "composite_intent" or classification.has_additional_request:
        metadata["has_additional_request"] = True
        return {"intent": "composite_intent", "intent_metadata": {"arabic_validated_swap": metadata}}
    return {"intent": "exercise_substitution", "intent_metadata": {**metadata, "arabic_data_validated": True}}


def _classify_arabic_swap(
    query: str, classification: ArabicIntentClassification, program: Any, store: Any
) -> dict[str, Any]:
    if not (
        RE_EXPLICIT_SWAP.search(query)
        or RE_ARABIC_SWAP_REQUEST.search(RE_ARABIC_DIACRITICS.sub("", query))
    ):
        return {"intent": "coaching_qa", "intent_metadata": {}}
    metadata = _validated_arabic_swap(program, store, classification) if store is not None else None
    return _arabic_swap_route(classification, metadata)


def _classify_arabic_intent(query: str, config: dict[str, Any] | None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    program = ledger.get_active_program() if ledger is not None else None
    try:
        classification = _classify_arabic_intent_with_llm(query, program)
    except Exception:
        logger.exception("Arabic player intent classification failed.")
        return {"intent": "coaching_qa", "intent_metadata": {}}
    if classification.intent in {"exercise_substitution", "composite_intent"} and (
        classification.intent == "exercise_substitution" or classification.has_swap
    ):
        return _classify_arabic_swap(query, classification, program, store)
    if classification.intent == "program_change":
        return _classify_arabic_program_change(query, classification, ledger)
    if classification.intent == "exercise_history":
        normalized = RE_ARABIC_DIACRITICS.sub("", query)
        if RE_ARABIC_TRAIN_REST_QUESTION.search(normalized):
            return {"intent": "coaching_qa", "intent_metadata": {}}
        return _classify_arabic_history(classification, program, store)
    return {"intent": "coaching_qa", "intent_metadata": {}}


def arabic_swap_clarification_node(
    state: AssistantState, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    kind = (state.get("intent_metadata") or {}).get("clarification_kind")
    response = {
        "program_change": ARABIC_PROGRAM_CHANGE_CLARIFICATION_RESPONSE,
        "program_reference": ARABIC_ACTION_CLARIFICATION_RESPONSE,
        "history": ARABIC_HISTORY_CLARIFICATION_RESPONSE,
    }.get(kind, ARABIC_SWAP_CLARIFICATION_RESPONSE)
    return _response(response)


def _clinical_turn_metadata(query: str, sub_intents=()) -> dict[str, Any] | None:
    if is_franco_arabic(query):
        return {"raw_query": query, "franco": True}
    queries = [query] + [part.strip() for part in RE_CLAUSE_SPLIT.split(query) if part.strip() != query]
    for sub in sub_intents:
        if sub.get("intent") == "clinical_intercept":
            return {**(sub.get("intent_metadata") or {}), "raw_query": query}
        if sub.get("query"):
            queries.append(sub["query"])
    for candidate in queries:
        clinical_metadata = _clinical_candidate_metadata(candidate)
        if clinical_metadata is not None:
            return {"raw_query": query, **clinical_metadata}
    return None


def _redundant_veto_followup(query: str) -> bool:
    return bool(re.fullmatch(
        r"(?:(?:should|can|could|may) i (?:add|do|include|try|use|perform) (?:it|them|that|those|this)(?: (?:exercise|movement|rows?))?"
        r"(?: (?:to|in) my (?:routine|program|split|workout))?|(?:is|are) (?:it|that|this|they|those) (?:safe|worth it|a good idea))",
        query.strip(" ,;?!."), re.IGNORECASE,
    ))


def _last_history_exchange(messages: Sequence[BaseMessage]) -> str | None:
    if not messages:
        return None
    followup = RE_FOLLOWUP_EXERCISE.fullmatch(_get_message_text(messages[-1]))
    if not followup:
        return None
    for message in reversed(messages[:-1]):
        if _message_role(message) != "user":
            continue
        prior = _get_message_text(message)
        if RE_FOLLOWUP_EXERCISE.fullmatch(prior):
            continue
        if not (_whole_session_query(prior) or RE_EXERCISE_PERFORMANCE_QUERY.search(prior) or RE_HISTORY_INDICATOR.search(prior)):
            return None
        target = re.sub(r"^(?:my|the)\s+", "", followup.group(1), flags=re.IGNORECASE).strip(" ?.")
        supported = _supported_history_query(prior)
        if RE_HISTORY_SCOPE.search(supported):
            return f"history for {target} {supported}"
        if re.search(r"\blast\s+logged\s+occurrence\b", prior, re.IGNORECASE):
            return f"last logged occurrence of {target}"
        return f"how did I do on {target} last session?"
    return None


def router_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if state.get("pipeline_error"):
        return {"intent": "telemetry_intercept", "intent_metadata": {"response_content": state["pipeline_error"]}}
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "coaching_qa", "intent_metadata": {}}

    query = _get_message_text(messages[-1])
    telemetry = state.get("telemetry_context") or ""
    arabic_dominant = _is_arabic_dominant(query)

    clinical = _clinical_turn_metadata(query)
    if clinical is not None:
        return {"intent": "clinical_intercept", "intent_metadata": clinical, "active_intents": []}

    choice = _deload_choice(query)
    if choice:
        return {"intent": "deload_choice", "intent_metadata": {"choice": choice}}

    history_followup = _last_history_exchange(messages)
    if (
        not arabic_dominant
        and history_followup is not None
        and not RE_BANNED_MOVEMENT.search(query)
        and len(RE_CLAUSE_SPLIT.split(query)) == 1
    ):
        return {"intent": "exercise_history", "intent_metadata": {"raw_query": history_followup}, "active_intents": []}

    name_response = _name_response(state, _graph_context(config)[0])
    if name_response:
        return {"intent": "telemetry_intercept", "intent_metadata": {"response_content": name_response}, "preferred_name": state.get("preferred_name")}

    if arabic_dominant:
        deterministic = _classify_single_clause(query, telemetry, messages)
        if deterministic and deterministic["intent"] in {
            "banned_movement",
            "telemetry_intercept",
            "deload_choice",
            "catalog_search",
        }:
            return {k: v for k, v in deterministic.items() if k != "query"}
        return _classify_arabic_intent(query, config)

    # Clause Splitting for Compound / Multi-Intent Queries
    clauses = [p.strip(" ,;?!.") for p in RE_CLAUSE_SPLIT.split(query) if p.strip(" ,;?!.")]
    if len(clauses) > 1:
        sub_results = [_classify_single_clause(c, telemetry, messages[:-1] + [HumanMessage(content=c)]) for c in clauses]
        sub_results = [r for r in sub_results if r is not None]
        clinical_sub = next((r for r in sub_results if r["intent"] == "clinical_intercept"), None)
        if clinical_sub:
            return {"intent": "clinical_intercept", "intent_metadata": {**clinical_sub["intent_metadata"], "raw_query": query}, "active_intents": []}
        if re.search(r"\b(?:if|unless|should|would|hypothetically|maybe|might)\b", query, re.IGNORECASE):
            for result in sub_results:
                if result["intent"] in {"program_mutation", "exercise_substitution"}:
                    result.update(intent="coaching_qa", intent_metadata={})
        actionable = [r for r in sub_results if r["intent"] != "coaching_qa"]
        if len(actionable) >= 2 or (len(actionable) == 1 and len(sub_results) >= 2):
            return {
                "intent": "composite_intent",
                "intent_metadata": {"sub_intents": sub_results, "raw_query": query},
                "active_intents": sub_results,
            }

    classified = _classify_single_clause(query, telemetry, messages)
    if classified and (classified["intent"] != "coaching_qa" or classified["intent_metadata"].get("clarification")):
        return {k: v for k, v in classified.items() if k != "query"}
    if not RE_ACTION_HINT.search(query) or not _action_command(query):
        return {"intent": "coaching_qa", "intent_metadata": {}}

    # LLM Router Fallback
    try:
        res = _classify_intent_with_llm(query)
        metadata: dict[str, Any] = {}
        if res.intent not in {"exercise_substitution", "program_mutation", "catalog_search", "coaching_qa"}:
            return {"intent": "coaching_qa", "intent_metadata": {}}
        if res.intent in {"exercise_substitution", "program_mutation"} and not _authorized_action(query, res.intent):
            return {"intent": "coaching_qa", "intent_metadata": {}}
        if res.intent == "exercise_substitution":
            src = res.source_exercise
            if not src:
                match = re.search(r"\b(?:for|to|swap|replace|substitute)\s+([a-zA-Z0-9\s\(\)\-\_]+)", query, re.IGNORECASE)
                if match:
                    src = match.group(1).strip()
            metadata = {
                "mode": "direct_swap" if res.target_exercise else "lookup_candidates",
                "source_exercise": src,
                "target_exercise": res.target_exercise,
            }
        elif res.intent == "program_mutation":
            metadata = {"target_frequency": res.target_frequency}
        elif res.intent == "catalog_search":
            metadata = {"search_query": res.search_query}

        return {"intent": res.intent, "intent_metadata": metadata}
    except Exception:
        return {"intent": "coaching_qa", "intent_metadata": {}}


def clinical_intercept_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    raw_query = meta.get("raw_query") or (_get_message_text(state["messages"][-1]) if state.get("messages") else "")
    if meta.get("franco"):
        response_key = ("franco", "input")
    else:
        language = "ar" if ARABIC_SCRIPT_RE.search(raw_query) else "en"
        response_type = "diagnosis" if meta.get("mode") == "diagnosis" else "clinical"
        response_key = (language, response_type)
    content = CLINICAL_SAFEGUARD_RESPONSES[response_key]
    return {"program_updated": False, "response_content": content, "messages": [AIMessage(content=content)]}


def banned_movement_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_query = _get_message_text(state["messages"][-1]).lower() if state.get("messages") else ""
    if "behind" in raw_query:
        msg = (
            "VETO: Behind-the-neck pressing is strictly prohibited due to extreme glenohumeral "
            "external rotation under load. Redirect immediately to seated dumbbell shoulder press "
            "or barbell overhead press in the scapular plane."
        )
    elif "upright" in raw_query:
        msg = (
            "VETO: Close-grip upright rows force internal rotation under axial load, inducing "
            "subacromial impingement. Redirect to cable lateral raises or chest-supported lateral raises."
        )
    else:
        msg = (
            "VETO: Light high-rep burn or activation sets cause excessive non-functional fatigue. "
            "Mandate heavy working sets (0-3 RIR) with 2-3+ minutes rest for mechanical tension."
        )
    return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}


def telemetry_intercept_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    content = state.get("intent_metadata", {}).get("response_content", "")
    return {"program_updated": False, "response_content": content, "messages": [AIMessage(content=content)]}


def _supported_history_query(query: str) -> str:
    query = re.sub(r"\b(?:compar\w*(?:\s+(?:it|that|this))?\s+(?:to|with|against)|versus|vs\.?)\s+(?:my |the )?(?:previous|prior|last)\s+(?:session|workout)\b", "", query, flags=re.IGNORECASE)
    if re.search(r"\bcompar\w*\b", query, re.IGNORECASE):
        query = re.sub(r"\s+(?:to|with|against)\s+(?:my |the )?(?:previous|prior|last)\s+(?:session|workout)\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\b(?:compare|comparison of)\s+(?=(?:my |the )?(?:last|latest)\s+(?:session|workout))", "", query, flags=re.IGNORECASE)
    if not RE_HISTORY_SCOPE.search(re.sub(r"\b(?:compare|comparison)\b", "", query, flags=re.IGNORECASE)):
        query = re.sub(r"^(?:compare|comparison\s+(?:for|of))\s+", "how did I do on ", query, flags=re.IGNORECASE)
    return query.strip(" ,;?!. ")


def _whole_session_query(query: str) -> bool:
    supported = _supported_history_query(query)
    if not supported and re.search(r"compar|versus|\bvs\b", query, re.IGNORECASE):
        return True
    query = re.sub(r"\b(?:all|every)\s+(?:the\s+)?exercises?\s+(?:from|in|on)\s+", "", supported, flags=re.IGNORECASE)
    return bool(re.fullmatch(
        r"(?:(?:how (?:was|is) (?:my )?(?:performance|perfomance)(?: in| on)?|how did i do(?: in| on)?|"
        r"give me (?:a )?summary of|(?:show|review|summari[sz]e|check)(?: me)?|"
        r"what (?:was|happened in))\s+)?"
        r"(?:my |the )?(?:last|latest|previous) (?:session|workout)(?: summary| performance| perfomance)?[?!.]*",
        query.strip(), re.IGNORECASE,
    ))


def _session_comparison_context(ledger: Any) -> dict[str, Any] | None:
    getter = getattr(ledger, "get_session_comparison_context", None)
    context = getter() if callable(getter) else None
    return context if isinstance(context, dict) else None


def _metric(value: Any, signed: bool = False) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        return "missing"
    return f"{value:+g}" if signed else f"{value:g}"


def _set_text(value: dict[str, Any] | None) -> str:
    value = value or {}
    return (
        f"{_metric(value.get('weight_kg'))} kg × {_metric(value.get('reps'))} reps"
        f" @ RIR {rir_label(value.get('rpe'))}"
    )


def _exercise_comparison_text(
    exercise: dict[str, Any], compact: bool = False, description: str | None = None
) -> str:
    current = exercise.get("current") or {}
    previous = exercise.get("previous")
    best = current.get("best_set") or {}
    description = description or exercise["name"]
    if compact:
        deltas = exercise.get("deltas") or {}
        baseline = (previous.get("session") or {}).get("session_date", "missing") if previous else "missing"
        status = exercise.get("status", "insufficient_data")
        return (
            f"{description} [{exercise['exercise_id']}]: best {_set_text(best)}; "
            f"sets={_metric(current.get('sets_count'))}, volume={_metric(current.get('volume_kg'))}kg; "
            f"baseline={baseline}; Δkg/reps/sets/volume/e1RM="
            + "/".join(_metric(deltas.get(key), signed=True) for key in ("load_kg", "reps", "sets", "volume_kg", "e1rm"))
            + f"; {status}."
        )
    content = (
        f"{description} [{exercise['exercise_id']}]: best {_set_text(best)}; "
        f"{_metric(current.get('sets_count'))} sets, {_metric(current.get('total_reps'))} total reps, "
        f"{_metric(current.get('volume_kg'))} kg volume."
    )
    if not compact:
        for logged_set in current.get("sets", []):
            content += f"\n  Set {logged_set['set_index']}: {_set_text(logged_set)}"
    if not previous:
        return content + " Baseline: missing previous occurrence; status: insufficient_data. No progress assessment available."
    content += f" Baseline: {previous['session']['session_date']} (previous logged occurrence"
    content += f"); best {_set_text(previous.get('best_set'))}."
    deltas = exercise.get("deltas") or {}
    content += " Observed deltas: " + ", ".join(
        f"{label} {_metric(deltas.get(key), signed=True)}{unit}"
        for key, label, unit in (("load_kg", "best load", " kg"), ("reps", "best reps", ""), ("sets", "sets", ""), ("volume_kg", "volume", " kg"), ("e1rm", "e1RM", " kg"))
    ) + "."
    # An unrated best set is scored with set_e1rm (#111), so the exercise's
    # real status stands: no effort reading downgrades it to insufficient_data.
    content += f" Status: {exercise.get('status', 'insufficient_data')} (observed, not a long-term trend)."
    return content


def _comparison_text(
    context: dict[str, Any], compact: bool = False, exercises=None, store: Any = None,
) -> str:
    session = context.get("session") or {}
    entries = context.get("exercises") or []
    sets_count = sum((ex.get("current") or {}).get("sets_count", 0) for ex in entries)
    volume = sum((ex.get("current") or {}).get("volume_kg", 0) for ex in entries)
    content = (
        f"Your last logged session: {session.get('split_name') or 'session'} on {session.get('session_date') or 'unknown date'}; "
        f"{sets_count} working sets, {_metric(volume)} kg total volume. Readiness: {_metric(session.get('readiness_score'))}/5.\n"
        f"Best set: {context.get('best_set_convention') or 'heaviest weight, then most reps, then earliest set_index'}. "
        "Each baseline is that exercise's previous logged occurrence, not necessarily the previous session."
    )
    selected = entries if exercises is None else exercises
    descriptions = (
        describe_exercises(
            store,
            ((exercise["exercise_id"], exercise["name"]) for exercise in selected),
        )
        if store is not None
        else [exercise["name"] for exercise in selected]
    )
    for exercise, description in zip(selected, descriptions):
        content += "\n- " + _exercise_comparison_text(exercise, compact, description)
    if not entries:
        content += "\nNo completed working sets recorded in this session; no progress assessment available."
    return content


def _session_summary_response(ledger: Any, store: Any) -> dict[str, Any]:
    comparison = _session_comparison_context(ledger)
    if comparison is not None:
        player_text = _comparison_text(comparison)
        model_text = _comparison_text(comparison, store=store)
        return _response_with_model_context(player_text, model_text)
    getter = getattr(ledger, "get_latest_session_summary", None)
    summary = getter() if callable(getter) else None
    if not isinstance(summary, dict) or not summary:
        return _response("I don't have a logged session summary available yet. Log a session and I can review it.")

    def number(value):
        return f"{value:g}" if type(value) in (int, float) and math.isfinite(value) and value >= 0 else "unavailable"

    date = summary.get("session_date")
    split = summary.get("split_name")
    label = split[:80] if isinstance(split, str) and split else "session"
    when = f" on {date[:32]}" if isinstance(date, str) and date else ""
    content = (
        f"Your last logged {label}{when}: {number(summary.get('sets_count'))} working sets, "
        f"{number(summary.get('total_volume_kg'))} kg total volume. "
        f"Readiness: {number(summary.get('readiness_score'))}/5."
    )
    model_content = content
    exercises = summary.get("exercises")
    model_exercises = []
    if isinstance(exercises, list):
        valid_exercises = [
            exercise for exercise in exercises
            if isinstance(exercise, dict) and isinstance(exercise.get("name"), str)
        ]
        described = describe_exercises(
            store,
            (
                (str(exercise.get("exercise_id") or ""), exercise["name"])
                for exercise in valid_exercises
            ),
        )
        for exercise, description in zip(valid_exercises, described):
            content += (
                f"\n- {exercise['name'][:100]}: {number(exercise.get('sets'))} sets, "
                f"{number(exercise.get('reps'))} total reps, {number(exercise.get('volume_kg'))} kg volume."
            )
            model_exercises.append(
                f"\n- {description[:300]}: {number(exercise.get('sets'))} sets, "
                f"{number(exercise.get('reps'))} total reps, {number(exercise.get('volume_kg'))} kg volume."
            )
    ending = "\n\nThis is a session snapshot; a comparison is needed to assess progress."
    return _response_with_model_context(content + ending, model_content + "".join(model_exercises) + ending)


def _arabic_history_fallback(
    state: AssistantState, config: dict[str, Any] | None
) -> dict[str, Any]:
    metadata = dict(state.get("intent_metadata", {}))
    metadata.pop("arabic_history", None)
    resolved = exercise_history_node({**state, "intent_metadata": metadata}, config)
    facts = (
        resolved.get("model_context_content")
        or resolved.get("response_content")
        or resolved.get("telemetry_context")
        or "No matching Training ledger history was found."
    )
    return {
        "intent": "exercise_history_fallback",
        "telemetry_context": (
            "Verified Training ledger history for this request. Use only these "
            "figures and answer in the latest message's language:\n" + str(facts)
        ),
    }


def _history_name(name: str) -> str:
    name = expand_fitness_abbreviations(name).lower()
    name = re.sub(r"\b(squat|deadlift|curl|row|press|lunge)(?:s|es)\b", r"\1", name)
    return " ".join(re.findall(r"[a-z0-9]+", name))


def _history_exercise_matches(target: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = _history_name(target)
    exact = [ex for ex in entries if str(ex['exercise_id']).lower() == target.lower() or _history_name(ex['name']) == normalized]
    if exact:
        return exact
    tokens = set(normalized.split())
    return [ex for ex in entries if tokens and tokens <= set(_history_name(ex['name']).split())]


def _history_catalog_matches(store: Any, target: str) -> list[dict[str, Any]]:
    with store.catalog_locked() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM exercises ORDER BY name COLLATE NOCASE, id")
        entries = [{"exercise_id": str(row[0]), "name": row[1]} for row in cursor.fetchall()]
    return _history_exercise_matches(target, entries)


def _history_model_fallback(state: AssistantState, config: dict[str, Any] | None) -> dict[str, Any]:
    fallback_state = {**state, "intent": "exercise_history_fallback"}
    return {
        **hydrate_context_node(fallback_state, config),
        "intent": "exercise_history_fallback",
    }


def exercise_history_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    messages = state.get("messages", [])
    metadata = state.get("intent_metadata", {})
    if metadata.get("arabic_history"):
        return _arabic_history_fallback(state, config)
    raw_query = metadata.get("raw_query")
    raw_query = _get_message_text(raw_query) if raw_query else (_get_message_text(messages[-1]) if messages else "")
    if _whole_session_query(raw_query):
        return _session_summary_response(ledger, store)
    lookup_query = _supported_history_query(raw_query)
    if RE_HISTORY_SCOPE.search(lookup_query):
        return _response("The requested time period is unavailable in this history lookup. I can compare the latest session with each exercise's previous logged occurrence, but cannot answer that date range.")
    occurrence = bool(re.search(r"\blast\s+logged\s+occurrence\b", lookup_query, re.IGNORECASE))
    lookup_query = re.sub(r"\b(?:in |on |during )?(?:my |the )?(?:last|latest|previous)\s+(?:session|workout)\b|\blast\s+logged\s+occurrence(?:\s+(?:of|for))?\b", "", lookup_query, flags=re.IGNORECASE).strip(" ,;?.")
    match = RE_EXERCISE_PERFORMANCE_QUERY.search(lookup_query)
    if match:
        target_name = match.group(1).strip(" ?.")
    else:
        match = re.search(r"\bhow\s+did\s+my\s+(.+?)\s+(?:look|go|perform)(?:\s|[?!.]|$)", raw_query, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(?:history|logged\s+(?:sets?|performance))\s+(?:for|on|of)\s+(.+)", raw_query, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(?:my\s+)?(.+?)\s+history\b", raw_query, re.IGNORECASE)
        if not match:
            match = re.search(r"^(?:for|on|in)\s+(.+)", lookup_query, re.IGNORECASE)
        if not match and occurrence:
            target_name = lookup_query
        elif not match:
            return _history_model_fallback(state, config)
        else:
            target_name = match.group(1).strip(" ?.")
    target_name = re.sub(r"\b(?:my|session|workout|sets?)\b", "", target_name, flags=re.IGNORECASE).strip(" ?.")
    target_name = expand_fitness_abbreviations(target_name)
    target_name = re.sub(r"\b(squat|deadlift|curl|row|press|lunge)(?:s|es)\b", r"\1", target_name, flags=re.IGNORECASE)
    if not target_name or target_name.lower() in {"load", "weight", "it", "that", "lifts", "training"}:
        return _history_model_fallback(state, config)

    comparison = _session_comparison_context(ledger)
    if not occurrence and comparison is not None:
        entries = comparison.get("exercises") or []
        matches = _history_exercise_matches(target_name, entries)
        if len(matches) == 1:
            player_text = _comparison_text(
                comparison, exercises=matches,
            )
            model_text = _comparison_text(comparison, exercises=matches, store=store)
            return _response_with_model_context(player_text, model_text)
        if len(matches) > 1:
            player_text = "Which exercise variant do you mean? " + ", ".join(
                f"{ex['name']} [{ex['exercise_id']}]" for ex in matches
            )
            descriptions = describe_exercises(
                store, ((ex["exercise_id"], ex["name"]) for ex in matches)
            )
            model_text = "Which exercise variant do you mean? " + ", ".join(
                f"{description} [{ex['exercise_id']}]"
                for ex, description in zip(matches, descriptions)
            )
            return _response_with_model_context(player_text, model_text)
        catalog = _history_catalog_matches(store, target_name)
        if not catalog:
            return _history_model_fallback(state, config)
        if len(catalog) > 1:
            player_text = "Which exercise variant do you mean? " + ", ".join(
                f"{ex['name']} [{ex['exercise_id']}]" for ex in catalog
            )
            descriptions = describe_exercises(
                store, ((ex["exercise_id"], ex["name"]) for ex in catalog)
            )
            model_text = "Which exercise variant do you mean? " + ", ".join(
                f"{description} [{ex['exercise_id']}]"
                for ex, description in zip(catalog, descriptions)
            )
            return _response_with_model_context(player_text, model_text)
        date = (comparison.get("session") or {}).get("session_date", "unknown date")
        return _response(f"No completed working sets for '{target_name}' in your latest session ({date}). This does not mean it was never logged. Ask for its last logged occurrence to look beyond that session.")
    if not occurrence:
        return _response("Latest-session exercise comparisons are unavailable. Ask explicitly for the last logged occurrence of an exercise to search older records.")
    candidates = _history_catalog_matches(store, target_name)
    if len(candidates) > 1:
        player_text = "Which exercise variant do you mean? " + ", ".join(
            f"{ex['name']} [{ex['exercise_id']}]" for ex in candidates
        )
        descriptions = describe_exercises(
            store, ((ex["exercise_id"], ex["name"]) for ex in candidates)
        )
        model_text = "Which exercise variant do you mean? " + ", ".join(
            f"{description} [{ex['exercise_id']}]"
            for ex, description in zip(candidates, descriptions)
        )
        return _response_with_model_context(player_text, model_text)
    exercise = {"id": candidates[0]["exercise_id"], "name": candidates[0]["name"]} if candidates else None
    if not exercise:
        return _history_model_fallback(state, config)

    sets = ledger.get_last_performance(str(exercise["id"]))

    if not sets:
        description = describe_exercise(store, exercise["id"], exercise["name"])
        msg = f"You haven't logged any completed working sets for **{exercise['name']}** yet."
        model_text = f"You haven't logged any completed working sets for **{description}** yet."
        return _response_with_model_context(msg, model_text)

    description = describe_exercise(store, exercise["id"], exercise["name"])
    set_lines = [f"- Set {s['set_index']}: {_set_text(s)}" for s in sets]
    content = (
        f"**Last logged occurrence for {exercise['name']}:**\n" + "\n".join(set_lines)
        + "\nThis may predate your latest session. This occurrence lookup does not provide a date or comparison; no progress assessment available."
    )
    model_content = content.replace(
        f"**Last logged occurrence for {exercise['name']}:**",
        f"**Last logged occurrence for {description}:**",
        1,
    )
    return _response_with_model_context(content, model_content)


def resolve_coreference_with_llm(
    query: str, messages: Sequence[BaseMessage], active_program, store: Any
) -> tuple[str | None, str | None]:
    prompt = _build_coreference_prompt(query, messages, active_program, store)
    try:
        structured_llm = llm.with_structured_output(SubstitutionResolution).bind(
            max_completion_tokens=player_output_budgets.player_output_budget("substitution_resolution")
        )
        res: SubstitutionResolution = structured_llm.invoke(prompt)
        return res.source_exercise, res.target_exercise
    except Exception as e:
        logger.warning(f"Coreference LLM fallback failed: {e}")
        return None, None


def _build_coreference_prompt(
    query: str, messages: Sequence[BaseMessage], active_program: Any, store: Any
) -> list[BaseMessage]:
    routine_names, chat_lines = _coreference_context(active_program, store, messages)
    coreference_prompt = (
        "You are an entity resolution engine for a fitness app.\n"
        "The user wants to replace or find alternatives for an exercise, but used a conversational reference.\n\n"
        f"[Active Routine Exercises]\n{chr(10).join(routine_names)}\n\n"
        f"[Recent Conversation]\n{chr(10).join(chat_lines)}\n\n"
        f'User\'s Query: "{query}"\n\n'
        "Identify source_exercise and target_exercise. Return ONLY valid structured data."
    )
    return [SystemMessage(content=coreference_prompt), HumanMessage(content=query)]


def _coreference_context(
    active_program: Any, store: Any, messages: Sequence[BaseMessage]
) -> tuple[list[str], list[str]]:
    routine_exercises = [
        (day, exercise)
        for day in active_program.days
        for exercise in day.exercises
    ]
    descriptions = describe_exercises(
        store,
        ((exercise.exercise_id, exercise.exercise_name) for _, exercise in routine_exercises),
    )
    routine_names = [
        f"- {description} (Day: {day.day_name})"
        for (day, _), description in zip(routine_exercises, descriptions)
    ]
    tail = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-3:]
    chat_lines = [f"{'Trainee' if isinstance(m, HumanMessage) else 'Coach'}: {_get_message_text(m)}" for m in tail]
    return routine_names, chat_lines


@dataclass(frozen=True)
class _AlternativeSuggestionRequest:
    source_id: str
    source_name: str
    source_entry: dict[str, Any]
    equipment_access: str
    prescribed_ids: frozenset[str]
    target_muscle: str
    body_part: str


def _matching_replace_alternatives(
    store: Any, request: _AlternativeSuggestionRequest
) -> list[dict[str, Any]]:
    matches = store.find_exercises_by_name(
        "",
        limit=1 + len(request.prescribed_ids) + 3,
        equipment_access=request.equipment_access,
        filter_browse=True,
        replacing_exercise_id=request.source_id,
    )
    source_action = request.source_entry.get("primary_action")
    source_muscle = request.source_entry.get("primary_muscle")
    return [
        match
        for match in matches
        if match["id"] != request.source_id
        and match["id"] not in request.prescribed_ids
        and (
            (source_action and match.get("primary_action") == source_action)
            or (source_muscle and match.get("primary_muscle") == source_muscle)
        )
    ][:3]


def _similar_candidate_is_compatible(
    candidate: dict[str, Any],
    request: _AlternativeSuggestionRequest,
    excluded_ids: set[str],
) -> bool:
    candidate_id = str(candidate["id"])
    target_hit = bool(
        request.target_muscle
        and request.target_muscle.lower()
        in (candidate.get("target_muscle") or "").lower()
    )
    candidate_body = (candidate.get("body_part") or "").lower()
    body_hit = bool(
        candidate_body
        and request.body_part
        and candidate_body == request.body_part.lower()
    )
    return (
        candidate_id != request.source_id
        and candidate_id not in request.prescribed_ids
        and candidate_id not in excluded_ids
        and equipment_access_allows(request.equipment_access, candidate.get("equipment"))
        and (target_hit or body_hit)
    )


def _similar_alternatives(
    store: Any,
    request: _AlternativeSuggestionRequest,
    excluded_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    query_vec = EMBED_MODEL.embed_query(
        f"{request.target_muscle} {request.source_name}"
    )
    candidates = []
    for candidate in store.search_similar_exercises(query_vec, limit=12):
        if not _similar_candidate_is_compatible(candidate, request, excluded_ids):
            continue
        candidates.append(candidate)
        if len(candidates) == limit:
            break
    return candidates


def _replace_ranked_alternative_candidates(
    store: Any, request: _AlternativeSuggestionRequest
) -> list[dict[str, Any]]:
    ranked = _matching_replace_alternatives(store, request)
    fallback = _similar_alternatives(
        store,
        request,
        {str(candidate["id"]) for candidate in ranked},
        3 - len(ranked),
    )
    return ranked + fallback


def _muscle_compatible(candidate: dict[str, Any], target_muscle: str, body_part: str) -> bool:
    """True when a candidate fills the slot's muscle (containment either direction, or body part)."""
    candidate_muscle = (candidate.get("target_muscle") or "").lower()
    slot_muscle = (target_muscle or "").lower()
    candidate_body = (candidate.get("body_part") or "").lower()
    slot_body = (body_part or "").lower()
    muscle_hit = bool(
        slot_muscle and candidate_muscle and (slot_muscle in candidate_muscle or candidate_muscle in slot_muscle)
    )
    body_hit = bool(slot_body and candidate_body and candidate_body == slot_body)
    return muscle_hit or body_hit


def _compatible_name_match(
    matches: list[dict[str, Any]], target_muscle: str, body_part: str, target_day: Any
) -> dict[str, Any] | None:
    compatible = [
        match for match in matches
        if _muscle_compatible(match, target_muscle, body_part)
    ]
    day_ids = {str(exercise.exercise_id) for exercise in target_day.exercises}
    return next(
        (match for match in compatible if str(match["id"]) not in day_ids),
        compatible[0] if compatible else None,
    )


def _near_miss_refusal(store: Any, target: str, exercise_ids: frozenset[str]) -> dict[str, Any]:
    similar_names = [
        entry["name"]
        for exercise_id in exercise_ids
        if store.is_exercise_library_exercise_visible(exercise_id)
        if (entry := store.get_exercise_library_entry(exercise_id)) is not None
    ]
    if similar_names:
        detail = ", ".join(f"**{name.title()}** is a different exercise" for name in similar_names)
    else:
        detail = "it is not a verified movement in this catalog"
    content = f"I can't resolve **{target}** as requested because {detail}."
    return {"program_updated": False, "response_content": content, "messages": [AIMessage(content=content)]}


def _slot_alternative_lines(
    db: Any,
    matched_ex: Any,
    target_muscle: str,
    body_part: str,
    equipment_access: str,
) -> list[str]:
    alt_vec = EMBED_MODEL.embed_query(f"{target_muscle} {matched_ex.exercise_name}")
    slot_candidates = db.search_similar_exercises(alt_vec, limit=6)
    return [
        f"- **{c['name'].title()}** (`{c.get('target_muscle', '').title()}` | `{c.get('equipment', '')}`)"
        for c in slot_candidates
        if str(c["id"]) != str(matched_ex.exercise_id)
        and equipment_access_allows(equipment_access, c.get("equipment"))
        and _muscle_compatible(c, target_muscle, body_part)
    ][:3]


def _movement_tail(candidate: dict[str, Any]) -> list[str]:
    """Last two words of the source name ("... lateral pulldown"), which variants of one movement share."""
    return (candidate.get("source_name") or candidate["name"]).lower().split()[-2:]


def _target_is_name_like(target_desc: str, candidates: list[dict[str, Any]]) -> bool:
    """True when the target reads like a specific exercise name that failed to resolve by name.

    Guards the semantic fallback: a named near miss with one shared movement term
    must refuse instead of installing its nearest lexical sibling.
    """
    target_tokens = {t for t in re.findall(r"[a-z0-9]+", target_desc.lower()) if len(t) > 2}
    if len(target_tokens) < 2:
        return False
    for candidate in candidates[:5]:
        # Players may name an exercise by its display name or its source name.
        for name in (candidate.get("name"), candidate.get("source_name")):
            candidate_tokens = set(re.findall(r"[a-z0-9]+", (name or "").lower()))
            if len(target_tokens & candidate_tokens) / len(target_tokens) >= 0.6:
                return True
    return False


def _requested_substitution_day(program: Any, query: str) -> str | None:
    """Resolve a day only when the message uses an explicit day reference."""
    normalized_query = query.strip().rstrip(".!?,").casefold()
    for day in sorted(program.days, key=lambda candidate: len(candidate.day_name), reverse=True):
        day_name = day.day_name.strip()
        base_name = re.sub(r"\s+day$", "", day_name, flags=re.IGNORECASE)
        names = {day_name, base_name}
        if normalized_query in {name.casefold() for name in names if name}:
            return day.day_name
        if normalized_query in {f"{name} day".casefold() for name in names if name}:
            return day.day_name
        for name in names:
            if not name:
                continue
            reference = re.escape(name)
            if re.search(rf"\b(?:on|in)\s+{reference}(?:\s+day)?\b", query, re.IGNORECASE):
                return day.day_name
            if re.search(rf"\bfor\s+{reference}\s+day\b", query, re.IGNORECASE):
                return day.day_name
    return None


def _source_request_fields(
    program: Any, source_name: str, requested_day: str | None
) -> tuple[str | None, str | None]:
    if not program or not source_name:
        return None, None
    resolved_source = expand_fitness_abbreviations(
        _remove_day_suffix(source_name.strip(), requested_day)
    )
    source_stem = clean_movement_stem(resolved_source.lower())
    matches = [
        (day, exercise)
        for day in program.days
        if requested_day is None or day.day_name == requested_day
        for exercise in day.exercises
        if _substitution_source_similarity(resolved_source, source_stem, exercise) == 1.0
    ]
    exercise_ids = {str(exercise.exercise_id) for _, exercise in matches}
    if len(exercise_ids) != 1:
        return None, None
    exercise_id = exercise_ids.pop()
    matching_days = {day.day_name for day, exercise in matches if str(exercise.exercise_id) == exercise_id}
    day_name = next(iter(matching_days)) if len(matching_days) == 1 else None
    return day_name, exercise_id


def _substitution_request_suggestion(
    store: Any, ledger: Any, query: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    source_name = str(metadata.get("source_exercise") or "").strip()
    target_name = str(metadata.get("target_exercise") or "").strip()
    program = ledger.get_active_program()
    requested_day = _requested_substitution_day(program, query) if program else None
    day_name, exercise_id = _source_request_fields(program, source_name, requested_day)
    replacement_name = (
        expand_fitness_abbreviations(_remove_day_suffix(target_name, requested_day))
        if target_name
        else ""
    )
    replacement_id = (
        store.find_unique_exercise_id_by_exact_name(replacement_name)
        if replacement_name
        else None
    )
    if replacement_id == exercise_id:
        replacement_id = None
    return {
        "kind": "exercise_substitution",
        "day_name": day_name,
        "exercise_id": exercise_id,
        "replacement_exercise_id": replacement_id,
        "reason": _request_suggestion_reason(query),
    }


def _request_suggestion_reason(query: str) -> str:
    return query[:MAX_REASON_CHARS]


def _split_change_request_suggestion(query: str, metadata: dict[str, Any]) -> dict[str, Any]:
    frequency = _extract_frequency(query)
    if frequency is not None and not 1 <= frequency <= 5:
        frequency = None
    elif frequency is None:
        supplied_frequency = metadata.get("target_frequency")
        if type(supplied_frequency) is int and 1 <= supplied_frequency <= 5:
            frequency = supplied_frequency
    split_preference = metadata.get("split_preference")
    return {
        "kind": "split_change",
        "desired_weekly_frequency": frequency,
        "desired_split_preference": split_preference if isinstance(split_preference, str) else None,
        "reason": _request_suggestion_reason(query),
    }


def _coach_program_refusal(query: str) -> str:
    if ARABIC_SCRIPT_RE.search(query):
        return (
            "يتولى مدربك المعيّن التحكم في برنامجك التدريبي. "
            "يمكنك مراجعة طلب وإرساله إلى مدربك."
        )
    return programs_service.COACH_CONTROLLED_REQUEST_ERROR


def _arabic_frequency_label(frequency: int) -> str:
    if frequency == 1:
        return "يوم واحد"
    if frequency == 2:
        return "يومين"
    return f"{frequency} أيام"


def _remove_day_suffix(exercise_name: str, day_name: str | None) -> str:
    if not day_name:
        return exercise_name
    return re.sub(
        rf"\s+(?:(?:on|in|for)\s+)?{re.escape(day_name)}(?:\s+day)?\s*$",
        "",
        exercise_name,
        flags=re.IGNORECASE,
    )


#: Bare number words reply to the numbered alternatives list rather than naming a movement
#: ("one" substring-matches "one arm dip"/"one leg squat"). Whole-string equality only, so
#: multi-word names containing them ("one arm pulldown") are unaffected.
UNSPECIFIC_CHOICE_WORDS = {"one", "two", "three", "first", "second", "third"}


def _validated_swap_success(
    state: AssistantState,
    metadata: dict[str, Any],
    substitution: dict[str, Any],
    ledger: Any,
) -> dict[str, Any]:
    replacement = substitution["replacement"]
    profile = ledger.get_player_profile() or {}
    experience_level = experience_level_for_training_age(profile.get("training_age_years", 0.0))
    day_name = substitution["day_names"][0]
    msg = _validated_swap_message(metadata, replacement, day_name, experience_level)
    if metadata.get("has_additional_request"):
        msg += "\n\n" + ARABIC_ONE_AT_A_TIME_NOTE
    return {
        "program_updated": True,
        "program_change": "swapped",
        "response_content": msg,
        "messages": [AIMessage(content=msg)],
    }


def _validated_swap_message(
    metadata: dict[str, Any], replacement: dict[str, Any], day_name: str, experience_level: str
) -> str:
    new_notes = replacement.get("instructions") or get_biomechanical_cue(replacement, experience_level)
    msg = (
        f"✅ **Routine Slot Updated ({day_name})**\n\n"
        f"- **Removed:** {metadata['source_exercise'].title()}\n"
        f"- **Installed:** {replacement['name'].title()} "
        f"(`{replacement['target_muscle']}` | `{replacement['equipment']}`)\n"
        f"- **Execution Directive:** *{new_notes}*"
    )
    return msg


def _persist_validated_swap(
    ledger: Any, store: Any, active_program: Any, metadata: dict[str, Any]
) -> dict[str, Any]:
    return substitute_program_exercise(
        ledger,
        store,
        active_program,
        ProgramSubstitution(
            day_name=metadata["source_day"],
            exercise_id=metadata["source_exercise_id"],
            replacement_exercise_id=metadata["target_exercise_id"],
        ),
    )


def _apply_validated_swap(
    state: AssistantState, config: dict[str, Any] | None, metadata: dict[str, Any]
) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    query = _get_message_text(state["messages"][-1])
    if not programs_service.player_controls_program(store, ledger, state.get("player_account_id")):
        return _response(_coach_program_refusal(query))
    active_program = ledger.get_active_program()
    if active_program is None:
        return _response(ARABIC_SWAP_CLARIFICATION_RESPONSE)
    substitution = _persist_validated_swap(ledger, store, active_program, metadata)
    if not substitution["ok"]:
        return _response(ARABIC_SWAP_CLARIFICATION_RESPONSE)
    return _validated_swap_success(state, metadata, substitution, ledger)


def exercise_substitution_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    meta = state.get("intent_metadata", {})
    if meta.get("arabic_data_validated") is True:
        return _apply_validated_swap(state, config, meta)

    source_name = (meta.get("source_exercise") or "").strip()
    target_desc = (meta.get("target_exercise") or "").strip()
    query = _get_message_text(state["messages"][-1])

    if not _authorized_action(query, "exercise_substitution"):
        return _response(AUTHORIZATION_RESPONSE)

    if not programs_service.player_controls_program(store, ledger, state.get("player_account_id")):
        suggestion = _substitution_request_suggestion(store, ledger, query, meta)
        return _response(_coach_program_refusal(query), request_suggestion=suggestion)

    active_program = ledger.get_active_program()
    if not active_program:
        msg = "No active routine found in your ledger. Generate a baseline routine first."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}
    player_profile = ledger.get_player_profile() or {}
    equipment_access = map_equipment_access(player_profile.get("equipment_access", COMMERCIAL_GYM))
    experience_level = experience_level_for_training_age(player_profile.get("training_age_years", 0.0))

    requested_day_name = _requested_substitution_day(active_program, query)

    raw_source = source_name
    raw_target = _remove_day_suffix(target_desc, requested_day_name)
    target_desc = raw_target

    # Expand fitness abbreviations (e.g. RDLs -> romanian deadlift, OHP -> overhead press, DB -> dumbbell)
    source_name = expand_fitness_abbreviations(source_name)
    target_desc = expand_fitness_abbreviations(target_desc)

    # If target_desc is an acronym token not in static dict, attempt LLM resolution
    if target_desc and len(target_desc.split()) == 1 and 2 <= len(target_desc) <= 6:
        llm_expanded = resolve_unknown_abbreviation_with_llm(target_desc)
        if llm_expanded:
            target_desc = llm_expanded

    PRONOUNS = {"it", "this", "that", "them", "choice", "option"}
    source_lower = source_name.lower()
    needs_llm_resolution = (
        not source_name
        or source_lower in PRONOUNS
        or len(source_name) < 3
        or any(word in source_lower for word in ["choice", "option", "number", "first", "second", "third"])
    )

    if needs_llm_resolution:
        resolved_src, resolved_tgt = resolve_coreference_with_llm(
            query, state.get("messages", []), active_program, store
        )
        if resolved_src:
            source_name = expand_fitness_abbreviations(resolved_src)
        if resolved_tgt:
            target_desc = expand_fitness_abbreviations(resolved_tgt)

    matched_ex, target_day, best_similarity = _match_substitution_source(active_program.days, source_name)
    if requested_day_name:
        requested_day = next(day for day in active_program.days if day.day_name == requested_day_name)
        requested_match = _match_substitution_source([requested_day], source_name)
        if requested_match[0] and requested_match[2] >= SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD:
            matched_ex, target_day, best_similarity = requested_match

    if (
        requested_day_name is None
        and matched_ex
        and best_similarity >= SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD
    ):
        matching_days = [
            day
            for day in active_program.days
            if any(str(ex.exercise_id) == str(matched_ex.exercise_id) for ex in day.exercises)
        ]
        if len(matching_days) > 1:
            day_list = ", ".join(day.day_name for day in matching_days)
            msg = f"I found **{matched_ex.exercise_name.title()}** on more than one day: {day_list}. Which day should I change?"
            return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    if not matched_ex or best_similarity < SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD:
        routine_exercises = [
            (day, exercise)
            for day in active_program.days
            for exercise in day.exercises
        ]
        descriptions = describe_exercises(
            store,
            ((exercise.exercise_id, exercise.exercise_name) for _, exercise in routine_exercises),
        )
        routine_list = [
            f"- {exercise.exercise_name.title()} (Day {day.day_order}: {day.day_name})"
            for day, exercise in routine_exercises
        ]
        model_routine_list = [
            f"- {description} (Day {day.day_order}: {day.day_name})"
            for (day, _), description in zip(routine_exercises, descriptions)
        ]
        if requested_day_name:
            msg = f"Could not identify **'{raw_source or source_name or query}'** in {requested_day_name}."
            model_msg = msg
        else:
            msg = f"Could not identify **'{raw_source or source_name or query}'** in your active split.\n\n**Active Movements:**\n" + "\n".join(routine_list)
            model_msg = f"Could not identify **'{raw_source or source_name or query}'** in your active split.\n\n**Active Movements:**\n" + "\n".join(model_routine_list)
        return _response_with_model_context(msg, model_msg)

    with store.catalog_locked() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT body_part, target_muscle, equipment FROM exercises WHERE id = ?", (matched_ex.exercise_id,))
        target_meta = cursor.fetchone()
    body_part, target_muscle, _ = target_meta if target_meta else ("", "", "")
    source_entry = store.get_exercise_library_entry(str(matched_ex.exercise_id))
    source_description = describe_exercise(
        store, str(matched_ex.exercise_id), matched_ex.exercise_name, entry=source_entry
    )

    if not target_desc:
        valid_candidates = []
        suggested_staples = getattr(matched_ex, "suggested_substitutes", [])
        has_suggested_staples = isinstance(suggested_staples, list) and bool(suggested_staples)
        prescribed_ids = {str(ex.exercise_id) for ex in target_day.exercises}
        suggestion_request = _AlternativeSuggestionRequest(
            source_id=str(matched_ex.exercise_id),
            source_name=matched_ex.exercise_name,
            source_entry=(
                source_entry
                if isinstance(source_entry, dict)
                else {"name": matched_ex.exercise_name}
            ),
            equipment_access=equipment_access,
            prescribed_ids=frozenset(prescribed_ids),
            target_muscle=target_muscle,
            body_part=body_part,
        )
        if has_suggested_staples:
            for staple in suggested_staples:
                staple_id = str(staple.exercise_id)
                if staple_id == str(matched_ex.exercise_id) or staple_id in prescribed_ids:
                    continue
                with store.catalog_locked() as conn:
                    row = conn.execute(
                        "SELECT e.id, e.name, e.equipment, e.target_muscle, e.body_part "
                        f"FROM exercises e WHERE e.id = ? AND {exercise_library_visible_sql('e.id')}",
                        (staple_id,),
                    ).fetchone()
                if not row:
                    continue
                candidate = dict(zip(("id", "name", "equipment", "target_muscle", "body_part"), row))
                if not equipment_access_allows(equipment_access, candidate["equipment"]):
                    continue
                candidate["name"] = staple.exercise_name
                valid_candidates.append(candidate)
        elif isinstance(source_entry, dict) and (
            source_entry.get("primary_action") or source_entry.get("primary_muscle")
        ):
            # Curated sources use Replace ranking; uncurated sources keep the semantic order
            # because display-name order has no movement signal for them.
            valid_candidates = _replace_ranked_alternative_candidates(
                store, suggestion_request,
            )
        else:
            valid_candidates = _similar_alternatives(
                store, suggestion_request, set(), 3
            )

        if valid_candidates:
            entries = store.get_exercise_library_entries(
                [str(candidate["id"]) for candidate in valid_candidates]
            )
            entries = entries if isinstance(entries, dict) else {}
            valid_candidates = [
                {
                    **candidate,
                    "primary_action": entries.get(str(candidate["id"]), {}).get("primary_action"),
                    "secondary_actions": entries.get(str(candidate["id"]), {}).get("secondary_actions", []),
                    "description": describe_exercise(
                        store,
                        str(candidate["id"]),
                        candidate["name"],
                        entry=entries.get(str(candidate["id"])),
                    ),
                }
                for candidate in valid_candidates
            ]

        if not valid_candidates:
            msg = f"No direct biomechanical alternatives found for **{matched_ex.exercise_name.title()}**."
            return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

        heading = "Suggested Staple substitutes" if has_suggested_staples else "Biomechanical Alternatives"
        header = f"**{heading} for {matched_ex.exercise_name.title()}** (`{target_muscle.title()}` | `{target_day.day_name}`):"
        model_header = f"**{heading} for {source_description}** (`{target_muscle.title()}` | `{target_day.day_name}`):"
        lines = [header]
        model_lines = [model_header]
        for i, c in enumerate(valid_candidates, start=1):
            cue = get_biomechanical_cue(c, experience_level)
            lines.append(f"{i}. **{c['name'].title()}** (`{c['equipment']}`)\n   *Cue:* {cue}")
            model_lines.append(f"{i}. **{c['description']}**\n   *Cue:* {cue}")
        lines.append(f"\n*To commit a swap, reply:* `swap {matched_ex.exercise_name} for [Choice]`")
        model_lines.append(f"\n*To commit a swap, reply:* `swap {matched_ex.exercise_name} for [Choice]`")
        return _response_with_model_context("\n".join(lines), "\n".join(model_lines))

    # Layer 1: deterministic catalog name resolution. An explicitly named movement must
    # resolve by name — it never silently falls through to its nearest embedding sibling.
    # Raw text is tried before abbreviation-expanded text: suffix rules like
    # "lat pulldown" → "cable lat pulldown" must not corrupt already-specific names.
    # Pronouns and ultra-short tokens ("it", "choice") are not names at all and must not
    # junk-match the substring tier ("it" → "sit-up"/"smith squat") or the embedding fallback.
    resolve_text = (
        raw_target
        if raw_target and len(raw_target) >= 3 and raw_target.lower() not in PRONOUNS
        else target_desc
    )
    target_unspecific = (
        not resolve_text or len(resolve_text) < 3 or resolve_text.lower() in PRONOUNS | UNSPECIFIC_CHOICE_WORDS
    )
    # A near-miss name (ADR 053) never resolves to its look-alike row; it refuses
    # unless the library holds the real exercise under that name or alias.
    near_miss_ids = near_miss_exercise_ids(resolve_text)

    name_matches: list[dict[str, Any]] = []
    if not target_unspecific:
        name_matches = [
            match
            for match in store.find_exercises_by_name(resolve_text)
            if str(match["id"]) != str(matched_ex.exercise_id)
            and str(match["id"]) not in near_miss_ids
        ]
        if not name_matches and resolve_text != target_desc:
            name_matches = [
                match
                for match in store.find_exercises_by_name(target_desc)
                if str(match["id"]) != str(matched_ex.exercise_id)
                and str(match["id"]) not in near_miss_ids
            ]
    if near_miss_ids and not name_matches:
        return _near_miss_refusal(store, resolve_text, near_miss_ids)
    compatible_name_match = _compatible_name_match(
        name_matches, target_muscle, body_part, target_day
    )

    replacement = None
    valid_replacements: list[dict[str, Any]] = []

    if compatible_name_match is not None:
        replacement = compatible_name_match
    elif name_matches:
        potential = _slot_alternative_lines(
            store, matched_ex, target_muscle, body_part,
            equipment_access,
        )
        rejected = name_matches[0]
        msg = (
            f"**{rejected['name'].title()}** is in the exercise database, but it targets "
            f"`{str(rejected.get('target_muscle') or 'a different muscle').title()}`, not your "
            f"`{target_muscle.title()}` slot.\n\n"
        )
        if potential:
            msg += "**Compatible alternatives for this slot:**\n" + "\n".join(potential)
            msg += f"\n\n*To select one, reply:* `swap {matched_ex.exercise_name} for [Choice]`"
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}
    else:
        # Layer 2: semantic resolution for descriptive targets (e.g. "something easier on my elbows").
        # Raw text is embedded first: abbreviation expansion may inject equipment ("lat pulldown"
        # → "cable lat pulldown") and must not corrupt an already-specific name's ranking.
        def _semantic_replacements(text: str) -> list[dict[str, Any]]:
            candidates = store.search_similar_exercises(EMBED_MODEL.embed_query(text), limit=20)
            # Pre-commit Guard: Strict confidence threshold (distance <= 0.27)
            return [
                c
                for c in candidates
                if str(c["id"]) != str(matched_ex.exercise_id)
                and equipment_access_allows(equipment_access, c.get("equipment"))
                and (
                    (
                        target_muscle
                        and (
                            target_muscle.lower() in c.get("target_muscle", "").lower()
                            or c.get("target_muscle", "").lower() in target_muscle.lower()
                        )
                    )
                    or (body_part and body_part.lower() == c.get("body_part", "").lower())
                )
                and ("distance" not in c or c["distance"] <= 0.27)
            ]

        if not target_unspecific:
            valid_replacements = _semantic_replacements(resolve_text)
            if not valid_replacements and target_desc != resolve_text:
                valid_replacements = _semantic_replacements(target_desc)

        if valid_replacements and _target_is_name_like(resolve_text, valid_replacements):
            # The player named an exercise we could not resolve — refuse rather than
            # install the closest lexical sibling.
            valid_replacements = []
        elif valid_replacements:
            replacement = valid_replacements[0]
            q_lower = query.lower()
            if "dumbbell" in q_lower or "db" in q_lower:
                db_cand = next((c for c in valid_replacements if "dumbbell" in c["name"].lower()), None)
                if db_cand:
                    replacement = db_cand
            elif "barbell" in q_lower or "bb" in q_lower:
                bb_cand = next((c for c in valid_replacements if "barbell" in c["name"].lower()), None)
                if bb_cand:
                    replacement = bb_cand
            else:
                # If tied within 0.02, prefer barbell for compound movements
                bb_cand = next((c for c in valid_replacements if "barbell" in c["name"].lower()), None)
                if bb_cand and abs(bb_cand.get("distance", 0) - replacement.get("distance", 0)) < 0.02:
                    replacement = bb_cand

    if not replacement:
        potential = _slot_alternative_lines(
            store, matched_ex, target_muscle, body_part,
            equipment_access,
        )
        msg = (
            f"Could not find a biomechanically suitable match for **'{raw_target or target_desc}'** "
            f"(I couldn't confidently identify it for your `{target_muscle.title()}` slot).\n\n"
            f"Could you provide further illustration or specify the full exercise name?"
        )
        if potential:
            msg += "\n\n**Did you mean one of these alternatives?**\n" + "\n".join(potential)
            msg += f"\n\n*To select one, reply:* `swap {matched_ex.exercise_name} for [Choice]`"
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    substitution = substitute_program_exercise(
        ledger,
        store,
        active_program,
        ProgramSubstitution(
            day_name=target_day.day_name,
            exercise_id=matched_ex.exercise_id,
            replacement_exercise_id=str(replacement["id"]),
        ),
    )
    if substitution["ok"]:
        replacement = substitution["replacement"]
        new_notes = replacement.get("instructions") or get_biomechanical_cue(
            replacement, experience_level
        )
        note_suffix = ""
        # Variants of one movement share the end of their source name ("... lateral pulldown");
        # display names end in an equipment suffix, so compare source names when known.
        installed = next((c for c in valid_replacements if str(c["id"]) == str(replacement["id"])), replacement)
        alt_variant = next(
            (c for c in valid_replacements if str(c["id"]) != str(replacement["id"]) and _movement_tail(c) == _movement_tail(installed)),
            None,
        )
        if alt_variant and ("dumbbell" not in query.lower() and "barbell" not in query.lower()):
            note_suffix = (
                f"\n\n*(Installed the primary **{replacement['equipment'].title()}** variant. "
                f"If you prefer **{alt_variant['name'].title()}**, reply: "
                f"`swap {matched_ex.exercise_name} for {alt_variant['name']}`.)*"
            )

        msg = (
            f"✅ **Routine Slot Updated ({target_day.day_name})**\n\n"
            f"- **Removed:** {matched_ex.exercise_name.title()}\n"
            f"- **Installed:** {replacement['name'].title()} (`{replacement['target_muscle']}` | `{replacement['equipment']}`)\n"
            f"- **Execution Directive:** *{new_notes}*{note_suffix}"
        )
        return {
            "program_updated": True,
            "program_change": "swapped",
            "response_content": msg,
            "messages": [AIMessage(content=msg)],
        }

    msg = substitution["error"]
    return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}


def _program_mutation_frequency(
    query: str, metadata: dict[str, Any]
) -> tuple[int | None, str | None]:
    arabic_data_validated = metadata.get("arabic_data_validated") is True
    requested = _extract_frequency(query)
    supplied = metadata.get("target_frequency")
    if arabic_data_validated and requested is not None and requested != supplied:
        return None, ARABIC_PROGRAM_CHANGE_CLARIFICATION_RESPONSE
    for frequency in (requested, supplied):
        if frequency is not None and (type(frequency) is not int or not 1 <= frequency <= 5):
            response = (
                ARABIC_PROGRAM_CHANGE_CLARIFICATION_RESPONSE
                if arabic_data_validated
                else "Training frequency must be 1–5 days per week (max 5 days). Please choose a supported frequency."
            )
            return None, response
    frequency = supplied if arabic_data_validated else (requested if requested is not None else supplied)
    return frequency, None


def _program_mutation_confirmation(
    program: Any, query: str, state: AssistantState
) -> str:
    if resolve_reply_language(query, state.get("display_language", "en")) == "ar":
        frequency_label = _arabic_frequency_label(program.weekly_frequency)
        return f"تمام، ظبطتلك البرنامج التدريبي على {frequency_label}: {program.program_name}."
    return f"Rebuilt routine: **{program.program_name}** ({program.weekly_frequency} Days/Week). Context cleared for new routine."


def _program_mutation_result(
    program: Any, query: str, state: AssistantState
) -> dict[str, Any]:
    response = _program_mutation_confirmation(program, query, state)
    return {
        "program_updated": True,
        "program_change": "regenerated",
        "response_content": response,
        "messages": [AIMessage(content=response)],
    }


def _run_program_mutation(
    state: AssistantState, ledger: Any, frequency: int | None
) -> dict[str, Any]:
    query = _get_message_text(state["messages"][-1])
    metadata = state.get("intent_metadata", {})
    arabic_data_validated = metadata.get("arabic_data_validated") is True
    split_preference = metadata.get("split_family") if arabic_data_validated else query
    try:
        prog, _ = generate_program_pipeline(
            user_split_override=split_preference,
            frequency_override=frequency,
            ledger=ledger,
        )
        # Intentional fresh-start: a rebuilt split invalidates routine-specific dialogue context.
        ledger.clear_chat_history()
    except Exception as e:
        logger.error(f"Mutation failure: {e}")
        failure = "Could not rebuild split with those parameters."
        return {"program_updated": False, "response_content": failure, "messages": [AIMessage(content=failure)]}
    return _program_mutation_result(prog, query, state)


def program_mutation_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    query = _get_message_text(state["messages"][-1])
    metadata = state.get("intent_metadata", {})
    if metadata.get("arabic_data_validated") is not True and not _authorized_action(query, "program_mutation"):
        return _response(AUTHORIZATION_RESPONSE)
    if not programs_service.player_controls_program(store, ledger, state.get("player_account_id")):
        suggestion = _split_change_request_suggestion(query, metadata)
        return _response(_coach_program_refusal(query), request_suggestion=suggestion)
    frequency, issue = _program_mutation_frequency(query, metadata)
    if issue:
        return _response(issue)
    return _run_program_mutation(state, ledger, frequency)


def deload_choice_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger, store = _graph_context(config)
    choice = (state.get("intent_metadata") or {}).get("choice")
    query = _get_message_text(state["messages"][-1]) if state.get("messages") else ""
    language = resolve_reply_language(query, state.get("display_language", "en"))
    no_change_response = (
        "مفيش حاجة محتاجة تغيير." if language == "ar" else DELOAD_NO_CHANGE_RESPONSE
    )
    if choice not in DELOAD_CHOICES:
        return _response(no_change_response)
    program = ledger.get_active_program()
    if program is None or not program.days:
        return _response(no_change_response)
    from service import workouts as workouts_service

    prescription = workouts_service.build_prescription(
        store, str(state.get("trainee_id", ledger.ledger_id)), program.days[0],
        ledger=ledger, player_account_id=state.get("player_account_id"),
    )
    deload = prescription["deload"]
    accepted_state = "applied" if choice == DELOAD_CHOICE_UNDO else "suggested"
    if deload["state"] != accepted_state:
        return _response(no_change_response)

    ledger.set_deload_choice(choice)
    reason = deload.get("reason") or "fatigue was detected"
    fatigue_info = prescription.get("fatigue_info") or {}
    reason_code = fatigue_info.get("reason_code")
    response = _deload_choice_copy(choice, reason, reason_code, language)

    account_id = state.get("player_account_id")
    if account_id:
        try:
            from service.progression_alerts import note_player_deload_choice

            note_player_deload_choice(store, account_id, choice)
        except Exception:
            logger.exception("Could not add player deload choice to coach alert")
    return _response(response, program_updated=True)


_ARABIC_DELOAD_REASON_COPY = {
    "acute_readiness_floor": "انخفاض حاد في الاستعداد (1/5 مسجل). التعافي العام متأثر.",
    "rolling_readiness_crash": "انخفاض مستمر في الاستعداد خلال آخر 3 حصص.",
    "high_exertion_density": "مجهود عالي في السيتات المسجلة عند RIR 0.5 أو أقل، مع انخفاض الاستعداد.",
}


def _localized_deload_reason(reason_code: str | None, reason: str) -> str:
    copy = _ARABIC_DELOAD_REASON_COPY.get(reason_code or "")
    if copy is None:
        return "غير محددة."
    if reason_code == "rolling_readiness_crash":
        match = re.search(r"avg (\d+(?:\.\d+)?)/5", reason)
        if match:
            return f"انخفاض مستمر في الاستعداد (متوسط {match.group(1)}/5 خلال آخر 3 حصص)."
    elif reason_code == "high_exertion_density":
        match = re.search(r"\((\d+)% of recent rated sets", reason)
        if match:
            return (
                f"مجهود عالي في {match.group(1)}% من السيتات المسجلة عند RIR 0.5 أو أقل، "
                "مع انخفاض الاستعداد."
            )
    return copy


def _deload_choice_copy(
    choice: str,
    reason: str,
    reason_code: str | None,
    language: DisplayLanguage,
) -> str:
    if language == "ar":
        action = "ألغيت" if choice == DELOAD_CHOICE_UNDO else "طبّقت"
        localized_reason = _localized_deload_reason(reason_code, reason)
        return f"تمام، {action} تخفيف التدريب للحصة الجاية بس. إشارة الإرهاق: {localized_reason}"
    default = "applied" if choice == DELOAD_CHOICE_UNDO else "suggested"
    return (
        f"I’ll {choice} the {default} deload for your next workout only. "
        f"The fatigue signal is: {reason}"
    )


def catalog_search_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    _, store = _graph_context(config)
    query = state.get("intent_metadata", {}).get("search_query") or _get_message_text(state["messages"][-1])
    try:
        candidates, from_name_search = _catalog_search_candidates(store, query)
        if not _catalog_search_has_matches(query, candidates, from_name_search):
            msg = f"No exercises matching '{query}' were found in the catalog."
            return {"response_content": msg, "messages": [AIMessage(content=msg)]}
        return _catalog_search_response(query, candidates)
    except Exception as e:
        logger.error(f"Catalog search error: {e}")
        return {"response_content": "Failed to search the exercise catalog.", "messages": [AIMessage(content="Failed to search the exercise catalog.")]}


def _catalog_search_candidates(store: Any, query: str) -> tuple[list[dict[str, Any]], bool]:
    if near_miss_exercise_ids(query):
        return [], True
    name_matches = store.find_exercises_by_name(query, limit=4)
    candidates = _library_search_details(store, name_matches)
    if candidates:
        return candidates, True
    similar = store.search_similar_exercises(EMBED_MODEL.embed_query(query), limit=4)
    return _library_search_details(store, similar), False


def _catalog_search_has_matches(
    query: str, candidates: list[dict[str, Any]], from_name_search: bool
) -> bool:
    if not candidates:
        return False
    if from_name_search:
        return True
    return not _target_is_name_like(query, candidates) and candidates[0].get("distance", 1.0) <= 0.85


def _catalog_search_response(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    player_lines = [
        f"- **{candidate['name'].title()}** (`{candidate['target_muscle']}` | "
        f"`{candidate['equipment']}`)\n  *{candidate['instructions'][:120]}...*"
        for candidate in candidates
    ]
    model_lines = [
        f"- **{candidate['description']}** (`{candidate['target_muscle']}` | "
        f"`{candidate['equipment']}`)\n  *{candidate['instructions'][:120]}...*"
        for candidate in candidates
    ]
    heading = f"**Catalog Matches for '{query}':**\n\n"
    return _response_with_model_context(
        heading + "\n\n".join(player_lines),
        heading + "\n\n".join(model_lines),
    )


def _library_search_details(store: Any, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = store.get_exercise_library_entries([str(match["id"]) for match in matches])
    entries = entries if isinstance(entries, dict) else {}
    candidates = []
    for match in matches:
        exercise = entries.get(str(match["id"]))
        if exercise is not None:
            candidates.append(
                {
                    **match,
                    "description": describe_exercise(
                        store, str(match["id"]), match["name"], entry=exercise
                    ),
                    "instructions": exercise["instructions"] or "",
                }
            )
    return candidates


def _count_display_tokens(text: str) -> int:
    """Estimate displayed tokens from text length for telemetry."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def build_prompt_payload(state: Dict[str, Any]) -> list[BaseMessage]:
    return build_player_chat_prompt(
        state,
        prompt_token_count=_prompt_token_count,
        prompt_budget=_prompt_budget,
    )


def _response(
    content: str,
    program_updated: bool = False,
    request_suggestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned = finalize_coach_output(content)
    return {
        "response_content": cleaned,
        "program_updated": program_updated,
        "request_suggestion": request_suggestion,
        "messages": [AIMessage(content=cleaned)],
    }


def _response_with_model_context(content: str, model_context_content: str) -> dict[str, Any]:
    """Keep player text clean while retaining a fact-rich internal model context."""
    return {**_response(content), "model_context_content": model_context_content}


def _finish_limited(message: Any) -> bool:
    metadata = getattr(message, "response_metadata", {}) or {}
    info = getattr(message, "generation_info", {}) or {}
    return any(m.get("finish_reason") in {"length", "max_tokens"} or m.get("stop_reason") == "max_tokens" for m in (metadata, info))


def generation_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = build_prompt_payload(state)
        response = llm.invoke(payload)
        content = finalize_coach_output(response.content)
        if _finish_limited(response):
            content += "\n\n" + OUTPUT_LIMIT_RESPONSE
        return {"response_content": content, "program_updated": False, "messages": [AIMessage(content=content)]}
    except PromptBudgetError as exc:
        return _response(str(exc))
    except Exception:
        logger.exception("Assistant generation failed")
        return _response(PIPELINE_ERROR_RESPONSE)


def composite_intent_node(state: AssistantState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    arabic_swap = meta.get("arabic_validated_swap")
    if isinstance(arabic_swap, dict):
        return _apply_validated_swap(state, config, arabic_swap)

    sub_intents = meta.get("sub_intents") or state.get("active_intents") or []
    original_msgs = list(state.get("messages", []))
    original_query = meta.get("raw_query") or (_get_message_text(original_msgs[-1]) if original_msgs else "")
    clinical = _clinical_turn_metadata(original_query, sub_intents)
    if clinical is not None:
        return clinical_intercept_node({**state, "intent_metadata": clinical}, config)
    if not sub_intents:
        return generation_node(state, config)

    responses = []
    preceding = []
    veto_pending = False
    any_program_updated = False
    program_change = None
    request_suggestion = None

    handler_map = {
        "clinical_intercept": clinical_intercept_node,
        "banned_movement": banned_movement_node,
        "telemetry_intercept": telemetry_intercept_node,
        "exercise_history": exercise_history_node,
        "exercise_substitution": exercise_substitution_node,
        "program_mutation": program_mutation_node,
        "deload_choice": deload_choice_node,
        "catalog_search": catalog_search_node,
        "coaching_qa": generation_node,
    }

    for sub in sub_intents:
        sub_intent = sub.get("intent", "coaching_qa")
        sub_query = sub.get("query") or _get_message_text(state["messages"][-1])
        if veto_pending and sub_intent == "coaching_qa" and _redundant_veto_followup(sub_query):
            continue
        handler = handler_map.get(sub_intent, generation_node)

        sub_state: AssistantState = dict(state)
        sub_state["intent"] = sub_intent
        sub_state["intent_metadata"] = {**(sub.get("intent_metadata") or {}), "original_query": original_query}
        sub_state["messages"] = original_msgs + preceding + [HumanMessage(content=sub_query)]
        veto_pending = sub_intent == "banned_movement"

        try:
            res = handler(sub_state, config)
            if res.get("program_updated"):
                any_program_updated = True
                program_change = res.get("program_change", program_change)
            if request_suggestion is None:
                request_suggestion = res.get("request_suggestion")
            content = res.get("response_content", "")
            if content and content.strip():
                responses.append(content.strip())
                model_context = res.get("model_context_content", content)
                preceding.extend(
                    [HumanMessage(content=sub_query), AIMessage(content=str(model_context).strip())]
                )
        except Exception as e:
            logger.error(f"Error handling sub-intent {sub_intent}: {e}")
            responses.append(f"Could not complete action for: '{sub_query}'.")

    combined_response = "\n\n---\n\n".join(responses) if responses else "Actions processed."
    return {
        "program_updated": any_program_updated,
        "program_change": program_change,
        "request_suggestion": request_suggestion,
        "response_content": combined_response,
        "messages": [AIMessage(content=combined_response)],
    }


def _safe_node(handler):
    def run(state, config=None):
        try:
            result = handler(state, config)
            if "response_content" in result and handler is not generation_node:
                return {
                    **result,
                    **_response(
                        result.get("response_content") or "",
                        result.get("program_updated", False),
                        result.get("request_suggestion"),
                    ),
                }
            return result
        except Exception:
            logger.exception("Assistant node failed: %s", handler.__name__)
            if handler is hydrate_context_node:
                return {"pipeline_error": PIPELINE_ERROR_RESPONSE}
            if handler is router_node:
                return {"intent": "telemetry_intercept", "intent_metadata": {"response_content": PIPELINE_ERROR_RESPONSE}}
            return _response(PIPELINE_ERROR_RESPONSE)
    return run


# StateGraph Assembly
builder = StateGraph(AssistantState)
builder.add_node("hydrate_context", _safe_node(hydrate_context_node))
builder.add_node("router", _safe_node(router_node))
builder.add_node("clinical_intercept", _safe_node(clinical_intercept_node))
builder.add_node("banned_movement", _safe_node(banned_movement_node))
builder.add_node("telemetry_intercept", _safe_node(telemetry_intercept_node))
builder.add_node("exercise_history", _safe_node(exercise_history_node))
builder.add_node("exercise_substitution", _safe_node(exercise_substitution_node))
builder.add_node("arabic_swap_clarification", _safe_node(arabic_swap_clarification_node))
builder.add_node("program_mutation", _safe_node(program_mutation_node))
builder.add_node("deload_choice", _safe_node(deload_choice_node))
builder.add_node("catalog_search", _safe_node(catalog_search_node))
builder.add_node("composite_intent", _safe_node(composite_intent_node))
builder.add_node("generation", _safe_node(generation_node))

builder.set_entry_point("hydrate_context")
builder.add_edge("hydrate_context", "router")

builder.add_conditional_edges(
    "router",
    lambda state: state.get("intent", "coaching_qa"),
    {
        "clinical_intercept": "clinical_intercept",
        "banned_movement": "banned_movement",
        "telemetry_intercept": "telemetry_intercept",
        "exercise_history": "exercise_history",
        "exercise_substitution": "exercise_substitution",
        "arabic_swap_clarification": "arabic_swap_clarification",
        "program_mutation": "program_mutation",
        "deload_choice": "deload_choice",
        "catalog_search": "catalog_search",
        "composite_intent": "composite_intent",
        "coaching_qa": "generation",
    },
)

for node in [
    "clinical_intercept", "banned_movement", "telemetry_intercept",
    "exercise_substitution", "arabic_swap_clarification", "program_mutation",
    "catalog_search", "composite_intent", "generation",
]:
    builder.add_edge(node, END)

builder.add_conditional_edges(
    "exercise_history",
    lambda state: "generation" if state.get("intent") == "exercise_history_fallback" else END,
    {"generation": "generation", END: END},
)

assistant_graph = builder.compile()

# Telemetry Logging & Stream Interface
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "myos.log"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_telemetry_handler() -> logging.FileHandler:
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == LOG_FILE.resolve():
            return handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    return fh


_telemetry_handler = _get_telemetry_handler()


def _stream_text_smoothly(text: str, delay: float = 0.035) -> Generator[str, None, None]:
    words = text.split(" ")
    for i, word in enumerate(words):
        yield word + (" " if i < len(words) - 1 else "")
        time.sleep(delay)


def _record_telemetry_event(
    intent: str,
    fast_path_ms: float,
    ttft_ms: float = 0.0,
    gen_time_s: float = 0.0,
    tokens: int = 0,
    tps: float = 0.0,
    user_id: str = "default",
) -> None:
    log_payload = (
        f"[TELEMETRY] User: {user_id} | Intent: {intent} | "
        f"Router: {fast_path_ms:.3f}ms | TTFT: {ttft_ms:.1f}ms | "
        f"Tokens: {tokens} | GenTime: {gen_time_s:.2f}s | Speed: {tps:.2f} TPS"
    )
    logger.info(log_payload)
    _telemetry_handler.flush()


def stream_assistant_turn(
    state: dict[str, Any], *, ledger: Any, store: Any
) -> Generator[str, None, None]:
    """Streams one assistant turn against the caller-owned ledger handle.

    The graph never reads a thread-local mount: the ledger (and the app store,
    when exercise-library lookups are needed) travel on the LangGraph ``config``
    so they stay out of the persisted/serialised state.
    """
    config = {"configurable": {"ledger": ledger, "store": store}}
    t_start = time.perf_counter()
    original_messages = list(state.get("messages", []))
    result = None
    visible = []
    scrubber = None
    try:
        state.update(hydrate_context_node(state, config))
        state.update(router_node(state, config))
        intent = state.get("intent", "coaching_qa")
        router_ms = (time.perf_counter() - t_start) * 1000.0
        handlers = {
            "telemetry_intercept": telemetry_intercept_node,
            "clinical_intercept": clinical_intercept_node,
            "banned_movement": banned_movement_node,
            "exercise_substitution": exercise_substitution_node,
            "arabic_swap_clarification": arabic_swap_clarification_node,
            "program_mutation": program_mutation_node,
            "deload_choice": deload_choice_node,
            "catalog_search": catalog_search_node,
            "composite_intent": composite_intent_node,
        }
        if intent == "exercise_history":
            result = exercise_history_node(state, config)
            if result.get("intent") == "exercise_history_fallback":
                arabic_history = (state.get("intent_metadata") or {}).get("arabic_history") is True
                state.update({key: value for key, value in result.items() if key != "intent"})
                intent = "exercise_history_fallback"
                # Arabic history still uses generated answers; fallback is only the answer path.
                if not arabic_history:
                    state["intent"] = intent
                result = None
        if result is not None:
            telemetry = {}
        elif intent in handlers:
            result = handlers[intent](state, config)
            telemetry = {}
        else:
            payload = build_prompt_payload(state)
            scrubber = CoachOutputScrubber()
            limited = False
            contract_warned = False
            raw_pieces: list[str] = []
            gen_start = time.perf_counter()
            ttft_s = 0.0
            for chunk in llm.stream(payload):
                if ttft_s == 0.0:
                    ttft_s = time.perf_counter() - gen_start
                limited = limited or _finish_limited(chunk)
                if not hasattr(chunk, "content") and not contract_warned:
                    logger.warning("LLM stream chunk %s lacks .content; coercing via str().", type(chunk).__name__)
                    contract_warned = True
                piece = chunk.content if hasattr(chunk, "content") else str(chunk)
                raw_pieces.append(str(piece))
                for char in piece:
                    cleaned = scrubber.feed(char)
                    if cleaned:
                        visible.append(cleaned)
                        yield cleaned
            cleaned = scrubber.finish()
            if cleaned:
                visible.append(cleaned)
                yield cleaned
            if not visible:
                visible.append(EMPTY_RESPONSE_FALLBACK)
                yield EMPTY_RESPONSE_FALLBACK
            if limited:
                note = "\n\n" + OUTPUT_LIMIT_RESPONSE
                visible.append(note)
                yield note
            gen_time_s = max(0.0, (time.perf_counter() - gen_start) - ttft_s)
            tokens = _count_display_tokens("".join(raw_pieces))
            tps = tokens / gen_time_s if gen_time_s > 0 else 0.0
            telemetry = {"ttft_ms": ttft_s * 1000.0, "gen_time_s": gen_time_s, "tokens": tokens, "tps": tps}
            if tokens and gen_time_s >= 0.5 and tps < 8.0:
                logger.warning(
                    "[PERF DEGRADATION] Low inference throughput detected: %.2f TPS (Threshold: 8.0 TPS). "
                    "Check CPU temperature or background processes.",
                    tps,
                )
        _record_telemetry_event(intent, router_ms, user_id=state.get("trainee_id", "default"), **telemetry)
    except PromptBudgetError as exc:
        result = _response(str(exc))
    except Exception:
        logger.exception("Assistant turn failed")
        if scrubber is not None:
            cleaned = scrubber.finish()
            if cleaned:
                visible.append(cleaned)
                yield cleaned
        result = _response(PIPELINE_ERROR_RESPONSE, bool(result and result.get("program_updated")))
    if result is not None:
        cleaned = finalize_coach_output(result.get("response_content") or "")
        piece = ("\n\n" if visible else "") + cleaned
        visible.append(piece)
        yield piece
    content = "".join(visible)
    state.update(
        response_content=content,
        program_updated=bool(result and result.get("program_updated")),
        program_change=result.get("program_change") if result else None,
        request_suggestion=result.get("request_suggestion") if result else None,
    )
    state["messages"] = original_messages + [AIMessage(content=content)]
