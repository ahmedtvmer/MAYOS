import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../../core/active_workout.dart';
import '../../../core/effort.dart';
import '../../../core/api_client.dart';
import '../../../core/baselines.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_settings_tile.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'active_workout_controller.dart';
import 'draft_sync_service.dart';
import 'logger_keypad.dart';

/// The frozen previous working set matched set by set: set N of the table is
/// the Nth working set of the baseline's `last_session` (#107/#123), for
/// planned and unplanned exercises alike.
///
/// N counts only non-warm-up rows, because `last_session` carries working sets
/// only — so a warm-up row has no previous set, shows `—`, and is never
/// auto-filled from one (#123 item 1). Null when there is no previous set.
BaselineSet? previousSetFor(
  ActiveWorkoutExercise exercise,
  int setIndex,
  Map<String, BaselineExercise> baselines,
) {
  if (setIndex < 0 || setIndex >= exercise.sets.length) {
    return null;
  }
  if (exercise.sets[setIndex].isWarmup) {
    return null;
  }
  int workingNumber = 0;
  for (int i = 0; i <= setIndex; i++) {
    if (!exercise.sets[i].isWarmup) {
      workingNumber += 1;
    }
  }
  final List<BaselineSet> last =
      baselines[exercise.exerciseId]?.lastSession.sets ?? const <BaselineSet>[];
  if (workingNumber - 1 >= last.length) {
    return null;
  }
  return last[workingNumber - 1];
}

/// `100 × 5 @1`, or `—` when there is no previous set. An unrated previous
/// set drops the `@` part (`100 × 5`).
String previousLabel(BaselineSet? set) {
  if (set == null) {
    return '—';
  }
  final String effort = set.rir == null ? '' : ' @${formatRir(set.rir!)}';
  return '${formatCellWeight(set.weightKg)} × ${set.reps}$effort';
}

/// `100`, `92.5`, `33.33` — the cell/previous weight format.
String formatCellWeight(double weight) =>
    weight == weight.roundToDouble() ? weight.round().toString() : '$weight';

/// The one mapping from a field to what its cell shows (#123 item 12): the
/// typed [value] when there is one, else the faded [hint].
///
/// The hint is the previous set first (#107/#123 item 1), falling back to the
/// prescription target — projected weight, target reps, target RIR — when
/// there is no previous value to take (#108: prescription `last_perf` stays
/// for the progression projection alone, so it never appears here).
({String? value, String? hint}) cellTexts({
  required ActiveWorkoutSet set,
  required BaselineSet? previous,
  required PrescriptionHint? prescriptionHint,
  required LoggerField field,
}) {
  String? fromPrevious;
  String? fromPrescription;
  switch (field) {
    case LoggerField.kg:
      fromPrevious =
          previous == null ? null : formatCellWeight(previous.weightKg);
      final double? projected = prescriptionHint?.weightKg;
      fromPrescription = projected == null || projected <= 0
          ? null
          : formatCellWeight(projected);
      return (
        value: set.weightKg > 0 ? formatCellWeight(set.weightKg) : null,
        hint: fromPrevious ?? fromPrescription,
      );
    case LoggerField.reps:
      fromPrevious = previous == null ? null : '${previous.reps}';
      final int? targetReps = prescriptionHint?.reps;
      fromPrescription =
          targetReps == null || targetReps <= 0 ? null : '$targetReps';
      return (
        value: set.reps > 0 ? '${set.reps}' : null,
        hint: fromPrevious ?? fromPrescription,
      );
    case LoggerField.rir:
      // A recorded RIR reads as itself (5 → 5+); the prescription fallback is
      // a *target*, so it reads as the equivalent minimum RIR (≥ n) (#111).
      final double? previousRir = previous?.rir;
      fromPrevious = previousRir == null ? null : formatRir(previousRir);
      final double? targetRir = prescriptionHint?.rir;
      fromPrescription = targetRir == null ? null : formatMinRir(targetRir);
      return (
        value: set.rir == null ? null : formatRir(set.rir!),
        hint: fromPrevious ?? fromPrescription,
      );
  }
}

/// The spec's tick: a 40dp square inside the row's 48dp tap area (#107).
const double kLoggerTickSize = 40;

/// The catalog dialog's content width. It is the app's narrow-phone content
/// width, kept as one named constant because the dialog measures its content
/// intrinsically and a shrink-wrapped results viewport cannot answer that
/// without a bounded width (#123 item 11).
const double kLoggerDialogWidth = 360;

/// The Hevy-style table logger (#107 Variant A), backed entirely by the
/// Active workout: one scrolling list of exercise cards with a
/// SET · PREVIOUS · KG · REPS · RIR · ✓ table, the app's own keypad, and the
/// Finish → save flow that writes a Workout draft exactly as before (#123).
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
  bool _saveStep = false;
  bool _saving = false;
  LoggerCellFocus? _focus;

  @override
  void initState() {
    super.initState();
    unawaited(_keepAwake(true));
    Future<void>.microtask(_load);
  }

  @override
  void dispose() {
    unawaited(_keepAwake(false));
    _notes.dispose();
    super.dispose();
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

  /// The save step defaults to the day the Active workout started (#123), and
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

  void _onKeypadText(String text) {
    final LoggerCellFocus? focus = _focus;
    if (focus == null) {
      return;
    }
    switch (focus.field) {
      case LoggerField.kg:
        _controller.updateCell(focus.exerciseIndex, focus.setIndex,
            weightKg: double.tryParse(text) ?? 0);
      case LoggerField.reps:
        _controller.updateCell(focus.exerciseIndex, focus.setIndex,
            reps: int.tryParse(text) ?? 0);
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
    if (rir == null) {
      _controller.updateCell(focus.exerciseIndex, focus.setIndex,
          unrated: true);
    } else {
      _controller.updateCell(focus.exerciseIndex, focus.setIndex, rir: rir);
    }
    final ActiveWorkout? workout = _workout;
    if (workout == null) {
      return;
    }
    setState(() => _focus = nextLoggerCellFocus(workout, focus));
  }

  void _onKeypadNext() {
    final ActiveWorkout? workout = _workout;
    final LoggerCellFocus? focus = _focus;
    if (workout == null || focus == null) {
      return;
    }
    setState(() => _focus = nextLoggerCellFocus(workout, focus));
  }

  void _onKeypadHide() {
    setState(() => _focus = null);
  }

  /// Ticking: empty cells take the previous value first; when a required cell
  /// (kg or reps) still has nothing, the tick opens the keypad there instead.
  Future<void> _toggleTick(int exerciseIndex, int setIndex) async {
    final ActiveWorkout? workout = _workout;
    if (workout == null) {
      return;
    }
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    if (set.ticked) {
      await _controller.setTicked(exerciseIndex, setIndex, false);
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
      setState(() {
        _focus = LoggerCellFocus(exerciseIndex, setIndex,
            weight <= 0 ? LoggerField.kg : LoggerField.reps);
      });
      return;
    }
    if (changed) {
      await _controller.updateCell(exerciseIndex, setIndex,
          weightKg: set.weightKg <= 0 ? weight : null,
          reps: set.reps <= 0 ? reps : null,
          rir: set.rir == null && rir != null ? rir : null);
    }
    await _controller.setTicked(exerciseIndex, setIndex, true);
    unawaited(HapticFeedback.selectionClick());
    if (!mounted) {
      return;
    }
    setState(() {
      if (_focus != null &&
          _focus!.exerciseIndex == exerciseIndex &&
          _focus!.setIndex == setIndex) {
        _focus = null;
      }
    });
  }

  Future<void> _removeSet(int exerciseIndex, int setIndex) async {
    setState(() => _focus = null);
    await _controller.removeSet(exerciseIndex, setIndex);
  }

  // ---- finish / save ------------------------------------------------------

  int _untickedCount(ActiveWorkout workout) => workout.exercises.fold<int>(
      0,
      (int total, ActiveWorkoutExercise exercise) =>
          total +
          exercise.sets.where((ActiveWorkoutSet s) => !s.ticked).length);

  Future<void> _finish() async {
    final ActiveWorkout? workout = _workout;
    if (workout == null || _blockReason != null) {
      return;
    }
    final bool anyWorking = workout.exercises.any(
        (ActiveWorkoutExercise exercise) => exercise.sets
            .any((ActiveWorkoutSet s) => s.ticked && s.countsAsWorkingSet));
    if (!anyWorking) {
      setState(() => _error = 'Log at least one set');
      return;
    }
    final int unticked = _untickedCount(workout);
    if (unticked > 0) {
      final bool proceed = await _confirmUnticked(unticked);
      if (!proceed || !mounted) {
        return;
      }
    }
    setState(() {
      _saveStep = true;
      _error = null;
      _focus = null;
    });
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
    );
  }

  void _backFromSave() {
    setState(() {
      _saveStep = false;
      _error = null;
    });
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
    return PopScope(
      canPop: !_saveStep,
      onPopInvokedWithResult: (bool didPop, Object? result) {
        if (!didPop && _saveStep && mounted) {
          _backFromSave();
        }
      },
      child: Column(
        children: <Widget>[
          Expanded(
            child: _saveStep ? _buildSaveStep(workout) : _buildActive(workout),
          ),
          if (_validFocus(workout) && _focus != null)
            _buildKeypad(workout, _focus!),
        ],
      ),
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
    return SingleChildScrollView(
      padding: MayosSpacing.screen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            workout.dayName,
            style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
          ),
          if (_fromCache) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            const _OfflineLoggerNotice(),
          ],
          const SizedBox(height: MayosSpacing.md),
          for (int i = 0; i < workout.exercises.length; i++)
            _buildExerciseCard(workout, i),
          MayosButton(
            key: const ValueKey<String>('logger.addExercise'),
            label: 'Add exercise',
            icon: Icons.add,
            variant: MayosButtonVariant.secondary,
            onPressed: _addUnplanned,
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            key: const ValueKey<String>('logger.finish'),
            label: 'Finish workout',
            icon: Icons.check,
            onPressed: _blockReason != null ? null : _finish,
          ),
          if (_blockReason != null) _MessageLine(_blockReason!),
          if (_error != null) _MessageLine(_error!),
          if (_notice != null) _MessageLine(_notice!, danger: false),
        ],
      ),
    );
  }

  Widget _buildExerciseCard(ActiveWorkout workout, int exerciseIndex) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: MayosCard(
        padding: const EdgeInsets.fromLTRB(MayosSpacing.md, MayosSpacing.sm,
            MayosSpacing.md, MayosSpacing.xxs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    exercise.exerciseName,
                    style:
                        MayosTypography.exerciseTitle.copyWith(color: c.accent),
                  ),
                ),
                if (exercise.unplanned) _unplannedTag(c),
              ],
            ),
            // The prescription caption, shown the way the old logger showed
            // it (#123 item 4).
            if (exercise.targetLabel != null)
              Text(
                exercise.targetLabel!,
                style: MayosTypography.caption.copyWith(color: c.textMuted),
              ),
            _tableHeader(c),
            for (int setIndex = 0; setIndex < exercise.sets.length; setIndex++)
              _buildSetRow(workout, exerciseIndex, setIndex),
            Align(
              alignment: Alignment.centerLeft,
              child: MayosButton(
                key: ValueKey<String>('logger.addSet.$exerciseIndex'),
                label: 'Add set',
                icon: Icons.add,
                variant: MayosButtonVariant.tertiary,
                expand: false,
                onPressed: () => _controller.addSet(exerciseIndex),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _unplannedTag(MayosThemeExtension c) => Container(
        padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
        decoration: BoxDecoration(
          color: c.secondarySurface,
          borderRadius: MayosRadii.pillRadius,
        ),
        child: Text('Unplanned', style: MayosTypography.caption),
      );

  static const List<int> _flex = <int>[2, 5, 3, 3, 2, 2];

  Widget _tableHeader(MayosThemeExtension c) {
    const List<String> labels = <String>[
      'SET',
      'PREVIOUS',
      'KG',
      'REPS',
      'RIR',
      '✓'
    ];
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Row(
        children: <Widget>[
          for (int i = 0; i < labels.length; i++)
            Expanded(
              flex: _flex[i],
              child: Text(labels[i],
                  textAlign: TextAlign.center,
                  style: MayosTypography.captionStrong
                      .copyWith(color: c.textMuted)),
            ),
        ],
      ),
    );
  }

  Widget _buildSetRow(ActiveWorkout workout, int exerciseIndex, int setIndex) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    final BaselineSet? prev =
        previousSetFor(exercise, setIndex, workout.baselines);
    final bool muted = set.isWarmup;

    ({String? value, String? hint}) texts(LoggerField field) => cellTexts(
          set: set,
          previous: prev,
          prescriptionHint: exercise.prescriptionHint,
          field: field,
        );

    Widget row = Container(
      margin: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: set.ticked ? c.successTint : null,
        borderRadius: MayosRadii.smallRadius,
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            flex: _flex[0],
            child: InkWell(
              key: ValueKey<String>('logger.setlabel.$exerciseIndex.$setIndex'),
              borderRadius: MayosRadii.smallRadius,
              onTap: () => _controller.toggleWarmup(exerciseIndex, setIndex),
              child: SizedBox(
                height: kMayosMinTapTarget,
                child: Center(
                  child: Text(
                    set.isWarmup ? 'W' : '${setIndex + 1}',
                    style: MayosTypography.numericSmall.copyWith(
                      color: muted ? c.textMuted : c.textPrimary,
                    ),
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            flex: _flex[1],
            child: Text(
              previousLabel(prev),
              textAlign: TextAlign.center,
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ),
          for (final LoggerField field in <LoggerField>[
            LoggerField.kg,
            LoggerField.reps,
            LoggerField.rir,
          ])
            _buildCell(
              exerciseIndex,
              setIndex,
              field,
              value: texts(field).value,
              hint: texts(field).hint,
              muted: muted,
              ticked: set.ticked,
            ),
          Expanded(
            flex: _flex[5],
            child: SizedBox(
              height: kMayosMinTapTarget,
              width: kMayosMinTapTarget,
              child: Center(
                child: InkWell(
                  key: ValueKey<String>('logger.tick.$exerciseIndex.$setIndex'),
                  borderRadius: MayosRadii.smallRadius,
                  onTap: () => _toggleTick(exerciseIndex, setIndex),
                  child: SizedBox(
                    width: kLoggerTickSize,
                    height: kLoggerTickSize,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: set.ticked ? c.success : c.surfaceSunken,
                        borderRadius: MayosRadii.smallRadius,
                      ),
                      child: Icon(
                        Icons.check,
                        size: 20,
                        color: set.ticked ? c.onSuccess : c.textMuted,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );

    if (exercise.sets.length > 1) {
      // Keyed by the row's own stable id, so removing an earlier row never
      // re-identifies the one being swiped (#123 item 3).
      row = Dismissible(
        key: ValueKey<String>(set.id),
        direction: DismissDirection.endToStart,
        onDismissed: (_) => _removeSet(exerciseIndex, setIndex),
        background: Container(
          color: c.danger,
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: MayosSpacing.md),
          child: Icon(Icons.delete, color: c.onDanger),
        ),
        child: row,
      );
    }
    return row;
  }

  Widget _buildCell(
    int exerciseIndex,
    int setIndex,
    LoggerField field, {
    required String? value,
    required String? hint,
    required bool muted,
    required bool ticked,
  }) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool focused =
        _focus == LoggerCellFocus(exerciseIndex, setIndex, field);
    // A hint (or a warm-up row) reads as disabled ink; a typed value is solid.
    final Color color = value == null || muted ? c.textDisabled : c.textPrimary;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xxs),
      child: Material(
        color: focused
            ? c.selectedSurface
            : ticked
                ? Colors.transparent
                : c.surfaceSunken,
        shape: RoundedRectangleBorder(
          borderRadius: MayosRadii.smallRadius,
          side: BorderSide(
              color: focused ? c.selectedBorder : Colors.transparent),
        ),
        child: InkWell(
          key: ValueKey<String>(
              'logger.cell.$exerciseIndex.$setIndex.${field.name}'),
          borderRadius: MayosRadii.smallRadius,
          onTap: () => setState(
              () => _focus = LoggerCellFocus(exerciseIndex, setIndex, field)),
          child: SizedBox(
            height: kMayosMinTapTarget,
            child: Center(
              child: Text(
                value ?? hint ?? '–',
                style: MayosTypography.numericSmall.copyWith(color: color),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSaveStep(ActiveWorkout workout) {
    final MayosThemeExtension c = MayosTheme.of(context);
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
                onPressed: _backFromSave,
                icon: const Icon(Icons.arrow_back),
              ),
              Text(
                'Save workout',
                style: MayosTypography.sectionHeading
                    .copyWith(color: c.textPrimary),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.sm),
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
}

/// The one message line the logger shows under the list or the save step:
/// blocking reasons and errors in the danger colour, notes neutral (#123 item
/// 12).
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

/// Searches the real catalog so an unplanned exercise carries an id the
/// service can validate, rather than an invented one that would be refused on
/// sync (ADR 020/033).
class _UnplannedExerciseDialog extends ConsumerStatefulWidget {
  const _UnplannedExerciseDialog();

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

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final String query = _query.text.trim();
    if (query.isEmpty) {
      setState(() => _error = 'Type an exercise name to search.');
      return;
    }
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      final List<ExerciseCatalogEntry> results =
          await ref.read(apiClientProvider).searchExercises(query);
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = results;
        _error = results.isEmpty ? 'No matching exercise found.' : null;
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

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return AlertDialog(
      title: const Text('Add unplanned exercise'),
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
            if (_results.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: <Widget>[
                    for (final ExerciseCatalogEntry entry in _results)
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
