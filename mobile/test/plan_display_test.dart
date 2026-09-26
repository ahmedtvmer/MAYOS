import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so route
/// transitions settle without depending on `pumpAndSettle`.
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

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
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
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Dashboard'));
}

/// A signed-in, onboarded player with a recovery email, optionally a coach.
FakeMayosApi _signedInFake({required bool coach}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _openPlan(WidgetTester tester) async {
  await tester.tap(find.byTooltip('Plan'));
  await _pumpUntilFound(tester, find.text('Lifter Free'));
}

void main() {
  test('missing server plan state cannot be inferred as Free', () {
    expect(
      () => Account.fromJson(<String, dynamic>{
        'account_id': 'account-alice',
        'trainee_id': 'alice',
        'capabilities': <String, dynamic>{'player': true, 'coach': true},
      }),
      throwsFormatException,
    );
  });

  test('Account parses independent Lifter and Coach plan states', () {
    final Account account = Account.fromJson(<String, dynamic>{
      'account_id': 'account-alice',
      'trainee_id': 'alice',
      'capabilities': <String, dynamic>{'player': true, 'coach': true},
      'plans': <String, dynamic>{
        'lifter': <String, dynamic>{'plan': 'pro', 'status': 'active'},
        'coach': <String, dynamic>{'plan': 'free', 'status': 'active'},
      },
    });

    expect(account.plans.lifter!.isPro, isTrue);
    expect(account.plans.coach!.isFree, isTrue);
    // Dropping the coach capability drops only the Coach plan.
    expect(account.plans.withoutCoach().coach, isNull);
    expect(account.plans.withoutCoach().lifter!.isPro, isTrue);
  });

  testWidgets('single-capability player sees Lifter Free and honest benefits',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    await _pumpApp(tester, fake);
    await _openPlan(tester);

    expect(find.text('Lifter Free'), findsOneWidget);
    expect(find.text('Coach Free'), findsNothing);
    expect(find.text('Ongoing plan — not a trial.'), findsOneWidget);
    for (final String benefit in <String>[
      'Automatic training program',
      'Weekly volume and personal-record dashboard',
      'Coaching assignment with your coach',
    ]) {
      expect(find.text(benefit), findsOneWidget);
    }

    // Truthful core Free: no claim of features still unbuilt.
    expect(find.textContaining('logging'), findsNothing);
    expect(find.textContaining('history'), findsNothing);
    expect(find.textContaining('alert'), findsNothing);
    expect(find.textContaining('publish'), findsNothing);
  });

  testWidgets('dual-capability account sees independent Lifter and Coach plans',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);
    await _openPlan(tester);

    expect(find.text('Lifter Free'), findsOneWidget);
    expect(find.text('Coach Free'), findsOneWidget);
    expect(find.text('Coach profile and player invite codes'), findsOneWidget);
    expect(find.text('Active roster with assignment status'), findsOneWidget);
    expect(find.text('Automatic training program'), findsOneWidget);
  });

  testWidgets('server-owned plan state is displayed, not inferred',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.lifterPlan = 'pro';
    await _pumpApp(tester, fake);
    await tester.tap(find.byTooltip('Plan'));
    await _pumpUntilFound(tester, find.text('Lifter Pro'));

    expect(find.text('Lifter Pro'), findsOneWidget);
    expect(find.text('Lifter Free'), findsNothing);
  });
}
