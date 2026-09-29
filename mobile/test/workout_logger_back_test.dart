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
import 'package:mayos_mobile/src/features/player/dashboard/dashboard_tab.dart';
import 'package:mayos_mobile/src/features/player/program/program_tab.dart';
import 'package:mayos_mobile/src/features/player/shell/player_shell.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

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

/// The signed-in app, optionally with a pre-seeded Active workout, so the
/// logger can be entered from Home, Program, or the Resume prompt (#156).
Future<ProviderContainer> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  InMemoryActiveWorkoutStore? store,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  final InMemoryActiveWorkoutStore activeStore =
      store ?? InMemoryActiveWorkoutStore();
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
        activeWorkoutStoreProvider.overrideWithValue(activeStore),
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
  await tester.pumpAndSettle();
  return ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
}

/// The logger entry point inside the shell tab [tabIndex] — scoped to the tab
/// so the same label on the other tab is never ambiguous.
Finder _logWorkoutIn(int tabIndex) => find.descendant(
      of: find.byType(tabIndex == 0 ? DashboardTab : ProgramTab),
      matching: find.text('Log workout'),
    );

void main() {
  testWidgets('starting from Home: the back arrow returns Home',
      (WidgetTester tester) async {
    final ProviderContainer container =
        await _pumpApp(tester, _signedInFake());

    await tester.tap(_logWorkoutIn(0));
    await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
    await tester.pumpAndSettle();
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);

    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(find.byType(PlayerShell), findsOneWidget);
    expect(container.read(playerShellTabProvider), 0);
  });

  testWidgets('starting from Program: the back arrow returns Program',
      (WidgetTester tester) async {
    final ProviderContainer container =
        await _pumpApp(tester, _signedInFake());

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));
    await tester.tap(_logWorkoutIn(1));
    await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
    await tester.pumpAndSettle();
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);

    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(find.byType(PlayerShell), findsOneWidget);
    expect(container.read(playerShellTabProvider), 1);
  });

  testWidgets('Resume from the prompt: the back arrow returns Home',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
    await store.write(_account, _storedWorkout());
    final ProviderContainer container =
        await _pumpApp(tester, _signedInFake(), store: store);

    expect(find.text('Unfinished workout'), findsOneWidget);
    await tester.tap(find.text('Resume'));
    await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
    await tester.pumpAndSettle();
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);

    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(find.byType(PlayerShell), findsOneWidget);
    expect(container.read(playerShellTabProvider), 0);
    // The Active workout is untouched, so it is still resumable.
    expect(await store.read(_account), isNotNull);
  });

  testWidgets('cold start with nothing underneath: the back arrow goes Home',
      (WidgetTester tester) async {
    final ProviderContainer container =
        await _pumpApp(tester, _signedInFake());

    // A deep link opens the logger with no page below it: the shell is
    // replaced, exactly the stack `go` used to leave behind (#156).
    container.read(routerProvider).go('$logWorkoutPath/2');
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    expect(find.byType(PlayerShell), findsNothing);

    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(find.byType(PlayerShell), findsOneWidget);
    expect(container.read(playerShellTabProvider), 0);
  });

  testWidgets('the summary step still intercepts back for the Active workout',
      (WidgetTester tester) async {
    final InMemoryActiveWorkoutStore store = InMemoryActiveWorkoutStore();
    await store.write(_account, _storedWorkout());
    final ProviderContainer container =
        await _pumpApp(tester, _signedInFake(), store: store);

    await tester.tap(find.text('Resume'));
    await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Finish workout'));
    await tester.pumpAndSettle();
    expect(find.text('Workout summary'), findsOneWidget);

    // The shared header arrow reaches the logger's PopScope first: the
    // summary steps back to the Active workout instead of leaving (#156).
    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.text('Workout summary'), findsNothing);
    expect(find.byType(WorkoutLoggerScreen), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Finish workout'), findsOneWidget);

    // From the Active workout the same arrow now leaves the logger.
    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkoutLoggerScreen), findsNothing);
    expect(find.byType(PlayerShell), findsOneWidget);
    expect(container.read(playerShellTabProvider), 0);
    expect(await store.read(_account), isNotNull);
  });
}
