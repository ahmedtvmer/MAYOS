import 'models.dart';

/// Projects the cached status into the immutable lines shown at Finish.
List<String> projectTrainingStatusSummary({
  required TrainingStatus? status,
  required List<WorkoutDraft> drafts,
  required DateTime now,
}) {
  if (status == null) {
    return const <String>[];
  }

  final List<WorkoutDraft> unsynced = drafts
      .where((WorkoutDraft draft) => draft.isUnsynced)
      .toList(growable: false);
  final int mayosWorkouts = status.mayosWorkouts + unsynced.length + 1;
  return List<String>.unmodifiable(<String>[
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

List<String> _weeklyLines(
  TrainingStatus status,
  List<WorkoutDraft> unsynced,
  DateTime now,
) {
  if (_weekStartIso(now) != status.weekStart) {
    return const <String>[];
  }
  final int done = status.weekDone + _pendingThisWeek(unsynced, status.weekStart) + 1;
  final int streak = _projectedStreak(status, done);
  final String weekWord = streak == 1 ? 'week' : 'weeks';
  return <String>[
    'Weekly streak: $streak $weekWord',
    'This week: $done of ${status.weekTarget} done',
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

String _checkpointLine(int mayosWorkouts) {
  if (_isCheckpoint(mayosWorkouts)) {
    return 'Your ${checkpointOrdinal(mayosWorkouts)} workout!';
  }
  final int checkpoint = _nextCheckpoint(mayosWorkouts);
  final int remaining = checkpoint - mayosWorkouts;
  final String workoutWord = remaining == 1 ? 'workout' : 'workouts';
  return '$remaining $workoutWord to your ${checkpointOrdinal(checkpoint)}';
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
  final int lastTwo = value % 100;
  if (lastTwo >= 11 && lastTwo <= 13) {
    return '${value}th';
  }
  return switch (value % 10) {
    1 => '${value}st',
    2 => '${value}nd',
    3 => '${value}rd',
    _ => '${value}th',
  };
}
