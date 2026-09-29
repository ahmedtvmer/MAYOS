import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// Pumps frames until [finder] matches, avoiding `pumpAndSettle` (the app can
/// keep scheduling frames while an indicator is on screen).
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

void main() {
  testWidgets('an unknown path shows the not-found page',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');

    await tester.pumpWidget(authApp(fake, tokens));
    await _pumpUntilFound(tester, find.text('Home'));

    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
      listen: false,
    );
    container.read(routerProvider).go('/no-such-page');
    await _pumpUntilFound(tester, find.text('Page not found'));

    expect(find.text('Page not found'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Go to home'), findsOneWidget);

    // The way out asks nothing of the rules: the router places the user.
    await tester.tap(find.widgetWithText(FilledButton, 'Go to home'));
    await _pumpUntilFound(tester, find.text('Program'));
    expect(find.text('Page not found'), findsNothing);
  });
}
