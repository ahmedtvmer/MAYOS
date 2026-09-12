# agent/assistant_graph.py
import logging
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
from utils.text_scrubber import scrub_coach_output

load_dotenv()
logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()

IntentType = Literal[
    "clinical_intercept",
    "banned_movement",
    "telemetry_intercept",
    "exercise_history",
    "exercise_substitution",
    "program_mutation",
    "catalog_search",
    "coaching_qa",
]

RE_ACUTE_INJURY = re.compile(
    r"\b(sharp\s+(?:pain|pop|pull|twinge|pinch)|shooting\s+pain|radiat(?:ing|es|ed)?(?:\s+pain)?|"
    r"numb(?:ness)?|tingling|pop(?:ped)?|tore|tear|torn|swell(?:ing)?|swollen|pinched(?:\s+nerve)?|"
    r"tweak(?:ed)?|hernia|dislocat(?:ed|ion)|can['']t\s+move\s+my|joint\s+clicking\s+with\s+pain)\b",
    re.IGNORECASE,
)
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
    r"\b(rebuild|regenerate|new\s+split|(?:change|switch|update)\s+(?:the\s+)?(?:split(?!\s+squat)|routine|program)|(\d+)\s*(?:days?|d/wk|days\s+a\s+week))\b",
    re.IGNORECASE,
)
RE_FREQ_DIGIT = re.compile(r"\b([1-6])\s*(?:days?|d/wk|days\s+a\s+week)\b", re.IGNORECASE)
RE_SEARCH_TOKENS = re.compile(r"\b(search|find|lookup|show me|list exercises)\b", re.IGNORECASE)
RE_ACTION_HINT = re.compile(
    r"\b(swap|replace|substitute|change|split|routine|program|days|rebuild|alternatives?|exercises)\b",
    re.IGNORECASE,
)
RE_EXERCISE_PERFORMANCE_QUERY = re.compile(
    r"\b(?:how\s+did\s+i\s+do\s+(?:in|on|for)|what\s+did\s+i\s+(?:do|hit|lift)\s+(?:in|on|for)|my\s+last\s+session\s+(?:for|on))\s+(.+)",
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


class SubstitutionResolution(BaseModel):
    source_exercise: str | None = None
    target_exercise: str | None = None


class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trainee_id: str
    coach_tone: str
    custom_instructions: str
    telemetry_context: str | None
    intent: IntentType | None
    intent_metadata: dict[str, Any]
    program_updated: bool
    response_content: str | None


def _get_message_text(msg: Any) -> str:
    """Extracts text content cleanly from BaseMessage, dict, or string."""
    if hasattr(msg, "content"):
        return str(msg.content).strip()
    if isinstance(msg, dict):
        return str(msg.get("content", "")).strip()
    return str(msg).strip()


def hydrate_context_node(state: AssistantState) -> dict[str, Any]:
    profile = db.get_user_profile() or {}
    return {
        "coach_tone": state.get("coach_tone") or profile.get("coach_tone", "Direct, grounded, and pragmatic"),
        "custom_instructions": state.get("custom_instructions") or profile.get("custom_instructions", ""),
        "telemetry_context": state.get("telemetry_context") or db.get_compact_telemetry(),
    }


def router_node(state: AssistantState) -> dict[str, Any]:
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "coaching_qa", "intent_metadata": {}}

    query = _get_message_text(messages[-1])
    telemetry = state.get("telemetry_context") or ""

    # Tier 0: Deterministic Fast Paths
    if RE_ACUTE_INJURY.search(query):
        return {"intent": "clinical_intercept", "intent_metadata": {"raw_query": query}}
    if RE_DIAGNOSIS.search(query):
        return {"intent": "clinical_intercept", "intent_metadata": {"raw_query": query, "mode": "diagnosis"}}

    # Tier 1: Somatosensory Semantic Intercept (Evaluated before any early exits)
    is_clinical, clinical_score = evaluate_clinical_semantic_guard(query, threshold=0.70)
    if is_clinical:
        return {
            "intent": "clinical_intercept",
            "intent_metadata": {"raw_query": query, "semantic_score": round(clinical_score, 3)},
        }

    # Banned Movements & Dynamic Ledger Intercepts
    if RE_BANNED_MOVEMENT.search(query):
        return {"intent": "banned_movement", "intent_metadata": {"raw_query": query}}

    telemetry_resp = reconcile_telemetry_query(query, telemetry)
    if telemetry_resp:
        return {
            "intent": "telemetry_intercept",
            "intent_metadata": {"response_content": telemetry_resp, "raw_query": query},
        }

    if RE_EXERCISE_PERFORMANCE_QUERY.search(query):
        return {"intent": "exercise_history", "intent_metadata": {"raw_query": query}}

    if RE_NUTRITION.search(query):
        return {"intent": "coaching_qa", "intent_metadata": {}}

    # Program Mutations & Exercise Swaps
    if RE_PROGRAM_MUTATION.search(query):
        freq_match = RE_FREQ_DIGIT.search(query)
        return {
            "intent": "program_mutation",
            "intent_metadata": {"target_frequency": int(freq_match.group(1)) if freq_match else None},
        }

    explicit_match = RE_EXPLICIT_SWAP.search(query)
    if explicit_match:
        data = explicit_match.groupdict()
        src, tgt = data["source"].strip(), data["target"].strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"] and not RE_FREQ_DIGIT.search(tgt):
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {"mode": "direct_swap", "source_exercise": src, "target_exercise": tgt},
            }

    single_match = RE_SINGLE_SWAP.search(query)
    if single_match:
        src = single_match.group("source").strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"]:
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {"mode": "lookup_candidates", "source_exercise": src, "target_exercise": None},
            }

    if RE_SEARCH_TOKENS.search(query):
        return {
            "intent": "catalog_search",
            "intent_metadata": {"search_query": RE_SEARCH_TOKENS.sub("", query).strip().rstrip(".!?")},
        }

    if not RE_ACTION_HINT.search(query):
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


def exercise_history_node(state: AssistantState) -> dict[str, Any]:
    messages = state.get("messages", [])
    raw_query = _get_message_text(messages[-1]) if messages else ""
    match = RE_EXERCISE_PERFORMANCE_QUERY.search(raw_query)
    target_name = match.group(1).strip(" ?.") if match else raw_query

    exercise = db.find_exercise_by_name(target_name)
    if not exercise:
        msg = f"I couldn't find '{target_name}' in your movement catalog."
        return {"response_content": msg, "messages": [AIMessage(content=msg)]}

    sets = db.get_last_performance(exercise["id"])
    if not sets:
        msg = f"You haven't logged any completed working sets for **{exercise['name']}** yet."
        return {"response_content": msg, "messages": [AIMessage(content=msg)]}

    set_lines = []
    best_e1rm = 0.0
    for s in sets:
        w, r, rpe = s["weight_kg"], s["reps"], s["rpe"]
        e1rm = round(w * (1 + r / 30.0), 1) if r > 1 else w
        best_e1rm = max(best_e1rm, e1rm)
        set_lines.append(f"- Set {s['set_index']}: **{w} kg** × **{r} reps** @ RPE {rpe}")

    content = f"**Last Logged Session for {exercise['name']}:**\n{'\n'.join(set_lines)}\n\n**Peak Estimated 1RM:** {best_e1rm} kg"
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


def exercise_substitution_node(state: AssistantState) -> dict[str, Any]:
    meta = state.get("intent_metadata", {})
    source_name = (meta.get("source_exercise") or "").strip()
    target_desc = (meta.get("target_exercise") or "").strip()
    query = _get_message_text(state["messages"][-1])

    active_program = db.get_active_program()
    if not active_program:
        msg = "No active routine found in your ledger. Generate a baseline routine first."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

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
            source_name = resolved_src
        if resolved_tgt:
            target_desc = resolved_tgt

    matched_ex, target_day, best_similarity = None, None, 0.0
    source_stem = clean_movement_stem(source_name.lower())

    for day in active_program.days:
        for ex in day.exercises:
            ex_name_clean = ex.exercise_name.lower()
            ex_stem = clean_movement_stem(ex_name_clean)
            if source_stem and (source_stem in ex_stem or ex_stem in source_stem):
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

    if (not matched_ex or best_similarity < 0.55) and not needs_llm_resolution:
        resolved_src, resolved_tgt = resolve_coreference_with_llm(query, state.get("messages", []), active_program)
        if resolved_src:
            for day in active_program.days:
                for ex in day.exercises:
                    if resolved_src.lower() in ex.exercise_name.lower():
                        matched_ex, target_day, best_similarity = ex, day, 1.0
                        break
            if resolved_tgt:
                target_desc = resolved_tgt

    if not matched_ex or best_similarity < 0.55:
        routine_list = [
            f"- {ex.exercise_name.title()} (Day {d.day_order}: {d.day_name})"
            for d in active_program.days
            for ex in d.exercises
        ]
        msg = f"Could not identify **'{source_name or query}'** in your active split.\n\n**Active Movements:**\n" + "\n".join(routine_list)
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    cursor = db.catalog_conn.cursor()
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

    query_vec = EMBED_MODEL.embed_query(f"{target_muscle} {target_desc}")
    candidates = db.search_similar_exercises(query_vec, limit=10)
    replacement = next(
        (
            c for c in candidates
            if str(c["id"]) != str(matched_ex.exercise_id)
            and (
                (target_muscle and (target_muscle.lower() in c.get("target_muscle", "").lower() or c.get("target_muscle", "").lower() in target_muscle.lower()))
                or (body_part and body_part.lower() == c.get("body_part", "").lower())
            )
        ),
        None,
    )

    if not replacement:
        msg = f"Could not find a biomechanically suitable match for **'{target_desc}'** targeting {target_muscle}."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    is_compound = any(kw in replacement["name"].lower() for kw in COMPOUND_KEYWORDS) and "calf" not in replacement["name"].lower()
    new_cue = get_biomechanical_cue(replacement["name"], "compound" if is_compound else "isolation")

    success = db.swap_program_exercise(
        old_exercise_id=matched_ex.exercise_id,
        new_exercise_id=str(replacement["id"]),
        new_notes=new_cue,
    )
    if success:
        msg = (
            f"✅ **Routine Slot Updated ({target_day.day_name})**\n\n"
            f"- **Removed:** {matched_ex.exercise_name.title()}\n"
            f"- **Installed:** {replacement['name'].title()} (`{replacement['target_muscle']}` | `{replacement['equipment']}`)\n"
            f"- **Execution Directive:** *{new_cue}*"
        )
        return {"program_updated": True, "response_content": msg, "messages": [AIMessage(content=msg)]}

    msg = "Database error: unable to update program slot in SQLite ledger."
    return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}


def program_mutation_node(state: AssistantState) -> dict[str, Any]:
    query = _get_message_text(state["messages"][-1])
    meta = state.get("intent_metadata", {})
    freq = meta.get("target_frequency") or extract_frequency_from_text(query)
    try:
        prog, _ = generate_program_pipeline(user_split_override=query, frequency_override=freq)
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


def build_prompt_payload(state: Dict[str, Any]) -> list[BaseMessage]:
    messages = state.get("messages", [])
    telemetry_context = state.get("telemetry_context", "None")
    coach_tone = state.get("coach_tone", "Direct, grounded, and pragmatic")
    custom_instructions = state.get("custom_instructions", "")

    context_block = f"[TRAINEE CONTEXT]\n{telemetry_context}\n\nTone: {coach_tone}\n{custom_instructions}\n"
    payload: list[BaseMessage] = [SystemMessage(content=f"{STATIC_SYSTEM_CORE}\n\n{context_block}")]
    payload.extend(messages)
    return payload


def generation_node(state: AssistantState) -> dict[str, Any]:
    response = llm.invoke(build_prompt_payload(state))
    cleaned = scrub_coach_output(response.content)
    return {"response_content": cleaned, "program_updated": False, "messages": [AIMessage(content=cleaned)]}


# StateGraph Assembly
builder = StateGraph(AssistantState)
builder.add_node("hydrate_context", hydrate_context_node)
builder.add_node("router", router_node)
builder.add_node("clinical_intercept", clinical_intercept_node)
builder.add_node("banned_movement", banned_movement_node)
builder.add_node("telemetry_intercept", telemetry_intercept_node)
builder.add_node("exercise_history", exercise_history_node)
builder.add_node("exercise_substitution", exercise_substitution_node)
builder.add_node("program_mutation", program_mutation_node)
builder.add_node("catalog_search", catalog_search_node)
builder.add_node("generation", generation_node)

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
        "coaching_qa": "generation",
    },
)

for node in [
    "clinical_intercept", "banned_movement", "telemetry_intercept",
    "exercise_history", "exercise_substitution", "program_mutation",
    "catalog_search", "generation",
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


def stream_assistant_turn(state: dict[str, Any]) -> Generator[str, None, None]:
    t_start = time.perf_counter()

    if not state.get("telemetry_context"):
        state.update(hydrate_context_node(state))

    messages = state.get("messages", [])
    if not messages:
        yield "No message received."
        return

    user_id = state.get("trainee_id", "default")
    state.update(router_node(state))
    intent = state.get("intent", "coaching_qa")
    router_ms = (time.perf_counter() - t_start) * 1000.0

    fast_handlers = {
        "telemetry_intercept": telemetry_intercept_node,
        "clinical_intercept": clinical_intercept_node,
        "banned_movement": banned_movement_node,
        "exercise_history": exercise_history_node,
        "exercise_substitution": exercise_substitution_node,
        "program_mutation": program_mutation_node,
        "catalog_search": catalog_search_node,
    }

    if intent in fast_handlers:
        res = fast_handlers[intent](state)
        state.update(res)
        _record_telemetry_event(intent, router_ms, user_id=user_id)
        yield from _stream_text_smoothly(state.get("response_content", ""))
        return

    payload = build_prompt_payload(state)
    accumulated_tokens = []
    t_stream_start = time.perf_counter()
    first_token_time = None
    token_count = 0

    try:
        for chunk in llm.stream(payload):
            if first_token_time is None:
                first_token_time = time.perf_counter()
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            accumulated_tokens.append(token)
            token_count += 1
            yield token

        t_end = time.perf_counter()
        ttft_ms = ((first_token_time - t_stream_start) * 1000.0) if first_token_time else 0.0
        gen_duration_s = (t_end - first_token_time) if first_token_time else 0.0
        tps = (token_count / gen_duration_s) if gen_duration_s > 0 else 0.0

        _record_telemetry_event(
            intent=intent,
            fast_path_ms=router_ms,
            ttft_ms=ttft_ms,
            gen_time_s=gen_duration_s,
            tokens=token_count,
            tps=tps,
            user_id=user_id,
        )
        full_response = scrub_coach_output("".join(accumulated_tokens))
        state["response_content"] = full_response
        state["messages"].append(AIMessage(content=full_response))
    except Exception as e:
        error_msg = f"Inference pipeline failure: {e!s}"
        state["response_content"] = error_msg
        logger.error(f"[TELEMETRY ERROR] User: {user_id} | Failure: {e!s}")
        yield error_msg
