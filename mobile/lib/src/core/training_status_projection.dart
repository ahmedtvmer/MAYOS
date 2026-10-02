import 'models.dart';
import 'checkpoint_ordinal.dart' as ordinal;

/// One typed fact projected for the workout summary.
sealed class TrainingStatusSummaryLine {
  const TrainingStatusSummaryLine();

  /// The existing English presentation, retained byte-for-byte for the
  /// English app and for callers that need the legacy line text.
  String get englishText;
}

final class WeeklyStreakSummaryLine extends TrainingStatusSummaryLine {
  const WeeklyStreakSummaryLine(this.weeks);

  final int weeks;

  @override
  String get englishText =>
      'Weekly streak: $weeks ${weeks == 1 ? 'week' : 'weeks'}';
}

final class WeeklyCompletionSummaryLine extends TrainingStatusSummaryLine {
  const WeeklyCompletionSummaryLine({
    required this.completed,
    required this.target,
  });

  final int completed;
  final int target;

  @override
  String get englishText => 'This week: $completed of $target done';
}

final class CheckpointProgressSummaryLine extends TrainingStatusSummaryLine {
  const CheckpointProgressSummaryLine({
    required this.remaining,
    required this.checkpoint,
  });

  final int remaining;
  final int checkpoint;

  @override
  String get englishText =>
      '$remaining ${remaining == 1 ? 'workout' : 'workouts'} to your ${checkpointOrdinal(checkpoint)}';
}

final class CheckpointReachedSummaryLine extends TrainingStatusSummaryLine {
  const CheckpointReachedSummaryLine(this.number);

  final int number;

  @override
  String get englishText => 'Your ${checkpointOrdinal(number)} workout!';
}

/// Projects cached status and unsynced drafts into typed summary facts.
List<TrainingStatusSummaryLine> projectTrainingStatusSummary({
  required TrainingStatus? status,
  required List<WorkoutDraft> drafts,
  required DateTime now,
}) {
  if (status == null) {
    return const <TrainingStatusSummaryLine>[];
  }

  final List<WorkoutDraft> unsynced = drafts
      .where((WorkoutDraft draft) => draft.isUnsynced)
      .toList(growable: false);
  final int mayosWorkouts = status.mayosWorkouts + unsynced.length + 1;
  return List<
      TrainingStatusSummaryLine>.unmodifiable(<TrainingStatusSummaryLine>[
    ..._weeklyLines(status, unsynced, now),
    _checkpointLine(mayosWorkouts),
  ]);
}

int? projectedCheckpointNumber({
  required TrainingStatus? status,
  required List<WorkoutDraft> drafts,
}) {
  if (status == null) return null;
  final int count = status.mayosWorkouts +
      drafts.where((WorkoutDraft draft) => draft.isUnsynced).length +
      1;
  return _isCheckpoint(count) ? count : null;
}

List<TrainingStatusSummaryLine> _weeklyLines(
  TrainingStatus status,
  List<WorkoutDraft> unsynced,
  DateTime now,
) {
  if (_weekStartIso(now) != status.weekStart) {
    return const <TrainingStatusSummaryLine>[];
  }
  final int done =
      status.weekDone + _pendingThisWeek(unsynced, status.weekStart) + 1;
  final int streak = _projectedStreak(status, done);
  return <TrainingStatusSummaryLine>[
    WeeklyStreakSummaryLine(streak),
    WeeklyCompletionSummaryLine(completed: done, target: status.weekTarget),
  ];
}

int _pendingThisWeek(List<WorkoutDraft> drafts, String weekStart) =>
    drafts.where((WorkoutDraft draft) {
      final DateTime? performed = _parseDate(draft.performedDate);
      return performed != null && _weekStartIso(performed) == weekStart;
    }).length;

int _projectedStreak(TrainingStatus status, int projectedDone) {
  if (status.weekTarget == 0 ||
      status.weekDone >= status.weekTarget ||
      projectedDone < status.weekTarget) {
    return status.weeklyStreak;
  }
  return status.weeklyStreak + 1;
}

TrainingStatusSummaryLine _checkpointLine(int mayosWorkouts) {
  if (_isCheckpoint(mayosWorkouts)) {
    return CheckpointReachedSummaryLine(mayosWorkouts);
  }
  final int checkpoint = _nextCheckpoint(mayosWorkouts);
  return CheckpointProgressSummaryLine(
    remaining: checkpoint - mayosWorkouts,
    checkpoint: checkpoint,
  );
}

DateTime _saturdayWeekStart(DateTime day) {
  final int daysSinceSaturday = (day.weekday + 1) % 7;
  return DateTime(day.year, day.month, day.day - daysSinceSaturday);
}

String _weekStartIso(DateTime day) =>
    _saturdayWeekStart(day).toIso8601String().substring(0, 10);

DateTime? _parseDate(String value) {
  if (value.length < 10) {
    return null;
  }
  return DateTime.tryParse(value.substring(0, 10));
}

bool _isCheckpoint(int count) =>
    count == 10 ||
    count == 25 ||
    count == 50 ||
    (count >= 100 && count % 100 == 0);

int _nextCheckpoint(int count) {
  for (final int checkpoint in const <int>[10, 25, 50, 100]) {
    if (count < checkpoint) {
      return checkpoint;
    }
  }
  return (count ~/ 100 + 1) * 100;
}

String checkpointOrdinal(int value) {
  return ordinal.checkpointOrdinal(value);
}
