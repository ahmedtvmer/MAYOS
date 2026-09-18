# agent/fitness_abbreviations.py
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from utils.logger import MyosLogger
from utils.model_downloader import llm

logger = MyosLogger().get_logger(__name__)

# Canonical mapping of fitness abbreviations and gym acronyms to catalog exercise stems
FITNESS_ABBREVIATIONS: dict[str, str] = {
    # Hinges / Deadlifts
    "rdls": "romanian deadlift",
    "rdl": "romanian deadlift",
    "sldls": "stiff leg deadlift",
    "sldl": "stiff leg deadlift",
    "deadlifts": "deadlift",
    "deadlift": "deadlift",
    "dls": "deadlift",
    "dl": "deadlift",
    "sumo dl": "barbell sumo deadlift",
    "ghr": "glute ham raise",
    "ghrs": "glute ham raise",
    # Presses / Shoulders / Triceps
    "ohp": "overhead press",
    "cgbp": "close grip bench press",
    "bp": "bench press",
    "jm press": "barbell jm press",
    "jm": "barbell jm press",
    "hspu": "handstand push up",
    "skull crushers": "lying triceps extension skull crusher",
    "skullcrushers": "lying triceps extension skull crusher",
    "skull crusher": "lying triceps extension skull crusher",
    "skullcrusher": "lying triceps extension skull crusher",
    "dips": "chest dip",
    # Squats / Lower Body
    "bss": "single leg split squat",
    "bulgarian split squat": "single leg split squat",
    "bulgarian split squats": "single leg split squat",
    "fs": "front squat",
    "bs": "back squat",
    "ssb": "safety squat bar squat",
    "ssb squat": "safety squat bar squat",
    "hip thrusts": "barbell hip thrust",
    "hip thrust": "barbell hip thrust",
    # Pulls / Back / Biceps
    "lat pulldowns": "cable lat pulldown",
    "lat pulldown": "cable lat pulldown",
    "pullups": "assisted standing pull-up",
    "pull ups": "assisted standing pull-up",
    "chinups": "chin-up",
    "chin ups": "chin-up",
    "preacher": "dumbbell preacher curl",
    "preacher curls": "dumbbell preacher curl",
    "preacher curl": "dumbbell preacher curl",
    "face pulls": "cable face pull",
    "face pull": "cable face pull",
    # Equipment shorthand
    "db": "dumbbell",
    "bb": "barbell",
    "kb": "kettlebell",
    "bw": "bodyweight",
    "sm": "smith machine",
    "smith machine": "smith machine",
    "ez bar": "ez bar",
    "ez-bar": "ez bar",
    "ez": "ez bar",
    # Grip / Stance
    "cg": "close grip",
    "wg": "wide grip",
    "ng": "neutral grip",
}

# Compile sorted pattern (longest first) with word boundaries
_SORTED_KEYS = sorted(FITNESS_ABBREVIATIONS.keys(), key=len, reverse=True)
_ABBREV_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SORTED_KEYS) + r")\b",
    re.IGNORECASE,
)


def expand_fitness_abbreviations(text: str) -> str:
    """Expands fitness acronyms, abbreviations, and gym slang into canonical movement names."""
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        word = match.group(0).lower()
        return FITNESS_ABBREVIATIONS.get(word, word)

    expanded = _ABBREV_PATTERN.sub(_replace, text)
    # Clean redundant multi-spaces
    return re.sub(r"\s+", " ", expanded).strip()


class AbbreviationExpansion(BaseModel):
    is_fitness_movement: bool = Field(description="True if this acronym/abbreviation refers to a gym exercise")
    canonical_name: Optional[str] = Field(
        default=None,
        description="The full expanded exercise name (e.g. 'Romanian Deadlift' for 'RDL'), or None if unknown",
    )


def resolve_unknown_abbreviation_with_llm(token: str) -> Optional[str]:
    """Uses LLM structured resolution as a fallback for novel or unusual fitness acronyms."""
    clean_token = token.strip()
    # Only attempt LLM fallback if token looks like an acronym or short shorthand (2 to 6 characters)
    if not re.fullmatch(r"[a-zA-Z]{2,6}", clean_token):
        return None

    prompt = (
        "You are an expert strength and conditioning biomechanics engine.\n"
        "A trainee provided an abbreviation for an exercise.\n"
        "Identify if this is a known gym exercise abbreviation (e.g., 'SLDL' -> 'Stiff Leg Deadlift', 'GHR' -> 'Glute Ham Raise').\n"
        "If it is a real gym movement, return canonical_name. If it is gibberish, non-fitness, or ambiguous, return is_fitness_movement=False."
    )
    try:
        structured_llm = llm.with_structured_output(AbbreviationExpansion)
        res: AbbreviationExpansion = structured_llm.invoke(
            [SystemMessage(content=prompt), HumanMessage(content=f"Abbreviation: '{clean_token}'")]
        )
        if res.is_fitness_movement and res.canonical_name:
            return res.canonical_name.lower().strip()
        return None
    except Exception as e:
        logger.warning(f"LLM abbreviation fallback failed for '{token}': {e}")
        return None

