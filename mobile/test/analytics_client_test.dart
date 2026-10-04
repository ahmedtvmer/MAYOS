import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/analytics_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_analytics_client.dart';
import 'support/fake_google_auth.dart';
import 'support/fake_mayos_api.dart';

void main() {
  test('fake analytics records calls while disabled', () {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient()
      ..setEnabled(false);

    analytics.identify('account-alice', role: 'player');
    analytics.onboardingStepViewed('disclosure');

    expect(analytics.identifiedAccountIds, <String>['account-alice']);
    expect(analytics.events, hasLength(1));
  });

  test('analytics stays disabled outside release builds or without a key', () {
    expect(
      createAnalyticsClient(
        isRelease: false,
        clientKey: 'phc_public_client_key',
        isWeb: false,
      ),
      isA<NoOpAnalyticsClient>(),
    );
    expect(
      createAnalyticsClient(
        isRelease: true,
        clientKey: '  ',
        isWeb: true,
      ),
      isA<NoOpAnalyticsClient>(),
    );
    expect(
      analyticsEnabledForBuild(isRelease: false, clientKey: 'phc_key'),
      isFalse,
    );
    expect(
      analyticsEnabledForBuild(isRelease: true, clientKey: ''),
      isFalse,
    );
    expect(
      analyticsEnabledForBuild(
        isRelease: true,
        clientKey: 'phc_public_client_key',
      ),
      isTrue,
    );
  });

  testWidgets(
      'account-info identifies the account id through the injected client',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..currentUsername = 'alice'
      ..issuedToken = 'token-alice';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await tester.pumpWidget(authApp(api, tokens, analytics: analytics));

    for (int attempt = 0;
        attempt < 30 && analytics.identifiedAccountIds.isEmpty;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(analytics.identifiedAccountIds, <String>['account-alice']);
    expect(analytics.identifiedRoles, <String>['player']);
  });

  testWidgets('sign-out resets the analytics identity',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..currentUsername = 'alice'
      ..issuedToken = 'token-alice';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final FakeGoogleAuthGateway google = FakeGoogleAuthGateway();
    final ProviderContainer container = authContainerFor(
      api,
      tokens,
      analytics: analytics,
      google: google,
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MayosApp(),
      ),
    );

    for (int attempt = 0;
        attempt < 30 && analytics.identifiedAccountIds.isEmpty;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(analytics.identifiedAccountIds, <String>['account-alice']);

    final Future<void> logout =
        container.read(authControllerProvider.notifier).logout();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await logout;

    expect(analytics.resetAccountIds, <String>['account-alice']);
  });

  testWidgets('Settings preference gates analytics and survives sign-in',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..currentUsername = 'alice'
      ..issuedToken = 'token-alice'
      ..analyticsAllowed = false
      ..recoveryEmail = 'alice@example.com'
      ..profileExists = true;
    api.passwords['alice'] = 'password-123';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final ProviderContainer container = authContainerFor(
      api,
      tokens,
      analytics: analytics,
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MayosApp(),
      ),
    );

    for (int attempt = 0;
        attempt < 30 &&
            container.read(authControllerProvider).status !=
                AuthStatus.authenticated;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(analytics.enabled, isFalse);
    expect(analytics.identifiedAccountIds, isEmpty);
    expect(analytics.events, isEmpty);

    container.read(routerProvider).go(settingsPath);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    final Finder preferenceSwitch = find.descendant(
      of: find.byKey(const Key('analytics_preference_switch')),
      matching: find.byType(Switch),
    );
    await tester.scrollUntilVisible(
      preferenceSwitch,
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.ensureVisible(preferenceSwitch);
    await tester.pump();
    expect(tester.widget<Switch>(preferenceSwitch).value, isFalse);

    await tester.tap(preferenceSwitch);
    for (int attempt = 0; attempt < 30 && !api.analyticsAllowed; attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(api.analyticsAllowed, isTrue);
    expect(analytics.enabled, isTrue);
    expect(analytics.identifiedAccountIds, <String>['account-alice']);

    await tester.tap(preferenceSwitch);
    for (int attempt = 0; attempt < 30 && api.analyticsAllowed; attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(api.analyticsAllowed, isFalse);
    expect(analytics.enabled, isFalse);
    expect(analytics.identifiedAccountIds, <String>['account-alice']);
    expect(analytics.events, isEmpty);
    expect(
      api.adapter.requests
          .where((request) => request.path == '/auth/analytics-preference')
          .map((request) => request.body['analytics_allowed']),
      <Object?>[true, false],
    );

    final Future<void> logout =
        container.read(authControllerProvider.notifier).logout();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await logout;
    expect(analytics.enabled, isTrue);

    final AuthController authController =
        container.read(authControllerProvider.notifier);
    bool loginComplete = false;
    final Future<void> login = authController
        .login(username: 'alice', password: 'password-123')
        .whenComplete(() => loginComplete = true);
    for (int attempt = 0; attempt < 40 && !loginComplete; attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(loginComplete, isTrue);
    await login;
    for (int attempt = 0; attempt < 10; attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(api.analyticsAllowed, isFalse);
    expect(analytics.enabled, isFalse);
    expect(analytics.identifiedAccountIds, <String>['account-alice']);
    expect(analytics.events, isEmpty);
    container.read(draftSyncServiceProvider).stop();
  });

  testWidgets('opted-out onboarding does not identify or capture',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..currentUsername = 'alice'
      ..issuedToken = 'token-alice'
      ..analyticsAllowed = false
      ..recoveryEmail = 'alice@example.com';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final ProviderContainer container = authContainerFor(
      api,
      tokens,
      analytics: analytics,
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MayosApp(),
      ),
    );

    final Finder disclosureContinue =
        find.byKey(const Key('onboarding_disclosure_continue'));
    for (int attempt = 0;
        attempt < 60 && disclosureContinue.evaluate().isEmpty;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(disclosureContinue, findsOneWidget);
    expect(analytics.enabled, isFalse);
    expect(analytics.identifiedAccountIds, isEmpty);
    expect(analytics.events, isEmpty);
    container.read(draftSyncServiceProvider).stop();
  });
}
