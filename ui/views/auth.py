"""Gatekeeper: login, registration, legacy claim, recovery, and the email gate."""

import streamlit as st

from ui import session
from ui.api_client import auth_headers, request_json

SERVICE_OUTDATED = "The training service is outdated. Restart the FastAPI service to enable account recovery."


def _save_gate_email(email: str) -> None:
    status, body, detail = request_json("POST", "/auth/email", json={"email": email}, headers=auth_headers())
    if status == 200 and body is not None:
        st.session_state.recovery_email = body.get("email")
        st.rerun()
    if status == 401:
        session.clear_and_flash("Session expired. Please log in again.", "error")
        st.rerun()
    if status == 404:
        st.error(SERVICE_OUTDATED)
        return
    st.error(str(detail or "Could not save the recovery email.")[:300])


def render_email_gate(error: str | None = None, outdated: bool = False) -> None:
    """Mandatory recovery-email gate for authenticated trainees without one.

    Intentionally minimal: no sidebar, no profile fetch, no dashboard access
    until an email is on file. Logout stays available as the escape hatch.
    """
    st.title("⚡ Mayos Engine")
    st.caption("One last step: add a recovery email so you can reset your password if you lose it.")
    if outdated:
        st.error(SERVICE_OUTDATED)
    elif error:
        st.warning(str(error)[:300])

    if st.button("Logout", key="gate_logout", use_container_width=False):
        session.logout()

    with st.form("recovery_email_gate_form"):
        email_val = st.text_input("Recovery email:", key="gate_email_input", placeholder="you@example.com")
        submitted = st.form_submit_button("Save & Continue", use_container_width=True)

    if submitted:
        if not email_val.strip():
            st.error("Enter a recovery email to continue.")
        else:
            _save_gate_email(email_val.strip())


def _login(trainee_id: str, password: str) -> None:
    status, body, detail = request_json(
        "POST", "/auth/login", json={"trainee_id": trainee_id, "password": password}
    )
    if status == 200 and body and "access_token" in body:
        session.establish_session(body)
        st.rerun()
    if status == 403:
        st.session_state.claim_user = trainee_id
        st.rerun()
    st.error(str(detail or "Login failed.")[:200])


def _claim(trainee_id: str, password: str) -> None:
    status, body, detail = request_json(
        "POST", "/auth/claim", json={"trainee_id": trainee_id, "password": password}
    )
    if status == 200 and body and "access_token" in body:
        session.establish_session(body)
        st.session_state.claim_user = None
        st.rerun()
    st.error(str(detail or "Claim failed.")[:200])


def _register(trainee_id: str, password: str) -> None:
    status, body, detail = request_json(
        "POST", "/auth/register", json={"trainee_id": trainee_id, "password": password}
    )
    if status == 201 and body:
        session.establish_session(body)
        st.success(f"Ledger initialized for {body['trainee_id']}.")
        st.rerun()
    st.error(str(detail or "Registration failed.")[:200])


def _forgot_password(email: str) -> None:
    status, body, detail = request_json("POST", "/auth/forgot-password", json={"email": email})
    if status == 202 and body:
        st.info(str(body.get("message", "Request received."))[:200])
    else:
        st.error(str(detail or "Request failed.")[:200])


def _reset_password(token: str, new_password: str) -> None:
    status, body, detail = request_json(
        "POST", "/auth/reset-password", json={"token": token, "new_password": new_password}
    )
    if status == 200 and body:
        st.success(str(body.get("message", "Password reset."))[:200])
        try:
            st.query_params.clear()
        except Exception:
            pass
    else:
        st.error(str(detail or "Reset failed.")[:200])


def _preset_reset_token() -> str:
    try:
        return str(st.query_params.get("reset_token", ""))[:128]
    except Exception:
        return ""


def render_gatekeeper() -> None:
    st.title("⚡ Mayos Engine")
    session.consume_flash()

    auth_tab, reg_tab, recover_tab = st.tabs(["🔑 Trainee Login", "✨ New Trainee Setup", "🔄 Recover Access"])

    with auth_tab:
        with st.form("login_form"):
            trainee_id = st.text_input("Trainee ID / Username:").strip()
            password = st.text_input("Password:", type="password")
            submit_login = st.form_submit_button("Access Ledger", use_container_width=True)

            if submit_login and trainee_id and password:
                _login(trainee_id, password)

        if st.session_state.get("claim_user"):
            st.info("This ledger predates passwords. Set one now to continue.")
            with st.form("claim_form"):
                new_password = st.text_input("Choose a password (8+ characters):", type="password")
                submit_claim = st.form_submit_button("Set Password & Continue", use_container_width=True)
                if submit_claim and new_password:
                    _claim(st.session_state.claim_user, new_password)

    with reg_tab:
        with st.form("register_form"):
            new_trainee_id = st.text_input("Choose Unique Trainee ID (letters and numbers only):").strip()
            new_password = st.text_input("Choose a password (8+ characters):", type="password")
            submit_new = st.form_submit_button("Create Private Ledger", use_container_width=True)

            if submit_new and new_trainee_id and new_password:
                _register(new_trainee_id, new_password)

    with recover_tab:
        st.caption("Forgot your password? Request a single-use reset link below.")
        with st.form("forgot_form"):
            recovery_email = st.text_input("Recovery email:").strip()
            submit_forgot = st.form_submit_button("Send Reset Link", use_container_width=True)
            if submit_forgot and recovery_email:
                # Generic by design: identical message whether or not the email is linked.
                _forgot_password(recovery_email)

        st.divider()
        with st.form("reset_form"):
            st.caption("Have a reset code? Paste it with your new password.")
            token_val = st.text_input("Reset code:", value=_preset_reset_token())
            reset_pw = st.text_input("New password (8+ characters):", type="password")
            submit_reset = st.form_submit_button("Reset Password", use_container_width=True)
            if submit_reset and token_val and reset_pw:
                _reset_password(token_val.strip(), reset_pw)

    st.stop()
