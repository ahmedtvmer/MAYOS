import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'baselines.dart';
import 'models.dart';
import 'performed_date_window.dart';
import 'secure_store.dart';

/// One set row of the Active workout (CONTEXT.md): weight, reps, effort as
/// RIR (null = unrated), the warm-up flag, and whether the player ticked it.
///
/// An empty cell is 0 for weight/reps and null for RIR, so "no value yet" is
/// distinguishable from a typed zero weight only by intent — the working-set
/// rules treat both as not logged, matching the server predicate.
class ActiveWorkoutSet {
  const ActiveWorkoutSet({
    this.weightKg = 0,
    this.reps = 0,
    this.rir,
    this.isWarmup = false,
    this.ticked = false,
  });

  factory ActiveWorkoutSet.fromJson(Map<String, dynamic> json) =>
      ActiveWorkoutSet(
        weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 0,
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        rir: (json['rir'] as num?)?.toDouble(),
        isWarmup: json['is_warmup'] as bool? ?? false,
        ticked: json['ticked'] as bool? ?? false,
      );

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
        weightKg: weightKg ?? this.weightKg,
        reps: reps ?? this.reps,
        rir: clearRir ? null : (rir ?? this.rir),
        isWarmup: isWarmup ?? this.isWarmup,
        ticked: ticked ?? this.ticked,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
        'rir': rir,
        'is_warmup': isWarmup,
        'ticked': ticked,
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
  });

  factory ActiveWorkoutExercise.fromJson(Map<String, dynamic> json) =>
      ActiveWorkoutExercise(
        exercise: Map<String, dynamic>.from(
            json['exercise'] as Map<String, dynamic>),
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) =>
                ActiveWorkoutSet.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
        unplanned: json['unplanned'] as bool? ?? false,
        targetLabel: json['target_label'] as String?,
      );

  /// The exact `ProgramExerciseSchema` payload the Workout draft expects.
  final Map<String, dynamic> exercise;
  final List<ActiveWorkoutSet> sets;
  final bool unplanned;

  /// The prescription caption shown on the card, when planned.
  final String? targetLabel;

  String get exerciseId => exercise['exercise_id'] as String;
  String get exerciseName => exercise['exercise_name'] as String;

  ActiveWorkoutExercise copyWith({List<ActiveWorkoutSet>? sets}) =>
      ActiveWorkoutExercise(
        exercise: exercise,
        sets: sets ?? this.sets,
        unplanned: unplanned,
        targetLabel: targetLabel,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise': exercise,
        'sets': <Map<String, dynamic>>[
          for (final ActiveWorkoutSet set in sets) set.toJson(),
        ],
        'unplanned': unplanned,
        'target_label': targetLabel,
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
      );

  static Map<String, BaselineExercise> _baselinesFromJson(dynamic raw) {
    if (raw is! Map<String, dynamic>) {
      return <String, BaselineExercise>{};
    }
    return <String, BaselineExercise>{
      for (final MapEntry<String, dynamic> entry in raw.entries)
        entry.key: BaselineExercise.fromJson(
            entry.value as Map<String, dynamic>),
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

  DateTime get startedAtClock => DateTime.tryParse(startedAt) ?? DateTime.now();

  /// The day the workout started, in the device's local zone — the default
  /// performed date of the finish step (#123).
  String get startedDate => formatPerformedDate(startedAtClock.toLocal());

  ActiveWorkout copyWith({
    List<ActiveWorkoutExercise>? exercises,
    Map<String, BaselineExercise>? baselines,
    int? programVersion,
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
