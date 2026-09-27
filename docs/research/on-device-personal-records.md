# Research: can existing data seed on-device personal-record checks?

Ticket: #106 (map #102). Sources: this repository at commit `d764de7` (branch `feat/web-into-app`). Every claim cites `path:line` at that commit.

## Answer in brief

- **"Previous" column: mostly yes, already.** `GET /workouts/prescription` returns `last_perf` for every *planned* exercise of a program day. `last_perf` holds the working sets of the most recent session containing that exercise, ordered by `set_index`. The app already caches this per day for offline use but never displays it. There is no equivalent for an **unplanned** exercise.
- **PR baseline: no, not cleanly.** `GET /dashboard/personal-records` is a recent-events feed (at most 100 rows across all exercises). It is not a per-exercise best. Its `max_weight` records are also scoped to the exact rep count. Per-exercise bests can be derived from `GET /dashboard/exercises/{id}/history` (`records`), but that takes one call per exercise. Neither endpoint tells "no history" apart from "history but no loaded sets".
- **Missing effort: the commit path cannot tolerate it today.** Some readers default a NULL RPE to 8.5. The session-commit and prescription paths, however, call `float(None)` or compare `None`, and the API schema requires `rpe`.
- **Recommendation:** add one read endpoint, `GET /workouts/baselines`, that returns per-exercise bests plus the last session's sets for every exercise the player has logged. Also make `rpe` nullable end to end. The details are at the end of this file.

## 1. What the backend computes today

### e1RM formula

`agent/progression_engine.py:23-27`:

```python
def calculate_e1rm(weight_kg, reps, rpe):
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    effective_reps = reps + (10.0 - min(max(rpe, 6.0), 10.0))
    return weight_kg * (1.0 + (effective_reps / 30.0))
```

This is Epley with RPE-adjusted reps: `effective_reps = reps + RIR`, where RIR = 10 − RPE and RPE is clamped to [6, 10]. So **e1RM depends on effort**. At RPE 10 it is plain Epley, and RPE 8.5 adds 1.5 reps. Wherever RPE may be missing, the engine substitutes **8.5**: `_set_e1rm` (`progression_engine.py:218-224`), `get_exercise_progression_history` (`:212-213`), CSV/JSON export (`service/sessions.py:25`). For PR checks on the device to match the server, the device must use this exact formula, the [6, 10] clamp, and the 8.5 default.

### PR detection (ADR 009)

- It runs server-side at commit, inside the ledger transaction: `service/workouts.py:539-551` calls `evaluate_session_prs` for **every submitted exercise, planned or unplanned**.
- Set filter (`progression_engine.py:345-351`): it excludes warm-ups and any set with `weight_kg <= 0` or `reps <= 0`.
- Candidate reduction (`:354-368`): it takes the heaviest set per exact rep count plus the single best-e1RM set. At most one row per record type per movement per session.
- Record types (`:237-241`, `database/schema/definitions.py:161-172`):
  - `max_weight` is **scoped to the exact rep count** (`WHERE ... record_type='max_weight' AND reps = ?`, `progression_engine.py:251-257`). It is "heaviest 5-rep set", not "heaviest weight ever".
  - `max_e1rm` covers the whole exercise (`:259-265`).
- Only strictly greater values count (`:268`), so a tie is not a PR.
- **The first session is recorded as a PR.** With no prior row, `current = 0.0` (`:267`), every positive value beats it, and a row is inserted with `prev_value = NULL` (`:283`). That PR reaches the commit response (`new_prs`, `service/workouts.py:581`) and the debrief. ADR 009 (`DECISIONS.md:79-82`) backfilled history at migration time so the *first post-ship* session would not create trivial PRs. A brand-new exercise, though, still records one.
- `personal_records` is append-only and values strictly increase per key, so `MAX(value)` per `(exercise_id, record_type[, reps])` is the current best.

### Endpoints that expose this

- `GET /dashboard/personal-records?limit=` (`svc/routers/dashboard.py:56-66` → `service/dashboard.py:41-55`). It returns the most recent PR *events* across all exercises, ordered by `achieved_at DESC`, with a limit clamped to 1..100. Each row has `exercise_id, name, record_type, reps, value, prev_value, achieved_at, session_id`. It is a feed of events, not a table of bests, and an exercise whose last PR is older than the most recent 100 events drops out of it.
- `GET /dashboard/exercises/{id}/history` (`svc/routers/dashboard.py:38-53`). It returns `history` (one point per session date, taken from the **heaviest** set that day, not the best-e1RM set: `progression_engine.py:192-215`, ordered by `weight_kg DESC` at `:200`) and `records` (every PR row for the exercise, `service/dashboard.py:58-70`). It is complete for a single exercise, but it costs one request per exercise.
- The app models the feed as `PersonalRecord` (`mobile/lib/src/core/models.dart:1626-1652`), and `ApiClient.personalRecords` calls it (`mobile/lib/src/core/api_client.dart:901-911`).

### Unplanned exercises

- The client submits them with a synthetic `ProgramExerciseSchema` (8–12 reps, RPE 8, 3 sets): `mobile/lib/src/features/player/workout/workout_logger_screen.dart:576-595`. The server checks that the id exists in the catalog (`svc/routers/workouts.py:32-45`).
- They are stored in `workout_sets` like any other set, and their PRs are evaluated (`service/workouts.py:540-551`). They are also recorded as `unplanned` divergences (`:520-528`).
- The data is the same as for planned exercises. The gap is **delivery**: `build_prescription` iterates only `day_plan.exercises` (`service/workouts.py:323`), so an unplanned exercise has no `last_perf` and no baseline on the device.

### Bodyweight exercises

- There is no bodyweight model. `weight_kg` is an external load with `ge=0` (`svc/schemas.py:639`), and the profile's body weight is never added to it.
- Sets at 0 kg are stored and count toward set totals, but `calculate_e1rm` returns 0 (`progression_engine.py:24-25`), and PR evaluation skips them (`:348`, `:318`, `:248`). **Unloaded bodyweight exercises can never produce a PR today.** Weighted bodyweight exercises (for example, dips with +10 kg) use only the added load.
- `EQUIPMENT_INCREMENTS` lists `bodyweight` (`:18-19`), but only for load stepping.

## 2. Can the API return the previous session's sets per exercise of a day?

Yes, for planned exercises:

- `build_prescription` (`service/workouts.py:318-362`) puts `last_perf = db.get_last_performance(exercise_id)` on each target (`:330`, `:337`).
- `get_last_performance` (`database/ledger/workouts.py:426-452`) finds the most recent session that has a working set of that exercise, ordered by `started_at DESC, ROWID DESC` (`:434`). It returns that session's working sets as `{set_index, weight_kg, reps, rpe}`, ordered by `set_index` (`:445-448`).
- "Previous" means **the last time this exercise was trained**, whatever the day or program. It does not mean "the last time this program day was run". This is the Hevy behaviour.
- The app parses it into `PrescriptionTarget.lastPerf` (`models.dart:1946-1989`) and caches the prescription per account and day for offline logging (`mobile/lib/src/core/workout_storage.dart:149-218`, loaded in `workout_logger_screen.dart:105-129`). **`lastPerf` is not read anywhere in the UI**, so the "previous" column only needs the UI to render it.

Caveats:

- Warm-ups are excluded (`is_warmup = 0`, `ledger/workouts.py:433,447`). So `set_index` values can skip, because warm-ups share the index sequence (`service/workouts.py:426-436`). Row *N* of the new logger should pair with the *N*th returned working set, not with `set_index == N`.
- The order uses `started_at`, which the commit path sets to the **commit time** (`service/workouts.py:389-394`), not to `session_date`. An offline draft synced late for an earlier performed date would therefore rank as "most recent". Most other ledger reads order by `session_date` first (`ledger/workouts.py:250`).
- Unplanned exercises: nothing is returned (see §1).

## 3. Behaviour when effort (RPE) is missing

The storage layer allows it: `workout_sets.rpe REAL CHECK(rpe BETWEEN 1 AND 10)` is nullable (`database/schema/definitions.py:147`). Everything above storage assumes a value is present.

**The API refuses it.** `WorkoutSetIn.rpe: float = Field(ge=6.0, le=10.0)` is required (`svc/schemas.py:641`). An RIR above 4 would map to an RPE below 6, which the schema rejects. Values of 4 and below are fine, since RIR 0–4 maps to RPE 10–6.

**The app hides it.** The logger fills a missing RPE with 8.5 (`workout_logger_screen.dart:542`), as does `WorkoutSetLog.fromJson` (`models.dart:1666`). `WorkoutSetLog.rpe` is non-nullable (`models.dart:1672`). A skipped RPE is therefore sent as a real 8.5, and the server cannot tell it apart from one the player entered.

**These places break on `None` (commit and prescription paths):**

| Location | What happens with `rpe=None` |
|---|---|
| `service/workouts.py:435` | `float(s["rpe"])` → TypeError, so the commit fails |
| `service/workouts.py:444, 449` | `calculate_e1rm` / `project_next_load` with `None` → `max(None, 6.0)` TypeError |
| `service/workouts.py:467, 469` | `top_set["rpe"] <= ...` / `>= 10.0` → TypeError |
| `service/workouts.py:345, 458` | `.get("rpe", 8.5)` returns `None` when the key exists with a NULL value (rows from `get_last_performance` always carry the key), so a stored NULL would crash the **next** prescription and commit |
| `agent/progression_engine.py:75, 84, 93` | `project_next_load` compares `last_rpe` directly |

**These places already tolerate `None`:** `_set_e1rm` for PR evaluation (`progression_engine.py:219-223`), progression history (`:212-213`), `get_progression_signals` (reads the already-defaulted history at `:422`), fatigue (`:471` filters `rpe IS NOT NULL`), export (`service/sessions.py:25`), debrief best-set deltas (`database/ledger/debriefs.py:39, 72`), and assistant session comparisons (`agent/assistant_graph.py:593, 619-620`).

Conclusion: "RIR optional, stored as RPE" needs backend work. The work is `rpe: float | None` in the schema, storing NULL, and a single `rpe if rpe is not None else 8.5` default in `_persist_session` and `build_prescription`. With that default in place, the e1RM of an effortless set is `weight × (1 + (reps + 1.5)/30)`, which is what the device must reproduce.

## 4. Data model a logger needs to decide PRs offline

Per exercise, fetched when the workout starts and cached with the prescription:

| Field | Why | Available today? |
|---|---|---|
| `has_history` (or `sessions_logged`) | "First session is the baseline, not a record": no PR badge without history | Not directly. Can be inferred from a non-empty `last_perf` (planned exercises only) |
| `max_weight_kg` across the whole exercise, all rep counts | The map's "heaviest weight" | Derivable as `MAX(value)` over `max_weight` rows of `/exercises/{id}/history` `records`, or `MAX(weight_kg)` of working sets. Not in any bulk endpoint |
| `best_e1rm_kg` | The map's "best e1RM" | `MAX(value)` over `max_e1rm` rows, same per-exercise call. Not in any bulk endpoint |
| `last_session_sets[]` | The "previous" column | Yes for planned exercises (`last_perf`). No for unplanned ones |

"First session" should be defined as **no committed working set with `weight_kg > 0` and `reps > 0` for this exercise before this workout**, the same filter PR evaluation uses. Bodyweight-only history then does not count as a baseline. On the device the session is also a baseline if the exercise appears in no *pending, unsynced* draft. Otherwise a second offline workout would compare against a stale server baseline, so the device should fold its unsynced drafts into the baseline.

Then on the device, for each ticked working set: badge "heaviest weight" if `has_history && weight > max(baseline.max_weight, best in this session so far)`, and badge "best e1RM" likewise, using the §1 formula with the 8.5 default. Only strictly greater values count, matching ADR 009.

## Facts that conflict with, or need reconciling against, the map's decisions

1. **"Heaviest weight" is not the server's `max_weight`.** The server's weight record is scoped to the exact rep count (ADR 009, `progression_engine.py:251-257`). The map's device badge is exercise-wide. Either the device record differs in meaning from the stored/dashboard `max_weight` rows, or the server is changed. This must be decided explicitly.
2. **The server records a PR on an exercise's first session** (`prev_value = NULL`, `progression_engine.py:267-283`). The map says the first session is a baseline and not a record. The commit response `new_prs` and the debrief would then show a record the logger did not badge. The server must suppress PRs when the exercise had no prior history, or the summary screen must ignore `prev_value = NULL` events.
3. **The progression engine cannot tolerate missing effort in the commit path** (§3). The schema requires `rpe ≥ 6`, so RIR above 4 is unrepresentable. The app silently sends 8.5 for a blank RPE.
4. **e1RM depends on effort.** A "best e1RM" PR for a set without RIR relies on the 8.5 default. The same weight × reps logged at RIR 0 has a *lower* e1RM than one logged blank (RPE 8.5 adds 1.5 reps; RPE 10 adds 0). If "blank" should not beat "honest RIR 0", the device and server need a different default for missing effort (for example 10, meaning plain Epley). Changing the default would also shift the historical e1RM series.
5. **Unloaded bodyweight exercises can never produce a PR** (weight 0 is excluded). This matches the server, but the logger UI should not imply otherwise.

## Recommended endpoint shape

One read-only endpoint in the player's own ledger, fetched when the workout starts and cached next to the prescription:

```
GET /workouts/baselines
→ 200
{
  "e1rm": {"formula": "epley_rpe_adjusted", "missing_rpe_default": 8.5, "rpe_clamp": [6.0, 10.0]},
  "exercises": [
    {
      "exercise_id": "0025",
      "sessions_logged": 7,              // sessions with >=1 loaded working set; 0 => baseline session
      "max_weight_kg": 102.5,            // exercise-wide, working sets with weight>0 & reps>0
      "best_e1rm_kg": 121.33,            // same filter, missing RPE -> 8.5
      "last_session": {
        "session_id": "…",
        "session_date": "2026-09-24",
        "sets": [ {"weight_kg": 100.0, "reps": 5, "rpe": 8.0}, … ]   // working sets, in order
      }
    }
  ]
}
```

- It covers **every exercise the player has ever logged**, so unplanned exercises work offline too. The payload is one row per distinct exercise, which is small.
- It is computed from `workout_sets`, not from `personal_records`. This makes it exercise-wide by construction and independent of the rep-scoped ledger.
- "Previous" should be ordered by `session_date DESC, started_at DESC, rowid DESC` to fix the late-sync ordering caveat in §2. Optionally, `?exercise_ids=` could narrow the response.
- `last_perf` in `/workouts/prescription` can stay for compatibility. The logger should read from `baselines`.
- Accompanying backend changes, which are separate tickets: make `WorkoutSetIn.rpe` optional with NULL stored and a single 8.5 default in `_persist_session`/`build_prescription`. Decide conflicts 1, 2 and 4 above.
