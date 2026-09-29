# MAYOS Workout Logging UI/UX Redesign

## Goal

Redesign the existing workout logging screen to match the approved concept while preserving all current workout/session logic.

Do **not** reimplement the workout timer. Reuse and visually integrate the existing timer implementation.

---

## 1. Screen Header

Replace the current oversized header layout with:

- Compact top app bar:
  - Back button.
  - `Log workout`.
  - Existing timer shortcut if useful.
  - Overflow menu.
- Session heading:
  - `Anterior`.
  - Secondary progress line:
    - `{completedExercises}/{totalExercises} exercises`
    - `{completedSets}/{totalSets} sets`
- Keep the serif MAYOS display font for major headings only.
- Use the normal application sans-serif typography for exercise/data UI.

---

## 2. Exercise Card Redesign

Each exercise should render as one compact card.

### Header

Show:

- Exercise catalog image.
- Exercise name.
- Prescription:
  - `{sets} sets · {minReps}–{maxReps} reps · RIR ≥ {targetRir}`
- Previous performance:
  - Example: `Last: 60kg × 6 · 60kg × 5`
- Overflow menu on the right.

Do not use blue for the exercise title. Use primary text color and reserve the MAYOS accent blue for active states/actions.

---

## 3. Exercise Catalog Images

Do **not** bundle mock/static exercise images for this screen.

Use the image already associated with the exercise in the MAYOS exercise catalog database.

Flow:

`workout exercise -> exercise/catalog ID -> catalog exercise record -> image reference -> UI`

Requirements:

- Reuse the existing exercise/catalog domain model and repository/service.
- Do not duplicate image metadata inside workout session records.
- Render the catalog image using the application's existing image-storage mechanism.
- Support:
  - loading state;
  - missing-image fallback;
  - failed-image fallback.
- Use a fixed rounded thumbnail container so image dimensions cannot alter card layout.
- Cache images through the application's existing image/cache layer where available.
- Avoid fetching the same catalog exercise/image repeatedly during rebuilds.

Flutter supports network-backed images directly through its image widgets; image loading should still include an appropriate placeholder/failure state. :chatgpt-content-reference{index="0"}

---

## 4. Remove `PREVIOUS` Table Column

Delete the existing:

`SET | PREVIOUS | KG | REPS | RIR | ✓`

Replace with:

`SET | KG | REPS | RIR | ✓`

Previous workout information belongs in the exercise header instead of consuming row width.

---

## 5. Set Row

Each row should contain:

- Set number.
- Weight input.
- Reps input.
- RIR selector.
- Completion control.

Example:

`1 | [60 kg] | [6] | [1 ▼] | ✓`

### Weight

- Numeric keyboard.
- Select existing value when focused.
- Allow direct typing.
- Optional `− / +` controls underneath.
- Preserve existing weight validation/domain rules.

### Reps

- Integer keyboard.
- Select current value on focus.
- Optional `− / +`.
- Preserve existing rep validation.

### RIR

Prefer a selector instead of free text.

Options:

`0, 1, 2, 3, 4+`

Use the application's actual supported RIR constraints if they differ.

---

## 6. Set Completion UX

### Pending set

- Neutral background.
- Outline completion circle/button.

### Active/current set

- Slight MAYOS-blue tinted row background.
- Clearly indicate that this is the next set to perform.

### Completed set

- Filled blue check button.
- Subtle completed-row tint.
- Preserve editable values unless existing workout rules prohibit edits.
- Trigger the existing completion behavior exactly as today.

Do not change workout persistence/sync semantics as part of this UI ticket.

---

## 7. Previous Performance

Resolve the most relevant previous completed performance using existing workout-history logic.

Display below the prescription:

`Last: 60kg × 6 · 60kg × 5`

Rules:

- Show only if historical data exists.
- Otherwise hide the row completely rather than displaying `—`.
- Do not make the historical data editable.
- Do not add additional backend queries per set if the information can be fetched/batched per exercise/session.

---

## 8. Add Set

Replace the plain text action with a full-width secondary action inside the card:

`+ Add set`

It should:

- use existing add-set behavior;
- immediately append the new set;
- preserve current draft/offline synchronization behavior.

---

## 9. Persistent Bottom Workout Bar

Add a fixed bottom bar above the system navigation area.

### Normal state

Display:

- `{completedSets} / {totalSets} sets`
- progress indicator;
- existing workout timer/rest state;
- `Finish` button.

### Resting state

Display the existing timer:

`Rest 01:24 | +30s | Finish`

Important:

- **Reuse the timer implementation already present in MAYOS.**
- Do not create another timer controller/service/state source.
- Bind this UI directly to the existing timer state and actions.
- Reuse existing start/pause/reset/add-time behavior where applicable.
- The timer must survive scrolling because the bar remains fixed.

---

## 10. Scrolling/Layout

Structure approximately as:

`Scaffold`
- body:
  - workout header
  - lazy exercise list
- bottom:
  - persistent workout control bar

Ensure the final exercise can scroll completely above the fixed bottom bar by adding appropriate bottom padding.

Prefer lazy list rendering rather than constructing all exercise cards eagerly.

---

## 11. Responsive Constraints

The row must remain usable on narrow Android screens.

Priorities:

1. set number;
2. weight;
3. reps;
4. RIR;
5. completion control.

Avoid fixed widths that reproduce the current cramped layout.

All interactive controls should maintain practical touch targets; Flutter's accessibility guidance recommends at least 48×48 logical pixels for tappable controls. :chatgpt-content-reference{index="1"}

---

## 12. Theme / Visual Rules

Use existing MAYOS theme tokens rather than hardcoded colors.

Dark-mode target:

- deep navy background;
- slightly lighter exercise cards;
- subtle borders;
- white/high-contrast primary text;
- muted secondary text;
- MAYOS blue for:
  - active row;
  - completed controls;
  - progress;
  - actionable elements.

Ensure the implementation still works with the existing light theme.

Maintain sufficient contrast for labels, previous-performance text and input values. Flutter recommends at least 4.5:1 contrast for normal text. :chatgpt-content-reference{index="2"}

---

## 13. Componentization

Prefer reusable components such as:

- `WorkoutLoggingHeader`
- `ExerciseLoggingCard`
- `ExerciseCatalogThumbnail`
- `SetLoggingRow`
- `RirSelector`
- `PreviousPerformanceSummary`
- `WorkoutBottomBar`

Do not move business logic into these presentation widgets.

Reuse existing workout state/controllers/services.

---

## 14. Preserve Existing Behaviour

This is primarily a UI/UX refactor.

Do not regress:

- workout drafts;
- offline workout capture;
- sync/reconciliation;
- set persistence;
- exercise ordering;
- previous workout data;
- timer functionality;
- workout completion;
- logout/restart recovery;
- existing domain validation.

---

## Acceptance Criteria

- [ ] Screen visually follows the approved redesign.
- [ ] Exercise cards use images from the existing exercise catalog database.
- [ ] No hardcoded/mock exercise images remain.
- [ ] Missing/broken images have a clean fallback.
- [ ] `PREVIOUS` column is removed.
- [ ] Previous performance appears in the exercise header.
- [ ] Weight/reps/RIR inputs are comfortably usable on mobile.
- [ ] Completed/current/pending sets have distinct states.
- [ ] Existing timer is reused, not reimplemented.
- [ ] Timer/rest state appears in the persistent bottom bar.
- [ ] `Finish` remains accessible without scrolling.
- [ ] Existing workout/offline/sync behavior remains unchanged.
- [ ] Dark and light themes remain supported.
- [ ] No overflow on common Android phone widths.
- [ ] Existing tests pass and targeted widget tests are added/updated.