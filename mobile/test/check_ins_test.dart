import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

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
  tester.view.physicalSize = const Size(1080, 4200);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
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
  await _pumpUntilFound(
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
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
  return fake;
}

FakeMayosApi _coachFake() {
  final FakeMayosApi fake = _signedInFake(coach: true);
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
    'next_follow_up_on': '2026-10-01',
  });
  return fake;
}

/// The coach shell opens on the Roster tab (#119).
Future<void> _openDrillDown(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('Active assignments'));
  await tester.tap(find.text('bob'));
}

Future<void> _openAlertCenter(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('Active assignments'));
  await tester.tap(find.text('Alerts'));
  await _pumpUntilFound(tester, find.text('Show resolved'));
}

Future<void> _openPlayerAssignment(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.byIcon(Icons.badge_outlined));
  await _pumpUntilFound(tester, find.text('Check-ins'));
}

CheckIn _checkIn(String id, String checkedInOn) => CheckIn(
      checkInId: id,
      assignmentId: 'assignment-1',
      checkedInOn: checkedInOn,
      channel: 'phone',
      createdAt: '2026-09-26T12:00:00Z',
    );

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  test('check-ins are sorted newest checked_in_on first', () {
    final List<CheckIn> sorted = sortCheckInsNewestFirst(<CheckIn>[
      _checkIn('a', '2026-09-10'),
      _checkIn('b', '2026-09-20'),
      _checkIn('c', '2026-09-15'),
    ]);
    expect(sorted.map((CheckIn c) => c.checkInId).toList(),
        <String>['b', 'c', 'a']);
  });

  testWidgets('coach records a check-in and it appears in the list',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openDrillDown(tester);
    await _pumpUntilFound(tester, find.text('Check-ins'));

    // Check-ins live in their own segment of the player page (#120), and the
    // record button opens the log-check-in sheet.
    await tester.tap(find.text('Check-ins'));
    final Finder recordButton = find.byKey(const Key('record_check_in_button'));
    await _pumpUntilFound(tester, recordButton);
    await tester.ensureVisible(recordButton);
    await tester.pump();
    await tester.tap(recordButton);
    await _pumpUntilFound(
        tester, find.byKey(const Key('check_in_submit_button')));

    // A channel is required; the note stays optional (#120).
    await tester.tap(find.byKey(const Key('check_in_channel_phone')));
    await tester.enterText(
        find.byKey(const Key('check_in_note_field')), 'Talked about sleep');
    await tester.tap(find.byKey(const Key('check_in_submit_button')));
    await _pumpUntilFound(tester, find.text('Check-in recorded.'));

    expect(fake.checkIns, hasLength(1));
    expect(fake.checkIns.single['channel'], 'phone');
    expect(fake.checkIns.single['note'], 'Talked about sleep');
    expect(find.textContaining('Phone'), findsWidgets);
    // The next follow-up date moved a full cadence past the new check-in.
    expect(find.textContaining('Next follow-up:'), findsOneWidget);
  });

  testWidgets('player sees former coaches\' check-ins after unassignment',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: false);
    // No active assignment: the check-in history must still be reachable.
    fake.activeAssignmentId = null;
    fake.checkIns.add(<String, dynamic>{
      'check_in_id': 'check-in-1',
      'assignment_id': 'assignment-1',
      'checked_in_on': '2026-09-20',
      'channel': 'email',
      'note': 'Quick catch-up',
      'created_at': '2026-09-20T09:00:00Z',
      'coach_username': 'bobcoach',
      'assignment_status': 'ended',
    });
    await _pumpApp(tester, fake);
    await _openPlayerAssignment(tester);

    expect(find.text('2026-09-20 · Email'), findsOneWidget);
    expect(find.textContaining('Coach bobcoach'), findsOneWidget);
    expect(find.textContaining('coaching ended'), findsOneWidget);
    expect(find.textContaining('Quick catch-up'), findsOneWidget);
  });

  testWidgets('alert center renders a follow-up-due alert', (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(<String, dynamic>{
      'alert_id': 'alert-follow-up',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'follow_up_due',
      'due_on': '2026-09-20',
      'last_check_in_on': null,
      'state': 'new',
      'created_at': '2026-09-20T08:00:00Z',
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    });
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(find.text('Follow-up due since 2026-09-20'), findsOneWidget);
    await tester.tap(find.text('Acknowledge'));
    await _pumpUntilFound(tester, find.text('Resolve'));
    expect(find.text('Resolve'), findsOneWidget);
  });
}
