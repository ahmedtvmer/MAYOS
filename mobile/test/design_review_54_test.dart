import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/login_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/recovery_email_screen.dart';
import 'package:mayos_mobile/src/features/player/auth/register_screen.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_screen.dart';
import 'package:mayos_mobile/src/features/player/progress/progress_chart.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';

/// Visual-verification tests for #54: the offline-Home fallback, the chart's
/// rounded ticks and edge padding, and a text-scale 2.0 / both-theme sweep of
/// every captured screen at 360x640.

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
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

FakeMayosApi _fake({bool coach = false}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  return fake;
}

List<Override> _appOverrides({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required ThemeMode mode,
  DraftStore? draftStore,
  WorkoutCacheStore? cacheStore,
  ChatCacheStore? chatCache,
}) {
  return <Override>[
    tokenStoreProvider.overrideWithValue(tokens),
    themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
    draftStoreProvider.overrideWithValue(draftStore ?? InMemoryDraftStore()),
    workoutCacheStoreProvider
        .overrideWithValue(cacheStore ?? InMemoryWorkoutCacheStore()),
    chatCacheStoreProvider
        .overrideWithValue(chatCache ?? InMemoryChatCacheStore()),
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
  ];
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode mode = ThemeMode.light,
  DraftStore? draftStore,
  WorkoutCacheStore? cacheStore,
  ChatCacheStore? chatCache,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: _appOverrides(
        fake: fake,
        tokens: tokens,
        mode: mode,
        draftStore: draftStore,
        cacheStore: cacheStore,
        chatCache: chatCache,
      ),
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

/// Relayouts the current screen at 2.0x text and [size], asserting no
/// overflow/exception.
Future<void> _assertNoOverflowAt2x(WidgetTester tester, Size size) async {
  tester.platformDispatcher.textScaleFactorTestValue = 2.0;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  tester.view.physicalSize = size;
  await tester.pump(const Duration(milliseconds: 350));
  expect(tester.takeException(), isNull);
}

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

Future<void> _tapSettingsTile(
    WidgetTester tester, String tile, Finder ready) async {
  await tester.tap(find.text(tile));
  await _pumpUntilFound(tester, ready);
}

const Size _small = Size(360, 640);

void main() {
  group('offline Home', () {
    testWidgets('serves the cached program and renders the next session',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _fake()
        ..activeProgramFails = true
        ..latestSessionFails = true;
      final InMemoryWorkoutCacheStore cacheStore = InMemoryWorkoutCacheStore();
      const TrainingProgram cached = TrainingProgram(
        programName: 'Cached Split',
        splitType: 'Upper/Lower',
        weeklyFrequency: 2,
        days: <ProgramDay>[
          ProgramDay(
            dayName: 'Upper 1',
            dayOrder: 1,
            exercises: <ProgramExercise>[
              ProgramExercise(
                exerciseId: 'bench_press',
                exerciseName: 'Bench Press',
                targetSets: 3,
                targetRepsMin: 5,
                targetRepsMax: 8,
                targetRpe: 8.5,
              ),
            ],
          ),
          ProgramDay(
            dayName: 'Lower 1',
            dayOrder: 2,
            exercises: <ProgramExercise>[
              ProgramExercise(
                exerciseId: 'squat',
                exerciseName: 'Squat',
                targetSets: 3,
                targetRepsMin: 5,
                targetRepsMax: 8,
                targetRpe: 8.5,
              ),
            ],
          ),
        ],
      );
      await cacheStore.writeProgram('account-alice', cached);
      await cacheStore.writeLatestSession(
        'account-alice',
        const LatestSession(
          sessionId: 's1',
          sessionDate: '2026-09-26',
          splitName: 'Upper 1',
          dayOrder: 1,
        ),
      );

      await _pumpApp(tester, fake, cacheStore: cacheStore);
      await _pumpUntilFound(tester, find.text('Lower 1'));

      // Next session is derived from the cached latest session (#54).
      expect(find.textContaining('Next session'), findsOneWidget);
      expect(find.text('Lower 1'), findsOneWidget);
      expect(
          find.text('Offline — showing your saved program.'), findsOneWidget);
    });
  });

  group('progress axis ticks', () {
    test('rounds the bounds and gridlines to whole numbers', () {
      final AxisTicks ticks = niceAxisTicks(110.0, 119.7);
      expect(ticks.min, 110);
      expect(ticks.max, 120);
      expect(ticks.values, <double>[110, 115, 120]);
    });

    test('uses a nice step for a wider span and never leaves decimals', () {
      final AxisTicks ticks = niceAxisTicks(114.8, 120.7);
      expect(ticks.min <= 114.8, isTrue);
      expect(ticks.max >= 120.7, isTrue);
      for (final double value in ticks.values) {
        expect(value, value.roundToDouble());
      }
    });

    test('a flat series still gets a padded, rounded axis', () {
      final AxisTicks ticks = niceAxisTicks(110.0, 110.0);
      expect(ticks.max > ticks.min, isTrue);
      for (final double value in ticks.values) {
        expect(value, value.roundToDouble());
      }
    });
  });

  testWidgets('chart draws a fully visible edge marker and selects it',
      (WidgetTester tester) async {
    int? selected;
    await tester.pumpWidget(
      MaterialApp(
        theme: MayosTheme.light,
        home: Scaffold(
          body: SizedBox(
            width: 328,
            child: ProgressLineChart(
              points: const <ProgressChartPoint>[
                ProgressChartPoint(date: '2026-06-03', value: 110),
                ProgressChartPoint(date: '2026-06-17', value: 115.6),
                ProgressChartPoint(date: '2026-07-01', value: 119.7),
              ],
              metricLabel: 'Estimated 1RM',
              unit: 'kg',
              exerciseName: 'Bench Press',
              onPointSelected: (int index) => selected = index,
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 400));
    // Tap the far right edge; the hit test must resolve to the last point.
    final Size size = tester.getSize(find.byType(ProgressLineChart));
    await tester.tapAt(tester.getTopLeft(find.byType(ProgressLineChart)) +
        Offset(size.width - 1, 120));
    await tester.pump();
    expect(selected, 2);
    expect(tester.takeException(), isNull);
  });

  group('chat composer docking', () {
    Future<void> pumpShortChat(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(() => tester.view.padding = const FakeViewPadding());
      addTearDown(() => tester.view.viewInsets = const FakeViewPadding());

      final FakeMayosApi fake = _fake();
      fake.chatHistory.addAll(<Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'chat-1',
          'role': 'user',
          'content': 'How should I warm up for bench press?',
          'created_at': '2026-09-26T12:00:00Z',
        },
        <String, dynamic>{
          'id': 'chat-2',
          'role': 'assistant',
          'content': 'Ramp with the empty bar, then your working weight.',
          'created_at': '2026-09-26T12:00:01Z',
        },
      ]);
      final InMemoryChatCacheStore chatCache = InMemoryChatCacheStore();
      await chatCache.writeDisclosureAccepted('account-alice');
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await tokens.save('token-alice');
      await tester.pumpWidget(
        ProviderScope(
          overrides: _appOverrides(
            fake: fake,
            tokens: tokens,
            mode: ThemeMode.light,
            chatCache: chatCache,
          ),
          child: const MayosApp(),
        ),
      );
      await _pumpUntilFound(tester, find.text('Home'));
      await tester.tap(find.byIcon(Icons.chat_bubble_outline));
      await _pumpUntilFound(
          tester, find.text('How should I warm up for bench press?'));
      tester.view.physicalSize = const Size(412, 915);
      await tester.pump(const Duration(milliseconds: 200));
    }

    testWidgets('docks to the bottom safe area with a short history at 412x915',
        (WidgetTester tester) async {
      await pumpShortChat(tester);
      tester.view.padding = const FakeViewPadding(bottom: 48);
      await tester.pump(const Duration(milliseconds: 200));

      final Rect bar =
          tester.getRect(find.byKey(const Key('chat_composer_bar')));
      // The composer sits on the safe-area edge, not floating mid-screen.
      expect(bar.bottom, lessThanOrEqualTo(915 - 48 + 1));
      expect(bar.bottom, greaterThanOrEqualTo(915 - 48 - 1));
      // The message history fills the space above it.
      expect(bar.top, greaterThan(0));
      expect(tester.takeException(), isNull);
    });

    testWidgets('stays above a simulated keyboard inset at 412x915',
        (WidgetTester tester) async {
      await pumpShortChat(tester);
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump(const Duration(milliseconds: 200));

      final Rect bar =
          tester.getRect(find.byKey(const Key('chat_composer_bar')));
      expect(bar.bottom, lessThanOrEqualTo(915 - 300 + 1));
      expect(tester.takeException(), isNull);
    });
  });

  test('docs/design-review/54/README.md links all resolve', () {
    final File readme = File(
        '${Directory.current.parent.path}/docs/design-review/54/README.md');
    expect(readme.existsSync(), isTrue, reason: 'review artifact missing');
    final RegExp link = RegExp(r'\]\(([^)]+)\)');
    int checked = 0;
    for (final RegExpMatch match in link.allMatches(readme.readAsStringSync())) {
      final String target = match.group(1)!;
      if (target.startsWith('http')) {
        continue;
      }
      checked++;
      final File resolved = File('${readme.parent.path}/$target');
      expect(resolved.existsSync(), isTrue, reason: 'missing file: $target');
    }
    expect(checked, greaterThan(30),
        reason: 'expected the index to link to the captured screens');
  });

  // -------------------------------------------------------------------------
  // Text-scale 2.0 sweep of every captured screen at 360x640, both themes.
  // -------------------------------------------------------------------------

  for (final ThemeMode mode in const <ThemeMode>[
    ThemeMode.light,
    ThemeMode.dark,
  ]) {
    final String theme = mode == ThemeMode.dark ? 'dark' : 'light';

    testWidgets('54 sweep splash $theme', (WidgetTester tester) async {
      tester.view.physicalSize = _small;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pumpWidget(
        MaterialApp(
          theme: MayosTheme.light,
          darkTheme: MayosTheme.dark,
          themeMode: mode,
          home: const SplashScreen(),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
    });

    for (final (String name, String path, Widget screen)
        in <(String, String, Widget)>[
      ('login', loginPath, const LoginScreen()),
      ('register', registerPath, const RegisterScreen()),
      ('recovery-email', recoveryEmailPath, const RecoveryEmailScreen()),
    ]) {
      testWidgets('54 sweep auth $name $theme', (WidgetTester tester) async {
        tester.view.physicalSize = _small;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        tester.platformDispatcher.textScaleFactorTestValue = 2.0;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final InMemoryTokenStore tokens = InMemoryTokenStore();
        await tester.pumpWidget(
          ProviderScope(
            overrides: _appOverrides(
              fake: _fake(),
              tokens: tokens,
              mode: mode,
            ),
            child: MaterialApp.router(
              theme: MayosTheme.light,
              darkTheme: MayosTheme.dark,
              themeMode: mode,
              routerConfig: GoRouter(
                initialLocation: path,
                routes: <RouteBase>[
                  GoRoute(
                    path: path,
                    builder: (BuildContext context, GoRouterState state) =>
                        screen,
                  ),
                ],
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 300));
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('54 sweep onboarding proportions and numeric $theme',
        (WidgetTester tester) async {
      tester.view.physicalSize = _small;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final FakeMayosApi fake = FakeMayosApi();
      fake.issuedToken = 'token-alice';
      fake.currentUsername = 'alice';
      fake.tokenValid = true;
      fake.profileExists = false;
      fake.intakeDisclosureAcknowledged = true;
      fake.intakeAnswers.addAll(<String, Object>{
        'gender': 'female',
        'proportions': 'long_legs',
      });
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await tokens.save('token-alice');
      await tester.pumpWidget(
        ProviderScope(
          overrides: _appOverrides(fake: fake, tokens: tokens, mode: mode),
          child: MaterialApp(
            theme: MayosTheme.light,
            darkTheme: MayosTheme.dark,
            themeMode: mode,
            home: const OnboardingScreen(),
          ),
        ),
      );
      await _pumpUntilFound(tester, find.byKey(const Key('age_increment')));
      expect(tester.takeException(), isNull);
    });

    testWidgets('54 sweep home $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep program $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Log workout'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep progress $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await tester.tap(find.text('Progress'));
      await _pumpUntilFound(tester, find.text('Estimated 1RM'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep settings $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(coach: true), mode: mode);
      await _openSettings(tester);
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep chat $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await tester.tap(find.byIcon(Icons.chat_bubble_outline));
      await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep workout logger $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Log workout'));
      await tester.tap(find.text('Log workout'));
      await _pumpUntilFound(tester, find.text('Performed date'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep workout drafts $theme', (WidgetTester tester) async {
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      await draftStore.write('account-alice', <WorkoutDraft>[
        WorkoutDraft(
          clientSessionId: 'sweep-1',
          accountId: 'account-alice',
          performedDate: '2026-09-26',
          performedTimezone: 'UTC',
          programVersion: 1,
          dayOrder: 1,
          dayName: 'Upper 1',
          capturedAt: '2026-09-26T11:00:00.000Z',
          exercises: <DraftExercise>[
            DraftExercise(
              exercise: <String, dynamic>{
                'exercise_id': 'bench_press',
                'exercise_name': 'Bench Press',
                'target_sets': 3,
                'target_reps_min': 5,
                'target_reps_max': 8,
                'target_rpe': 8.5,
                'rest_seconds': 180,
                'notes': null,
              },
              sets: const <WorkoutSetLog>[
                WorkoutSetLog(weightKg: 100, reps: 5, rpe: 8),
              ],
            ),
          ],
          readiness: 4,
          updatedAt: '2026-09-26T11:00:00.000Z',
        ),
      ]);
      await _pumpApp(tester, _fake()..commitFails = true,
          mode: mode, draftStore: draftStore);
      await _openSettings(tester);
      await _tapSettingsTile(
          tester, 'Workout drafts', find.textContaining('pending'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep profile $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await _openSettings(tester);
      await _tapSettingsTile(tester, 'Profile', find.text('Training profile'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep plan $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await _openSettings(tester);
      await _tapSettingsTile(
          tester, 'Plan', find.textContaining('Lifter and Coach'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep assignment $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(), mode: mode);
      await _openSettings(tester);
      await _tapSettingsTile(
          tester, 'Coaching assignment', find.text('Coach assignment'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep coach profile $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(coach: true), mode: mode);
      await tester.tap(find.text('Profile'));
      await _pumpUntilFound(tester, find.text('These details describe you'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep coach alerts $theme', (WidgetTester tester) async {
      await _pumpApp(tester, _fake(coach: true), mode: mode);
      await tester.tap(find.text('Alerts'));
      await _pumpUntilFound(tester, find.textContaining('No alerts'));
      await _assertNoOverflowAt2x(tester, _small);
    });

    testWidgets('54 sweep coach assignments $theme',
        (WidgetTester tester) async {
      await _pumpApp(tester, _fake(coach: true), mode: mode);
      await _pumpUntilFound(tester, find.text('Active assignments'));
      await _assertNoOverflowAt2x(tester, _small);
    });
  }
}
