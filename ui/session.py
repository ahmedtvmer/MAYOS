"""Streamlit session-state orchestration: init, establish, and clear."""

import httpx
import streamlit as st

from ui.api_client import API_BASE_URL, REQUEST_TIMEOUT


def ensure_state() -> None:
    if "authenticated_user" not in st.session_state:
        st.session_state.authenticated_user = None
    if "jwt_token" not in st.session_state:
        st.session_state.jwt_token = None
    if "active_program" not in st.session_state:
        st.session_state.active_program = None
    if "onboarding_state" not in st.session_state:
        st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}


def establish_session(body: dict) -> None:
    st.session_state.authenticated_user = body["trainee_id"]
    st.session_state.jwt_token = body["access_token"]
    st.session_state.active_program = None
    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}


def logout() -> None:
    try:
        token = st.session_state.get("jwt_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        httpx.post(f"{API_BASE_URL}/auth/logout", headers=headers, timeout=REQUEST_TIMEOUT)
    except httpx.ConnectError:
        pass
    st.session_state.clear()
    st.rerun()
