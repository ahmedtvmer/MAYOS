import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/connectivity.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_app_header.dart';
import 'package:mayos_mobile/src/core/ui/mayos_scaffold.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_widgets.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

/// Pumps frames until [finder] matches, avoiding `pumpAndSettle`.
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

ProviderContainer _container(FakeApiAdapter adapter) {
  final ProviderContainer container = ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
      apiClientProvider.overrideWith((ref) => ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: adapter,
          )),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

void main() {
  test('a transport failure marks offline and the next response online',
      () async {
    int calls = 0;
    final FakeApiAdapter adapter = FakeApiAdapter((FakeRequest request) {
      calls += 1;
      if (calls == 1) {
        return const FakeResponse.networkFailure();
      }
      if (calls == 3) {
        // A service refusal has a status code: it is not a connectivity change.
        return const FakeResponse(500, <String, dynamic>{'detail': 'down'});
      }
      return const FakeResponse(200, <String, dynamic>{});
    });
    final ProviderContainer container = _container(adapter);
    expect(container.read(connectivityControllerProvider), isTrue);

    await expectLater(container.read(apiClientProvider).logout(),
        throwsA(isA<ApiException>()));
    expect(container.read(connectivityControllerProvider), isFalse);

    await container.read(apiClientProvider).logout();
    expect(container.read(connectivityControllerProvider), isTrue);

    await expectLater(container.read(apiClientProvider).logout(),
        throwsA(isA<ApiException>()));
    expect(container.read(connectivityControllerProvider), isTrue);
  });

  test('a service refusal after a transport failure means back online',
      () async {
    int calls = 0;
    final FakeApiAdapter adapter = FakeApiAdapter((FakeRequest request) {
      calls += 1;
      return calls == 1
          ? const FakeResponse.networkFailure()
          : const FakeResponse(500, <String, dynamic>{'detail': 'down'});
    });
    final ProviderContainer container = _container(adapter);
    container.read(connectivityControllerProvider);

    await expectLater(container.read(apiClientProvider).logout(),
        throwsA(isA<ApiException>()));
    expect(container.read(connectivityControllerProvider), isFalse);

    await expectLater(container.read(apiClientProvider).logout(),
        throwsA(isA<ApiException>()));
    expect(container.read(connectivityControllerProvider), isTrue);
  });

  testWidgets('the offline banner shows while offline and clears when online',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    await tester.pumpWidget(authApp(
      fake,
      tokens,
      extraOverrides: <Override>[
        offlineBannerEnabledProvider.overrideWithValue(true),
      ],
    ));
    await _pumpUntilFound(tester, find.text('Home'));
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    container.read(routerProvider).go('/no-such-page');
    await _pumpUntilFound(tester, find.text('Page not found'));
    expect(find.text(OfflineBanner.message), findsNothing);

    container.read(connectivityControllerProvider.notifier).markOffline();
    await tester.pump();
    expect(find.text(OfflineBanner.message), findsOneWidget);

    container.read(connectivityControllerProvider.notifier).markOnline();
    await tester.pump();
    expect(find.text(OfflineBanner.message), findsNothing);
  });

  testWidgets('browser events drive the banner below the app header',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final StreamController<bool> browserEvents =
        StreamController<bool>.broadcast();
    addTearDown(browserEvents.close);

    await tester.pumpWidget(authApp(
      fake,
      tokens,
      extraOverrides: <Override>[
        offlineBannerEnabledProvider.overrideWithValue(true),
        browserConnectivityEventsProvider.overrideWithValue(
          browserEvents.stream,
        ),
      ],
    ));
    await _pumpUntilFound(tester, find.text('Home'));
    expect(find.text(OfflineBanner.message), findsNothing);

    browserEvents.add(false);
    await tester.pump();
    await tester.pump();
    expect(find.text(OfflineBanner.message), findsOneWidget);

    final Rect header = tester.getRect(find.byType(MayosAppHeader));
    final Rect banner = tester.getRect(find.byType(OfflineBanner));
    final Rect body = tester.getRect(find.byKey(MayosScaffold.bodyContentKey));
    expect(banner.top, greaterThanOrEqualTo(header.bottom));
    expect(banner.bottom, lessThanOrEqualTo(body.top));

    browserEvents.add(true);
    await tester.pump();
    await tester.pump();
    expect(find.text(OfflineBanner.message), findsNothing);
  });

  testWidgets('the auth banner is at the top of content and keeps its slot',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final StreamController<bool> browserEvents =
        StreamController<bool>.broadcast();
    addTearDown(browserEvents.close);
    await tester.pumpWidget(authApp(
      fake,
      InMemoryTokenStore(),
      extraOverrides: <Override>[
        offlineBannerEnabledProvider.overrideWithValue(true),
        browserConnectivityEventsProvider.overrideWithValue(
          browserEvents.stream,
        ),
      ],
    ));
    await _pumpUntilFound(tester, find.byKey(const Key('login_username')));

    browserEvents.add(false);
    await tester.pump();
    await tester.pump();
    expect(find.byType(OfflineBanner), findsOneWidget);
    expect(
      tester.getRect(find.byType(OfflineBanner)).bottom,
      lessThanOrEqualTo(tester.getRect(find.byType(AuthHeading)).top),
    );

    final Finder editable = find.descendant(
      of: find.byKey(const Key('login_username')),
      matching: find.byType(EditableText),
    );
    final State<EditableText> fieldState = tester.state(editable);
    await tester.tap(find.byKey(const Key('login_username')));
    await tester.pump();
    browserEvents.add(true);
    await tester.pump();
    expect(tester.state<State<EditableText>>(editable), same(fieldState));
  });

  testWidgets('no banner without the web flag, even when offline',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    // The flag defaults to `!kIsWeb`, so a test run on the VM keeps the
    // Android surface: no banner, whatever the connectivity says.
    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.text('Home'));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    container.read(connectivityControllerProvider.notifier).markOffline();
    await tester.pump();
    expect(find.text(OfflineBanner.message), findsNothing);
  });
}
