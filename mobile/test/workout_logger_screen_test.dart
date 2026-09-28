import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/performed_date_window.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

const String _account = 'account-alice';

const Map<String, dynamic> _benchJson = <String, dynamic>{
  'exercise_id': 'bench_press',
  'exercise_name': 'Bench Press',
  'target_sets': 3,
  'target_reps_min': 5,
  'target_reps_max': 8,
  'target_rpe': 8.5,
  'rest_seconds': 180,
  'notes': null,
};

const Map<String, dynamic> _inclineJson = <String, dynamic>{
  'exercise_id': 'incline_press',
  'exercise_name': 'Incline Press',
  'target_sets': 1,
  'target_reps_min': 8,
  'target_reps_max': 12,
  'target_rpe': 8.0,
  'rest_seconds': 120,
  'notes': null,
};

ActiveWorkout _seedWorkout({
  List<ActiveWorkoutExercise>? exercises,
  Map<String, BaselineExercise>? baselines,
}) =>
    ActiveWorkout(
      id: 'aw-seed',
      accountId: _account,
      startedAt: '2026-09-28T08:00:00.000Z',
      dayOrder: 2,
      dayName: 'Upper A',
      programVersion: 3,
      exercises: exercises ??
          const <ActiveWorkoutExercise>[
            ActiveWorkoutExercise(
              exercise: _benchJson,
              sets: <ActiveWorkoutSet>[
                ActiveWorkoutSet(),
                ActiveWorkoutSet(),
                ActiveWorkoutSet(),
              ],
            ),
            ActiveWorkoutExercise(
              exercise: _inclineJson,
              sets: <ActiveWorkoutSet>[ActiveWorkoutSet()],
            ),
          ],
      baselines: baselines ?? _defaultBaselines(),
    );

Map<String, BaselineExercise> _defaultBaselines() =>
    <String, BaselineExercise>{
      'bench_press': const BaselineExercise(
        exerciseId: 'bench_press',
        sessionsLogged: 3,
        maxWeightKg: 100,
        bestE1rmKg: 121.67,
        lastSession: BaselineLastSession(
          performedDate: '2026-09-26',
          sets: <BaselineSet>[
            BaselineSet(weightKg: 100, reps: 5, rir: 1),
            BaselineSet(weightKg: 95, reps: 6, rir: 2),
          ],
        ),
      ),
      'incline_press': const BaselineExercise(
        exerciseId: 'incline_press',
        sessionsLogged: 1,
        maxWeightKg: 40,
        bestE1rmKg: 53.33,
        lastSession: BaselineLastSession(
          performedDate: '2026-09-26',
          // An unrated previous set: the label drops the `@` part.
          sets: <BaselineSet>[BaselineSet(weightKg: 40, reps: 10, rir: null)],
        ),
      ),
    };

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

/// The signed-in app with a stored Active workout, opened through the
/// app-open Resume prompt — the real entry into the table logger (#123).
Future<void> _openLogger(
  WidgetTester tester, {
  required ActiveWorkout seed,
  InMemoryDraftStore? drafts,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final FakeMayosApi fake = _signedInFake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
  await store.write(_account, seed);

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
        draftStoreProvider.overrideWithValue(drafts ?? InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        activeWorkoutStoreProvider.overrideWithValue(store),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('UTC')),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.pumpAndSettle();
  expect(find.text('Unfinished workout'), findsOneWidget);
  await tester.tap(find.text('Resume'));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
  await tester.pumpAndSettle();
}

Finder _cell(int exercise, int set, String field) => find.byKey(
    ValueKey<String>('logger.cell.$exercise.$set.$field'));

Finder _tick(int exercise, int set) =>
    find.byKey(ValueKey<String>('logger.tick.$exercise.$set'));

Color _textColor(WidgetTester tester, Finder finder) => tester
    .widget<Text>(find.descendant(of: finder, matching: find.byType(Text)))
    .style!
    .color!;

void main() {
  testWidgets('PREVIOUS is matched set by set and shows — with none',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    expect(find.text('100 × 5 @1'), findsOneWidget);
    expect(find.text('95 × 6 @2'), findsOneWidget);
    // The third bench set has no previous working set…
    expect(find.text('—'), findsOneWidget);
    // …and an unrated previous set drops the `@` part (planned alike).
    expect(find.text('40 × 10'), findsOneWidget);
    // Header columns from the #107 resolution.
    for (final String label in <String>['SET', 'PREVIOUS', 'KG', 'REPS', 'RIR']) {
      expect(find.text(label), findsWidgets);
    }
    // The Unplanned tag only where it applies: none of the planned cards.
    expect(find.text('Unplanned'), findsNothing);
  });

  testWidgets('ticking an empty row fills it from the previous values',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    final MayosThemeExtension c = MayosThemeExtension.light;
    // Before the tick the cells are empty hints (muted).
    expect(_textColor(tester, _cell(0, 0, 'kg')), c.textDisabled);

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.descendant(of: _cell(0, 0, 'kg'), matching: find.text('100')),
        findsOneWidget);
    expect(find.descendant(of: _cell(0, 0, 'reps'), matching: find.text('5')),
        findsOneWidget);
    expect(find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('1')),
        findsOneWidget);
    // Filled, not hinted: the values now read as real values.
    expect(_textColor(tester, _cell(0, 0, 'kg')), c.textPrimary);
    // No keypad was needed.
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('ticking with no value and no previous opens the keypad there',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    // Bench set 3 has no previous working set, so the tick cannot fill it.
    await tester.tap(_tick(0, 2));
    await tester.pump(const Duration(milliseconds: 100));

    expect(
      find.text('Bench Press · set 3 · Weight (kg)'),
      findsOneWidget,
    );
    // The row was not ticked.
    expect(_textColor(tester, _cell(0, 2, 'kg')), MayosThemeExtension.light.textDisabled);

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.hide')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('the keypad Next order is kg → reps → RIR → the next set',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    await tester.tap(_cell(0, 0, 'kg'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Weight (kg)'), findsOneWidget);
    expect(find.text('.'), findsOneWidget); // kg keypad carries the dot

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Reps'), findsOneWidget);
    expect(find.text('.'), findsNothing); // …reps does not

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 1 · Reps in reserve'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Bench Press · set 2 · Weight (kg)'), findsOneWidget);

    // Walk the remaining order: set 2 reps/rir, set 3 kg/reps/rir, then the
    // final Next hides the keypad.
    for (int i = 0; i < 6; i++) {
      await tester.tap(find.byKey(const ValueKey<String>('logger.key.next')));
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('Bench Press · set 3 · Reps in reserve'), findsNothing);
    expect(find.text('Hide'), findsNothing);
  });

  testWidgets('the RIR keypad is one-tap chips 0–5 and Unrated',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    await tester.tap(_cell(0, 0, 'rir'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Unrated'), findsOneWidget);
    expect(find.text('.'), findsNothing);

    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.2')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('2')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 0, 'rir')),
        MayosThemeExtension.light.textPrimary);
    // The chip does not move on its own; Next walks to the next set's kg.
    expect(find.text('Bench Press · set 1 · Reps in reserve'), findsOneWidget);

    // Unrated clears the effort back to the previous-value hint.
    await tester.tap(find.byKey(const ValueKey<String>('logger.rir.unrated')));
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      find.descendant(of: _cell(0, 0, 'rir'), matching: find.text('1')),
      findsOneWidget,
    );
    expect(_textColor(tester, _cell(0, 0, 'rir')),
        MayosThemeExtension.light.textDisabled);
  });

  testWidgets('tapping the SET number cycles N ↔ W and mutes the row',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    final Finder label = find.byKey(const ValueKey<String>('logger.setlabel.0.0'));
    expect(_textColor(tester, label), MayosThemeExtension.light.textPrimary);

    await tester.tap(label);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsOneWidget);
    expect(_textColor(tester, label), MayosThemeExtension.light.textMuted);

    await tester.tap(label);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('W'), findsNothing);
    expect(_textColor(tester, label), MayosThemeExtension.light.textPrimary);
  });

  testWidgets('Finish with nothing ticked is blocked by Log at least one set',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    await tester.tap(finish);
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Log at least one set'), findsOneWidget);
    expect(find.text('Performed date'), findsNothing);
  });

  testWidgets('the unticked-sets sheet offers Keep logging and Discard',
      (WidgetTester tester) async {
    await _openLogger(tester, seed: _seedWorkout());

    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();

    // Four rows, one ticked.
    expect(find.text("3 sets aren't ticked"), findsOneWidget);

    await tester.tap(find.text('Keep logging'));
    await tester.pumpAndSettle();
    expect(find.text("3 sets aren't ticked"), findsNothing);
    expect(find.text('Performed date'), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();
    expect(find.text('Performed date'), findsOneWidget);
    expect(find.text('Save workout'), findsWidgets);

    // Back from the save step returns to the Active workout.
    await tester.tap(find.byKey(const ValueKey<String>('logger.save.back')));
    await tester.pumpAndSettle();
    expect(find.text('Performed date'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Finish workout'), findsOneWidget);
  });

  testWidgets(
      'the saved draft matches today\'s shape: ticked sets, warm-up flag, skipped exercise',
      (WidgetTester tester) async {
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    await _openLogger(tester, seed: _seedWorkout(), drafts: drafts);

    // Bench set 1 ticked, bench set 2 ticked as a warm-up; the rest unticked.
    await tester.tap(_tick(0, 0));
    await tester.pump(const Duration(milliseconds: 100));
    await tester
        .tap(find.byKey(const ValueKey<String>('logger.setlabel.0.1')));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(_tick(0, 1));
    await tester.pump(const Duration(milliseconds: 100));

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    // bench set 3 + the incline exercise are unticked.
    expect(find.text("2 sets aren't ticked"), findsOneWidget);
    await tester.tap(find.text('Discard unticked sets and finish'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'felt strong');
    await tester.tap(find.widgetWithText(FilledButton, 'Save workout'));
    await _pumpUntilFound(tester, find.text('Workouts'));

    final List<WorkoutDraft> saved = await drafts.read(_account);
    expect(saved, hasLength(1));
    final WorkoutDraft draft = saved.single;

    // The scalar shape the logger has always written.
    expect(draft.dayOrder, 2);
    expect(draft.dayName, 'Upper A');
    expect(draft.programVersion, 3);
    expect(draft.performedTimezone, 'UTC');
    expect(
      draft.performedDate,
      formatPerformedDate(DateTime.parse('2026-09-28T08:00:00.000Z').toLocal()),
    );
    expect(draft.readiness, 4);
    expect(draft.notes, 'felt strong');

    // Only ticked sets are logged; the warm-up flag travels with its set; an
    // exercise with no ticked set is `skipped`.
    final List<Map<String, dynamic>> expected = <Map<String, dynamic>>[
      DraftExercise(
        exercise: _benchJson,
        sets: const <WorkoutSetLog>[
          WorkoutSetLog(weightKg: 100, reps: 5, rpe: 9.0),
          WorkoutSetLog(weightKg: 95, reps: 6, rpe: 8.0, isWarmup: true),
        ],
      ).toJson(),
      DraftExercise(exercise: _inclineJson, sets: const <WorkoutSetLog>[],
              skipped: true)
          .toJson(),
    ];
    expect(
      jsonEncode(draft.exercises
          .map((DraftExercise exercise) => exercise.toJson())
          .toList()),
      jsonEncode(expected),
    );
  });
}
