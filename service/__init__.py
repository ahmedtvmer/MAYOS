"""Backend service layer shared by the Streamlit UI and the FastAPI service.

Every function takes an explicit ``DatabaseManager`` (and ``trainee_id``
where user-scoped) and returns plain data. No Streamlit imports allowed here.
"""

from service import auth, chat, dashboard, onboarding, profile, programs, workouts

__all__ = ["auth", "chat", "dashboard", "onboarding", "profile", "programs", "workouts"]
