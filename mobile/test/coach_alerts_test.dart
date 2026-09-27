import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
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
  await _pumpUntilFound(tester, find.text('Home'));
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

Future<void> _openRoster(WidgetTester tester) async {
  await _openSettings(tester);
  await tester.tap(find.byIcon(Icons.handshake_outlined));
  await _pumpUntilFound(tester, find.text('Active assignments'));
}

Future<void> _openAlertCenter(WidgetTester tester) async {
  await _openRoster(tester);
  await tester.tap(find.text('Alert center'));
  await _pumpUntilFound(tester, find.text('Acknowledge'));
}

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  testWidgets('roster shows new and acknowledged alert badges', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _openRoster(tester);

    expect(find.text('2'), findsOneWidget);
    expect(find.text('1'), findsOneWidget);
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
    await tester.tap(find.text('Resolved'));
    await _pumpUntilFound(tester, find.text('Resolved by coach'));
    expect(find.text('Resolved by coach'), findsOneWidget);
    expect(find.text('Resolve'), findsNothing);
  });

  testWidgets('deload alert renders its reason and can be resolved',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachAlerts.add(_deloadAlert());
    await _pumpApp(tester, fake);
    await _openAlertCenter(tester);

    expect(
      find.text('Deload recommended — Rolling readiness crash (avg 1.7/5)'),
      findsOneWidget,
    );

    await tester.tap(find.text('Resolve'));
    await _pumpUntilFound(tester, find.text('Resolve'));
    expect(fake.coachAlerts.single['state'], 'resolved');
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
