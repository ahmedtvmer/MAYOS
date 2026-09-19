"""Streamlit session-state orchestration: init, establish, flash, and clear."""

import httpx
import streamlit as st

from ui.api_client import API_BASE_URL, REQUEST_TIMEOUT


def flash(message: str, level: str = "info") -> None:
    """Queues a one-shot message rendered by the next ``consume_flash()``."""
    st.session_state["flash_message"] = {"level": level, "message": message}


def consume_flash() -> None:
    """Renders and clears the queued flash message, if any."""
    entry = st.session_state.pop("flash_message", None)
    if not entry:
        return
    message = str(entry.get("message", ""))[:300]
    level = str(entry.get("level", "info"))
    renderer = {"success": st.success, "warning": st.warning, "error": st.error}.get(level, st.info)
    renderer(message)


def clear_and_flash(message: str, level: str = "info") -> None:
    """Wipes session state (logout/expiry) without losing the explanatory message."""
    st.session_state.clear()
    flash(message, level)


def ensure_state() -> None:
    if "authenticated_user" not in st.session_state:
        st.session_state.authenticated_user = None
    if "jwt_token" not in st.session_state:
        st.session_state.jwt_token = None
    if "recovery_email" not in st.session_state:
        st.session_state.recovery_email = None
    if "active_program" not in st.session_state:
        st.session_state.active_program = None
    if "onboarding_state" not in st.session_state:
        st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}


def establish_session(body: dict) -> None:
    st.session_state.authenticated_user = body["trainee_id"]
    st.session_state.jwt_token = body["access_token"]
    st.session_state.recovery_email = None
    st.session_state.active_program = None
    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}


def logout() -> None:
    try:
        token = st.session_state.get("jwt_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        httpx.post(f"{API_BASE_URL}/auth/logout", headers=headers, timeout=REQUEST_TIMEOUT)
    except httpx.RequestError:
        pass
    st.session_state.clear()
    st.rerun()
