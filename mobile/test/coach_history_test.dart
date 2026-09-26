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
  });
  return fake;
}

Future<void> _openRosterEntry(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.handshake_outlined));
  await _pumpUntilFound(tester, find.text('Active assignments'));
  await tester.tap(find.text('bob'));
}

void main() {
  testWidgets('roster tap opens the assigned player history drill-down',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    // Chat data present on the wire must never render in a coach response.
    fake.coachPlayerSummary['chat'] = 'ASSISTANT-CHAT-SECRET';
    fake.coachPlayerRecords.first['chat'] = 'ASSISTANT-CHAT-SECRET';
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(
        tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Since 2026-09-24T10:00:00Z'), findsOneWidget);
    expect(find.text('Chest: 12.5'), findsOneWidget);
    expect(find.textContaining('4200.0'), findsWidgets);
    expect(find.text('Bench Press'), findsWidgets);
    expect(find.textContaining('ASSISTANT-CHAT-SECRET'), findsNothing);

    // Drilling into an exercise loads its history inline.
    await tester.tap(find.widgetWithText(ExpansionTile, 'Bench Press'));
    await _pumpUntilFound(tester, find.textContaining('e1RM 120.0'));
    expect(find.textContaining('e1RM 120.0'), findsOneWidget);
  });

  testWidgets('the drill-down shows skipped and unplanned divergences',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(
        tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Skipped: Squat'), findsOneWidget);
    expect(find.text('Unplanned: Lat Pulldown'), findsOneWidget);
    // The Lower 1 session carries no divergences, so only one of each renders.
    expect(find.text('Lower 1 · 2026-09-23'), findsOneWidget);
    expect(find.textContaining('Skipped:'), findsOneWidget);
    expect(find.textContaining('Unplanned:'), findsOneWidget);
  });

  testWidgets('sessions without divergences render no divergence rows',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    final Map<String, dynamic> summary = fake.coachPlayerSummary;
    (summary['latest_session'] as Map<String, dynamic>)['divergences'] =
        <Map<String, dynamic>>[];
    for (final dynamic session
        in summary['recent_sessions'] as List<dynamic>) {
      (session as Map<String, dynamic>)['divergences'] =
          <Map<String, dynamic>>[];
    }
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(
        tester, find.text('Volume (weighted working sets)'));

    expect(find.textContaining('Skipped:'), findsNothing);
    expect(find.textContaining('Unplanned:'), findsNothing);
  });

  testWidgets('a denied assignment shows the error state with no training data',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.coachHistoryDenied = true;
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('No active assignment.'));

    expect(find.text('No active assignment.'), findsOneWidget);
    expect(find.text('Bench Press'), findsNothing);
    expect(find.textContaining('4200.0'), findsNothing);
    expect(find.textContaining('chat'), findsNothing);
  });

  test('malformed coach history payloads fail closed with ApiException',
      () async {
    final FakeMayosApi fake = _coachFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final ApiClient client = ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

    // Wrong-typed field in a map payload.
    fake.coachPlayerSummary = <String, dynamic>{'player_username': 123};
    await expectLater(
      client.coachPlayerSummary('assignment-1'),
      throwsA(isA<ApiException>()),
    );

    // Wrong-typed entry in a list payload.
    fake.coachPlayerRecords = <Map<String, dynamic>>[
      <String, dynamic>{'exercise_id': 7, 'name': 'Bench Press'},
    ];
    await expectLater(
      client.coachPlayerPersonalRecords('assignment-1'),
      throwsA(isA<ApiException>()),
    );

    // Malformed divergence entry fails the whole summary closed.
    fake.coachPlayerSummary = <String, dynamic>{
      'player_username': 'bob',
      'started_at': '2026-09-24T10:00:00Z',
      'status': 'active',
      'volume': <String, dynamic>{},
      'latest_session': <String, dynamic>{
        'session_date': '2026-09-25',
        'split_name': 'Upper 1',
        'sets_count': 12,
        'total_volume_kg': 4200.0,
        'divergences': <dynamic>[
          <String, dynamic>{
            'kind': 'skipped',
            'exercise_id': 7,
            'exercise_name': 'Squat',
          },
        ],
      },
    };
    await expectLater(
      client.coachPlayerSummary('assignment-1'),
      throwsA(isA<ApiException>()),
    );
  });
}
