import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'baselines.dart';
import 'effort.dart';
import 'models.dart';
import 'performed_date_window.dart';
import 'rest_length.dart';
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

@immutable
class ActiveWarmupSet {
  const ActiveWarmupSet({this.weightKg, required this.reps, this.ticked = false});

  factory ActiveWarmupSet.fromJson(Map<String, dynamic> json) =>
      ActiveWarmupSet(
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        ticked: json['ticked'] as bool? ?? false,
      );

  final double? weightKg;
  final int reps;
  final bool ticked;

  ActiveWarmupSet copyWith({
    double? weightKg,
    int? reps,
    bool? ticked,
    bool clearWeight = false,
  }) => ActiveWarmupSet(
    weightKg: clearWeight ? null : (weightKg ?? this.weightKg),
    reps: reps ?? this.reps,
    ticked: ticked ?? this.ticked,
  );

  Map<String, dynamic> toJson() => <String, dynamic>{
    'weight_kg': weightKg,
    'reps': reps,
    'ticked': ticked,
  };
}

@immutable
class ActiveWarmupMovement {
  const ActiveWarmupMovement({
    required this.exerciseName,
    required this.sets,
    this.exerciseId,
  });

  factory ActiveWarmupMovement.fromJson(Map<String, dynamic> json) =>
      ActiveWarmupMovement(
        exerciseId: json['exercise_id'] as String?,
        exerciseName: json['exercise_name'] as String,
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic set) =>
                ActiveWarmupSet.fromJson(set as Map<String, dynamic>))
            .toList(growable: false),
      );

  factory ActiveWarmupMovement.fromPrescription(WarmupExercise movement) =>
      ActiveWarmupMovement(
        exerciseId: movement.exerciseId,
        exerciseName: movement.exerciseName,
        sets: <ActiveWarmupSet>[
          for (int i = 0; i < movement.sets; i++)
            ActiveWarmupSet(reps: movement.reps),
        ],
      );

  final String? exerciseId;
  final String exerciseName;
  final List<ActiveWarmupSet> sets;

  ActiveWarmupMovement copyWith({List<ActiveWarmupSet>? sets}) =>
      ActiveWarmupMovement(
        exerciseId: exerciseId,
        exerciseName: exerciseName,
        sets: sets ?? this.sets,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
    'exercise_id': exerciseId,
    'exercise_name': exerciseName,
    'sets': <Map<String, dynamic>>[
      for (final ActiveWarmupSet set in sets) set.toJson(),
    ],
  };
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

  bool get countsAsWorkingSet =>
      isWorkingSet(isWarmup: isWarmup, weightKg: weightKg, reps: reps);

  /// Whether this row is a working row for the **Current set** and the
  /// progress line (#158/#159): the row's *role* — not a warm-up — rather
  /// than the server's value predicate [countsAsWorkingSet]. The next set to
  /// do is normally still empty, and a progress total counts the rows the
  /// player still has to tick, so neither may look at the values.
  bool get isWorkingRow => !isWarmup;

  ActiveWorkoutSet copyWith({
    double? weightKg,
    int? reps,
    double? rir,
    bool? isWarmup,
    bool? ticked,
    bool clearRir = false,
  }) => ActiveWorkoutSet(
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

/// The card's previous-performance line (#158): the frozen baseline's last
/// session as `Last: 60kg × 6 · 60kg × 5`, working sets in logged order. A
/// bodyweight set reads `BW × 10`, never `0kg × 10`.
String lastSessionLabel(List<BaselineSet> sets) {
  final String joined = <String>[
    for (final BaselineSet set in sets)
      set.weightKg > 0
          ? '${formatCellWeight(set.weightKg)}kg × ${set.reps}'
          : 'BW × ${set.reps}',
  ].join(' · ');
  return 'Last: $joined';
}

/// The prescription caption (#108, #158): the effective prescription the rows
/// were seeded from, projection included — `4 sets · 6–8 reps · 62.5 kg ·
/// RIR ≥ 2`. One line that wraps: a clause appears only when the workout
/// carries it, and a single set reads `1 set`.
String prescriptionCaption({
  required int setCount,
  required int minReps,
  required int maxReps,
  double? projectedWeightKg,
  double? rir,
}) => <String>[
  setCount == 1 ? '1 set' : '$setCount sets',
  if (minReps > 0 && maxReps > 0) '$minReps–$maxReps reps',
  if (projectedWeightKg != null && projectedWeightKg > 0)
    '${formatCellWeight(projectedWeightKg)} kg',
  if (rir != null) 'RIR ${formatMinRir(rir)}',
].join(' · ');

/// The card's prescription line (#158): [prescriptionCaption] over the
/// effective prescription the rows were seeded from — so it never says
/// "3 sets" over 4 seeded rows — plus the rest length the player is using
/// right now (#125), e.g. `4 sets · 6–8 reps · 62.5 kg · RIR ≥ 2 · Rest 2:00`.
String exercisePrescriptionLine(
  ActiveWorkoutExercise exercise, {
  required int restSeconds,
}) {
  final Map<String, dynamic> payload = exercise.exercise;
  final int minReps = (payload['target_reps_min'] as num?)?.toInt() ?? 0;
  final int maxReps = (payload['target_reps_max'] as num?)?.toInt() ?? 0;
  final double? targetRpe = (payload['target_rpe'] as num?)?.toDouble();
  final double? rir =
      exercise.prescriptionHint?.rir ??
      (targetRpe == null ? null : rirFromRpe(clampRpe(targetRpe)));
  final String caption = prescriptionCaption(
    setCount: exercise.effectiveSetCount,
    minReps: minReps,
    maxReps: maxReps,
    // #108: the projection the prescription froze for this workout.
    projectedWeightKg: exercise.prescriptionHint?.weightKg,
    rir: rir,
  );
  final String rest = restSeconds <= 0
      ? 'Rest Off'
      : 'Rest ${restMmSs(restSeconds)}';
  return '$caption · $rest';
}

/// Whether the exercise at [exerciseIndex] is a **Replace exercise**'s
/// replacement (#162): an unplanned exercise sitting directly after the
/// planned exercise that replace hid. A replace keeps the pair adjacent, so
/// this holds however many other exercises come and go around them — it is
/// what the card menu labels **Undo replace** instead of **Remove exercise**.
bool isReplacementExerciseAt(ActiveWorkout workout, int exerciseIndex) {
  if (exerciseIndex <= 0 || exerciseIndex >= workout.exercises.length) {
    return false;
  }
  final ActiveWorkoutExercise replacement = workout.exercises[exerciseIndex];
  final ActiveWorkoutExercise planned = workout.exercises[exerciseIndex - 1];
  return replacement.unplanned && planned.replaced;
}

/// The **Current set** (CONTEXT.md, #158): the first unticked working set in
/// workout order — warm-ups skipped, moving across exercises. Null when
/// every working set is ticked.
///
/// "Working" is the row's *role* (not a warm-up), not the server's value
/// predicate [isWorkingSet] — [ActiveWorkoutSet.isWorkingRow], shared with
/// [workoutProgressOf]: the next set to do is normally still empty, and an
/// empty pending row is exactly the set the player logs next.
({int exerciseIndex, int setIndex})? currentSetOf(ActiveWorkout workout) {
  for (
    int exerciseIndex = 0;
    exerciseIndex < workout.exercises.length;
    exerciseIndex++
  ) {
    final List<ActiveWorkoutSet> sets = workout.exercises[exerciseIndex].sets;
    for (int setIndex = 0; setIndex < sets.length; setIndex++) {
      final ActiveWorkoutSet set = sets[setIndex];
      if (set.isWorkingRow && !set.ticked) {
        return (exerciseIndex: exerciseIndex, setIndex: setIndex);
      }
    }
  }
  return null;
}

/// The progress line's four counts (#159, reused by the bottom bar in #160).
///
/// "Working" is the **Current set's** rule —
/// [ActiveWorkoutSet.isWorkingRow], the row's role, not a warm-up — so
/// warm-ups are excluded from both set counts, exactly like the highlight
/// that points past them. An exercise is **completed** only when all of its
/// working rows are ticked, and an exercise with no working rows (every row
/// is a warm-up) is excluded from the exercise counts entirely: it is not a
/// to-do, so it neither blocks nor pads progress — the line can reach N/N.
/// The workout summary's own "exercises done" keeps its looser meaning — at
/// least one ticked working set (#124).
({int exercisesCompleted, int exercisesTotal, int setsTicked, int setsTotal})
workoutProgressOf(ActiveWorkout workout) {
  int exercisesCompleted = 0;
  int exercisesTotal = 0;
  int setsTicked = 0;
  int setsTotal = 0;
  for (final ActiveWorkoutExercise exercise in workout.exercises) {
    int working = 0;
    int ticked = 0;
    for (final ActiveWorkoutSet set in exercise.sets) {
      if (!set.isWorkingRow) {
        continue;
      }
      working += 1;
      if (set.ticked) {
        ticked += 1;
      }
    }
    if (working == 0) {
      // Nothing to do here: no working rows means no to-do (#159).
      continue;
    }
    exercisesTotal += 1;
    setsTotal += working;
    setsTicked += ticked;
    if (ticked == working) {
      exercisesCompleted += 1;
    }
  }
  return (
    exercisesCompleted: exercisesCompleted,
    exercisesTotal: exercisesTotal,
    setsTicked: setsTicked,
    setsTotal: setsTotal,
  );
}

/// The bottom bar's progress fraction (#160): [workoutProgressOf]'s ticked
/// sets over its total working sets, clamped to 0..1 — and 0 when the
/// workout has no working sets, so the bar renders empty rather than
/// indeterminate. The one place the fraction is worked out, beside the
/// counts it comes from, so the bar and the line can never disagree.
double workoutSetsFractionOf(ActiveWorkout workout) {
  final ({
    int exercisesCompleted,
    int exercisesTotal,
    int setsTicked,
    int setsTotal,
  })
  progress = workoutProgressOf(workout);
  if (progress.setsTotal <= 0) {
    return 0;
  }
  return (progress.setsTicked / progress.setsTotal).clamp(0.0, 1.0).toDouble();
}

/// **Workout time** (CONTEXT.md, #159): the wall-clock time since the
/// workout started, clamped at zero at [now]. It is derived from the stored
/// start time, so it has no pause, holds no state of its own, and stays
/// correct after an app restart. The caller supplies the clock — both call
/// sites read the app's clock provider — so nothing here reads time behind
/// the caller's back.
Duration workoutElapsed(ActiveWorkout workout, {required DateTime now}) {
  final Duration elapsed = now.difference(workout.startedAtClock);
  return elapsed.isNegative ? Duration.zero : elapsed;
}

/// Workout time as the top bar and the summary show it (#159): `mm:ss`, and
/// `h:mm:ss` once it passes an hour — `00:05`, `05:09`, `59:30`, `1:02:03`.
String formatWorkoutTime(Duration elapsed) {
  final Duration clamped = elapsed.isNegative ? Duration.zero : elapsed;
  final int seconds = clamped.inSeconds;
  final String ss = (seconds % 60).toString().padLeft(2, '0');
  final int minutes = seconds ~/ 60;
  if (minutes < 60) {
    return '${minutes.toString().padLeft(2, '0')}:$ss';
  }
  return '${minutes ~/ 60}:${(minutes % 60).toString().padLeft(2, '0')}:$ss';
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

  DateTime endsAtClock(DateTime fallback) =>
      DateTime.tryParse(endsAt) ?? fallback;

  /// Whole seconds left, rounded up — exact while the app is in the
  /// foreground because it is computed from the clock, never decremented.
  int remainingSeconds(DateTime now) {
    final int ms = endsAtClock(now).difference(now).inMilliseconds;
    if (ms <= 0) {
      return 0;
    }
    return (ms / 1000).ceil();
  }

  bool isOver(DateTime now) => !endsAtClock(now).isAfter(now);

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
    this.replaced = false,
    this.targetLabel,
    this.prescriptionHint,
    this.effectiveSets,
  });

  factory ActiveWorkoutExercise.fromJson(Map<String, dynamic> json) =>
      ActiveWorkoutExercise(
        exercise: Map<String, dynamic>.from(
          json['exercise'] as Map<String, dynamic>,
        ),
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map(
              (dynamic s) =>
                  ActiveWorkoutSet.fromJson(s as Map<String, dynamic>),
            )
            .toList(growable: false),
        unplanned: json['unplanned'] as bool? ?? false,
        replaced: json['replaced'] as bool? ?? false,
        targetLabel: json['target_label'] as String?,
        prescriptionHint: json['prescription_hint'] is Map<String, dynamic>
            ? PrescriptionHint.fromJson(
                json['prescription_hint'] as Map<String, dynamic>,
              )
            : null,
        effectiveSets: (json['effective_sets'] as num?)?.toInt(),
      );

  /// The exact `ProgramExerciseSchema` payload the Workout draft expects.
  final Map<String, dynamic> exercise;
  final List<ActiveWorkoutSet> sets;
  final bool unplanned;

  /// A planned exercise the player swapped out with **Replace exercise**
  /// (#162): it keeps its place and its exact program payload so the Workout
  /// draft still carries it as skipped, but it holds no rows, is never
  /// rendered as a card, and is excluded from progress by having no working
  /// rows. The replacement sits right after it as an unplanned exercise.
  final bool replaced;

  /// The program day's own caption, kept on the exercise and persisted with
  /// the Active workout; the card rebuilds its own line from the same facts
  /// (#158: [effectiveSetCount] and [prescriptionHint]'s projection), so
  /// planned and unplanned cards read alike.
  final String? targetLabel;

  /// The prescription target shown as the faded hint on cells that have no
  /// previous set to hint from (#107/#108).
  final PrescriptionHint? prescriptionHint;

  /// The effective set count the rows were seeded from (#108, #158): the
  /// prescription's effective sets when the workout started, so the card
  /// says what it actually seeded rather than the program's raw target.
  /// Null only for workouts stored before it was kept.
  final int? effectiveSets;

  String get exerciseId => exercise['exercise_id'] as String;
  String get exerciseName => exercise['exercise_name'] as String;

  /// The catalog image path the program payload carried (#161), for the
  /// card's picture. Null when the program (or an unplanned addition) had
  /// none, so the card falls back without a network lookup.
  String? get imagePath => exercise['image_path'] as String?;

  /// What the card's prescription line reports as the set count, in order:
  /// the seeded effective sets, else the program target, else today's rows.
  int get effectiveSetCount =>
      effectiveSets ??
      (exercise['target_sets'] as num?)?.toInt() ??
      sets.length;

  ActiveWorkoutExercise copyWith({
    List<ActiveWorkoutSet>? sets,
    bool? unplanned,
    bool? replaced,
  }) => ActiveWorkoutExercise(
    exercise: exercise,
    sets: sets ?? this.sets,
    unplanned: unplanned ?? this.unplanned,
    replaced: replaced ?? this.replaced,
    targetLabel: targetLabel,
    prescriptionHint: prescriptionHint,
    effectiveSets: effectiveSets,
  );

  Map<String, dynamic> toJson() => <String, dynamic>{
    'exercise': exercise,
    'sets': <Map<String, dynamic>>[
      for (final ActiveWorkoutSet set in sets) set.toJson(),
    ],
    'unplanned': unplanned,
    // Omitted unless true, so every exercise that was never replaced
    // stores exactly the JSON it did before this field existed (#162).
    if (replaced) 'replaced': true,
    'target_label': targetLabel,
    'prescription_hint': prescriptionHint?.toJson(),
    'effective_sets': effectiveSets,
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
    this.clientSessionId,
    this.commitAttempted = false,
    required this.startedAt,
    required this.dayOrder,
    required this.dayName,
    required this.exercises,
    this.warmupMovements = const <ActiveWarmupMovement>[],
    this.cardio,
    required this.baselines,
    this.programVersion,
    this.rest,
  });

  factory ActiveWorkout.fromJson(Map<String, dynamic> json) => ActiveWorkout(
    id: json['id'] as String,
    accountId: json['account_id'] as String,
    clientSessionId: json['client_session_id'] as String?,
    commitAttempted: json['commit_attempted'] as bool? ?? false,
    startedAt: json['started_at'] as String,
    dayOrder: (json['day_order'] as num).toInt(),
    dayName: json['day_name'] as String? ?? 'Day',
    programVersion: (json['program_version'] as num?)?.toInt(),
    exercises: (json['exercises'] as List<dynamic>? ?? const <dynamic>[])
        .map(
          (dynamic e) =>
              ActiveWorkoutExercise.fromJson(e as Map<String, dynamic>),
        )
        .toList(growable: false),
    warmupMovements:
        (json['warmup_movements'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic movement) => ActiveWarmupMovement.fromJson(
                movement as Map<String, dynamic>))
            .toList(growable: false),
    cardio: json['cardio'] is Map<String, dynamic>
        ? WorkoutCardio.fromJson(json['cardio'] as Map<String, dynamic>)
        : null,
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
        entry.key: BaselineExercise.fromJson(
          entry.value as Map<String, dynamic>,
        ),
    };
  }

  final String id;
  final String accountId;

  /// Stable idempotency key created when this workout starts (ADR 033).
  /// Null only for workouts persisted by an older app version.
  final String? clientSessionId;

  /// True once a direct commit has been attempted, so a reload retries through
  /// the by-client-id reconciliation endpoint before posting again.
  final bool commitAttempted;

  /// When it started, as a UTC ISO-8601 string.
  final String startedAt;

  /// The program day it started from.
  final int dayOrder;
  final String dayName;

  /// The program version the day came from; null when none was known, which
  /// blocks the finish step exactly as the logger's own guard does.
  final int? programVersion;

  final List<ActiveWorkoutExercise> exercises;

  final List<ActiveWarmupMovement> warmupMovements;

  /// The prescribed Cardio item and its logged minutes, independent of sets.
  final WorkoutCardio? cardio;

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
    List<ActiveWarmupMovement>? warmupMovements,
    WorkoutCardio? cardio,
    Map<String, BaselineExercise>? baselines,
    String? clientSessionId,
    bool? commitAttempted,
    int? programVersion,
    ActiveRestTimer? rest,
    bool clearRest = false,
  }) => ActiveWorkout(
    id: id,
    accountId: accountId,
    clientSessionId: clientSessionId ?? this.clientSessionId,
    commitAttempted: commitAttempted ?? this.commitAttempted,
    startedAt: startedAt,
    dayOrder: dayOrder,
    dayName: dayName,
    programVersion: programVersion ?? this.programVersion,
    exercises: exercises ?? this.exercises,
    warmupMovements: warmupMovements ?? this.warmupMovements,
    cardio: cardio ?? this.cardio,
    baselines: baselines ?? this.baselines,
    rest: clearRest ? null : (rest ?? this.rest),
  );

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'account_id': accountId,
    if (clientSessionId != null) 'client_session_id': clientSessionId,
    if (commitAttempted) 'commit_attempted': true,
    'started_at': startedAt,
    'day_order': dayOrder,
    'day_name': dayName,
    'program_version': programVersion,
    'exercises': <Map<String, dynamic>>[
      for (final ActiveWorkoutExercise exercise in exercises) exercise.toJson(),
    ],
    if (warmupMovements.isNotEmpty)
      'warmup_movements': <Map<String, dynamic>>[
        for (final ActiveWarmupMovement movement in warmupMovements)
          movement.toJson(),
      ],
    if (cardio != null) 'cardio': cardio!.toJson(),
    'baselines': <String, dynamic>{
      for (final MapEntry<String, BaselineExercise> entry in baselines.entries)
        entry.key: entry.value.toJson(),
    },
    'rest': rest?.toJson(),
  };

  /// Builds the direct `POST /workouts/sessions` body from this Active
  /// workout, without turning it into a Workout draft (the web contract).
  /// Returns null when this workout has no stable id or program version.
  Map<String, dynamic>? buildCommitBody({
    required String timezone,
    required DateTime now,
    String? performedDate,
    int readiness = 4,
    String notes = '',
  }) {
    final int? version = programVersion;
    final String? sessionId = clientSessionId;
    if (version == null || sessionId == null) return null;
    final List<Map<String, dynamic>> loggedExercises = <Map<String, dynamic>>[];
    for (final ActiveWorkoutExercise exercise in exercises) {
      final List<WorkoutSetLog> sets = _loggedSets(exercise);
      if (sets.isNotEmpty) {
        loggedExercises.add(<String, dynamic>{
          'exercise': exercise.exercise,
          'sets': <Map<String, dynamic>>[
            for (final WorkoutSetLog set in sets) set.toJson(),
          ],
        });
      }
    }
    final List<WarmupMovementLog> loggedWarmupMovements =
        _loggedWarmupMovements(warmupMovements);
    return <String, dynamic>{
      'day_order': dayOrder,
      'readiness': readiness,
      'session_notes': notes,
      'sets': loggedExercises,
      if (loggedWarmupMovements.isNotEmpty)
        'warmup_movements': <Map<String, dynamic>>[
          for (final WarmupMovementLog movement in loggedWarmupMovements)
            movement.toJson(),
        ],
      if (cardio?.isCommitted == true) 'cardio': cardio!.toCommitJson(),
      'client_session_id': sessionId,
      'performed_date': performedDate ?? startedDate,
      'performed_timezone': timezone,
      'program_version': version,
      'captured_at': now.toUtc().toIso8601String(),
    };
  }

  static List<WorkoutSetLog> _loggedSets(ActiveWorkoutExercise exercise) =>
      <WorkoutSetLog>[
        for (final ActiveWorkoutSet set in exercise.sets)
          if (set.ticked)
            WorkoutSetLog(
              weightKg: set.weightKg,
              reps: set.reps,
              rpe: rpeFromRir(set.rir),
              isWarmup: set.isWarmup,
            ),
      ];

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
      warmupMovements: _draftWarmupMovements(warmupMovements),
      cardio: cardio,
      readiness: readiness,
      notes: notes,
      status: DraftStatus.pending,
      updatedAt: iso,
    );
  }

  static DraftExercise _draftExercise(ActiveWorkoutExercise exercise) {
    final List<WorkoutSetLog> ticked = _loggedSets(exercise);
    return DraftExercise(
      exercise: exercise.exercise,
      sets: ticked,
      skipped: ticked.isEmpty,
    );
  }

  static List<WarmupMovementLog> _loggedWarmupMovements(
    List<ActiveWarmupMovement> movements,
  ) => <WarmupMovementLog>[
    for (final ActiveWarmupMovement movement in movements)
      if (movement.sets.any((ActiveWarmupSet set) => set.ticked))
        WarmupMovementLog(
          exerciseId: movement.exerciseId,
          exerciseName: movement.exerciseName,
          sets: <WarmupSetLog>[
            for (final ActiveWarmupSet set in movement.sets)
              if (set.ticked)
                WarmupSetLog(weightKg: set.weightKg, reps: set.reps),
          ],
        ),
  ];

  static List<WarmupMovementDraft> _draftWarmupMovements(
    List<ActiveWarmupMovement> movements,
  ) => <WarmupMovementDraft>[
    for (final ActiveWarmupMovement movement in movements)
      WarmupMovementDraft(
        exerciseId: movement.exerciseId,
        exerciseName: movement.exerciseName,
        sets: <WarmupSetDraft>[
          for (final ActiveWarmupSet set in movement.sets)
            WarmupSetDraft(
              weightKg: set.weightKg,
              reps: set.reps,
              ticked: set.ticked,
            ),
        ],
      ),
  ];
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
