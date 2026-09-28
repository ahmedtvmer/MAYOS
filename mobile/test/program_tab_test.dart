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

Future<void> _pumpProgram(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode mode = ThemeMode.light,
  Size size = const Size(1080, 2400),
}) async {
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
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
  await tester.pump(const Duration(milliseconds: 400));
  await tester.tap(find.text('Program'));
  await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));

  // Resize after navigating so the layout is exercised at the target size
  // without depending on bottom-bar hit-testing at the small viewport.
  if (size != const Size(1080, 2400)) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  testWidgets('program overview shows real days, prescriptions, and provenance',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpProgram(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);
    expect(find.text('Version 6'), findsOneWidget);
    expect(find.text('Former coach'), findsOneWidget);

    // The expanded first day sections warm-up, working sets, and cardio.
    expect(find.text('Warm-up'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.textContaining('3 × 5–8'), findsOneWidget);
    expect(find.text('Cardio'), findsOneWidget);
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets('program renders in ${mode.name} theme without overflow',
        (tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

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
