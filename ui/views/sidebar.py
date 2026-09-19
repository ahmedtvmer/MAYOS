"""Sidebar: session controls, profile/persona editing, program actions."""

import time

import streamlit as st

from ui import present, session
from ui.api_client import api


def render_sidebar(profile: dict | None) -> None:
    with st.sidebar:
        st.title("⚡ Myos Engine")
        st.caption(f"Trainee: **{st.session_state.authenticated_user}**")

        if st.button("Logout", use_container_width=True):
            session.logout()

        st.divider()

        if profile:
            st.subheader("Active Profile")

            with st.expander("✏️ Edit Profile & Biomechanics", expanded=False):
                with st.form("edit_profile_form"):
                    proportions_opts = ["balanced", "long_legs", "long_torso"]
                    current_prop = profile.get("proportions", "balanced").lower()
                    prop_idx = proportions_opts.index(current_prop) if current_prop in proportions_opts else 0
                    new_proportions = st.selectbox("Limb Proportions", proportions_opts, index=prop_idx)

                    rep_opts = ["low", "balanced", "high"]
                    current_rep = profile.get("rep_preference", "balanced").lower()
                    rep_idx = rep_opts.index(current_rep) if current_rep in rep_opts else 1
                    new_rep_pref = st.selectbox("Rep Preference", rep_opts, index=rep_idx)

                    new_goal = st.text_input("Primary Goal", value=profile.get("current_goal", "Hypertrophy"))
                    new_freq = st.slider(
                        "Weekly Frequency (Days)", min_value=1, max_value=5, value=int(profile.get("weekly_frequency", 4))
                    )
                    new_equipment = st.text_input(
                        "Equipment Access", value=profile.get("equipment_access", "Commercial Gym")
                    )
                    new_limitations = st.text_input(
                        "Injuries / Limitations", value=profile.get("injuries_or_limitations", "None")
                    )
                    new_weight = st.number_input(
                        "Bodyweight (kg)",
                        min_value=30.0,
                        max_value=250.0,
                        value=float(profile.get("weight_kg", 80.0)),
                        step=0.5,
                    )

                    save_profile_btn = st.form_submit_button("Save Profile Changes", use_container_width=True)

                    if save_profile_btn:
                        result = api(
                            "PUT",
                            "/profile",
                            json={
                                "proportions": new_proportions,
                                "rep_preference": new_rep_pref,
                                "current_goal": new_goal.strip(),
                                "weekly_frequency": new_freq,
                                "equipment_access": new_equipment.strip(),
                                "injuries_or_limitations": new_limitations.strip(),
                                "weight_kg": new_weight,
                            },
                        )
                        if result.get("program_rebuilt"):
                            st.session_state.active_program = present.ns(result["program"])
                            st.success(f"Profile updated & routine rebuilt for {new_freq} days/week.")
                        else:
                            st.success("Ledger profile updated.")
                        st.rerun()

            st.markdown(f"**Proportions:** `{profile.get('proportions', 'balanced')}`")
            st.markdown(f"**Rep Bias:** `{profile.get('rep_preference', 'balanced')}`")
            st.markdown(f"**Frequency:** `{profile.get('weekly_frequency', 4)} days/week`")
            st.markdown(f"**Limitations:** `{profile.get('injuries_or_limitations', 'None')}`")
            st.markdown(f"**Equipment:** `{profile.get('equipment_access', 'Commercial Gym')}`")

            with st.expander("⚙️ Coach Persona & Directives"):
                tone_options = [
                    "Direct, grounded, and pragmatic",
                    "Scientific & biomechanics-focused",
                    "Drill sergeant / High accountability",
                    "Concise & bullet-points only",
                    "Custom",
                ]
                current_tone = profile.get("coach_tone", "Direct, grounded, and pragmatic")
                default_tone_idx = tone_options.index(current_tone) if current_tone in tone_options else 4

                selected_tone = st.selectbox("Speaking Tone", tone_options, index=default_tone_idx)
                if selected_tone == "Custom":
                    selected_tone = st.text_input("Define Custom Tone:", value=current_tone)

                custom_rules = st.text_area(
                    "Behavioral Directives & Guardrails:",
                    value=profile.get("custom_instructions", ""),
                    placeholder="e.g., Never use motivational fluff. Always prioritize joint longevity over load.",
                )

                if st.button("Save Coach Settings", use_container_width=True):
                    api("PUT", "/profile/persona", json={"coach_tone": selected_tone, "custom_instructions": custom_rules})
                    st.success("Persona saved.")
                    st.rerun()

            st.divider()

            if st.button("🔄 Regenerate Program", use_container_width=True):
                with st.spinner("⚡ Rebuilding split matrix and overload parameters..."):
                    time.sleep(0.35)
                    program_body = api("POST", "/programs/generate", json={})
                    st.session_state.active_program = present.ns(program_body)
                    st.session_state.just_regenerated = True
                    st.rerun()

            if st.button("Reset Profile", type="secondary", use_container_width=True):
                api("DELETE", "/profile")
                st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}
                st.session_state.active_program = None
                st.rerun()
        else:
            st.info("Onboarding in progress. Answer the intake questions in the chat.")

        st.divider()
        with st.expander("🔐 Password & Recovery", expanded=False):
            with st.form("change_password_form"):
                current_pw = st.text_input("Current password:", type="password")
                new_pw = st.text_input("New password (8+ characters):", type="password")
                change_btn = st.form_submit_button("Change Password (logs out everywhere)", use_container_width=True)
                if change_btn and current_pw and new_pw:
                    body = api(
                        "POST",
                        "/auth/change-password",
                        json={"current_password": current_pw, "new_password": new_pw},
                    )
                    if body is not None:
                        session.clear_and_flash(body.get("message", "Password updated."), "success")
                        st.rerun()

            st.markdown("**Recovery email** (for self-service password reset):")
            current_email = api("GET", "/auth/email", allow_404=True)
            with st.form("recovery_email_form"):
                email_val = st.text_input(
                    "Email:", value=(current_email or {}).get("email") or "", placeholder="you@example.com"
                )
                save_email_btn = st.form_submit_button("Save Recovery Email", use_container_width=True)
                if save_email_btn and email_val.strip():
                    saved = api("POST", "/auth/email", json={"email": email_val.strip()})
                    if saved is not None:
                        st.success(f"Recovery email set: {saved.get('email')}")
                        st.rerun()
