"""Workout logger tab: prescription banner, set-entry form, commit, and debrief."""

import streamlit as st

from ui.api_client import api
from ui.views.debrief import render_debrief
from utils.plate_calculator import calculate_barbell_plates


def _exercise_payload(ex) -> dict:
    return {
        "exercise_id": str(ex.exercise_id),
        "exercise_name": ex.exercise_name,
        "target_sets": ex.target_sets,
        "target_reps_min": ex.target_reps_min,
        "target_reps_max": ex.target_reps_max,
        "target_rpe": ex.target_rpe,
        "rest_seconds": ex.rest_seconds,
        "notes": ex.notes,
    }


def render_logger(program) -> None:
    if not program:
        st.info("No active program loaded. Complete onboarding first.")
        return
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

            session_payload.append({"exercise": _exercise_payload(ex), "sets": ex_sets})
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
        render_debrief(result, readiness)
