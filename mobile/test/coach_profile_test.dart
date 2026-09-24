import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so route
/// transitions settle without depending on `pumpAndSettle` (indeterminate
/// progress indicators never settle).
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
  // A tall surface keeps the profile form's Save button on screen without
  // scrolling, so the test can focus on behavior rather than scroll plumbing.
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

/// A signed-in, onboarded player with a recovery email, optionally already a coach.
FakeMayosApi _signedInFake({required bool coach}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  fake.coachBio = 'Strength coach.';
  fake.coachSpecialization = 'Powerlifting';
  fake.coachCapacity = 12;
  return fake;
}

void main() {
  testWidgets('coach profile loads, validates, and saves', (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.groups_outlined));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(find.text('Coach Alice'), findsOneWidget);
    expect(find.text('Powerlifting'), findsOneWidget);

    final Finder fields = find.byType(TextFormField);

    // Capacity validation rejects 0 with no server write.
    await tester.enterText(fields.at(3), '0');
    await tester.tap(find.text('Save profile'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Capacity must be between 1 and 200.'), findsOneWidget);
    expect(fake.coachCapacity, 12);

    // Display name is required.
    await tester.enterText(fields.at(0), '   ');
    await tester.enterText(fields.at(3), '15');
    await tester.tap(find.text('Save profile'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Enter a display name.'), findsOneWidget);
    expect(fake.coachCapacity, 12);

    // A valid save persists every field.
    await tester.enterText(fields.at(0), 'Coach A');
    await tester.enterText(fields.at(1), 'Hypertrophy');
    await tester.enterText(fields.at(2), 'New bio');
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Coach profile saved.'));
    expect(fake.coachDisplayName, 'Coach A');
    expect(fake.coachSpecialization, 'Hypertrophy');
    expect(fake.coachBio, 'New bio');
    expect(fake.coachCapacity, 15);
  });

  testWidgets('coach profile surfaces a load error and retries',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.coachProfileLoadFails = true;
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.groups_outlined));
    await _pumpUntilFound(tester, find.text('The service is unavailable.'));
    expect(find.text('Retry'), findsOneWidget);

    fake.coachProfileLoadFails = false;
    await tester.tap(find.text('Retry'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(find.text('Coach Alice'), findsOneWidget);
  });

  testWidgets('player redeems an owner invite to unlock coaching',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.validCoachInviteToken = 'coach-invite-token-123456';
    await _pumpApp(tester, fake);

    // A player has no coach tab until the capability is granted.
    expect(find.byIcon(Icons.groups_outlined), findsNothing);

    await tester.tap(find.byIcon(Icons.workspace_premium_outlined));
    await _pumpUntilFound(tester, find.text('Enter your invite code'));

    // A wrong code shows the generic error and grants nothing.
    await tester.enterText(find.byType(TextField), 'wrong-invite-code-123456');
    await tester.tap(find.text('Enable coaching'));
    await _pumpUntilFound(tester, find.text('Invalid or expired invite code.'));
    expect(fake.coach, isFalse);

    // The valid code grants the capability and routes to the profile editor.
    await tester.enterText(find.byType(TextField), 'coach-invite-token-123456');
    await tester.tap(find.text('Enable coaching'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(fake.coach, isTrue);
  });

  testWidgets(
      'a committed grant is not reported as failed when a follow-up read would fail',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.validCoachInviteToken = 'coach-invite-token-123456';
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.workspace_premium_outlined));
    await _pumpUntilFound(tester, find.text('Enter your invite code'));

    final int meCallsBefore =
        fake.adapter.requests.where((r) => r.path == '/auth/me').length;
    // Any post-redeem account read would now fail transiently.
    fake.meFails = true;

    await tester.enterText(find.byType(TextField), 'coach-invite-token-123456');
    await tester.tap(find.text('Enable coaching'));

    // The grant stands and the coach surface opens without a follow-up read.
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(fake.coach, isTrue);
    expect(find.text('Invalid or expired invite code.'), findsNothing);
    expect(
      fake.adapter.requests.where((r) => r.path == '/auth/me').length,
      meCallsBefore,
    );
  });

  testWidgets('app resume refreshes live capabilities', (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    await _pumpApp(tester, fake);
    expect(find.byIcon(Icons.groups_outlined), findsNothing);

    // A grant happened elsewhere while the app was backgrounded.
    fake.coach = true;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await _pumpUntilFound(tester, find.byIcon(Icons.groups_outlined));
    expect(find.byIcon(Icons.groups_outlined), findsOneWidget);
  });
}
