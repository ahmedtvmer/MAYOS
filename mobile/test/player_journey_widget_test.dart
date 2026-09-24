import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches. Avoids `pumpAndSettle`, which
/// never settles while an indeterminate progress indicator is on screen. Once
/// found, pumps a few more frames so route transitions finish and the previous
/// screen is disposed before the test interacts.
Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 30}) async {
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

bool _sawOnboardingCall(FakeMayosApi fake) =>
    fake.adapter.requests.any((r) => r.path.startsWith('/onboarding'));

void main() {
  testWidgets('player journey renders through the real app and router',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();

    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: fake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: const MayosApp(),
      ),
    );

    // Startup resolves no token → login.
    await _pumpUntilFound(tester, find.text('Create an account'));

    // Register through the UI.
    await tester.tap(find.text('Create an account'));
    await _pumpUntilFound(tester, find.text('Create account'));
    final Finder fields = find.byType(TextField);
    await tester.enterText(fields.at(0), 'alice');
    await tester.enterText(fields.at(1), 'correct-horse-1');
    await tester.enterText(fields.at(2), 'correct-horse-1');
    await tester.tap(find.widgetWithText(FilledButton, 'Create account'));

    // ADR 007 gate: recovery email is required before any onboarding call.
    await _pumpUntilFound(tester, find.text('Recovery email'));
    expect(_sawOnboardingCall(fake), isFalse);

    // A server error is shown and does not unlock the gate.
    await tester.enterText(find.byType(TextField), 'not-an-email');
    await tester.tap(find.text('Save email'));
    await _pumpUntilFound(tester, find.text('Enter a valid email address.'));
    expect(_sawOnboardingCall(fake), isFalse);

    // A valid email unlocks the gate; the disclosure still blocks onboarding.
    await tester.enterText(find.byType(TextField), 'alice@example.com');
    await tester.tap(find.text('Save email'));
    await _pumpUntilFound(tester, find.text('Hosted AI processing'));
    expect(_sawOnboardingCall(fake), isFalse);

    // Consent, then onboarding begins.
    await tester.tap(find.text('Continue'));
    await _pumpUntilFound(tester, find.text('Set up your training'));
    expect(_sawOnboardingCall(fake), isTrue);

    // Answer onboarding until the program can be built.
    for (int i = 0;
        i < 4 && find.text('Build my program').evaluate().isEmpty;
        i++) {
      await tester.enterText(find.byType(TextField), 'Four days');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.tap(find.text('Build my program'));
    await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));

    // Completion panel is reachable, then Continue routes home via capabilities.
    expect(find.text('Continue'), findsOneWidget);
    await tester.tap(find.text('Continue'));
    await _pumpUntilFound(tester, find.text('Weekly weighted sets'));
    expect(find.text('Recent personal records'), findsOneWidget);

    // Switch to the program tab and see the full automatic program.
    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);

    // Warm-up, working-set details, and cardio are all rendered.
    expect(find.text('Warm-up'), findsOneWidget);
    expect(find.text('Band Pull-Apart'), findsOneWidget);
    expect(find.textContaining('Squeeze at the top.'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.textContaining('rest 180s'), findsOneWidget);
    expect(find.textContaining('Pause on the chest.'), findsOneWidget);
    expect(find.text('Cardio'), findsOneWidget);
    expect(find.text('10 min incline walk'), findsOneWidget);
  });
}
