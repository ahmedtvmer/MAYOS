from langchain_core.tools import tool
from agent.state import UserProfileSchema
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger("agent_tools")
db = DatabaseManager()

@tool(args_schema=UserProfileSchema)
def save_user_profile(
    proportions: str,
    age: int,
    weight_kg: float,
    height_cm: float,
    current_goal: str,
    long_term_goal: str,
    weekly_frequency: int,
    training_age_years: float,
    equipment_access: str,
    stress_and_sleep: str,
    injuries_or_limitations: str = "None"
) -> str:
    """
    Saves the user's physical profile, goals, constraints, and recovery metrics to the database.
    Call this once all 9 onboarding profile questions have been collected from the user.
    """
    profile_data = {
        "proportions": proportions,
        "age": age,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "current_goal": current_goal,
        "long_term_goal": long_term_goal,
        "weekly_frequency": weekly_frequency,
        "training_age_years": training_age_years,
        "equipment_access": equipment_access,
        "injuries_or_limitations": injuries_or_limitations,
        "stress_and_sleep": stress_and_sleep
    }
    
    try:
        db.upsert_user_profile(profile_data)
        logger.info("User profile successfully upserted into SQLite.")
        return "User profile successfully saved and locked into database."
    except Exception as e:
        logger.error(f"Failed to save profile: {e}")
        return f"Database error while saving profile: {str(e)}"