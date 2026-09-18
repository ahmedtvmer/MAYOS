"""MYOS Streamlit client. Thin UI over the FastAPI service: no DB, LLM, or domain logic here."""

import sys
from pathlib import Path

import streamlit as st

# Streamlit Page Configuration MUST be the first command
st.set_page_config(page_title="Myos | Training Engine", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

from ui import present, session  # noqa: E402
from ui.api_client import api  # noqa: E402
from ui.views import (  # noqa: E402
    auth as auth_view,
    chat as chat_view,
    dashboard as dashboard_view,
    logger as logger_view,
    onboarding as onboarding_view,
    sidebar as sidebar_view,
)


# Clean Dark Theme Styling
st.markdown(
    """
<style>
    .stApp {
        background-color: #0e1117;
        color: #e6edf3;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #30363d;
        border-radius: 6px;
    }
</style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------------
# Session State Hydration
# -------------------------------------------------------------------------
session.ensure_state()

# -------------------------------------------------------------------------
# Gatekeeper: Login & Registration
# -------------------------------------------------------------------------
if not st.session_state.get("authenticated_user") or not st.session_state.get("jwt_token"):
    auth_view.render_gatekeeper()
    st.stop()

# -------------------------------------------------------------------------
# Authenticated Trainee Context Hydration
# -------------------------------------------------------------------------
profile = api("GET", "/profile", allow_404=True)
if profile is None and st.session_state.active_program is None:
    program_body = api("GET", "/programs/active")
    if program_body is not None:
        st.session_state.active_program = present.ns(program_body)

if profile is not None and st.session_state.active_program is None:
    program_body = api("GET", "/programs/active")
    if program_body is not None:
        st.session_state.active_program = present.ns(program_body)

if profile is None and not st.session_state.onboarding_state["messages"]:
    started = api("POST", "/onboarding/start")
    st.session_state.onboarding_state.update(
        {"messages": [("assistant", text) for text in started.get("messages", [])], "intake_step": started.get("intake_step", 1), "is_complete": started.get("is_complete", False)}
    )


# -------------------------------------------------------------------------
# Sidebar: Controls & Persona Settings
# -------------------------------------------------------------------------
sidebar_view.render_sidebar(profile)

# -------------------------------------------------------------------------
# Viewport Routing: Onboarding vs Active Trainee
# -------------------------------------------------------------------------
if not profile:
    onboarding_view.render_calibration()

else:
    main_view_tab, logger_tab, chat_tab = st.tabs(
        ["📋 Program & Dashboard", "🏋️ Active Workout Logger", "💬 Training Assistant"]
    )

    # ---------------- TAB 1: Program & Dashboard ----------------
    with main_view_tab:
        dashboard_view.render_dashboard(profile, st.session_state.active_program)

    # ---------------- TAB 2: Workout Logger ----------------
    with logger_tab:
        logger_view.render_logger(st.session_state.active_program)

    # ---------------- TAB 3: Training Assistant ----------------
    with chat_tab:
        chat_view.render_chat()
