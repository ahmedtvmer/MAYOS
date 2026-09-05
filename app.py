import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
import uuid
from datetime import datetime, timezone
import time
from dotenv import load_dotenv
import os
load_dotenv()

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
from agent.debrief import generate_session_debrief
from core.warmup import calculate_warmup_sets
from core.progression import evaluate_progression, calculate_epley_e1rm
from agent.assistant_graph import assistant_graph

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

# -------------------------------------------------------------------------
# Session-Scoped Database & Identity Management
# -------------------------------------------------------------------------

llm = ChatOllama(model=os.getenv("LLM"), temperature=0.0)



db = DatabaseManager()

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None

if "active_program" not in st.session_state:
    st.session_state.active_program = None

if "onboarding_state" not in st.session_state:
    st.session_state.onboarding_state = {
        "messages": [],
        "trainee_id": None,
        "intake_step": 1,
        "is_complete": False,
        "profile_data": None
    }

if "assistant_messages" not in st.session_state:
    st.session_state.assistant_messages = []

# -------------------------------------------------------------------------
# Gatekeeper: Login / Registration (Hides all other trainee data)
# -------------------------------------------------------------------------
if not st.session_state.get("authenticated_user"):
    st.title("⚡ Myos Engine")

    auth_tab, reg_tab = st.tabs(["🔑 Trainee Login", "✨ New Trainee Setup"])

    with auth_tab:
        with st.form("login_form"):
            trainee_id = st.text_input("Trainee ID / Username:").strip()
            submit_login = st.form_submit_button("Access Ledger", use_container_width=True)

            if submit_login and trainee_id:
                clean_id = db._sanitize_username(trainee_id)
                if db.user_exists(clean_id):
                    db.switch_user(clean_id)
                    st.session_state.authenticated_user = clean_id
                    st.session_state.active_program = db.get_active_program()
                    st.session_state.onboarding_state = {
                        "messages": [],
                        "trainee_id": clean_id,
                        "intake_step": 1,
                        "is_complete": bool(db.get_user_profile()),
                        "profile_data": db.get_user_profile()
                    }
                    st.session_state.assistant_messages = []
                    st.rerun()
                else:
                    st.error("Trainee ID not found. Verify spelling or initialize a new profile.")

    with reg_tab:
        with st.form("register_form"):
            new_trainee_id = st.text_input("Choose Unique Trainee ID (letters and numbers only):").strip()
            submit_new = st.form_submit_button("Create Private Ledger", use_container_width=True)

            if submit_new and new_trainee_id:
                clean_id = db._sanitize_username(new_trainee_id)
                if db.user_exists(clean_id):
                    st.warning("This Trainee ID already exists. Please log in.")
                else:
                    db.switch_user(clean_id)
                    st.session_state.authenticated_user = clean_id
                    st.session_state.active_program = None
                    st.session_state.onboarding_state = {
                        "messages": [],
                        "trainee_id": clean_id,
                        "intake_step": 1,
                        "is_complete": False,
                        "profile_data": None
                    }
                    st.session_state.assistant_messages = []
                    st.success(f"Ledger initialized for {clean_id}.")
                    st.rerun()

    # Halt execution until authenticated
    st.stop()

# -------------------------------------------------------------------------
# Authenticated Trainee Hydration (Executes only after successful login)
# -------------------------------------------------------------------------
if st.session_state.authenticated_user and db.active_user != st.session_state.authenticated_user:
    db.switch_user(st.session_state.authenticated_user)

profile = db.get_user_profile()

if "onboarding_state" not in st.session_state:
    st.session_state.onboarding_state = {
        "messages": [],
        "intake_step": 1,
        "is_complete": bool(profile),
        "profile_data": profile
    }

if "assistant_messages" not in st.session_state:
    st.session_state.assistant_messages = []

if "active_program" not in st.session_state:
    st.session_state.active_program = db.get_active_program()

# If user profile already exists, load the saved program instantly on startup
if profile and st.session_state.active_program is None:
    saved_program = db.get_active_program()
    if saved_program:
        st.session_state.active_program = saved_program
    else:
        with st.spinner("Synthesizing your calibrated routine..."):
            prog, _ = generate_program_pipeline(rep_preference_override=profile.get("rep_preference", "balanced"))
            st.session_state.active_program = prog

# If NO profile exists and onboarding hasn't run, trigger intake question #1
if not profile and not st.session_state.onboarding_state["messages"]:
    st.session_state.onboarding_state["trainee_id"] = st.session_state.authenticated_user
    initial_output = onboarding_graph.invoke(st.session_state.onboarding_state)
    st.session_state.onboarding_state.update(initial_output)

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
# -------------------------------------------------------------------------
# Sidebar: Profile & Controls
# -------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ Myos Engine")
    st.caption(f"Trainee: **{st.session_state.authenticated_user}**")
    
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    st.divider()

    if profile:
        st.subheader("Active Profile")

        # -----------------------------------------------------------------
        # Direct Profile Editor (Zero-LLM UI Form)
        # -----------------------------------------------------------------
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
                new_freq = st.slider("Weekly Frequency (Days)", min_value=1, max_value=5, value=int(profile.get("weekly_frequency", 4)))
                new_equipment = st.text_input("Equipment Access", value=profile.get("equipment_access", "Commercial Gym"))
                new_limitations = st.text_input("Injuries / Limitations", value=profile.get("injuries_or_limitations", "None"))
                new_weight = st.number_input("Bodyweight (kg)", min_value=30.0, max_value=250.0, value=float(profile.get("weight_kg", 80.0)), step=0.5)

                save_profile_btn = st.form_submit_button("Save Profile Changes", use_container_width=True)

                if save_profile_btn:
                    # Detect if frequency or biomechanical drivers changed
                    freq_changed = int(new_freq) != int(profile.get("weekly_frequency", 4))
                    rep_changed = new_rep_pref != profile.get("rep_preference", "balanced")
                    limits_changed = new_limitations.strip() != profile.get("injuries_or_limitations", "None")

                    updated_payload = {
                        **profile,
                        "proportions": new_proportions,
                        "rep_preference": new_rep_pref,
                        "current_goal": new_goal.strip(),
                        "weekly_frequency": new_freq,
                        "equipment_access": new_equipment.strip(),
                        "injuries_or_limitations": new_limitations.strip(),
                        "weight_kg": new_weight
                    }
                    db.upsert_user_profile(updated_payload)

                    # Automatically compile a matching routine if frequency or constraints shifted
                    if freq_changed or rep_changed or limits_changed:
                        new_prog, _ = generate_program_pipeline(
                            rep_preference_override=new_rep_pref,
                            frequency_override=new_freq
                        )
                        st.session_state.active_program = new_prog
                        st.success(f"Profile updated & routine rebuilt for {new_freq} days/week.")
                    else:
                        st.success("Ledger profile updated.")

                    st.rerun()

        # Scannable Badges of Current State
        st.markdown(f"**Proportions:** `{profile.get('proportions', 'balanced')}`")
        st.markdown(f"**Rep Bias:** `{profile.get('rep_preference', 'balanced')}`")
        st.markdown(f"**Frequency:** `{profile.get('weekly_frequency', 4)} days/week`")
        st.markdown(f"**Limitations:** `{profile.get('injuries_or_limitations', 'None')}`")
        st.markdown(f"**Equipment:** `{profile.get('equipment_access', 'Commercial Gym')}`")

        # --- Coach Persona & Behavior Configuration ---
        with st.expander("⚙️ Coach Persona & Directives"):
            tone_options = [
                "Direct, grounded, and pragmatic",
                "Scientific & biomechanics-focused",
                "Drill sergeant / High accountability",
                "Concise & bullet-points only",
                "Custom"
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
                help="These directives are permanently injected into the training assistant's system prompt for your account."
            )

            if st.button("Save Coach Settings", use_container_width=True):
                db.update_user_persona(selected_tone, custom_rules)
                st.success("Persona saved.")
                st.rerun()

        st.divider()

        if st.button("🔄 Regenerate Program", use_container_width=True):
            with st.spinner("⚡ Rebuilding split matrix and overload parameters..."):
                time.sleep(0.35)  # Perceptual visual buffer for sub-50ms assembly
                latest_profile = db.get_user_profile()
                target_freq = latest_profile.get("weekly_frequency", 4)

                program, _ = generate_program_pipeline(
                    rep_preference_override=latest_profile.get("rep_preference", "balanced"),
                    frequency_override=target_freq
                )

                st.session_state.active_program = program
                st.session_state.just_regenerated = True
                st.rerun()

        if st.button("Reset Profile", type="secondary", use_container_width=True):
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
        st.info("Onboarding in progress. Answer the intake questions in the chat.") 

# -------------------------------------------------------------------------
# Viewport Routing: Onboarding vs Active Trainee
# -------------------------------------------------------------------------
if not profile:
    st.subheader("⚡ Trainee Calibration")
    st.caption("Answer the intake questions below to initialize your training ledger.")

    for msg in st.session_state.onboarding_state["messages"]:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        with st.chat_message(role):
            st.markdown(msg.content)

    user_input = st.chat_input("Answer intake questions...")
    if user_input:
        st.session_state.onboarding_state["messages"].append(HumanMessage(content=user_input))
        st.session_state.onboarding_state["trainee_id"] = st.session_state.authenticated_user

        with st.spinner("Processing intake telemetry..."):
            output_state = onboarding_graph.invoke(st.session_state.onboarding_state)
            st.session_state.onboarding_state.update(output_state)

            if st.session_state.onboarding_state.get("is_complete", False):
                with st.status("⚡ Calibrating Trainee Profile & Program Matrix...", expanded=True) as status:
                    st.write("🔒 Securing biometrics to private SQLite ledger...")
                    db.switch_user(st.session_state.authenticated_user)
                    
                    st.write("📐 Synthesizing biomechanics and selecting optimal movements...")
                    prog, _ = generate_program_pipeline()
                    st.session_state.active_program = prog

                    st.write("🤖 Initializing Training Assistant context...")
                    st.session_state.assistant_messages = [
                        AIMessage(
                            content=(
                                f"Welcome! I have calibrated your active program: **{prog.program_name}** "
                                f"({prog.weekly_frequency} days/week). "
                                "Inspect your routine in **Program & Dashboard**, "
                                "or command exercise substitutions and loading adjustments here."
                            )
                        )
                    ]
                    status.update(label="✅ Calibration complete!", state="complete", expanded=False)

                st.session_state.just_onboarded = True
                st.rerun()

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
        if st.session_state.get("just_regenerated"):
            st.toast("✅ Routine recalibrated and saved to ledger!", icon="⚡")
            st.session_state.just_regenerated = False

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

            # Unique key per day order
            with st.form(key=f"workout_log_form_{day_plan.day_order}"):
                # 1. Dynamic readiness slider inside the form
                readiness = st.slider(
                    "Readiness & CNS State",
                    min_value=1,
                    max_value=5,
                    value=4,
                    key=f"readiness_slider_{day_plan.day_order}",
                    help="1 = Fatigued / low drive, 5 = Peak recovery"
                )

                session_payload = []
                for ex_idx, ex in enumerate(day_plan.exercises, start=1):
                    st.markdown(f"#### #{ex_idx} • {ex.exercise_name.title()}")
                    st.caption(f"Target: {ex.target_sets} sets × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}")

                    last_perf = db.get_last_performance(ex.exercise_id)
                    default_weight = last_perf[0]["weight_kg"] if last_perf else 20.0

                    if ex_idx == 1 or ex.target_reps_min <= 8:
                        with st.expander("🔥 Warm-up Ramp Sets"):
                            warmups = calculate_warmup_sets(default_weight)
                            if warmups:
                                w_cols = st.columns(len(warmups))
                                for w_i, w_set in enumerate(warmups):
                                    with w_cols[w_i]:
                                        st.metric(f"{w_set['set']} ({w_set['reps']} reps)", f"{w_set['load_kg']} kg", w_set["focus"])

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
                            key=f"w_{day_plan.day_order}_{ex.exercise_id}_{s_i}"
                        )
                        reps = c3.number_input(
                            "Reps",
                            min_value=0,
                            max_value=50,
                            value=int(last_set["reps"] if last_set else ex.target_reps_min),
                            step=1,
                            key=f"r_{day_plan.day_order}_{ex.exercise_id}_{s_i}"
                        )
                        rpe = c4.number_input(
                            "RPE",
                            min_value=6.0,
                            max_value=10.0,
                            value=float(ex.target_rpe),
                            step=0.5,
                            key=f"rpe_{day_plan.day_order}_{ex.exercise_id}_{s_i}"
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

                db.log_workout_session(
                    session_id=session_id,
                    session_date=today_date,
                    split_name=day_plan.day_name,
                    started_at=now_iso,
                    completed_at=now_iso,
                    readiness_score=readiness,
                    notes=session_notes
                )

                st.success("✅ Session Saved to Ledger.")

                exercise_summaries = []
                for item in session_payload:
                    ex = item["exercise"]
                    sets = item["sets"]
                    prev_sets = item["previous_perf"]

                    volume_load = 0.0
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
                        volume_load += (s_data["weight_kg"] * s_data["reps"])

                    best_set = max(sets, key=lambda s: calculate_epley_e1rm(s["weight_kg"], s["reps"]))
                    current_e1rm = calculate_epley_e1rm(best_set["weight_kg"], best_set["reps"])

                    if prev_sets:
                        prev_best_set = max(prev_sets, key=lambda s: calculate_epley_e1rm(s["weight_kg"], s["reps"]))
                        prev_best_load = prev_best_set["weight_kg"]
                        prev_e1rm = calculate_epley_e1rm(prev_best_load, prev_best_set["reps"])
                        load_delta = round(best_set["weight_kg"] - prev_best_load, 1)
                        e1rm_delta = round(current_e1rm - prev_e1rm, 1)
                    else:
                        load_delta = None
                        e1rm_delta = None

                    body_part = getattr(ex, "body_part", None) or getattr(ex, "target_muscle", "")
                    mechanic = "compound" if ex.target_reps_min <= 8 else "isolation"

                    verdict = evaluate_progression(
                        mechanic=mechanic,
                        performed_sets=sets,
                        target_reps_min=ex.target_reps_min,
                        target_reps_max=ex.target_reps_max,
                        body_part=body_part
                    )

                    exercise_summaries.append({
                        "name": ex.exercise_name.title(),
                        "top_load": best_set["weight_kg"],
                        "top_reps": best_set["reps"],
                        "top_rpe": best_set["rpe"],
                        "volume_load": volume_load,
                        "current_e1rm": current_e1rm,
                        "load_delta": load_delta,
                        "e1rm_delta": e1rm_delta,
                        "action": verdict.get("action", "hold"),
                        "status_badge": verdict.get("status_badge", ""),
                        "target_text": verdict.get("target_text", "")
                    })

                with st.spinner("Coach is analyzing session telemetry..."):
                    debrief_content = generate_session_debrief(
                        split_name=day_plan.day_name,
                        readiness=readiness,
                        session_notes=session_notes,
                        exercise_summaries=exercise_summaries,
                        profile=profile or {}
                    )
                    db.save_session_debrief(session_id, debrief_content)
                    st.session_state.assistant_messages.append(
                        AIMessage(content=f"### 📋 Debrief: {day_plan.day_name} ({today_date})\n\n{debrief_content}")
                    )

                st.markdown("### 🎙️ Coach Post-Session Debrief")
                st.markdown(debrief_content)
                st.divider()

                st.markdown("### 📊 Movement Analytics")
                for ex_stat in exercise_summaries:
                    st.markdown(f"#### {ex_stat['name']} `{ex_stat['status_badge']}`")
                    c_load, c_e1rm, c_target = st.columns([1.2, 1.2, 2.6])
                    with c_load:
                        delta_str = f"{ex_stat['load_delta']:+} kg vs last" if ex_stat["load_delta"] is not None else "Baseline set"
                        st.metric("Top Load", f"{ex_stat['top_load']} kg × {ex_stat['top_reps']}", delta=delta_str)
                    with c_e1rm:
                        e1rm_delta_str = f"{ex_stat['e1rm_delta']:+} kg e1RM" if ex_stat["e1rm_delta"] is not None else None
                        st.metric("Est. 1-Rep Max", f"{ex_stat['current_e1rm']} kg", delta=e1rm_delta_str)
                    with c_target:
                        st.markdown("**Next Session Directive:**")
                        st.markdown(f"> {ex_stat['target_text']}")
                    st.divider()

    # ---------------- TAB 3: Training Assistant ----------------
    with chat_tab:
        st.subheader("💬 Training Assistant")
        st.caption("Ask biomechanics questions, search movements, or command split adjustments.")

        # Render strictly assistant messages
        for msg in st.session_state.assistant_messages:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            with st.chat_message(role):
                st.markdown(msg.content)

        user_input = st.chat_input("Ask a question or enter a command...")
        if user_input:
            st.session_state.assistant_messages.append(HumanMessage(content=user_input))

            with st.spinner("Processing..."):
                initial_state = {
                    "messages": st.session_state.assistant_messages,
                    "trainee_id": st.session_state.authenticated_user,
                    "coach_tone": profile.get("coach_tone", "Direct, grounded, and pragmatic"),
                    "custom_instructions": profile.get("custom_instructions", ""),
                    "intent": None,
                    "intent_metadata": {},
                    "retrieved_context": None,
                    "program_updated": False,
                    "response_content": None
                }

                output = assistant_graph.invoke(initial_state)

                if output.get("program_updated"):
                    st.session_state.active_program = db.get_active_program()

                if output.get("response_content"):
                    st.session_state.assistant_messages.append(
                        AIMessage(content=output["response_content"])
                    )

            st.rerun()