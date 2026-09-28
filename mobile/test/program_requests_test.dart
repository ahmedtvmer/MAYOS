import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
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

/// Pumps until [finder] stops matching (a sheet or dialog leaving the tree).
Future<void> _pumpUntilGone(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isEmpty) {
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

FakeMayosApi _playerFake() {
  final FakeMayosApi fake = _signedInFake(coach: false);
  fake.activeAssignmentId = 'assignment-1';
  fake.activeCoachDisplayName = 'Coach Alice';
  fake.activeCoachSpecialization = 'Powerlifting';
  fake.programVersion = 1;
  fake.programPublishedByCoachAccountId = 'account-coach';
  fake.coachControlsProgram = true;
  return fake;
}

Map<String, dynamic> _request({
  required String id,
  required String status,
  String kind = 'exercise_substitution',
  String? response,
  String? dayName = 'Upper 1',
  String? exerciseId = 'bench_press',
  String? replacementExerciseId = 'incline_press',
  int? desiredWeeklyFrequency,
  String? desiredSplitPreference,
  String reason = 'Shoulder discomfort.',
}) =>
    <String, dynamic>{
      'request_id': id,
      'assignment_id': 'assignment-1',
      'kind': kind,
      'program_version': 1,
      'day_name': dayName,
      'exercise_id': exerciseId,
      'replacement_exercise_id': replacementExerciseId,
      'desired_weekly_frequency': desiredWeeklyFrequency,
      'desired_split_preference': desiredSplitPreference,
      'reason': reason,
      'status': status,
      'response': response,
      'created_at': '2026-09-26T12:00:00Z',
      'resolved_at': status == 'pending' ? null : '2026-09-26T12:30:00Z',
      'resolved_by': status == 'pending' ? null : 'coach',
    };

Future<void> _openPlayerAssignment(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.byIcon(Icons.badge_outlined));
  await _pumpUntilFound(tester, find.text('Program requests'));
}

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
  testWidgets('player creates a substitution request and sees it pending',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    await _pumpApp(tester, fake);
    await _openPlayerAssignment(tester);
    expect(find.text('No program requests yet.'), findsOneWidget);

    await tester.tap(find.text('Request a change'));
    await _pumpUntilFound(tester, find.text('Request a program change'));
    await tester.enterText(
        find.byKey(const Key('program_request_day_field')), 'Upper 1');
    await tester.enterText(
        find.byKey(const Key('program_request_exercise_field')), 'bench_press');
    await tester.enterText(
        find.byKey(const Key('program_request_replacement_field')),
        'incline_press');
    await tester.enterText(
        find.byKey(const Key('program_request_reason_field')),
        'Shoulder discomfort.');
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await _pumpUntilFound(tester, find.text('Pending'));

    expect(fake.programRequests.length, 1);
    expect(fake.programRequests.first['day_name'], 'Upper 1');
    expect(
        fake.programRequests.first['replacement_exercise_id'], 'incline_press');
    expect(fake.programRequests.first['status'], 'pending');
    expect(find.text('Reason: Shoulder discomfort.'), findsOneWidget);
  });

  testWidgets('player sees the coach decline response', (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programRequests.add(_request(
      id: 'req-declined',
      status: 'declined',
      response: 'Rest that shoulder first.',
    ));
    await _pumpApp(tester, fake);
    await _openPlayerAssignment(tester);

    expect(find.text('Declined'), findsOneWidget);
    expect(find.text('Coach: Rest that shoulder first.'), findsOneWidget);
  });

  testWidgets('player cancels a pending request', (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programRequests.add(_request(id: 'req-pending', status: 'pending'));
    await _pumpApp(tester, fake);
    await _openPlayerAssignment(tester);

    await tester.tap(find.text('Cancel request'));
    await _pumpUntilFound(tester, find.text('Cancelled'));

    expect(fake.programRequests.single['status'], 'cancelled');
  });

  testWidgets('coach applies a request and a stale target refuses inline',
      (tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'started_at': '2026-09-24T10:00:00Z',
      'status': 'active',
    });
    fake.programVersion = 1;
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    fake.programRequests
        .add(_request(id: 'req-2', status: 'pending', reason: 'Knee pain.'));
    await _pumpApp(tester, fake);

    // The coach shell opens on the Roster tab (#119).
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('History'));
    // Requests live in their own player-page segment (#121).
    await _pumpUntilFound(tester, find.text('Requests (2)'));
    await tester.tap(find.text('Requests (2)'));
    await _pumpUntilFound(tester, find.text('Program requests'));
    expect(find.text('bench_press → incline_press'), findsNWidgets(2));

    // Tapping a pending row opens the shared resolve sheet (#121).
    final Finder firstCard = find.byKey(const Key('request_card_req-1'));
    await tester.ensureVisible(firstCard);
    await tester.pump();
    await tester.tap(firstCard);
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    expect(find.text('Apply swap'), findsOneWidget);
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_apply_button')));
    await _pumpUntilFound(tester, find.text('Applied'));
    expect(
      fake.programRequests
          .where((Map<String, dynamic> r) => r['status'] == 'applied')
          .length,
      1,
    );
    expect(fake.programVersion, greaterThan(1));

    // Let the success snackbar clear before the next tap.
    await tester.pump(const Duration(seconds: 5));

    fake.staleProgramRequest = true;
    final Finder remainingCard = find.byKey(const Key('request_card_req-2'));
    await tester.ensureVisible(remainingCard);
    await tester.pump();
    await tester.tap(remainingCard);
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilFound(
        tester,
        find.textContaining(
            'The program changed since this request was created'));
    expect(
      fake.programRequests
          .where((Map<String, dynamic> r) => r['status'] == 'pending')
          .length,
      1,
    );
    // The list refreshed and the refused request is still pending.
    expect(find.text('Pending'), findsOneWidget);
  });

  testWidgets('player screen renders status chips for all four states',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programRequests.addAll(<Map<String, dynamic>>[
      _request(id: 'r1', status: 'pending'),
      _request(id: 'r2', status: 'applied'),
      _request(id: 'r3', status: 'declined', response: 'Not this time.'),
      _request(id: 'r4', status: 'cancelled'),
    ]);
    await _pumpApp(tester, fake);
    await _openPlayerAssignment(tester);

    expect(find.text('Pending'), findsOneWidget);
    expect(find.text('Applied'), findsOneWidget);
    expect(find.text('Declined'), findsOneWidget);
    expect(find.text('Cancelled'), findsOneWidget);
  });
}
