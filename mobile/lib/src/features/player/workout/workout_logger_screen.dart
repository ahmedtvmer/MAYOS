import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../../core/active_workout.dart';
import '../../../core/api_client.dart';
import '../../../core/baselines.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/personal_records.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_settings_tile.dart';
import '../../../core/ui/mayos_stat.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'active_workout_controller.dart';
import 'draft_sync_service.dart';
import 'logger_bottom_bar.dart';
import 'logger_card_widgets.dart';
import 'logger_keypad.dart';
import 'rest_timer_widgets.dart';

// The frozen previous working set and the cell weight format live beside the
// Active workout (`core/active_workout.dart`); the cell/hint mapping, the
// card and the rows live in `logger_card_widgets.dart` (#158), the fixed
// bottom bar in `logger_bottom_bar.dart` (#160) — this screen owns only the
// decisions: focus, ticks, records, the Current set and persistence
// (#123/#124/#125).

/// The catalog dialog's content width. It is the app's narrow-phone content
/// width, kept as one named constant because the dialog measures its content
/// intrinsically and a shrink-wrapped results viewport cannot answer that
/// without a bounded width (#123 item 11).
const double kLoggerDialogWidth = 360;

/// Why Finish refuses while nothing is ticked (#123), and the one message a
/// tick itself clears (#160): it is the Finish bar's own nudge, shown right
/// above that bar, so it must not outlive the state it describes. Other
/// errors (a failed save, an offline refusal) stay until they are fixed.
const String _kFinishBlockedError = 'Log at least one set';

/// The message slot's cap (#160/#45): at most this share of the screen
/// height, scrolling inside itself, so a long line at a large text scale
/// can never push the bottom bar (or the keypad) off the screen.
const double _kMessageSlotMaxHeightFraction = 1 / 3;

/// The Hevy-style table logger (#107 Variant A), backed entirely by the
/// Active workout: one scrolling list of compact exercise cards with a
/// SET · KG · REPS · RIR · ✓ table, the app's own keypad, live
/// Personal-record badges under the rows (#124), and a persistent bottom bar
/// carrying sets progress and a Finish that opens the workout summary and
/// writes a Workout draft exactly as before (#123/#160). The redesign
/// (#158/#159/#160) drops the PREVIOUS column for the card's "Last:" line,
/// highlights the Current set and pins Finish above the system navigation;
/// everything below the pixels is unchanged.
class WorkoutLoggerScreen extends ConsumerStatefulWidget {
  const WorkoutLoggerScreen({super.key, required this.dayOrder});

  /// The day this route was opened for; only used when no Active workout
  /// exists yet and one has to be started from the cached program.
  final int dayOrder;

  @override
  ConsumerState<WorkoutLoggerScreen> createState() =>
      _WorkoutLoggerScreenState();
}

class _WorkoutLoggerScreenState extends ConsumerState<WorkoutLoggerScreen> {
  final TextEditingController _notes = TextEditingController();

  bool _loading = true;
  String? _loadError;
  String? _error;

  /// A non-blocking note to the player (e.g. a clamped performed date).
  String? _notice;
  bool _fromCache = false;

  /// Null only when it could not be determined at all (never guessed as
  /// `'UTC'`) — Finish stays blocked until it is known (ADR 020/033).
  String? _timezone;
  DateTime _performedDate = DateTime.now();
  int _readiness = 4;

  /// The workout summary, which replaces the old plain save step (#124): open
  /// from Finish until Back or a successful Save.
  bool _summaryStep = false;

  /// The celebration and the stats, computed once on the device when Finish
  /// opens the summary and never recomputed after that (#124: a summary
  /// already shown is never rewritten after a sync).
  WorkoutSummary? _summary;
  bool _saving = false;
  LoggerCellFocus? _focus;

  /// The foreground countdown ticker (#125): while a rest runs it wakes the
  /// bar every quarter second and, at the end time, completes the rest — the
  /// vibration, the sound, and the bar going away — even when the keypad (and
  /// so the bar) is hidden.
  Timer? _restTicker;

  @override
  void initState() {
    super.initState();
    unawaited(_keepAwake(true));
    Future<void>.microtask(_load);
  }

  @override
  void dispose() {
    _restTicker?.cancel();
    _restTicker = null;
    unawaited(_keepAwake(false));
    _notes.dispose();
    super.dispose();
  }

  /// Starts or stops the ticker to match whether a rest is running. Called
  /// from build, which only ever touches the timer, never the tree.
  void _syncRestTicker(ActiveWorkout workout) {
    final bool running = workout.rest != null;
    if (running && _restTicker == null) {
      _restTicker = Timer.periodic(
          const Duration(milliseconds: 250), (_) => _onRestTick());
    } else if (!running && _restTicker != null) {
      _restTicker?.cancel();
      _restTicker = null;
    }
  }

  void _onRestTick() {
    final ActiveRestTimer? rest = _workout?.rest;
    if (rest == null) {
      return;
    }
    final DateTime now = DateTime.now();
    if (rest.isOver(now)) {
      unawaited(_controller.completeRest());
      return;
    }
    if (rest.remainingSeconds(now) <= 1) {
      // The foreground end is a second away: drop the platform alarm so the
      // ticker's own end is the only alert for this rest (#125).
      unawaited(_controller.dropImminentEndAlarm());
    }
    // No setState here: this ticker exists for the end-of-rest alert alone,
    // so it runs even behind the keypad, while the countdown repaints itself
    // through RestTimerControls' own ticker (#160). The rest ending changes
    // the controller's state, which rebuilds the screen anyway.
  }

  /// The chip's picker (#125): Off, then 1:00–5:00 in 15-second steps, saved
  /// as this device's override for the exercise.
  Future<void> _pickRest(int exerciseIndex) async {
    final int? picked = await showRestLengthPicker(
      context,
      initial: _controller.restLengthFor(exerciseIndex),
    );
    if (picked == null || !mounted) {
      return;
    }
    await _controller.setRestLength(exerciseIndex, picked);
    // The override lives in the device store, not in the Active workout's
    // state, so the chip has to be rebuilt by hand (#125).
    if (mounted) {
      setState(() {});
    }
  }

  /// The screen stays awake while the logger is open (#107). Kept best-effort
  /// so an unsupported platform (or a test host) never breaks the screen.
  Future<void> _keepAwake(bool on) async {
    try {
      if (on) {
        await WakelockPlus.enable();
      } else {
        await WakelockPlus.disable();
      }
    } on Object {
      // No-op where wakelock is unavailable.
    }
  }

  Future<void> _load() async {
    // Opening the logger starts a fresh session: any summary snapshot a
    // previous one left behind is dropped, so the top bar's Workout time is
    // live again rather than frozen on a workout that was already saved or
    // discarded (#159). The snapshot is cleared on Back too, which is the
    // only exit that keeps this screen mounted.
    if (mounted) {
      ref.read(loggerSummaryProvider.notifier).state = null;
    }
    if (!ref.read(offlineWorkoutDraftsEnabledProvider)) {
      // The web client is online-only and never captures drafts (ADR 022).
      setState(() => _loading = false);
      return;
    }
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    if (accountId == null) {
      setState(() {
        _loading = false;
        _loadError = 'You are not signed in.';
      });
      return;
    }
    _timezone = await ref.read(deviceTimezoneOrNullProvider);
    // The offline banner tracks what this screen could fetch, exactly as the
    // logger did when it loaded the program itself.
    bool fromCache = false;
    try {
      await ref.read(apiClientProvider).activeProgram();
    } on ApiException {
      fromCache = true;
    }

    final ActiveWorkoutController controller =
        ref.read(activeWorkoutControllerProvider.notifier);
    // Waits for the device restore for this account, so a workout that is
    // still loading is never mistaken for a missing one.
    await controller.syncAccount(accountId);
    if (controller.workout == null) {
      // Reached without an Active workout (deep link): start one from the
      // cached program day, the way Home/Program do.
      final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
      final TrainingProgram? program = await cache.readProgram(accountId);
      ProgramDay? day;
      for (final ProgramDay candidate
          in program?.days ?? const <ProgramDay>[]) {
        if (candidate.dayOrder == widget.dayOrder) {
          day = candidate;
        }
      }
      if (day == null) {
        if (!mounted) return;
        setState(() {
          _loading = false;
          _loadError = 'This training day is not available offline.';
          _fromCache = fromCache;
        });
        return;
      }
      await controller.startFromDay(
        accountId: accountId,
        day: day,
        programVersion: program?.version,
      );
    }
    final ActiveWorkout? workout = controller.workout;
    if (!mounted) return;
    setState(() {
      _fromCache = fromCache;
      _loading = false;
      if (workout != null) {
        _applyDefaultPerformedDate(workout);
      }
    });
  }

  /// The workout summary's performed date defaults to the day the Active
  /// workout started (#123), and
  /// that day is held to the same allowed window the date picker enforces
  /// (ADR 020/035): a start day outside it is clamped exactly like the old
  /// logger's picker clamps an out-of-range date, and the player is told
  /// (#123 item 7).
  void _applyDefaultPerformedDate(ActiveWorkout workout) {
    final DateTime started =
        DateTime.tryParse(workout.startedDate) ?? DateTime.now();
    final DateTime clamped = performedDateWindow().clamp(started);
    _performedDate = clamped;
    if (formatPerformedDate(clamped) != formatPerformedDate(started)) {
      _notice = 'This workout started on ${formatPerformedDate(started)}, '
          'outside the allowed entry window, so its performed date was set '
          'to ${formatPerformedDate(clamped)}.';
    }
  }

  ActiveWorkout? get _workout =>
      ref.read(activeWorkoutControllerProvider).workout;

  ActiveWorkoutController get _controller =>
      ref.read(activeWorkoutControllerProvider.notifier);

  /// Why Finish is blocked beyond "no sets ticked", or null.
  String? get _blockReason {
    if (_timezone == null) {
      return 'Your device timezone could not be determined, so the workout '
          'date cannot be recorded truthfully. Check your device time-zone '
          'settings and try again.';
    }
    if (_workout?.programVersion == null && _workout != null) {
      return 'No cached program version is available offline. Connect once '
          'to refresh your program before logging this workout.';
    }
    return null;
  }

  // ---- table interactions -------------------------------------------------

  String _initialText(ActiveWorkout workout, LoggerCellFocus focus) {
    final ActiveWorkoutExercise exercise =
        workout.exercises[focus.exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[focus.setIndex];
    return cellTexts(
          set: set,
          previous: previousSetFor(exercise, focus.setIndex, workout.baselines),
          prescriptionHint: exercise.prescriptionHint,
          field: focus.field,
        ).value ??
        '';
  }

  // ---- personal records (#124) -------------------------------------------

  /// The badge state of one exercise's rows right now, keyed by row id: the
  /// calculator is pure over the persisted rows and the frozen baseline, so
  /// every render recomputes exactly what the Active workout holds.
  Map<String, SetRecordBadges> _recordBadges(int exerciseIndex) {
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= workout.exercises.length) {
      return const <String, SetRecordBadges>{};
    }
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    return exerciseRecordBadges(
      sets: exercise.sets,
      baseline: workout.baselines[exercise.exerciseId],
    );
  }

  /// The row the focused cell belongs to, and the records it held when that
  /// cell took focus: the snapshot a settled edit is compared against, so the
  /// heavy haptic fires once when the player leaves the cell — never per
  /// keystroke (#124).
  ({int exerciseIndex, String setId, Set<PrRecordKind> before})? _recordFocus;

  /// Moves focus to [next]: the old cell settles first (its row's records are
  /// compared with the snapshot it took at focus, and a record the edit newly
  /// earned gets the heavy haptic), then [next] takes its own snapshot.
  void _changeFocus(LoggerCellFocus? next) {
    _settleRecordFocus();
    _focus = next;
    _recordFocus = null;
    if (next == null) {
      return;
    }
    final String? setId = _setIdAt(next.exerciseIndex, next.setIndex);
    if (setId == null) {
      return;
    }
    _recordFocus = (
      exerciseIndex: next.exerciseIndex,
      setId: setId,
      before: _recordBadges(next.exerciseIndex)[setId]?.current ??
          const <PrRecordKind>{},
    );
  }

  /// Settles the focused cell's edit: the heavy haptic fires only if its row
  /// now holds a record the focus-time snapshot did not.
  void _settleRecordFocus() {
    final ({
      int exerciseIndex,
      String setId,
      Set<PrRecordKind> before
    })? recordFocus = _recordFocus;
    _recordFocus = null;
    if (recordFocus == null) {
      return;
    }
    final Set<PrRecordKind> now =
        _recordBadges(recordFocus.exerciseIndex)[recordFocus.setId]?.current ??
            const <PrRecordKind>{};
    if (now.difference(recordFocus.before).isNotEmpty) {
      unawaited(HapticFeedback.heavyImpact());
    }
  }

  /// Re-snapshots the focused cell's row after an action that settles a value
  /// on its own — tick, untick, warm-up toggle, delete — so only a cell edit
  /// can make a later settle vibrate (#124).
  void _refreshRecordFocus() {
    final ({
      int exerciseIndex,
      String setId,
      Set<PrRecordKind> before
    })? recordFocus = _recordFocus;
    if (recordFocus == null) {
      return;
    }
    _recordFocus = (
      exerciseIndex: recordFocus.exerciseIndex,
      setId: recordFocus.setId,
      before: _recordBadges(recordFocus.exerciseIndex)[recordFocus.setId]
              ?.current ??
          const <PrRecordKind>{},
    );
  }

  /// Applies [mutate] and then heavy-haptics when the row it touched newly
  /// holds a solid record — for the actions that settle a value themselves
  /// (the tick, the warm-up toggle), with no pop-up (#124).
  Future<void> _updateWithRecordHaptic(
    int exerciseIndex,
    int setIndex,
    Future<void> Function() mutate,
  ) async {
    final String? setId = _setIdAt(exerciseIndex, setIndex);
    final Map<String, SetRecordBadges> before = _recordBadges(exerciseIndex);
    await mutate();
    if (!mounted) {
      return;
    }
    _refreshRecordFocus();
    if (setId == null) {
      return;
    }
    final Set<PrRecordKind> held =
        _recordBadges(exerciseIndex)[setId]?.current ?? const <PrRecordKind>{};
    final Set<PrRecordKind> had =
        before[setId]?.current ?? const <PrRecordKind>{};
    if (held.difference(had).isNotEmpty) {
      unawaited(HapticFeedback.heavyImpact());
    }
  }

  String? _setIdAt(int exerciseIndex, int setIndex) {
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= workout.exercises.length ||
        setIndex < 0 ||
        setIndex >= workout.exercises[exerciseIndex].sets.length) {
      return null;
    }
    return workout.exercises[exerciseIndex].sets[setIndex].id;
  }

  void _onKeypadText(String text) {
    final LoggerCellFocus? focus = _focus;
    if (focus == null) {
      return;
    }
    // A keystroke is never settled: the heavy haptic waits for the edit to
    // commit — Next, Hide, or leaving the cell (#124).
    switch (focus.field) {
      case LoggerField.kg:
        unawaited(_controller.updateCell(focus.exerciseIndex, focus.setIndex,
            weightKg: double.tryParse(text) ?? 0));
      case LoggerField.reps:
        unawaited(_controller.updateCell(focus.exerciseIndex, focus.setIndex,
            reps: int.tryParse(text) ?? 0));
      case LoggerField.rir:
        break; // RIR is one-tap chips only.
    }
  }

  /// One-tap RIR chips: set the value, then advance to the next set's kg the
  /// way the #107 prototype does, so a run of sets can be rated without
  /// hunting for the next cell (#123 item 10).
  void _onKeypadRir(double? rir) {
    final LoggerCellFocus? focus = _focus;
    if (focus == null) {
      return;
    }
    unawaited(_commitRir(focus, rir));
  }

  /// The chip's value and its advance are one action, so the edit settles —
  /// and the record haptic can fire — the moment the chip is tapped.
  Future<void> _commitRir(LoggerCellFocus focus, double? rir) async {
    if (rir == null) {
      await _controller.updateCell(focus.exerciseIndex, focus.setIndex,
          unrated: true);
    } else {
      await _controller.updateCell(focus.exerciseIndex, focus.setIndex,
          rir: rir);
    }
    if (!mounted) {
      return;
    }
    final ActiveWorkout? workout = _workout;
    if (workout == null) {
      return;
    }
    setState(() => _changeFocus(nextLoggerCellFocus(workout, focus)));
  }

  void _onKeypadNext() {
    final ActiveWorkout? workout = _workout;
    final LoggerCellFocus? focus = _focus;
    if (workout == null || focus == null) {
      return;
    }
    setState(() => _changeFocus(nextLoggerCellFocus(workout, focus)));
  }

  void _onKeypadHide() {
    setState(() => _changeFocus(null));
  }

  /// Ticking: empty cells take the previous value first; when a required cell
  /// (kg or reps) still has nothing, the tick opens the keypad there instead.
  Future<void> _toggleTick(int exerciseIndex, int setIndex) async {
    final ActiveWorkout? workout = _workout;
    if (workout == null) {
      return;
    }
    if (_error == _kFinishBlockedError) {
      // The Finish bar's own nudge, sitting right above that bar: a tick
      // makes it untrue, so it goes. Every other message — a save failure,
      // an offline refusal — is never dismissed by ticking (#160).
      setState(() => _error = null);
    }
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    if (set.ticked) {
      await _controller.setTicked(exerciseIndex, setIndex, false);
      // An untick only recalculates: it never vibrates (#124).
      _refreshRecordFocus();
      return;
    }
    final BaselineSet? prev =
        previousSetFor(exercise, setIndex, workout.baselines);
    double weight = set.weightKg;
    int reps = set.reps;
    double? rir = set.rir;
    bool changed = false;
    if (weight <= 0 && prev != null) {
      weight = prev.weightKg;
      changed = true;
    }
    if (reps <= 0 && prev != null) {
      reps = prev.reps;
      changed = true;
    }
    if (rir == null && prev != null && prev.rir != null) {
      rir = prev.rir;
      changed = true;
    }
    if (weight <= 0 || reps <= 0) {
      // Nothing to log yet: open the keypad at the first required cell.
      setState(() => _changeFocus(LoggerCellFocus(exerciseIndex, setIndex,
          weight <= 0 ? LoggerField.kg : LoggerField.reps)));
      return;
    }
    if (changed) {
      await _controller.updateCell(exerciseIndex, setIndex,
          weightKg: set.weightKg <= 0 ? weight : null,
          reps: set.reps <= 0 ? reps : null,
          rir: set.rir == null && rir != null ? rir : null);
    }
    await _updateWithRecordHaptic(
      exerciseIndex,
      setIndex,
      () => _controller.setTicked(exerciseIndex, setIndex, true),
    );
    unawaited(HapticFeedback.selectionClick());
    if (!mounted) {
      return;
    }
    setState(() {
      if (_focus != null &&
          _focus!.exerciseIndex == exerciseIndex &&
          _focus!.setIndex == setIndex) {
        _changeFocus(null);
      }
    });
  }

  Future<void> _removeSet(int exerciseIndex, int setIndex) async {
    // A delete recalculates badges; it never vibrates, so the focused cell's
    // snapshot goes with the focus (#124).
    setState(() {
      _recordFocus = null;
      _focus = null;
    });
    await _controller.removeSet(exerciseIndex, setIndex);
  }

  // ---- finish / summary ----------------------------------------------------

  int _untickedCount(ActiveWorkout workout) => workout.exercises.fold<int>(
      0,
      (int total, ActiveWorkoutExercise exercise) =>
          total +
          exercise.sets.where((ActiveWorkoutSet s) => !s.ticked).length);

  /// `{completed}/{total} exercises · {ticked}/{total} sets` under the day
  /// heading (#159): warm-ups excluded from both counts, an exercise done
  /// only when all its working sets are ticked — all of it derived by
  /// [workoutProgressOf], so the line and the bottom bar (#160) can never
  /// disagree.
  String _progressLine(ActiveWorkout workout) {
    final ({
      int exercisesCompleted,
      int exercisesTotal,
      int setsTicked,
      int setsTotal
    }) progress = workoutProgressOf(workout);
    return '${progress.exercisesCompleted}/${progress.exercisesTotal} '
        'exercises · ${progress.setsTicked}/${progress.setsTotal} sets';
  }

  /// Finish opens the workout summary (#124): the unticked-sets sheet first,
  /// then the summary — celebration, stats, performed date, readiness, notes —
  /// with nothing saved until the player taps Save workout there.
  ///
  /// The records and the stats are computed once, here, on the device: they
  /// are this workout's snapshot and are never recomputed after a sync.
  Future<void> _finish() async {
    final ActiveWorkout? workout = _workout;
    if (workout == null || _blockReason != null) {
      return;
    }
    final bool anyWorking = workout.exercises.any(
        (ActiveWorkoutExercise exercise) => exercise.sets
            .any((ActiveWorkoutSet s) => s.ticked && s.countsAsWorkingSet));
    if (!anyWorking) {
      setState(() => _error = _kFinishBlockedError);
      return;
    }
    final int unticked = _untickedCount(workout);
    if (unticked > 0) {
      final bool proceed = await _confirmUnticked(unticked);
      if (!proceed || !mounted) {
        return;
      }
    }
    final ActiveWorkout? finished = _workout;
    if (finished == null || !mounted) {
      return;
    }
    setState(() {
      _summary = WorkoutSummary.of(finished, now: ref.read(clockProvider)());
      _summaryStep = true;
      _error = null;
      _recordFocus = null;
      _focus = null;
    });
    // Published for the top bar: Workout time holds this snapshot's duration
    // while the summary is open, so it never ticks beside the frozen stat
    // (#159).
    ref.read(loggerSummaryProvider.notifier).state = _summary;
    // The summary replaces the workout: the lock-screen notification and the
    // end alarm come off until Back returns to a still-running rest (#125).
    unawaited(_controller.suspendRestAlerts());
  }

  /// "N sets aren't ticked · Discard unticked sets and finish / Keep logging"
  /// (#108 resolution). Only ticked sets are ever logged.
  Future<bool> _confirmUnticked(int unticked) async {
    final bool? choice = await showModalBottomSheet<bool>(
      context: context,
      builder: (BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(
                unticked == 1
                    ? "1 set isn't ticked"
                    : "$unticked sets aren't ticked",
                style: MayosTypography.sectionHeading,
              ),
              const SizedBox(height: MayosSpacing.xs),
              const Text('Only ticked sets are saved to the workout.'),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: 'Discard unticked sets and finish',
                onPressed: () => Navigator.of(context).pop(true),
              ),
              const SizedBox(height: MayosSpacing.sm),
              MayosButton(
                label: 'Keep logging',
                variant: MayosButtonVariant.secondary,
                onPressed: () => Navigator.of(context).pop(false),
              ),
            ],
          ),
        ),
      ),
    );
    return choice == true;
  }

  Future<void> _pickDate() async {
    // The device has no IANA timezone database, so "today" is computed from
    // the device's own wall clock — the same clock [_timezone] names.
    final PerformedDateWindow window = performedDateWindow();
    final DateTime initial = window.clamp(_performedDate);
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: window.first,
      lastDate: window.last,
    );
    if (picked != null && mounted) {
      setState(() => _performedDate = picked);
    }
  }

  Future<void> _save() async {
    final ActiveWorkout? workout = _workout;
    final String? timezone = _timezone;
    if (workout == null || timezone == null || _blockReason != null) {
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final DraftSyncService sync = ref.read(draftSyncServiceProvider);
      final WorkoutDraft? draft = workout.buildWorkoutDraft(
        timezone: timezone,
        clientSessionId: sync.newClientSessionId(),
        now: DateTime.now(),
        performedDate: formatPerformedDate(_performedDate),
        readiness: _readiness,
        notes: _notes.text.trim(),
      );
      if (draft == null) {
        setState(() {
          _error = 'No cached program version is available offline. Connect '
              'once to refresh your program before logging this workout.';
        });
        return;
      }
      await sync.saveDraft(draft);
      // Saving ends the Active workout (CONTEXT.md): the draft now owns it.
      // The controller waits for every pending store write before deleting, so
      // a late write can never resurrect it (#123 item 5).
      await _controller.discard(
          accountId: workout.accountId, workoutId: workout.id);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Workout saved to your drafts.')),
      );
      context.go(workoutsPath);
    } on Object catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => _error = _saveFailureMessage(error));
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  /// How a failed save is reported: the service's own message when it has one,
  /// otherwise a line that promises the workout is still on screen (#123
  /// item 6).
  static String _saveFailureMessage(Object error) => error is ApiException
      ? error.message
      : 'The workout could not be saved. Nothing was lost — try again.';

  Future<void> _addUnplanned() async {
    final ExerciseCatalogEntry? entry = await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => const _UnplannedExerciseDialog(),
    );
    if (entry == null) {
      return;
    }
    await _controller.addUnplannedExercise(
      exerciseId: entry.id,
      exerciseName: entry.name,
      imagePath: entry.imagePath,
    );
  }

  /// Back from the summary returns to the Active workout (#124). The snapshot
  /// is dropped, so a later Finish computes a fresh one from the rows. A rest
  /// that kept counting gets its notification and alarm back (#125).
  void _backFromSummary() {
    setState(() {
      _summaryStep = false;
      _summary = null;
      _error = null;
    });
    // Back to the logger: the top bar's Workout time runs live again (#159).
    ref.read(loggerSummaryProvider.notifier).state = null;
    unawaited(_controller.restoreRestAlerts());
  }

  // ---- build --------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (!ref.watch(offlineWorkoutDraftsEnabledProvider)) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(MayosSpacing.xl),
          child: Text(
            'Offline workout logging is available in the Android app.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    final ActiveWorkoutState active =
        ref.watch(activeWorkoutControllerProvider);
    if (_loading || !active.ready) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Text(_loadError!, textAlign: TextAlign.center),
        ),
      );
    }
    final ActiveWorkout? workout = active.workout;
    if (workout == null) {
      // The workout was just cleared by Save; the route moves away next frame.
      return const Center(child: CircularProgressIndicator());
    }
    _syncRestTicker(workout);
    final bool keypadVisible = _validFocus(workout) && _focus != null;
    return PopScope(
      canPop: !_summaryStep,
      onPopInvokedWithResult: (bool didPop, Object? result) {
        if (!didPop && _summaryStep && mounted) {
          _backFromSummary();
        }
      },
      child: Column(
        children: <Widget>[
          Expanded(
            child: _summaryStep
                ? SafeArea(
                    // The frame no longer insets the logger's body; the bar
                    // and the keypad take the inset inside their own surface,
                    // and the summary — which shows neither — takes it too.
                    top: false,
                    child: _buildSummary(),
                  )
                : _buildActive(workout),
          ),
          if (!_summaryStep) ...<Widget>[
            // Messages sit above the bottom bar, never scrolled away at the
            // end of the list: that is where the player acts on them (#160).
            ..._activeMessages(),
            // The keypad replaces the bottom bar outright while an edit is
            // open, so the screen has exactly one bottom bar at a time and
            // the keypad never covers it (#160).
            if (keypadVisible)
              _buildKeypad(workout, _focus!)
            else
              _buildBottomBar(workout),
          ],
        ],
      ),
    );
  }

  /// The active workout's message lines — a blocking reason, an error, or a
  /// note — as the slot between the list and the bottom bar renders them.
  ///
  /// The slot is capped at a third of the screen and scrolls inside that cap,
  /// so a long line at a large text scale can never push the bar (or the
  /// keypad) off the bottom of the screen (#160/#45).
  List<Widget> _activeMessages() {
    final List<Widget> lines = <Widget>[];
    if (_blockReason != null) {
      lines.add(_MessageLine(_blockReason!));
    }
    if (_error != null) {
      lines.add(_MessageLine(_error!));
    }
    if (_notice != null) {
      lines.add(_MessageLine(_notice!, danger: false));
    }
    if (lines.isEmpty) {
      return const <Widget>[];
    }
    return <Widget>[
      ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height *
              _kMessageSlotMaxHeightFraction,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.only(
            left: MayosSpacing.lg,
            right: MayosSpacing.lg,
            top: MayosSpacing.xs,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: lines,
          ),
        ),
      ),
    ];
  }

  /// The persistent bottom workout bar (#160): `{ticked}/{total} sets`, a
  /// progress bar and Finish — all from the same pure counts as the header's
  /// progress line — plus #125's rest controls while a rest runs. It lives in
  /// the column below the list, so the list is sized to the space it leaves
  /// and the last card scrolls clear; the keypad takes its place instead
  /// while a cell is being edited.
  Widget _buildBottomBar(ActiveWorkout workout) {
    final ({
      int exercisesCompleted,
      int exercisesTotal,
      int setsTicked,
      int setsTotal
    }) progress = workoutProgressOf(workout);
    final ActiveRestTimer? rest = workout.rest;
    return LoggerBottomBar(
      key: const ValueKey<String>('logger.bottomBar'),
      setsTicked: progress.setsTicked,
      setsTotal: progress.setsTotal,
      // The one place the fill is worked out, beside the counts above it.
      progressValue: workoutSetsFractionOf(workout),
      onFinish: _blockReason != null ? null : _finish,
      restControls: rest == null ? null : _buildRestControls(rest),
    );
  }

  /// #125's rest controls for the bar: −15 / m:ss / +15 / Skip. The row
  /// carries its own quarter-second ticker and reads the wall clock itself,
  /// so a running rest never repaints the screen; no new timer state and no
  /// "+30s" (#125 unchanged, absorbed by the bottom bar in #160).
  Widget _buildRestControls(ActiveRestTimer rest) {
    return RestTimerControls(
      rest: rest,
      onMinus: () =>
          unawaited(_controller.adjustRest(const Duration(seconds: -15))),
      onPlus: () =>
          unawaited(_controller.adjustRest(const Duration(seconds: 15))),
      onSkip: () => unawaited(_controller.skipRest()),
    );
  }

  bool _validFocus(ActiveWorkout workout) {
    final LoggerCellFocus? focus = _focus;
    if (focus == null) {
      return false;
    }
    return focus.exerciseIndex >= 0 &&
        focus.exerciseIndex < workout.exercises.length &&
        focus.setIndex >= 0 &&
        focus.setIndex < workout.exercises[focus.exerciseIndex].sets.length;
  }

  Widget _buildKeypad(ActiveWorkout workout, LoggerCellFocus focus) {
    final ActiveWorkoutSet set =
        workout.exercises[focus.exerciseIndex].sets[focus.setIndex];
    return LoggerKeypad(
      exerciseName: workout.exercises[focus.exerciseIndex].exerciseName,
      setNumber: focus.setIndex + 1,
      field: focus.field,
      initialText: _initialText(workout, focus),
      selectedRir: set.rir,
      onText: _onKeypadText,
      onRir: _onKeypadRir,
      onNext: _onKeypadNext,
      onHide: _onKeypadHide,
    );
  }

  Widget _buildActive(ActiveWorkout workout) {
    final MayosThemeExtension c = MayosTheme.of(context);
    // Derived, never stored: the first unticked working set in workout
    // order, warm-ups skipped, moving across exercises (#158).
    final ({int exerciseIndex, int setIndex})? current = currentSetOf(workout);
    // The bar below is a sibling of this list rather than an overlay, and
    // the page padding keeps 32dp under the last card — so the end of the
    // workout scrolls fully clear of the bar (#160).
    return SingleChildScrollView(
      key: const ValueKey<String>('logger.list'),
      padding: MayosSpacing.screen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            workout.dayName,
            style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          // The progress line (#159): the same pure counts the bottom bar
          // will show (#160), under the screen's one serif heading.
          Text(
            _progressLine(workout),
            key: const ValueKey<String>('logger.progress'),
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          if (_fromCache) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            const _OfflineLoggerNotice(),
          ],
          const SizedBox(height: MayosSpacing.md),
          for (int i = 0; i < workout.exercises.length; i++)
            // A replaced planned exercise (#162) keeps its place in the
            // workout for the draft but is never a card: it has no rows and
            // is nothing left to do.
            if (!workout.exercises[i].replaced)
              _buildExerciseCard(workout, i, current),
          // Add exercise stays the list's last action; Finish lives in the
          // fixed bottom bar (#160), so it never needs scrolling to.
          MayosButton(
            key: const ValueKey<String>('logger.addExercise'),
            label: 'Add exercise',
            icon: Icons.add,
            variant: MayosButtonVariant.secondary,
            onPressed: _addUnplanned,
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
      ),
    );
  }

  /// One exercise, one compact card (#158): the card and its rows are pure
  /// presentation — this method only assembles what they show, including the
  /// Current set's highlight and the records the rows carry.
  Widget _buildExerciseCard(ActiveWorkout workout, int exerciseIndex,
      ({int exerciseIndex, int setIndex})? current) {
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    // A replacement is undone rather than removed: taking it out brings the
    // hidden planned exercise back (#162).
    final bool isReplacement = isReplacementExerciseAt(workout, exerciseIndex);
    // One computation per exercise per build: the calculator is pure over the
    // persisted rows and the frozen baseline, so the badges are what the
    // Active workout holds — restart included (#124).
    final Map<String, SetRecordBadges> badges = _recordBadges(exerciseIndex);
    return ExerciseLoggingCard(
      exercise: exercise,
      unplanned: exercise.unplanned,
      restSeconds: _controller.restLengthFor(exerciseIndex),
      // The card's ⋮ menu and its entries (#162), keyed the way the rows are,
      // so a test opens exactly what a player opens.
      menuKey: ValueKey<String>('logger.cardMenu.$exerciseIndex'),
      replaceKey: ValueKey<String>('logger.cardMenu.$exerciseIndex.replace'),
      restKey: ValueKey<String>('logger.cardMenu.$exerciseIndex.rest'),
      removeKey: ValueKey<String>('logger.cardMenu.$exerciseIndex.remove'),
      undoReplaceKey:
          ValueKey<String>('logger.cardMenu.$exerciseIndex.undo'),
      // The frozen baseline's last session, in logged order; empty hides the
      // "Last:" line entirely (#158).
      lastSession: workout.baselines[exercise.exerciseId]?.lastSession.sets ??
          const <BaselineSet>[],
      rows: <Widget>[
        for (int setIndex = 0; setIndex < exercise.sets.length; setIndex++)
          _buildSetRow(
            workout,
            exerciseIndex,
            setIndex,
            badges,
            isCurrent: current != null &&
                current.exerciseIndex == exerciseIndex &&
                current.setIndex == setIndex,
          ),
      ],
      addSetKey: ValueKey<String>('logger.addSet.$exerciseIndex'),
      onPickRest: () => unawaited(_pickRest(exerciseIndex)),
      onAddSet: () => _controller.addSet(exerciseIndex),
      // Replace is for every player whatever the Program authority (#162);
      // a replacement is undone, any other unplanned exercise is removed.
      onReplace: () => unawaited(_onReplaceExercise(exerciseIndex)),
      onRemove: exercise.unplanned && !isReplacement
          ? () => unawaited(_onRemoveExercise(exerciseIndex))
          : null,
      onUndoReplace: isReplacement
          ? () => unawaited(_onUndoReplace(exerciseIndex))
          : null,
    );
  }

  /// **Replace exercise** (#162, #157 Q15–Q17): confirm first when the
  /// exercise holds ticked sets, then open the catalog search Add exercise
  /// uses — opening with this exercise's target muscle listed, and never
  /// offering an exercise already in this workout — and hand the pick to the
  /// controller. This changes the workout only; the program is never touched.
  Future<void> _onReplaceExercise(int exerciseIndex) async {
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= workout.exercises.length) {
      return;
    }
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final int ticked =
        exercise.sets.where((ActiveWorkoutSet set) => set.ticked).length;
    if (ticked > 0 && !await _confirmReplace(ticked)) {
      return;
    }
    if (!mounted) {
      return;
    }
    final String? muscle = await _targetMuscleOf(exercise.exerciseId);
    if (!mounted) {
      return;
    }
    final Set<String> inWorkout = <String>{
      for (final ActiveWorkoutExercise e in _workout?.exercises ?? <ActiveWorkoutExercise>[])
        e.exerciseId,
    };
    final ExerciseCatalogEntry? entry = await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => _UnplannedExerciseDialog(
        title: 'Replace exercise',
        targetMuscle: muscle,
        excludeExerciseIds: inWorkout,
      ),
    );
    if (entry == null || !mounted) {
      return;
    }
    final ActiveWorkout? latest = _workout;
    if (latest == null || exerciseIndex >= latest.exercises.length) {
      return;
    }
    // The planned card keeps its slot (marked and hidden) while the
    // replacement is inserted after it, so a keypad focus on a later card
    // moves with that card; an unplanned exercise is swapped in place (#162).
    final int delta = latest.exercises[exerciseIndex].unplanned ? 0 : 1;
    setState(() => _reindexFocus(exerciseIndex, delta: delta));
    await _controller.replaceExercise(
      exerciseIndex: exerciseIndex,
      exerciseId: entry.id,
      exerciseName: entry.name,
      imagePath: entry.imagePath,
    );
  }

  /// "Replace and discard N logged sets?" (#162): the confirmation that comes
  /// before a replace can touch rows the player has already ticked. Resolves
  /// true only for Replace; "Keep logging" and any dismissal change nothing.
  Future<bool> _confirmReplace(int ticked) async {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool? replace = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(ticked == 1
            ? 'Replace and discard 1 logged set?'
            : 'Replace and discard $ticked logged sets?'),
        content: Text(
          "The sets you've logged on this exercise will be cleared.",
          style: MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
        ),
        actions: <Widget>[
          MayosButton(
            label: 'Keep logging',
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: 'Replace',
            destructive: true,
            expand: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
        ],
      ),
    );
    return replace ?? false;
  }

  /// The exercise's target muscle, read from the catalog detail the app
  /// already has a call for (`GET /workouts/exercises/{id}`): its first
  /// primary muscle is the catalog's `target_muscle`, the same column the
  /// search rows carry, so the two compare exactly. Null — unknown id,
  /// offline, a catalog row with no muscle — just opens the search
  /// unfiltered, so the lookup can never block a replace.
  Future<String?> _targetMuscleOf(String exerciseId) async {
    try {
      final ExerciseCatalogDetail detail = await ref
          .read(apiClientProvider)
          .exerciseCatalogDetail(exerciseId)
          .timeout(const Duration(seconds: 3));
      return detail.primaryMuscles.isNotEmpty
          ? detail.primaryMuscles.first
          : null;
    } on Object {
      return null;
    }
  }

  /// The card menu's **Remove exercise** (#162): takes a plain unplanned
  /// exercise out, confirming first when it holds logged sets. The controller
  /// still refuses anything but an unplanned exercise.
  Future<void> _onRemoveExercise(int exerciseIndex) async {
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= workout.exercises.length) {
      return;
    }
    final int ticked = workout.exercises[exerciseIndex]
        .sets
        .where((ActiveWorkoutSet set) => set.ticked)
        .length;
    if (ticked > 0 && !await _confirmDiscardSets(ticked, confirm: 'Remove')) {
      return;
    }
    if (!mounted) {
      return;
    }
    setState(() => _reindexFocus(exerciseIndex, delta: -1));
    await _controller.removeExercise(exerciseIndex);
  }

  /// The card menu's **Undo replace** (#162): takes the replacement out and
  /// brings its planned exercise back as an ordinary card, confirming first
  /// when the replacement holds logged sets.
  Future<void> _onUndoReplace(int exerciseIndex) async {
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= workout.exercises.length) {
      return;
    }
    final int ticked = workout.exercises[exerciseIndex]
        .sets
        .where((ActiveWorkoutSet set) => set.ticked)
        .length;
    if (ticked > 0 &&
        !await _confirmDiscardSets(ticked, confirm: 'Undo replace')) {
      return;
    }
    if (!mounted) {
      return;
    }
    setState(() => _reindexFocus(exerciseIndex, delta: -1));
    await _controller.undoReplace(exerciseIndex);
  }

  /// "Remove and discard N logged sets?" (#162): the confirmation both Remove
  /// exercise and Undo replace raise over an exercise that holds ticked sets.
  /// Nothing is discarded unless [confirm] is tapped; "Keep logging" and any
  /// dismissal change nothing.
  Future<bool> _confirmDiscardSets(int ticked, {required String confirm}) async {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool? discard = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(ticked == 1
            ? 'Remove and discard 1 logged set?'
            : 'Remove and discard $ticked logged sets?'),
        content: Text(
          "The sets you've logged on this exercise will be discarded.",
          style: MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
        ),
        actions: <Widget>[
          MayosButton(
            label: 'Keep logging',
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: confirm,
            destructive: true,
            expand: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
        ],
      ),
    );
    return discard ?? false;
  }

  /// Keeps the keypad's focus on the same exercise across an edit to the
  /// exercise list (#162): a focus on the edited card is dropped (its rows
  /// changed), and a focus on a card after it moves with that card — [delta]
  /// is +1 when the edit inserts an exercise after the edited index, -1 when
  /// it removes one, and 0 when the exercise is swapped in place.
  void _reindexFocus(int editedIndex, {required int delta}) {
    final LoggerCellFocus? focus = _focus;
    if (focus != null) {
      if (focus.exerciseIndex == editedIndex) {
        _focus = null;
      } else if (focus.exerciseIndex > editedIndex && delta != 0) {
        _focus = LoggerCellFocus(
            focus.exerciseIndex + delta, focus.setIndex, focus.field);
      }
    }
    final ({
      int exerciseIndex,
      String setId,
      Set<PrRecordKind> before
    })? recordFocus = _recordFocus;
    if (recordFocus != null) {
      if (recordFocus.exerciseIndex == editedIndex) {
        _recordFocus = null;
      } else if (recordFocus.exerciseIndex > editedIndex && delta != 0) {
        _recordFocus = (
          exerciseIndex: recordFocus.exerciseIndex + delta,
          setId: recordFocus.setId,
          before: recordFocus.before,
        );
      }
    }
  }

  /// One row, assembled here so the screen keeps every decision it makes:
  /// which previous set it hints from, whether the derived Current set lands
  /// on it, what the keypad's focus is, and which records it holds (#158).
  Widget _buildSetRow(ActiveWorkout workout, int exerciseIndex, int setIndex,
      Map<String, SetRecordBadges> badges,
      {required bool isCurrent}) {
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    return SetLoggingRow(
      exerciseIndex: exerciseIndex,
      setIndex: setIndex,
      set: set,
      previous: previousSetFor(exercise, setIndex, workout.baselines),
      prescriptionHint: exercise.prescriptionHint,
      badges: badges[set.id] ?? const SetRecordBadges(),
      focus: _focus,
      isCurrent: isCurrent,
      onSelectCell: (LoggerField field) => setState(() =>
          _changeFocus(LoggerCellFocus(exerciseIndex, setIndex, field))),
      onToggleWarmup: () => unawaited(_updateWithRecordHaptic(
        exerciseIndex,
        setIndex,
        () => _controller.toggleWarmup(exerciseIndex, setIndex),
      )),
      onToggleTick: () => _toggleTick(exerciseIndex, setIndex),
      // A row is swiped away only when the exercise keeps at least one row,
      // exactly as before (#123 item 3).
      onDismissed: exercise.sets.length > 1
          ? () => _removeSet(exerciseIndex, setIndex)
          : null,
    );
  }

  /// The workout summary (#124), which replaces the plain save step: the
  /// celebration and the stats of the snapshot computed at Finish, then the
  /// performed date, readiness, notes and Save workout — the save step's own
  /// behaviour, unchanged. Back returns to the Active workout.
  ///
  /// The snapshot is `_summary`, taken by [_finish]: there is no fallback
  /// computation here, because a summary must never be derived from rows
  /// that changed after Finish (#124).
  Widget _buildSummary() {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutSummary summary = _summary!;
    final String date = formatPerformedDate(_performedDate);
    return SingleChildScrollView(
      padding: MayosSpacing.screen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              IconButton(
                key: const ValueKey<String>('logger.save.back'),
                tooltip: 'Back to workout',
                onPressed: _backFromSummary,
                icon: const Icon(Icons.arrow_back),
              ),
              Text(
                'Workout summary',
                style: MayosTypography.sectionHeading
                    .copyWith(color: c.textPrimary),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.sm),
          if (summary.records.isNotEmpty) ...<Widget>[
            _buildCelebration(summary.records),
            const SizedBox(height: MayosSpacing.md),
          ],
          _buildStats(summary),
          const SizedBox(height: MayosSpacing.lg),
          MayosCard(
            padding: EdgeInsets.zero,
            child: MayosSettingsTile(
              icon: Icons.event_outlined,
              title: 'Performed date',
              subtitle: date,
              trailing: Icon(Icons.edit_outlined, size: 20, color: c.textMuted),
              onTap: _pickDate,
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          MayosSectionHeader(title: 'Readiness: $_readiness/5'),
          Slider(
            value: _readiness.toDouble(),
            min: 1,
            max: 5,
            divisions: 4,
            label: '$_readiness',
            onChanged: (double value) =>
                setState(() => _readiness = value.round()),
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosTextField(
            controller: _notes,
            maxLines: 3,
            label: 'Notes (pumps, joint aches, fatigue)',
          ),
          if (_blockReason != null) _MessageLine(_blockReason!),
          if (_error != null) _MessageLine(_error!),
          if (_notice != null) _MessageLine(_notice!, danger: false),
          const SizedBox(height: MayosSpacing.lg),
          MayosButton(
            key: const ValueKey<String>('logger.save'),
            label: 'Save workout',
            icon: Icons.check,
            loading: _saving,
            onPressed: _saving || _blockReason != null ? null : _save,
          ),
        ],
      ),
    );
  }

  /// The celebration at the top of the summary: one line per current record
  /// (`Bench Press · PR e1RM 112.5 kg`), omitted when the workout earned none
  /// (#124).
  Widget _buildCelebration(List<WorkoutRecord> records) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            'Personal records',
            style: MayosTypography.exerciseTitle.copyWith(color: c.accent),
          ),
          const SizedBox(height: MayosSpacing.xs),
          for (final WorkoutRecord record in records)
            Padding(
              padding: const EdgeInsets.only(bottom: MayosSpacing.xxs),
              child: Text(
                record.line,
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textPrimary),
              ),
            ),
        ],
      ),
    );
  }

  /// The four stats the summary shows: exercises done, ticked working sets,
  /// total volume over those sets (#124) and the workout's total duration
  /// (#159). Two rows of two, so a duration like `1:05:09` still fits the
  /// 360dp minimum without shrinking the figures.
  Widget _buildStats(WorkoutSummary summary) {
    final WorkoutSummaryStats stats = summary.stats;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: MayosStat(
                value: '${stats.exercisesDone}',
                label: 'Exercises done',
              ),
            ),
            Expanded(
              child: MayosStat(
                value: '${stats.workingSets}',
                label: 'Ticked working sets',
              ),
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.md),
        Row(
          children: <Widget>[
            Expanded(
              child: MayosStat(
                value: stats.volumeLabel,
                label: 'Total volume',
                unit: 'kg',
              ),
            ),
            Expanded(
              child: MayosStat(
                key: const ValueKey<String>('logger.summary.duration'),
                value: formatWorkoutTime(summary.duration),
                label: 'Duration',
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// The one message line the logger shows under the list or the workout
/// summary: blocking reasons and errors in the danger colour, notes neutral
/// (#123 item 12).
class _MessageLine extends StatelessWidget {
  const _MessageLine(this.text, {this.danger = true});

  final String text;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.sm),
      child: Text(
        text,
        style: MayosTypography.bodySecondary
            .copyWith(color: danger ? c.danger : c.textSecondary),
      ),
    );
  }
}

/// The offline banner for the logger, matching the Program tab's treatment.
class _OfflineLoggerNotice extends StatelessWidget {
  const _OfflineLoggerNotice();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.sm),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.cloud_off, size: 18, color: c.textSecondary),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              'Offline: showing your cached program.',
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
          ),
        ],
      ),
    );
  }
}

/// Searches the real catalog so an exercise picked here carries an id the
/// service can validate, rather than an invented one that would be refused on
/// sync (ADR 020/033). It is both the **Add exercise** dialog and the search
/// **Replace exercise** opens (#162), which passes [targetMuscle].
///
/// The service's search matches names only — `GET /workouts/exercises` has no
/// muscle parameter — so the pre-filter is applied here: while the chip is on,
/// only rows whose `target_muscle` equals [targetMuscle] are offered, and
/// clearing the chip (or any query the player types) searches the whole
/// catalog again.
class _UnplannedExerciseDialog extends ConsumerStatefulWidget {
  const _UnplannedExerciseDialog({
    this.title = 'Add unplanned exercise',
    this.targetMuscle,
    this.excludeExerciseIds = const <String>{},
  });

  /// The dialog's heading: "Add unplanned exercise", or "Replace exercise".
  final String title;

  /// The planned exercise's target muscle (#162): when present the search
  /// opens listing that muscle's exercises (server-side `target_muscle`),
  /// with a pill that turns the pre-filter off to search by name.
  final String? targetMuscle;

  /// Exercise ids already in this workout (#162): the Replace search never
  /// offers them, planned or unplanned. Empty for Add exercise, which keeps
  /// offering the whole catalog.
  final Set<String> excludeExerciseIds;

  @override
  ConsumerState<_UnplannedExerciseDialog> createState() =>
      _UnplannedExerciseDialogState();
}

class _UnplannedExerciseDialogState
    extends ConsumerState<_UnplannedExerciseDialog> {
  final TextEditingController _query = TextEditingController();

  bool _searching = false;
  String? _error;
  List<ExerciseCatalogEntry> _results = const <ExerciseCatalogEntry>[];

  /// Whether [widget.targetMuscle] narrows the results right now (#162).
  bool _muscleFilter = false;

  @override
  void initState() {
    super.initState();
    // Replace opens pre-listed with the target muscle; Add exercise never
    // filters and so never searches until the player asks.
    _muscleFilter = widget.targetMuscle != null;
    if (_muscleFilter) {
      // The first listing runs before the player types anything (#162);
      // a microtask keeps setState out of initState.
      Future<void>.microtask(() {
        if (mounted) {
          unawaited(_search());
        }
      });
    }
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  /// The muscle the query is narrowed by right now, or null while the pill
  /// is off — the one place the two search modes are decided (#162).
  String? get _activeMuscle => _muscleFilter ? widget.targetMuscle : null;

  Future<void> _search() async {
    final String query = _query.text.trim();
    final String? muscle = _activeMuscle;
    if (query.isEmpty && muscle == null) {
      setState(() => _error = 'Type an exercise name to search.');
      return;
    }
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      // With a muscle set the server lists or narrows by `target_muscle`, so
      // the Replace dialog can show that muscle before any typing (#162);
      // Add exercise passes nothing and searches by name exactly as before.
      final List<ExerciseCatalogEntry> results = await ref
          .read(apiClientProvider)
          .searchExercises(query, targetMuscle: muscle);
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = results;
        _error = results.isEmpty
            ? (muscle == null
                ? 'No matching exercise found.'
                : 'No $muscle exercise matched.')
            : null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = const <ExerciseCatalogEntry>[];
        _error = error.message;
      });
    }
  }

  /// What the player is offered: the search's rows minus every exercise
  /// already in this workout (#162). The muscle itself is the server's job —
  /// `GET /workouts/exercises?target_muscle=` — so this list is whatever that
  /// query returned, minus the workout's own exercises.
  List<ExerciseCatalogEntry> get _visible => _results
      .where((ExerciseCatalogEntry entry) =>
          !widget.excludeExerciseIds.contains(entry.id))
      .toList(growable: false);

  /// The pill (#162): on, the server lists the target muscle (no name needed);
  /// off, the search goes back to the whole catalog by name — which needs a
  /// query, so an empty one says exactly that instead of showing muscle rows.
  void _toggleMuscleFilter() {
    setState(() {
      _muscleFilter = !_muscleFilter;
      if (!_muscleFilter && _query.text.trim().isEmpty) {
        _results = const <ExerciseCatalogEntry>[];
        _error = 'Type an exercise name to search.';
      }
    });
    // Re-list the muscle when it turns on; re-search by name when it turns
    // off and there is a query to search with.
    if (!_muscleFilter && _query.text.trim().isEmpty) {
      return;
    }
    unawaited(_search());
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ExerciseCatalogEntry> visible = _visible;
    final bool filteredOut = _results.isNotEmpty && visible.isEmpty;
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: kLoggerDialogWidth,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosTextField(
              controller: _query,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              label: 'Search the exercise catalog',
            ),
            if (widget.targetMuscle != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.xs),
                child: _MuscleFilterChip(
                  muscle: widget.targetMuscle!,
                  active: _muscleFilter,
                  onToggle: _toggleMuscleFilter,
                ),
              ),
            if (_searching)
              const Padding(
                padding: EdgeInsets.only(top: MayosSpacing.sm),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  _error!,
                  style:
                      MayosTypography.bodySecondary.copyWith(color: c.danger),
                ),
              ),
            if (filteredOut)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  'Every match is already in this workout.',
                  style: MayosTypography.bodySecondary
                      .copyWith(color: c.textSecondary),
                ),
              ),
            if (visible.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: <Widget>[
                    for (final ExerciseCatalogEntry entry in visible)
                      MayosSettingsTile(
                        icon: Icons.fitness_center,
                        title: entry.name,
                        onTap: () => Navigator.of(context).pop(entry),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
      actions: <Widget>[
        MayosButton(
          label: 'Cancel',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          label: 'Search',
          expand: false,
          loading: _searching,
          onPressed: _searching ? null : _search,
        ),
      ],
    );
  }
}

/// The Replace search's pre-filter (#162): a full-height pill naming the
/// target muscle. On, the dialog lists that muscle straight from
/// `GET /workouts/exercises?target_muscle=`; the ✕ (or a tap) turns it off so
/// the same dialog searches the whole catalog by name.
class _MuscleFilterChip extends StatelessWidget {
  const _MuscleFilterChip({
    required this.muscle,
    required this.active,
    required this.onToggle,
  });

  final String muscle;
  final bool active;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return SizedBox(
      height: kMayosMinTapTarget,
      child: Align(
        alignment: Alignment.centerLeft,
        child: InkWell(
          key: const ValueKey<String>('logger.search.muscleFilter'),
          borderRadius: MayosRadii.pillRadius,
          onTap: onToggle,
          child: Container(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
            decoration: BoxDecoration(
              color: active ? c.accentSubtle : c.surfaceSunken,
              borderRadius: MayosRadii.pillRadius,
              border: Border.all(color: active ? c.accent : c.border),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  'Muscle: $muscle',
                  style: MayosTypography.caption.copyWith(
                      color: active ? c.accent : c.textSecondary),
                ),
                if (active) ...<Widget>[
                  const SizedBox(width: MayosSpacing.xs),
                  Icon(
                    Icons.close,
                    size: MayosIconSizes.small,
                    color: c.textMuted,
                    semanticLabel: 'Clear the muscle filter',
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
