import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';
import 'support/in_memory_browser_key_value_store.dart';

Future<void> _primePlayerCache({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required InMemoryBrowserKeyValueStore storage,
  required String language,
}) async {
  fake.passwords['alice'] = 'password-123';
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.displayLanguage = language;
  fake.whatsNewSeenRelease = 6;
  fake.foodLogToday = _today();

  final ProviderContainer container = authContainerFor(
    fake,
    tokens,
    savedPlayerDataBrowser: storage,
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
    await api.prescription(1);
    await api.nutrition();
    await api.foodLogDay();
  } finally {
    container.dispose();
  }
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

void main() {
  for (final String language in <String>['en', 'ar']) {
    testWidgets('cold start shows saved Player data in $language',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryBrowserKeyValueStore storage =
          InMemoryBrowserKeyValueStore();
      await _primePlayerCache(
        fake: fake,
        tokens: tokens,
        storage: storage,
        language: language,
      );
      fake.allRequestsOffline = true;

      await tester.pumpWidget(authApp(
        fake,
        tokens,
        savedPlayerDataBrowser: storage,
      ));
      final MayosCopy copy = MayosCopy(language);
      await _pumpUntilFound(tester, find.text(copy.offlineSavedData));
      await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));

      expect(find.text(copy.offlineSavedData), findsOneWidget);
      expect(find.text(copy.home), findsWidgets);
      expect(find.text('Upper/Lower 4x'), findsOneWidget);
      expect(find.text('Bench Press'), findsWidgets);
      expect(find.byKey(const Key('login_username')), findsNothing);
      final ProviderContainer container = ProviderScope.containerOf(
        tester.element(find.byType(MayosApp)),
        listen: false,
      );
      final ApiClient api = container.read(apiClientProvider);
      expect((await api.volume())['Chest'], 12.5);
      expect((await api.activeProgram())?.programName, 'Upper/Lower 4x');
      expect((await api.prescription(1)).targets, isNotEmpty);
      expect((await api.nutrition()).state, 'not_started');
      expect((await api.foodLogDay()).date, DateTime.parse(_today()));

      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('connectivity regain confirms session and refreshes Home',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final InMemoryBrowserKeyValueStore storage =
        InMemoryBrowserKeyValueStore();
    final StreamController<bool> browserEvents =
        StreamController<bool>.broadcast();
    addTearDown(browserEvents.close);
    await _primePlayerCache(
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
    final int previousVolumeReads = fake.adapter.requests
        .where((FakeRequest request) => request.path == '/dashboard/volume')
        .length;

    fake.allRequestsOffline = false;
    browserEvents.add(true);
    for (int attempt = 0; attempt < 60; attempt++) {
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
    expect(
      fake.adapter.requests
          .where((FakeRequest request) => request.path == '/dashboard/volume')
          .length,
      greaterThan(previousVolumeReads),
    );

    await tester.pumpWidget(const SizedBox.shrink());
  });

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
    expect(await tokens.read(), isNull);
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    expect(
      await container
          .read(savedPlayerDataStoreProvider)
          .session('account-alice'),
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
      fake.tokenValid = !accountDeleted;

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
    await bobTokens.save('token-bob');
    await bobTokens.saveAccountId('account-bob');
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

  test('logout clears the saved account snapshot', () async {
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
    await container.read(authControllerProvider.notifier).logout();
    expect(
      await container.read(savedPlayerDataStoreProvider).session('account-alice'),
      isNull,
    );
  });

}
