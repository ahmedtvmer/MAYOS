import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Sequence, Optional, Literal, Dict, Any, List, Generator, Tuple
from typing_extensions import TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import DatabaseManager
from agent.program_generator import generate_program_pipeline, extract_frequency_from_text, get_biomechanical_cue
from agent.program_rules import COMPOUND_KEYWORDS
from utils.logger import MyosLogger
from utils.text_scrubber import scrub_coach_output

load_dotenv()
logger = MyosLogger().get_logger(__name__)

db = DatabaseManager()

# -------------------------------------------------------------------------
# Engine Configuration & Token Clamping
# -------------------------------------------------------------------------
llm = ChatOllama(
    model=os.getenv("LLM", "qwen2.5:3b"),
    temperature=0.0,
    num_ctx=4096,
    keep_alive="30m",
    num_predict=200
)

EMBED_MODEL = HuggingFaceEmbeddings(
    model_name=os.getenv("EMBEDDING_MODEL"),
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)

TAIL_WINDOW_SIZE = 6

STATIC_SYSTEM_CORE = """You are Myos, an elite hypertrophy and biomechanics coach.

Core Directives:
- Base all advice on mechanical tension, lengthened-position loading, and stability.
- You have full, direct access to the trainee's database and performance records via the telemetry header below.
- NEVER say 'As an AI...', 'I don't have access to your telemetry', or ask the user to provide details already recorded in telemetry.
- If the user asks how they did, analyze the 'Last Session' telemetry directly.
- Keep answers clear, technical, and actionable. Zero conversational or motivational filler.

Clinical & Biomechanical Guardrails:
- NEVER diagnose medical conditions, injuries, or pain syndromes.
- NEVER instruct a trainee to train through sharp, clicking, radiating, or joint pain.
- NEVER prescribe or validate behind-the-neck pressing/pulldowns or extreme internal rotation rows.
- If joint discomfort is mentioned, immediately cue a biomechanically stable alternative or joint deload.

Output Budget & Structural Constraints:
- Output length must remain concise: strictly 2 to 4 complete, dense sentences or a maximum 3-bullet list.
- Conclude every thought decisively within 80–130 words so generation terminates cleanly before hitting token limits.
- Never trail off, introduce speculative tangents, or append boilerplate conversational wrap-ups."""

# -------------------------------------------------------------------------
# Graph State & Contracts
# -------------------------------------------------------------------------
IntentType = Literal[
    "clinical_intercept",
    "exercise_substitution",
    "program_mutation", 
    "catalog_search", 
    "coaching_qa"
]

class IntentClassification(BaseModel):
    intent: str = Field(
        description="One of: 'exercise_substitution', 'program_mutation', 'catalog_search', 'coaching_qa'"
    )
    source_exercise: Optional[str] = Field(default=None, description="Exercise being replaced or queried")
    target_exercise: Optional[str] = Field(default=None, description="New replacement exercise, if specified")
    target_frequency: Optional[int] = Field(default=None, description="Target frequency if modifying schedule (1-5).")
    search_query: Optional[str] = Field(default=None, description="Search term for movement catalog.")

class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trainee_id: str
    coach_tone: str
    custom_instructions: str
    telemetry_context: Optional[str]
    intent: Optional[IntentType]
    intent_metadata: Dict[str, Any]
    program_updated: bool
    response_content: Optional[str]

# -------------------------------------------------------------------------
# Fast-Path Compiled Patterns & Clinical Safeguards
# -------------------------------------------------------------------------
RE_ACUTE_INJURY = re.compile(
    r"\b("
    r"sharp\s+(?:pain|pop|pull|twinge)|"
    r"shooting\s+pain|"
    r"numb(?:ness)?|tingling|"
    r"pop(?:ped)?|"
    r"tore|tear|torn|"
    r"swell(?:ing)?|swollen|"
    r"pinched\s+nerve|"
    r"hernia|"
    r"dislocat(?:ed|ion)|"
    r"can['']t\s+move\s+my|"
    r"joint\s+clicking\s+with\s+pain"
    r")\b",
    re.IGNORECASE
)

CLINICAL_SAFEGUARD_RESPONSE = (
    "⚠️ **Movement Discontinued & Clinical Safeguard Triggered**\n\n"
    "Acute, sharp, popping, or radiating neural sensations indicate potential soft-tissue "
    "or joint injury. **Myos is an automated training ledger and biomechanics engine, not a physician.**\n\n"
    "- **Cease training the affected movement immediately.**\n"
    "- Do not attempt to work through sharp or radiating pain.\n"
    "- Seek diagnostic evaluation from a licensed sports medicine physician or physical therapist."
)

RE_EXPLICIT_SWAP = re.compile(
    r"\b(?:swap|replace|substitute|switch(?:\s+out)?|change)\b\s+(?P<source>.+?)\s+\b(?:for|with|instead of|to)\b\s+(?P<target>.+)",
    re.IGNORECASE
)
RE_SINGLE_SWAP = re.compile(
    r"(?:(?:i\s+(?:just\s+)?want|show\s+me|give\s+me)\s+)?\b(?:swap|replace|substitute|alternatives?\s+(?:for|to)|switch(?:\s+out)?)\b\s+(?P<source>[a-zA-Z0-9\s\(\)\-\_]+)",
    re.IGNORECASE
)
RE_PROGRAM_MUTATION = re.compile(
    r"\b(rebuild|regenerate|new\s+split|"
    r"(?:change|switch|update)\s+(?:the\s+)?(?:split(?!\s+squat)|routine|program)|"
    r"(\d+)\s*(?:days?|d/wk|days\s+a\s+week))\b",
    re.IGNORECASE
)
RE_FREQ_DIGIT = re.compile(r"\b([1-6])\s*(?:days?|d/wk|days\s+a\s+week)\b", re.IGNORECASE)
RE_SEARCH_TOKENS = re.compile(r"\b(search|find|lookup|show me|list exercises)\b", re.IGNORECASE)

# Ambiguity Trigger: fires only when mutation words exist but exact regex structure failed
RE_ACTION_HINT = re.compile(
    r"\b(swap|replace|substitute|change|split|routine|program|days|rebuild|alternatives?|exercises)\b",
    re.IGNORECASE
)

ROUTER_PROMPT = """Classify the trainee query into EXACTLY one category:
- exercise_substitution: Swapping/changing a specific movement in the routine.
- program_mutation: Rebuilding the split or altering weekly training days.
- catalog_search: Finding or listing movements from the database.
- coaching_qa: Biomechanics, technique cues, session reviews, fatigue, or general gym questions.

Extract entities where present."""

# -------------------------------------------------------------------------
# Coreference Resolver Schema & Helper
# -------------------------------------------------------------------------
class SubstitutionResolution(BaseModel):
    source_exercise: Optional[str] = Field(
        default=None, 
        description="The exact exercise name from the active routine being replaced or queried."
    )
    target_exercise: Optional[str] = Field(
        default=None, 
        description="The replacement exercise the user wants, or None if only asking for ideas."
    )

COREFERENCE_RESOLVER_PROMPT = """You are an entity resolution engine for a fitness app.
The user wants to replace or find alternatives for an exercise, but used a conversational reference (like 'it', 'that', 'choice 2', or a shorthand name).

[Active Routine Exercises]
{active_exercises}

[Recent Conversation]
{chat_history}

User's Query: "{user_query}"

Instructions:
1. Identify `source_exercise`: Which exact exercise from the [Active Routine Exercises] is the user referring to?
2. Identify `target_exercise`: What new exercise did the user choose? (If they said 'choice 3', 'the first one', or named a movement from the previous assistant message, extract the full exercise name. If they are only asking for alternative suggestions, set this to null).

Return ONLY valid structured data."""


def resolve_coreference_with_llm(
    query: str, 
    messages: Sequence[BaseMessage], 
    active_program
) -> Tuple[Optional[str], Optional[str]]:
    """Invokes LLM with conversational context to resolve pronouns and selections."""
    routine_names = []
    for day in active_program.days:
        for ex in day.exercises:
            routine_names.append(f"- {ex.exercise_name} (Day: {day.day_name})")
    active_str = "\n".join(routine_names)

    tail = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-3:]
    chat_lines = [f"{'Trainee' if isinstance(m, HumanMessage) else 'Coach'}: {m.content}" for m in tail]
    chat_str = "\n".join(chat_lines)

    prompt = COREFERENCE_RESOLVER_PROMPT.format(
        active_exercises=active_str,
        chat_history=chat_str,
        user_query=query
    )

    try:
        structured_llm = llm.with_structured_output(SubstitutionResolution)
        res: SubstitutionResolution = structured_llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=query)
        ])
        return res.source_exercise, res.target_exercise
    except Exception as e:
        logger.warning(f"Coreference LLM fallback failed: {e}")
        return None, None

# -------------------------------------------------------------------------
# Node 1: Context Hydration
# -------------------------------------------------------------------------
def hydrate_context_node(state: AssistantState) -> Dict[str, Any]:
    profile = db.get_user_profile() or {}
    telemetry = db.get_compact_telemetry()
    return {
        "coach_tone": profile.get("coach_tone", "Direct, grounded, and pragmatic"),
        "custom_instructions": profile.get("custom_instructions", ""),
        "telemetry_context": telemetry
    }

# -------------------------------------------------------------------------
# Node 2: Tiered Deterministic Router
# -------------------------------------------------------------------------
def router_node(state: AssistantState) -> Dict[str, Any]:
    """
    Tier 0: Clinical red-flag intercept (< 0.1ms).
    Tier 1: High-confidence regex match (< 0.5ms).
    Tier 2: Direct coaching QA pass-through (< 0.5ms).
    Tier 3: Selective LLM fallback (fires only on ambiguous action queries).
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "coaching_qa", "intent_metadata": {}}

    query = messages[-1].content.strip()

    # ====== TIER 0: CLINICAL RED-FLAG INTERCEPTOR (0ms / 0 Tokens) ======
    if RE_ACUTE_INJURY.search(query):
        return {
            "intent": "clinical_intercept",
            "intent_metadata": {"raw_query": query}
        }

    # ====== TIER 1: HIGH-CONFIDENCE REGEX (0ms) ======
    if RE_PROGRAM_MUTATION.search(query):
        freq_match = RE_FREQ_DIGIT.search(query)
        return {
            "intent": "program_mutation",
            "intent_metadata": {"target_frequency": int(freq_match.group(1)) if freq_match else None}
        }

    explicit_match = RE_EXPLICIT_SWAP.search(query)
    if explicit_match:
        data = explicit_match.groupdict()
        src = data["source"].strip()
        tgt = data["target"].strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"] and not RE_FREQ_DIGIT.search(tgt):
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {
                    "mode": "direct_swap",
                    "source_exercise": src,
                    "target_exercise": tgt
                }
            }

    single_match = RE_SINGLE_SWAP.search(query)
    if single_match:
        src = single_match.group("source").strip().rstrip(".!?")
        if src.lower() not in ["split", "routine", "program", "schedule"]:
            return {
                "intent": "exercise_substitution",
                "intent_metadata": {
                    "mode": "lookup_candidates",
                    "source_exercise": src,
                    "target_exercise": None
                }
            }

    if RE_SEARCH_TOKENS.search(query):
        return {
            "intent": "catalog_search",
            "intent_metadata": {"search_query": RE_SEARCH_TOKENS.sub("", query).strip().rstrip(".!?")}
        }

    # ====== TIER 2: PASS-THROUGH CHECK (0ms) ======
    if not RE_ACTION_HINT.search(query):
        return {
            "intent": "coaching_qa",
            "intent_metadata": {}
        }

    # ====== TIER 3: SELECTIVE LLM FALLBACK (1.2s - 1.8s) ======
    try:
        structured_llm = llm.with_structured_output(IntentClassification)
        res: IntentClassification = structured_llm.invoke([
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=query)
        ])

        metadata = {}
        if res.intent == "exercise_substitution":
            src = res.source_exercise
            if not src:
                match = re.search(r"\b(?:for|to|swap|replace|substitute)\s+([a-zA-Z0-9\s\(\)\-\_]+)", query, re.IGNORECASE)
                if match:
                    src = match.group(1).strip()

            metadata = {
                "mode": "direct_swap" if res.target_exercise else "lookup_candidates",
                "source_exercise": src,
                "target_exercise": res.target_exercise
            }
        elif res.intent == "program_mutation":
            metadata = {"target_frequency": res.target_frequency}
        elif res.intent == "catalog_search":
            metadata = {"search_query": res.search_query}

        return {
            "intent": res.intent,
            "intent_metadata": metadata
        }
    except Exception:
        return {
            "intent": "coaching_qa",
            "intent_metadata": {}
        }

# -------------------------------------------------------------------------
# Node 3: Exercise Substitution
# -------------------------------------------------------------------------
STANCE_MODIFIERS = {
    "assisted", "standing", "seated", "lying", "incline", "decline", 
    "flat", "machine", "cable", "barbell", "dumbbell", "lever", "plate", 
    "weighted", "neutral", "grip", "wide", "close", "single", "arm", "leg"
}

def clean_movement_stem(name: str) -> str:
    tokens = re.findall(r"\w+", name.lower())
    core = [t for t in tokens if t not in STANCE_MODIFIERS]
    return " ".join(core) if core else name.lower()

def exercise_substitution_node(state: AssistantState) -> Dict[str, Any]:
    meta = state.get("intent_metadata", {})
    source_name = (meta.get("source_exercise") or "").strip()
    target_desc = (meta.get("target_exercise") or "").strip()
    query = state["messages"][-1].content.strip()

    active_program = db.get_active_program()
    if not active_program:
        return {
            "program_updated": False,
            "response_content": "No active routine found in your ledger. Generate a baseline routine first."
        }

    PRONOUNS = {"it", "this", "that", "them", "choice", "option"}
    source_lower = source_name.lower()

    needs_llm_resolution = (
        not source_name or 
        source_lower in PRONOUNS or 
        len(source_name) < 3 or
        any(word in source_lower for word in ["choice", "option", "number", "first", "second", "third"])
    )

    if needs_llm_resolution:
        resolved_src, resolved_tgt = resolve_coreference_with_llm(
            query=query,
            messages=state.get("messages", []),
            active_program=active_program
        )
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
                SequenceMatcher(None, source_stem, ex_stem).ratio()
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
                        matched_ex, target_day = ex, day
                        best_similarity = 1.0
                        break
            if resolved_tgt:
                target_desc = resolved_tgt

    if not matched_ex or best_similarity < 0.55:
        routine_list = [
            f"- {ex.exercise_name.title()} (Day {d.day_order}: {d.day_name})" 
            for d in active_program.days for ex in d.exercises
        ]
        return {
            "program_updated": False,
            "response_content": (
                f"Could not identify **'{source_name or query}'** in your active split.\n\n"
                f"**Active Movements:**\n" + "\n".join(routine_list)
            )
        }

    mode = "direct_swap" if target_desc else "lookup_candidates"

    cursor = db.catalog_conn.cursor()
    cursor.execute(
        "SELECT body_part, target_muscle, equipment FROM exercises WHERE id = ?",
        (matched_ex.exercise_id,)
    )
    target_meta = cursor.fetchone()
    body_part, target_muscle, equipment = target_meta if target_meta else ("", "", "")

    # BRANCH A: Candidate Lookup ("alternatives for X")
    if mode == "lookup_candidates":
        query_text = f"{target_muscle} {matched_ex.exercise_name}"
        query_vec = EMBED_MODEL.embed_query(query_text)
        raw_candidates = db.search_similar_exercises(query_vec, limit=12)

        valid_candidates = []
        for c in raw_candidates:
            if str(c["id"]) == str(matched_ex.exercise_id):
                continue
            cand_muscle = c.get("target_muscle", "").lower()
            cand_body = c.get("body_part", "").lower()

            if (target_muscle and target_muscle.lower() in cand_muscle) or \
               (cand_body and body_part and cand_body == body_part.lower()):
                valid_candidates.append(c)
            if len(valid_candidates) == 3:
                break

        if not valid_candidates:
            return {
                "program_updated": False,
                "response_content": f"No direct biomechanical alternatives found for **{matched_ex.exercise_name.title()}**."
            }

        lines = [
            f"**Biomechanical Alternatives for {matched_ex.exercise_name.title()}** "
            f"(`{target_muscle.title()}` | `{target_day.day_name}`):"
        ]
        for i, c in enumerate(valid_candidates, start=1):
            is_comp = any(kw in c["name"].lower() for kw in COMPOUND_KEYWORDS) and "calf" not in c["name"].lower()
            cue = get_biomechanical_cue(c["name"], "compound" if is_comp else "isolation")
            lines.append(
                f"{i}. **{c['name'].title()}** (`{c['equipment']}`)\n"
                f"   *Cue:* {cue}"
            )
        lines.append(f"\n*To commit a swap, reply:* `swap {matched_ex.exercise_name} for [Choice]`")

        return {
            "program_updated": False,
            "response_content": "\n".join(lines)
        }

    # BRANCH B: Direct 2-Way Swap ("swap X for Y")
    enhanced_search = f"{target_muscle} {target_desc}"
    query_vec = EMBED_MODEL.embed_query(enhanced_search)
    candidates = db.search_similar_exercises(query_vec, limit=10)

    replacement = None
    for c in candidates:
        if str(c["id"]) == str(matched_ex.exercise_id):
            continue
        cand_muscle = c.get("target_muscle", "").lower()
        cand_body = c.get("body_part", "").lower()

        if target_muscle and (target_muscle.lower() in cand_muscle or cand_muscle in target_muscle.lower()):
            replacement = c
            break
        elif body_part and (body_part.lower() == cand_body):
            replacement = c
            break

    if not replacement:
        return {
            "program_updated": False,
            "response_content": f"Could not find a biomechanically suitable match for **'{target_desc}'** targeting {target_muscle}."
        }

    is_compound = any(kw in replacement["name"].lower() for kw in COMPOUND_KEYWORDS) and "calf" not in replacement["name"].lower()
    mechanic = "compound" if is_compound else "isolation"
    new_cue = get_biomechanical_cue(replacement["name"], mechanic)

    success = db.swap_program_exercise(
        old_exercise_id=matched_ex.exercise_id,
        new_exercise_id=str(replacement["id"]),
        new_notes=new_cue,
        day_id=None
    )

    if success:
        msg = (
            f"✅ **Routine Slot Updated ({target_day.day_name})**\n\n"
            f"- **Removed:** {matched_ex.exercise_name.title()}\n"
            f"- **Installed:** {replacement['name'].title()} (`{replacement['target_muscle']}` | `{replacement['equipment']}`)\n"
            f"- **Execution Directive:** *{new_cue}*"
        )
        return {"program_updated": True, "response_content": msg}

    return {
        "program_updated": False,
        "response_content": "Database error: unable to update program slot in SQLite ledger."
    }

# -------------------------------------------------------------------------
# Node 4: Program Mutation
# -------------------------------------------------------------------------
def program_mutation_node(state: AssistantState) -> Dict[str, Any]:
    query = state["messages"][-1].content
    meta = state.get("intent_metadata", {})
    freq = meta.get("target_frequency") or extract_frequency_from_text(query)

    try:
        prog, _ = generate_program_pipeline(
            user_split_override=query,
            frequency_override=freq
        )
        db.clear_chat_history()
        
        msg = f"Rebuilt routine: **{prog.program_name}** ({prog.weekly_frequency} Days/Week). Context cleared for new routine."
        return {"program_updated": True, "response_content": msg}
    except Exception as e:
        logger.error(f"Mutation failure: {e}")
        return {"program_updated": False, "response_content": "Could not rebuild split with those parameters."}

# -------------------------------------------------------------------------
# Node 5: Catalog Search
# -------------------------------------------------------------------------
def catalog_search_node(state: AssistantState) -> Dict[str, Any]:
    query = state.get("intent_metadata", {}).get("search_query") or state["messages"][-1].content
    try:
        vector = EMBED_MODEL.embed_query(query)
        candidates = db.search_similar_exercises(vector, limit=4)

        if not candidates or candidates[0].get("distance", 1.0) > 0.85:
            return {"response_content": f"No exercises matching '{query}' were found in the catalog."}

        formatted = [
            f"- **{c['name'].title()}** (`{c['target_muscle']}` | `{c['equipment']}`)\n  *{c['instructions'][:120]}...*"
            for c in candidates
        ]
        res = f"**Catalog Matches for '{query}':**\n\n" + "\n\n".join(formatted)
        return {"response_content": res}
    except Exception as e:
        logger.error(f"Catalog search error: {e}")
        return {"response_content": "Failed to search the exercise catalog."}

# -------------------------------------------------------------------------
# Node 6: Clinical Intercept Node
# -------------------------------------------------------------------------
def clinical_intercept_node(state: AssistantState) -> Dict[str, Any]:
    """Zero-LLM safeguard node for acute pain or potential injury queries."""
    return {
        "program_updated": False,
        "response_content": CLINICAL_SAFEGUARD_RESPONSE
    }

# -------------------------------------------------------------------------
# Node 7: Unified Coaching & Science QA Generation
# -------------------------------------------------------------------------
def build_prompt_payload(state: AssistantState) -> List[BaseMessage]:
    """Builds static-to-dynamic prefix-cached prompt payload."""
    coach_tone = state.get("coach_tone", "Direct, grounded, and pragmatic")
    custom_directives = state.get("custom_instructions", "")
    telemetry = state.get("telemetry_context", "")

    prompt_parts = [STATIC_SYSTEM_CORE]

    persona_block = f"\n[COACHING DIRECTIVES]\nTone: {coach_tone}"
    if custom_directives.strip():
        persona_block += f"\nCustom Directives: {custom_directives.strip()}"
    prompt_parts.append(persona_block)

    if telemetry:
        prompt_parts.append(f"\n{telemetry}")

    full_system_prompt = "\n".join(prompt_parts)

    raw_messages = state.get("messages", [])
    dialogue_messages = [
        m for m in raw_messages 
        if isinstance(m, (HumanMessage, AIMessage))
    ]
    clamped_tail = dialogue_messages[-TAIL_WINDOW_SIZE:]

    return [SystemMessage(content=full_system_prompt), *clamped_tail]

def generation_node(state: AssistantState) -> Dict[str, Any]:
    payload = build_prompt_payload(state)
    response = llm.invoke(payload)
    cleaned_content = scrub_coach_output(response.content)
    return {"response_content": cleaned_content, "program_updated": False}

# -------------------------------------------------------------------------
# Graph Assembly (.invoke() Compatible)
# -------------------------------------------------------------------------
builder = StateGraph(AssistantState)

builder.add_node("hydrate_context", hydrate_context_node)
builder.add_node("router", router_node)
builder.add_node("clinical_intercept", clinical_intercept_node)
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
        "exercise_substitution": "exercise_substitution",
        "program_mutation": "program_mutation",
        "catalog_search": "catalog_search",
        "coaching_qa": "generation"
    }
)

builder.add_edge("clinical_intercept", END)
builder.add_edge("exercise_substitution", END)
builder.add_edge("program_mutation", END)
builder.add_edge("catalog_search", END)
builder.add_edge("generation", END)

assistant_graph = builder.compile()

# -------------------------------------------------------------------------
# Token Streaming Generator Adapter
# -------------------------------------------------------------------------
def stream_assistant_turn(state: Dict[str, Any]) -> Generator[str, None, None]:
    """
    Streaming generator adapter for real-time UI token streaming.
    - Intercepts acute injuries and clinical red flags deterministically (0 LLM tokens).
    - Executes program mutations, substitutions, and catalog searches without streaming.
    - Streams tokens dynamically via llm.stream() only for valid coaching QA.
    """
    if not state.get("telemetry_context"):
        hydration = hydrate_context_node(state)  # type: ignore
        state.update(hydration)

    r_out = router_node(state)  # type: ignore
    state.update(r_out)
    intent = state.get("intent", "coaching_qa")

    if intent == "clinical_intercept":
        intercept_res = clinical_intercept_node(state)  # type: ignore
        state.update(intercept_res)
        yield state.get("response_content", CLINICAL_SAFEGUARD_RESPONSE)
        return

    if intent == "exercise_substitution":
        sub_res = exercise_substitution_node(state)  # type: ignore
        state.update(sub_res)
        yield state.get("response_content", "Exercise substitution executed.")
        return

    if intent == "program_mutation":
        mut_res = program_mutation_node(state)  # type: ignore
        state.update(mut_res)
        yield state.get("response_content", "Routine rebuilt.")
        return

    if intent == "catalog_search":
        cat_res = catalog_search_node(state)  # type: ignore
        state.update(cat_res)
        yield state.get("response_content", "Catalog search complete.")
        return

    payload = build_prompt_payload(state)  # type: ignore
    chunks: List[str] = []
    for chunk in llm.stream(payload):
        if chunk.content:
            chunks.append(chunk.content)
            yield chunk.content

    raw_text = "".join(chunks)
    state["response_content"] = scrub_coach_output(raw_text)
    state["program_updated"] = False