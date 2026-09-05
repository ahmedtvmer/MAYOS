import os
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from agent.UserState import OnboardingState, UserProfileSchema
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger(__name__)

db = DatabaseManager()
llm = ChatOllama(model=os.getenv("LLM"), temperature=0.0)

def ask_questions(state: OnboardingState) -> dict:
    step = state.get("intake_step", 1)
    
    prompts = {
        1: "Welcome to Myos. Let's set up your profile.\n"
           "1. Who is taller/longer: your upper body or lower body?\n"
           "2. What is your gender (male/female), age, weight (kg), and height (cm)?",
        2: "Got it. Next up: goals and volume capacity.\n"
           "3. What is your current primary goal?\n"
           "4. What is your long-term goal?\n"
           "5. How many days per week can you realistically commit?\n"
           "6. What is your training age (how many years of lifting)?",
        3: "Last section: logistics and recovery.\n"
           "7. What equipment do you have access to?\n"
           "8. Do you have any injuries or joint issues?\n"
           "9. How is your job/daily stress and average sleep quality?"
    }

    prompt_text = prompts.get(step, "All intake questions completed.")
    return {"messages": [AIMessage(content=prompt_text)]}

def parse_and_advance(state: OnboardingState) -> dict:
    current_step = state.get("intake_step", 1)
    next_step = current_step + 1
    is_complete = next_step > 3
    return {"intake_step": next_step, "is_complete": is_complete}

def save_profile_node(state: OnboardingState) -> dict:
    logger.info("Extracting structured profile data from conversation history...")
    
    # 1. Deterministic extraction safeguard for gender from raw user messages
    user_text_corpus = " ".join([
        msg.content.lower() 
        for msg in state["messages"] 
        if isinstance(msg, HumanMessage)
    ])
    detected_gender = "female" if "female" in user_text_corpus or "woman" in user_text_corpus else "male"

    # 2. Comprehensive extraction prompt
    extraction_prompt = [
        SystemMessage(content=(
            "Extract the trainee's profile from the conversation history into the structured schema.\n"
            "CRITICAL FIELDS:\n"
            "- gender: strictly 'female' or 'male' (inspect the conversation closely)\n"
            "- proportions: 'long_legs', 'long_torso', or 'balanced'\n"
            "- age, weight_kg, height_cm: clean numeric values\n"
            "- weekly_frequency: integer (1 to 5)\n"
            "- current_goal, long_term_goal, equipment_access, injuries_or_limitations, stress_and_sleep\n"
            "- rep_preference: 'low', 'balanced', or 'high'"
        )),
        *state["messages"],
        HumanMessage(content="Extract and return the completed profile schema now.")
    ]
    
    structured_llm = llm.with_structured_output(UserProfileSchema)
    extracted_profile: UserProfileSchema = structured_llm.invoke(extraction_prompt)
    
    # Python override: Guarantee explicit user intent overrides LLM hallucination/defaults
    extracted_profile.gender = detected_gender
    
    # Persist to database
    db.upsert_user_profile(extracted_profile.model_dump())
    logger.info(f"Profile saved to SQLite successfully (Gender: {extracted_profile.gender}).")

    return {
        "profile_data": extracted_profile.model_dump(),
        "messages": [AIMessage(content=f"Profile setup complete ({extracted_profile.gender.capitalize()} specialization active). Calibrating program...")]
    }

def entry_router(state: OnboardingState) -> str:
    messages = state.get("messages", [])
    # If starting fresh or last message was from AI, prompt the user
    if not messages or isinstance(messages[-1], AIMessage):
        return "ask_questions"
    # User sent a message, advance step
    return "parse_and_advance"

def route_after_advance(state: OnboardingState) -> str:
    if state.get("is_complete", False):
        return "save_profile"
    return "ask_questions"

# Build Graph
builder = StateGraph(OnboardingState)

builder.add_node("ask_questions", ask_questions)
builder.add_node("parse_and_advance", parse_and_advance)
builder.add_node("save_profile", save_profile_node)

# Conditional Entry Point
builder.set_conditional_entry_point(
    entry_router,
    {
        "ask_questions": "ask_questions",
        "parse_and_advance": "parse_and_advance"
    }
)

# Edges
builder.add_edge("ask_questions", END)
builder.add_conditional_edges(
    "parse_and_advance",
    route_after_advance,
    {
        "ask_questions": "ask_questions",
        "save_profile": "save_profile"
    }
)
builder.add_edge("save_profile", END)

onboarding_graph = builder.compile()