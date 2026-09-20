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
            warmups = getattr(day, "warmup_exercises", None) or []
            if warmups:
                st.markdown("##### 🔥 Warm Up")
                warmup_data = [
                    {
                        "Exercise": w.exercise_name,
                        "Sets": w.sets,
                        "Reps": w.reps,
                        "Rest": f"{w.rest_seconds}s",
                    }
                    for w in warmups
                ]
                st.dataframe(
                    pd.DataFrame(warmup_data),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Exercise": st.column_config.TextColumn(width="medium"),
                        "Sets": st.column_config.NumberColumn(width="small"),
                        "Reps": st.column_config.NumberColumn(width="small"),
                        "Rest": st.column_config.TextColumn(width="small"),
                    },
                )

            data = [
                {
                    "Order": i + 1,
                    "Exercise": ex.exercise_name,
                    "Warm-up Sets": ex.warmup_sets if ex.warmup_sets else "-",
                    "Sets": ex.target_sets,
                    "Reps": f"{ex.target_reps_min}–{ex.target_reps_max}",
                    "RPE": f"@{ex.target_rpe}",
                    "Rest": f"{ex.rest_seconds}s",
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
                    "Warm-up Sets": st.column_config.NumberColumn(width="small"),
                    "Sets": st.column_config.NumberColumn(width="small"),
                    "Reps": st.column_config.TextColumn(width="small"),
                    "RPE": st.column_config.TextColumn(width="small"),
                    "Rest": st.column_config.TextColumn(width="small"),
                },
            )

            if getattr(day, "cardio", None):
                st.info(day.cardio)

            st.markdown("##### 🎬 Biomechanical Execution & Form Demos")
            for i, ex in enumerate(day.exercises):
                with st.expander(f"#{i + 1} • {ex.exercise_name.title()} (Visual Demo & Steps)"):
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
                        warmup_line = f"+ {ex.warmup_sets} warm-up sets • " if ex.warmup_sets else ""
                        st.markdown(
                            f"**Loading Parameters:** `{warmup_line}{ex.target_sets} sets × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}`"
                        )
                        st.markdown(f"**Prescribed Rest:** `{ex.rest_seconds} seconds`")
                        if ex.notes:
                            steps = "\n".join(f"- {line.strip()}" for line in str(ex.notes).splitlines() if line.strip())
                            st.markdown(f"**Execution Steps:**\n{steps}")
                        else:
                            st.markdown("**Execution Steps:** consult the training assistant for form cues.")
