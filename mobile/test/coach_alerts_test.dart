import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
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
    'alerts_new': 2,
    'alerts_acknowledged': 1,
    'current_missed_streak': 3,
  });
  return fake;
}

Map<String, dynamic> _alert({
  String state = 'new',
}) =>
    <String, dynamic>{
      'alert_id': 'alert-1',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'missed_expected_days',
      'streak_start_date': '2026-09-20',
      'last_missed_date': '2026-09-21',
      'missed_count': 2,
      'state': state,
      'created_at': '2026-09-22T08:00:00Z',
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    };

Map<String, dynamic> _deloadAlert({String state = 'new'}) => <String, dynamic>{
      'alert_id': 'alert-deload',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'deload_recommended',
      'state': state,
      'created_at': '2026-09-22T08:00:00Z',
      'reason': 'Rolling readiness crash (avg 1.7/5)',
      'severity': 'HIGH',
      'recent_readiness_avg': 1.67,
      'player_deload_choice': <String, dynamic>{
        'choice': 'apply',
        'scope': 'next_workout_only',
      },
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    };

Map<String, dynamic> _regressionAlert({String state = 'new'}) =>
    <String, dynamic>{
      'alert_id': 'alert-regression',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'performance_regression',
      'state': state,
      'created_at': '2026-09-22T08:00:00Z',
      'exercise_id': 'bp',
      'exercise_name': 'Bench Press',
      'status_badge': 'OVERSHOOT',
      'e1rm_delta': -6.2,
      'current_e1rm': 93.8,
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    };

Map<String, dynamic> _profileChangeAlert() => <String, dynamic>{
      'alert_id': 'alert-profile-change',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'profile_change',
      'state': 'new',
      'created_at': '2026-09-22T08:00:00Z',
      'profile_changes': <String, dynamic>{
        'injuries_or_limitations': <String, String>{
          'before': 'None',
          'after': 'Left knee pain',
        },
        'equipment_access': <String, String>{
          'before': 'Commercial gym',
          'after': 'Home gym',
        },
      },
    };

Map<String, dynamic> _stallAlert({String state = 'new'}) => <String, dynamic>{
      'alert_id': 'alert-stall',
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': 'stall',
      'stall_length': 8,
      'window_start_date': '2026-09-15',
      'state': state,
      'created_at': '2026-09-22T08:00:00Z',
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    };

/// The coach shell opens on the Roster tab (#119).
Future<void> _openRoster(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('Active assignments'));
}

Future<void> _openAlertCenter(WidgetTester tester) async {
  await _openRoster(tester);
  await tester.tap(find.text('Alerts'));
  await _pumpUntilFound(tester, find.text('Show resolved'));
}

void main() {
  testWidgets('roster row carries the new-alert chip and no acknowledged '
      'chip', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);

    // Two new alerts and one acknowledged: a roster row counts new alerts
    // only, as the "N alerts" chip (#120).
    expect(find.text('2 alerts'), findsOneWidget);
    expect(find.text('1'), findsNothing);
    expect(find.text('1 alert'), findsNothing);
    // The missed-day chip for the same row comes from the streak.
    expect(find.text('Missed 3d'), findsOneWidget);
  });

  testWidgets('coach acknowledges then resolves an alert', (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_alert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(find.text('bob'), findsWidgets);
    expect(
        find.text('Missed 2 expected training days (2026-09-20 to 2026-09-21)'),
        findsOneWidget);

    await tester.tap(find.text('Acknowledge'));
    await _pumpUntilFound(tester, find.text('Resolve'));
    expect(find.text('Acknowledge'), findsNothing);
    expect(find.text('Resolve'), findsOneWidget);

    await tester.tap(find.text('Resolve'));
    await _pumpUntilFound(tester, find.text('Resolved'));
    // The alert leaves the default open filter; switch to resolved to inspect it.
    await tester.tap(find.text('Show resolved'));
    await _pumpUntilFound(tester, find.text('Resolved by coach'));
    expect(find.text('Resolved by coach'), findsOneWidget);
    expect(find.text('Resolve'), findsNothing);
  });

  testWidgets('coach alert list renders profile changes as before and after',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_profileChangeAlert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(find.textContaining('Injuries or limitations: None → Left knee pain'), findsOneWidget);
    expect(find.textContaining('Equipment access: Commercial gym → Home gym'), findsOneWidget);
  });

  testWidgets('deload alert renders its reason and can be resolved',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_deloadAlert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(
      find.text(
        'Deload recommended — Rolling readiness crash (avg 1.7/5) · '
        'Player chose to apply it for the next workout only',
      ),
      findsOneWidget,
    );

    await tester.tap(find.text('Resolve'));
    await _pumpUntilFound(tester, find.text('Resolve'));
    expect(fake.coachAlerts.single['state'], 'resolved');
  });

  testWidgets('stall alert has its own label and can be acknowledged',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_stallAlert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(
      find.text('Stalling — 8 sessions without a personal record (since 2026-09-15)'),
      findsOneWidget,
    );
    await tester.tap(find.text('Acknowledge'));
    await _pumpUntilFound(tester, find.text('Acknowledged'));
    expect(fake.coachAlerts.single['state'], 'acknowledged');
  });

  testWidgets('performance regression alert renders exercise and e1RM delta',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_regressionAlert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(
      find.text(
          'Performance regression — Bench Press: e1RM −6.2 kg (OVERSHOOT)'),
      findsOneWidget,
    );
  });
}
