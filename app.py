import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

# Page Configuration MUST be the first Streamlit command
st.set_page_config(
    page_title="Myos | Training Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

from agent.onboarding_graph import onboarding_graph
from agent.program_generator import generate_program_pipeline
from database.database_manager import DatabaseManager
from utils.exporter import export_program_to_excel

# Clean Table & Dark Theme Styling
st.markdown("""
<style>
    .stApp {
        background-color: #0e1117;
        color: #e6edf3;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #30363d;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

db = DatabaseManager()

# -------------------------------------------------------------------------
# Session State Initialization
# -------------------------------------------------------------------------
profile = db.get_user_profile()

if "graph_state" not in st.session_state:
    st.session_state.graph_state = {
        "messages": [],
        "intake_step": 1,
        "is_complete": False,
        "profile_data": None
    }

if "active_program" not in st.session_state:
    st.session_state.active_program = None

# If no profile exists and graph hasn't started, trigger initial node
if not profile and not st.session_state.graph_state["messages"]:
    initial_output = onboarding_graph.invoke(st.session_state.graph_state)
    st.session_state.graph_state.update(initial_output)

# -------------------------------------------------------------------------
# UI Component: Program Dashboard & Excel Exporter
# -------------------------------------------------------------------------
def resolve_media_path(path: str | None) -> str | None:
    """
    Resolves remote URLs or verifies existing local file paths.
    Checks root, data/, and dataset/ directories.
    Returns None if the file cannot be verified on disk.
    """
    if not path or not isinstance(path, str):
        return None
        
    if path.startswith("http://") or path.startswith("https://"):
        return path

    candidates = [
        Path(path),
        BASE_DIR / path,
        BASE_DIR / "data" / path,
        BASE_DIR / "dataset" / path,
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    return None

def render_program_dashboard(program):
    """Renders tabs per training day with dataframes and visual form demos."""
    st.subheader(f"📋 {program.program_name}")
    st.caption(f"**Split:** {program.split_type} | **Weekly Frequency:** {program.weekly_frequency} Days")

    excel_bytes = export_program_to_excel(program)
    st.download_button(
        label="📥 Download Program as Excel (.xlsx)",
        data=excel_bytes,
        file_name=f"{program.program_name.replace(' ', '_').lower()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    day_titles = [f"Day {d.day_order}: {d.day_name}" for d in program.days]
    tabs = st.tabs(day_titles)

    for idx, day in enumerate(program.days):
        with tabs[idx]:
            # 1. Scannable Double-Progression Overview Matrix
            data = [
                {
                    "Order": i + 1,
                    "Exercise": ex.exercise_name,
                    "Sets": ex.target_sets,
                    "Reps": f"{ex.target_reps_min}–{ex.target_reps_max}",
                    "Target RPE": f"@{ex.target_rpe}",
                    "Rest": f"{ex.rest_seconds}s",
                    "Notes & Cues": ex.notes or "-"
                }
                for i, ex in enumerate(day.exercises)
            ]
            df = pd.DataFrame(data)
            st.dataframe(
                df,
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
                }
            )

            st.write("")
            st.markdown("##### 🎬 Biomechanical Execution & Form Demos")

            # 2. Collapsible Media & Cue Cards
            # Collapsible Media & Cue Cards
            for i, ex in enumerate(day.exercises):
                with st.expander(f"#{i+1} • {ex.exercise_name.title()} (Visual Demo & Cues)"):
                    # Give the demo a compact column and the details more space
                    col_demo, col_details = st.columns([1, 3])
                    
                    with col_demo:
                        media = resolve_media_path(ex.gif_path) or resolve_media_path(ex.image_path)
                        
                        if media:
                            try:
                                # Lock width to prevent low-res GIF upscaling blur
                                st.image(media, width=260)
                            except Exception:
                                st.caption("Demonstration media could not be loaded.")
                        else:
                            st.caption("No media asset found on disk.")

                    with col_details:
                        st.markdown(f"**Loading Parameters:** `{ex.target_sets} sets × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}`")
                        st.markdown(f"**Prescribed Rest:** `{ex.rest_seconds} seconds`")
                        st.markdown(f"**Execution Cue:**\n> {ex.notes or 'Maintain maximum tension through full active range of motion.'}")
# -------------------------------------------------------------------------
# Sidebar: Profile & Controls
# -------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ Myos Engine")
    st.divider()

    if profile:
        st.subheader("Active Profile")
        st.markdown(f"**Gender:** `{profile.get('gender', 'male').capitalize()}`")
        st.markdown(f"**Goal:** `{profile.get('current_goal', 'Hypertrophy')}`")
        st.markdown(f"**Frequency:** `{profile.get('weekly_frequency', 4)} days/week`")
        st.markdown(f"**Equipment:** `{profile.get('equipment_access', 'Commercial Gym')}`")
        st.markdown(f"**Limitations:** `{profile.get('injuries_or_limitations', 'None')}`")
        st.markdown(f"**Proportions:** `{profile.get('proportions', 'Average')}`")
        st.markdown(f"**Rep Bias:** `{profile.get('rep_preference', 'balanced')}`")
        st.divider()

        if st.button("Regenerate Program", use_container_width=True):
            with st.spinner("Synthesizing program via local LLM..."):
                program, _ = generate_program_pipeline(
                    rep_preference_override=profile.get("rep_preference", "balanced")
                )
                st.session_state.active_program = program
                st.session_state.graph_state["messages"].append(
                    AIMessage(content="Program regenerated successfully. Updated dashboard rendered above.")
                )
                st.rerun()

        if st.button("Reset Profile / Re-run Onboarding", type="secondary", use_container_width=True):
            db.clear_user_profile()
            st.session_state.graph_state = {
                "messages": [],
                "intake_step": 1,
                "is_complete": False,
                "profile_data": None
            }
            st.session_state.active_program = None
            st.rerun()
    else:
        st.info("Onboarding in progress. Answer the intake questions below.")

# -------------------------------------------------------------------------
# Main Viewport: Active Program Dashboard
# -------------------------------------------------------------------------
if st.session_state.active_program is not None:
    render_program_dashboard(st.session_state.active_program)
    st.divider()

# -------------------------------------------------------------------------
# Chat History Rendering
# -------------------------------------------------------------------------
for msg in st.session_state.graph_state["messages"]:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.markdown(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.markdown(msg.content)

# Hydrate instantly from SQLite if session state is empty
if profile and not st.session_state.active_program:
    existing_program = db.get_active_program()
    if existing_program:
        st.session_state.active_program = existing_program
    elif not st.session_state.graph_state["messages"]:
        with st.spinner("Synthesizing initial program..."):
            program, _ = generate_program_pipeline()
            st.session_state.active_program = program

# -------------------------------------------------------------------------
# Chat Input & Routing
# -------------------------------------------------------------------------
user_input = st.chat_input("Type your response or command...")

if user_input:
    st.session_state.graph_state["messages"].append(HumanMessage(content=user_input))

    # Case 1: Still in Onboarding Graph
    if not profile or not st.session_state.graph_state.get("is_complete", False):
        with st.spinner("Processing responses..."):
            output_state = onboarding_graph.invoke(st.session_state.graph_state)
            st.session_state.graph_state.update(output_state)

        if st.session_state.graph_state.get("is_complete", False):
            with st.spinner("Profile saved. Synthesizing initial training program..."):
                program, _ = generate_program_pipeline()
                st.session_state.active_program = program
                st.session_state.graph_state["messages"].append(
                    AIMessage(content="Profile setup complete. Your routine and Excel spreadsheet are ready above.")
                )
        st.rerun()

    # Case 2: Post-Onboarding Dynamic Interaction
    else:
        text = user_input.lower()
        split_override = user_input if any(w in text for w in ["split", "day", "upper", "lower", "ppl", "arnold", "full body"]) else None
        rep_override = "high" if "high rep" in text else "low" if ("low rep" in text or "heavy" in text) else None

        with st.spinner("Synthesizing updated program..."):
            program, _ = generate_program_pipeline(
                user_split_override=split_override,
                rep_preference_override=rep_override
            )
            st.session_state.active_program = program
            response = f"Updated your routine to **{program.split_type}** with **{rep_override or 'balanced'}** rep ranges. See dashboard above."
            st.session_state.graph_state["messages"].append(AIMessage(content=response))
        st.rerun()