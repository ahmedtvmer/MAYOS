"""Post-session debrief rendering: totals, coach text, and movement analytics."""

import streamlit as st


def render_debrief(result: dict, readiness: int) -> None:
    total_tonnage_kg = result["total_tonnage_kg"]
    total_working_sets = result["total_working_sets"]
    exercise_summaries = result["exercise_summaries"]
    debrief_content = result["debrief"]

    st.success("✅ Session Saved to Ledger.")

    # Post-Session Visual Debrief & Movement Breakdown
    st.markdown("### 🎙️ Coach Post-Session Debrief")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Volume Load", f"{total_tonnage_kg:,.1f} kg")
    m2.metric("Working Sets", f"{total_working_sets} sets")
    m3.metric("Session Readiness", f"{readiness}/5")

    st.markdown(debrief_content)
    st.divider()

    st.markdown("### 📊 Movement Analytics")
    for ex_stat in exercise_summaries:
        badge = ex_stat.get("status_badge", "LOGGED")
        st.markdown(f"#### {ex_stat.get('name', 'Movement')} `{badge}`")

        c_load, c_e1rm, c_target = st.columns([1.2, 1.2, 2.6])
        with c_load:
            ld = ex_stat.get("load_delta")
            delta_str = f"{ld:+} kg vs last" if ld is not None else "Baseline set"
            st.metric(
                "Top Load",
                f"{ex_stat.get('top_load', 0.0)} kg × {ex_stat.get('top_reps', 0)}",
                delta=delta_str,
            )
        with c_e1rm:
            ed = ex_stat.get("e1rm_delta")
            e1rm_delta_str = f"{ed:+} kg e1RM" if ed is not None else None
            st.metric("Est. 1-Rep Max", f"{ex_stat.get('current_e1rm', 0.0)} kg", delta=e1rm_delta_str)
        with c_target:
            st.markdown("**Next Session Directive:**")
            directive = ex_stat.get("target_text", "Maintain current load and strive for rep progression.")
            st.markdown(f"> {directive}")
        st.divider()
