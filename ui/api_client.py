"""HTTP transport for the Streamlit client: JSON calls, downloads, and SSE turns."""

import os
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 30.0
STREAM_TIMEOUT = 300.0


def auth_headers() -> dict:
    token = st.session_state.get("jwt_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_json(
    method: str, path: str, *, timeout: float = REQUEST_TIMEOUT, **kwargs: Any
) -> tuple[int, Any | None, str | None]:
    """JSON call that never raises and never touches Streamlit state.

    Returns ``(status, body, detail)``:
    - ``status``: HTTP status, or ``0`` on transport failure (timeout, refused).
    - ``body``: parsed JSON of any shape (dict/list/None on empty or non-JSON).
    - ``detail``: ready-to-display error string for 4xx/5xx/transport, else None.

    Callers own the UX: streaming views may inline ``detail`` instead of a
    full-page stop, so a malformed or failed response can never blank the app.

    ``transport`` (optional) is a test seam: any other value must be an
    ``httpx.BaseTransport`` (e.g. ``httpx.MockTransport``) used in place of
    real networking.
    """
    transport = kwargs.pop("transport", None)
    url = f"{API_BASE_URL}{path}"
    try:
        if transport is None:
            response = httpx.request(method, url, timeout=timeout, **kwargs)
        else:
            with httpx.Client(transport=transport) as client:
                response = client.request(method, url, timeout=timeout, **kwargs)
    except httpx.RequestError as exc:
        return 0, None, f"Cannot reach the training service at {API_BASE_URL} ({exc.__class__.__name__})."
    body: Any | None = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None
    if response.status_code >= 400:
        detail = None
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error")
        return response.status_code, body, str(detail or f"Request failed ({response.status_code}).")[:300]
    return response.status_code, body, None


def api(method: str, path: str, allow_404: bool = False, **kwargs: Any):
    """JSON API call. Returns parsed body (None for 204, or for 404 when allow_404); reruns login on 401."""
    status, body, detail = request_json(method, path, headers=auth_headers(), **kwargs)
    if status == 0:
        st.error(detail)
        st.stop()
    if status == 401:
        from ui import session  # local import breaks the module cycle

        session.clear_and_flash("Session expired. Please log in again.", "error")
        st.rerun()
    if status == 204:
        return None
    if status == 404 and allow_404:
        return None
    if status >= 400:
        st.error(str(detail)[:300])
        st.stop()
    return body


def api_bytes(path: str, params: dict | None = None) -> tuple[str, bytes]:
    try:
        response = httpx.get(f"{API_BASE_URL}{path}", headers=auth_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except httpx.RequestError as exc:
        st.error(f"Cannot reach the training service at {API_BASE_URL} ({exc.__class__.__name__}).")
        st.stop()
    if response.status_code == 401:
        from ui import session  # local import breaks the module cycle

        session.clear_and_flash("Session expired. Please log in again.", "error")
        st.rerun()
    if response.status_code >= 400:
        st.error("Download failed.")
        st.stop()
    filename = "program.xlsx"
    if "filename=" in response.headers.get("content-disposition", ""):
        filename = response.headers["content-disposition"].split("filename=")[1].strip('"')
    return filename, response.content


def sse_chat_turn(content: str, holder: dict):
    """Yields assistant tokens from the SSE stream; stashes the done-frame in holder."""
    try:
        with httpx.stream(
            "POST",
            f"{API_BASE_URL}/chat/messages",
            headers=auth_headers(),
            json={"content": content},
            timeout=STREAM_TIMEOUT,
        ) as stream:
            if stream.status_code == 401:
                from ui import session  # local import breaks the module cycle

                session.clear_and_flash("Session expired. Please log in again.", "error")
                st.rerun()
            if stream.status_code == 429:
                st.error("Too many messages. Please wait a moment and retry.")
                st.stop()
            if stream.status_code >= 400:
                st.error("Assistant request failed.")
                st.stop()
            import json as _json

            pending_error = False
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    pending_error = line[len("event:"):].strip() == "error"
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    event = _json.loads(line[len("data:"):])
                except ValueError:
                    continue
                if "token" in event:
                    yield event["token"]
                elif event.get("done"):
                    holder.update(event)
                elif pending_error:
                    yield event.get("detail", "Assistant request failed.")
                    pending_error = False
    except httpx.RequestError as exc:
        st.error(f"Cannot reach the training service at {API_BASE_URL} ({exc.__class__.__name__}).")
        st.stop()
