"""Active routine blueprint: tables, export, and execution demos."""

from pathlib import Path

import pandas as pd
import streamlit as st

from ui import present
from ui.api_client import api_bytes

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def render_program_dashboard(program) -> None:
    """Renders daily training cards, loading tables, and media execution demos."""
    st.subheader(f"📋 {program.program_name}")
    st.caption(f"**Split:** {program.split_type} | **Weekly Frequency:** {program.weekly_frequency} Days")

    filename, excel_bytes = api_bytes("/programs/active.xlsx")
    st.download_button(
        label="📥 Download Program as Excel (.xlsx)",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    day_titles = [f"Day {d.day_order}: {d.day_name}" for d in program.days]
    tabs = st.tabs(day_titles)

    for idx, day in enumerate(program.days):
        with tabs[idx]:
            data = [
                {
                    "Order": i + 1,
                    "Exercise": ex.exercise_name,
                    "Sets": ex.target_sets,
                    "Reps": f"{ex.target_reps_min}–{ex.target_reps_max}",
                    "Target RPE": f"@{ex.target_rpe}",
                    "Rest": f"{ex.rest_seconds}s",
                    "Notes & Cues": ex.notes or "-",
                }
                for i, ex in enumerate(day.exercises)
            ]
            st.dataframe(
                pd.DataFrame(data),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Order": st.column_config.NumberColumn(width="small"),
                    "Exercise": st.column_config.TextColumn(width="medium"),
                    "Sets": st.column_config.NumberColumn(width="small"),
                    "Reps": st.column_config.TextColumn(width="small"),
                    "Target RPE": st.column_config.TextColumn(width="small"),
                    "Rest": st.column_config.TextColumn(width="small"),
                    "Notes & Cues": st.column_config.TextColumn(width="large"),
                },
            )

            st.markdown("##### 🎬 Biomechanical Execution & Form Demos")
            for i, ex in enumerate(day.exercises):
                with st.expander(f"#{i + 1} • {ex.exercise_name.title()} (Visual Demo & Cues)"):
                    col_demo, col_details = st.columns([1, 3])
                    with col_demo:
                        media = present.resolve_media_path(ex.gif_path, BASE_DIR) or present.resolve_media_path(ex.image_path, BASE_DIR)
                        if media:
                            try:
                                st.image(media, width=260)
                            except Exception:
                                st.caption("Demonstration media could not be loaded.")
                        else:
                            st.caption("No media asset found on disk.")
                    with col_details:
                        st.markdown(
                            f"**Loading Parameters:** `{ex.target_sets} sets × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}`"
                        )
                        st.markdown(f"**Prescribed Rest:** `{ex.rest_seconds} seconds`")
                        st.markdown(
                            f"**Execution Cue:**\n> {ex.notes or 'Maintain maximum tension through full active range of motion.'}"
                        )
