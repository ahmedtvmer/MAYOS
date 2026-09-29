import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'baselines.dart';
import 'effort.dart';
import 'models.dart';
import 'performed_date_window.dart';
import 'secure_store.dart';

int _setSequence = 0;

/// A fresh identity for one set row (#123 item 3).
///
/// Rows keep their id for the life of the workout — across edits, restores,
/// and re-serialization — so the table's swipe-to-delete `Dismissible` is
/// keyed by the row itself rather than by its position, which shifts whenever
/// an earlier row is removed.
String newActiveWorkoutSetId() {
  _setSequence += 1;
  return 'set-${DateTime.now().microsecondsSinceEpoch}-$_setSequence';
}

/// One set row of the Active workout (CONTEXT.md): weight, reps, effort as
/// RIR (null = unrated), the warm-up flag, and whether the player ticked it.
///
/// Rows start **empty** (0 kg, 0 reps, no RIR), exactly like the #107
/// prototype: the table shows the previous set as a faded hint and fills the
/// cells on tick, so nothing is pre-entered for the player to correct.
/// An empty cell is 0 for weight/reps and null for RIR, so "no value yet" is
/// distinguishable from a typed zero weight only by intent — the working-set
/// rules treat both as not logged, matching the server predicate.
class ActiveWorkoutSet {
  ActiveWorkoutSet({
    String? id,
    this.weightKg = 0,
    this.reps = 0,
    this.rir,
    this.isWarmup = false,
    this.ticked = false,
  }) : id = id ?? newActiveWorkoutSetId();

  factory ActiveWorkoutSet.fromJson(Map<String, dynamic> json) =>
      ActiveWorkoutSet(
        id: json['id'] as String? ?? newActiveWorkoutSetId(),
        weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 0,
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        rir: (json['rir'] as num?)?.toDouble(),
        isWarmup: json['is_warmup'] as bool? ?? false,
        ticked: json['ticked'] as bool? ?? false,
      );

  /// Stable identity of this row, persisted with the Active workout.
  final String id;

  final double weightKg;
  final int reps;

  /// Reps in reserve; null when the set is unrated (#111).
  final double? rir;

  final bool isWarmup;
  final bool ticked;

  bool get countsAsWorkingSet => isWorkingSet(
        isWarmup: isWarmup,
        weightKg: weightKg,
        reps: reps,
      );

  ActiveWorkoutSet copyWith({
    double? weightKg,
    int? reps,
    double? rir,
    bool? isWarmup,
    bool? ticked,
    bool clearRir = false,
  }) =>
      ActiveWorkoutSet(
        id: id,
        weightKg: weightKg ?? this.weightKg,
        reps: reps ?? this.reps,
        rir: clearRir ? null : (rir ?? this.rir),
        isWarmup: isWarmup ?? this.isWarmup,
        ticked: ticked ?? this.ticked,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'weight_kg': weightKg,
        'reps': reps,
        'rir': rir,
        'is_warmup': isWarmup,
        'ticked': ticked,
      };
}

/// `100 × 5 @1` — one ticked row as the rest notification's "last" shows it
/// (`last 100 × 5 @1`, #125), unrated rows dropping the `@` part like the
/// table's previous column does.
String setPerformanceLabel(ActiveWorkoutSet set) {
  final String effort = set.rir == null ? '' : ' @${formatRir(set.rir!)}';
  return '${formatCellWeight(set.weightKg)} × ${set.reps}$effort';
}

/// `100`, `92.5`, `33.33` — the cell/previous weight format.
String formatCellWeight(double weight) =>
    weight == weight.roundToDouble() ? weight.round().toString() : '$weight';

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

/// The **Current set** (CONTEXT.md, #158): the first unticked working set in
/// workout order — warm-ups skipped, moving across exercises — derived from
/// the Active workout and never stored. Null when every working set is
/// ticked.
///
/// "Working" is the row's *role* (not a warm-up), not the server's value
/// predicate [isWorkingSet]: the next set to do is normally still empty, and
/// an empty pending row is exactly the set the player logs next.
({int exerciseIndex, int setIndex})? currentSetOf(ActiveWorkout workout) {
  for (int exerciseIndex = 0;
      exerciseIndex < workout.exercises.length;
      exerciseIndex++) {
    final List<ActiveWorkoutSet> sets =
        workout.exercises[exerciseIndex].sets;
    for (int setIndex = 0; setIndex < sets.length; setIndex++) {
      final ActiveWorkoutSet set = sets[setIndex];
      if (!set.isWarmup && !set.ticked) {
        return (exerciseIndex: exerciseIndex, setIndex: setIndex);
      }
    }
  }
  return null;
}

/// The running rest timer, stored inside the Active workout so it survives a
/// restart (#125): when it ends, plus what the bar and the lock-screen
/// notification label it with.
@immutable
class ActiveRestTimer {
  const ActiveRestTimer({
    required this.endsAt,
    required this.totalSeconds,
    required this.exerciseId,
    required this.exerciseName,
    required this.setNumber,
    this.lastLabel,
  });

  factory ActiveRestTimer.fromJson(Map<String, dynamic> json) =>
      ActiveRestTimer(
        endsAt: json['ends_at'] as String,
        totalSeconds: (json['total_seconds'] as num?)?.toInt() ?? 0,
        exerciseId: json['exercise_id'] as String? ?? '',
        exerciseName: json['exercise_name'] as String? ?? '',
        setNumber: (json['set_number'] as num?)?.toInt() ?? 0,
        lastLabel: json['last_label'] as String?,
      );

  /// When the rest ends, as a UTC ISO-8601 string.
  final String endsAt;

  /// The length the rest started with — the bar's draining fill and the
  /// notification's "Rest m:ss" read this.
  final int totalSeconds;

  final String exerciseId;
  final String exerciseName;

  /// The 1-based row number that started the rest, as the keypad numbers it.
  final int setNumber;

  /// `100 × 5 @1` of the ticked set, when there were values to show.
  final String? lastLabel;

  DateTime get endsAtClock => DateTime.tryParse(endsAt) ?? DateTime.now();

  /// Whole seconds left, rounded up — exact while the app is in the
  /// foreground because it is computed from the clock, never decremented.
  int remainingSeconds(DateTime now) {
    final int ms = endsAtClock.difference(now).inMilliseconds;
    if (ms <= 0) {
      return 0;
    }
    return (ms / 1000).ceil();
  }

  bool isOver(DateTime now) => !endsAtClock.isAfter(now);

  ActiveRestTimer copyWith({String? endsAt}) => ActiveRestTimer(
        endsAt: endsAt ?? this.endsAt,
        totalSeconds: totalSeconds,
        exerciseId: exerciseId,
        exerciseName: exerciseName,
        setNumber: setNumber,
        lastLabel: lastLabel,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'ends_at': endsAt,
        'total_seconds': totalSeconds,
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'set_number': setNumber,
        'last_label': lastLabel,
      };
}

/// The prescription target an empty cell falls back to as its faded hint when
/// there is no previous set to hint from (#107/#108): the projected weight,
/// the target rep floor, and the target RPE expressed as RIR.
///
/// It is a display hint only — the cells stay empty until the player types or
/// ticks them, and the prescription `last_perf` never reaches this column
/// (#108: it stays for the progression projection alone).
@immutable
class PrescriptionHint {
  const PrescriptionHint({this.weightKg, this.reps, this.rir});

  factory PrescriptionHint.fromJson(Map<String, dynamic> json) =>
      PrescriptionHint(
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        reps: (json['reps'] as num?)?.toInt(),
        rir: (json['rir'] as num?)?.toDouble(),
      );

  final double? weightKg;
  final int? reps;
  final double? rir;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
        'rir': rir,
      };
}

/// One exercise of the Active workout: planned (from the program day) or
/// unplanned (added during the workout), each with its set rows.
class ActiveWorkoutExercise {
  const ActiveWorkoutExercise({
    required this.exercise,
    required this.sets,
    this.unplanned = false,
    this.targetLabel,
    this.prescriptionHint,
  });

  factory ActiveWorkoutExercise.fromJson(Map<String, dynamic> json) =>
      ActiveWorkoutExercise(
        exercise:
            Map<String, dynamic>.from(json['exercise'] as Map<String, dynamic>),
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) =>
                ActiveWorkoutSet.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
        unplanned: json['unplanned'] as bool? ?? false,
        targetLabel: json['target_label'] as String?,
        prescriptionHint: json['prescription_hint'] is Map<String, dynamic>
            ? PrescriptionHint.fromJson(
                json['prescription_hint'] as Map<String, dynamic>)
            : null,
      );

  /// The exact `ProgramExerciseSchema` payload the Workout draft expects.
  final Map<String, dynamic> exercise;
  final List<ActiveWorkoutSet> sets;
  final bool unplanned;

  /// The program day's own caption, kept on the exercise and persisted with
  /// the Active workout. The card no longer renders it (#158): it builds its
  /// prescription line from [exercise] instead, so planned and unplanned
  /// cards read alike.
  final String? targetLabel;

  /// The prescription target shown as the faded hint on cells that have no
  /// previous set to hint from (#107/#108).
  final PrescriptionHint? prescriptionHint;

  String get exerciseId => exercise['exercise_id'] as String;
  String get exerciseName => exercise['exercise_name'] as String;

  ActiveWorkoutExercise copyWith({List<ActiveWorkoutSet>? sets}) =>
      ActiveWorkoutExercise(
        exercise: exercise,
        sets: sets ?? this.sets,
        unplanned: unplanned,
        targetLabel: targetLabel,
        prescriptionHint: prescriptionHint,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise': exercise,
        'sets': <Map<String, dynamic>>[
          for (final ActiveWorkoutSet set in sets) set.toJson(),
        ],
        'unplanned': unplanned,
        'target_label': targetLabel,
        'prescription_hint': prescriptionHint?.toJson(),
      };
}

/// The unfinished workout the player is logging right now (CONTEXT.md).
///
/// A device holds at most one per account, it is persisted after every change,
/// and the baselines resolved at start are [baselines] — frozen for the life
/// of the workout (ADR 042, #123).
class ActiveWorkout {
  const ActiveWorkout({
    required this.id,
    required this.accountId,
    required this.startedAt,
    required this.dayOrder,
    required this.dayName,
    required this.exercises,
    required this.baselines,
    this.programVersion,
    this.rest,
  });

  factory ActiveWorkout.fromJson(Map<String, dynamic> json) => ActiveWorkout(
        id: json['id'] as String,
        accountId: json['account_id'] as String,
        startedAt: json['started_at'] as String,
        dayOrder: (json['day_order'] as num).toInt(),
        dayName: json['day_name'] as String? ?? 'Day',
        programVersion: (json['program_version'] as num?)?.toInt(),
        exercises: (json['exercises'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic e) =>
                ActiveWorkoutExercise.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        baselines: _baselinesFromJson(json['baselines']),
        rest: json['rest'] is Map<String, dynamic>
            ? ActiveRestTimer.fromJson(json['rest'] as Map<String, dynamic>)
            : null,
      );

  static Map<String, BaselineExercise> _baselinesFromJson(dynamic raw) {
    if (raw is! Map<String, dynamic>) {
      return <String, BaselineExercise>{};
    }
    return <String, BaselineExercise>{
      for (final MapEntry<String, dynamic> entry in raw.entries)
        entry.key:
            BaselineExercise.fromJson(entry.value as Map<String, dynamic>),
    };
  }

  final String id;
  final String accountId;

  /// When it started, as a UTC ISO-8601 string.
  final String startedAt;

  /// The program day it started from.
  final int dayOrder;
  final String dayName;

  /// The program version the day came from; null when none was known, which
  /// blocks the finish step exactly as the logger's own guard does.
  final int? programVersion;

  final List<ActiveWorkoutExercise> exercises;

  /// The baselines frozen at start, keyed by exercise id.
  final Map<String, BaselineExercise> baselines;

  /// The rest timer currently running, or null (#125). It is persisted with
  /// the workout, so the countdown survives an app restart.
  final ActiveRestTimer? rest;

  DateTime get startedAtClock => DateTime.tryParse(startedAt) ?? DateTime.now();

  /// The day the workout started, in the device's local zone — the default
  /// performed date of the finish step (#123).
  String get startedDate => formatPerformedDate(startedAtClock.toLocal());

  ActiveWorkout copyWith({
    List<ActiveWorkoutExercise>? exercises,
    Map<String, BaselineExercise>? baselines,
    int? programVersion,
    ActiveRestTimer? rest,
    bool clearRest = false,
  }) =>
      ActiveWorkout(
        id: id,
        accountId: accountId,
        startedAt: startedAt,
        dayOrder: dayOrder,
        dayName: dayName,
        programVersion: programVersion ?? this.programVersion,
        exercises: exercises ?? this.exercises,
        baselines: baselines ?? this.baselines,
        rest: clearRest ? null : (rest ?? this.rest),
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'account_id': accountId,
        'started_at': startedAt,
        'day_order': dayOrder,
        'day_name': dayName,
        'program_version': programVersion,
        'exercises': <Map<String, dynamic>>[
          for (final ActiveWorkoutExercise exercise in exercises)
            exercise.toJson(),
        ],
        'baselines': <String, dynamic>{
          for (final MapEntry<String, BaselineExercise> entry
              in baselines.entries)
            entry.key: entry.value.toJson(),
        },
        'rest': rest?.toJson(),
      };

  /// The `WorkoutDraft` this workout finishes into, built exactly the way the
  /// logger builds one today: only ticked sets are logged, and an exercise
  /// with no ticked set is sent as `skipped`.
  ///
  /// Returns null when the program version is unknown, so the finish step can
  /// block with the logger's own message instead of writing a draft the
  /// service would refuse.
  WorkoutDraft? buildWorkoutDraft({
    required String timezone,
    required String clientSessionId,
    required DateTime now,
    String? performedDate,
    int readiness = 4,
    String notes = '',
  }) {
    final int? version = programVersion;
    if (version == null) {
      return null;
    }
    final String date = performedDate ?? startedDate;
    final String iso = now.toUtc().toIso8601String();
    return WorkoutDraft(
      clientSessionId: clientSessionId,
      accountId: accountId,
      performedDate: date,
      performedTimezone: timezone,
      programVersion: version,
      dayOrder: dayOrder,
      dayName: dayName,
      capturedAt: iso,
      exercises: <DraftExercise>[
        for (final ActiveWorkoutExercise exercise in exercises)
          _draftExercise(exercise),
      ],
      readiness: readiness,
      notes: notes,
      status: DraftStatus.pending,
      updatedAt: iso,
    );
  }

  static DraftExercise _draftExercise(ActiveWorkoutExercise exercise) {
    final List<WorkoutSetLog> ticked = <WorkoutSetLog>[
      for (final ActiveWorkoutSet set in exercise.sets)
        if (set.ticked)
          WorkoutSetLog(
            weightKg: set.weightKg,
            reps: set.reps,
            rpe: rpeFromRir(set.rir),
            isWarmup: set.isWarmup,
          ),
    ];
    return DraftExercise(
      exercise: exercise.exercise,
      sets: ticked,
      skipped: ticked.isEmpty,
    );
  }
}

/// Device persistence for the single Active workout, keyed by account id
/// (the per-account pattern of [AppModeStore], #123).
abstract class ActiveWorkoutStore {
  Future<ActiveWorkout?> read(String accountId);

  Future<void> write(String accountId, ActiveWorkout workout);

  Future<void> deleteForAccount(String accountId);
}

class SecureActiveWorkoutStore implements ActiveWorkoutStore {
  SecureActiveWorkoutStore({FlutterSecureStorage? storage})
      : _store = SecureStore(storage: storage);

  final SecureStore _store;

  static String _key(String accountId) => 'active_workout.$accountId';

  @override
  Future<ActiveWorkout?> read(String accountId) async {
    final dynamic decoded = await _store.readJson(_key(accountId));
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    try {
      return ActiveWorkout.fromJson(decoded);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> write(String accountId, ActiveWorkout workout) =>
      _store.writeJson(key: _key(accountId), value: workout.toJson());

  @override
  Future<void> deleteForAccount(String accountId) =>
      _store.deleteExactOrPrefixed(_key(accountId), '${_key(accountId)}.');
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates an app restart reading the same protected storage.
class InMemoryActiveWorkoutStore implements ActiveWorkoutStore {
  final Map<String, ActiveWorkout> _byAccount = <String, ActiveWorkout>{};

  @override
  Future<ActiveWorkout?> read(String accountId) async => _byAccount[accountId];

  @override
  Future<void> write(String accountId, ActiveWorkout workout) async {
    _byAccount[accountId] = workout;
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _byAccount.remove(accountId);
  }
}
