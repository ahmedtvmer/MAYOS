import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../../core/active_workout.dart';
import '../../../core/active_program.dart';
import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/baselines.dart';
import '../../../core/client_session_id.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/device_timezone.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/personal_records.dart';
import '../../../core/rest_alerts.dart';
import '../../../core/training_status_projection.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_settings_tile.dart';
import '../../../core/ui/mayos_stat.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/workout_equipment.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../exercise_picker_dialog.dart';
import 'active_workout_controller.dart';
import 'draft_sync_service.dart';
import 'deload_banner.dart';
import 'logger_program_substitution.dart';
import 'logger_replace_confirmation.dart';
import 'logger_bottom_bar.dart';
import 'logger_card_widgets.dart';
import 'logger_keypad.dart';
import 'rest_timer_widgets.dart';
import 'web_workout_committer.dart';

// The frozen previous working set and the cell weight format live beside the
// Active workout (`core/active_workout.dart`); the cell/hint mapping, the
// card and the rows live in `logger_card_widgets.dart` (#158), the fixed
// bottom bar in `logger_bottom_bar.dart` (#160) — this screen owns only the
// decisions: focus, ticks, records, the Current set and persistence
// (#123/#124/#125).

/// Why Finish refuses while nothing is ticked (#123), and the one message a
/// tick itself clears (#160): it is the Finish bar's own nudge, shown right
/// above that bar, so it must not outlive the state it describes. Other
/// errors (a failed save, an offline refusal) stay until they are fixed.
/// The message slot's cap (#160/#45): at most this share of the screen
/// height, scrolling inside itself, so a long line at a large text scale
/// can never push the bottom bar (or the keypad) off the screen.
const double _kMessageSlotMaxHeightFraction = 1 / 3;

/// The logger's shared route for linked exercises and warm-up movements.
void openLoggerExerciseDetail(
  BuildContext context, {
  required String exerciseId,
  int? dayOrder,
}) {
  final String path = '$exerciseDetailPath/${Uri.encodeComponent(exerciseId)}';
  context.push(
    dayOrder == null ? '$path?library=1' : '$path?day=$dayOrder',
  );
}

enum _SummaryAction { save, retry, discardWorkout, done }

enum _WorkoutLoggerCopyError {
  workoutProgressBlocked,
  connectToRefresh,
  saveFailedNoLoss,
  couldNotReachMayos,
  reopenWorkoutToSave,
  programRefreshBeforeSave,
  mayosBusy,
}

sealed class _WorkoutLoggerError {
  const _WorkoutLoggerError({this.programUnchangedPrefix = false});

  final bool programUnchangedPrefix;
}

final class _WorkoutLoggerCopyErrorState extends _WorkoutLoggerError {
  const _WorkoutLoggerCopyErrorState(this.message);

  final _WorkoutLoggerCopyError message;
}

final class _WorkoutLoggerFailureErrorState extends _WorkoutLoggerError {
  const _WorkoutLoggerFailureErrorState(this.failure,
      {super.programUnchangedPrefix});

  final FailureMessage failure;
}

final class _WorkoutLoggerSubstitutionErrorState extends _WorkoutLoggerError {
  const _WorkoutLoggerSubstitutionErrorState(this.messageType,
      {super.programUnchangedPrefix});

  final LoggerProgramSubstitutionMessage messageType;
}

final class _WorkoutLoggerDetailErrorState extends _WorkoutLoggerError {
  const _WorkoutLoggerDetailErrorState(this.detail,
      {super.programUnchangedPrefix});

  final String detail;
}

class _WorkoutExerciseAtIndex {
  const _WorkoutExerciseAtIndex(this.workout, this.exercise);

  final ActiveWorkout workout;
  final ActiveWorkoutExercise exercise;
}

class _LoggerProgramLoad {
  const _LoggerProgramLoad({
    required this.program,
    required this.fromCache,
    required this.fetchedOnline,
  });

  final TrainingProgram? program;
  final bool fromCache;
  final bool fetchedOnline;
}

class _LoggerReplacementPick {
  const _LoggerReplacementPick({
    required this.workout,
    required this.exerciseIndex,
    required this.exercise,
    required this.replacement,
  });

  final ActiveWorkout workout;
  final int exerciseIndex;
  final ActiveWorkoutExercise exercise;
  final ExerciseCatalogEntry replacement;
}

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

class _WorkoutLoggerScreenState extends ConsumerState<WorkoutLoggerScreen>
    with WidgetsBindingObserver {
  final TextEditingController _notes = TextEditingController();
  final TextEditingController _refreshedCoachReason = TextEditingController();

  bool _loading = true;
  String? _loadError;
  FailureMessage? _loadFailure;
  _WorkoutLoggerError? _error;

  /// A non-blocking note to the player (e.g. a clamped performed date).
  String? _notice;
  bool _fromCache = false;
  TrainingProgram? _loggerProgram;
  bool _loggerProgramOnline = false;
  _LoggerReplacementPick? _pendingCoachRequest;
  bool _pendingCoachReasonRequired = false;
  bool _pendingCoachRequestSubmitting = false;

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
  int? _checkpointNumber;
  CheckpointReview? _checkpointReview;
  bool _saving = false;
  WorkoutCopy get _copy => WorkoutCopy(ref.read(displayLanguageProvider));

  String? _visibleError(BuildContext context) {
    final _WorkoutLoggerError? error = _error;
    if (error == null) return null;
    final String detail = switch (error) {
      _WorkoutLoggerCopyErrorState(:final message) => switch (message) {
          _WorkoutLoggerCopyError.workoutProgressBlocked =>
            _copy.workoutProgressBlocked,
          _WorkoutLoggerCopyError.connectToRefresh => _copy.connectToRefresh,
          _WorkoutLoggerCopyError.saveFailedNoLoss => _copy.saveFailedNoLoss,
          _WorkoutLoggerCopyError.couldNotReachMayos =>
            _copy.couldNotReachMayos,
          _WorkoutLoggerCopyError.reopenWorkoutToSave =>
            _copy.reopenWorkoutToSave,
          _WorkoutLoggerCopyError.programRefreshBeforeSave =>
            _copy.programRefreshBeforeSave,
          _WorkoutLoggerCopyError.mayosBusy => _copy.mayosBusy,
        },
      _WorkoutLoggerFailureErrorState(:final failure) =>
        displayCopyOf(context).failureMessage(failure),
      _WorkoutLoggerSubstitutionErrorState(:final messageType) =>
        _substitutionText(messageType),
      _WorkoutLoggerDetailErrorState(:final detail) => detail,
    };
    if (error.programUnchangedPrefix) {
      return _copy.swapSavedButProgramUnchanged(detail);
    }
    return detail;
  }

  _SummaryAction _summaryAction = _SummaryAction.save;
  LoggerCellFocus? _focus;
  final Map<String, GlobalKey> _rowKeys = <String, GlobalKey>{};
  late final bool _webPageVisibilityEnabled;
  bool _pageVisible = true;

  /// The foreground countdown ticker (#125): while a rest runs it wakes the
  /// bar every quarter second and, at the end time, completes the rest — the
  /// vibration, the sound, and the bar going away — even when the keypad (and
  /// so the bar) is hidden.
  Timer? _restTicker;

  @override
  void initState() {
    super.initState();
    _webPageVisibilityEnabled = ref.read(webPageVisibilityEnabledProvider);
    WidgetsBinding.instance.addObserver(this);
    unawaited(_keepAwake(true));
    Future<void>.microtask(_load);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _restTicker?.cancel();
    _restTicker = null;
    unawaited(_keepAwake(false));
    _notes.dispose();
    _refreshedCoachReason.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_webPageVisibilityEnabled) {
      return;
    }
    if (state == AppLifecycleState.resumed) {
      final bool returnedFromHidden = !_pageVisible;
      _pageVisible = true;
      if (returnedFromHidden) {
        // Re-read the stored end time immediately. If rest ended while this
        // page was away, clear it without a background alert on return.
        _catchUpRestAfterHidden();
        if (mounted) {
          setState(() {});
        }
      }
    } else if (state == AppLifecycleState.hidden ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _pageVisible = false;
    }
  }

  /// Starts or stops the ticker to match whether a rest is running. Called
  /// from build, which only ever touches the timer, never the tree.
  void _syncRestTicker(ActiveWorkout workout) {
    final bool running = workout.rest != null;
    if (running && _restTicker == null) {
      _restTicker = Timer.periodic(
        const Duration(milliseconds: 250),
        (_) => _onRestTick(),
      );
    } else if (!running && _restTicker != null) {
      _restTicker?.cancel();
      _restTicker = null;
    }
  }

  void _onRestTick() {
    if (!_pageVisible) {
      return;
    }
    final ActiveRestTimer? rest = _workout?.rest;
    if (rest == null) {
      return;
    }
    final DateTime now = ref.read(clockProvider)();
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

  void _catchUpRestAfterHidden() {
    final ActiveRestTimer? rest = _workout?.rest;
    if (rest == null) {
      return;
    }
    if (!rest.isOver(ref.read(clockProvider)())) {
      _onRestTick();
      return;
    }
    unawaited(_controller.completeRest(playAlert: false));
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
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    if (accountId == null) {
      setState(() {
        _loading = false;
        _loadFailure = const AppFailureMessage(
          AppFailureId.draftNotSignedIn,
          'You are not signed in.',
        );
      });
      return;
    }
    _timezone = await ref.read(deviceTimezoneOrNullProvider);
    final _LoggerProgramLoad programLoad = await _loadLoggerProgram(accountId);
    final bool fromCache = programLoad.fromCache;

    final ActiveWorkoutController controller = ref.read(
      activeWorkoutControllerProvider.notifier,
    );
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
          _loadError = _copy.trainingDayUnavailableOffline;
          _fromCache = fromCache;
        });
        return;
      }
      final StartWorkoutOutcome outcome = await controller.startFromDay(
        accountId: accountId,
        day: day,
        programVersion: program?.version,
      );
      if (outcome == StartWorkoutOutcome.started) {
        ref.read(analyticsClientProvider).workoutStarted();
      }
    }
    final ActiveWorkout? workout = controller.workout;
    if (!mounted) return;
    setState(() {
      _fromCache = fromCache;
      _loggerProgram = programLoad.program;
      _loggerProgramOnline = programLoad.fetchedOnline;
      _loading = false;
      if (workout != null) {
        _applyDefaultPerformedDate(workout);
      }
    });
  }

  Future<_LoggerProgramLoad> _loadLoggerProgram(String accountId) async {
    try {
      final ActiveProgram active = await loadActiveProgram(
        api: ref.read(apiClientProvider),
        cache: ref.read(workoutCacheStoreProvider),
        accountId: accountId,
      );
      return _LoggerProgramLoad(
        program: active.program,
        fromCache: active.fromCache,
        fetchedOnline: !active.fromCache && active.program != null,
      );
    } on ApiException {
      return const _LoggerProgramLoad(
        program: null,
        fromCache: true,
        fetchedOnline: false,
      );
    }
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
    final DateTime clamped = performedDateWindow(
      now: ref.read(clockProvider)(),
    ).clamp(started);
    _performedDate = clamped;
    if (formatPerformedDate(clamped) != formatPerformedDate(started)) {
      _notice = _copy.dateWindowClamped(
        formatPerformedDate(started),
        formatPerformedDate(clamped),
      );
    }
  }

  ActiveWorkout? get _workout =>
      ref.read(activeWorkoutControllerProvider).workout;

  ActiveWorkoutController get _controller =>
      ref.read(activeWorkoutControllerProvider.notifier);

  /// Why Finish is blocked beyond "no sets ticked", or null.
  String? get _blockReason {
    if (_timezone == null) {
      return _copy.timezoneUnavailable;
    }
    if (_workout?.programVersion == null && _workout != null) {
      return _copy.programUnavailable;
    }
    return null;
  }

  // ---- table interactions -------------------------------------------------

  String _initialText(ActiveWorkout workout, LoggerCellFocus focus) {
    final ActiveWorkoutExercise exercise =
        workout.exercises[focus.exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[focus.setIndex];
    if (focus.field == LoggerField.kg &&
        zeroLoadLabelKind(set.weightKg, exercise.equipment) != null) {
      return '';
    }
    return cellTexts(
          LoggerCellState(
            set: set,
            previous:
                previousSetFor(exercise, focus.setIndex, workout.baselines),
            prescriptionHint: exercise.prescriptionHint,
            equipment: exercise.equipment,
          ),
          focus.field,
          _copy,
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
      equipment: exercise.equipment,
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

  void _changeFocusAndReveal(LoggerCellFocus? next) {
    setState(() => _changeFocus(next));
    if (next == null) {
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _revealFocusedRow(next),
    );
  }

  void _revealFocusedRow(LoggerCellFocus focus) {
    if (!mounted) {
      return;
    }
    final ActiveWorkout? workout = _workout;
    if (workout == null ||
        focus.exerciseIndex >= workout.exercises.length ||
        focus.setIndex >= workout.exercises[focus.exerciseIndex].sets.length) {
      return;
    }
    final String setId =
        workout.exercises[focus.exerciseIndex].sets[focus.setIndex].id;
    final BuildContext? rowContext = _rowKeys[setId]?.currentContext;
    if (rowContext == null) {
      return;
    }
    final RenderObject? rowObject = rowContext.findRenderObject();
    final RenderObject? viewportObject =
        Scrollable.of(rowContext).context.findRenderObject();
    if (rowObject is! RenderBox || viewportObject is! RenderBox) {
      return;
    }
    final Rect rowRect = rowObject.localToGlobal(Offset.zero) & rowObject.size;
    final Rect viewportRect =
        viewportObject.localToGlobal(Offset.zero) & viewportObject.size;
    final ScrollPositionAlignmentPolicy policy;
    if (rowRect.bottom > viewportRect.bottom) {
      policy = ScrollPositionAlignmentPolicy.keepVisibleAtEnd;
    } else if (rowRect.top < viewportRect.top) {
      policy = ScrollPositionAlignmentPolicy.keepVisibleAtStart;
    } else {
      return;
    }
    unawaited(
      Scrollable.ensureVisible(
        rowContext,
        alignmentPolicy: policy,
        duration: MayosMotion.fast,
      ),
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
      before: _recordBadges(
            recordFocus.exerciseIndex,
          )[recordFocus.setId]
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
        unawaited(
          _controller.updateWeightCell(
            focus.exerciseIndex,
            focus.setIndex,
            weightKg: double.tryParse(text) ?? 0,
            weightExplicitlyEntered: double.tryParse(text) != null,
          ),
        );
      case LoggerField.reps:
        unawaited(
          _controller.updateCell(
            focus.exerciseIndex,
            focus.setIndex,
            reps: int.tryParse(text) ?? 0,
          ),
        );
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
      await _controller.updateCell(
        focus.exerciseIndex,
        focus.setIndex,
        unrated: true,
      );
    } else {
      await _controller.updateCell(
        focus.exerciseIndex,
        focus.setIndex,
        rir: rir,
      );
    }
    if (!mounted) {
      return;
    }
    final ActiveWorkout? workout = _workout;
    if (workout == null) {
      return;
    }
    _changeFocusAndReveal(nextLoggerCellFocus(workout, focus));
  }

  void _onKeypadNext() {
    final ActiveWorkout? workout = _workout;
    final LoggerCellFocus? focus = _focus;
    if (workout == null || focus == null) {
      return;
    }
    _changeFocusAndReveal(nextLoggerCellFocus(workout, focus));
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
    if (_error is _WorkoutLoggerCopyErrorState &&
        (_error as _WorkoutLoggerCopyErrorState).message ==
            _WorkoutLoggerCopyError.workoutProgressBlocked) {
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
    final BaselineSet? prev = previousSetFor(
      exercise,
      setIndex,
      workout.baselines,
    );
    double weight = set.weightKg;
    int reps = set.reps;
    double? rir = set.rir;
    bool changed = false;
    if (shouldAutofillPreviousWeight(
      set: set,
      previousWeightKg: prev?.weightKg,
      equipment: exercise.equipment,
    )) {
      // A missing weight borrows the previous performance unless the player
      // explicitly entered zero for a body-weight or band exercise.
      weight = prev!.weightKg;
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
    final bool weightRequired =
        !isBodyWeightOrBandEquipment(exercise.equipment) && weight <= 0;
    if (weightRequired || reps <= 0) {
      // Nothing to log yet: open the keypad at the first required cell.
      _changeFocusAndReveal(
        LoggerCellFocus(
          exerciseIndex,
          setIndex,
          weightRequired ? LoggerField.kg : LoggerField.reps,
        ),
      );
      return;
    }
    if (_webPageVisibilityEnabled &&
        !set.isWarmup &&
        _controller.restLengthFor(exerciseIndex) > 0) {
      // Invoke resume synchronously while this tick callback is still a user
      // gesture, before the row and rest are persisted.
      unlockWebRestAudio();
    }
    if (changed) {
      await _controller.updateCell(
        exerciseIndex,
        setIndex,
        weightKg: set.weightKg <= 0 ? weight : null,
        reps: set.reps <= 0 ? reps : null,
        rir: set.rir == null && rir != null ? rir : null,
      );
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
            exercise.sets.where((ActiveWorkoutSet s) => !s.ticked).length,
      );

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
      int setsTotal,
    }) progress = workoutProgressOf(workout);
    return _copy.workoutProgress(
      exercisesDone: progress.exercisesCompleted,
      exercisesTotal: progress.exercisesTotal,
      setsDone: progress.setsTicked,
      setsTotal: progress.setsTotal,
    );
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
    final bool hasLoggableSet = workout.exercises.any(
      (ActiveWorkoutExercise exercise) => exercise.hasLoggableSet,
    );
    if (!hasLoggableSet) {
      setState(
        () => _error = const _WorkoutLoggerCopyErrorState(
          _WorkoutLoggerCopyError.workoutProgressBlocked,
        ),
      );
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
    final DateTime now = ref.read(clockProvider)();
    List<WorkoutDraft> drafts = const <WorkoutDraft>[];
    try {
      drafts = await ref.read(draftStoreProvider).read(finished.accountId);
    } on PlatformException {
      // The current workout still projects if protected storage is unavailable.
    } on MissingPluginException {
      // The current workout still projects if pending drafts cannot be read.
    }
    final TrainingStatus? trainingStatus = await ref
        .read(trainingStatusProvider.notifier)
        .statusForSummary(finished.accountId);
    if (!mounted || _workout?.id != finished.id) {
      return;
    }
    final List<TrainingStatusSummaryLine> trainingLines =
        projectTrainingStatusSummary(
      status: trainingStatus,
      drafts: drafts,
      now: now,
    ).toList();
    final int? checkpointNumber = projectedCheckpointNumber(
      status: trainingStatus,
      drafts: drafts,
    );
    if (checkpointNumber != null) {
      trainingLines.removeWhere(
        (TrainingStatusSummaryLine line) =>
            line is CheckpointReachedSummaryLine,
      );
    }
    setState(() {
      _summary = WorkoutSummary.of(
        finished,
        now: now,
        trainingLines: trainingLines,
      );
      _checkpointNumber = checkpointNumber;
      _checkpointReview = null;
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
                _copy.untickedSetQuestion(unticked),
                textAlign: _copy.isArabic ? TextAlign.end : null,
                style: MayosTypography.of(context).sectionHeading,
              ),
              const SizedBox(height: MayosSpacing.xs),
              Text(_copy.onlyTickedSetsSaved),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: _copy.discardUntickedAndFinish,
                onPressed: () => Navigator.of(context).pop(true),
              ),
              const SizedBox(height: MayosSpacing.sm),
              MayosButton(
                label: _copy.keepLogging,
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
    if (ref.read(webDirectWorkoutCommitEnabledProvider)) {
      await _saveWebWorkout();
      return;
    }
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
        clientSessionId: newClientSessionId(),
        now: DateTime.now(),
        performedDate: formatPerformedDate(_performedDate),
        readiness: _readiness,
        notes: _notes.text.trim(),
      );
      if (draft == null) {
        setState(() {
          _error = const _WorkoutLoggerCopyErrorState(
            _WorkoutLoggerCopyError.connectToRefresh,
          );
        });
        return;
      }
      await sync.saveDraft(draft);
      // Saving ends the Active workout (CONTEXT.md): the draft now owns it.
      // The controller waits for every pending store write before deleting, so
      // a late write can never resurrect it (#123 item 5).
      await _controller.finishAsDraft(
        accountId: workout.accountId,
        workoutId: workout.id,
      );
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_copy.saveDraftNotice)),
      );
      context.go(workoutsPath);
    } on Object catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        if (error is ApiException) {
          _error = _WorkoutLoggerFailureErrorState(apiFailureMessage(error));
        } else {
          _error = const _WorkoutLoggerCopyErrorState(
            _WorkoutLoggerCopyError.saveFailedNoLoss,
          );
        }
      });
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  Future<void> _saveWebWorkout() async {
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
      final WebWorkoutCommitResult result =
          await ref.read(webWorkoutCommitterProvider).save(
                workout: workout,
                timezone: timezone,
                now: DateTime.now(),
                performedDate: formatPerformedDate(_performedDate),
                readiness: _readiness,
                notes: _notes.text.trim(),
              );
      final dynamic checkpointBody = result.response?['checkpoint'];
      final int? reachedCheckpoint = checkpointBody is Map<String, dynamic>
          ? (checkpointBody['number'] as num?)?.toInt()
          : null;
      CheckpointReview? checkpointReview;
      if (result.status == WebWorkoutCommitStatus.committed &&
          reachedCheckpoint != null) {
        try {
          checkpointReview = await ref
              .read(apiClientProvider)
              .checkpointReview(reachedCheckpoint);
        } on ApiException {
          checkpointReview = null;
        }
      }
      if (!mounted) {
        return;
      }
      setState(() {
        _checkpointNumber = reachedCheckpoint ?? _checkpointNumber;
        _checkpointReview = checkpointReview;
        switch (result.status) {
          case WebWorkoutCommitStatus.committed:
            _summaryAction = _SummaryAction.done;
            _error = null;
            _notice = _copy.savedToHistory;
            break;
          case WebWorkoutCommitStatus.retryable:
            _summaryAction = _SummaryAction.retry;
            _error = _webWorkoutCommitError(result);
            break;
          case WebWorkoutCommitStatus.sessionProblem:
            _summaryAction = _SummaryAction.retry;
            _error = _webWorkoutCommitError(result);
            break;
          case WebWorkoutCommitStatus.refused:
            _summaryAction = _SummaryAction.discardWorkout;
            _error = _webWorkoutCommitError(result);
            break;
        }
      });
    } on Object {
      if (mounted) {
        setState(() {
          _summaryAction = _SummaryAction.retry;
          _error = const _WorkoutLoggerCopyErrorState(
            _WorkoutLoggerCopyError.couldNotReachMayos,
          );
        });
      }
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  /// How a failed save is reported: the service's own message when it has one,
  /// otherwise a line that promises the workout is still on screen (#123
  /// item 6).
  _WorkoutLoggerError? _webWorkoutCommitError(WebWorkoutCommitResult result) {
    final FailureMessage? failure = result.failureMessage;
    if (failure != null) {
      return _WorkoutLoggerFailureErrorState(failure);
    }
    return switch (result.messageType) {
      WebWorkoutCommitMessage.reopenWorkout =>
        const _WorkoutLoggerCopyErrorState(
          _WorkoutLoggerCopyError.reopenWorkoutToSave,
        ),
      WebWorkoutCommitMessage.refreshProgram =>
        const _WorkoutLoggerCopyErrorState(
          _WorkoutLoggerCopyError.programRefreshBeforeSave,
        ),
      WebWorkoutCommitMessage.connection => const _WorkoutLoggerCopyErrorState(
          _WorkoutLoggerCopyError.couldNotReachMayos,
        ),
      WebWorkoutCommitMessage.busy => const _WorkoutLoggerCopyErrorState(
          _WorkoutLoggerCopyError.mayosBusy,
        ),
      null => result.message == null
          ? null
          : _WorkoutLoggerDetailErrorState(result.message!),
    };
  }

  Future<void> _addUnplanned() async {
    final ExerciseCatalogEntry? entry = await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => ExercisePickerDialog(
        title: _copy.addUnplannedExercise,
      ),
    );
    if (entry == null) {
      return;
    }
    await _controller.addUnplannedExercise(
      exerciseId: entry.id,
      exerciseName: entry.name,
      imagePath: entry.imagePath,
      equipment: entry.equipment,
    );
  }

  Future<void> _discardRefusedWebWorkout() async {
    final ActiveWorkout? workout = _workout;
    if (workout == null || !await _confirmWebWorkoutDiscard()) return;
    await _controller.discard(
      accountId: workout.accountId,
      workoutId: workout.id,
    );
    if (mounted) context.go(homePath);
  }

  Future<bool> _confirmWebWorkoutDiscard() async {
    final bool? discard = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(_copy.confirmDiscardTitle),
        content: Text(_copy.discardBrowserSets),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(_copy.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(_copy.discard),
          ),
        ],
      ),
    );
    return discard == true && mounted;
  }

  /// Back from the summary returns to the Active workout (#124). The snapshot
  /// is dropped, so a later Finish computes a fresh one from the rows. A rest
  /// that kept counting gets its notification and alarm back (#125).
  void _backFromSummary() {
    if (_saving) {
      return;
    }
    if (_summaryAction == _SummaryAction.done) {
      context.go(homePath);
      return;
    }
    setState(() {
      _summaryStep = false;
      _summary = null;
      _checkpointNumber = null;
      _checkpointReview = null;
      _error = null;
      _summaryAction = _SummaryAction.save;
    });
    // Back to the logger: the top bar's Workout time runs live again (#159).
    ref.read(loggerSummaryProvider.notifier).state = null;
    unawaited(_controller.restoreRestAlerts());
  }

  // ---- build --------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    final ActiveWorkoutState active = ref.watch(
      activeWorkoutControllerProvider,
    );
    if (_loading || !active.ready) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null || _loadFailure != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Text(
            _loadFailure == null
                ? _loadError!
                : displayCopyOf(context).failureMessage(_loadFailure!),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    final ActiveWorkout? workout = active.workout;
    if (workout == null && !_summaryStep) {
      // The workout was just cleared by Save; the route moves away next frame.
      return const Center(child: CircularProgressIndicator());
    }
    if (workout != null) {
      _syncRestTicker(workout);
    }
    final bool keypadVisible =
        workout != null && _validFocus(workout) && _focus != null;
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
                : _buildActive(workout!),
          ),
          if (!_summaryStep) ...<Widget>[
            // Messages sit above the bottom bar, never scrolled away at the
            // end of the list: that is where the player acts on them (#160).
            ..._activeMessages(),
            // The keypad replaces the bottom bar outright while an edit is
            // open, so the screen has exactly one bottom bar at a time and
            // the keypad never covers it (#160).
            if (workout != null)
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
    final String? visibleError = _visibleError(context);
    if (visibleError != null) {
      lines.add(_MessageLine(visibleError));
    }
    if (_notice != null) {
      lines.add(_MessageLine(_notice!, danger: false));
    }
    if (_pendingCoachRequest != null) {
      lines.add(LoggerCoachRequestReasonPrompt(
        controller: _refreshedCoachReason,
        reasonRequired: _pendingCoachReasonRequired,
        submitting: _pendingCoachRequestSubmitting,
        onSubmit: () => unawaited(_submitPendingCoachRequest()),
      ));
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
          padding: const EdgeInsetsDirectional.only(
            start: MayosSpacing.lg,
            end: MayosSpacing.lg,
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
      int setsTotal,
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
  /// carries its own quarter-second ticker and reads the app clock itself,
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
    final WorkoutCopy copy = _copy;
    final Set<String> currentSetIds = <String>{
      for (final ActiveWorkoutExercise exercise in workout.exercises)
        for (final ActiveWorkoutSet set in exercise.sets) set.id,
    };
    _rowKeys.removeWhere(
      (String setId, GlobalKey key) => !currentSetIds.contains(setId),
    );
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
            style: MayosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          // The progress line (#159): the same pure counts the bottom bar
          // will show (#160), under the screen's one serif heading.
          Text(
            _progressLine(workout),
            key: const ValueKey<String>('logger.progress'),
            textAlign: copy.isArabic ? TextAlign.end : null,
            style: MayosTypography.of(context).bodySecondary.copyWith(
              color: c.textSecondary,
            ),
          ),
          if (_fromCache) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            const _OfflineLoggerNotice(),
          ],
          if (workout.deload != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            DeloadBanner(
              key: const ValueKey<String>('logger.deload'),
              decision: workout.deload!,
              onOpenAssistant: () => context.push(chatPath),
            ),
          ],
          const SizedBox(height: MayosSpacing.md),
          if (workout.warmupMovements.isNotEmpty) ...<Widget>[
            MayosSectionHeader(
              key: ValueKey<String>('logger.warmup.section'),
              title: _copy.warmup,
              padding: EdgeInsets.zero,
            ),
            const SizedBox(height: MayosSpacing.xs),
            for (int i = 0; i < workout.warmupMovements.length; i++)
              WarmupMovementLoggingCard(
                movement: workout.warmupMovements[i],
                movementIndex: i,
                onSetChanged: (edit) =>
                    unawaited(_controller.updateWarmupMovementSet(
                  i,
                  edit.$1,
                  edit.$2,
                )),
                onOpenDetail: workout.warmupMovements[i].exerciseId == null ||
                        workout.warmupMovements[i].exerciseId!.isEmpty
                    ? null
                    : () => openLoggerExerciseDetail(
                          context,
                          exerciseId: workout.warmupMovements[i].exerciseId!,
                        ),
              ),
            MayosSectionHeader(
              key: const ValueKey<String>('logger.exercises.section'),
              title: _copy.exercises,
              padding: EdgeInsets.zero,
            ),
            const SizedBox(height: MayosSpacing.xs),
          ],
          for (int i = 0; i < workout.exercises.length; i++)
            // A replaced planned exercise (#162) keeps its place in the
            // workout for the draft but is never a card: it has no rows and
            // is nothing left to do.
            if (!workout.exercises[i].replaced)
              _buildExerciseCard(workout, i, current),
          if (workout.cardio != null) ...<Widget>[
            CardioLoggingCard(
              cardio: workout.cardio!,
              onChanged: (WorkoutCardio updated) =>
                  unawaited(_controller.updateCardio(updated)),
            ),
          ],
          // Add exercise stays the list's last action; Finish lives in the
          // fixed bottom bar (#160), so it never needs scrolling to.
          MayosButton(
            key: const ValueKey<String>('logger.addExercise'),
            label: _copy.addExercise,
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
  Widget _buildExerciseCard(
    ActiveWorkout workout,
    int exerciseIndex,
    ({int exerciseIndex, int setIndex})? current,
  ) {
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    // A replacement is undone rather than removed: taking it out brings the
    // hidden planned exercise back (#162).
    final bool isReplacement = isReplacementExerciseAt(workout, exerciseIndex);
    final String? linkedExerciseId =
        exercise.exercise['exercise_id'] as String?;
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
      undoReplaceKey: ValueKey<String>('logger.cardMenu.$exerciseIndex.undo'),
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
      onOpenDetail: linkedExerciseId == null ||
              linkedExerciseId.isEmpty ||
              exercise.isCoachExercise
          ? null
          : () => openLoggerExerciseDetail(
                context,
                exerciseId: linkedExerciseId,
                dayOrder: exercise.unplanned ? null : workout.dayOrder,
              ),
      onRemove: exercise.unplanned && !isReplacement
          ? () => unawaited(_onRemoveExercise(exerciseIndex))
          : null,
      onUndoReplace:
          isReplacement ? () => unawaited(_onUndoReplace(exerciseIndex)) : null,
    );
  }

  /// **Replace exercise** (#162/#171): pick a catalog entry, persist the
  /// workout change, then optionally apply the same swap to its program slot.
  Future<void> _onReplaceExercise(int exerciseIndex) async {
    final _WorkoutExerciseAtIndex? current = _workoutExerciseAt(exerciseIndex);
    if (current == null) return;
    final bool programActionAvailable = _canOfferProgramSwap(
      current.workout,
      current.exercise,
    );
    final int ticked = current.exercise.sets
        .where((ActiveWorkoutSet set) => set.ticked)
        .length;
    LoggerReplaceConfirmation confirmation = const LoggerReplaceConfirmation(
      confirmed: true,
    );
    if (ticked > 0 || programActionAvailable) {
      final LoggerReplaceConfirmation? answer =
          await _confirmReplaceBeforePicking(
        current.exercise,
        programActionAvailable: programActionAvailable,
      );
      if (answer == null || !answer.confirmed || !mounted) return;
      confirmation = answer;
    }
    final ExerciseCatalogEntry? replacement =
        await _pickReplacementFromCatalog(current.exercise);
    if (replacement == null || !mounted) return;
    final _LoggerReplacementPick? pick =
        _replacementPickAtIndex(exerciseIndex, replacement);
    if (pick == null) return;
    await _replaceInActiveWorkout(pick);
    if (confirmation.keepInProgram && mounted) {
      await _keepSwapInProgram(pick, reason: confirmation.reason);
    }
  }

  _WorkoutExerciseAtIndex? _workoutExerciseAt(int exerciseIndex) {
    final ActiveWorkout? latest = _workout;
    if (latest == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= latest.exercises.length) {
      return null;
    }
    return _WorkoutExerciseAtIndex(latest, latest.exercises[exerciseIndex]);
  }

  Future<LoggerReplaceConfirmation?> _confirmReplaceBeforePicking(
    ActiveWorkoutExercise exercise, {
    required bool programActionAvailable,
  }) {
    final int ticked =
        exercise.sets.where((ActiveWorkoutSet set) => set.ticked).length;
    final bool coachControlled = _loggerProgram?.playerControlsProgram != true;
    return showDialog<LoggerReplaceConfirmation>(
      context: context,
      builder: (BuildContext context) => LoggerReplaceConfirmationDialog(
        tickedSetCount: ticked,
        programActionAvailable: programActionAvailable,
        coachControlled: coachControlled,
      ),
    );
  }

  _LoggerReplacementPick? _replacementPickAtIndex(
    int exerciseIndex,
    ExerciseCatalogEntry replacement,
  ) {
    final _WorkoutExerciseAtIndex? latest = _workoutExerciseAt(exerciseIndex);
    if (latest == null) return null;
    return _LoggerReplacementPick(
      workout: latest.workout,
      exerciseIndex: exerciseIndex,
      exercise: latest.exercise,
      replacement: replacement,
    );
  }

  Future<ExerciseCatalogEntry?> _pickReplacementFromCatalog(
    ActiveWorkoutExercise exercise,
  ) async {
    final String? muscle = await _targetMuscleOf(exercise.exerciseId);
    if (!mounted) return null;
    final Set<String> inWorkout = <String>{
      for (final ActiveWorkoutExercise workoutExercise
          in _workout?.exercises ?? <ActiveWorkoutExercise>[])
        workoutExercise.exerciseId,
    };
    return showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => ExercisePickerDialog(
        title: _copy.replaceExercise,
        targetMuscle: muscle,
        replacingExerciseId: exercise.exerciseId,
        excludeExerciseIds: inWorkout,
        suggestedSubstitutes: <SuggestedSubstitute>[
          for (final dynamic item in (exercise.exercise['suggested_substitutes']
                  as List<dynamic>? ??
              const <dynamic>[]))
            if (item is Map<String, dynamic>)
              SuggestedSubstitute.fromJson(item),
        ],
      ),
    );
  }

  Future<void> _replaceInActiveWorkout(_LoggerReplacementPick pick) async {
    // The planned card keeps its slot (marked and hidden) while the
    // replacement is inserted after it, so a keypad focus on a later card
    // moves with that card; an unplanned exercise is swapped in place (#162).
    final int delta = pick.exercise.unplanned ? 0 : 1;
    setState(() => _reindexFocus(pick.exerciseIndex, delta: delta));
    await _controller.replaceExercise(
      exerciseIndex: pick.exerciseIndex,
      replacementExercise: pick.replacement,
    );
  }

  bool _canOfferProgramSwap(
    ActiveWorkout workout,
    ActiveWorkoutExercise exercise,
  ) {
    if (!_loggerProgramOnline || exercise.unplanned || exercise.replaced) {
      return false;
    }
    final TrainingProgram? program = _loggerProgram;
    if (program == null) return false;
    final ProgramDay? day = _programDayForWorkout(program, workout);
    return day != null &&
        day.exercises.any((ProgramExercise programExercise) =>
            programExercise.exerciseId == exercise.exerciseId);
  }

  ProgramDay? _programDayForWorkout(
    TrainingProgram program,
    ActiveWorkout workout,
  ) {
    for (final ProgramDay day in program.days) {
      if (day.dayOrder == workout.dayOrder) return day;
    }
    return null;
  }

  Future<void> _keepSwapInProgram(
    _LoggerReplacementPick pick, {
    required String? reason,
  }) async {
    final TrainingProgram? program = _loggerProgram;
    if (program == null) {
      _showProgramSwapError(_copy.exerciseCatalogUnavailable,
          knownLocalDetail: true);
      return;
    }
    final ProgramDay? day = _programDayForWorkout(program, pick.workout);
    if (day == null || !_programContains(day, pick.exercise.exerciseId)) {
      _showProgramSwapError(
        _copy.exerciseNoLongerInProgram(pick.exercise.exerciseName),
        knownLocalDetail: true,
      );
      return;
    }
    final LoggerProgramSubstitutionResult result =
        await LoggerProgramSubstitutionController(
      api: ref.read(apiClientProvider),
      cache: ref.read(workoutCacheStoreProvider),
      accountId: ref.read(authControllerProvider).session?.account.accountId,
    ).apply(LoggerProgramSwap(
      workout: pick.workout,
      program: program,
      day: day,
      oldExercise: pick.exercise,
      replacement: pick.replacement,
      reason: reason,
    ));
    if (result.program != null && mounted) {
      setState(() {
        _loggerProgram = result.program;
        _loggerProgramOnline = true;
      });
    }
    if (result.coachReasonRequired) {
      setState(() {
        _pendingCoachRequest = pick;
        _pendingCoachReasonRequired = false;
        _pendingCoachRequestSubmitting = false;
        _refreshedCoachReason.clear();
        _notice = _substitutionMessage(result);
        _error = null;
      });
      return;
    }
    if (result.error) {
      _showProgramSwapError(
        result.message,
        messageType: result.messageType,
        failureMessage: result.failureMessage,
      );
    } else {
      setState(() {
        _pendingCoachRequest = null;
        _pendingCoachReasonRequired = false;
        _pendingCoachRequestSubmitting = false;
        _refreshedCoachReason.clear();
      });
      _showProgramSwapNotice(result.message, result.messageType);
    }
  }

  Future<void> _submitPendingCoachRequest() async {
    final _LoggerReplacementPick? pick = _pendingCoachRequest;
    if (pick == null || _pendingCoachRequestSubmitting) return;
    final String reason = _refreshedCoachReason.text.trim();
    if (reason.isEmpty) {
      setState(() => _pendingCoachReasonRequired = true);
      return;
    }
    setState(() => _pendingCoachRequestSubmitting = true);
    await _keepSwapInProgram(pick, reason: reason);
    if (mounted) setState(() => _pendingCoachRequestSubmitting = false);
  }

  bool _programContains(ProgramDay day, String exerciseId) => day.exercises.any(
        (ProgramExercise exercise) => exercise.exerciseId == exerciseId,
      );

  void _showProgramSwapError(
    String detail, {
    LoggerProgramSubstitutionMessage? messageType,
    FailureMessage? failureMessage,
    bool knownLocalDetail = false,
  }) {
    if (!mounted) return;
    setState(() {
      final bool showPrefix =
          messageType != LoggerProgramSubstitutionMessage.versionChanged;
      if (failureMessage != null) {
        _error = _WorkoutLoggerFailureErrorState(
          failureMessage,
          programUnchangedPrefix: showPrefix,
        );
      } else if (messageType != null) {
        _error = _WorkoutLoggerSubstitutionErrorState(
          messageType,
          programUnchangedPrefix: showPrefix,
        );
      } else {
        _error = _WorkoutLoggerDetailErrorState(
          detail,
          programUnchangedPrefix: showPrefix,
        );
      }
      _notice = null;
    });
  }

  void _showProgramSwapNotice(
    String message,
    LoggerProgramSubstitutionMessage? messageType,
  ) {
    if (!mounted) return;
    setState(() {
      _notice = messageType == null ? message : _substitutionText(messageType);
      _error = null;
    });
  }

  String _substitutionMessage(LoggerProgramSubstitutionResult result) =>
      result.failureMessage != null
          ? MayosCopy(ref.read(displayLanguageProvider))
              .failureMessage(result.failureMessage!)
          : result.messageType == null
              ? result.message
              : _substitutionText(result.messageType!);

  String _substitutionText(LoggerProgramSubstitutionMessage type) =>
      switch (type) {
        LoggerProgramSubstitutionMessage.versionChanged => _copy.versionChanged,
        LoggerProgramSubstitutionMessage.swapSaved => _copy.swapSaved,
        LoggerProgramSubstitutionMessage.coachReasonRequired =>
          _copy.reasonBeforeCoachRequest,
        LoggerProgramSubstitutionMessage.coachRequestSent =>
          _copy.coachAskedPermanentSwap,
        LoggerProgramSubstitutionMessage.refreshProgramTab =>
          _copy.programChangedSubstituteFromTab,
        LoggerProgramSubstitutionMessage.coachNowControlsProgram =>
          _copy.coachNowControlsProgram,
        LoggerProgramSubstitutionMessage.activeProgramUnavailable =>
          _copy.exerciseCatalogUnavailable,
      };

  /// The exercise's target muscle, read from the catalog detail the app
  /// already has a call for (`GET /workouts/exercises/{id}`): its first
  /// primary muscle is the catalog's `target_muscle`, the same column the
  /// search rows carry, so the two compare exactly. Null — unknown id,
  /// offline, a catalog row with no muscle — just opens the search
  /// unfiltered, so the lookup can never block a replace.
  Future<String?> _targetMuscleOf(String exerciseId) async {
    return exerciseTargetMuscle(
      ref.read(apiClientProvider),
      exerciseId,
    );
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
    final int ticked = workout.exercises[exerciseIndex].sets
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
    final int ticked = workout.exercises[exerciseIndex].sets
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
  Future<bool> _confirmDiscardSets(
    int ticked, {
    required String confirm,
  }) async {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool? discard = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(
          _copy.setsWereRemoved(ticked, undo: confirm == 'Undo replace'),
        ),
        content: Text(
          _copy.loggedSetsDiscarded,
          style: MayosTypography.of(context).bodySecondary.copyWith(color: c.textPrimary),
        ),
        actions: <Widget>[
          MayosButton(
            label: _copy.keepLogging,
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: confirm == 'Remove' ? _copy.removeAction : _copy.undoReplace,
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
          focus.exerciseIndex + delta,
          focus.setIndex,
          focus.field,
        );
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
  Widget _buildSetRow(
    ActiveWorkout workout,
    int exerciseIndex,
    int setIndex,
    Map<String, SetRecordBadges> badges, {
    required bool isCurrent,
  }) {
    final ActiveWorkoutExercise exercise = workout.exercises[exerciseIndex];
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    return SetLoggingRow(
      key: _rowKeys.putIfAbsent(set.id, GlobalKey.new),
      exerciseIndex: exerciseIndex,
      setIndex: setIndex,
      set: set,
      equipment: exercise.equipment,
      previous: previousSetFor(exercise, setIndex, workout.baselines),
      prescriptionHint: exercise.prescriptionHint,
      badges: badges[set.id] ?? const SetRecordBadges(),
      focus: _focus,
      isCurrent: isCurrent,
      onSelectCell: (LoggerField field) => _changeFocusAndReveal(
        LoggerCellFocus(exerciseIndex, setIndex, field),
      ),
      onToggleWarmup: () => unawaited(
        _updateWithRecordHaptic(
          exerciseIndex,
          setIndex,
          () => _controller.toggleWarmup(exerciseIndex, setIndex),
        ),
      ),
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
    final ActiveWorkout? workout = _workout;
    final _SummaryAction action = _summaryAction == _SummaryAction.save &&
            workout?.commitAttempted == true
        ? _SummaryAction.retry
        : _summaryAction;
    final String actionLabel = switch (action) {
      _SummaryAction.save => _copy.saveWorkout,
      _SummaryAction.retry => _copy.retry,
      _SummaryAction.discardWorkout => _copy.discardWorkout,
      _SummaryAction.done => _copy.done,
    };
    final VoidCallback actionHandler = switch (action) {
      _SummaryAction.save || _SummaryAction.retry => _save,
      _SummaryAction.discardWorkout => _discardRefusedWebWorkout,
      _SummaryAction.done => () => context.go(homePath),
    };
    return SingleChildScrollView(
      padding: MayosSpacing.screen,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              if (!_saving)
                IconButton(
                  key: const ValueKey<String>('logger.save.back'),
                  tooltip: _copy.backToWorkout,
                  onPressed: _backFromSummary,
                  icon: const Icon(Icons.arrow_back),
                ),
              Text(
                _copy.workoutSummary,
                style: MayosTypography.of(context).sectionHeading.copyWith(
                  color: c.textPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.sm),
          if (summary.records.isNotEmpty) ...<Widget>[
            _buildCelebration(summary.records),
            const SizedBox(height: MayosSpacing.md),
          ],
          if (_checkpointNumber != null) ...<Widget>[
            _checkpointCelebration(),
            const SizedBox(height: MayosSpacing.md),
          ],
          _buildStats(summary),
          if (summary.trainingLines.isNotEmpty) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            _buildTrainingStatus(summary.trainingLines),
          ],
          const SizedBox(height: MayosSpacing.lg),
          MayosCard(
            padding: EdgeInsets.zero,
            child: MayosSettingsTile(
              icon: Icons.event_outlined,
              title: _copy.performedDate,
              subtitle: date,
              subtitleTextDirection: TextDirection.ltr,
              trailing: Icon(Icons.edit_outlined, size: 20, color: c.textMuted),
              onTap: _pickDate,
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          _readinessHeader(),
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
            label: _copy.notesHint,
          ),
          if (_blockReason != null) _MessageLine(_blockReason!),
          if (_visibleError(context) case final String error)
            _MessageLine(error),
          if (_notice != null) _MessageLine(_notice!, danger: false),
          const SizedBox(height: MayosSpacing.lg),
          MayosButton(
            key: const ValueKey<String>('logger.save'),
            label: actionLabel,
            icon: action == _SummaryAction.discardWorkout
                ? Icons.delete_outline
                : Icons.check,
            loading: _saving,
            onPressed: _saving || _blockReason != null ? null : actionHandler,
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
            _copy.personalRecords,
            style: MayosTypography.of(context).exerciseTitle.copyWith(color: c.accent),
          ),
          const SizedBox(height: MayosSpacing.xs),
          for (final WorkoutRecord record in records)
            Padding(
              padding: const EdgeInsets.only(bottom: MayosSpacing.xxs),
              child: Text(
                workoutCopyOf(context).recordCelebration(
                  record.exerciseName,
                  record.kind,
                  formatRecordKg(record.value),
                ),
                style: MayosTypography.of(context).bodySecondary.copyWith(
                  color: c.textPrimary,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _readinessHeader() {
    if (!_copy.isArabic) {
      return MayosSectionHeader(title: _copy.readinessOutOfFive(_readiness));
    }
    final TextStyle? style = Theme.of(context).textTheme.headlineSmall;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text.rich(
              TextSpan(
                text: '${_copy.readiness}: ',
                children: <InlineSpan>[
                  WidgetSpan(
                    alignment: PlaceholderAlignment.baseline,
                    baseline: TextBaseline.alphabetic,
                    child: Directionality(
                      textDirection: TextDirection.ltr,
                      child: Text('$_readiness/5', style: style),
                    ),
                  ),
                ],
              ),
              style: style,
            ),
          ),
        ],
      ),
    );
  }

  Widget _checkpointCelebration() {
    final MayosThemeExtension c = MayosTheme.of(context);
    final int checkpoint = _checkpointNumber!;
    final CheckpointReview? review = _checkpointReview;
    return MayosCard(
      key: const ValueKey<String>('logger.summary.checkpoint'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            workoutCopyOf(context).checkpointWorkout(checkpoint),
            style: MayosTypography.of(context).exerciseTitle.copyWith(color: c.accent),
          ),
          const SizedBox(height: MayosSpacing.xs),
          if (review == null) ...<Widget>[
            Text(workoutCopyOf(context).reviewWillAppear),
          ] else ...<Widget>[
            Text(review.text),
            for (final CheckpointRatingPart part in review.rating)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.xs),
                child: Text('${part.part}: ${part.label}'),
              ),
          ],
        ],
      ),
    );
  }

  /// The core stats the summary shows: exercises done, ticked working sets,
  /// total volume over those sets (#124) and the workout's total duration
  /// (#159). Two rows of two, so a duration like `1:05:09` still fits the
  /// 360dp minimum without shrinking the figures.
  Widget _buildStats(WorkoutSummary summary) {
    final WorkoutSummaryStats stats = summary.stats;
    final WorkoutCopy copy = _copy;
    Widget stat({
      Key? key,
      required String value,
      required String label,
      String? unit,
    }) {
      final MayosStat child = MayosStat(
        key: key,
        value: value,
        label: label,
        unit: unit,
        alignment: CrossAxisAlignment.start,
      );
      return child;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: stat(
                value: '${stats.exercisesDone}',
                label: copy.exercisesDone,
              ),
            ),
            Expanded(
              child: stat(
                value: '${stats.workingSets}',
                label: copy.workingSets,
              ),
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.md),
        Row(
          children: <Widget>[
            Expanded(
              child: stat(
                value: stats.volumeLabel,
                label: copy.totalVolume,
                unit: 'kg',
              ),
            ),
            Expanded(
              child: stat(
                key: const ValueKey<String>('logger.summary.duration'),
                value: formatWorkoutTime(summary.duration),
                label: copy.duration,
              ),
            ),
          ],
        ),
        if (stats.cardioMinutes != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Row(
            children: <Widget>[
              Expanded(
                child: stat(
                  key: const ValueKey<String>('logger.summary.cardio'),
                  value: '${stats.cardioMinutes}',
                  label: copy.cardio,
                  unit: copy.minutesUnit,
                ),
              ),
              const Expanded(child: SizedBox.shrink()),
            ],
          ),
        ],
      ],
    );
  }

  Widget _buildTrainingStatus(List<TrainingStatusSummaryLine> lines) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutCopy copy = _copy;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          for (int index = 0; index < lines.length; index++)
            Padding(
              padding: EdgeInsets.only(
                bottom: index == lines.length - 1 ? 0 : MayosSpacing.xs,
              ),
              child: Text(
                copy.trainingStatusLine(lines[index]),
                key: ValueKey<String>('logger.summary.training.$index'),
                textAlign: copy.isArabic ? TextAlign.end : null,
                style: MayosTypography.of(context).bodySecondary.copyWith(
                  color: c.textPrimary,
                ),
              ),
            ),
        ],
      ),
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
        style: MayosTypography.of(context).bodySecondary.copyWith(
          color: danger ? c.danger : c.textSecondary,
        ),
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
        horizontal: MayosSpacing.md,
        vertical: MayosSpacing.sm,
      ),
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
              workoutCopyOf(context).offlineCachedProgram,
              style: MayosTypography.of(context).bodySecondary.copyWith(
                color: c.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
