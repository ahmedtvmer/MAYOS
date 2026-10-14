import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/features/player/dashboard/home_planning.dart';

TrainingProgram _program() => TrainingProgram(
      programName: 'Upper/Lower 4x',
      splitType: 'Upper/Lower',
      weeklyFrequency: 4,
      days: <ProgramDay>[
        for (int order in <int>[1, 2, 3, 4])
          ProgramDay(
            dayName: 'Day $order',
            dayOrder: order,
            exercises: <ProgramExercise>[
              ProgramExercise(
                exerciseId: 'e$order',
                exerciseName: 'Exercise $order',
                targetSets: 3,
                targetRepsMin: 6,
                targetRepsMax: 10,
                targetRpe: 8.0,
              ),
            ],
          ),
      ],
    );

TrainingSchedule _schedule(List<int> weekdays) => TrainingSchedule(
      current: TrainingScheduleVersion(
        scheduleId: 's1',
        weekdays: weekdays,
        timezone: 'Europe/London',
        effectiveFrom: '2026-09-01',
        createdAt: '2026-09-01T00:00:00Z',
      ),
    );

TrainedDay _trained({
  int? dayOrder,
  int? weekOrder,
  int? programVersion,
  String? dayName,
  String performedDate = '2026-09-20',
  String updatedAt = '2026-09-20T10:00:00Z',
}) =>
    TrainedDay(
      dayOrder: dayOrder,
      weekOrder: weekOrder,
      programVersion: programVersion,
      dayName: dayName,
      performedDate: performedDate,
      updatedAt: updatedAt,
    );

TrainedDay _fromServer(
  String splitName, {
  int? dayOrder,
  String sessionDate = '2026-09-20',
}) =>
    TrainedDay.fromLatestSession(LatestSession(
      sessionId: 'sess-$splitName-$sessionDate',
      sessionDate: sessionDate,
      splitName: splitName,
      dayOrder: dayOrder,
    ));

void main() {
  group('greetingFor', () {
    test('does not invent a name and follows the hour', () {
      expect(greetingFor(DateTime(2026, 9, 21, 8)), 'Good morning');
      expect(greetingFor(DateTime(2026, 9, 21, 14)), 'Good afternoon');
      expect(greetingFor(DateTime(2026, 9, 21, 20)), 'Good evening');
    });

    test('Arabic greeting follows morning, afternoon, and evening', () {
      const MayosCopy arabic = MayosCopy('ar');
      expect(arabic.greetingFor(DateTime(2026, 9, 21, 8)), 'صباح الخير');
      expect(arabic.greetingFor(DateTime(2026, 9, 21, 14)), 'طاب يومك');
      expect(arabic.greetingFor(DateTime(2026, 9, 21, 20)), 'مساء الخير');
    });
  });

  group('nextScheduledWeekday', () {
    test('returns the next weekday at or after today', () {
      // Tue 2026-09-22; schedule Mon/Wed/Fri → Wed (3).
      expect(nextScheduledWeekday(<int>[1, 3, 5], DateTime(2026, 9, 22)), 3);
    });

    test('returns today when today is a scheduled weekday', () {
      expect(nextScheduledWeekday(<int>[1, 3, 5], DateTime(2026, 9, 23)), 3);
    });

    test('wraps to the first weekday next week', () {
      // Sat 2026-09-26; nothing remains this week → Mon (1).
      expect(nextScheduledWeekday(<int>[1, 3, 5], DateTime(2026, 9, 26)), 1);
    });
  });

  group('nextSessionLabel', () {
    test('is a bare "Next session" without a schedule', () {
      expect(nextSessionLabel(null, DateTime(2026, 9, 22)), 'Next session');
    });

    test('labels the expected weekday with a schedule', () {
      expect(
        nextSessionLabel(_schedule(<int>[1, 3, 5]), DateTime(2026, 9, 22)),
        'Next session · Wed',
      );
    });

    test('is independent of which program day is next', () {
      expect(
        nextSessionLabel(_schedule(<int>[1, 3, 5]), DateTime(2026, 9, 25)),
        'Next session · Fri',
      );
    });
  });

  group('latestTrainedDay', () {
    test('is null with no history', () {
      expect(latestTrainedDay(const <TrainedDay>[]), isNull);
    });

    test('uses the latest performed date', () {
      expect(
        latestTrainedDay(<TrainedDay>[
          _trained(dayOrder: 1, performedDate: '2026-09-18'),
          _trained(dayOrder: 3, performedDate: '2026-09-21'),
          _trained(dayOrder: 2, performedDate: '2026-09-19'),
        ])!
            .dayOrder,
        3,
      );
    });

    test('breaks a same-date tie with the later update', () {
      expect(
        latestTrainedDay(<TrainedDay>[
          _trained(
              dayOrder: 2,
              performedDate: '2026-09-21',
              updatedAt: '2026-09-21T08:00:00Z'),
          _trained(
              dayOrder: 4,
              performedDate: '2026-09-21',
              updatedAt: '2026-09-21T18:00:00Z'),
        ])!
            .dayOrder,
        4,
      );
    });
  });

  group('selectNextDay', () {
    test('with no history starts at Day 1', () {
      final ProgramDay? day = selectNextDay(_program(), const <TrainedDay>[]);
      expect(day, isNotNull);
      expect(day!.dayOrder, 1);
    });

    test('advances to the day after the most recently trained', () {
      final ProgramDay? day =
          selectNextDay(_program(), <TrainedDay>[_trained(dayOrder: 1)]);
      expect(day!.dayOrder, 2);
    });

    test('wraps to Day 1 after the last day', () {
      final ProgramDay? day =
          selectNextDay(_program(), <TrainedDay>[_trained(dayOrder: 4)]);
      expect(day!.dayOrder, 1);
    });

    test('restarts at Day 1 when the trained day left the program', () {
      final ProgramDay? day =
          selectNextDay(_program(), <TrainedDay>[_trained(dayOrder: 9)]);
      expect(day!.dayOrder, 1);
    });

    test('matches a server session by name when day_order is absent', () {
      // "Day 2" is the program's day_order 2.
      final ProgramDay? day =
          selectNextDay(_program(), <TrainedDay>[_fromServer('Day 2')]);
      expect(day!.dayOrder, 3);
    });

    test('matches a server session by day_order when present', () {
      final ProgramDay? day = selectNextDay(
          _program(), <TrainedDay>[_fromServer('ignored', dayOrder: 3)]);
      expect(day!.dayOrder, 4);
    });

    test('unmatched server day name restarts at Day 1', () {
      final ProgramDay? day =
          selectNextDay(_program(), <TrainedDay>[_fromServer('Full Body A')]);
      expect(day!.dayOrder, 1);
    });

    test('uses the server session when it is newer than the drafts', () {
      final ProgramDay? day = selectNextDay(_program(), <TrainedDay>[
        _trained(dayOrder: 1, performedDate: '2026-09-18'),
        _fromServer('Day 3', sessionDate: '2026-09-22'),
      ]);
      expect(day!.dayOrder, 4);
    });

    test('uses the draft when it is newer than the server session', () {
      final ProgramDay? day = selectNextDay(_program(), <TrainedDay>[
        _fromServer('Day 1', sessionDate: '2026-09-18'),
        _trained(dayOrder: 3, performedDate: '2026-09-22'),
      ]);
      expect(day!.dayOrder, 4);
    });

    test('orders by day_order, not by list position', () {
      final TrainingProgram shuffled = TrainingProgram(
        programName: 'Shuffled',
        splitType: 'custom',
        weeklyFrequency: 3,
        days: <ProgramDay>[
          ProgramDay(dayName: 'C', dayOrder: 3, exercises: const []),
          ProgramDay(dayName: 'A', dayOrder: 1, exercises: const []),
          ProgramDay(dayName: 'B', dayOrder: 2, exercises: const []),
        ],
      );
      expect(
          selectNextDay(shuffled, <TrainedDay>[_trained(dayOrder: 1)])!.dayName,
          'B');
      expect(
          selectNextDay(shuffled, <TrainedDay>[_trained(dayOrder: 3)])!.dayName,
          'A');
    });

    test('returns null when the program has no days', () {
      final TrainingProgram empty = TrainingProgram(
        programName: 'Empty',
        splitType: 'custom',
        weeklyFrequency: 1,
        days: const <ProgramDay>[],
      );
      expect(selectNextDay(empty, const <TrainedDay>[]), isNull);
    });

    test('walks the cached current week from locally completed workouts', () {
      final TrainingProgram block = TrainingProgram(
        programName: 'Two weeks',
        splitType: 'custom',
        weeklyFrequency: 2,
        version: 4,
        currentWeek: 1,
        weekCount: 2,
        nextDayOrder: 1,
        days: <ProgramDay>[
          for (int week in <int>[1, 2])
            for (int day in <int>[1, 2])
              ProgramDay(
                dayName: 'Day $day',
                dayOrder: day,
                weekOrder: week,
                exercises: const <ProgramExercise>[],
              ),
        ],
      );

      final ProgramDay? next = selectNextDay(
        block,
        <TrainedDay>[
          _trained(
            dayOrder: 1,
            weekOrder: 1,
            programVersion: 4,
          ),
        ],
      );

      expect((next?.weekOrder, next?.dayOrder), (1, 2));
    });

    test('advances offline to the next known week after completing this week', () {
      final List<ProgramDay> weekOne = <ProgramDay>[
        for (int day in <int>[1, 2])
          ProgramDay(
            dayName: 'Week 1 Day $day',
            dayOrder: day,
            weekOrder: 1,
            exercises: const <ProgramExercise>[],
          ),
      ];
      final List<ProgramDay> weekTwo = <ProgramDay>[
        for (int day in <int>[1, 2])
          ProgramDay(
            dayName: 'Week 2 Day $day',
            dayOrder: day,
            weekOrder: 2,
            exercises: const <ProgramExercise>[],
          ),
      ];
      final TrainingProgram block = TrainingProgram(
        programName: 'Two weeks',
        splitType: 'custom',
        weeklyFrequency: 2,
        version: 4,
        currentWeek: 1,
        weekCount: 2,
        nextDayOrder: 1,
        days: <ProgramDay>[...weekOne, ...weekTwo],
        weeks: <ProgramWeek>[
          ProgramWeek(weekName: 'Base', weekOrder: 1, days: weekOne),
          ProgramWeek(weekName: 'Build', weekOrder: 2, days: weekTwo),
        ],
      );
      final List<TrainedDay> completedWeekOne = <TrainedDay>[
        _trained(dayOrder: 1, weekOrder: 1, programVersion: 4),
        _trained(dayOrder: 2, weekOrder: 1, programVersion: 4),
      ];

      final ProgramDay? next = selectNextDay(block, completedWeekOne);

      expect((next?.weekOrder, next?.dayOrder), (2, 1));
    });

    test('clamps offline completion to the last week and repeats its next day', () {
      final List<ProgramDay> weekOne = <ProgramDay>[
        for (int day in <int>[1, 2])
          ProgramDay(
            dayName: 'Week 1 Day $day',
            dayOrder: day,
            weekOrder: 1,
            exercises: const <ProgramExercise>[],
          ),
      ];
      final List<ProgramDay> weekTwo = <ProgramDay>[
        for (int day in <int>[1, 2])
          ProgramDay(
            dayName: 'Week 2 Day $day',
            dayOrder: day,
            weekOrder: 2,
            exercises: const <ProgramExercise>[],
          ),
      ];
      final TrainingProgram block = TrainingProgram(
        programName: 'Two weeks',
        splitType: 'custom',
        weeklyFrequency: 2,
        version: 4,
        currentWeek: 2,
        weekCount: 2,
        nextDayOrder: 1,
        days: <ProgramDay>[...weekOne, ...weekTwo],
        weeks: <ProgramWeek>[
          ProgramWeek(weekName: 'Base', weekOrder: 1, days: weekOne),
          ProgramWeek(weekName: 'Build', weekOrder: 2, days: weekTwo),
        ],
      );
      final List<TrainedDay> completed = <TrainedDay>[
        _trained(dayOrder: 1, weekOrder: 1, programVersion: 4),
        _trained(dayOrder: 2, weekOrder: 1, programVersion: 4),
        _trained(
          dayOrder: 1,
          weekOrder: 2,
          programVersion: 4,
          performedDate: '2026-09-21',
        ),
        _trained(
          dayOrder: 2,
          weekOrder: 2,
          programVersion: 4,
          performedDate: '2026-09-22',
        ),
      ];

      final ProgramDay? next = selectNextDay(block, completed);

      expect((next?.weekOrder, next?.dayOrder), (2, 1));
    });
  });
}
