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
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_analytics_client.dart';
import 'support/fake_mayos_api.dart';

const String _account = 'account-alice';

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

ActiveWorkout _storedWorkout() => ActiveWorkout(
      id: 'aw-stored',
      accountId: _account,
      startedAt: '2026-09-28T08:00:00.000Z',
      dayOrder: 2,
      dayName: 'Upper A',
      programVersion: 3,
      exercises: <ActiveWorkoutExercise>[
        ActiveWorkoutExercise(
          exercise: <String, dynamic>{
            'exercise_id': 'bench_press',
            'exercise_name': 'Bench Press',
            'target_sets': 2,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.5,
            'rest_seconds': 180,
            'notes': null,
          },
          sets: <ActiveWorkoutSet>[
            ActiveWorkoutSet(weightKg: 100, reps: 5, rir: 1, ticked: true),
          ],
        ),
      ],
      baselines: <String, BaselineExercise>{},
    );

/// The signed-in app with a pre-seeded device store, so the Active workout
/// is "already there" when the shell opens.
Future<ProviderContainer> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake,
  InMemoryActiveWorkoutStore store, {
  FakeAnalyticsClient? analytics,
}
) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        activeWorkoutStoreProvider.overrideWithValue(store),
        analyticsClientProvider.overrideWithValue(
          analytics ?? FakeAnalyticsClient(),
        ),
        // The logger resolves the device timezone through a platform channel
        // no test host implements; inject a value like the logger's own tests.
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
  return ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
}

void main() {
  testWidgets('opening the app offers Resume or Discard for a stored workout',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await store.write(_account, _storedWorkout());
    final ProviderContainer container = await _pumpApp(
      tester,
      _signedInFake(),
      store,
      analytics: analytics,
    );

    await tester.pumpAndSettle();
    expect(find.text('Unfinished workout'), findsOneWidget);
    expect(find.textContaining('Upper A'), findsOneWidget);

    await tester.tap(find.text('Discard'));
    await tester.pumpAndSettle();

    expect(find.text('Unfinished workout'), findsNothing);
    expect(await store.read(_account), isNull);
    expect(
      analytics.events.where((Map<String, Object> event) =>
          event['event'] == 'workout_draft_discarded'),
      hasLength(1),
    );
    expect(
      container.read(activeWorkoutControllerProvider).hasWorkout,
      isFalse,
    );
  });

  testWidgets('Resume routes to the logger', (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
    await store.write(_account, _storedWorkout());
    await _pumpApp(tester, _signedInFake(), store);

    await tester.pumpAndSettle();
    expect(find.text('Unfinished workout'), findsOneWidget);

    await tester.tap(find.text('Resume'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    // The stored workout survives a resume: nothing was discarded.
    expect(await store.read(_account), isNotNull);
  });

  testWidgets(
      'starting a workout while one exists asks to finish or discard it first',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
    await store.write(_account, _storedWorkout());
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpApp(tester, _signedInFake(), store, analytics: analytics);

    // Defer the app-open offer: tapping outside dismisses it, and a
    // dismissed prompt is a cancel — nothing is discarded or started (#123
    // item 13).
    await tester.pumpAndSettle();
    expect(find.text('Unfinished workout'), findsOneWidget);
    expect(find.text('Not now'), findsNothing);
    await tester.tapAt(const Offset(20, 20));
    await tester.pumpAndSettle();

    // Starting another workout hits the guard instead of silently replacing.
    final Finder logWorkout = find.text('Log workout');
    await tester.ensureVisible(logWorkout);
    await tester.tap(logWorkout);
    await tester.pumpAndSettle();

    expect(find.text('Finish your current workout'), findsOneWidget);
    expect(find.text('Unfinished workout'), findsNothing);

    await tester.tap(find.text('Discard'));
    await tester.pumpAndSettle();

    // The old workout is gone, a new one was started, and the logger opened.
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    final ActiveWorkout? current = await store.read(_account);
    expect(current, isNotNull);
    expect(current!.id, isNot('aw-stored'));
    expect(
      analytics.events.where((Map<String, Object> event) =>
          event['event'] == 'workout_started'),
      hasLength(1),
    );
    expect(
      analytics.events.where((Map<String, Object> event) =>
          event['event'] == 'workout_draft_discarded'),
      hasLength(1),
    );
  });
}
