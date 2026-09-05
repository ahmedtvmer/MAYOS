import os
import re
from difflib import SequenceMatcher 
from typing import Annotated, Sequence, Optional, Literal, Dict, Any, List
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from database.database_manager import DatabaseManager
from agent.program_generator import generate_program_pipeline, extract_frequency_from_text
from agent.program_generator import get_biomechanical_cue
from agent.program_rules import COMPOUND_KEYWORDS
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger(__name__)

db = DatabaseManager()
llm = ChatOllama(model=os.getenv("LLM"), temperature=0.0)

# -------------------------------------------------------------------------
# Graph State & Contracts
# -------------------------------------------------------------------------
IntentType = Literal[
    "program_mutation", 
    "exercise_substitution",
    "catalog_search", 
    "research_qa", 
    "coaching_qa", 
    "fallback"
]

class IntentClassification(BaseModel):
    intent: IntentType = Field(description="Classify into exactly one intent.")
    confidence: float = Field(ge=0.0, le=1.0)
    exercise_to_replace: Optional[str] = Field(
        default=None, 
        description="Name of the exercise the trainee wants to remove or replace."
    )
    replacement_target: Optional[str] = Field(
        default=None, 
        description="Name, equipment, or description of the desired new movement."
    )
    target_frequency: Optional[int] = Field(default=None)
    rep_preference: Optional[Literal["low", "balanced", "high"]] = Field(default=None)
    search_query: Optional[str] = Field(default=None)
    
class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trainee_id: str
    coach_tone: str
    custom_instructions: str
    intent: Optional[IntentType]
    intent_metadata: Dict[str, Any]
    retrieved_context: Optional[str]
    program_updated: bool
    response_content: Optional[str]

# -------------------------------------------------------------------------
# Node 1: Context Hydration
# -------------------------------------------------------------------------
def hydrate_context_node(state: AssistantState) -> Dict[str, Any]:
    profile = db.get_user_profile() or {}
    return {
        "coach_tone": profile.get("coach_tone", "Direct, grounded, and pragmatic"),
        "custom_instructions": profile.get("custom_instructions", "")
    }

# -------------------------------------------------------------------------
# Node 2: Fast Router with Heuristic Fallback
# -------------------------------------------------------------------------
RESEARCH_TOKENS = re.compile(r"\b(study|studies|paper|research|evidence|pubmed|literature|data shows)\b", re.IGNORECASE)
MUTATION_TOKENS = re.compile(r"\b(switch to|change split|days a week|train \d days|split to|make it \d day)\b", re.IGNORECASE)
SUBSTITUTION_TOKENS = re.compile(
    r"\b(?:swap|replace|substitute|switch(?:\s+out)?|change)\b\s+(?P<source>.+?)\s+\b(?:for|with|instead of|to)\b\s+(?P<target>.+)",
    re.IGNORECASE
)

ROUTER_PROMPT = """You are the intent classifier for the Myos training engine.
Analyze the user's latest query and classify it into EXACTLY ONE category:

- program_mutation: Adjusting frequency (e.g. '3 days'), split type, or volume.
- catalog_search: Asking to find, show, or list physical exercises or gym equipment.
- research_qa: Explicitly citing or asking about scientific literature, studies, or research data.
- coaching_qa: Direct technical questions on exercise execution, form cues, injury avoidance, fatigue, or recovery.
- fallback: Creative writing (poems, stories), general chit-chat, non-lifting topics, or completely ambiguous requests.

Return ONLY the structured classification.
"""

def router_node(state: AssistantState) -> Dict[str, Any]:
    query = state["messages"][-1].content.strip()

    # Deterministic substitution check
    if SUBSTITUTION_TOKENS.search(query):
        structured_llm = llm.with_structured_output(IntentClassification)
        try:
            res = structured_llm.invoke([
                SystemMessage(content=(
                    "Extract the exercise to replace and the replacement target from the user query.\n"
                    "Example: 'Swap leg press for hack squat' -> exercise_to_replace: 'leg press', replacement_target: 'hack squat'."
                )),
                HumanMessage(content=query)
            ])
            return {
                "intent": "exercise_substitution",
                "intent_metadata": res.model_dump()
            }
        except Exception:
            pass

    if RESEARCH_TOKENS.search(query):
        return {
            "intent": "research_qa",
            "intent_metadata": {"search_query": query, "confidence": 1.0}
        }

    if MUTATION_TOKENS.search(query):
        return {
            "intent": "program_mutation",
            "intent_metadata": {
                "target_frequency": extract_frequency_from_text(query),
                "confidence": 0.95
            }
        }

    structured_llm = llm.with_structured_output(IntentClassification)
    try:
        classification: IntentClassification = structured_llm.invoke([
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content=query)
        ])
        intent = classification.intent
        metadata = classification.model_dump()
    except Exception as e:
        logger.warning(f"Routing parser failed ({e}). Defaulting to coaching_qa.")
        intent = "coaching_qa" if len(query.split()) > 3 else "fallback"
        metadata = {"confidence": 0.5}

    return {"intent": intent, "intent_metadata": metadata}

# -------------------------------------------------------------------------
# Node 2: Exercise Substitution
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
    source_name = (meta.get("exercise_to_replace") or "").strip().lower()
    target_desc = (meta.get("replacement_target") or "").strip()
    
    active_program = db.get_active_program()
    if not active_program:
        msg = "No active program found in your ledger. Generate a baseline routine first."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    # 1. High-Confidence Exercise Matching
    matched_ex = None
    target_day = None
    best_similarity = 0.0
    source_stem = clean_movement_stem(source_name)

    for day in active_program.days:
        for ex in day.exercises:
            ex_name_clean = ex.exercise_name.lower()
            ex_stem = clean_movement_stem(ex_name_clean)

            # A. Exact substring check on stems
            if source_stem and (source_stem in ex_stem or ex_stem in source_stem):
                matched_ex = ex
                target_day = day
                best_similarity = 1.0
                break

            # B. Sequence matcher against full name and stem
            sim = max(
                SequenceMatcher(None, source_name, ex_name_clean).ratio(),
                SequenceMatcher(None, source_stem, ex_stem).ratio()
            )

            if sim > best_similarity:
                best_similarity = sim
                candidate_match = ex
                candidate_day = day

        if best_similarity == 1.0:
            break

    # Hard confidence threshold (>= 0.55 prevents cross-pattern false positives)
    if not matched_ex and best_similarity >= 0.55:
        matched_ex = candidate_match
        target_day = candidate_day

    if not matched_ex:
        routine_list = [f"- {ex.exercise_name} (Day {d.day_order}: {d.day_name})" for d in active_program.days for ex in d.exercises]
        msg = (
            f"Could not identify **'{source_name}'** in your active routine.\n\n"
            f"**Current exercises in your program:**\n" + "\n".join(routine_list)
        )
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    # 2. Fetch Muscle Metadata from Catalog for Context Locking
    cursor = db.catalog_conn.cursor()
    cursor.execute("SELECT body_part, target_muscle, equipment FROM exercises WHERE id = ?", (matched_ex.exercise_id,))
    target_meta = cursor.fetchone()
    body_part, target_muscle, current_equip = target_meta if target_meta else ("", "", "")

    # 3. Contextualize Replacement Query
    # If the user says "another machine" or "cable", anchor the query with the target muscle
    enhanced_search_query = f"{target_muscle} {target_desc}" if target_desc else f"{target_muscle} {matched_ex.exercise_name}"
    query_vec = EMBED_MODEL.embed_query(enhanced_search_query)

    # 4. Semantic Search + Target Muscle Enforcement
    candidates = db.search_similar_exercises(query_vec, limit=10)
    
    replacement = None
    for c in candidates:
        # Prevent self-substitution
        if str(c["id"]) == str(matched_ex.exercise_id):
            continue

        # Reject cross-pattern shifts: match must share body_part or target_muscle
        cand_muscle = c.get("target_muscle", "").lower()
        cand_body = c.get("body_part", "").lower()

        if target_muscle and (target_muscle.lower() in cand_muscle or cand_muscle in target_muscle.lower()):
            replacement = c
            break
        elif body_part and (body_part.lower() == cand_body):
            replacement = c
            break

    if not replacement:
        msg = f"Could not find an alternative for **{matched_ex.exercise_name}** ({target_muscle}) matching '{target_desc}'."
        return {"program_updated": False, "response_content": msg, "messages": [AIMessage(content=msg)]}

    # 5. Recompute Biomechanical Cue
    name_lower = replacement["name"].lower()
    is_compound = any(kw in name_lower for kw in COMPOUND_KEYWORDS) and "calf" not in name_lower
    mechanic = "compound" if is_compound else "isolation"
    new_cue = get_biomechanical_cue(replacement["name"], mechanic)

    # 6. Atomic Slot Update in SQLite
    success = db.swap_program_exercise(
        old_exercise_id=matched_ex.exercise_id,
        new_exercise_id=str(replacement["id"]),
        new_notes=new_cue,
        day_id=None
    )

    if success:
        msg = (
            f"Successfully updated **{target_day.day_name}**:\n"
            f"- **Replaced:** {matched_ex.exercise_name.title()}\n"
            f"- **New Movement:** {replacement['name'].title()} ({replacement['target_muscle']} | {replacement['equipment']})\n"
            f"- **Execution Directive:** *{new_cue}*"
        )
        return {
            "program_updated": True,
            "response_content": msg,
            "messages": [AIMessage(content=msg)]
        }
    else:
        err = "Database write failed while updating the exercise slot."
        return {"program_updated": False, "response_content": err, "messages": [AIMessage(content=err)]}# -------------------------------------------------------------------------

# Node 3: Program Mutation
# -------------------------------------------------------------------------
def program_mutation_node(state: AssistantState) -> Dict[str, Any]:
    query = state["messages"][-1].content
    meta = state.get("intent_metadata", {})
    freq = meta.get("target_frequency") or extract_frequency_from_text(query)
    rep_pref = meta.get("rep_preference")

    try:
        prog, _ = generate_program_pipeline(
            user_split_override=query,
            rep_preference_override=rep_pref,
            frequency_override=freq
        )
        msg = f"Updated your routine to **{prog.program_name}** ({prog.weekly_frequency} Days/Week). The **Program & Dashboard** tab reflects your updated plan."
        return {
            "program_updated": True,
            "response_content": msg,
            "messages": [AIMessage(content=msg)]
        }
    except Exception as e:
        logger.error(f"Mutation failure: {e}")
        err = "Could not modify routine with those parameters. Existing schedule remains active."
        return {
            "program_updated": False,
            "response_content": err,
            "messages": [AIMessage(content=err)]
        }

EMBED_MODEL = HuggingFaceEmbeddings(
    model_name=os.getenv("EMBEDDING_MODEL"),
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)

# -------------------------------------------------------------------------
# Node 4: Catalog Vector Retrieval
# -------------------------------------------------------------------------
def catalog_search_node(state: AssistantState) -> Dict[str, Any]:
    query = state.get("intent_metadata", {}).get("search_query") or state["messages"][-1].content
    try:
        # Use module-level singleton
        vector = EMBED_MODEL.embed_query(query)
        candidates = db.search_similar_exercises(vector, limit=3)

        if not candidates:
            return {
                "retrieved_context": None,
                "response_content": "No exercises matching that description were found in the catalog.",
                "messages": [AIMessage(content="No exercises matching that description were found in the catalog.")]
            }

        # Calibrated threshold for normalized BGE embeddings (Cosine distance <= 0.85)
        best_distance = candidates[0].get("distance", 1.0)
        if best_distance > 0.85:
            return {
                "intent": "fallback",
                "retrieved_context": None
            }

        formatted = []
        for c in candidates:
            formatted.append(
                f"- **{c['name'].title()}** ({c['target_muscle']} | {c['equipment']})\n"
                f"  Execution: {c['instructions'][:140]}..."
            )

        context_str = "Matching Catalog Exercises:\n" + "\n".join(formatted)
        return {
            "retrieved_context": context_str,
            "response_content": context_str,
            "messages": [AIMessage(content=context_str)]
        }

    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return {"retrieved_context": None, "intent": "fallback"}

# -------------------------------------------------------------------------
# Node 5: Constrained Research Context Node
# -------------------------------------------------------------------------
def research_search_node(state: AssistantState) -> Dict[str, Any]:
    """
    Supplies compact literature boundaries to prevent hallucinations.
    """
    query = state["messages"][-1].content
    # Safe literature bounds for standard hypertrophy/strength inquiries
    research_summary = (
        "Literature Grounding (Schoenfeld et al., Helms et al.):\n"
        "- Hypertrophy per-set yield is equivalent across 6-30 reps when sets are taken within 0-2 RIR.\n"
        "- Lengthened-position overload and high mechanical stability yield higher hypertrophy per unit of fatigue.\n"
        "- Minimum effective volume starts at ~4-6 hard sets per muscle/week; optimal adaptive volume is typically 10-15 sets/week."
    )
    return {"retrieved_context": research_summary}

# -------------------------------------------------------------------------
# Node 6: Primary Response Generation (Single-Pass Injection)
# -------------------------------------------------------------------------
def generation_node(state: AssistantState) -> Dict[str, Any]:
    coach_tone = state.get("coach_tone", "Direct, grounded, and pragmatic")
    custom_directives = state.get("custom_instructions", "")
    retrieved = state.get("retrieved_context")

    system_prompt = (
        "You are Myos, an expert hypertrophy and biomechanics coach.\n"
        f"Tone Directive: {coach_tone}.\n"
    )
    if custom_directives.strip():
        system_prompt += f"Mandatory User Rules: {custom_directives.strip()}\n"

    system_prompt += (
        "\nProvide direct, practical guidance based on mechanical tension and stability-first execution. "
        "Keep answers concise and devoid of motivational fluff."
    )

    if retrieved:
        system_prompt += f"\n\nContext Data to Use:\n{retrieved}"

    payload = [SystemMessage(content=system_prompt), *state["messages"]]
    response = llm.invoke(payload)

    return {
        "response_content": response.content,
        "messages": [AIMessage(content=response.content)]
    }

# -------------------------------------------------------------------------
# Node 7: Fallback & Clarification Node
# -------------------------------------------------------------------------
def fallback_node(state: AssistantState) -> Dict[str, Any]:
    clarification = (
        "Could not resolve the exact training request. You can:\n"
        "- Modify routine: *'Switch to 3 days a week'* or *'Run Upper/Lower'*\n"
        "- Find movements: *'Search cable exercises for rear delts'*\n"
        "- Form & setup: *'How do I set the seat height on the hack squat?'*"
    )
    return {
        "response_content": clarification,
        "messages": [AIMessage(content=clarification)]
    }

# -------------------------------------------------------------------------
# Conditional Edge Dispatchers
# -------------------------------------------------------------------------
def route_initial_intent(state: AssistantState) -> str:
    intent = state.get("intent")
    if intent == "program_mutation":
        return "program_mutation"
    elif intent == "exercise_substitution":
        return "exercise_substitution"
    elif intent == "catalog_search":
        return "catalog_search"
    elif intent == "research_qa":
        return "research_search"
    elif intent == "coaching_qa":
        return "generation"
    return "fallback"

def route_post_retrieval(state: AssistantState) -> str:
    if state.get("intent") == "fallback" or not state.get("retrieved_context"):
        return "fallback"
    return "generation"

# -------------------------------------------------------------------------
# Graph Construction
# -------------------------------------------------------------------------
builder = StateGraph(AssistantState)

builder.add_node("exercise_substitution", exercise_substitution_node)
builder.add_node("hydrate_context", hydrate_context_node)
builder.add_node("router", router_node)
builder.add_node("program_mutation", program_mutation_node)
builder.add_node("catalog_search", catalog_search_node)
builder.add_node("research_search", research_search_node)
builder.add_node("generation", generation_node)
builder.add_node("fallback", fallback_node)

builder.set_entry_point("hydrate_context")
builder.add_edge("hydrate_context", "router")

builder.add_conditional_edges(
    "router",
    route_initial_intent,
    {
        "program_mutation": "program_mutation",
        "exercise_substitution": "exercise_substitution",
        "catalog_search": "catalog_search",
        "research_search": "research_search",
        "generation": "generation",
        "fallback": "fallback"
    }
)

builder.add_conditional_edges(
    "catalog_search",
    route_post_retrieval,
    {
        "generation": "generation",
        "fallback": "fallback"
    }
)

builder.add_edge("research_search", "generation")
builder.add_edge("program_mutation", END)
builder.add_edge("generation", END)
builder.add_edge("fallback", END)
builder.add_edge("exercise_substitution", END)

assistant_graph = builder.compile()