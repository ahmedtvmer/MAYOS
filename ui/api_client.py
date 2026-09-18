"""HTTP transport for the Streamlit client: JSON calls, downloads, and SSE turns."""

import os

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


def api(method: str, path: str, allow_404: bool = False, **kwargs):
    """JSON API call. Returns parsed body (None for 204, or for 404 when allow_404); reruns login on 401."""
    try:
        response = httpx.request(method, f"{API_BASE_URL}{path}", headers=auth_headers(), timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()
    if response.status_code == 401:
        st.session_state.clear()
        st.error("Session expired. Please log in again.")
        st.rerun()
    if response.status_code == 204:
        return None
    if response.status_code == 404 and allow_404:
        return None
    if response.status_code >= 400:
        detail = response.json().get("detail", "Request failed.") if "application/json" in response.headers.get("content-type", "") else response.text
        st.error(str(detail)[:300])
        st.stop()
    return response.json()


def api_bytes(path: str, params: dict | None = None) -> tuple[str, bytes]:
    try:
        response = httpx.get(f"{API_BASE_URL}{path}", headers=auth_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()
    if response.status_code == 401:
        st.session_state.clear()
        st.error("Session expired. Please log in again.")
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
                st.session_state.clear()
                st.error("Session expired. Please log in again.")
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
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()
