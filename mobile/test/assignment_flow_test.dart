import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Pumps finite frames until [finder] matches, then a few more so transitions
/// settle without depending on `pumpAndSettle` (indeterminate spinners never settle).
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
  fake.coachCapacity = 10;
  return fake;
}

void main() {
  testWidgets('player previews access, consents, then ends the assignment',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'assignment-invite-token-123456';
    fake.pendingCoachDisplayName = 'Coach Bob';
    fake.pendingCoachSpecialization = 'Strength';
    await _pumpApp(tester, fake);

    // Open the player assignment surface from the app bar.
    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('Coach assignment'));

    // A bad code is rejected and grants nothing.
    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'wrong-code-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Invalid or expired invite code.'));
    expect(fake.activeAssignmentId, isNull);

    // Preview reveals identity and exact access; nothing is consumed yet.
    await tester.enterText(find.byKey(const Key('assignment_code_field')),
        'assignment-invite-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));
    expect(find.text('Your coach will be Coach Bob'), findsOneWidget);
    expect(fake.activeAssignmentId, isNull);

    // Explicit consent binds immediately and shows the active coach.
    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Your coach'));
    expect(find.text('Coach Bob'), findsOneWidget);
    expect(fake.activeAssignmentId, 'assignment-1');

    // The player can end it; the invite section returns.
    await tester.tap(find.widgetWithText(OutlinedButton, 'End assignment'));
    await _pumpUntilFound(tester, find.text('End assignment?'));
    await tester.tap(find.widgetWithText(FilledButton, 'End assignment'));
    await _pumpUntilFound(tester, find.text('Coach assignment'));
    expect(fake.activeAssignmentId, isNull);
  });

  testWidgets('editing the code after preview clears the previewed consent',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'coach-a-token-123456';
    fake.pendingCoachDisplayName = 'Coach A';
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('Coach assignment'));

    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'coach-a-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));
    expect(find.text('Your coach will be Coach A'), findsOneWidget);

    // Switching the code invalidates the preview, so consent cannot target coach B.
    fake.pendingAssignmentToken = 'coach-b-token-123456';
    fake.pendingCoachDisplayName = 'Coach B';
    await tester.enterText(
        find.byKey(const Key('assignment_code_field')), 'coach-b-token-123456');
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Accept assignment'), findsNothing);
    expect(find.text('Your coach will be Coach A'), findsNothing);
    expect(fake.activeAssignmentId, isNull);

    // Re-previewing binds consent to coach B only.
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Your coach will be Coach B'));
    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Coach B'));
    expect(fake.activeCoachDisplayName, 'Coach B');
  });

  testWidgets(
      'a committed assignment is not reported as failed when a read would fail',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    fake.pendingAssignmentToken = 'coach-b-token-123456';
    fake.pendingCoachDisplayName = 'Coach Bob';
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('Coach assignment'));

    await tester.enterText(find.byKey(const Key('assignment_code_field')),
        'coach-b-token-123456');
    await tester.tap(find.text('Preview access'));
    await _pumpUntilFound(tester, find.text('Accept assignment'));

    final int meCallsBefore =
        fake.adapter.requests.where((r) => r.path == '/assignments/me').length;
    // Any post-redeem account read would now fail transiently.
    fake.myAssignmentFails = true;

    await tester.tap(find.text('Accept assignment'));
    await _pumpUntilFound(tester, find.text('Your coach'));
    expect(find.text('Coach Bob'), findsOneWidget);
    expect(find.text('The service is unavailable.'), findsNothing);
    expect(
      fake.adapter.requests.where((r) => r.path == '/assignments/me').length,
      meCallsBefore,
    );
  });

  testWidgets('coach issues a code, reviews notices, revokes, disables',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'started_at': '2026-09-24T10:00:00Z',
      'status': 'active',
    });
    fake.assignmentNotices.add(<String, dynamic>{
      'notice_id': 'n1',
      'kind': 'assignment_redeemed',
      'message': 'bob accepted your coaching invite and is now assigned to you.',
      'created_at': '2026-09-24T10:00:00Z',
      'read_at': null,
    });
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.handshake_outlined));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('bob'), findsOneWidget);
    expect(
        find.text('bob accepted your coaching invite and is now assigned to you.'),
        findsOneWidget);

    // Issuing shows the one-time bearer code and remaining capacity.
    await tester.tap(find.text('Create invite code'));
    await _pumpUntilFound(
        tester, find.text('assignment-invite-token-123456'));
    expect(fake.issuedAssignmentToken, 'assignment-invite-token-123456');

    // Revoke removes the assignment from the console.
    await tester.tap(find.text('Revoke'));
    await _pumpUntilFound(tester, find.text('Revoke assignment?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Revoke'));
    await _pumpUntilFound(tester, find.text('No assigned players yet.'));
    expect(fake.assignments, isEmpty);

    // Disabling coaching clears the capability and ends every assignment.
    fake.meFails = true; // A follow-up account read would fail after the commit.
    await tester.tap(find.text('Disable coaching'));
    await _pumpUntilFound(tester, find.text('Disable coaching?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Disable coaching'));
    await _pumpUntilFound(tester, find.text('Coaching disabled. 0 assignment(s) ended.'));
    expect(fake.coach, isFalse);
    expect(find.byIcon(Icons.handshake_outlined), findsNothing);
  });
}
