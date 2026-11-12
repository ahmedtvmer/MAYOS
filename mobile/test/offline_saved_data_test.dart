import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/connectivity.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/saved_player_data.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/dashboard/dashboard_tab.dart';
import 'package:mayos_mobile/src/features/player/tour/feature_list.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';
import 'support/in_memory_browser_key_value_store.dart';

Future<void> _primePlayerCache({
  WidgetTester? tester,
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required InMemoryBrowserKeyValueStore storage,
  required String language,
  List<Override> extraOverrides = const <Override>[],
}) async {
  fake.passwords['alice'] = 'password-123';
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.displayLanguage = language;
  fake.whatsNewSeenRelease = currentFeatureRelease;
  fake.foodLogToday = _today();
  // The fake intentionally returns 503 until a training status is supplied.
  fake.trainingStatusBody = <String, dynamic>{
    'weekly_streak': 2,
    'week_start': _today(),
    'week_done': 1,
    'week_target': 3,
    'mayos_workouts': 9,
    'next_checkpoint': 10,
    'workouts_to_next': 1,
  };
  fake.nutritionState = <String, dynamic>{
    'state': 'ready',
    'goal': 'maintain',
    'daily_activity': 'mostly_sitting',
    'targets': <String, dynamic>{
      'calories': 2345, 'protein_g': 160, 'carbs_g': 270,
      'fat_g': 70, 'fiber_g': 30, 'water_ml': 2500,
    },
  };

  // Real async work outside a pump never completes under testWidgets' fake
  // clock; the first test in this file paid lazy start-up costs there and hung.
  Future<void> prime() async {
    final ProviderContainer container = authContainerFor(
      fake,
      tokens,
      savedPlayerDataBrowser: storage,
      extraOverrides: extraOverrides,
    );
    try {
      await container.read(authControllerProvider.notifier).login(
            username: 'alice',
            password: 'password-123',
          );
      final ApiClient api = container.read(apiClientProvider);
      await api.activeProgram();
      await api.trainingSchedule();
      await api.volume();
      await api.personalRecords();
      await api.checkpointReviews();
      await api.myAssignment();
      await api.trainingStatus();
      await api.prescription(1);
      await api.nutrition();
      await api.foodLogDay();
      // Live responses do not wait for best-effort snapshot writes. Let the
      // final response finish saving before simulating another process.
      await Future<void>.delayed(Duration.zero);
      final Map<String, dynamic>? savedFoodLog = await container
          .read(savedPlayerDataStoreProvider)
          .read('account-alice', '/nutrition/food-log');
      expect(savedFoodLog, isNotNull);
      expect(savedFoodLog!['day'], _today());
      expect(savedFoodLog['body']['date'], fake.foodLogToday);
    } finally {
      container.dispose();
    }
  }

  if (tester == null) return prime();
  // runAsync reports exceptions to the binding and returns null. Stop here if
  // priming failed rather than exercising an incomplete snapshot offline.
  expect(await tester.runAsync(() async {
    await prime();
    return true;
  }), isTrue);
}
String _today() => DateTime.now().toIso8601String().substring(0, 10);

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int attempt = 0; attempt < attempts; attempt++) {
    if (finder.evaluate().isNotEmpty) {
      for (int frame = 0; frame < 4; frame++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<T> _waitWithPumps<T>(WidgetTester tester, Future<T> operation) async {
  bool completed = false;
  operation.then<void>((_) {
    completed = true;
  }, onError: (Object error) {
    completed = true;
  });
  for (int attempt = 0; attempt < 120 && !completed; attempt++) {
    await tester.pump(Duration.zero);
  }
  expect(completed, isTrue, reason: 'The async operation did not complete');
  return operation;
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues(<String, String>{}));

  for (final bool androidStorage in <bool>[false, true]) {
    for (final String language in <String>['en', 'ar']) {
      testWidgets('cold start shows saved Player data in $language with ${androidStorage ? 'Android' : 'web'} storage',
          (WidgetTester tester) async {
        final FakeMayosApi fake = FakeMayosApi();
        final InMemoryTokenStore tokens = InMemoryTokenStore();
        final InMemoryBrowserKeyValueStore storage =
            InMemoryBrowserKeyValueStore();
        final List<Override> overrides = <Override>[
          if (androidStorage)
            savedPlayerDataStoreProvider.overrideWith((ref) {
              final SavedPlayerDataStore store = SavedPlayerDataStore();
              ref.onDispose(store.dispose);
              return store;
            }),
          if (!androidStorage)
            offlineWorkoutDraftsEnabledProvider.overrideWithValue(false),
        ];
        await _primePlayerCache(
          tester: tester,
          fake: fake,
          tokens: tokens,
          storage: storage,
          language: language,
          extraOverrides: overrides,
        );
        fake.allRequestsOffline = true;

        await tester.pumpWidget(authApp(
          fake,
          tokens,
          savedPlayerDataBrowser: storage,
          extraOverrides: overrides,
        ));
        final MayosCopy copy = MayosCopy(language);
        await _pumpUntilFound(tester, find.text(copy.offlineSavedData));
        await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));

        expect(find.text(copy.offlineSavedData), findsOneWidget);
        expect(find.text(copy.home), findsWidgets);
        expect(find.text('Upper/Lower 4x'), findsWidgets);
        expect(find.byKey(const Key('login_username')), findsNothing);
        final ProviderContainer container = ProviderScope.containerOf(
          tester.element(find.byType(MayosApp)),
          listen: false,
        );
        final ApiClient api = container.read(apiClientProvider);
        // This store's queue was created by startup on the fake clock.
        // runAsync would pause that queue while waiting for its reads.
        expect((await _waitWithPumps(tester, api.volume()))['Chest'], 12.5);
        expect((await _waitWithPumps(tester, api.activeProgram()))?.programName,
            'Upper/Lower 4x');
        expect((await _waitWithPumps(tester, api.trainingStatus())).mayosWorkouts,
            9);
        expect((await _waitWithPumps(tester, api.prescription(1))).targets,
            isNotEmpty);
        expect((await _waitWithPumps(tester, api.nutrition())).targets?['calories'],
            2345);
        expect((await _waitWithPumps(tester, api.foodLogDay())).date,
            DateTime.parse(_today()));

        await tester.tap(find.text(copy.nutritionTab).last);
        await _pumpUntilFound(tester, find.text('2345'));
        expect(find.text('2345'), findsOneWidget);
        expect(find.text(copy.offlineSavedData), findsOneWidget);

        // Nutrition can mount CopyFoodMealButton on the last pumped frame.
        await tester.pump(Duration.zero);
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump(Duration.zero);
      });
    }
  }

  for (final bool androidEvents in <bool>[false, true]) {
    testWidgets('${androidEvents ? 'Android' : 'browser'} connectivity regain confirms session and refreshes Home',
        (WidgetTester tester) async {
      const MethodChannel networkChannel = MethodChannel('com.mayos/connectivity');
      final TargetPlatform? originalPlatform = debugDefaultTargetPlatformOverride;
      try {
        if (androidEvents) {
          debugDefaultTargetPlatformOverride = TargetPlatform.android;
          tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
            networkChannel,
            (MethodCall call) async => call.method == 'startListening' ? false : null,
          );
          addTearDown(() => tester.binding.defaultBinaryMessenger
              .setMockMethodCallHandler(networkChannel, null));
        }
        final FakeMayosApi fake = FakeMayosApi();
        final InMemoryTokenStore tokens = InMemoryTokenStore();
        final InMemoryBrowserKeyValueStore storage =
            InMemoryBrowserKeyValueStore();
        final StreamController<bool> browserEvents =
            StreamController<bool>.broadcast();
        addTearDown(browserEvents.close);
        await _primePlayerCache(
          tester: tester,
          fake: fake,
          tokens: tokens,
          storage: storage,
          language: 'en',
        );
        fake.allRequestsOffline = true;

        await tester.pumpWidget(authApp(
          fake,
          tokens,
          savedPlayerDataBrowser: storage,
          extraOverrides: <Override>[
            if (!androidEvents) browserConnectivityEventsProvider.overrideWithValue(
              browserEvents.stream,
            ),
          ],
        ));
        await _pumpUntilFound(tester, find.text(MayosCopy('en').offlineSavedData));
        if (!androidEvents) {
          browserEvents.add(false);
          await tester.pump(Duration.zero);
        }
        final int previousVolumeReads = fake.adapter.requests
            .where((FakeRequest request) => request.path == '/dashboard/volume')
            .length;

        fake.allRequestsOffline = false;
        fake.volumeByDays = <int, Map<String, dynamic>>{
          7: <String, dynamic>{'Chest': 99.0},
        };
        if (androidEvents) {
          tester.binding.channelBuffers.push(
            networkChannel.name,
            const StandardMethodCodec().encodeMethodCall(const MethodCall('changed', true)),
            (_) {},
          );
        } else {
          browserEvents.add(true);
        }
        for (int attempt = 0; attempt < 10; attempt++) {
          await tester.pump(const Duration(milliseconds: 100));
          final int currentVolumeReads = fake.adapter.requests
              .where((FakeRequest request) => request.path == '/dashboard/volume')
              .length;
          if (currentVolumeReads > previousVolumeReads) break;
        }

        final ProviderContainer container = ProviderScope.containerOf(
          tester.element(find.byType(MayosApp)),
          listen: false,
        );
        expect(container.read(authControllerProvider).isOffline, isFalse);
        expect(find.text(MayosCopy('en').offlineSavedData), findsNothing);
        expect(find.byKey(const Key('login_username')), findsNothing);
        await tester.scrollUntilVisible(find.text('99'), 250,
          scrollable: find.descendant(
            of: find.byType(DashboardTab), matching: find.byType(Scrollable),
          ).first,
        );
        expect(find.text('99'), findsOneWidget);
        expect(
          fake.adapter.requests
              .where((FakeRequest request) => request.path == '/dashboard/volume')
              .length,
          greaterThan(previousVolumeReads),
        );
      } finally {
        try {
          // Scrolling mounts CopyFoodMealButton, which starts a Dio request.
          // Complete its zero-duration interceptor timers while providers live.
          await tester.pump(Duration.zero);
          await tester.pumpWidget(const SizedBox.shrink());
          await tester.pump(Duration.zero);
        } finally {
          // Flutter checks foundation globals before addTearDown callbacks.
          debugDefaultTargetPlatformOverride = originalPlatform;
        }
      }
    });
  }

  testWidgets('401 after connectivity regain returns to sign in',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage =
        InMemoryBrowserKeyValueStore();
    final StreamController<bool> browserEvents =
        StreamController<bool>.broadcast();
    addTearDown(browserEvents.close);
    await _primePlayerCache(
      tester: tester,
      fake: fake,
      tokens: tokens,
      storage: storage,
      language: 'en',
    );
    fake.allRequestsOffline = true;

    await tester.pumpWidget(authApp(
      fake,
      tokens,
      savedPlayerDataBrowser: storage,
      extraOverrides: <Override>[
        browserConnectivityEventsProvider.overrideWithValue(
          browserEvents.stream,
        ),
      ],
    ));
    await _pumpUntilFound(tester, find.text(MayosCopy('en').offlineSavedData));

    fake.allRequestsOffline = false;
    fake.tokenValid = false;
    browserEvents.add(true);
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));

    expect(find.byKey(const Key('login_username')), findsOneWidget);
    expect(find.text(MayosCopy('en').offlineSavedData), findsNothing);
    expect(await _waitWithPumps(tester, tokens.read()), isNull);
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    expect(
      await _waitWithPumps(tester,
          container.read(savedPlayerDataStoreProvider).session('account-alice')),
      isNull,
    );

    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final bool accountDeleted in <bool>[false, true]) {
    test(
        'startup ${accountDeleted ? 'account_deleted' : '401'} clears session data',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryBrowserKeyValueStore storage =
          InMemoryBrowserKeyValueStore();
      await _primePlayerCache(
        fake: fake,
        tokens: tokens,
        storage: storage,
        language: 'en',
      );
      fake.accountDeleted = accountDeleted;
      fake.tokenValid = false;

      final ProviderContainer container = authContainerFor(
        fake,
        tokens,
        savedPlayerDataBrowser: storage,
      );
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);

      await auth.initialize();

      expect(container.read(authControllerProvider).status,
          AuthStatus.unauthenticated);
      expect(await tokens.read(), isNull);
      expect(
        await container
            .read(savedPlayerDataStoreProvider)
            .session('account-alice'),
        isNull,
      );
    });
  }

  test('saved snapshots stay scoped to the immutable account id', () async {
    final FakeMayosApi alice = FakeMayosApi();
    final InMemoryTokenStore aliceTokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage =
        InMemoryBrowserKeyValueStore();
    await _primePlayerCache(
      fake: alice,
      tokens: aliceTokens,
      storage: storage,
      language: 'en',
    );

    final FakeMayosApi bob = FakeMayosApi()
      ..issuedToken = 'token-bob'
      ..currentUsername = 'bob'
      ..allRequestsOffline = true;
    final InMemoryTokenStore bobTokens = InMemoryTokenStore();
    final String payload = base64Url.encode(utf8.encode(
      jsonEncode(<String, String>{'sub': 'account-bob'}),
    ));
    await bobTokens.save('header.$payload.signature');
    // Stale local metadata must never override the new bearer's subject.
    await bobTokens.saveAccountId('account-alice');
    final ProviderContainer bobContainer = authContainerFor(
      bob,
      bobTokens,
      savedPlayerDataBrowser: storage,
    );
    addTearDown(bobContainer.dispose);
    await bobContainer.read(authControllerProvider.notifier).initialize();
    expect(bobContainer.read(authControllerProvider).session, isNull);
    expect(
      await bobContainer
          .read(savedPlayerDataStoreProvider)
          .session('account-alice'),
      isNotNull,
    );
    expect(
      await bobContainer
          .read(savedPlayerDataStoreProvider)
          .session('account-bob'),
      isNull,
    );
    await expectLater(
      bobContainer.read(apiClientProvider).volume(),
      throwsA(isA<ApiException>()),
    );
  });

  for (final String exit in <String>['logout', 'clearSession', 'deleteAccount']) {
    test('$exit erases saved reads without erasing another account', () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryBrowserKeyValueStore storage =
          InMemoryBrowserKeyValueStore();
      await _primePlayerCache(
        fake: fake,
        tokens: tokens,
        storage: storage,
        language: 'en',
      );

      final ProviderContainer container = authContainerFor(
        fake,
        tokens,
        savedPlayerDataBrowser: storage,
      );
      addTearDown(container.dispose);
      await container.read(authControllerProvider.notifier).initialize();

      final FakeMayosApi bob = FakeMayosApi()
        ..passwords['bob'] = 'password-123'
        ..profileExists = true
        ..recoveryEmail = 'bob@example.com';
      final ProviderContainer bobContainer = authContainerFor(
        bob, InMemoryTokenStore(), savedPlayerDataBrowser: storage,
      );
      addTearDown(bobContainer.dispose);
      await bobContainer.read(authControllerProvider.notifier).login(
        username: 'bob', password: 'password-123',
      );
      await bobContainer.read(apiClientProvider).volume();

      switch (exit) {
        case 'logout':
          fake.allRequestsOffline = true;
          await container.read(authControllerProvider.notifier).logout();
        case 'clearSession':
          await container.read(authRepositoryProvider).clearSession();
        case 'deleteAccount':
          await container.read(authControllerProvider.notifier)
              .deleteAccount('password-123');
      }
      expect(
        await container.read(savedPlayerDataStoreProvider).session('account-alice'),
        isNull,
      );
      expect(await tokens.read(), isNull);
      expect(await container.read(savedPlayerDataStoreProvider)
          .read('account-alice', '/dashboard/volume'), isNull);
      bob.allRequestsOffline = true;
      expect((await bobContainer.read(apiClientProvider).volume())['Chest'], 12.5);
    });
  }

  test('late reads cannot recreate saved data after logout and same-account login',
      () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage = InMemoryBrowserKeyValueStore();
    await _primePlayerCache(
      fake: fake, tokens: tokens, storage: storage, language: 'en',
    );
    final ProviderContainer container = authContainerFor(
      fake, tokens, savedPlayerDataBrowser: storage,
    );
    addTearDown(container.dispose);
    final AuthController auth = container.read(authControllerProvider.notifier);
    await auth.initialize();
    final Completer<void> requestStarted = Completer<void>();
    final Completer<void> releaseResponse = Completer<void>();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/dashboard/volume') {
        requestStarted.complete();
        await releaseResponse.future;
      }
    };
    // Logout cancels this request; observe the rejection before teardown so it
    // cannot become an unhandled error while the next session signs in.
    final Future<void> oldRead = expectLater(
      container.read(apiClientProvider).volume(),
      throwsA(isA<ApiException>()),
    );
    await requestStarted.future;
    await auth.logout();
    await auth.login(username: 'alice', password: 'password-123');
    // FakeMayosApi issues the same opaque bearer again; account generations
    // must still reject the response that started before logout.
    releaseResponse.complete();
    await oldRead;
    fake.adapter.beforeRespond = null;
    fake.allRequestsOffline = true;
    await auth.initialize();
    expect(container.read(authControllerProvider).isAuthenticated, isTrue);
    await expectLater(container.read(apiClientProvider).volume(),
        throwsA(isA<ApiException>()));
  });

  testWidgets('failed startup confirmations back off without losing the session',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage = InMemoryBrowserKeyValueStore();
    await _primePlayerCache(
      tester: tester,
      fake: fake, tokens: tokens, storage: storage, language: 'en',
    );
    final ProviderContainer container = authContainerFor(
      fake, tokens, savedPlayerDataBrowser: storage,
    );
    try {
      fake.allRequestsOffline = true;
      int confirmations() => fake.adapter.requests
          .where((FakeRequest request) => request.path == '/auth/me').length;
      final int before = confirmations();
      await _waitWithPumps(tester,
          container.read(authControllerProvider.notifier).initialize());
      expect(confirmations(), before + 1);
      await tester.pump(const Duration(seconds: 2));
      await tester.pump(Duration.zero);
      expect(confirmations(), before + 2);
      await tester.pump(const Duration(seconds: 3));
      expect(confirmations(), before + 2);
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(Duration.zero);
      expect(confirmations(), before + 3);
      expect(container.read(authControllerProvider).isOffline, isTrue);
      expect(await _waitWithPumps(tester, tokens.read()), isNotNull);
    } finally {
      container.dispose();
    }
  });

  test('a server refusal does not authenticate from saved data', () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage = InMemoryBrowserKeyValueStore();
    await _primePlayerCache(
      fake: fake, tokens: tokens, storage: storage, language: 'en',
    );
    final ProviderContainer container = authContainerFor(
      fake, tokens, savedPlayerDataBrowser: storage,
    );
    addTearDown(container.dispose);
    fake.meRefusalStatus = 403;
    await container.read(authControllerProvider.notifier).initialize();
    expect(container.read(authControllerProvider).isAuthenticated, isFalse);
    expect(container.read(authControllerProvider).isOffline, isFalse);
    expect(await tokens.read(), isNotNull);
    expect(
      await container
          .read(savedPlayerDataStoreProvider)
          .session('account-alice'),
      isNotNull,
    );
    fake.allRequestsOffline = true;
    final ApiClient api = container.read(apiClientProvider);
    await expectLater(api.changeWaterGlasses(undo: false),
        throwsA(isA<ApiException>()));
    expect(fake.waterGlasses, 0);
    expect((await api.nutrition()).todayWaterGlasses, 0);
  });

  test('a 5xx while the service restarts keeps the saved session', () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage = InMemoryBrowserKeyValueStore();
    await _primePlayerCache(
      fake: fake, tokens: tokens, storage: storage, language: 'en',
    );
    final ProviderContainer container = authContainerFor(
      fake, tokens, savedPlayerDataBrowser: storage,
    );
    addTearDown(container.dispose);
    fake.meFails = true;
    await container.read(authControllerProvider.notifier).initialize();
    expect(container.read(authControllerProvider).isAuthenticated, isTrue);
    expect(await tokens.read(), isNotNull);
  });

}
