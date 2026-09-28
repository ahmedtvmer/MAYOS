import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches (never `pumpAndSettle`, which
/// never settles while a progress indicator is on screen).
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

Widget _app(FakeMayosApi fake, InMemoryTokenStore tokens) {
  return ProviderScope(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
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
  );
}

GoRouter _routerOf(WidgetTester tester) {
  final ProviderContainer container =
      ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
  return container.read(routerProvider);
}

Future<void> _openResetLink(WidgetTester tester, String url) async {
  _routerOf(tester).go(url);
  await _pumpUntilFound(tester, find.text('Set new password'));
}

void main() {
  testWidgets('App Link deep link opens the reset screen with the token',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(_app(fake, tokens));
    await _pumpUntilFound(tester, find.text('Log in'));

    // The full https URL arrives via Flutter's built-in deep linking; go_router
    // matches its path and the screen reads the token from the query string.
    await _openResetLink(
      tester,
      'https://mayos-api.fly.dev/reset-password?token=deep-link-token-1',
    );

    expect(find.text('Reset password'), findsOneWidget);
    expect(find.text('deep-link-token-1'), findsOneWidget);
  });

  testWidgets('a successful reset routes to login with a success message',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    fake.validResetToken = 'deep-link-token-1';
    // Seed a live session, so the reset must also clear the stored token.
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('old-session-token');
    fake.issuedToken = 'old-session-token';
    fake.currentUsername = 'alice';
    fake.profileExists = true;
    fake.recoveryEmail = 'alice@example.com';
    await tester.pumpWidget(_app(fake, tokens));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 100));
    expect(await tokens.read(), 'old-session-token');

    await _openResetLink(
      tester,
      'https://mayos-api.fly.dev/reset-password?token=deep-link-token-1',
    );
    final Finder fields = find.byType(TextField);
    await tester.enterText(fields.at(1), 'new-horse-123');
    await tester.enterText(fields.at(2), 'new-horse-123');
    await tester.tap(find.text('Set new password'));

    await _pumpUntilFound(
        tester, find.text('Password changed. Sign in with your new password.'));
    expect(find.text('Log in'), findsWidgets);
    expect(await tokens.read(), isNull);
  });

  testWidgets('a failed reset shows the service generic message',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    fake.validResetToken = 'the-real-token';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(_app(fake, tokens));
    await _pumpUntilFound(tester, find.text('Log in'));

    await _openResetLink(
      tester,
      'https://mayos-api.fly.dev/reset-password?token=stale-token',
    );
    final Finder fields = find.byType(TextField);
    await tester.enterText(fields.at(1), 'new-horse-123');
    await tester.enterText(fields.at(2), 'new-horse-123');
    await tester.tap(find.text('Set new password'));

    await _pumpUntilFound(tester, find.text('Invalid or expired reset code.'));
    // A new link can still be requested.
    expect(find.text('Request a new link'), findsOneWidget);
  });

  testWidgets('forgot-password flow shows the constant confirmation',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(_app(fake, tokens));
    await _pumpUntilFound(tester, find.text('Log in'));

    await tester.tap(find.text('Forgot password?'));
    await _pumpUntilFound(tester, find.text('Send reset link'));
    await tester.enterText(find.byType(TextField), 'alice@example.com');
    await tester.tap(find.text('Send reset link'));

    await _pumpUntilFound(tester, find.text(fake.resetConfirmation));
    expect(fake.forgotRequests, 1);
    expect(fake.lastForgotEmail, 'alice@example.com');
  });

  testWidgets('forgot-password offline shows the needs-connection message',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    fake.failOffline('POST', '/auth/forgot-password');
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tester.pumpWidget(_app(fake, tokens));
    await _pumpUntilFound(tester, find.text('Log in'));

    await tester.tap(find.text('Forgot password?'));
    await _pumpUntilFound(tester, find.text('Send reset link'));
    await tester.enterText(find.byType(TextField), 'alice@example.com');
    await tester.tap(find.text('Send reset link'));

    await _pumpUntilFound(tester, find.text(needsConnectionMessage));
  });
}
