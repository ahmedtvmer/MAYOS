"""Gatekeeper: login, registration, and legacy password claim."""

import httpx
import streamlit as st

from ui import session
from ui.api_client import API_BASE_URL, REQUEST_TIMEOUT


def render_gatekeeper() -> None:
    st.title("⚡ Myos Engine")

    auth_tab, reg_tab = st.tabs(["🔑 Trainee Login", "✨ New Trainee Setup"])

    with auth_tab:
        with st.form("login_form"):
            trainee_id = st.text_input("Trainee ID / Username:").strip()
            password = st.text_input("Password:", type="password")
            submit_login = st.form_submit_button("Access Ledger", use_container_width=True)

            if submit_login and trainee_id and password:
                try:
                    resp = httpx.post(
                        f"{API_BASE_URL}/auth/login",
                        json={"trainee_id": trainee_id, "password": password},
                        timeout=REQUEST_TIMEOUT,
                    )
                    body = resp.json()
                except httpx.ConnectError:
                    st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
                    st.stop()
                if "access_token" in body:
                    session.establish_session(body)
                    st.rerun()
                elif resp.status_code == 403:
                    st.session_state.claim_user = trainee_id
                    st.rerun()
                else:
                    st.error(str(body.get("detail", "Login failed."))[:200])

        if st.session_state.get("claim_user"):
            st.info("This ledger predates passwords. Set one now to continue.")
            with st.form("claim_form"):
                new_password = st.text_input("Choose a password (8+ characters):", type="password")
                submit_claim = st.form_submit_button("Set Password & Continue", use_container_width=True)
                if submit_claim and new_password:
                    try:
                        resp = httpx.post(
                            f"{API_BASE_URL}/auth/claim",
                            json={"trainee_id": st.session_state.claim_user, "password": new_password},
                            timeout=REQUEST_TIMEOUT,
                        )
                        body = resp.json()
                    except httpx.ConnectError:
                        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
                        st.stop()
                    if "access_token" in body:
                        session.establish_session(body)
                        st.session_state.claim_user = None
                        st.rerun()
                    else:
                        st.error(str(body.get("detail", "Claim failed."))[:200])

    with reg_tab:
        with st.form("register_form"):
            new_trainee_id = st.text_input("Choose Unique Trainee ID (letters and numbers only):").strip()
            new_password = st.text_input("Choose a password (8+ characters):", type="password")
            submit_new = st.form_submit_button("Create Private Ledger", use_container_width=True)

            if submit_new and new_trainee_id and new_password:
                try:
                    resp = httpx.post(
                        f"{API_BASE_URL}/auth/register",
                        json={"trainee_id": new_trainee_id, "password": new_password},
                        timeout=REQUEST_TIMEOUT,
                    )
                except httpx.ConnectError:
                    st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
                    st.stop()
                if resp.status_code == 201:
                    body = resp.json()
                    session.establish_session(body)
                    st.success(f"Ledger initialized for {body['trainee_id']}.")
                    st.rerun()
                else:
                    st.error(str(resp.json().get("detail", "Registration failed."))[:200])

    st.stop()
