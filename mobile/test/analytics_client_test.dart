import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/analytics_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_analytics_client.dart';
import 'support/fake_google_auth.dart';
import 'support/fake_mayos_api.dart';

void main() {
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
}
