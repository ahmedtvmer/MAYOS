import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_pro_gate.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

Future<ProviderContainer> _pumpGate(WidgetTester tester, String plan) async {
  final FakeMayosApi fake = FakeMayosApi()
    ..coach = true
    ..coachPlan = plan
    ..profileExists = true
    ..recoveryEmail = 'coach@example.com'
    ..currentUsername = 'coach'
    ..issuedToken = 'token-coach'
    ..tokenValid = true;
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-coach');
  final ProviderContainer container = authContainerFor(fake, tokens);
  await tester.runAsync(
    () => container.read(authControllerProvider.notifier).initialize(),
  );
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(
        home: Scaffold(
          body: CoachProGate(
            child: Text('Pro-only placeholder', key: Key('pro-placeholder')),
          ),
        ),
      ),
    ),
  );
  return container;
}

void main() {
  testWidgets('hides the Pro-only placeholder for a Free Coach plan',
      (WidgetTester tester) async {
    final ProviderContainer container = await _pumpGate(tester, 'free');
    addTearDown(container.dispose);

    expect(find.byKey(const Key('pro-placeholder')), findsNothing);
  });

  testWidgets('shows the Pro-only placeholder for a Pro Coach plan',
      (WidgetTester tester) async {
    final ProviderContainer container = await _pumpGate(tester, 'pro');
    addTearDown(container.dispose);

    expect(find.byKey(const Key('pro-placeholder')), findsOneWidget);
  });
}
