import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage
import uuid
from datetime import datetime, timezone

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
from core.warmup import calculate_warmup_sets
from core.progression import evaluate_progression, calculate_epley_e1rm

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
# Session State & Immediate Cold-Start Hydration
# -------------------------------------------------------------------------
profile = db.get_user_profile()

if "graph_state" not in st.session_state:
    st.session_state.graph_state = {
        "messages": [],
        "intake_step": 1,
        "is_complete": bool(profile),
        "profile_data": profile
    }

if "active_program" not in st.session_state:
    st.session_state.active_program = None

# If user profile already exists, load the saved program instantly on startup
if profile and st.session_state.active_program is None:
    saved_program = db.get_active_program()
    if saved_program:
        st.session_state.active_program = saved_program
    else:
        # Fallback: Profile exists but no program in DB yet -> synthesize once
        with st.spinner("Synthesizing your calibrated routine..."):
            prog, _ = generate_program_pipeline(rep_preference_override=profile.get("rep_preference", "balanced"))
            st.session_state.active_program = prog

# If NO profile exists and onboarding haven't run, trigger first question
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
# Viewport Routing: Onboarding vs Active Trainee
# -------------------------------------------------------------------------
if not profile:
    # 1. Onboarding Flow (Chat Only)
    st.subheader("⚡ Trainee Calibration")
    for msg in st.session_state.graph_state["messages"]:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        with st.chat_message(role):
            st.markdown(msg.content)

    user_input = st.chat_input("Answer intake questions...")
    if user_input:
        st.session_state.graph_state["messages"].append(HumanMessage(content=user_input))
        with st.spinner("Processing responses..."):
            output_state = onboarding_graph.invoke(st.session_state.graph_state)
            st.session_state.graph_state.update(output_state)
            if st.session_state.graph_state.get("is_complete", False):
                prog, _ = generate_program_pipeline()
                st.session_state.active_program = prog
        st.rerun()

else:
    # 2. Fully Separated 3-Tab Architecture
    main_view_tab, logger_tab, chat_tab = st.tabs([
        "📋 Program & Dashboard", 
        "🏋️ Active Workout Logger", 
        "💬 Training Assistant"
    ])

    # ---------------- TAB 1: Pure Program View ----------------
    with main_view_tab:
        if st.session_state.active_program is not None:
            render_program_dashboard(st.session_state.active_program)
        else:
            st.info("No active program loaded.")

    # ---------------- TAB 2: Workout Logger ----------------
    with logger_tab:
        if not st.session_state.active_program:
            st.info("No active program loaded. Complete onboarding first.")
        else:
            program = st.session_state.active_program
            day_names = [f"Day {d.day_order}: {d.day_name}" for d in program.days]
            selected_day_label = st.selectbox("Select Today's Session:", day_names)
            selected_day_idx = day_names.index(selected_day_label)
            day_plan = program.days[selected_day_idx]

            st.subheader(f"Logging: {day_plan.day_name}")
            readiness = st.slider(
                "Readiness & CNS State",
                min_value=1,
                max_value=5,
                value=4,
                help="1 = Fatigued / low drive, 5 = Peak recovery"
            )

            with st.form(key=f"workout_log_form_{day_plan.day_order}"):
                session_payload = []

                for ex_idx, ex in enumerate(day_plan.exercises, start=1):
                    st.markdown(f"#### #{ex_idx} • {ex.exercise_name.title()}")
                    st.caption(
                        f"Target: {ex.target_sets} sets × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}"
                    )

                    last_perf = db.get_last_performance(ex.exercise_id)
                    default_weight = last_perf[0]["weight_kg"] if last_perf else 20.0

                    if ex_idx == 1 or ex.target_reps_min <= 8:
                        with st.expander("🔥 Warm-up Ramp Sets"):
                            warmups = calculate_warmup_sets(default_weight)
                            if warmups:
                                w_cols = st.columns(len(warmups))
                                for w_i, w_set in enumerate(warmups):
                                    with w_cols[w_i]:
                                        st.metric(
                                            f"{w_set['set']} ({w_set['reps']} reps)",
                                            f"{w_set['load_kg']} kg",
                                            w_set["focus"]
                                        )

                    ex_sets = []
                    for s_i in range(ex.target_sets):
                        last_set = last_perf[s_i] if s_i < len(last_perf) else None
                        last_str = f"Last: {last_set['weight_kg']}kg × {last_set['reps']}" if last_set else "Last: —"

                        c1, c2, c3, c4 = st.columns([1, 2, 2, 2])
                        c1.markdown(f"**Set {s_i+1}**")
                        c1.caption(last_str)

                        weight = c2.number_input(
                            "Load (kg)",
                            min_value=0.0,
                            max_value=500.0,
                            value=float(last_set["weight_kg"] if last_set else default_weight),
                            step=2.5,
                            key=f"w_{ex.exercise_id}_{s_i}"
                        )
                        reps = c3.number_input(
                            "Reps",
                            min_value=0,
                            max_value=50,
                            value=int(last_set["reps"] if last_set else ex.target_reps_min),
                            step=1,
                            key=f"r_{ex.exercise_id}_{s_i}"
                        )
                        rpe = c4.number_input(
                            "RPE",
                            min_value=6.0,
                            max_value=10.0,
                            value=float(ex.target_rpe),
                            step=0.5,
                            key=f"rpe_{ex.exercise_id}_{s_i}"
                        )

                        ex_sets.append({"weight_kg": weight, "reps": reps, "rpe": rpe})

                    session_payload.append({
                        "exercise": ex,
                        "sets": ex_sets,
                        "previous_perf": last_perf
                    })
                    st.divider()

                session_notes = st.text_input("Session Notes (pumps, joint aches, fatigue):")
                submit_btn = st.form_submit_button("🏁 Finish & Commit Workout to Ledger", use_container_width=True)

            if submit_btn:
                session_id = str(uuid.uuid4())
                now_iso = datetime.now(timezone.utc).isoformat()
                today_date = datetime.now().strftime("%Y-%m-%d")

                # Commit Master Session
                db.log_workout_session(
                    session_id=session_id,
                    session_date=today_date,
                    split_name=day_plan.day_name,
                    started_at=now_iso,
                    completed_at=now_iso,
                    readiness_score=readiness,
                    notes=session_notes
                )

                st.success("✅ Session Saved.")
                st.markdown("### 📊 Performance Analytics & Progression Targets")

                # Render Modern Performance Metric Cards
                for item in session_payload:
                    ex = item["exercise"]
                    sets = item["sets"]
                    prev_sets = item["previous_perf"]

                    # 1. Commit sets to SQLite
                    for s_i, s_data in enumerate(sets, start=1):
                        db.log_workout_set(
                            set_id=str(uuid.uuid4()),
                            session_id=session_id,
                            exercise_id=ex.exercise_id,
                            set_index=s_i,
                            weight_kg=s_data["weight_kg"],
                            reps=s_data["reps"],
                            rpe=s_data["rpe"]
                        )

                    # 2. Performance Metrics Calculation
                    # Find top set based on best calculated e1RM
                    best_set = max(sets, key=lambda s: calculate_epley_e1rm(s["weight_kg"], s["reps"]))
                    current_e1rm = calculate_epley_e1rm(best_set["weight_kg"], best_set["reps"])

                    # Previous session comparisons
                    if prev_sets:
                        prev_best_set = max(prev_sets, key=lambda s: calculate_epley_e1rm(s["weight_kg"], s["reps"]))
                        prev_best_load = prev_best_set["weight_kg"]
                        prev_e1rm = calculate_epley_e1rm(prev_best_load, prev_best_set["reps"])
                        
                        load_delta = round(best_set["weight_kg"] - prev_best_load, 1)
                        e1rm_delta = round(current_e1rm - prev_e1rm, 1)
                    else:
                        load_delta = None
                        e1rm_delta = None

                    # 3. Progression Directives
                    body_part = getattr(ex, "body_part", None) or getattr(ex, "target_muscle", "")
                    mechanic = "compound" if ex.target_reps_min <= 8 else "isolation"

                    verdict = evaluate_progression(
                        mechanic=mechanic,
                        performed_sets=sets,
                        target_reps_min=ex.target_reps_min,
                        target_reps_max=ex.target_reps_max,
                        body_part=body_part
                    )

                    # 4. Render Clean Card Layout
                    with st.container():
                        st.markdown(f"#### {ex.exercise_name.title()} `{verdict['status_badge']}`")
                        
                        c_load, c_e1rm, c_target = st.columns([1.2, 1.2, 2.6])
                        
                        with c_load:
                            delta_str = f"{load_delta:+} kg vs last" if load_delta is not None else "Baseline set"
                            st.metric(
                                label="Top Load",
                                value=f"{best_set['weight_kg']} kg × {best_set['reps']}",
                                delta=delta_str
                            )

                        with c_e1rm:
                            e1rm_delta_str = f"{e1rm_delta:+} kg e1RM" if e1rm_delta is not None else None
                            st.metric(
                                label="Est. 1-Rep Max",
                                value=f"{current_e1rm} kg",
                                delta=e1rm_delta_str,
                                help="Epley model: weight * (1 + reps / 30)"
                            )

                        with c_target:
                            st.markdown("**Next Session Directive:**")
                            if verdict["action"] == "increase":
                                st.success(verdict["target_text"])
                            elif verdict["action"] == "hold":
                                st.info(verdict["target_text"])
                            else:
                                st.markdown(f"> {verdict['target_text']}")

                        st.divider()
                        
    # ---------------- TAB 3: Isolated Training Assistant ----------------
    with chat_tab:
        st.subheader("💬 Training Assistant")
        st.caption("Ask biomechanics questions, swap movements, or command split/frequency adjustments.")

        # Chat history rendered only inside this tab
        for msg in st.session_state.graph_state["messages"]:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            with st.chat_message(role):
                st.markdown(msg.content)

        user_input = st.chat_input("Ask a question or issue a command (e.g. 'switch to 3 days', 'prefer heavy sets')...")
        if user_input:
            st.session_state.graph_state["messages"].append(HumanMessage(content=user_input))
            text = user_input.lower()

            split_keywords = ["split", "day", "days", "upper", "lower", "ppl", "arnold", "full body", "legs", "push", "pull"]
            is_program_command = any(w in text for w in split_keywords) or any(w in text for w in ["rep", "heavy", "light"])

            if is_program_command:
                split_override = user_input if any(w in text for w in split_keywords) else None
                rep_override = "high" if "high rep" in text else "low" if ("low rep" in text or "heavy" in text) else None

                with st.spinner("Regenerating program parameters..."):
                    prog, _ = generate_program_pipeline(
                        user_split_override=split_override,
                        rep_preference_override=rep_override
                    )
                    st.session_state.active_program = prog
                    st.session_state.graph_state["messages"].append(
                        AIMessage(content=f"Updated your routine to **{prog.program_name}** ({prog.weekly_frequency} Days/Week). Check the **Program & Dashboard** tab to view your updated schedule.")
                    )
            else:
                with st.spinner("Consulting training engine..."):
                    response = llm.invoke([
                        SystemMessage(content=(
                            "You are the Myos Training Assistant. You specialize in biomechanics, "
                            "hypertrophy, and low-injury stability-first training. "
                            "Give concise, pragmatic, and direct guidance."
                        )),
                        *st.session_state.graph_state["messages"]
                    ])
                    st.session_state.graph_state["messages"].append(AIMessage(content=response.content))

            st.rerun()# -------------------------------------------------------------------------
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