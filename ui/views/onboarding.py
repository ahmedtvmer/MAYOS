"""Trainee calibration viewport (pre-profile)."""

import streamlit as st

from ui import present
from ui.api_client import api


def render_calibration() -> None:
    st.subheader("⚡ Trainee Calibration")
    st.caption("Answer the intake questions below to initialize your training ledger.")

    for role, text in st.session_state.onboarding_state["messages"]:
        with st.chat_message(role):
            st.markdown(text)

    user_input = st.chat_input("Answer intake questions...")
    if user_input:
        st.session_state.onboarding_state["messages"].append(("user", user_input))

        with st.spinner("Processing intake telemetry..."):
            output = api("POST", "/onboarding/step", json={"content": user_input})
            for text in output.get("messages", []):
                st.session_state.onboarding_state["messages"].append(("assistant", text))
            st.session_state.onboarding_state["intake_step"] = output.get("intake_step", 1)
            st.session_state.onboarding_state["is_complete"] = output.get("is_complete", False)

            if st.session_state.onboarding_state.get("is_complete", False):
                with st.status("⚡ Calibrating Trainee Profile & Program Matrix...", expanded=True) as status:
                    st.write("🔒 Securing biometrics to private SQLite ledger...")
                    api("POST", "/onboarding/complete")
                    st.write("📐 Synthesizing biomechanics and selecting optimal movements...")
                    program_body = api("GET", "/programs/active")
                    st.session_state.active_program = present.ns(program_body) if program_body else None
                    status.update(label="✅ Calibration complete!", state="complete", expanded=False)

                st.session_state.just_regenerated = True
                st.rerun()

        st.rerun()
