import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/exercise/exercise_detail_screen.dart';
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

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _pumpDetail(
  WidgetTester tester,
  FakeMayosApi fake,
  String exerciseId, {
  ThemeMode mode = ThemeMode.light,
  int? dayOrder = 1,
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
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
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
      child: MaterialApp(
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: mode,
        home: ExerciseDetailScreen(exerciseId: exerciseId, dayOrder: dayOrder),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Overview'));
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

void main() {
  testWidgets('Program exercise opens detail with prescription stats',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));
    await tester.tap(find.text('Bench Press'));
    await _pumpUntilFound(tester, find.text('RIR 1.5'));

    // Serif name, prescription trio, and muscle/equipment chips from the catalog.
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.text('3 × 5–8'), findsOneWidget);
    expect(find.text('RIR 1.5'), findsOneWidget);
    expect(find.text('180s'), findsOneWidget);
    // Title-cased catalog strings.
    expect(find.text('Chest'), findsWidgets);
    expect(find.text('Barbell'), findsWidgets);
    // Category and body part collapse into one row when equal.
    expect(find.text('Body part'), findsNothing);
  });

  testWidgets('technique tab renders instructions with an empty state fallback',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'bench_press');
    await tester.tap(find.text('Technique'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.textContaining('Lie on a flat bench'), findsOneWidget);
  });

  testWidgets('technique tab shows an honest empty state without instructions',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'machine_row', dayOrder: null);
    await tester.tap(find.text('Technique'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(
      find.text('Instructions aren\'t available for this exercise yet.'),
      findsOneWidget,
    );
  });

  testWidgets('history tab shows real points', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'bench_press');
    await tester.tap(find.text('History'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.textContaining('100 kg × 5'), findsOneWidget);
  });

  testWidgets('history tab shows an honest empty state', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'overhead_press', dayOrder: null);
    await tester.tap(find.text('History'));
    await tester.pump(const Duration(milliseconds: 200));
    expect(
      find.text(
          'No history for this exercise yet. Log a workout to see it here.'),
      findsOneWidget,
    );
  });

  testWidgets('media flag off renders no Image widgets', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'bench_press');
    expect(find.byType(Image), findsNothing);
    expect(find.text('Bench Press'), findsOneWidget);
  });

  testWidgets('exercise detail renders in both themes without overflow',
      (tester) async {
    for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
      final FakeMayosApi fake = _signedInFake();
      await _pumpDetail(tester, fake, 'bench_press', mode: mode);

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);

      final Brightness brightness = Theme.of(
        tester.element(find.text('Bench Press')),
      ).brightness;
      expect(brightness,
          mode == ThemeMode.dark ? Brightness.dark : Brightness.light);
    }
  });

  testWidgets('exercise detail has no overflow at 360x640 and text scale 2.0',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpDetail(tester, fake, 'bench_press', size: const Size(360, 640));
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await tester.pump(const Duration(milliseconds: 200));
    expect(tester.takeException(), isNull);
  });
}
