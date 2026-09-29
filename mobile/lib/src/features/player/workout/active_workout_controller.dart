import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/active_workout.dart';
import '../../../core/api_client.dart';
import '../../../core/baseline_service.dart';
import '../../../core/baselines.dart';
import '../../../core/models.dart';
import '../../../core/rest_alerts.dart';
import '../../../core/rest_length.dart';
import '../../../core/workout_storage.dart';

/// The workout-start prescription (#123 item 4): a fresh
/// `GET /workouts/prescription` inside [timeout], written back to the
/// per-account cache on success, otherwise whatever the cache already holds —
/// the order the old logger used, bounded so a slow network never blocks
/// starting a workout.
Future<Prescription?> prescriptionAtStart({
  required ApiClient api,
  required WorkoutCacheStore cache,
  required String accountId,
  required int dayOrder,
  Duration timeout = const Duration(seconds: 5),
}) async {
  try {
    final Prescription fresh =
        await api.prescription(dayOrder).timeout(timeout);
    try {
      await cache.writePrescription(accountId, dayOrder, fresh);
    } on Object {
      // A cache failure must not lose the fresh prescription.
    }
    return fresh;
  } on Object {
    try {
      return await cache.readPrescription(accountId, dayOrder);
    } on Object {
      return null;
    }
  }
}

/// Why [ActiveWorkoutController.startFromDay] refused to start: there is at
/// most one Active workout per account, so a second start must first be
/// finished or discarded (#123).
enum StartWorkoutOutcome {
  /// A new Active workout was created and persisted.
  started,

  /// An Active workout already exists; the caller must offer Resume/Discard.
  activeExists,

  /// The account signed out or changed while the start was resolving its
  /// baseline, so nothing was created or persisted for it.
  aborted,
}

/// The signed-in account's Active workout, plus how far its store read has
/// got ([ready] is false while the stored workout is still being read, so a
/// start can never race the restore).
class ActiveWorkoutState {
  const ActiveWorkoutState({
    required this.accountId,
    required this.ready,
    required this.workout,
    this.restoredFromDevice = false,
  });

  final String? accountId;
  final bool ready;
  final ActiveWorkout? workout;

  /// True when [workout] came from the device store at sign-in — the case the
  /// app-open prompt offers Resume/Discard for. A workout the player just
  /// started sets it false, so starting one never re-triggers the offer.
  final bool restoredFromDevice;

  bool get hasWorkout => workout != null;

  @override
  bool operator ==(Object other) =>
      other is ActiveWorkoutState &&
      other.accountId == accountId &&
      other.ready == ready &&
      other.workout == workout &&
      other.restoredFromDevice == restoredFromDevice;

  @override
  int get hashCode =>
      Object.hash(accountId, ready, workout, restoredFromDevice);
}

/// Owns the single Active workout of the signed-in account: restores it on
/// sign-in, creates it from a program day (resolving and freezing the
/// baseline), applies every set-row change by persisting after each one, and
/// discards it.
///
/// The set-row operations are the seam the table logger drives; the draft the
/// finish step saves comes from [ActiveWorkout.buildWorkoutDraft].
class ActiveWorkoutController extends StateNotifier<ActiveWorkoutState> {
  ActiveWorkoutController({
    required ActiveWorkoutStore store,
    required BaselinesService baselines,
    Future<Prescription?> Function(String accountId, int dayOrder)?
        loadPrescription,
    DateTime Function()? now,
    String Function()? newId,
    RestLengthStore? restLengths,
    RestAlerts? alerts,
  })  : _store = store,
        _baselines = baselines,
        _loadPrescription = loadPrescription,
        _now = now ?? DateTime.now,
        _newId = newId ?? _fallbackId,
        _restLengths = restLengths,
        _alerts = alerts,
        super(const ActiveWorkoutState(
          accountId: null,
          ready: true,
          workout: null,
        ));

  final ActiveWorkoutStore _store;
  final BaselinesService _baselines;

  /// Fresh `GET /workouts/prescription` with a short timeout, else the cached
  /// prescription — how the old logger resolved it (#123 item 4).
  final Future<Prescription?> Function(String accountId, int dayOrder)?
      _loadPrescription;
  final DateTime Function() _now;
  final String Function() _newId;

  /// The player's per-exercise rest overrides for this account, loaded with
  /// the workout and written back on every change (#125). Null in builds or
  /// tests that do not wire the store; the defaults still resolve.
  final RestLengthStore? _restLengths;

  /// The one seam to the platform's notification/alarm/sound layer (#125).
  final RestAlerts? _alerts;

  /// The overrides of the signed-in account, keyed by exercise id.
  Map<String, int> _restOverrides = const <String, int>{};

  /// True while the platform layer shows or schedules anything for this
  /// workout, so sign-out and discard cancel only when there is something to
  /// cancel (#125).
  bool _alertsLive = false;

  /// True from the Finish summary until Back, so the lock-screen notification
  /// and alarm are off during the summary and come back if the player
  /// returns (#125).
  bool _alertsSuspended = false;

  /// `<workout id>:<rest end time>` of the rest this controller already ended.
  /// The ticker, a late return to the logger, and a restore can all reach
  /// [completeRest] for the same rest; only the first one may alert (#125).
  String? _endedRest;

  /// The end time whose platform alarm the foreground ticker already dropped
  /// (see [dropImminentEndAlarm]); re-armed by every re-schedule (#125).
  String? _droppedEndFor;

  /// How long after its end time a rest may still alert in-app: within this
  /// window the ticker was clearly counting down with the player; any later
  /// and the rest ended while the app was away, where the platform alarm has
  /// already had its say (#125).
  static const Duration _endAlertGrace = Duration(seconds: 2);

  /// Invalidates an in-flight store read when the account changes (#119
  /// pattern), so a late read never overwrites a newer account's state.
  int _epoch = 0;

  /// The in-flight restore for one account, so a second sync while it runs
  /// awaits the same read instead of starting a racing one.
  Future<void>? _pendingRestore;
  String? _pendingRestoreFor;

  /// Every store write and delete runs through this single chain, so writes
  /// land in the order the state changed (the latest state wins) and a
  /// discard/save can wait for the pending writes before it deletes (#123
  /// item 5). Failures are swallowed inside the link, so the chain never
  /// breaks.
  Future<void> _writeChain = Future<void>.value();

  static String _fallbackId() => 'aw-${DateTime.now().microsecondsSinceEpoch}';

  bool get hasActive => state.workout != null;

  ActiveWorkout? get workout => state.workout;

  /// Re-reads the stored Active workout whenever the session's account
  /// changes, mirroring [AppModeController.syncAccount] (#119).
  Future<void> syncAccount(String? accountId) async {
    if (accountId == null) {
      _epoch++;
      _pendingRestore = null;
      _pendingRestoreFor = null;
      state =
          const ActiveWorkoutState(accountId: null, ready: true, workout: null);
      _restOverrides = const <String, int>{};
      // A signed-out account's countdown must not outlive its session (#125).
      if (_alertsLive) {
        _alertsLive = false;
        _alertsSuspended = false;
        await _removeAlerts();
      }
      return;
    }
    if (accountId == state.accountId && state.ready) {
      return;
    }
    // Switching straight to another account takes A's countdown with it: its
    // lock-screen notification and alarm are removed exactly the way sign-out
    // does, and A's device rest overrides never leak into B (#125).
    if (state.accountId != null && state.accountId != accountId) {
      _restOverrides = const <String, int>{};
      if (_alertsLive) {
        _alertsLive = false;
        _alertsSuspended = false;
        await _removeAlerts();
      }
    }
    final Future<void>? inFlight = _pendingRestore;
    if (inFlight != null && _pendingRestoreFor == accountId) {
      return inFlight;
    }
    final int epoch = ++_epoch;
    state =
        ActiveWorkoutState(accountId: accountId, ready: false, workout: null);
    final Future<void> pending = _restore(accountId, epoch);
    _pendingRestore = pending;
    _pendingRestoreFor = accountId;
    try {
      await pending;
    } finally {
      if (identical(_pendingRestore, pending)) {
        _pendingRestore = null;
        _pendingRestoreFor = null;
      }
    }
  }

  Future<void> _restore(String accountId, int epoch) async {
    ActiveWorkout? stored;
    try {
      stored = await _store.read(accountId);
    } on Object {
      stored = null;
    }
    if (!mounted || epoch != _epoch) {
      return;
    }
    // The rest overrides load beside the restore rather than inside it: a
    // keystore that is slow (or unavailable, as on a test host) must never
    // hold the workout back, and any override picked while it was in flight
    // wins the merge (#125).
    unawaited(_loadRestOverrides(accountId, epoch));
    state = ActiveWorkoutState(
      accountId: accountId,
      ready: true,
      workout: stored,
      restoredFromDevice: stored != null,
    );
    // A stored countdown keeps running across a restart; one that already
    // elapsed while the app was closed is cleared without re-alerting — the
    // scheduled alarm has already fired (#125).
    final ActiveRestTimer? rest = stored?.rest;
    if (rest == null) {
      return;
    }
    if (rest.isOver(_now())) {
      _alertsLive = true;
      await completeRest(playAlert: false);
    } else {
      _alertsLive = true;
      _alertsSuspended = false;
      await _applyAlerts(rest, requestPermission: false);
    }
  }

  Future<void> _loadRestOverrides(String accountId, int epoch) async {
    final RestLengthStore? restLengths = _restLengths;
    if (restLengths == null) {
      return;
    }
    Map<String, int> loaded;
    try {
      loaded = await restLengths.read(accountId);
    } on Object {
      return;
    }
    if (!mounted || epoch != _epoch || state.accountId != accountId) {
      return;
    }
    _restOverrides = <String, int>{...loaded, ..._restOverrides};
  }

  /// Starts a workout from [day]: resolves the prescription and the baseline
  /// (freezing the latter), seeds the planned set rows, and persists. Returns
  /// [StartWorkoutOutcome.activeExists] when an Active workout already exists,
  /// so the caller can offer Resume / Discard first, and
  /// [StartWorkoutOutcome.aborted] when the account signed out or changed
  /// while the baseline was loading (#123 item 5).
  Future<StartWorkoutOutcome> startFromDay({
    required String accountId,
    required ProgramDay day,
    required int? programVersion,
  }) async {
    await syncAccount(accountId);
    if (state.workout != null) {
      return StartWorkoutOutcome.activeExists;
    }
    // Everything below resolves network/async work; an account change in the
    // middle of it (sign-out, switch) bumps [_epoch] and must never be
    // persisted for the account that is no longer signed in.
    final int epoch = _epoch;
    Future<Prescription?> prescriptionFuture = Future<Prescription?>.value();
    final Future<Prescription?> Function(String, int)? loadPrescription =
        _loadPrescription;
    if (loadPrescription != null) {
      prescriptionFuture = loadPrescription(accountId, day.dayOrder);
    }
    final BaselineResolution resolution =
        await _baselines.resolveForStart(accountId);
    if (!mounted || epoch != _epoch || state.accountId != accountId) {
      return StartWorkoutOutcome.aborted;
    }
    final Prescription? prescription = await prescriptionFuture;
    if (!mounted || epoch != _epoch || state.accountId != accountId) {
      return StartWorkoutOutcome.aborted;
    }
    // The store could have been written while the baseline resolved.
    await syncAccount(accountId);
    if (state.workout != null) {
      return StartWorkoutOutcome.activeExists;
    }
    final ActiveWorkout created = ActiveWorkout(
      id: _newId(),
      accountId: accountId,
      startedAt: _now().toUtc().toIso8601String(),
      dayOrder: day.dayOrder,
      dayName: day.dayName,
      programVersion: programVersion,
      exercises: <ActiveWorkoutExercise>[
        for (final ProgramExercise exercise in day.exercises)
          _seedExercise(exercise, prescription),
      ],
      baselines: <String, BaselineExercise>{
        for (final BaselineExercise baseline in resolution.baselines)
          baseline.exerciseId: baseline,
      },
    );
    await _persist(created);
    return StartWorkoutOutcome.started;
  }

  /// Discards the Active workout of [accountId]: clears the state and the
  /// stored copy, after every pending write has landed so a late write can
  /// never resurrect it (#123 item 5).
  ///
  /// [workoutId] narrows the discard to one workout; a caller that names the
  /// wrong account or workout gets a no-op instead of clearing a workout that
  /// is not theirs.
  Future<void> discard({required String accountId, String? workoutId}) async {
    final ActiveWorkout? current = state.workout;
    if (current == null ||
        current.accountId != accountId ||
        (workoutId != null && current.id != workoutId)) {
      return;
    }
    state = ActiveWorkoutState(
      accountId: state.accountId,
      ready: state.ready,
      workout: null,
    );
    // Discarding the workout removes its lock-screen notification and alarm
    // too (#125) — this covers both Discard and Finish-then-Save.
    if (_alertsLive) {
      _alertsLive = false;
      _alertsSuspended = false;
      await _removeAlerts();
    }
    try {
      await _enqueue(() => _store.deleteForAccount(accountId));
    } on Object {
      // Best-effort, like the other protected stores; state already shows none.
    }
  }

  /// Appends a new empty row (the logger's "+ Add set"): like the #107
  /// prototype, the row is blank and the table's hints fill it in.
  Future<void> addSet(int exerciseIndex) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null) {
      return;
    }
    await _replaceExercise(
      exerciseIndex,
      exercise.copyWith(sets: <ActiveWorkoutSet>[
        ...exercise.sets,
        ActiveWorkoutSet(),
      ]),
    );
  }

  /// Removes one set row; the last remaining row of an exercise is kept, the
  /// same guard the logger's remove button has.
  Future<void> removeSet(int exerciseIndex, int setIndex) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || exercise.sets.length <= 1) {
      return;
    }
    if (setIndex < 0 || setIndex >= exercise.sets.length) {
      return;
    }
    final List<ActiveWorkoutSet> sets = List<ActiveWorkoutSet>.of(exercise.sets)
      ..removeAt(setIndex);
    await _replaceExercise(exerciseIndex, exercise.copyWith(sets: sets));
  }

  /// Edits one cell: whichever of [weightKg] / [reps] / [rir] is non-null is
  /// applied (weight 0 and reps 0 are how a cell is cleared), and [unrated]
  /// clears the effort back to "not rated" (#111).
  Future<void> updateCell(
    int exerciseIndex,
    int setIndex, {
    double? weightKg,
    int? reps,
    double? rir,
    bool unrated = false,
  }) =>
      _updateSet(
          exerciseIndex,
          setIndex,
          (ActiveWorkoutSet set) => set.copyWith(
                weightKg: weightKg,
                reps: reps,
                rir: rir,
                clearRir: unrated,
              ));

  /// Toggles a set row between working and warm-up (`N ↔ W`); warm-ups never
  /// count as working sets.
  Future<void> toggleWarmup(int exerciseIndex, int setIndex) => _updateSet(
      exerciseIndex,
      setIndex,
      (ActiveWorkoutSet set) => set.copyWith(isWarmup: !set.isWarmup));

  /// Ticks or unticks a set row; only ticked rows reach the Workout draft.
  ///
  /// Ticking a *working* set starts (or restarts) the rest timer with that
  /// exercise's rest length — never for a warm-up, and never when the rest is
  /// Off (#125).
  Future<void> setTicked(int exerciseIndex, int setIndex, bool ticked) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || !_validSet(exercise, setIndex)) {
      return;
    }
    final bool wasWarmup = exercise.sets[setIndex].isWarmup;
    await _updateSet(exerciseIndex, setIndex,
        (ActiveWorkoutSet set) => set.copyWith(ticked: ticked));
    if (ticked && !wasWarmup) {
      await maybeStartRest(exerciseIndex, setIndex);
    }
  }

  /// Appends an unplanned exercise with the same three starter rows (empty,
  /// like the prototype) and `ProgramExerciseSchema` payload the logger builds
  /// today.
  Future<void> addUnplannedExercise({
    required String exerciseId,
    required String exerciseName,
  }) async {
    final ActiveWorkout? current = state.workout;
    if (current == null) {
      return;
    }
    final Map<String, dynamic> exercise = <String, dynamic>{
      'exercise_id': exerciseId,
      'exercise_name': exerciseName,
      'target_sets': 3,
      'target_reps_min': 8,
      'target_reps_max': 12,
      'target_rpe': 8.0,
      'rest_seconds': 120,
      'notes': null,
    };
    final ActiveWorkoutExercise added = ActiveWorkoutExercise(
      exercise: exercise,
      sets: <ActiveWorkoutSet>[
        for (int i = 0; i < 3; i++) ActiveWorkoutSet(),
      ],
      unplanned: true,
      prescriptionHint: _prescriptionHint(exercise, null),
    );
    await _persist(current.copyWith(
        exercises: <ActiveWorkoutExercise>[...current.exercises, added]));
  }

  // ---- rest timer (#125) ---------------------------------------------------

  /// The rest length exercise [exerciseIndex] uses right now: the player's
  /// device override when there is one, else the program's `rest_seconds`,
  /// else the flat 2:00 — a missing `rest_seconds` counting as unset.
  int restLengthFor(int exerciseIndex) {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null) {
      return kDefaultRestSeconds;
    }
    final int? program = (exercise.exercise['rest_seconds'] as num?)?.toInt();
    return resolveRestSeconds(
      programSeconds: program,
      overrideSeconds: _restOverrides[exercise.exerciseId],
    );
  }

  /// Remembers the player's rest choice for one exercise, per account on this
  /// device only ([seconds] 0 means Off). It overrides the default in later
  /// workouts and is never sent to the server (#125).
  Future<void> setRestLength(int exerciseIndex, int seconds) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    final String? accountId = state.accountId;
    if (exercise == null || accountId == null) {
      return;
    }
    _restOverrides = <String, int>{
      ..._restOverrides,
      exercise.exerciseId: seconds,
    };
    final RestLengthStore? store = _restLengths;
    if (store != null) {
      // Detached, like the other best-effort persistence: a keystore that
      // never answers (a test host) must not block the picker (#125).
      unawaited(
          store.write(accountId, _restOverrides).catchError((Object _) {}));
    }
  }

  /// Starts (or restarts) the rest timer for a just-ticked working set of
  /// [exerciseIndex], with that exercise's resolved rest length. A warm-up
  /// and an Off rest leave any running timer alone and start nothing (#125).
  Future<void> maybeStartRest(int exerciseIndex, int setIndex) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    final ActiveWorkout? current = state.workout;
    if (exercise == null || !_validSet(exercise, setIndex) || current == null) {
      return;
    }
    final ActiveWorkoutSet set = exercise.sets[setIndex];
    if (set.isWarmup) {
      return;
    }
    final int seconds = restLengthFor(exerciseIndex);
    if (seconds <= 0) {
      return;
    }
    final ActiveRestTimer rest = ActiveRestTimer(
      endsAt: _now().add(Duration(seconds: seconds)).toUtc().toIso8601String(),
      totalSeconds: seconds,
      exerciseId: exercise.exerciseId,
      exerciseName: exercise.exerciseName,
      setNumber: setIndex + 1,
      lastLabel:
          set.reps > 0 || set.weightKg > 0 ? setPerformanceLabel(set) : null,
    );
    await _persist(current.copyWith(rest: rest));
    _alertsLive = true;
    _alertsSuspended = false;
    // The permission is asked once, the first time a rest timer starts (#125).
    await _applyAlerts(rest, requestPermission: true);
  }

  /// Moves the running rest's end time by [delta] (the bar's −15 / +15) and
  /// re-posts the notification and alarm (#125). No-op when nothing runs.
  Future<void> adjustRest(Duration delta) async {
    final ActiveWorkout? current = state.workout;
    final ActiveRestTimer? rest = current?.rest;
    if (current == null || rest == null) {
      return;
    }
    DateTime ends = rest.endsAtClock.add(delta);
    final DateTime now = _now();
    if (ends.isBefore(now)) {
      ends = now;
    }
    final ActiveRestTimer next =
        rest.copyWith(endsAt: ends.toUtc().toIso8601String());
    await _persist(current.copyWith(rest: next));
    if (!_alertsSuspended) {
      await _applyAlerts(next, requestPermission: false);
    }
  }

  /// Ends the rest early: clears it from the workout and removes the
  /// notification and alarm (#125).
  Future<void> skipRest() async {
    final ActiveWorkout? current = state.workout;
    if (current == null || current.rest == null) {
      return;
    }
    await _persist(current.copyWith(clearRest: true));
    if (_alertsLive) {
      _alertsLive = false;
      _alertsSuspended = false;
      await _removeAlerts();
    }
  }

  /// The rest ran out (the in-app ticker reached the end time): clears it,
  /// removes the notification and alarm, and plays the in-app vibration and
  /// sound (#125). [playAlert] is false when a stored rest is cleared on
  /// restore, where the alarm has already had its say.
  ///
  /// Ends at most once per rest: the ticker, a late return to the logger and
  /// a restore all reach here for the same end time, and only the first call
  /// touches the seam. A rest that ended more than [_endAlertGrace] ago is
  /// cleared *silently* — it ended while the app was away, where the
  /// scheduled alarm already alerted (#125).
  Future<void> completeRest({bool playAlert = true}) async {
    final ActiveWorkout? current = state.workout;
    final ActiveRestTimer? rest = current?.rest;
    if (current == null || rest == null) {
      return;
    }
    final String ended = '${current.id}:${rest.endsAt}';
    if (_endedRest == ended) {
      return;
    }
    _endedRest = ended;
    final RestAlertInfo info = _alertInfo(rest);
    final bool late = _now().difference(rest.endsAtClock) > _endAlertGrace;
    await _persist(current.copyWith(clearRest: true));
    if (_alertsLive) {
      _alertsLive = false;
      _alertsSuspended = false;
      await _removeAlerts();
    }
    if (playAlert && !late) {
      final RestAlerts? alerts = _alerts;
      if (alerts != null) {
        try {
          await alerts.playEnd(info);
        } on Object {
          // Best-effort; a missing vibration channel must not break the tick.
        }
      }
    }
  }

  /// The rest is within its last second while the logger is open: drop the
  /// platform alarm now, so the foreground ticker is the only thing that ends
  /// this rest — the alarm must not fire a second "Rest complete" right after
  /// the in-app one (#125). Driven by the logger's ticker, at most once per
  /// end time; a ±15 (or Back from the summary) re-schedules the alarm and
  /// re-arms the drop for the new end time.
  Future<void> dropImminentEndAlarm() async {
    final ActiveRestTimer? rest = state.workout?.rest;
    if (rest == null || !_alertsLive || _alertsSuspended) {
      return;
    }
    if (rest.remainingSeconds(_now()) > 1 || _droppedEndFor == rest.endsAt) {
      return;
    }
    _droppedEndFor = rest.endsAt;
    final RestAlerts? alerts = _alerts;
    if (alerts == null) {
      return;
    }
    try {
      await alerts.cancelEnd();
    } on Object {
      // Best-effort (#125).
    }
  }

  /// The Finish summary replaces the workout: the lock-screen notification
  /// and alarm are removed while it is open (#125 "removed on Finish").
  Future<void> suspendRestAlerts() async {
    if (!_alertsLive || _alertsSuspended) {
      return;
    }
    _alertsSuspended = true;
    await _removeAlerts();
  }

  /// Back from the summary to a still-running rest: the notification and
  /// alarm come back (#125).
  Future<void> restoreRestAlerts() async {
    final ActiveRestTimer? rest = state.workout?.rest;
    if (!_alertsLive || !_alertsSuspended || rest == null) {
      return;
    }
    _alertsSuspended = false;
    await _applyAlerts(rest, requestPermission: false);
  }

  /// The platform calls for one running rest: the one-time permission ask on
  /// first start, then the ongoing notification and the end alarm. Each call
  /// is isolated so a plugin failure never breaks a workout (#125).
  Future<void> _applyAlerts(ActiveRestTimer rest,
      {required bool requestPermission}) async {
    final RestAlerts? alerts = _alerts;
    if (alerts == null || _alertsSuspended) {
      return;
    }
    final RestAlertInfo info = _alertInfo(rest);
    if (requestPermission) {
      try {
        await alerts.ensureReady();
      } on Object {
        // A refused or unavailable permission never blocks the rest (#125).
      }
    }
    try {
      await alerts.showRest(info);
    } on Object {
      // Best-effort: the platform layer is never load-bearing (#125).
    }
    try {
      // Every (re)schedule arms the foreground drop again for this end time.
      _droppedEndFor = null;
      await alerts.scheduleEnd(info);
    } on Object {
      // Best-effort: the in-app ticker still ends the rest (#125).
    }
  }

  Future<void> _removeAlerts() async {
    final RestAlerts? alerts = _alerts;
    if (alerts == null) {
      return;
    }
    try {
      await alerts.removeRest();
    } on Object {
      // Best-effort (#125).
    }
    try {
      await alerts.cancelEnd();
    } on Object {
      // Best-effort (#125).
    }
  }

  /// The platform's view of the running rest: when it ends, plus the second
  /// line that always describes the NEXT set to do — the next unticked row of
  /// the exercise the rest started on, else the first unticked row of a later
  /// exercise — with *that* row's previous value from the frozen baseline as
  /// its "last", omitted when there is none (#125). Only when every row is
  /// ticked does it fall back to the row that started the rest.
  RestAlertInfo _alertInfo(ActiveRestTimer rest) {
    final ActiveWorkout? current = state.workout;
    RestAlertInfo origin() => RestAlertInfo(
          endsAt: rest.endsAtClock,
          totalSeconds: rest.totalSeconds,
          exerciseName: rest.exerciseName,
          setNumber: rest.setNumber,
          lastLabel: rest.lastLabel,
        );
    if (current == null) {
      return origin();
    }
    final ({ActiveWorkoutExercise exercise, int setIndex})? next =
        _nextSetAfter(current, rest);
    if (next == null) {
      return origin();
    }
    final BaselineSet? previous =
        previousSetFor(next.exercise, next.setIndex, current.baselines);
    return RestAlertInfo(
      endsAt: rest.endsAtClock,
      totalSeconds: rest.totalSeconds,
      exerciseName: next.exercise.exerciseName,
      setNumber: next.setIndex + 1,
      lastLabel: previous == null ? null : previousLabel(previous),
    );
  }

  /// The next unticked row after the one [rest] started on: the rest of that
  /// exercise first, then the first unticked row of every later exercise.
  /// Null when the workout has nothing left to tick (#125).
  static ({ActiveWorkoutExercise exercise, int setIndex})? _nextSetAfter(
    ActiveWorkout workout,
    ActiveRestTimer rest,
  ) {
    final int exerciseIndex = workout.exercises.indexWhere(
        (ActiveWorkoutExercise e) => e.exerciseId == rest.exerciseId);
    if (exerciseIndex < 0) {
      return null;
    }
    // rest.setNumber is the 1-based row that started the rest, so the row
    // after it is the one at that index.
    final ActiveWorkoutExercise started = workout.exercises[exerciseIndex];
    for (int i = rest.setNumber; i < started.sets.length; i++) {
      if (!started.sets[i].ticked) {
        return (exercise: started, setIndex: i);
      }
    }
    for (int e = exerciseIndex + 1; e < workout.exercises.length; e++) {
      final ActiveWorkoutExercise exercise = workout.exercises[e];
      final int setIndex =
          exercise.sets.indexWhere((ActiveWorkoutSet set) => !set.ticked);
      if (setIndex >= 0) {
        return (exercise: exercise, setIndex: setIndex);
      }
    }
    return null;
  }

  ActiveWorkoutExercise? _exerciseAt(int exerciseIndex) {
    final ActiveWorkout? current = state.workout;
    if (current == null ||
        exerciseIndex < 0 ||
        exerciseIndex >= current.exercises.length) {
      return null;
    }
    return current.exercises[exerciseIndex];
  }

  static bool _validSet(ActiveWorkoutExercise exercise, int setIndex) =>
      setIndex >= 0 && setIndex < exercise.sets.length;

  /// The one place every set-row mutation goes through: [fn] maps the current
  /// row to its next value and the result is persisted (#123 item 12).
  Future<void> _updateSet(
    int exerciseIndex,
    int setIndex,
    ActiveWorkoutSet Function(ActiveWorkoutSet set) fn,
  ) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || !_validSet(exercise, setIndex)) {
      return;
    }
    final List<ActiveWorkoutSet> sets =
        List<ActiveWorkoutSet>.of(exercise.sets);
    sets[setIndex] = fn(sets[setIndex]);
    await _replaceExercise(exerciseIndex, exercise.copyWith(sets: sets));
  }

  Future<void> _replaceExercise(
      int exerciseIndex, ActiveWorkoutExercise exercise) async {
    final ActiveWorkout? current = state.workout;
    if (current == null) {
      return;
    }
    final List<ActiveWorkoutExercise> exercises =
        List<ActiveWorkoutExercise>.of(current.exercises);
    exercises[exerciseIndex] = exercise;
    await _persist(current.copyWith(exercises: exercises));
  }

  /// Applies [workout] to the state first, then queues its store write, so the
  /// UI always reflects the change even if protected storage is briefly
  /// unavailable. Writes run one after another on [_writeChain], so the last
  /// state written is the last state stored (#123 item 5).
  Future<void> _persist(ActiveWorkout workout) {
    if (mounted) {
      state = ActiveWorkoutState(
        accountId: workout.accountId,
        ready: true,
        workout: workout,
        // A workout the player just started is not a resume candidate.
        restoredFromDevice: false,
      );
    }
    return _enqueue(() => _store.write(workout.accountId, workout));
  }

  /// Appends [action] to the single write chain and returns its future, so a
  /// caller can wait for every already-queued write plus this one (#123 item
  /// 5). Storage failures are swallowed inside the link: persistence is
  /// best-effort, like `AppModeStore`, and one failed write must not break the
  /// chain for the writes after it.
  Future<void> _enqueue(Future<void> Function() action) {
    final Future<void> next =
        _writeChain.then<void>((_) => action()).catchError((Object _) {});
    _writeChain = next;
    return next;
  }

  /// Seeds one planned exercise: as many empty rows as the day (or the fresh
  /// prescription) prescribes, the card's caption, and the prescription hint
  /// the empty cells fall back to (#123 item 2).
  static ActiveWorkoutExercise _seedExercise(
      ProgramExercise exercise, Prescription? prescription) {
    final PrescriptionTarget? target =
        prescription?.forExercise(exercise.exerciseId);
    final int setCount = target?.effectiveSets ?? exercise.targetSets;
    final PrescriptionHint? hint = _prescriptionHint(exercise.toJson(), target);
    return ActiveWorkoutExercise(
      exercise: exercise.toJson(),
      // #108: the caption keeps the effective prescription and the frozen
      // projection — what the rows were actually seeded from — not the raw
      // program target the card might otherwise contradict.
      targetLabel: prescriptionCaption(
        setCount: setCount,
        minReps: exercise.targetRepsMin,
        maxReps: exercise.targetRepsMax,
        projectedWeightKg: hint?.weightKg,
        rir: hint?.rir,
      ),
      sets: <ActiveWorkoutSet>[
        for (int i = 0; i < setCount; i++) ActiveWorkoutSet(),
      ],
      prescriptionHint: hint,
      effectiveSets: setCount,
    );
  }

  /// The prescription target an empty cell shows as its faded hint when there
  /// is no previous set: the projected weight (when the prescription projects
  /// one), the target rep floor, and the target RPE cap as its equivalent
  /// minimum RIR (the *least* RIR the set may leave, read as `≥ n` by the cell)
  /// — the effort at the display boundary, inside the service's accepted RPE
  /// 5–10 band (#111).
  static PrescriptionHint? _prescriptionHint(
    Map<String, dynamic> exercise,
    PrescriptionTarget? target,
  ) {
    final double projected = target?.projectedWeight ?? 0;
    final int reps = (exercise['target_reps_min'] as num?)?.toInt() ?? 0;
    final double rpe = target?.targetRpeCap ??
        (exercise['target_rpe'] as num?)?.toDouble() ??
        8.5;
    return PrescriptionHint(
      weightKg: projected > 0 ? projected : null,
      reps: reps > 0 ? reps : null,
      rir: rirFromRpe(clampRpe(rpe)),
    );
  }
}
