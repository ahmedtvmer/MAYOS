import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/connectivity.dart';
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

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  List<Override> extraOverrides = const <Override>[],
}) async {
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
        ...extraOverrides,
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text(fake.coach ? 'Roster' : 'Home'));
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

/// The coach shell opens on the Roster tab (#119).
Future<void> _openRosterEntry(WidgetTester tester) async {
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
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Since 2026-09-24T10:00:00Z'), findsOneWidget);
    expect(find.text('Chest: 12.5'), findsOneWidget);
    expect(find.textContaining('4200.0'), findsWidgets);
    expect(find.text('Bench Press'), findsWidgets);
    expect(find.textContaining('ASSISTANT-CHAT-SECRET'), findsNothing);

    // Drilling into an exercise loads its history inline. The player page's
    // header, actions, and segments sit above the drill-down content (#120),
    // so the Exercises card is scrolled into view first.
    final Finder benchTile = find.widgetWithText(ExpansionTile, 'Bench Press');
    await tester.scrollUntilVisible(benchTile, 300,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(benchTile);
    await tester.pump();
    await tester.tap(benchTile);
    await _pumpUntilFound(tester, find.textContaining('e1RM 120.0'));
    expect(find.textContaining('e1RM 120.0'), findsOneWidget);
  });

  testWidgets('the player history offline banner sits below its app bar',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    final StreamController<bool> browserEvents =
        StreamController<bool>.broadcast();
    addTearDown(browserEvents.close);
    await _pumpApp(
      tester,
      fake,
      extraOverrides: <Override>[
        offlineBannerEnabledProvider.overrideWithValue(true),
        browserConnectivityEventsProvider.overrideWithValue(
          browserEvents.stream,
        ),
      ],
    );

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    browserEvents.add(false);
    await tester.pump();
    await tester.pump();

    expect(find.text(OfflineBanner.message), findsOneWidget);
    expect(
      tester.getRect(find.byType(OfflineBanner)).top,
      greaterThanOrEqualTo(
        tester
            .getRect(find.byKey(const Key('coach_player_history_app_bar')))
            .bottom,
      ),
    );
  });

  testWidgets('the drill-down shows skipped and unplanned divergences',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

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
    for (final dynamic session in summary['recent_sessions'] as List<dynamic>) {
      (session as Map<String, dynamic>)['divergences'] =
          <Map<String, dynamic>>[];
    }
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(find.textContaining('Skipped:'), findsNothing);
    expect(find.textContaining('Unplanned:'), findsNothing);
  });

  testWidgets('the drill-down shows a performed-date correction note',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    final Map<String, dynamic> correction = <String, dynamic>{
      'previous_date': '2026-09-26',
      'corrected_date': '2026-09-25',
      'corrected_at': '2026-09-26T12:00:00Z',
    };
    final Map<String, dynamic> summary = fake.coachPlayerSummary;
    (summary['latest_session'] as Map<String, dynamic>)['corrections'] =
        <Map<String, dynamic>>[correction];
    for (final dynamic session in summary['recent_sessions'] as List<dynamic>) {
      (session as Map<String, dynamic>)['corrections'] = <Map<String, dynamic>>[
        correction
      ];
    }
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(
      find.text('Date corrected from 2026-09-26 to 2026-09-25'),
      findsWidgets,
    );
  });

  testWidgets('the drill-down shows the expected weekdays, timezone, and pause',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Expected: Mon, Wed, Fri'), findsOneWidget);
    expect(find.text('Timezone: Europe/London'), findsOneWidget);
    expect(find.text('Pause: 2026-09-28 → 2026-10-02'), findsOneWidget);
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
