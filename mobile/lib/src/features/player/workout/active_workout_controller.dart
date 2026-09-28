import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/active_workout.dart';
import '../../../core/baseline_service.dart';
import '../../../core/baselines.dart';
import '../../../core/models.dart';

/// Why [ActiveWorkoutController.startFromDay] refused to start: there is at
/// most one Active workout per account, so a second start must first be
/// finished or discarded (#123).
enum StartWorkoutOutcome {
  /// A new Active workout was created and persisted.
  started,

  /// An Active workout already exists; the caller must offer Resume/Discard.
  activeExists,
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
    DateTime Function()? now,
    String Function()? newId,
  })  : _store = store,
        _baselines = baselines,
        _now = now ?? DateTime.now,
        _newId = newId ?? _fallbackId,
        super(const ActiveWorkoutState(
          accountId: null,
          ready: true,
          workout: null,
        ));

  final ActiveWorkoutStore _store;
  final BaselinesService _baselines;
  final DateTime Function() _now;
  final String Function() _newId;

  /// Invalidates an in-flight store read when the account changes (#119
  /// pattern), so a late read never overwrites a newer account's state.
  int _epoch = 0;

  /// The in-flight restore for one account, so a second sync while it runs
  /// awaits the same read instead of starting a racing one.
  Future<void>? _pendingRestore;
  String? _pendingRestoreFor;

  static String _fallbackId() =>
      'aw-${DateTime.now().microsecondsSinceEpoch}';

  bool get hasActive => state.workout != null;

  ActiveWorkout? get workout => state.workout;

  /// Re-reads the stored Active workout whenever the session's account
  /// changes, mirroring [AppModeController.syncAccount] (#119).
  Future<void> syncAccount(String? accountId) async {
    if (accountId == null) {
      _epoch++;
      _pendingRestore = null;
      _pendingRestoreFor = null;
      state = const ActiveWorkoutState(
          accountId: null, ready: true, workout: null);
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
    state = ActiveWorkoutState(accountId: accountId, ready: false, workout: null);
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

  /// Starts a workout from [day]: resolves and freezes the baselines, seeds
  /// the planned set rows, and persists. Returns [StartWorkoutOutcome
  /// .activeExists] when an Active workout already exists, so the caller can
  /// offer Resume / Discard first (#123).
  Future<StartWorkoutOutcome> startFromDay({
    required String accountId,
    required ProgramDay day,
    required int? programVersion,
    Prescription? prescription,
  }) async {
    await syncAccount(accountId);
    if (state.workout != null) {
      return StartWorkoutOutcome.activeExists;
    }
    final BaselineResolution resolution =
        await _baselines.resolveForStart(accountId);
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

  /// Discards the Active workout: clears the state and the stored copy (#123).
  Future<void> discard() async {
    final ActiveWorkout? current = state.workout;
    state = ActiveWorkoutState(
      accountId: state.accountId,
      ready: state.ready,
      workout: null,
    );
    final String? accountId = current?.accountId;
    if (accountId == null) {
      return;
    }
    try {
      await _store.deleteForAccount(accountId);
    } on Object {
      // Best-effort, like the other protected stores; state already shows none.
    }
  }

  /// Appends a set copied from the row above it (the logger's "Add set").
  Future<void> addSet(int exerciseIndex) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null) {
      return;
    }
    final ActiveWorkoutSet? last =
        exercise.sets.isEmpty ? null : exercise.sets.last;
    final ActiveWorkoutSet added = last == null
        ? const ActiveWorkoutSet()
        : ActiveWorkoutSet(
            weightKg: last.weightKg,
            reps: last.reps,
            rir: last.rir,
          );
    await _replaceExercise(
      exerciseIndex,
      exercise.copyWith(sets: <ActiveWorkoutSet>[...exercise.sets, added]),
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
    final List<ActiveWorkoutSet> sets =
        List<ActiveWorkoutSet>.of(exercise.sets)..removeAt(setIndex);
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
  }) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || !_validSet(exercise, setIndex)) {
      return;
    }
    final List<ActiveWorkoutSet> sets =
        List<ActiveWorkoutSet>.of(exercise.sets);
    sets[setIndex] = sets[setIndex].copyWith(
      weightKg: weightKg,
      reps: reps,
      rir: rir,
      clearRir: unrated,
    );
    await _replaceExercise(exerciseIndex, exercise.copyWith(sets: sets));
  }

  /// Toggles a set row between working and warm-up (`N ↔ W`); warm-ups never
  /// count as working sets.
  Future<void> toggleWarmup(int exerciseIndex, int setIndex) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || !_validSet(exercise, setIndex)) {
      return;
    }
    final List<ActiveWorkoutSet> sets =
        List<ActiveWorkoutSet>.of(exercise.sets);
    final ActiveWorkoutSet set = sets[setIndex];
    sets[setIndex] = set.copyWith(isWarmup: !set.isWarmup);
    await _replaceExercise(exerciseIndex, exercise.copyWith(sets: sets));
  }

  /// Ticks or unticks a set row; only ticked rows reach the Workout draft.
  Future<void> setTicked(
      int exerciseIndex, int setIndex, bool ticked) async {
    final ActiveWorkoutExercise? exercise = _exerciseAt(exerciseIndex);
    if (exercise == null || !_validSet(exercise, setIndex)) {
      return;
    }
    final List<ActiveWorkoutSet> sets =
        List<ActiveWorkoutSet>.of(exercise.sets);
    sets[setIndex] = sets[setIndex].copyWith(ticked: ticked);
    await _replaceExercise(exerciseIndex, exercise.copyWith(sets: sets));
  }

  /// Appends an unplanned exercise with the same three starter rows and
  /// `ProgramExerciseSchema` payload the logger builds today.
  Future<void> addUnplannedExercise({
    required String exerciseId,
    required String exerciseName,
  }) async {
    final ActiveWorkout? current = state.workout;
    if (current == null) {
      return;
    }
    final ActiveWorkoutExercise added = ActiveWorkoutExercise(
      exercise: <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'target_sets': 3,
        'target_reps_min': 8,
        'target_reps_max': 12,
        'target_rpe': 8.0,
        'rest_seconds': 120,
        'notes': null,
      },
      sets: <ActiveWorkoutSet>[
        for (int i = 0; i < 3; i++)
          const ActiveWorkoutSet(weightKg: 0, reps: 8, rir: 2.0),
      ],
      unplanned: true,
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

  /// Applies [workout] to the state first, then persists it, so the UI always
  /// reflects the change even if protected storage is briefly unavailable.
  Future<void> _persist(ActiveWorkout workout) async {
    if (mounted) {
      state = ActiveWorkoutState(
        accountId: workout.accountId,
        ready: true,
        workout: workout,
        // A workout the player just started is not a resume candidate.
        restoredFromDevice: false,
      );
    }
    try {
      await _store.write(workout.accountId, workout);
    } on Object {
      // Persistence is best-effort, like AppModeStore; the in-memory
      // workout still applies.
    }
  }

  /// Seeds one planned exercise's rows exactly the way the logger seeds them
  /// from the day and its prescription (#123).
  static ActiveWorkoutExercise _seedExercise(
      ProgramExercise exercise, Prescription? prescription) {
    final PrescriptionTarget? target =
        prescription?.forExercise(exercise.exerciseId);
    final double weight = target?.projectedWeight ?? 0;
    final double rpe = target?.targetRpeCap ?? exercise.targetRpe;
    final int setCount = target?.effectiveSets ?? exercise.targetSets;
    // The logger seeds the RPE the prescription asks for; the row stores the
    // equivalent RIR (10 - RPE, inside the service's accepted [6, 10] RPE
    // band, i.e. RIR [0, 4]).
    double rir = 10.0 - rpe;
    if (rir < 0.0) {
      rir = 0.0;
    } else if (rir > 4.0) {
      rir = 4.0;
    }
    return ActiveWorkoutExercise(
      exercise: exercise.toJson(),
      targetLabel: exercise.prescription,
      sets: <ActiveWorkoutSet>[
        for (int i = 0; i < setCount; i++)
          ActiveWorkoutSet(
              weightKg: weight, reps: exercise.targetRepsMin, rir: rir),
      ],
    );
  }
}
