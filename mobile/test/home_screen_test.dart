import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';

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

Future<void> _pumpHome(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeModeStore? themeStore,
  Size size = const Size(1080, 2400),
}) async {
  tester.view.physicalSize = size;
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
        themeModeStoreProvider
            .overrideWithValue(themeStore ?? InMemoryThemeModeStore()),
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

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

void main() {
  testWidgets('home maps the active program, volume, and records',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);

    // The weekly schedule (Mon/Wed/Fri) drives the next-session label.
    expect(find.textContaining('Next session ·'), findsOneWidget);

    // Volume muscles and a personal record are real values.
    expect(find.text('Chest'), findsOneWidget);
    expect(find.text('Back'), findsOneWidget);
    expect(find.text('120 kg × 5'), findsOneWidget);
  });

  testWidgets('home shows honest empty states without data', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.noActiveProgram = true;
    fake.scheduleEmpty = true;
    fake.volumeEmpty = true;
    fake.recordsEmpty = true;
    await _pumpHome(tester, fake);

    expect(find.text('No active program'), findsOneWidget);
    expect(
      find.text('Generate a program to see your next session here.'),
      findsOneWidget,
    );
    expect(find.text('Go to Program'), findsOneWidget);
    // With no program there is no next session at all — not even a placeholder.
    expect(find.text('Next session'), findsNothing);
    expect(find.text('No training day is scheduled yet.'), findsNothing);
    expect(find.text('No sets logged in the last 7 days.'), findsOneWidget);
    expect(find.text('No personal records yet.'), findsOneWidget);
  });

  testWidgets('the no-program action opens the Program tab', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.noActiveProgram = true;
    fake.scheduleEmpty = true;
    fake.volumeEmpty = true;
    fake.recordsEmpty = true;
    await _pumpHome(tester, fake);

    await tester.tap(find.text('Go to Program'));
    await _pumpUntilFound(tester, find.text('Regenerate program'));
    expect(find.text('Regenerate program'), findsOneWidget);
  });

  testWidgets('home reads the latest committed session from the ledger',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.latestSessionBody = <String, dynamic>{
      'session_id': 'sess-1',
      'session_date': '2026-09-20',
      'split_name': 'Upper 1',
      'day_order': null,
      'program_version': 1,
    };
    await _pumpHome(tester, fake);

    expect(
      fake.adapter.requests
          .any((request) => request.path == '/workouts/sessions/latest'),
      isTrue,
    );
    expect(find.text('Upper 1'), findsOneWidget);
  });

  testWidgets('home opens an unopened Checkpoint review and clears its card',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..checkpointReviewRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'checkpoint': 10,
          'period_start': '2026-01-01',
          'period_end': '2026-09-30',
          'rating': <Map<String, dynamic>>[
            <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
          ],
          'opened': false,
        },
      ]
      ..checkpointReviewDetails[10] = <String, dynamic>{
        'checkpoint': 10,
        'period_start': '2026-01-01',
        'period_end': '2026-09-30',
        'facts': <String, dynamic>{'workouts_in_period': 10},
        'rating': <Map<String, dynamic>>[
          <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
        ],
        'text': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'text_is_template': true,
      };
    await _pumpHome(tester, fake);

    expect(find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
        findsOneWidget);
    await tester.tap(
      find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
    );
    await _pumpUntilFound(tester, find.text('Your 10th workout'));
    expect(find.text('Consistency'), findsOneWidget);
    expect(find.text('Strong'), findsOneWidget);
    expect(
      find.text(
        'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
      ),
      findsOneWidget,
    );

    await tester.pageBack();
    await _pumpUntilFound(
      tester,
      find.byType(MayosBottomNavigation),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
        findsNothing);
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets('home renders in ${mode.name} theme without overflow',
        (tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpHome(
        tester,
        fake,
        themeStore: InMemoryThemeModeStore(mode),
        size: const Size(360, 640),
      );

      // Let the home data and the persisted theme settle before checking for
      // layout overflow at the largest supported text scale.
      await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));
      expect(
        Theme.of(tester.element(find.text('Upper/Lower 4x'))).brightness,
        mode == ThemeMode.dark ? Brightness.dark : Brightness.light,
      );

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });
  }
}
