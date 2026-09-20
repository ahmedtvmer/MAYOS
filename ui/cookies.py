"""Browser-cookie persistence for sign-in sessions (consented; see ADR 010).

Only the bearer JWT is stored, and only after the trainee opts in via the
"Remember me" checkbox. Every operation is best-effort: if the cookie component
is unavailable the app silently falls back to in-memory session state.
"""

import base64
import json
from typing import Any

import streamlit as st

COOKIE_NAME = "mayos_jwt"
STATE_KEY = "cookie_manager"


def parse_jwt_subject(token: str) -> str | None:
    """Unverified read of the JWT ``sub`` claim for display/gating only.

    Every bearer call is verified server-side; this never grants access by itself.
    """
    try:
        payload = str(token).split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        subject = claims.get("sub")
        return str(subject) if subject else None
    except Exception:
        return None


def mount_cookies() -> Any | None:
    """Mounts the cookie component for this run; blocks one frame until it is ready.

    A fresh manager is constructed every run: the constructor syncs cookies through
    the component and keeps its write queue in session state, so a cached instance
    would never see cookies that arrive after the first frame. The current run's
    instance is parked in session state for same-run set/clear calls.
    """
    try:
        from streamlit_cookies_manager import CookieManager
    except Exception:
        st.session_state[STATE_KEY] = None
        return None
    try:
        manager = CookieManager()
    except Exception:
        st.session_state[STATE_KEY] = None
        return None
    st.session_state[STATE_KEY] = manager
    if not manager.ready():
        st.spinner("Connecting…")
        st.stop()
    return manager


def apply_auth_cookie(cookies: Any | None, token: str) -> None:
    if cookies is None or not token:
        return
    try:
        cookies[COOKIE_NAME] = token
        cookies.save()
    except Exception:
        pass


def remove_auth_cookie(cookies: Any | None) -> None:
    if cookies is None:
        return
    try:
        if COOKIE_NAME in cookies:
            del cookies[COOKIE_NAME]
            cookies.save()
    except Exception:
        pass
