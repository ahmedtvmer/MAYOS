"""Backend service layer used by the FastAPI service.

Every function takes an explicit ``DatabaseManager`` (and ``ledger_id``
where user-scoped) and returns plain data.
"""

from service import auth, chat, dashboard, onboarding, profile, programs, workouts

__all__ = ["auth", "chat", "dashboard", "onboarding", "profile", "programs", "workouts"]
