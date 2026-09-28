import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/exercise/exercise_detail_screen.dart';
import 'package:mayos_mobile/src/features/player/progress/progress_tab.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

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

/// Five real-shaped Bench Press sessions, oldest first.
List<Map<String, dynamic>> _benchPoints() => <Map<String, dynamic>>[
      <String, dynamic>{
        'date': '2026-06-03',
        'weight_kg': 95.0,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 110.0,
      },
      <String, dynamic>{
        'date': '2026-06-10',
        'weight_kg': 97.5,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 112.9,
      },
      <String, dynamic>{
        'date': '2026-06-17',
        'weight_kg': 100.0,
        'reps': 5,
        'rpe': 8.0,
        'e1rm': 115.6,
      },
      <String, dynamic>{
        'date': '2026-06-24',
        'weight_kg': 102.5,
        'reps': 3,
        'rpe': 9.0,
        'e1rm': 116.8,
      },
      <String, dynamic>{
        'date': '2026-07-01',
        'weight_kg': 105.0,
        'reps': 3,
        'rpe': 9.0,
        'e1rm': 119.7,
      },
    ];

FakeMayosApi _signedInFake({int points = 5}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.dashboardExerciseHistories = <String, Map<String, dynamic>>{
    'bench_press': <String, dynamic>{
      'history': _benchPoints().take(points).toList(growable: false),
      'caption': null,
      'records': <dynamic>[],
    },
    'overhead_press': <String, dynamic>{
      'history': <Map<String, dynamic>>[
        <String, dynamic>{
          'date': '2026-06-05',
          'weight_kg': 40.0,
          'reps': 8,
          'rpe': 8.0,
          'e1rm': 50.0,
        },
      ],
      'caption': null,
      'records': <dynamic>[],
    },
  };
  return fake;
}

Override _apiOverride(FakeMayosApi fake, InMemoryTokenStore tokens) {
  return apiClientProvider.overrideWith((ref) {
    final ApiClient client = ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );
    client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
    return client;
  });
}

Future<void> _pumpProgress(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode mode = ThemeMode.light,
  Size size = const Size(1080, 2400),
  double textScale = 1.0,
  Finder? ready,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[_apiOverride(fake, tokens)],
      child: MaterialApp(
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: mode,
        home: const Scaffold(body: ProgressTab()),
      ),
    ),
  );
  await _pumpUntilFound(tester, ready ?? find.text('Estimated 1RM'));
}

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
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
}

Future<void> _openProgressTab(WidgetTester tester) async {
  await tester.tap(find.descendant(
    of: find.byType(MayosBottomNavigation),
    matching: find.text('Progress'),
  ));
  await _pumpUntilFound(tester, find.text('Estimated 1RM'));
}

void main() {
  testWidgets('strength maps real history into the chart, rows, and units',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(tester, fake);

    expect(find.text('Estimated 1RM'), findsOneWidget);
    expect(find.textContaining('Bench Press · kg'), findsOneWidget);
    expect(find.byKey(const Key('progress.chart')), findsOneWidget);
    // Recent-session rows carry the real values and dates (not the reference's).
    expect(find.textContaining('95 kg × 5 @ RIR 2'), findsOneWidget);
    expect(find.textContaining('Jun 3'), findsOneWidget);
    expect(find.textContaining('105 kg × 3 @ RIR 1'), findsOneWidget);
    expect(find.textContaining('e1RM 110'), findsOneWidget);
  });

  testWidgets('tapping a chart point shows that session\'s real values',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(tester, fake);

    // Tapping the chart centre selects the middle (third of five) session.
    await tester.tap(find.byKey(const Key('progress.chart')));
    await tester.pump(const Duration(milliseconds: 400));

    final Finder callout = find.byKey(const Key('progress.callout'));
    expect(callout, findsOneWidget);
    expect(
      find.descendant(
          of: callout, matching: find.textContaining('100 kg × 5 reps')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: callout, matching: find.textContaining('Jun 17')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: callout, matching: find.textContaining('e1RM 115.6')),
      findsOneWidget,
    );
  });

  testWidgets('selecting another logged exercise reloads its history',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(tester, fake);

    await tester.tap(find.byType(DropdownButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Overhead Press').last);
    await tester.pumpAndSettle();

    expect(
      fake.adapter.requests
          .any((request) => request.path.contains('overhead_press/history')),
      isTrue,
    );
    expect(find.textContaining('40 kg × 8'), findsOneWidget);
  });

  testWidgets('volume period switching requests days=7, 28, and 90',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(tester, fake);

    await tester.tap(find.text('Volume'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.volumeDaysRequests, contains(7));
    expect(find.textContaining('Last 7 days'), findsOneWidget);

    await tester.tap(find.text('28 days'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.volumeDaysRequests, contains(28));
    expect(find.textContaining('Last 28 days'), findsOneWidget);

    await tester.tap(find.text('90 days'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.volumeDaysRequests, contains(90));
    expect(find.textContaining('Last 90 days'), findsOneWidget);
  });

  testWidgets('volume shows weighted sets per muscle with numbers',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(tester, fake);
    await tester.tap(find.text('Volume'));
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.text('Weighted sets'), findsOneWidget);
    expect(find.text('Chest'), findsOneWidget);
    expect(find.text('12.5'), findsOneWidget);
    expect(find.textContaining('weighted sets'), findsWidgets);
  });

  testWidgets('a single session shows one marker and a trend explanation',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(points: 1);
    await _pumpProgress(tester, fake);

    expect(find.byKey(const Key('progress.chart')), findsOneWidget);
    expect(find.textContaining('at least two sessions'), findsOneWidget);
    expect(find.byKey(const Key('progress.callout')), findsNothing);
  });

  testWidgets('no history shows an honest empty state with a Program action',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.loggedExercises = <Map<String, dynamic>>[];
    await _pumpProgress(tester, fake);

    expect(find.text('No training history yet'), findsOneWidget);
    expect(find.text('Go to Program'), findsOneWidget);
    expect(find.byKey(const Key('progress.chart')), findsNothing);
  });

  testWidgets('no volume in the period shows a period-specific message',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.volumeEmpty = true;
    await _pumpProgress(tester, fake);
    await tester.tap(find.text('Volume'));
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.text('No weighted sets logged in the last 7 days.'),
        findsOneWidget);
  });

  testWidgets('offline first load shows the shared connectivity message',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.loggedExercisesFails = true;
    await _pumpProgress(tester, fake, ready: find.text(needsConnectionMessage));

    expect(find.text(needsConnectionMessage), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });

  testWidgets('View exercise opens the exercise detail History tab',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpApp(tester, fake);
    await _openProgressTab(tester);

    await tester.tap(find.text('View exercise'));
    await _pumpUntilFound(tester, find.text('History'));

    expect(find.byType(ExerciseDetailScreen), findsOneWidget);
    expect(find.text('History'), findsOneWidget);
    // The History tab is active and renders the same real ledger rows.
    expect(find.textContaining('95 kg × 5 @ RIR 2'), findsWidgets);
  });

  testWidgets('bottom navigation now exposes Home, Program, and Progress',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpApp(tester, fake);

    final MayosBottomNavigation nav = tester
        .widget<MayosBottomNavigation>(find.byType(MayosBottomNavigation));
    expect(nav.items.map((MayosNavItem item) => item.label),
        <String>['Home', 'Program', 'Progress']);
  });

  testWidgets('progress has no overflow at 360x640 and text scale 2.0',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgress(
      tester,
      fake,
      size: const Size(360, 640),
      textScale: 2.0,
    );
    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.takeException(), isNull);

    await tester.ensureVisible(find.text('Volume'));
    await tester.tap(find.text('Volume'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.takeException(), isNull);
  });

  testWidgets('progress chart renders in both themes',
      (WidgetTester tester) async {
    for (final ThemeMode mode in <ThemeMode>[
      ThemeMode.light,
      ThemeMode.dark,
    ]) {
      final FakeMayosApi fake = _signedInFake();
      await _pumpProgress(tester, fake, mode: mode);
      await tester.pump(const Duration(milliseconds: 400));

      expect(tester.takeException(), isNull);
      final Finder chart = find.byKey(const Key('progress.chart'));
      expect(chart, findsOneWidget);
      final Brightness brightness = Theme.of(tester.element(chart)).brightness;
      expect(brightness,
          mode == ThemeMode.dark ? Brightness.dark : Brightness.light);
    }
  });
}
