"""Streamlit session-state orchestration: init, establish, flash, and clear."""

import time
from typing import Any, MutableMapping

import httpx
import streamlit as st

from ui import cookies as cookie_store
from ui.api_client import API_BASE_URL, REQUEST_TIMEOUT

#: Session-state key remembering the fingerprint of a bearer the server rejected,
#: so cookie hydration never restores it again in this browser session.
REJECTED_TOKEN_KEY = "rejected_cookie_token"


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


def clear_and_flash(message: str, level: str = "info", reject_token: str | None = None) -> None:
    """Wipes session state (logout/expiry) without losing the message or cookie manager.

    When ``reject_token`` is supplied, its fingerprint stays behind as a rejection
    marker: the next cookie hydration refuses that token, breaking the
    stale-cookie -> 401 -> rerun loop even if the cookie deletion races.
    """
    manager = st.session_state.get(cookie_store.STATE_KEY)
    cookie_store.remove_auth_cookie(manager)
    st.session_state.clear()
    if manager is not None:
        st.session_state[cookie_store.STATE_KEY] = manager
    if reject_token:
        st.session_state[REJECTED_TOKEN_KEY] = cookie_store.token_fingerprint(reject_token)
    flash(message, level)


def reject_session(message: str, level: str = "error") -> None:
    """Clears the session for a server-rejected bearer and remembers its fingerprint."""
    clear_and_flash(message, level, reject_token=st.session_state.get("jwt_token"))


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


def restore_auth_from_cookies(state: MutableMapping[str, Any], cookies: Any | None) -> bool:
    """Restores a sign-in session from a consented cookie. Pure enough for unit tests.

    Unverified ``sub``/``exp`` reads gate the restore only; the server verifies
    every bearer on every call. Tokens already expired or fingerprinted as
    rejected in this session are refused, so a stale cookie can never re-trigger
    the existing 401 clear-and-flash flow in a loop.
    """
    if state.get("jwt_token"):
        return False
    token = None
    try:
        if cookies is not None:
            token = cookies.get(cookie_store.COOKIE_NAME)
    except Exception:
        token = None
    if not token:
        return False
    if state.get(REJECTED_TOKEN_KEY) == cookie_store.token_fingerprint(token):
        return False
    subject, expires = cookie_store.parse_jwt_claims(token)
    if not subject:
        return False
    if expires is not None and expires <= time.time():
        return False
    state["jwt_token"] = token
    state["authenticated_user"] = subject
    return True


def hydrate_from_cookie(cookies: Any | None) -> bool:
    """Restores the sign-in session from the browser cookie, if any."""
    restored = restore_auth_from_cookies(st.session_state, cookies)
    if not restored and cookies is not None and st.session_state.get(REJECTED_TOKEN_KEY):
        # Best-effort second deletion pass: the first clear races the cookie
        # component and may not have landed in the browser yet.
        try:
            if cookie_store.COOKIE_NAME in cookies:
                cookie_store.remove_auth_cookie(cookies)
        except Exception:
            pass
    return restored


def establish_session(body: dict, remember: bool = False) -> None:
    st.session_state.authenticated_user = body["trainee_id"]
    st.session_state.jwt_token = body["access_token"]
    st.session_state.recovery_email = None
    st.session_state.active_program = None
    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}
    st.session_state.pop(REJECTED_TOKEN_KEY, None)
    manager = st.session_state.get(cookie_store.STATE_KEY)
    if remember:
        cookie_store.apply_auth_cookie(manager, body["access_token"])
    else:
        cookie_store.remove_auth_cookie(manager)


def logout() -> None:
    try:
        token = st.session_state.get("jwt_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        httpx.post(f"{API_BASE_URL}/auth/logout", headers=headers, timeout=REQUEST_TIMEOUT)
    except httpx.RequestError:
        pass
    manager = st.session_state.get(cookie_store.STATE_KEY)
    cookie_store.remove_auth_cookie(manager)
    st.session_state.clear()
    if manager is not None:
        st.session_state[cookie_store.STATE_KEY] = manager
    st.rerun()
