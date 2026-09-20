"""Program & dashboard tab: metrics, volume, trajectories, and routine blueprint."""

import pandas as pd
import streamlit as st

from ui.api_client import api
from ui.views.program import render_program_dashboard


def _record_label(record: dict) -> str:
    if record.get("record_type") == "max_weight":
        return f"{record.get('reps')}-rep max"
    return "e1RM"


def _render_pr_table(records: list[dict], include_movement: bool = False) -> None:
    rows = []
    for record in records:
        row = {}
        if include_movement:
            row["Movement"] = record.get("name", record.get("exercise_id", "—"))
        row["Record"] = _record_label(record)
        row["Value"] = f"{float(record['value']):g} kg"
        row["Previous"] = f"{float(record['prev_value']):g} kg" if record.get("prev_value") is not None else "—"
        row["Achieved"] = str(record.get("achieved_at", ""))[:10]
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_dashboard(profile: dict, program) -> None:
    if st.session_state.get("just_regenerated"):
        st.toast("✅ Routine recalibrated and saved to ledger!", icon="⚡")
        st.session_state.just_regenerated = False

    prof = profile
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Trainee", f"{prof.get('gender', 'M').capitalize()}, {prof.get('age', 25)}yo")
    with m2:
        st.metric("Bodyweight", f"{prof.get('weight_kg', 75.0)} kg")
    with m3:
        st.metric("Frequency", f"{prof.get('weekly_frequency', 4)} d/wk")
    with m4:
        st.metric("Rep Bias", prof.get("rep_preference", "balanced").capitalize())

    st.divider()

    # Rolling 7-Day Fractional Volume Distribution
    st.markdown("#### 📈 Rolling 7-Day Volume Attribution")
    st.caption("Direct Sets = 1.0 | Secondary Synergists = 0.5")

    vol_data = api("GET", "/dashboard/volume", params={"days": 7})
    if any(value for value in vol_data.values()):
        df_vol = pd.DataFrame(list(vol_data.items()), columns=["Muscle", "Effective Sets"])
        st.bar_chart(df_vol.set_index("Muscle"), color="#FF4B4B")
    else:
        st.info("No sets logged in the last 7 days. Complete a workout in Tab 2 to populate volume telemetry.")

    st.divider()

    # Personal Record Shelf (deterministic, no LLM involvement)
    st.markdown("#### 🏆 Recent Personal Records")
    st.caption("Heaviest set per exact rep count and best RPE-adjusted e1RM, newest first.")
    recent_prs = api("GET", "/dashboard/personal-records", params={"limit": 10})
    if recent_prs:
        _render_pr_table(recent_prs, include_movement=True)
    else:
        st.info("No personal records yet. Finish a workout to set your first baseline.")

    st.divider()

    # Longitudinal Overload Trajectory
    st.markdown("#### 🎯 Longitudinal Overload Trajectory")
    st.caption("Inspect RPE-adjusted estimated 1RM (e1RM) and top-set loads across recorded exposures.")

    logged_exercises = api("GET", "/dashboard/exercises")

    if logged_exercises:
        ex_options = {entry["name"]: entry["id"] for entry in logged_exercises}
        selected_name = st.selectbox("Select Movement to Inspect:", list(ex_options.keys()))
        selected_id = ex_options[selected_name]

        payload = api("GET", f"/dashboard/exercises/{selected_id}/history")
        history = payload.get("history", [])
        if history:
            df_hist = pd.DataFrame(history)
            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                st.markdown("**Estimated 1RM (kg)**")
                st.line_chart(df_hist.set_index("date")["e1rm"])
            with c_chart2:
                st.markdown("**Top Set Load (kg)**")
                st.line_chart(df_hist.set_index("date")["weight_kg"])

            st.caption(payload.get("caption", ""))

            records = payload.get("records", [])
            with st.expander(f"🏆 PR Shelf — {selected_name}", expanded=bool(records)):
                if records:
                    _render_pr_table(records[:10])
                    if len(records) > 10:
                        st.caption(f"Showing the 10 most recent of {len(records)} records.")
                else:
                    st.caption("No records logged for this movement yet.")
    else:
        st.info("Log workouts in Tab 2 to unlock movement overload charts.")

    st.divider()

    # Active Split Blueprint
    st.markdown("#### 📋 Active Routine Blueprint")
    if program is not None:
        render_program_dashboard(program)
    else:
        st.info("No active program loaded.")
