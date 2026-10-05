import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
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

Future<void> _pumpUntilGone(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isEmpty) {
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpCoachApp(WidgetTester tester, FakeMayosApi fake) async {
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
  await _pumpUntilFound(tester, find.text('Roster'));
}

FakeMayosApi _coachFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
    'alerts_new': 1,
    'alerts_acknowledged': 0,
    'pending_requests': 1,
    'last_workout_on': '2026-09-26',
  });
  fake.programRequests.add(<String, dynamic>{
    'request_id': 'request-1',
    'assignment_id': 'assignment-1',
    'kind': 'exercise_substitution',
    'program_version': 2,
    'day_name': 'Upper 1',
    'exercise_id': 'bench_press',
    'replacement_exercise_id': 'incline_press',
    'exercise_name': 'Bench Press',
    'replacement_exercise_name': 'Incline Press',
    'desired_weekly_frequency': null,
    'desired_split_preference': null,
    'reason': 'Shoulder discomfort.',
    'status': 'pending',
    'response': null,
    'created_at': '2026-09-25T12:00:00Z',
    'resolved_at': null,
    'resolved_by': null,
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-1',
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'kind': 'missed_expected_days',
    'streak_start_date': '2026-09-20',
    'last_missed_date': '2026-09-21',
    'missed_count': 2,
    'state': 'new',
    'created_at': '2026-09-22T08:00:00Z',
    'acknowledged_at': null,
    'resolved_at': null,
    'resolved_by': null,
    'message_code': 'coach_alert.missed_expected_days.v1',
    'message_params': <String, dynamic>{
      'count': 2,
      'start_date': '2026-09-20',
      'end_date': '2026-09-21',
    },
    'message_fallback':
        'Missed 2 expected training days (2026-09-20 to 2026-09-21)',
  });
  return fake;
}

void main() {
  testWidgets('coach reviews a player, resolves a request, and closes an alert',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpCoachApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));

    expect(find.text('bob'), findsOneWidget);
    expect(find.text('1 request'), findsOneWidget);
    expect(find.text('1 alert'), findsOneWidget);

    // The roster drill-down opens the assigned Player's history and current
    // alert context inside the real Coach mode shell.
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Open alerts'));
    expect(find.text('Missed 2 expected training days (2026-09-20 to 2026-09-21)'),
        findsOneWidget);
    await tester.tap(find.byType(BackButton));
    await _pumpUntilFound(tester, find.text('Active assignments'));

    // Resolve a Player's substitution request through the Requests tab.
    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));
    await tester.tap(find.byKey(const Key('request_card_request-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    expect(find.text('bob asks'), findsOneWidget);
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_apply_button')));
    expect(fake.programRequests.single['status'], 'applied');

    // Acknowledge and resolve the missed-day alert from the Alerts tab.
    await tester.tap(find.text('Alerts'));
    await _pumpUntilFound(tester, find.text('Show resolved'));
    expect(find.text('Missed 2 expected training days (2026-09-20 to 2026-09-21)'),
        findsOneWidget);
    await tester.tap(find.text('Acknowledge'));
    await _pumpUntilFound(tester, find.text('Resolve'));
    expect(fake.coachAlerts.single['state'], 'acknowledged');
    await tester.tap(find.text('Resolve'));
    await _pumpUntilFound(tester, find.text('Resolved'));
    expect(fake.coachAlerts.single['state'], 'resolved');

    expect(
      fake.adapter.requests.any((request) =>
          request.path == '/coach/assignments/assignment-1/player/summary'),
      isTrue,
    );
    expect(
      fake.adapter.requests.any((request) =>
          request.path == '/coach/assignments/assignment-1/program-requests'),
      isTrue,
    );
    expect(
      fake.adapter.requests.any((request) =>
          request.path == '/coach/alerts/alert-1/acknowledge'),
      isTrue,
    );
    expect(
      fake.adapter.requests.any((request) =>
          request.path == '/coach/alerts/alert-1/resolve'),
      isTrue,
    );
  });
}
