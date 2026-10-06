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

Future<void> _expandHistorySection(WidgetTester tester, String section) async {
  final Finder card =
      find.byKey(Key('coach_history_section_${section}_semantics'));
  await tester.scrollUntilVisible(card, 300,
      scrollable: find.byType(Scrollable).first);
  await tester.tap(card);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the active assigned player\'s session shows Cardio minutes',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    (fake.coachPlayerSummary['latest_session'] as Map<String, dynamic>)[
        'cardio'] = <String, dynamic>{
      'prescription': 'Steady bike',
      'minutes': 25,
    };
    (fake.coachPlayerSummary['recent_sessions'] as List<Map<String, dynamic>>)
        .first['cardio'] = <String, dynamic>{
      'prescription': 'Steady bike',
      'minutes': 25,
    };
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Cardio: 25 min'), findsOneWidget);
    await _expandHistorySection(tester, 'recentSessions');
    expect(find.text('Cardio: 25 min'), findsNWidgets(2));
  });

  testWidgets('player segments separate Program from History and keep alerts',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachAlerts.add(<String, dynamic>{
        'alert_id': 'alert-player-page',
        'assignment_id': 'assignment-1',
        'player_username': 'bob',
        'kind': 'missed_expected_days',
        'streak_start_date': '2026-09-20',
        'last_missed_date': '2026-09-21',
        'missed_count': 2,
        'state': 'new',
        'created_at': '2026-09-22T08:00:00Z',
      })
      ..programRequests.add(<String, dynamic>{
        'request_id': 'request-1',
        'assignment_id': 'assignment-1',
        'kind': 'exercise_substitution',
        'program_version': 7,
        'exercise_id': 'sq',
        'exercise_name': 'Squat',
        'reason': 'Please change this exercise.',
        'status': 'pending',
        'created_at': '2026-10-02T10:00:00Z',
      });
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Latest session'));

    expect(find.text('Program'), findsOneWidget);
    expect(find.text('History'), findsOneWidget);
    expect(find.text('Check-ins'), findsOneWidget);
    expect(find.text('Requests (1)'), findsOneWidget);
    expect(find.text('Since 2026-09-24T10:00:00Z'), findsOneWidget);
    expect(find.text('Latest session'), findsOneWidget);
    expect(find.text('Volume (weighted working sets)'), findsOneWidget);
    expect(find.text('No active program.'), findsNothing);
    expect(find.text('Open alerts'), findsOneWidget);

    await tester.tap(find.text('Program').first);
    await _pumpUntilFound(tester, find.text('No active program.'));
    expect(find.byKey(const Key('write_program_action')), findsOneWidget);
    expect(find.byKey(const Key('generate_draft_action')), findsOneWidget);
    expect(find.byKey(const Key('coach_assistant_entry')), findsNothing);
    expect(find.text('Open alerts'), findsOneWidget);

    await tester.tap(find.text('Check-ins'));
    await _pumpUntilFound(tester, find.text('No check-ins recorded yet.'));
    expect(find.text('Open alerts'), findsOneWidget);

    await tester.tap(find.text('Requests (1)'));
    await _pumpUntilFound(tester, find.text('Please change this exercise.'));
    expect(find.text('Open alerts'), findsOneWidget);
  });

  testWidgets('history groups start collapsed with counts and expand on tap',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    expect(find.text('Lower 1 · 2026-09-23'), findsNothing);
    expect(find.textContaining('Latest Recorded:'), findsNothing);
    final Finder recentSessionsControl = find.byKey(const Key(
      'coach_history_section_recentSessions_semantics',
    ));
    expect(
      tester.getSemantics(recentSessionsControl),
      isSemantics(
        label: 'Recent sessions (2)',
        isButton: true,
        hasExpandedState: true,
        isExpanded: false,
      ),
    );
    await _expandHistorySection(tester, 'recentSessions');
    expect(find.text('Recent sessions (2)'), findsOneWidget);
    expect(find.text('Lower 1 · 2026-09-23'), findsOneWidget);
    expect(
      tester.getSemantics(recentSessionsControl),
      isSemantics(
        label: 'Recent sessions (2)',
        isButton: true,
        hasExpandedState: true,
        isExpanded: true,
      ),
    );

    await _expandHistorySection(tester, 'records');
    expect(find.text('Personal records (1)'), findsOneWidget);
    await _expandHistorySection(tester, 'checkpoints');
    expect(find.text('Checkpoints (0)'), findsOneWidget);
    await _expandHistorySection(tester, 'exercises');
    expect(find.text('Exercises (1)'), findsOneWidget);
    expect(find.widgetWithText(ExpansionTile, 'Bench Press'), findsOneWidget);
    expect(find.textContaining('Latest Recorded:'), findsNothing);
  });

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
    expect(find.text('Bench Press'), findsNothing);
    expect(find.textContaining('ASSISTANT-CHAT-SECRET'), findsNothing);

    // Drilling into an exercise loads its history inline. The player page's
    // header, actions, and segments sit above the drill-down content (#120),
    // so the Exercises card is scrolled into view first.
    await _expandHistorySection(tester, 'exercises');
    final Finder benchTile = find.widgetWithText(ExpansionTile, 'Bench Press');
    expect(find.text('Bench Press'), findsOneWidget);
    await tester.scrollUntilVisible(benchTile, 300,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(benchTile);
    await tester.pump();
    await tester.tap(benchTile);
    await _pumpUntilFound(tester, find.textContaining('e1RM 120.0'));
    expect(find.textContaining('e1RM 120.0'), findsOneWidget);
  });

  testWidgets('coach history labels zero-load resistance band sets',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachPlayerExercises = <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'band_pull_apart',
          'name': 'Band Pull-Apart',
          'equipment': 'resistance band',
        },
      ]
      ..coachPlayerHistories = <String, Map<String, dynamic>>{
        'band_pull_apart': <String, dynamic>{
          'equipment': 'resistance band',
          'history': <Map<String, dynamic>>[
            <String, dynamic>{
              'date': '2026-09-20',
              'weight_kg': 0.0,
              'reps': 12,
              'rpe': 8.0,
              'e1rm': 0.0,
            },
          ],
          'caption': 'Latest Recorded: **0.0 kg × 12 reps**',
          'records': <dynamic>[],
        },
      };
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _expandHistorySection(tester, 'exercises');
    final Finder bandTile = find.widgetWithText(ExpansionTile, 'Band Pull-Apart');
    await tester.scrollUntilVisible(bandTile, 300,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(bandTile);
    await tester.pump();
    await tester.tap(bandTile);
    await _pumpUntilFound(tester, find.textContaining('Band × 12'));

    expect(find.textContaining('Band × 12'), findsOneWidget);
    expect(find.textContaining('0.0 kg × 12'), findsNothing);
    expect(find.textContaining('Band × 12 (e1RM'), findsNothing);
  });

  testWidgets('coach history lists and opens Checkpoints for the assignment',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake()
      ..checkpointReviewRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'checkpoint': 10,
          'period_start': '2026-01-01',
          'period_end': '2026-09-30',
          'rating': <Map<String, dynamic>>[
            <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
          ],
          'opened': false,
        },
      ]
      ..checkpointReviewDetails[10] = <String, dynamic>{
        'checkpoint': 10,
        'period_start': '2026-01-01',
        'period_end': '2026-09-30',
        'facts': <String, dynamic>{'workouts_in_period': 10},
        'rating': <Map<String, dynamic>>[
          <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
        ],
        'text': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'text_is_template': true,
      };
    await _pumpApp(tester, fake);

    await _openRosterEntry(tester);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _expandHistorySection(tester, 'checkpoints');
    final Finder checkpoint =
        find.byKey(const ValueKey<String>('coach.checkpoint.10'));
    await tester.scrollUntilVisible(checkpoint, 300,
        scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(checkpoint);
    await tester.pumpAndSettle();
    await tester.tap(checkpoint);
    await _pumpUntilFound(tester, find.text('Your 10th workout'));

    expect(find.text('Consistency'), findsOneWidget);
    expect(find.text('Strong'), findsOneWidget);
    expect(
      find.text(
        'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
      ),
      findsOneWidget,
    );
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
    await _expandHistorySection(tester, 'recentSessions');

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
    await _expandHistorySection(tester, 'recentSessions');

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

  testWidgets('History shows Schedule for either source and omits both empty',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    final List<({bool schedule, bool pauses, bool shown})> scenarios =
        <({bool schedule, bool pauses, bool shown})>[
      (schedule: true, pauses: false, shown: true),
      (schedule: false, pauses: true, shown: true),
      (schedule: false, pauses: false, shown: false),
    ];
    for (int index = 0; index < scenarios.length; index++) {
      final ({bool schedule, bool pauses, bool shown}) scenario =
          scenarios[index];
      fake.coachPlayerSummary['schedule'] = scenario.schedule
          ? <String, dynamic>{
              'weekdays': <int>[1, 3, 5],
              'timezone': 'Europe/London',
            }
          : null;
      final List<Map<String, dynamic>> pauses =
          fake.coachPlayerSummary['pauses'] as List<Map<String, dynamic>>;
      pauses
        ..clear()
        ..addAll(
          scenario.pauses
              ? <Map<String, dynamic>>[
                  <String, dynamic>{
                    'starts_on': '2026-09-28',
                    'ends_on': '2026-10-02',
                  },
                ]
              : const <Map<String, dynamic>>[],
        );

      if (index == 0) {
        await _openRosterEntry(tester);
      } else {
        await tester.binding.handlePopRoute();
        await _pumpUntilFound(tester, find.text('Active assignments'));
        await _openRosterEntry(tester);
      }
      await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

      expect(
        find.text('Training schedule'),
        scenario.shown ? findsOneWidget : findsNothing,
      );
    }
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
