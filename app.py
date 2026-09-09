import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

# Streamlit Page Configuration MUST be the first command
st.set_page_config(page_title="Myos | Training Engine", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

from agent.assistant_graph import stream_assistant_turn
from agent.debrief import generate_session_debrief
from agent.onboarding_graph import onboarding_graph
from agent.program_generator import generate_program_pipeline
from agent.progression_engine import (
    calculate_e1rm,
    evaluate_systemic_fatigue,
    get_exercise_progression_history,
    get_weekly_muscle_volume,
    project_next_load,
)
from core.warmup import calculate_warmup_sets
from database.database_manager import DatabaseManager
from utils.exporter import export_program_to_excel
from utils.plate_calculator import calculate_barbell_plates

# Clean Dark Theme Styling
st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------------
# Database Initialization & Session State Hydration
# -------------------------------------------------------------------------
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
        "profile_data": None,
    }

# -------------------------------------------------------------------------
# Gatekeeper: Login & Registration
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
                        "profile_data": db.get_user_profile(),
                    }
                    st.rerun()
                else:
                    st.error("Trainee ID not found. Verify spelling or create a new profile.")

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
                        "profile_data": None,
                    }
                    st.success(f"Ledger initialized for {clean_id}.")
                    st.rerun()

    st.stop()

# -------------------------------------------------------------------------
# Authenticated Trainee Context Hydration
# -------------------------------------------------------------------------
if st.session_state.authenticated_user and db.active_user != st.session_state.authenticated_user:
    db.switch_user(st.session_state.authenticated_user)

profile = db.get_user_profile()

if profile and st.session_state.active_program is None:
    saved_program = db.get_active_program()
    if saved_program:
        st.session_state.active_program = saved_program
    else:
        with st.spinner("Synthesizing your calibrated routine..."):
            prog, _ = generate_program_pipeline(rep_preference_override=profile.get("rep_preference", "balanced"))
            st.session_state.active_program = prog

if not profile and not st.session_state.onboarding_state["messages"]:
    st.session_state.onboarding_state["trainee_id"] = st.session_state.authenticated_user
    initial_output = onboarding_graph.invoke(st.session_state.onboarding_state)
    st.session_state.onboarding_state.update(initial_output)


# -------------------------------------------------------------------------
# Program Visualization Helpers
# -------------------------------------------------------------------------
def resolve_media_path(path: str | None) -> str | None:
    """Verifies local existence or remote accessibility of demo assets."""
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
    """Renders daily training cards, loading tables, and media execution demos."""
    st.subheader(f"📋 {program.program_name}")
    st.caption(f"**Split:** {program.split_type} | **Weekly Frequency:** {program.weekly_frequency} Days")

    excel_bytes = export_program_to_excel(program)
    st.download_button(
        label="📥 Download Program as Excel (.xlsx)",
        data=excel_bytes,
        file_name=f"{program.program_name.replace(' ', '_').lower()}.xlsx",
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
                        media = resolve_media_path(ex.gif_path) or resolve_media_path(ex.image_path)
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


# -------------------------------------------------------------------------
# Sidebar: Controls & Persona Settings
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
                        "weight_kg": new_weight,
                    }
                    db.upsert_user_profile(updated_payload)

                    if freq_changed or rep_changed or limits_changed:
                        new_prog, _ = generate_program_pipeline(
                            rep_preference_override=new_rep_pref, frequency_override=new_freq
                        )
                        st.session_state.active_program = new_prog
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
                db.update_user_persona(selected_tone, custom_rules)
                st.success("Persona saved.")
                st.rerun()

        st.divider()

        if st.button("🔄 Regenerate Program", use_container_width=True):
            with st.spinner("⚡ Rebuilding split matrix and overload parameters..."):
                time.sleep(0.35)
                latest_profile = db.get_user_profile()
                target_freq = latest_profile.get("weekly_frequency", 4)
                program, _ = generate_program_pipeline(
                    rep_preference_override=latest_profile.get("rep_preference", "balanced"),
                    frequency_override=target_freq,
                )
                st.session_state.active_program = program
                st.session_state.just_regenerated = True
                st.rerun()

        if st.button("Reset Profile", type="secondary", use_container_width=True):
            db.clear_user_profile()
            st.session_state.onboarding_state = {
                "messages": [],
                "trainee_id": st.session_state.authenticated_user,
                "intake_step": 1,
                "is_complete": False,
                "profile_data": None,
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

                    db.add_chat_message(
                        "assistant",
                        f"Welcome! I have calibrated your active routine: **{prog.program_name}** "
                        f"({prog.weekly_frequency} days/week). Inspect your split in **Program & Dashboard**, "
                        "log your work in **Active Workout Logger**, or query me here.",
                    )
                    status.update(label="✅ Calibration complete!", state="complete", expanded=False)

                st.session_state.just_regenerated = True
                st.rerun()

        st.rerun()

else:
    main_view_tab, logger_tab, chat_tab = st.tabs(
        ["📋 Program & Dashboard", "🏋️ Active Workout Logger", "💬 Training Assistant"]
    )

    # ---------------- TAB 1: Program & Dashboard ----------------
    with main_view_tab:
        if st.session_state.get("just_regenerated"):
            st.toast("✅ Routine recalibrated and saved to ledger!", icon="⚡")
            st.session_state.just_regenerated = False

        prof = db.get_user_profile() or {}
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

        vol_data = get_weekly_muscle_volume(db, days_lookback=7)
        if vol_data:
            df_vol = pd.DataFrame(list(vol_data.items()), columns=["Muscle", "Effective Sets"])
            st.bar_chart(df_vol.set_index("Muscle"), color="#FF4B4B")
        else:
            st.info("No sets logged in the last 7 days. Complete a workout in Tab 2 to populate volume telemetry.")

        st.divider()

        # Longitudinal Overload Trajectory
        st.markdown("#### 🎯 Longitudinal Overload Trajectory")
        st.caption("Inspect RPE-adjusted estimated 1RM (e1RM) and top-set loads across recorded exposures.")

        cursor = db.user_conn.cursor()
        cursor.execute("""
            SELECT DISTINCT e.id, e.name
            FROM workout_sets ws
            JOIN catalog.exercises e ON ws.exercise_id = e.id
            ORDER BY e.name ASC
        """)
        logged_exercises = cursor.fetchall()

        if logged_exercises:
            ex_options = {name: ex_id for ex_id, name in logged_exercises}
            selected_name = st.selectbox("Select Movement to Inspect:", list(ex_options.keys()))
            selected_id = ex_options[selected_name]

            history = get_exercise_progression_history(db, selected_id)
            if history:
                df_hist = pd.DataFrame(history)
                c_chart1, c_chart2 = st.columns(2)
                with c_chart1:
                    st.markdown("**Estimated 1RM (kg)**")
                    st.line_chart(df_hist.set_index("date")["e1rm"])
                with c_chart2:
                    st.markdown("**Top Set Load (kg)**")
                    st.line_chart(df_hist.set_index("date")["weight_kg"])

                last_entry = history[-1]
                st.caption(
                    f"Latest Recorded: **{last_entry['weight_kg']} kg × {last_entry['reps']} reps @ RPE {last_entry['rpe']}** (e1RM: {last_entry['e1rm']} kg)"
                )
        else:
            st.info("Log workouts in Tab 2 to unlock movement overload charts.")

        st.divider()

        # Active Split Blueprint
        st.markdown("#### 📋 Active Routine Blueprint")
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

            # 1. Evaluate systemic fatigue ONCE at the session level
            fatigue_info = evaluate_systemic_fatigue(db)

            # 2. Render Deload Warning Banner when active
            if fatigue_info["deload_recommended"]:
                st.warning(
                    f"🚨 **DELOAD PROTOCOL ACTIVE ({fatigue_info['severity']})**\n\n"
                    f"- **Driver:** {fatigue_info['reason']}\n"
                    f"- **Prescription Directive:** Cut total working sets by "
                    f"{int((1.0 - fatigue_info['volume_multiplier']) * 100)}% and cap all movements at "
                    f"**RPE {fatigue_info['intensity_cap_rpe']}**.",
                    icon="⚠️",
                )

            with st.form(key=f"workout_log_form_{day_plan.day_order}"):
                readiness = st.slider(
                    "Readiness & CNS State",
                    min_value=1,
                    max_value=5,
                    value=4,
                    key=f"readiness_slider_{day_plan.day_order}",
                    help="1 = Fatigued / low drive, 5 = Peak recovery",
                )

                session_payload = []
                for ex_idx, ex in enumerate(day_plan.exercises, start=1):
                    is_barbell = (
                        "barbell" in ex.exercise_name.lower() or "barbell" in str(getattr(ex, "equipment", "")).lower()
                    )

                    st.markdown(f"#### #{ex_idx} • {ex.exercise_name.title()}")

                    # Calculate volume and intensity caps
                    effective_sets = ex.target_sets
                    target_rpe_cap = ex.target_rpe or 8.5

                    if fatigue_info["deload_recommended"]:
                        effective_sets = max(1, round(ex.target_sets * fatigue_info["volume_multiplier"]))
                        target_rpe_cap = min(target_rpe_cap, fatigue_info["intensity_cap_rpe"] or 10.0)
                        st.caption(
                            f"Prescription: **{effective_sets} sets** (Deload Adjusted from {ex.target_sets}) × "
                            f"{ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {target_rpe_cap}"
                        )
                    else:
                        st.caption(
                            f"Prescription: {ex.target_sets} sets × "
                            f"{ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}"
                        )

                    last_perf = db.get_last_performance(ex.exercise_id)
                    default_weight = 20.0

                    if last_perf:
                        top_prev = max(last_perf, key=lambda s: s["weight_kg"])
                        proj = project_next_load(
                            last_weight=top_prev["weight_kg"],
                            last_reps=top_prev["reps"],
                            last_rpe=top_prev.get("rpe", 8.5),
                            target_reps_min=ex.target_reps_min,
                            target_reps_max=ex.target_reps_max,
                            target_rpe=target_rpe_cap,
                            equipment="barbell" if is_barbell else "other",
                        )
                        default_weight = proj["projected_weight"]
                        delta = proj["delta_kg"]
                        delta_tag = f"(+{delta}kg)" if delta > 0 else (f"({delta}kg)" if delta < 0 else "(Maintained)")
                        st.info(
                            f"🎯 **Auto-Regulated Target:** {proj['projected_weight']} kg × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe} {delta_tag}"
                        )

                        # Soft Progression Ceiling / Anomaly Alert
                        if delta >= 5.0 or (top_prev["weight_kg"] > 0 and (delta / top_prev["weight_kg"]) >= 0.10):
                            st.warning(
                                f"⚠️ **Large Load Jump (+{delta:g} kg vs last session):** "
                                f"Prior top set was {top_prev['weight_kg']:g} kg. Verify target load before unracking.",
                                icon="⚠️",
                            )
                    else:
                        st.caption("🎯 **Target:** Baseline session. Enter calibration weight.")

                    # Plate loading badge for barbell movements
                    if is_barbell and default_weight > 0:
                        plate_data = calculate_barbell_plates(default_weight)
                        st.caption(f"🏋️ **Loading:** `{plate_data['formatted_display']}`")

                    # Warm-up Ramp Sets with Plate Math
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
                                            w_set["focus"],
                                        )
                                        if is_barbell:
                                            w_plates = calculate_barbell_plates(w_set["load_kg"])
                                            p_str = ", ".join(f"{p:g}" for p in w_plates["plates_per_side"])
                                            side_str = f"[{p_str}]/side" if p_str else "Bar Only"
                                            st.caption(f"🏋️ `{side_str}`")

                    ex_sets = []
                    for s_i in range(effective_sets):
                        last_set = last_perf[s_i] if (last_perf and s_i < len(last_perf)) else None
                        last_str = f"Last: {last_set['weight_kg']}kg × {last_set['reps']}" if last_set else "Last: —"

                        initial_load = (
                            float(default_weight)
                            if s_i == 0
                            else (float(last_set["weight_kg"]) if last_set else float(default_weight))
                        )

                        c1, c2, c3, c4 = st.columns([1, 2, 2, 2])
                        c1.markdown(f"**Set {s_i + 1}**")
                        c1.caption(last_str)

                        weight = c2.number_input(
                            "Load (kg)",
                            min_value=0.0,
                            max_value=500.0,
                            value=initial_load,
                            step=2.5,
                            key=f"w_{day_plan.day_order}_{ex.exercise_id}_{s_i}",
                        )
                        reps = c3.number_input(
                            "Reps",
                            min_value=0,
                            max_value=50,
                            value=int(last_set["reps"] if last_set else ex.target_reps_min),
                            step=1,
                            key=f"r_{day_plan.day_order}_{ex.exercise_id}_{s_i}",
                        )
                        rpe = c4.number_input(
                            "RPE",
                            min_value=6.0,
                            max_value=10.0,
                            value=float(last_set["rpe"] if (last_set and last_set.get("rpe")) else ex.target_rpe),
                            step=0.5,
                            key=f"rpe_{day_plan.day_order}_{ex.exercise_id}_{s_i}",
                        )
                        ex_sets.append({"weight_kg": weight, "reps": reps, "rpe": rpe})

                    session_payload.append({"exercise": ex, "sets": ex_sets, "previous_perf": last_perf})
                    st.divider()

                session_notes = st.text_input("Session Notes (pumps, joint aches, fatigue):")
                submit_btn = st.form_submit_button("🏁 Finish & Commit Workout to Ledger", use_container_width=True)

            if submit_btn:
                session_id = str(uuid.uuid4())
                now_iso = datetime.now(UTC).isoformat()
                today_date = datetime.now().strftime("%Y-%m-%d")

                # 1. Register session metadata
                db.log_workout_session(
                    session_id=session_id,
                    session_date=today_date,
                    split_name=day_plan.day_name,
                    started_at=now_iso,
                    completed_at=now_iso,
                    readiness_score=readiness,
                    notes=session_notes,
                )

                total_tonnage_kg = 0.0
                total_working_sets = 0
                exercise_summaries = []
                all_sets_to_batch = []

                # 2. Process metrics & assemble atomic batch insert payload
                for item in session_payload:
                    ex_obj = item["exercise"]
                    sets_data = item["sets"]
                    prev_perf = item.get("previous_perf") or []
                    working_sets = [s for s in sets_data if not s.get("is_warmup", False)]

                    total_working_sets += len(working_sets)
                    ex_volume = sum(s["weight_kg"] * s["reps"] for s in working_sets)
                    total_tonnage_kg += ex_volume

                    # Append to unified batch payload
                    for idx, s in enumerate(sets_data, start=1):
                        all_sets_to_batch.append(
                            {
                                "id": str(uuid.uuid4()),
                                "session_id": session_id,
                                "exercise_id": str(ex_obj.exercise_id),
                                "set_index": idx,
                                "weight_kg": float(s["weight_kg"]),
                                "reps": int(s["reps"]),
                                "rpe": float(s["rpe"]),
                                "is_warmup": 0,
                                "logged_at": now_iso,
                            }
                        )

                    if working_sets:
                        top_set = max(working_sets, key=lambda x: x["weight_kg"])
                        curr_e1rm = round(calculate_e1rm(top_set["weight_kg"], top_set["reps"], top_set["rpe"]), 2)

                        next_proj = project_next_load(
                            last_weight=top_set["weight_kg"],
                            last_reps=top_set["reps"],
                            last_rpe=top_set["rpe"],
                            target_reps_min=ex_obj.target_reps_min,
                            target_reps_max=ex_obj.target_reps_max,
                            target_rpe=ex_obj.target_rpe or 8.5,
                            equipment="barbell" if ("barbell" in ex_obj.exercise_name.lower()) else "other",
                        )

                        if prev_perf:
                            prev_top = max(prev_perf, key=lambda x: x["weight_kg"])
                            prev_e1rm = round(
                                calculate_e1rm(prev_top["weight_kg"], prev_top["reps"], prev_top.get("rpe", 8.5)), 2
                            )
                            e1rm_delta = round(curr_e1rm - prev_e1rm, 2)
                            load_delta = round(top_set["weight_kg"] - prev_top["weight_kg"], 2)
                            reps_delta = top_set["reps"] - prev_top["reps"]

                            if top_set["weight_kg"] > prev_top["weight_kg"]:
                                status_badge = "LOAD INCREASE"
                                action = "increase"
                            elif top_set["reps"] > prev_top["reps"] and top_set["weight_kg"] >= prev_top["weight_kg"]:
                                status_badge = "REP OVERLOAD"
                                action = "increase"
                            elif top_set["reps"] >= ex_obj.target_reps_max and top_set["rpe"] <= ex_obj.target_rpe:
                                status_badge = "GRADUATED"
                                action = "increase"
                            elif top_set["rpe"] >= 10.0 and ex_obj.target_rpe <= 8.5:
                                status_badge = "OVERSHOOT"
                                action = "deload"
                            else:
                                status_badge = "CONSOLIDATING"
                                action = "hold"
                        else:
                            e1rm_delta = None
                            load_delta = None
                            reps_delta = None
                            status_badge = "BASELINE"
                            action = "hold"

                        if next_proj["status"] == "PROGRESSION_UP":
                            target_text = f"Bracket ceiling reached. Advance load to {next_proj['projected_weight']} kg for {ex_obj.target_reps_min}–{ex_obj.target_reps_max} reps."
                        elif next_proj["status"] == "DYNAMIC_UPSCALE":
                            target_text = f"Velocity surplus detected. Step load up to {next_proj['projected_weight']} kg (+{next_proj['delta_kg']} kg)."
                        elif next_proj["status"] == "RPE_OVERSHOOT_DELOAD":
                            target_text = f"Exertion threshold exceeded. Deload to {next_proj['projected_weight']} kg to re-establish reserve."
                        elif prev_perf:
                            target_text = f"Consolidate at {top_set['weight_kg']} kg. Push for {min(top_set['reps'] + 1, ex_obj.target_reps_max)} reps @ RPE {ex_obj.target_rpe}."
                        else:
                            target_text = f"Baseline logged at {top_set['weight_kg']} kg. Target {ex_obj.target_reps_min}–{ex_obj.target_reps_max} reps next session."

                        exercise_summaries.append(
                            {
                                "name": ex_obj.exercise_name,
                                "top_load": top_set["weight_kg"],
                                "top_reps": top_set["reps"],
                                "top_rpe": top_set["rpe"],
                                "sets_completed": len(working_sets),
                                "volume_load": ex_volume,
                                "current_e1rm": curr_e1rm,
                                "e1rm_delta": e1rm_delta,
                                "load_delta": load_delta,
                                "reps_delta": reps_delta,
                                "action": action,
                                "status_badge": status_badge,
                                "target_text": target_text,
                            }
                        )

                # 3. Atomic commit of all workout sets
                db.log_workout_sets_batch(all_sets_to_batch)

                fatigue_post = evaluate_systemic_fatigue(db)

                with st.spinner("Coach is analyzing session telemetry..."):
                    debrief_content = generate_session_debrief(
                        split_name=day_plan.day_name,
                        readiness=readiness,
                        session_notes=session_notes,
                        exercise_summaries=exercise_summaries,
                        profile=profile or {},
                        total_tonnage=total_tonnage_kg,
                        total_sets=total_working_sets,
                        fatigue_info=fatigue_post,
                    )
                    db.save_session_debrief(session_id, debrief_content)

                    compact_pointer = (
                        f"📋 **Session Logged:** {day_plan.day_name} ({today_date}) | "
                        f"{total_working_sets} Sets | Volume: {total_tonnage_kg:,.1f} kg | "
                        f"Readiness: {readiness}/5 | Saved to Ledger."
                    )
                    db.add_chat_message("assistant", compact_pointer)

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

    # ---------------- TAB 3: Training Assistant ----------------
    with chat_tab:
        c_title, c_clear = st.columns([4, 1])
        with c_title:
            st.subheader("💬 Training Assistant")
            st.caption("Ask biomechanics questions, search movements, or command split adjustments.")
        with c_clear:
            if st.button("🗑️ Clear", use_container_width=True, help="Flush current dialogue context"):
                db.clear_chat_history()
                st.rerun()

        # 1. Render dialogue history from SQLite ledger
        full_history = db.get_chat_history()
        for msg in full_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("Ask a question or enter a command...")
        if user_input:
            # 2. Persist user turn immediately to SQLite and render
            db.add_chat_message("user", user_input)
            with st.chat_message("user"):
                st.markdown(user_input)

            # 3. Clamped 6-message dialogue tail
            recent_records = db.get_chat_history(limit=6)
            tail_messages = []
            for r in recent_records:
                if r["role"] == "user":
                    tail_messages.append(HumanMessage(content=r["content"]))
                elif r["role"] == "assistant":
                    tail_messages.append(AIMessage(content=r["content"]))

            # 4. Real-Time Token Streaming (No blocking spinner)
            with st.chat_message("assistant"):
                initial_state = {
                    "messages": tail_messages,
                    "trainee_id": st.session_state.authenticated_user,
                    "coach_tone": profile.get("coach_tone", "Direct, grounded, and pragmatic"),
                    "custom_instructions": profile.get("custom_instructions", ""),
                    "telemetry_context": None,
                    "intent": None,
                    "intent_metadata": {},
                    "program_updated": False,
                    "response_content": None,
                }

                # Stream tokens iteratively into the active container
                generator = stream_assistant_turn(initial_state)
                streamed_output = st.write_stream(generator)

                # 5. Atomic persistence to SQLite post-completion
                final_response = initial_state.get("response_content") or streamed_output
                if final_response:
                    db.add_chat_message("assistant", final_response)

                # 6. Synchronize routine state on mutations or substitutions
                if initial_state.get("program_updated"):
                    st.session_state.active_program = db.get_active_program()
                    st.toast("Routine updated in ledger!", icon="📋")
                    time.sleep(0.4)
                    st.rerun()
