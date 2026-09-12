# agent/onboarding_graph.py
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
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
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
    proportions: Literal["long_legs", "long_torso", "balanced"] | None = Field(
        default=None,
        description="Must be null if user did not compare upper vs lower body or torso vs legs. NEVER guess balanced.",
    )
    gender: Literal["male", "female"] | None = Field(default=None)
    age: int | None = Field(default=None)
    weight_kg: float | None = Field(default=None)
    height_cm: float | None = Field(default=None)
    is_off_topic: bool = Field(default=False, description="True ONLY if user asks non-intake questions.")


class Step2Extraction(BaseModel):
    current_goal: str | None = Field(default=None, description="Primary short-term goal.")
    long_term_goal: str | None = Field(default=None, description="Long-term physique/strength goal.")
    weekly_frequency: int | None = Field(default=None, description="Integer days committed per week.")
    training_age_years: float | None = Field(default=None, description="Years of lifting experience.")
    rep_preference: Literal["low", "balanced", "high"] | None = Field(default="balanced")
    is_off_topic: bool = Field(default=False, description="True ONLY if input is unrelated to workout goals.")


class Step3Extraction(BaseModel):
    equipment_access: str | None = Field(default=None, description="Gym or home equipment available.")
    injuries_or_limitations: str | None = Field(
        default=None,
        description="Injuries or joint issues. If user states none, zero, or healthy, set to 'None'.",
    )
    stress_and_sleep: str | None = Field(default=None, description="Job/daily stress and sleep hours/quality.")
    is_off_topic: bool = Field(default=False, description="True ONLY if completely unrelated to fitness logistics.")


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
    raw_lower = raw_input.lower()

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
                cleaned_for_age = re.sub(r"\d+(?:\.\d+)?\s*(?:kg|kilos?|cm|centimeters?)", "", raw_lower)
                standalone_nums = [int(n) for n in re.findall(r"\b(\d+)\b", cleaned_for_age)]
                for n in standalone_nums:
                    if 12 <= n <= 100:
                        age = n
                        break
        else:
            prompt = (
                f"Extract Step 1 biometrics from user input:\n\"{raw_input}\"\n\n"
                f"RULES:\n"
                f"- If upper vs lower body proportions are NOT mentioned, leave proportions as null.\n"
                f"- Flag is_off_topic=True ONLY if input is trivia, coding, or unrelated to biometrics."
            )
            ext: Step1Extraction = step1_extractor.invoke(prompt)
            proportions, gender, age, weight_kg, height_cm = (
                ext.proportions, ext.gender, ext.age, ext.weight_kg, ext.height_cm
            )
            is_off_topic = ext.is_off_topic and not any([proportions, gender, age, weight_kg, height_cm])

        raw_lower = raw_input.lower()
        if not proportions:
            if any(k in raw_lower for k in ["longer leg", "long leg", "legs than torso", "legs longer", "longer legs"]):
                proportions = "long_legs"
            elif any(k in raw_lower for k in ["longer torso", "long torso", "torso than legs", "torso longer"]):
                proportions = "long_torso"
            elif any(k in raw_lower for k in ["balanced", "equal", "same", "proportional"]):
                proportions = "balanced"
            elif any(k in raw_lower for k in ["legs", "torso", "limbs"]):
                proportions = "long_legs" if "leg" in raw_lower else "balanced"
            else:
                proportions = "balanced"

        if not gender:
            if re.search(r"\b(male|man|boy)\b", raw_lower):
                gender = "male"
            elif re.search(r"\b(female|woman|girl)\b", raw_lower):
                gender = "female"

        if weight_kg is None:
            w_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilos?|kilos)\b", raw_lower) or re.search(r"weighing\s+(\d+(?:\.\d+)?)", raw_lower)
            if w_m:
                weight_kg = float(w_m.group(1))

        if height_cm is None:
            h_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", raw_lower) or re.search(r"at\s+(\d+(?:\.\d+)?)\s*cm", raw_lower)
            if h_m:
                height_cm = float(h_m.group(1))

        if age is None:
            a_m = re.search(r"\b(\d+)\s*(?:years?\s*old|yrs?\s*old|yo|years?|yrs?)\b", raw_lower) or re.search(r"\bam\s+(?:an?\s+)?(\d+)\s*year", raw_lower)
            if a_m:
                age = int(a_m.group(1))
            else:
                cleaned_for_age = re.sub(r"\d+(?:\.\d+)?\s*(?:kg|kilos?|cm|centimeters?)", "", raw_lower)
                standalone_nums = [int(n) for n in re.findall(r"\b(\d+)\b", cleaned_for_age)]
                for n in standalone_nums:
                    if 12 <= n <= 100:
                        age = n
                        break

        if is_off_topic:
            return _reject(step, "Input is off-topic. Please provide your proportion comparison and biometrics.", profile)

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
            return _reject(step, f"Incomplete or invalid biometrics: Please provide valid {', '.join(missing)}.", profile)

        profile.update({"proportions": proportions, "gender": gender, "age": age, "weight_kg": weight_kg, "height_cm": height_cm})
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
            prompt = (
                f"Extract Step 2 goals and capacity from user input:\n\"{raw_input}\"\n\n"
                f"RULES:\n"
                f"- current_goal: primary short-term focus.\n"
                f"- long_term_goal: long-term outcome.\n"
                f"- weekly_frequency: integer days per week (1-7).\n"
                f"- training_age_years: lifting experience in years.\n"
                f"- Flag is_off_topic=True ONLY if input is completely unrelated to lifting."
            )
            ext: Step2Extraction = step2_extractor.invoke(prompt)
            current_goal, long_term_goal = ext.current_goal, ext.long_term_goal
            weekly_frequency, training_age_years = ext.weekly_frequency, ext.training_age_years
            rep_pref = ext.rep_preference or "balanced"
            has_step2_data = any([current_goal, long_term_goal, weekly_frequency is not None, training_age_years is not None])
            is_off_topic = ext.is_off_topic and not has_step2_data

        if not current_goal:
            curr_m = re.search(r"(?:current\s*(?:primary\s*)?(?:focus|goal)|focus|goal)\s*(?:is|:)?\s*([^.]+)", raw_input, re.I)
            if not curr_m:
                curr_m = re.search(r"(?:want to|looking to)\s*([^,.]+)", raw_input, re.I)
            if curr_m:
                current_goal = curr_m.group(1).strip()
            elif len(raw_input.strip()) > 5:
                current_goal = raw_input.split(".")[0].strip()

        if not long_term_goal:
            long_m = re.search(r"(?:long[\s-]term(?:\s+goal)?)\s*(?:is|:)?\s*([^.]+)", raw_input, re.I)
            if not long_m:
                long_m = re.search(r"(?:eventually|future)\s*(?:want to|goal is)\s*([^.]+)", raw_input, re.I)
            if long_m:
                long_term_goal = long_m.group(1).strip()
            else:
                long_term_goal = current_goal or "Maintain strength and hypertrophy progression"

        if weekly_frequency is None:
            freq_m = re.search(r"\b([1-7])\s*(?:days?\s*(?:weekly|a\s+week|per\s+week|\/wk)?)\b", raw_input, re.I)
            if freq_m:
                weekly_frequency = int(freq_m.group(1))

        if training_age_years is None:
            exp_m = re.search(r"(?:lifting|training)(?:\s+for)?\s*(\d+(?:\.\d+)?)\s*years?", raw_input, re.I)
            if not exp_m:
                exp_m = re.search(r"(\d+(?:\.\d+)?)\s*years?\s*(?:of\s+)?(?:lifting|training)", raw_input, re.I)
            if not exp_m:
                exp_m = re.search(r"\b(\d+(?:\.\d+)?)\s*years?\b", raw_input, re.I)
            if exp_m:
                training_age_years = float(exp_m.group(1))

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
            prompt = (
                f"Extract Step 3 logistics from user input:\n\"{raw_input}\"\n\n"
                f"RULES:\n"
                f"- equipment_access: gym or equipment details.\n"
                f"- injuries_or_limitations: injuries or issues. If user EXPLICITLY states none/healthy, set 'None'. "
                f"If injuries are NOT mentioned at all, you MUST leave this null.\n"
                f"- stress_and_sleep: job stress and sleep hours.\n"
                f"- Flag is_off_topic=True ONLY if completely unrelated to fitness logistics."
            )
            ext: Step3Extraction = step3_extractor.invoke(prompt)
            equipment, injuries, recovery = ext.equipment_access, ext.injuries_or_limitations, ext.stress_and_sleep
            has_step3_data = any([equipment, injuries, recovery])
            is_off_topic = ext.is_off_topic and not has_step3_data

        if not equipment:
            equip_m = re.search(r"(?:access to|using|have|home gym|gym with)\s*([^.]+)", raw_input, re.I)
            if equip_m:
                equipment = equip_m.group(0).strip()
            elif any(k in raw_input.lower() for k in ["gym", "rack", "dumbbell", "barbell", "machine", "cable"]):
                equipment = raw_input.split(".")[0].strip()

        if not injuries:
            if re.search(r"\b(no injuries|no limitations|none|healthy|no joint issues|zero joint issues|no issues|never injured|without injury)\b", raw_input, re.I):
                injuries = "None"
            else:
                inj_m = re.search(r"(?:injuries|limitations|joint issues)[:\s]+([^.]+)", raw_input, re.I)
                if inj_m:
                    injuries = inj_m.group(1).strip()

        if injuries:
            inj_clean = injuries.strip().lower()
            if any(neg in inj_clean for neg in ["no injuries", "no limitations", "none", "healthy", "no joint", "zero joint", "nil", "n/a", "no issues"]):
                injuries = "None"

        if not recovery:
            rec_m = re.search(r"([^.]*(?:stress|sleep)[^.]*)", raw_input, re.I)
            if rec_m:
                recovery = rec_m.group(1).strip()

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
