import re
from typing import Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from database.database_manager import DatabaseManager
from utils.logger import MyosLogger
from utils.model_downloader import llm

load_dotenv()
logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()

STEP_PROMPTS: dict[int, str] = {
    1: (
        "Welcome to Myos. Let's set up your profile.\n\n"
        "1. Who is taller/longer: your upper body or lower body?\n"
        "2. What is your gender (male/female), age, weight (kg), and height (cm)?"
    ),
    2: (
        "Got it. Next up: goals and volume capacity.\n\n"
        "3. What is your current primary goal?\n"
        "4. What is your long-term goal?\n"
        "5. How many days per week can you realistically commit (1–5)?\n"
        "6. What is your training age (how many years of lifting)?"
    ),
    3: (
        "Last section: logistics and recovery.\n\n"
        "7. What equipment do you have access to?\n"
        "8. Do you have any injuries or joint issues?\n"
        "9. How is your job/daily stress and average sleep quality?"
    ),
}

WORDS_TO_INT = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

STEP1_SEGMENT_RE = re.compile(
    r"(?:^|[,\.;\s])1(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q1>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))2(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q2>.*)$",
    re.IGNORECASE | re.DOTALL,
)

STEP2_SEGMENT_RE = re.compile(
    r"(?:^|[,\.;\s])3(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q3>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))4(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q4>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))5(?:[:\.\-\)]|\s+|(?=[a-zA-Z]|\d))\s*(?P<q5>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))6(?:[:\.\-\)]|\s+|(?=[a-zA-Z]|\d))\s*(?P<q6>.*)$",
    re.IGNORECASE | re.DOTALL,
)

STEP3_SEGMENT_RE = re.compile(
    r"(?:^|[,\.;\s])7(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q7>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))8(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q8>.*?)"
    r"(?:[,\.;\s]+|(?<=[a-zA-Z]))9(?:[:\.\-\)]|\s+|(?=[a-zA-Z]))\s*(?P<q9>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_number_token(text: str) -> float | None:
    t = text.lower().strip()
    for word, val in WORDS_TO_INT.items():
        if re.search(rf"\b{word}\b", t):
            return float(val)
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


class Step1Extraction(BaseModel):
    is_off_topic: bool = Field(default=False)
    proportions: Literal["long_legs", "long_torso", "balanced"] | None = None
    gender: Literal["male", "female"] | None = None
    age: int | None = None
    weight_kg: float | None = None
    height_cm: float | None = None


class Step2Extraction(BaseModel):
    is_off_topic: bool = Field(default=False)
    current_goal: str | None = None
    long_term_goal: str | None = None
    weekly_frequency: int | None = None
    training_age_years: float | None = None
    rep_preference: Literal["low", "balanced", "high"] | None = "balanced"


class Step3Extraction(BaseModel):
    is_off_topic: bool = Field(default=False)
    equipment_access: str | None = None
    injuries_or_limitations: str | None = None
    stress_and_sleep: str | None = None


class OnboardingGraphState(TypedDict):
    messages: list[BaseMessage]
    trainee_id: str | None
    intake_step: int
    is_complete: bool
    profile_data: dict[str, Any] | None


step1_extractor = llm.with_structured_output(Step1Extraction)
step2_extractor = llm.with_structured_output(Step2Extraction)
step3_extractor = llm.with_structured_output(Step3Extraction)


def _reject(step: int, reason: str, profile: dict) -> dict[str, Any]:
    return {
        "messages": [
            AIMessage(
                content=f"⚠️ **Invalid response:** {reason}\n\nPlease provide valid data for the following:\n\n{STEP_PROMPTS[step]}"
            )
        ],
        "intake_step": step,
        "is_complete": False,
        "profile_data": profile,
    }


def _advance(next_step: int, profile: dict) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content=STEP_PROMPTS[next_step])],
        "intake_step": next_step,
        "is_complete": False,
        "profile_data": profile,
    }


def intake_node(state: OnboardingGraphState) -> dict[str, Any]:
    messages = state.get("messages", [])
    step = state.get("intake_step", 1)
    profile = dict(state.get("profile_data") or {})

    if not messages:
        return {
            "messages": [AIMessage(content=STEP_PROMPTS[1])],
            "intake_step": 1,
            "is_complete": False,
            "profile_data": profile,
        }

    raw_input = messages[-1].content.strip()

    if step == 1:
        seg_match = STEP1_SEGMENT_RE.search(raw_input)
        proportions, gender, age, weight_kg, height_cm = None, None, None, None, None
        is_off_topic = False

        if seg_match:
            q1_text, q2_text = seg_match.group("q1").lower(), seg_match.group("q2").lower()
            if "lower" in q1_text or "leg" in q1_text:
                proportions = "long_legs"
            elif "upper" in q1_text or "torso" in q1_text:
                proportions = "long_torso"
            elif any(k in q1_text for k in ["balanced", "equal", "same"]):
                proportions = "balanced"

            if "female" in q2_text or "woman" in q2_text:
                gender = "female"
            elif "male" in q2_text or "man" in q2_text:
                gender = "male"

            w_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilos?)\b", q2_text)
            if w_match:
                weight_kg = float(w_match.group(1))

            h_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", q2_text)
            if h_match:
                height_cm = float(h_match.group(1))

            a_match = re.search(r"\b(1[2-9]|[2-9]\d)\s*(?:years?|yrs?|yo)\b", q2_text)
            if a_match:
                age = int(a_match.group(1))

            all_nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", q2_text)]
            claimed = {n for n in [weight_kg, height_cm, float(age) if age else None] if n is not None}
            unclaimed = [n for n in all_nums if n not in claimed]

            if height_cm is None:
                for n in unclaimed:
                    if 100.0 <= n <= 250.0:
                        height_cm = n
                        unclaimed.remove(n)
                        break
            if weight_kg is None:
                for n in unclaimed:
                    if 30.0 <= n <= 250.0:
                        weight_kg = n
                        unclaimed.remove(n)
                        break
            if age is None:
                for n in unclaimed:
                    if 12 <= n <= 100:
                        age = int(n)
                        break
        else:
            ext: Step1Extraction = step1_extractor.invoke(f'Extract Step 1 biometrics:\n"{raw_input}"')
            is_off_topic = ext.is_off_topic
            proportions, gender, age, weight_kg, height_cm = (
                ext.proportions,
                ext.gender,
                ext.age,
                ext.weight_kg,
                ext.height_cm,
            )

        if is_off_topic:
            return _reject(
                step, "Input is off-topic. Please provide your proportion comparison and biometrics.", profile
            )

        missing = []
        if not proportions:
            missing.append("upper body vs lower body comparison")
        if not gender:
            missing.append("gender")
        if age is None or not (12 <= age <= 100):
            missing.append("age (between 12 and 100)")
        if weight_kg is None or not (30.0 <= weight_kg <= 300.0):
            missing.append("weight (between 30 and 300 kg)")
        if height_cm is None or not (100.0 <= height_cm <= 250.0):
            missing.append("height (between 100 and 250 cm)")

        if missing:
            return _reject(
                step, f"Incomplete or invalid biometrics: Please provide valid {', '.join(missing)}.", profile
            )

        profile.update(
            {"proportions": proportions, "gender": gender, "age": age, "weight_kg": weight_kg, "height_cm": height_cm}
        )
        return _advance(step + 1, profile)

    elif step == 2:
        seg_match = STEP2_SEGMENT_RE.search(raw_input)
        current_goal, long_term_goal, weekly_frequency, training_age_years = None, None, None, None
        rep_pref = "balanced"
        is_off_topic = False

        if seg_match:
            current_goal = seg_match.group("q3").strip()
            long_term_goal = seg_match.group("q4").strip()
            raw_freq = parse_number_token(seg_match.group("q5"))
            if raw_freq is not None:
                weekly_frequency = int(raw_freq)
            raw_age = parse_number_token(seg_match.group("q6"))
            if raw_age is not None:
                training_age_years = float(raw_age)
        else:
            ext: Step2Extraction = step2_extractor.invoke(f'Extract Step 2 goals and capacity:\n"{raw_input}"')
            is_off_topic = ext.is_off_topic
            current_goal, long_term_goal = ext.current_goal, ext.long_term_goal
            weekly_frequency, training_age_years = ext.weekly_frequency, ext.training_age_years
            rep_pref = ext.rep_preference or "balanced"

        if is_off_topic:
            return _reject(step, "Input is off-topic. Please answer the goals and volume questions.", profile)

        missing = []
        if not current_goal or len(current_goal.strip()) < 2:
            missing.append("current primary goal")
        if not long_term_goal or len(long_term_goal.strip()) < 2:
            missing.append("long-term goal")
        if weekly_frequency is None or not (1 <= weekly_frequency <= 5):
            missing.append("weekly frequency (must be strictly between 1 and 5 days)")
        if training_age_years is None or not (0.0 <= training_age_years <= 70.0):
            missing.append("training age (years of lifting)")

        if missing:
            return _reject(step, f"Invalid or missing details: {', '.join(missing)}.", profile)

        profile.update(
            {
                "current_goal": current_goal.strip(),
                "long_term_goal": long_term_goal.strip(),
                "weekly_frequency": weekly_frequency,
                "training_age_years": training_age_years,
                "rep_preference": rep_pref,
            }
        )
        return _advance(step + 1, profile)

    else:
        seg_match = STEP3_SEGMENT_RE.search(raw_input)
        equipment, injuries, recovery = None, None, None
        is_off_topic = False

        if seg_match:
            equipment, injuries, recovery = (
                seg_match.group("q7").strip(),
                seg_match.group("q8").strip(),
                seg_match.group("q9").strip(),
            )
        else:
            ext: Step3Extraction = step3_extractor.invoke(f'Extract Step 3 logistics:\n"{raw_input}"')
            is_off_topic = ext.is_off_topic
            equipment, injuries, recovery = ext.equipment_access, ext.injuries_or_limitations, ext.stress_and_sleep

        if is_off_topic:
            return _reject(step, "Input is off-topic. Please answer the logistics questions.", profile)

        missing = []
        if not equipment or len(equipment.strip()) < 2:
            missing.append("equipment access")
        if not injuries or len(injuries.strip()) < 2:
            missing.append("injuries/limitations")
        if not recovery or len(recovery.strip()) < 2:
            missing.append("stress and sleep quality")

        if missing:
            return _reject(step, f"Incomplete logistics: Please provide {', '.join(missing)}.", profile)

        profile.update(
            {
                "equipment_access": equipment.strip(),
                "injuries_or_limitations": injuries.strip(),
                "stress_and_sleep": recovery.strip(),
            }
        )

        trainee = state.get("trainee_id") or db.active_user or "default"
        db.switch_user(trainee)
        profile.setdefault("coach_tone", "Direct, grounded, and pragmatic")
        profile.setdefault("custom_instructions", "")
        db.upsert_user_profile(profile)

        return {
            "messages": [
                AIMessage(
                    content=f"Profile setup complete ({profile.get('gender', 'male').capitalize()} specialization active). Calibrating program..."
                )
            ],
            "intake_step": 3,
            "is_complete": True,
            "profile_data": profile,
        }


builder = StateGraph(OnboardingGraphState)
builder.add_node("intake_processor", intake_node)
builder.set_entry_point("intake_processor")
builder.add_edge("intake_processor", END)
onboarding_graph = builder.compile()
