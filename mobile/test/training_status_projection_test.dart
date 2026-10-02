import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/training_status_projection.dart';

TrainingStatus _status({
  String weekStart = '2026-09-26',
  int weeklyStreak = 2,
  int weekDone = 1,
  int weekTarget = 2,
  int mayosWorkouts = 8,
}) =>
    TrainingStatus(
      weeklyStreak: weeklyStreak,
      weekStart: weekStart,
      weekDone: weekDone,
      weekTarget: weekTarget,
      mayosWorkouts: mayosWorkouts,
      nextCheckpoint: 10,
      workoutsToNext: 10 - mayosWorkouts,
    );

WorkoutDraft _draft(
  String id,
  String performedDate, {
  String status = DraftStatus.pending,
}) =>
    WorkoutDraft(
      clientSessionId: id,
      accountId: 'account-1',
      performedDate: performedDate,
      performedTimezone: 'UTC',
      programVersion: 1,
      dayOrder: 1,
      dayName: 'Full A',
      capturedAt: '${performedDate}T12:00:00Z',
      exercises: const <DraftExercise>[],
      readiness: 4,
      status: status,
      updatedAt: '${performedDate}T12:00:00Z',
    );

List<String> _englishLines(List<TrainingStatusSummaryLine> lines) =>
    lines.map((TrainingStatusSummaryLine line) => line.englishText).toList();

void main() {
  final DateTime currentWeek = DateTime(2026, 9, 30, 12);

  test('projects the in-progress weekly streak and Checkpoint online', () {
    expect(
      _englishLines(projectTrainingStatusSummary(
        status: _status(),
        drafts: const <WorkoutDraft>[],
        now: currentWeek,
      )),
      <String>[
        'Weekly streak: 3 weeks',
        'This week: 2 of 2 done',
        '1 workout to your 10th',
      ],
    );
  });

  test(
    'omits weekly lines for a stale cached week and keeps Checkpoint progress',
    () {
      expect(
        _englishLines(projectTrainingStatusSummary(
          status: _status(weekStart: '2026-09-19', mayosWorkouts: 9),
          drafts: const <WorkoutDraft>[],
          now: currentWeek,
        )),
        <String>['Your 10th workout!'],
      );
    },
  );

  test(
    'counts only pending drafts from this week toward the weekly projection',
    () {
      final List<String> lines = _englishLines(projectTrainingStatusSummary(
        status: _status(weekDone: 1, weekTarget: 3, mayosWorkouts: 7),
        drafts: <WorkoutDraft>[
          _draft('current-week', '2026-09-29'),
          _draft('previous-week', '2026-09-20'),
          _draft('already-synced', '2026-09-30', status: DraftStatus.synced),
        ],
        now: currentWeek,
      ));
      expect(lines, <String>[
        'Weekly streak: 3 weeks',
        'This week: 3 of 3 done',
        'Your 10th workout!',
      ]);
    },
  );

  test('formats singular streak and checkpoint ordinals', () {
    expect(
      _englishLines(projectTrainingStatusSummary(
        status: _status(
          weeklyStreak: 1,
          weekDone: 0,
          weekTarget: 3,
          mayosWorkouts: 24,
        ),
        drafts: const <WorkoutDraft>[],
        now: currentWeek,
      )),
      <String>[
        'Weekly streak: 1 week',
        'This week: 1 of 3 done',
        'Your 25th workout!',
      ],
    );
    expect(
      _englishLines(projectTrainingStatusSummary(
        status: _status(
          weeklyStreak: 1,
          weekDone: 0,
          weekTarget: 3,
          mayosWorkouts: 49,
        ),
        drafts: const <WorkoutDraft>[],
        now: currentWeek,
      )).last,
      'Your 50th workout!',
    );
  });
}
