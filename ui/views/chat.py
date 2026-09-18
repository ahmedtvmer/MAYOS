"""Training assistant tab: ledger history plus streamed turns."""

import time

import streamlit as st

from ui import api_client, present
from ui.api_client import api


def render_chat() -> None:
    c_title, c_clear = st.columns([4, 1])
    with c_title:
        st.subheader("💬 Training Assistant")
        st.caption("Ask biomechanics questions, search movements, or command split adjustments.")
    with c_clear:
        if st.button("🗑️ Clear", use_container_width=True, help="Flush current dialogue context"):
            api("DELETE", "/chat/history")
            st.rerun()

    # 1. Render dialogue history from the service ledger (authoritative text only)
    full_history = api("GET", "/chat/history")
    for msg in full_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask a question or enter a command...")
    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            holder: dict = {}
            st.write_stream(api_client.sse_chat_turn(user_input, holder))

        # 5. Server persists the authoritative response; refresh routine state on mutations
        if holder.get("program_updated"):
            latest = api("GET", "/programs/active")
            st.session_state.active_program = present.ns(latest) if latest else None
            st.toast("Routine updated in ledger!", icon="📋")
            time.sleep(0.4)
            st.rerun()
