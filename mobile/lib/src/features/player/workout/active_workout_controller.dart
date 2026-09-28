import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/active_workout.dart';
import '../../../core/api_client.dart';
import '../../../core/baseline_service.dart';
import '../../../core/baselines.dart';
import '../../../core/models.dart';
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
  })  : _store = store,
        _baselines = baselines,
        _loadPrescription = loadPrescription,
        _now = now ?? DateTime.now,
        _newId = newId ?? _fallbackId,
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
      return;
    }
    if (accountId == state.accountId && state.ready) {
      return;
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
    state = ActiveWorkoutState(
      accountId: accountId,
      ready: true,
      workout: stored,
      restoredFromDevice: stored != null,
    );
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
  /// clears the effort back to "unrated" (#111).
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
  Future<void> setTicked(int exerciseIndex, int setIndex, bool ticked) =>
      _updateSet(exerciseIndex, setIndex,
          (ActiveWorkoutSet set) => set.copyWith(ticked: ticked));

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
    return ActiveWorkoutExercise(
      exercise: exercise.toJson(),
      targetLabel: exercise.prescription,
      sets: <ActiveWorkoutSet>[
        for (int i = 0; i < setCount; i++) ActiveWorkoutSet(),
      ],
      prescriptionHint: _prescriptionHint(exercise.toJson(), target),
    );
  }

  /// The prescription target an empty cell shows as its faded hint when there
  /// is no previous set: the projected weight (when the prescription projects
  /// one), the target rep floor, and the target RPE as RIR — the effort at the
  /// display boundary, inside the service's accepted [6, 10] RPE band (#111).
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
      rir: 10.0 - clampRpe(rpe),
    );
  }
}
