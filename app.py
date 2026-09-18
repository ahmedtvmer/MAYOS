"""MYOS Streamlit client. Thin UI over the FastAPI service: no DB, LLM, or domain logic here."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Streamlit Page Configuration MUST be the first command
st.set_page_config(page_title="Myos | Training Engine", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

from utils.plate_calculator import calculate_barbell_plates  # noqa: E402  (pure display math, no DB/LLM)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 30.0
STREAM_TIMEOUT = 300.0


def _ns(value):
    """Converts API dicts/lists to attribute-style namespaces for the render code below."""
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _ns(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_ns(item) for item in value]
    return value


def auth_headers() -> dict:
    token = st.session_state.get("jwt_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def api(method: str, path: str, allow_404: bool = False, **kwargs):
    """JSON API call. Returns parsed body (None for 204, or for 404 when allow_404); reruns login on 401."""
    try:
        response = httpx.request(method, f"{API_BASE_URL}{path}", headers=auth_headers(), timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()
    if response.status_code == 401:
        st.session_state.clear()
        st.error("Session expired. Please log in again.")
        st.rerun()
    if response.status_code == 204:
        return None
    if response.status_code == 404 and allow_404:
        return None
    if response.status_code >= 400:
        detail = response.json().get("detail", "Request failed.") if "application/json" in response.headers.get("content-type", "") else response.text
        st.error(str(detail)[:300])
        st.stop()
    return response.json()


def api_bytes(path: str, params: dict | None = None) -> tuple[str, bytes]:
    try:
        response = httpx.get(f"{API_BASE_URL}{path}", headers=auth_headers(), params=params, timeout=REQUEST_TIMEOUT)
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()
    if response.status_code == 401:
        st.session_state.clear()
        st.error("Session expired. Please log in again.")
        st.rerun()
    if response.status_code >= 400:
        st.error("Download failed.")
        st.stop()
    filename = "program.xlsx"
    if "filename=" in response.headers.get("content-disposition", ""):
        filename = response.headers["content-disposition"].split("filename=")[1].strip('"')
    return filename, response.content


def sse_chat_turn(content: str, holder: dict):
    """Yields assistant tokens from the SSE stream; stashes the done-frame in holder."""
    try:
        with httpx.stream(
            "POST",
            f"{API_BASE_URL}/chat/messages",
            headers=auth_headers(),
            json={"content": content},
            timeout=STREAM_TIMEOUT,
        ) as stream:
            if stream.status_code == 401:
                st.session_state.clear()
                st.error("Session expired. Please log in again.")
                st.rerun()
            if stream.status_code == 429:
                st.error("Too many messages. Please wait a moment and retry.")
                st.stop()
            if stream.status_code >= 400:
                st.error("Assistant request failed.")
                st.stop()
            import json as _json

            pending_error = False
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    pending_error = line[len("event:"):].strip() == "error"
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    event = _json.loads(line[len("data:"):])
                except ValueError:
                    continue
                if "token" in event:
                    yield event["token"]
                elif event.get("done"):
                    holder.update(event)
                elif pending_error:
                    yield event.get("detail", "Assistant request failed.")
                    pending_error = False
    except httpx.ConnectError:
        st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
        st.stop()


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
# Session State Hydration
# -------------------------------------------------------------------------
if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "jwt_token" not in st.session_state:
    st.session_state.jwt_token = None
if "active_program" not in st.session_state:
    st.session_state.active_program = None
if "onboarding_state" not in st.session_state:
    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}

# -------------------------------------------------------------------------
# Gatekeeper: Login & Registration
# -------------------------------------------------------------------------
if not st.session_state.get("authenticated_user") or not st.session_state.get("jwt_token"):
    st.title("⚡ Myos Engine")

    auth_tab, reg_tab = st.tabs(["🔑 Trainee Login", "✨ New Trainee Setup"])

    with auth_tab:
        with st.form("login_form"):
            trainee_id = st.text_input("Trainee ID / Username:").strip()
            submit_login = st.form_submit_button("Access Ledger", use_container_width=True)

            if submit_login and trainee_id:
                try:
                    body = httpx.post(
                        f"{API_BASE_URL}/auth/login", json={"trainee_id": trainee_id}, timeout=REQUEST_TIMEOUT
                    ).json()
                except httpx.ConnectError:
                    st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
                    st.stop()
                if "access_token" in body:
                    st.session_state.authenticated_user = body["trainee_id"]
                    st.session_state.jwt_token = body["access_token"]
                    st.session_state.active_program = None
                    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}
                    st.rerun()
                else:
                    st.error(str(body.get("detail", "Login failed."))[:200])

    with reg_tab:
        with st.form("register_form"):
            new_trainee_id = st.text_input("Choose Unique Trainee ID (letters and numbers only):").strip()
            submit_new = st.form_submit_button("Create Private Ledger", use_container_width=True)

            if submit_new and new_trainee_id:
                try:
                    resp = httpx.post(
                        f"{API_BASE_URL}/auth/register", json={"trainee_id": new_trainee_id}, timeout=REQUEST_TIMEOUT
                    )
                except httpx.ConnectError:
                    st.error(f"Cannot reach the training service at {API_BASE_URL}. Is it running?")
                    st.stop()
                if resp.status_code == 201:
                    body = resp.json()
                    st.session_state.authenticated_user = body["trainee_id"]
                    st.session_state.jwt_token = body["access_token"]
                    st.session_state.active_program = None
                    st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}
                    st.success(f"Ledger initialized for {body['trainee_id']}.")
                    st.rerun()
                else:
                    st.error(str(resp.json().get("detail", "Registration failed."))[:200])

    st.stop()

# -------------------------------------------------------------------------
# Authenticated Trainee Context Hydration
# -------------------------------------------------------------------------
profile = api("GET", "/profile", allow_404=True)
if profile is None and st.session_state.active_program is None:
    program_body = api("GET", "/programs/active")
    if program_body is not None:
        st.session_state.active_program = _ns(program_body)

if profile is None and not st.session_state.onboarding_state["messages"]:
    started = api("POST", "/onboarding/start")
    st.session_state.onboarding_state.update(
        {"messages": [("assistant", text) for text in started.get("messages", [])], "intake_step": started.get("intake_step", 1), "is_complete": started.get("is_complete", False)}
    )


# -------------------------------------------------------------------------
# Program Visualization Helpers
# -------------------------------------------------------------------------
def resolve_media_path(path: str | None) -> str | None:
    """Local file when present, otherwise the service media URL (public catalog assets)."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    for candidate in [Path(path), BASE_DIR / path, BASE_DIR / "data" / path, BASE_DIR / "dataset" / path]:
        if candidate.is_file():
            return str(candidate.resolve())
    name = Path(path).name
    if name and ".." not in Path(name).parts:
        return f"{API_BASE_URL}/media/{name}"
    return None


def render_program_dashboard(program):
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
                        st.session_state.active_program = _ns(result["program"])
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
                st.session_state.active_program = _ns(program_body)
                st.session_state.just_regenerated = True
                st.rerun()

        if st.button("Reset Profile", type="secondary", use_container_width=True):
            api("DELETE", "/profile")
            st.session_state.onboarding_state = {"messages": [], "intake_step": 1, "is_complete": False}
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
                    result = api("POST", "/onboarding/complete")
                    st.write("📐 Synthesizing biomechanics and selecting optimal movements...")
                    program_body = api("GET", "/programs/active")
                    st.session_state.active_program = _ns(program_body) if program_body else None
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

            # 1. Prescription (fatigue + auto-regulated targets) from the service
            prescription = api("GET", "/workouts/prescription", params={"day_order": day_plan.day_order})
            fatigue_info = prescription["fatigue_info"]
            targets_by_exercise = {entry["exercise_id"]: entry for entry in prescription["targets"]}

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
                    target = targets_by_exercise.get(str(ex.exercise_id), {})
                    is_barbell = target.get("is_barbell", False)
                    effective_sets = target.get("effective_sets", ex.target_sets)

                    st.markdown(f"#### #{ex_idx} • {ex.exercise_name.title()}")

                    if fatigue_info["deload_recommended"]:
                        st.caption(
                            f"Prescription: **{effective_sets} sets** (Deload Adjusted from {ex.target_sets}) × "
                            f"{ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {target.get('target_rpe_cap', ex.target_rpe)}"
                        )
                    else:
                        st.caption(
                            f"Prescription: {ex.target_sets} sets × "
                            f"{ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe}"
                        )

                    last_perf = target.get("last_perf") or []
                    default_weight = target.get("projected_weight", 20.0)

                    if last_perf:
                        proj = target.get("projection", {})
                        delta = proj.get("delta_kg", 0)
                        delta_tag = f"(+{delta}kg)" if delta > 0 else (f"({delta}kg)" if delta < 0 else "(Maintained)")
                        st.info(
                            f"🎯 **Auto-Regulated Target:** {proj.get('projected_weight', default_weight)} kg × {ex.target_reps_min}–{ex.target_reps_max} reps @ RPE {ex.target_rpe} {delta_tag}"
                        )

                        if target.get("large_jump"):
                            top_prev = max(last_perf, key=lambda s: s["weight_kg"])
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
                            warmups = target.get("warmups") or []
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

                    session_payload.append(
                        {
                            "exercise": {
                                "exercise_id": str(ex.exercise_id),
                                "exercise_name": ex.exercise_name,
                                "target_sets": ex.target_sets,
                                "target_reps_min": ex.target_reps_min,
                                "target_reps_max": ex.target_reps_max,
                                "target_rpe": ex.target_rpe,
                                "rest_seconds": ex.rest_seconds,
                                "notes": ex.notes,
                            },
                            "sets": ex_sets,
                        }
                    )
                    st.divider()

                session_notes = st.text_input("Session Notes (pumps, joint aches, fatigue):")
                submit_btn = st.form_submit_button("🏁 Finish & Commit Workout to Ledger", use_container_width=True)

            if submit_btn:
                result = api(
                    "POST",
                    "/workouts/sessions",
                    json={
                        "day_order": day_plan.day_order,
                        "readiness": readiness,
                        "session_notes": session_notes,
                        "sets": session_payload,
                    },
                )
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

    # ---------------- TAB 3: Training Assistant ----------------
    with chat_tab:
        c_title, c_clear = st.columns([4, 1])
        with c_title:
            st.subheader("💬 Training Assistant")
            st.caption("Ask biomechanics questions, search movements, or command split adjustments.")
        with c_clear:
            if st.button("🗑️ Clear", use_container_width=True, help="Flush current dialogue context"):
                api("DELETE", "/chat/history")
                st.rerun()

        # 1. Render dialogue history from the service ledger (authoritative text only)
        full_history = api("GET", "/chat/history")
        for msg in full_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("Ask a question or enter a command...")
        if user_input:
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                holder: dict = {}
                st.write_stream(sse_chat_turn(user_input, holder))

            # 5. Server persists the authoritative response; refresh routine state on mutations
            if holder.get("program_updated"):
                latest = api("GET", "/programs/active")
                st.session_state.active_program = _ns(latest) if latest else None
                st.toast("Routine updated in ledger!", icon="📋")
                time.sleep(0.4)
                st.rerun()
