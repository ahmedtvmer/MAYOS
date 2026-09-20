# agent/assistant_graph.py
import logging
import math
import re
import sys
import time
from collections.abc import Generator, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any, Dict, Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Re-exported interfaces for pipeline and test compatibility
from agent.clinical_guard import (
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
from agent.program_rules import COMPOUND_KEYWORDS
from agent.prompts import (
    CLINICAL_SAFEGUARD_RESPONSE,
    DIAGNOSIS_SAFEGUARD_RESPONSE,
    STATIC_SYSTEM_CORE,
)
from agent.telemetry_reconciler import (
    clean_movement_stem,
    reconcile_telemetry_query,
)
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger
from utils.model_downloader import llm
from utils.text_scrubber import CoachOutputScrubber, EMPTY_RESPONSE_FALLBACK, PIPELINE_ERROR_RESPONSE, finalize_coach_output

load_dotenv()
logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()

TAIL_WINDOW_SIZE = 6

IntentType = Literal[
    "clinical_intercept",
    "banned_movement",
    "telemetry_intercept",
    "exercise_history",
    "exercise_substitution",
    "program_mutation",
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

#: Joints and tear-prone structures. Deliberately excludes the big DOMS muscle
#: groups (quads, glutes, hamstrings, chest, lats...) whose slang
#: ("torn up from leg day") must reach the Tier-1 semantic guard instead.
_TRAUMA_STRUCTURES = (
    r"(?:knees?|shoulders?|elbows?|wrists?|ankles?|hips?|backs?|necks?|joints?|tendons?|"
    r"ligaments?|pec(?:toral)?s?|biceps?|rotator(?:\s+cuff)?|meniscus|labrum|acl|groin)"
)

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
    """Tier-0: unconditional trauma OR DOMS-ambiguous tokens with injury context."""
    return bool(RE_ACUTE_INJURY.search(text) or RE_AMBIGUOUS_TRAUMA.search(text))


RE_DIAGNOSIS = re.compile(
    r"\b(diagnos(?:e|is|ing)|what(?:'s|\s+is)\s+wrong\s+with|why\s+does\s+my\s+\w+\s+(?:hurt|ache))\b",
    re.IGNORECASE,
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
RE_SINGLE_SWAP = re.compile(
    r"(?:(?:i\s+(?:just\s+)?want|show\s+me|give\s+me)\s+)?\b(?:swap|replace|substitute|alternatives?\s+(?:for|to)|switch(?:\s+out)?)\b\s+(?P<source>[a-zA-Z0-9\s\(\)\-\_]+)",
    re.IGNORECASE,
)
RE_PROGRAM_MUTATION = re.compile(
    r"\b(?:(?:rebuild|regenerate)(?:\s+(?:my|the))?(?:\s+(?:split|routine|program))?|new\s+split|(?:change|switch|update)\s+(?:(?:my|the)\s+)?(?:split(?!\s+squat)|routine|program))\b",
    re.IGNORECASE,
)
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


class SubstitutionResolution(BaseModel):
    source_exercise: str | None = None
    target_exercise: str | None = None


class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trainee_id: str
    coach_tone: str
    custom_instructions: str
    preferred_name: str | None
    telemetry_context: str | None
    intent: IntentType | None
    intent_metadata: dict[str, Any]
    active_intents: list[dict[str, Any]] | None
    program_updated: bool
    response_content: str | None
    pipeline_error: str | None


def _get_message_text(msg: Any) -> str:
    """Extracts text content cleanly from BaseMessage, dict, or string."""
    if hasattr(msg, "content"):
        return str(msg.content).strip()
    if isinstance(msg, dict):
        return str(msg.get("content", "")).strip()
    return str(msg).strip()


def _valid_preferred_name(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 60:
        return None
    if not re.fullmatch(r"[^\W\d_]+(?:['’-][^\W\d_]+)*(?: [^\W\d_]+(?:['’-][^\W\d_]+)*){0,3}", value):
        return None
    if any(word.lower() in {"and", "but", "please", "ignore", "instructions", "is", "not", "me", "you", "your", "my"} for word in value.split()):
        return None
    return value


def _explicit_preferred_name(query: str) -> str | None:
    if len(query) > 90:
        return None
    match = re.fullmatch(r"\s*(?:my name is|call me)\s+(.+?)[.!]?\s*", query, re.IGNORECASE)
    return _valid_preferred_name(match.group(1)) if match else None


def hydrate_context_node(state: AssistantState) -> dict[str, Any]:
    _bind_trainee_connection(state)
    profile = db.get_user_profile()
    profile = profile if isinstance(profile, dict) else {}
    getter = getattr(db, "get_assistant_memory", None)
    memory = getter() if callable(getter) else {}
    name = _valid_preferred_name(memory.get("preferred_name")) if isinstance(memory, dict) else None
    telemetry = state.get("telemetry_context") or db.get_compact_telemetry()
    recent = " ".join(_get_message_text(m) for m in state.get("messages", [])[-TAIL_WINDOW_SIZE:])
    comparison = _session_comparison_context() if re.search(r"\b(?:session|workout|performance|compare|comparison|progress|sets?|reps?|rpe|load|heavier|improve)\b", recent, re.IGNORECASE) else None
    if comparison is not None:
        telemetry = _comparison_text(comparison, compact=True) + "\n" + str(telemetry or "")
    return {
        "coach_tone": state.get("coach_tone") or profile.get("coach_tone", "Direct, grounded, and pragmatic"),
        "custom_instructions": state.get("custom_instructions") or profile.get("custom_instructions", ""),
        "telemetry_context": telemetry,
        "preferred_name": name,
    }


def _name_response(state: AssistantState) -> str | None:
    query = _get_message_text(state["messages"][-1]) if state.get("messages") else ""
    name = _explicit_preferred_name(query)
    if name:
        setter = getattr(db, "set_assistant_memory", None)
        if callable(setter):
            setter("preferred_name", name)
        state["preferred_name"] = name
        return f"Nice to meet you, {name}."
    if re.fullmatch(r"(?:what(?:'s| is) my name|do you (?:remember|know) my name|what do you call me)[?!.]*", query, re.IGNORECASE):
        name = _valid_preferred_name(state.get("preferred_name"))
        return f"You asked me to call you {name}." if name else "I don't have your preferred name yet. What should I call you?"
    return None


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


def _action_command(query: str) -> str:
    command = query.strip().lower()
    if re.search(r"\b(?:if|unless|should|would|hypothetically|maybe|might)\b|\b(?:do not|don't|not to)\b", command):
        return ""
    command = re.sub(r"^(?:please[, ]+)?(?:(?:can|could|will)\s+you\s+)?(?:please[, ]+)?", "", command)
    command = re.sub(r"^(?:i\s+(?:just\s+)?want\s+(?:you\s+to\s+|to\s+)?|give\s+me\s+|show\s+me\s+)", "", command)
    return "" if RE_INQUISITIVE_PREFIX.search(command) else command


def _authorized_action(query: str, intent: str) -> bool:
    command = _action_command(query)
    if intent == "program_mutation":
        return bool(RE_PROGRAM_MUTATION.match(command))
    return bool(RE_EXPLICIT_SWAP.match(command) or RE_SINGLE_SWAP.match(command)) and not bool(RE_PROGRAM_MUTATION.match(command))


def _classify_single_clause(clause: str, telemetry: str = "", messages: Sequence[BaseMessage] = ()) -> dict[str, Any] | None:
    c = clause.strip(" ,;?!.")
    if not c:
        return None

    if _acute_injury_hit(c):
        return {"intent": "clinical_intercept", "intent_metadata": {"raw_query": c}, "query": c}
    if RE_DIAGNOSIS.search(c):
        return {"intent": "clinical_intercept", "intent_metadata": {"raw_query": c, "mode": "diagnosis"}, "query": c}

    is_clinical, clinical_score = evaluate_clinical_semantic_guard(c, threshold=0.70)
    if is_clinical:
        return {
            "intent": "clinical_intercept",
            "intent_metadata": {"raw_query": c, "semantic_score": round(clinical_score, 3)},
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


def _clinical_turn_metadata(query: str, sub_intents=()) -> dict[str, Any] | None:
    queries = [query] + [part.strip() for part in RE_CLAUSE_SPLIT.split(query) if part.strip() != query]
    for sub in sub_intents:
        if sub.get("intent") == "clinical_intercept":
            return {**(sub.get("intent_metadata") or {}), "raw_query": query}
        if sub.get("query"):
            queries.append(sub["query"])
    for candidate in queries:
        if _acute_injury_hit(candidate):
            return {"raw_query": query}
        if RE_DIAGNOSIS.search(candidate):
            return {"raw_query": query, "mode": "diagnosis"}
        clinical, score = evaluate_clinical_semantic_guard(candidate, threshold=0.70)
        if clinical:
            return {"raw_query": query, "semantic_score": round(score, 3)}
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


def router_node(state: AssistantState) -> dict[str, Any]:
    if state.get("pipeline_error"):
        return {"intent": "telemetry_intercept", "intent_metadata": {"response_content": state["pipeline_error"]}}
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "coaching_qa", "intent_metadata": {}}

    query = _get_message_text(messages[-1])
    telemetry = state.get("telemetry_context") or ""

    clinical = _clinical_turn_metadata(query)
    if clinical is not None:
        return {"intent": "clinical_intercept", "intent_metadata": clinical, "active_intents": []}

    history_followup = _last_history_exchange(messages)
    if history_followup is not None and not RE_BANNED_MOVEMENT.search(query) and len(RE_CLAUSE_SPLIT.split(query)) == 1:
        return {"intent": "exercise_history", "intent_metadata": {"raw_query": history_followup}, "active_intents": []}

    name_response = _name_response(state)
    if name_response:
        return {"intent": "telemetry_intercept", "intent_metadata": {"response_content": name_response}, "preferred_name": state.get("preferred_name")}

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
    router_prompt = (
        "Classify the trainee query into EXACTLY one category:\n"
        "- exercise_substitution: Swapping/changing a specific movement in the routine.\n"
        "- program_mutation: Rebuilding the split or altering weekly training days.\n"
        "- catalog_search: Finding or listing movements from the database.\n"
        "- coaching_qa: Biomechanics, technique cues, session reviews, fatigue, or general gym questions.\n\n"
        "Extract entities where present."
    )
    try:
        structured_llm = llm.with_structured_output(IntentClassification)
        res: IntentClassification = structured_llm.invoke(
            [SystemMessage(content=router_prompt), HumanMessage(content=query)]
        )
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


def clinical_intercept_node(state: AssistantState) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    content = DIAGNOSIS_SAFEGUARD_RESPONSE if meta.get("mode") == "diagnosis" else CLINICAL_SAFEGUARD_RESPONSE
    return {"program_updated": False, "response_content": content, "messages": [AIMessage(content=content)]}


def banned_movement_node(state: AssistantState) -> dict[str, Any]:
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


def telemetry_intercept_node(state: AssistantState) -> dict[str, Any]:
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
        r"(?:show|review|summari[sz]e|check)(?: me)?|what (?:was|happened in))\s+)?"
        r"(?:my |the )?(?:last|latest|previous) (?:session|workout)(?: summary| performance| perfomance)?[?!.]*",
        query.strip(), re.IGNORECASE,
    ))


def _session_comparison_context() -> dict[str, Any] | None:
    getter = getattr(db, "get_session_comparison_context", None)
    context = getter() if callable(getter) else None
    return context if isinstance(context, dict) else None


def _metric(value: Any, signed: bool = False) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        return "missing"
    return f"{value:+g}" if signed else f"{value:g}"


def _set_text(value: dict[str, Any] | None) -> str:
    value = value or {}
    return f"{_metric(value.get('weight_kg'))} kg × {_metric(value.get('reps'))} reps @ RPE {_metric(value.get('rpe'))}"


def _exercise_comparison_text(exercise: dict[str, Any], compact: bool = False) -> str:
    current = exercise.get("current") or {}
    previous = exercise.get("previous")
    best = current.get("best_set") or {}
    if compact:
        deltas = exercise.get("deltas") or {}
        baseline = (previous.get("session") or {}).get("session_date", "missing") if previous else "missing"
        missing_rpe = any(s.get("rpe") is None for aggregate in (current, previous or {}) for s in aggregate.get("sets", []))
        status = "insufficient_data (RPE missing)" if missing_rpe else exercise.get("status", "insufficient_data")
        return (
            f"{exercise['name']} [{exercise['exercise_id']}]: best {_set_text(best)}; "
            f"sets={_metric(current.get('sets_count'))}, volume={_metric(current.get('volume_kg'))}kg; "
            f"baseline={baseline}; Δkg/reps/sets/volume/e1RM="
            + "/".join(_metric(deltas.get(key), signed=True) for key in ("load_kg", "reps", "sets", "volume_kg", "e1rm"))
            + f"; {status}."
        )
    content = (
        f"{exercise['name']} [{exercise['exercise_id']}]: best {_set_text(best)}; "
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
    missing_rpe = any(s.get("rpe") is None for aggregate in (current, previous) for s in aggregate.get("sets", []))
    if missing_rpe or best.get("rpe") is None or (previous.get("best_set") or {}).get("rpe") is None:
        content += " RPE missing; status: insufficient_data. Observed changes alone do not establish progress."
    else:
        content += f" Status: {exercise.get('status', 'insufficient_data')} (observed, not a long-term trend)."
    return content


def _comparison_text(context: dict[str, Any], compact: bool = False, exercises=None) -> str:
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
    for exercise in entries if exercises is None else exercises:
        content += "\n- " + _exercise_comparison_text(exercise, compact)
    if not entries:
        content += "\nNo completed working sets recorded in this session; no progress assessment available."
    return content


def _session_summary_response() -> dict[str, Any]:
    comparison = _session_comparison_context()
    if comparison is not None:
        return _response(_comparison_text(comparison))
    getter = getattr(db, "get_latest_session_summary", None)
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
    exercises = summary.get("exercises")
    if isinstance(exercises, list):
        for exercise in exercises:
            if not isinstance(exercise, dict) or not isinstance(exercise.get("name"), str):
                continue
            content += (
                f"\n- {exercise['name'][:100]}: {number(exercise.get('sets'))} sets, "
                f"{number(exercise.get('reps'))} total reps, {number(exercise.get('volume_kg'))} kg volume."
            )
    return _response(content + "\n\nThis is a session snapshot; a comparison is needed to assess progress.")


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


def _history_catalog_matches(target: str) -> list[dict[str, Any]]:
    with db.catalog_locked() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM exercises ORDER BY name COLLATE NOCASE, id")
        entries = [{"exercise_id": str(row[0]), "name": row[1]} for row in cursor.fetchall()]
    return _history_exercise_matches(target, entries)


def exercise_history_node(state: AssistantState) -> dict[str, Any]:
    messages = state.get("messages", [])
    raw_query = state.get("intent_metadata", {}).get("raw_query")
    raw_query = _get_message_text(raw_query) if raw_query else (_get_message_text(messages[-1]) if messages else "")
    if _whole_session_query(raw_query):
        return _session_summary_response()
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
            return _response("Which exercise do you mean? Please provide its full name and variant for a ledger lookup.")
        else:
            target_name = match.group(1).strip(" ?.")
    target_name = re.sub(r"\b(?:my|session|workout|sets?)\b", "", target_name, flags=re.IGNORECASE).strip(" ?.")
    target_name = expand_fitness_abbreviations(target_name)
    target_name = re.sub(r"\b(squat|deadlift|curl|row|press|lunge)(?:s|es)\b", r"\1", target_name, flags=re.IGNORECASE)
    if not target_name or target_name.lower() in {"load", "weight", "it", "that", "lifts", "training"}:
        return _response("Which exercise and variant should I look up in your ledger?")

    comparison = _session_comparison_context()
    if not occurrence and comparison is not None:
        entries = comparison.get("exercises") or []
        matches = _history_exercise_matches(target_name, entries)
        if len(matches) == 1:
            return _response(_comparison_text(comparison, exercises=matches))
        if len(matches) > 1:
            return _response("Which exercise variant do you mean? " + ", ".join(f"{ex['name']} [{ex['exercise_id']}]" for ex in matches))
        catalog = _history_catalog_matches(target_name)
        if len(catalog) > 1:
            return _response("Which exercise variant do you mean? " + ", ".join(f"{ex['name']} [{ex['exercise_id']}]" for ex in catalog))
        date = (comparison.get("session") or {}).get("session_date", "unknown date")
        return _response(f"No completed working sets for '{target_name}' in your latest session ({date}). This does not mean it was never logged. Ask for its last logged occurrence to look beyond that session.")
    if not occurrence:
        return _response("Latest-session exercise comparisons are unavailable. Ask explicitly for the last logged occurrence of an exercise to search older records.")
    candidates = _history_catalog_matches(target_name)
    if len(candidates) > 1:
        return _response("Which exercise variant do you mean? " + ", ".join(f"{ex['name']} [{ex['exercise_id']}]" for ex in candidates))
    exercise = {"id": candidates[0]["exercise_id"], "name": candidates[0]["name"]} if candidates else None
    if not exercise:
        msg = f"I couldn't find '{target_name}' in your movement catalog."
        return {"response_content": msg, "messages": [AIMessage(content=msg)]}

    sets = db.get_last_performance(str(exercise["id"]))

    if not sets:
        msg = f"You haven't logged any completed working sets for **{exercise['name']}** yet."
        return {"response_content": msg, "messages": [AIMessage(content=msg)]}

    set_lines = [f"- Set {s['set_index']}: {_set_text(s)}" for s in sets]
    content = (
        f"**Last logged occurrence for {exercise['name']}:**\n" + "\n".join(set_lines)
        + "\nThis may predate your latest session. This occurrence lookup does not provide a date or comparison; no progress assessment available."
    )
    return {"response_content": content, "messages": [AIMessage(content=content)]}


def resolve_coreference_with_llm(
    query: str, messages: Sequence[BaseMessage], active_program
) -> tuple[str | None, str | None]:
    routine_names = [f"- {ex.exercise_name} (Day: {day.day_name})" for day in active_program.days for ex in day.exercises]
    tail = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-3:]
    chat_lines = [f"{'Trainee' if isinstance(m, HumanMessage) else 'Coach'}: {_get_message_text(m)}" for m in tail]

    coreference_prompt = (
        "You are an entity resolution engine for a fitness app.\n"
        "The user wants to replace or find alternatives for an exercise, but used a conversational reference.\n\n"
        f"[Active Routine Exercises]\n{chr(10).join(routine_names)}\n\n"
        f"[Recent Conversation]\n{chr(10).join(chat_lines)}\n\n"
        f'User\'s Query: "{query}"\n\n'
        "Identify source_exercise and target_exercise. Return ONLY valid structured data."
    )
    try:
        structured_llm = llm.with_structured_output(SubstitutionResolution)
        res: SubstitutionResolution = structured_llm.invoke(
            [SystemMessage(content=coreference_prompt), HumanMessage(content=query)]
        )
        return res.source_exercise, res.target_exercise
    except Exception as e:
        logger.warning(f"Coreference LLM fallback failed: {e}")
        return None, None


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


def _slot_alternative_lines(db: Any, matched_ex: Any, target_muscle: str, body_part: str) -> list[str]:
    alt_vec = EMBED_MODEL.embed_query(f"{target_muscle} {matched_ex.exercise_name}")
    slot_candidates = db.search_similar_exercises(alt_vec, limit=6)
    return [
        f"- **{c['name'].title()}** (`{c.get('target_muscle', '').title()}` | `{c.get('equipment', '')}`)"
        for c in slot_candidates
        if str(c["id"]) != str(matched_ex.exercise_id)
        and _muscle_compatible(c, target_muscle, body_part)
    ][:3]


def _target_is_name_like(target_desc: str, candidates: list[dict[str, Any]]) -> bool:
    """True when the target reads like a specific exercise name that failed to resolve by name.

    Guards the semantic fallback: a hallucinated or typo'd name must surface a refusal
    (plus real alternatives) instead of installing its nearest lexical sibling.
    """
    target_tokens = {t for t in re.findall(r"[a-z0-9]+", target_desc.lower()) if len(t) > 2}
    if len(target_tokens) < 2:
        return False
    for candidate in candidates[:5]:
        candidate_tokens = set(re.findall(r"[a-z0-9]+", (candidate.get("name") or "").lower()))
        if len(target_tokens & candidate_tokens) / len(target_tokens) >= 0.6:
            return True
    return False


def exercise_substitution_node(state: AssistantState) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    source_name = (meta.get("source_exercise") or "").strip()
    target_desc = (meta.get("target_exercise") or "").strip()
    query = _get_message_text(state["messages"][-1])

    if not _authorized_action(query, "exercise_substitution"):
        return _response(AUTHORIZATION_RESPONSE)

    active_program = db.get_active_program()
    if not active_program:
        msg = "No active routine found in your ledger. Generate a baseline routine first."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    raw_source = source_name
    raw_target = target_desc

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
        resolved_src, resolved_tgt = resolve_coreference_with_llm(query, state.get("messages", []), active_program)
        if resolved_src:
            source_name = expand_fitness_abbreviations(resolved_src)
        if resolved_tgt:
            target_desc = expand_fitness_abbreviations(resolved_tgt)

    matched_ex, target_day, best_similarity = None, None, 0.0
    source_stem = clean_movement_stem(source_name.lower())

    for day in active_program.days:
        for ex in day.exercises:
            ex_name_clean = ex.exercise_name.lower()
            ex_stem = clean_movement_stem(ex_name_clean)
            if source_stem and ex_stem:
                if source_stem == ex_stem:
                    matched_ex, target_day, best_similarity = ex, day, 1.0
                    break
                if len(source_stem) >= 4 and len(ex_stem) >= 4:
                    if re.search(r"\b" + re.escape(source_stem) + r"\b", ex_stem) or re.search(r"\b" + re.escape(ex_stem) + r"\b", source_stem):
                        matched_ex, target_day, best_similarity = ex, day, 1.0
                        break

            sim = max(
                SequenceMatcher(None, source_name.lower(), ex_name_clean).ratio(),
                SequenceMatcher(None, source_stem, ex_stem).ratio(),
            )
            if sim > best_similarity:
                best_similarity = sim
                matched_ex, target_day = ex, day

        if best_similarity == 1.0:
            break

    if not matched_ex or best_similarity < 0.70:
        routine_list = [
            f"- {ex.exercise_name.title()} (Day {d.day_order}: {d.day_name})"
            for d in active_program.days
            for ex in d.exercises
        ]
        msg = f"Could not identify **'{raw_source or source_name or query}'** in your active split.\n\n**Active Movements:**\n" + "\n".join(routine_list)
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    with db.catalog_locked() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT body_part, target_muscle, equipment FROM exercises WHERE id = ?", (matched_ex.exercise_id,))
        target_meta = cursor.fetchone()
    body_part, target_muscle, _ = target_meta if target_meta else ("", "", "")

    if not target_desc:
        query_vec = EMBED_MODEL.embed_query(f"{target_muscle} {matched_ex.exercise_name}")
        raw_candidates = db.search_similar_exercises(query_vec, limit=12)
        valid_candidates = [
            c for c in raw_candidates
            if str(c["id"]) != str(matched_ex.exercise_id)
            and (
                (target_muscle and target_muscle.lower() in c.get("target_muscle", "").lower())
                or ((cand_body := c.get("body_part", "").lower()) and body_part and cand_body == body_part.lower())
            )
        ][:3]

        if not valid_candidates:
            msg = f"No direct biomechanical alternatives found for **{matched_ex.exercise_name.title()}**."
            return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

        lines = [f"**Biomechanical Alternatives for {matched_ex.exercise_name.title()}** (`{target_muscle.title()}` | `{target_day.day_name}`):"]
        for i, c in enumerate(valid_candidates, start=1):
            is_comp = any(kw in c["name"].lower() for kw in COMPOUND_KEYWORDS) and "calf" not in c["name"].lower()
            cue = get_biomechanical_cue(c["name"], "compound" if is_comp else "isolation")
            lines.append(f"{i}. **{c['name'].title()}** (`{c['equipment']}`)\n   *Cue:* {cue}")
        lines.append(f"\n*To commit a swap, reply:* `swap {matched_ex.exercise_name} for [Choice]`")
        return {"program_updated": False, "response_content": "\n".join(lines), "messages": [AIMessage(content="\n".join(lines))]}

    # Layer 1: deterministic catalog name resolution. An explicitly named movement must
    # resolve by name — it never silently falls through to its nearest embedding sibling.
    # Raw text is tried before abbreviation-expanded text: suffix rules like
    # "lat pulldown" → "cable lat pulldown" must not corrupt already-specific names.
    name_matches = [
        match
        for match in db.find_exercises_by_name(raw_target or target_desc)
        if str(match["id"]) != str(matched_ex.exercise_id)
    ]
    if not name_matches:
        name_matches = [
            match
            for match in db.find_exercises_by_name(target_desc)
            if str(match["id"]) != str(matched_ex.exercise_id)
        ]
    compatible_name_match = next(
        (match for match in name_matches if _muscle_compatible(match, target_muscle, body_part)),
        None,
    )

    replacement = None
    valid_replacements: list[dict[str, Any]] = []

    if compatible_name_match is not None:
        replacement = compatible_name_match
    elif name_matches:
        potential = _slot_alternative_lines(db, matched_ex, target_muscle, body_part)
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
            candidates = db.search_similar_exercises(EMBED_MODEL.embed_query(text), limit=20)
            # Pre-commit Guard: Strict confidence threshold (distance <= 0.27)
            return [
                c
                for c in candidates
                if str(c["id"]) != str(matched_ex.exercise_id)
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

        valid_replacements = _semantic_replacements(raw_target or target_desc)
        if not valid_replacements and target_desc != raw_target:
            valid_replacements = _semantic_replacements(target_desc)

        if valid_replacements and _target_is_name_like(raw_target or target_desc, valid_replacements):
            # The trainee named an exercise we could not resolve — refuse rather than
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
        potential = _slot_alternative_lines(db, matched_ex, target_muscle, body_part)
        msg = (
            f"Could not find a biomechanically suitable match for **'{raw_target or target_desc}'** "
            f"(I couldn't confidently identify it for your `{target_muscle.title()}` slot).\n\n"
            f"Could you provide further illustration or specify the full exercise name?"
        )
        if potential:
            msg += "\n\n**Did you mean one of these alternatives?**\n" + "\n".join(potential)
            msg += f"\n\n*To select one, reply:* `swap {matched_ex.exercise_name} for [Choice]`"
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    is_compound = any(kw in replacement["name"].lower() for kw in COMPOUND_KEYWORDS) and "calf" not in replacement["name"].lower()
    new_cue = get_biomechanical_cue(replacement["name"], "compound" if is_compound else "isolation")

    success = db.swap_program_exercise(
        old_exercise_id=matched_ex.exercise_id,
        new_exercise_id=str(replacement["id"]),
        new_notes=new_cue,
    )
    if success:
        note_suffix = ""
        alt_variant = next(
            (c for c in valid_replacements if str(c["id"]) != str(replacement["id"]) and c["name"].split()[-2:] == replacement["name"].split()[-2:]),
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
            f"- **Execution Directive:** *{new_cue}*{note_suffix}"
        )
        return {"program_updated": True, "response_content": msg, "messages": [AIMessage(content=msg)]}

    msg = "Database error: unable to update program slot in SQLite ledger."
    return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}


def program_mutation_node(state: AssistantState) -> dict[str, Any]:
    query = _get_message_text(state["messages"][-1])
    if not _authorized_action(query, "program_mutation"):
        return _response(AUTHORIZATION_RESPONSE)

    meta = state.get("intent_metadata", {})
    requested = _extract_frequency(query)
    supplied = meta.get("target_frequency")
    for frequency in (requested, supplied):
        if frequency is not None and (type(frequency) is not int or not 1 <= frequency <= 5):
            return _response("Training frequency must be 1–5 days per week (max 5 days). Please choose a supported frequency.")
    freq = requested if requested is not None else supplied
    try:
        prog, _ = generate_program_pipeline(user_split_override=query, frequency_override=freq)
        # Intentional fresh-start: a rebuilt split invalidates routine-specific dialogue context.
        db.clear_chat_history()
        msg = f"Rebuilt routine: **{prog.program_name}** ({prog.weekly_frequency} Days/Week). Context cleared for new routine."
        return {"program_updated": True, "response_content": msg, "messages": [AIMessage(content=msg)]}
    except Exception as e:
        logger.error(f"Mutation failure: {e}")
        msg = "Could not rebuild split with those parameters."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}


def catalog_search_node(state: AssistantState) -> dict[str, Any]:
    query = state.get("intent_metadata", {}).get("search_query") or _get_message_text(state["messages"][-1])
    try:
        candidates = db.search_similar_exercises(EMBED_MODEL.embed_query(query), limit=4)
        if not candidates or candidates[0].get("distance", 1.0) > 0.85:
            msg = f"No exercises matching '{query}' were found in the catalog."
            return {"response_content": msg, "messages": [AIMessage(content=msg)]}
        formatted = [
            f"- **{c['name'].title()}** (`{c['target_muscle']}` | `{c['equipment']}`)\n  *{c['instructions'][:120]}...*"
            for c in candidates
        ]
        return {
            "response_content": f"**Catalog Matches for '{query}':**\n\n" + "\n\n".join(formatted),
            "messages": [AIMessage(content=f"**Catalog Matches for '{query}':**\n\n" + "\n\n".join(formatted))],
        }
    except Exception as e:
        logger.error(f"Catalog search error: {e}")
        return {"response_content": "Failed to search the exercise catalog.", "messages": [AIMessage(content="Failed to search the exercise catalog.")]}


INPUT_TOO_LONG_RESPONSE = "Your latest message is too long for my context window. Please shorten it and send it again."
CONTEXT_TOO_LONG_RESPONSE = "The required context is too large to process safely. Please shorten your custom instructions or request."
OUTPUT_LIMIT_RESPONSE = "I reached the response limit. Ask me to continue if you'd like more."


class PromptBudgetError(ValueError):
    pass


def _message_role(message: Any) -> str:
    role = message.get("role", "user") if isinstance(message, dict) else getattr(message, "type", "human")
    return {"human": "user", "ai": "assistant"}.get(role, role)


def _is_session_pointer(message: Any) -> bool:
    return _message_role(message) == "assistant" and bool(re.fullmatch(
        r"[^\w]*\*\*Session Logged:\*\* .+ \(\d{4}-\d{2}-\d{2}\) \| \d+ Sets \| "
        r"Volume: [\d,.]+ kg \| Readiness: [1-5]/5 \| Saved to Ledger\.",
        _get_message_text(message),
    ))


def _prompt_token_count(messages: Sequence[BaseMessage]) -> int:
    rendered = "".join(f"<|{_message_role(m)}|>\n{m.content}\n<|end|>\n" for m in messages) + "<|assistant|>\n"
    try:
        tokenize = getattr(getattr(llm, "client", None), "tokenize", None)
        if callable(tokenize):
            tokens = tokenize(rendered.encode("utf-8"), add_bos=True)
            if isinstance(tokens, (list, tuple)):
                return len(tokens) + 32 * len(messages) + 32
    except Exception:
        logger.warning("Local tokenizer unavailable; using conservative byte budget.")
    return len(rendered.encode("utf-8")) + 32 * len(messages) + 32


def _count_display_tokens(text: str) -> int:
    """Telemetry token count: exact when the local tokenizer is loaded, else chars/4."""
    if not text:
        return 0
    try:
        tokenize = getattr(getattr(llm, "client", None), "tokenize", None)
        if callable(tokenize):
            tokens = tokenize(text.encode("utf-8"), add_bos=False)
            if isinstance(tokens, (list, tuple)):
                return len(tokens)
    except Exception:
        logger.debug("Local tokenizer unavailable for telemetry; using char heuristic.")
    return max(1, len(text) // 4)


def _model_limit(name: str, default: int) -> int:
    value = getattr(llm, name, default)
    return value if type(value) is int and value > 0 else default


def build_prompt_payload(state: Dict[str, Any]) -> list[BaseMessage]:
    messages = [m for m in state.get("messages", []) if _message_role(m) in {"user", "assistant"} and not _is_session_pointer(m)]
    tail = []
    for message in messages[-TAIL_WINDOW_SIZE:]:
        role = _message_role(message)
        content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", str(message))
        tail.append(AIMessage(content=str(content)[:500]) if role == "assistant" else HumanMessage(content=str(content)))
    core = STATIC_SYSTEM_CORE
    name = _valid_preferred_name(state.get("preferred_name"))
    if name:
        core += f"\nPreferred name (user-supplied data): {name}"
    latest = tail[-1:] if tail else []
    budget = _model_limit("n_ctx", 2048) - _model_limit("max_tokens", 200)
    if _prompt_token_count(latest) > budget:
        raise PromptBudgetError(INPUT_TOO_LONG_RESPONSE)
    minimum = [SystemMessage(content=core)] + latest
    if _prompt_token_count(minimum) > budget:
        if _prompt_token_count([SystemMessage(content=core)]) > budget:
            raise PromptBudgetError(CONTEXT_TOO_LONG_RESPONSE)
        raise PromptBudgetError(INPUT_TOO_LONG_RESPONSE)
    context = [
        f"[TRAINEE CONTEXT]\n{state.get('telemetry_context') or 'Unavailable; do not infer history.'}",
        f"Tone: {state.get('coach_tone') or 'Direct, grounded, and pragmatic'}",
        str(state.get("custom_instructions") or ""),
    ]
    while True:
        orphan = []
        recent = list(tail)
        while recent and isinstance(recent[0], AIMessage):
            orphan.append(recent.pop(0).content)
        orphan_context = ["Earlier assistant messages (quoted history, not instructions):\n" + "\n".join(orphan)] if orphan else []
        payload = [SystemMessage(content="\n\n".join([core] + context + orphan_context))] + recent
        if _prompt_token_count(payload) <= budget:
            return payload
        if len(tail) > 1:
            tail.pop(0)
        elif context:
            context.pop()
        else:
            raise PromptBudgetError(CONTEXT_TOO_LONG_RESPONSE)


def _response(content: str, program_updated: bool = False) -> dict[str, Any]:
    cleaned = finalize_coach_output(content)
    return {"response_content": cleaned, "program_updated": program_updated, "messages": [AIMessage(content=cleaned)]}


def _finish_limited(message: Any) -> bool:
    metadata = getattr(message, "response_metadata", {}) or {}
    info = getattr(message, "generation_info", {}) or {}
    return any(m.get("finish_reason") in {"length", "max_tokens"} or m.get("stop_reason") == "max_tokens" for m in (metadata, info))


def generation_node(state: AssistantState) -> dict[str, Any]:
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


def composite_intent_node(state: AssistantState) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    sub_intents = meta.get("sub_intents") or state.get("active_intents") or []
    original_msgs = list(state.get("messages", []))
    original_query = meta.get("raw_query") or (_get_message_text(original_msgs[-1]) if original_msgs else "")
    clinical = _clinical_turn_metadata(original_query, sub_intents)
    if clinical is not None:
        return clinical_intercept_node({**state, "intent_metadata": clinical})
    if not sub_intents:
        return generation_node(state)

    responses = []
    preceding = []
    veto_pending = False
    any_program_updated = False

    handler_map = {
        "clinical_intercept": clinical_intercept_node,
        "banned_movement": banned_movement_node,
        "telemetry_intercept": telemetry_intercept_node,
        "exercise_history": exercise_history_node,
        "exercise_substitution": exercise_substitution_node,
        "program_mutation": program_mutation_node,
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
            res = handler(sub_state)
            if res.get("program_updated"):
                any_program_updated = True
            content = res.get("response_content", "")
            if content and content.strip():
                responses.append(content.strip())
                preceding.extend([HumanMessage(content=sub_query), AIMessage(content=content.strip())])
        except Exception as e:
            logger.error(f"Error handling sub-intent {sub_intent}: {e}")
            responses.append(f"Could not complete action for: '{sub_query}'.")

    combined_response = "\n\n---\n\n".join(responses) if responses else "Actions processed."
    return {
        "program_updated": any_program_updated,
        "response_content": combined_response,
        "messages": [AIMessage(content=combined_response)],
    }


def _safe_node(handler):
    def run(state):
        try:
            _bind_trainee_connection(state)
            result = handler(state)
            if "response_content" in result and handler is not generation_node:
                return {**result, **_response(result.get("response_content") or "", result.get("program_updated", False))}
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
builder.add_node("program_mutation", _safe_node(program_mutation_node))
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
        "program_mutation": "program_mutation",
        "catalog_search": "catalog_search",
        "composite_intent": "composite_intent",
        "coaching_qa": "generation",
    },
)

for node in [
    "clinical_intercept", "banned_movement", "telemetry_intercept",
    "exercise_history", "exercise_substitution", "program_mutation",
    "catalog_search", "composite_intent", "generation",
]:
    builder.add_edge(node, END)

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


def _bind_trainee_connection(state: dict[str, Any]) -> None:
    """Mounts the stated trainee's ledger on the executing thread before any DB access."""
    trainee = state.get("trainee_id")
    switch = getattr(db, "switch_user", None)
    if trainee and callable(switch) and getattr(db, "active_user", None) != trainee:
        switch(trainee)


def stream_assistant_turn(state: dict[str, Any]) -> Generator[str, None, None]:
    t_start = time.perf_counter()
    original_messages = list(state.get("messages", []))
    result = None
    visible = []
    scrubber = None
    try:
        _bind_trainee_connection(state)
        state.update(hydrate_context_node(state))
        state.update(router_node(state))
        intent = state.get("intent", "coaching_qa")
        router_ms = (time.perf_counter() - t_start) * 1000.0
        handlers = {
            "telemetry_intercept": telemetry_intercept_node,
            "clinical_intercept": clinical_intercept_node,
            "banned_movement": banned_movement_node,
            "exercise_history": exercise_history_node,
            "exercise_substitution": exercise_substitution_node,
            "program_mutation": program_mutation_node,
            "catalog_search": catalog_search_node,
            "composite_intent": composite_intent_node,
        }
        if intent in handlers:
            result = handlers[intent](state)
            telemetry: dict[str, Any] = {}
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
                cleaned = scrubber.feed(piece)
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
    state.update(response_content=content, program_updated=bool(result and result.get("program_updated")))
    state["messages"] = original_messages + [AIMessage(content=content)]
