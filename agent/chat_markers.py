"""Shared session-commit chat marker (ADR 033/036).

A committed workout writes one assistant "session logged" pointer into the
player's chat history (``service/workouts.py``). That exact line must be
recognised in two places — the assistant prompt builder trims it so it never
enters model context, and ``GET /chat/history`` labels it for the client — so
the pattern lives here once rather than in each reader.
"""

import re

#: Matches the assistant session-logged pointer written at commit; the exact
#: wording is produced by ``service/workouts.py``.
SESSION_POINTER_PATTERN = re.compile(
    r"[^\w]*\*\*Session Logged:\*\* .+ \(\d{4}-\d{2}-\d{2}\) \| \d+ Sets \| "
    r"Volume: [\d,.]+ kg \| Readiness: [1-5]/5 \| Saved to Ledger\."
)


def is_session_pointer_text(text: str) -> bool:
    """True when ``text`` is exactly the assistant session-logged pointer."""
    return bool(SESSION_POINTER_PATTERN.fullmatch(text))


def chat_message_kind(role: str, content: str) -> str:
    """The wire ``kind`` for one stored message: ``debrief`` or ``message``."""
    if role == "assistant" and is_session_pointer_text(content):
        return "debrief"
    return "message"
