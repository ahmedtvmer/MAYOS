import re
from typing import Annotated, Sequence, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class UserProfileSchema(BaseModel):
    # Proportions & Biometrics
    proportions: str = Field(description="Limb-to-torso proportions: 'long_legs', 'long_torso', or 'balanced'")
    age: int = Field(ge=12, le=100)
    weight_kg: float = Field(gt=30.0, lt=200.0)
    height_cm: float = Field(gt=100.0, lt=210.0)
    
    # Goals & Volume Capacity
    current_goal: str = Field(description="Immediate training objective")
    long_term_goal: str = Field(description="Longer-term strength/physique target")
    weekly_frequency: int = Field(ge=1, le=7)
    training_age_years: float = Field(ge=0.0)
    
    # Logistics & Systemic Recovery
    equipment_access: str = Field(description="Available equipment or gym type")
    injuries_or_limitations: Optional[str] = Field(default="None")
    stress_and_sleep: str = Field(description="Daily stress level and average sleep quality")

    @field_validator("proportions", mode="before")
    @classmethod
    def parse_proportions(cls, v):
        if isinstance(v, dict):
            v = v.get("value", str(v))
        v_str = str(v).lower()
        if "lower" in v_str or "leg" in v_str:
            return "long_legs"
        if "upper" in v_str or "torso" in v_str:
            return "long_torso"
        return "balanced"

    @field_validator("age", "weekly_frequency", mode="before")
    @classmethod
    def sanitize_int(cls, v):
        if isinstance(v, dict):
            v = v.get("value", v)
        if isinstance(v, str):
            # Extract first integer sequence (e.g. "21 years old" -> 21)
            match = re.search(r"\d+", v)
            if match:
                return int(match.group(0))
        return v

    @field_validator("weight_kg", "height_cm", "training_age_years", mode="before")
    @classmethod
    def sanitize_float(cls, v):
        if isinstance(v, dict):
            v = v.get("value", v)
        if isinstance(v, str):
            # Extract float sequence (e.g. "82.5 kg" -> 82.5)
            match = re.search(r"\d+(\.\d+)?", v)
            if match:
                return float(match.group(0))
        return v

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    profile: Optional[dict]  # Store raw dict for SQLite checkpointer serialization
    active_session_id: Optional[str]
    intake_step: int         # 0: unstarted, 1: biometrics, 2: goals, 3: constraints, 4: complete