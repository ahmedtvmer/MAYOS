import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

/// Widget tests for the roster rows and the player page (#120).

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

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake,
  InMemoryAppModeStore modeStore,
) async {
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
        appModeStoreProvider.overrideWithValue(modeStore),
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

Future<void> _settle(WidgetTester tester) async {
  for (int i = 0; i < 6; i++) {
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

String _iso(DateTime date) => '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

String _today() => _iso(DateTime.now());

String _daysFromToday(int days) =>
    _iso(DateTime.now().add(Duration(days: days)));

FakeMayosApi _coachFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  return fake;
}

/// A roster row as the service returns it. Alert badges and the pending
/// request count are left out unless given, so the fake derives them the way
/// `GET /coach/assignments` does (#118).
Map<String, dynamic> _assignment(
  String id,
  String username, {
  int? alertsNew,
  int? pendingRequests,
  int missedStreak = 0,
  String? nextFollowUpOn,
  String? lastWorkoutOn,
  String? programName,
}) =>
    <String, dynamic>{
      'assignment_id': id,
      'player_username': username,
      'started_at': '2026-09-01T10:00:00Z',
      'status': 'active',
      'current_missed_streak': missedStreak,
      if (alertsNew != null) 'alerts_new': alertsNew,
      if (alertsNew != null) 'alerts_acknowledged': 0,
      if (pendingRequests != null) 'pending_requests': pendingRequests,
      'next_follow_up_on': nextFollowUpOn,
      'last_workout_on': lastWorkoutOn,
      if (programName != null) 'program_name': programName,
    };

Map<String, dynamic> _alert(
  String id, {
  String kind = 'missed_expected_days',
  String state = 'new',
  String? dueOn,
}) =>
    <String, dynamic>{
      'alert_id': id,
      'assignment_id': 'assignment-1',
      'player_username': 'bob',
      'kind': kind,
      'state': state,
      'created_at': '2026-09-22T08:00:00Z',
      if (kind == 'missed_expected_days') ...<String, dynamic>{
        'streak_start_date': '2026-09-20',
        'last_missed_date': '2026-09-21',
        'missed_count': 2,
      },
      if (dueOn != null) 'due_on': dueOn,
      'acknowledged_at': null,
      'resolved_at': null,
      'resolved_by': null,
    };

Map<String, dynamic> _checkInRow(
  String id,
  String checkedInOn,
  String channel,
) =>
    <String, dynamic>{
      'check_in_id': id,
      'assignment_id': 'assignment-1',
      'checked_in_on': checkedInOn,
      'channel': channel,
      'note': null,
      'created_at': '2026-09-20T09:00:00Z',
      'coach_username': 'alice',
      'assignment_status': 'active',
    };

/// The roster shows the rows in the order the service returned them — a
/// never-trained, calm player first — so the client never re-sorts, and each
/// row carries the chips that apply to it (#120).

void main() {
  testWidgets('roster rows keep the server order and show each urgency chip',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    // Server order as returned: the calm, never-trained player first.
    fake.assignments.add(_assignment('assignment-dev', 'dev'));
    fake.assignments.add(_assignment(
      'assignment-1',
      'bob',
      alertsNew: 1,
      pendingRequests: 2,
      missedStreak: 3,
      nextFollowUpOn: _daysFromToday(-2),
      lastWorkoutOn: '2026-09-20',
      programName: 'Upper/Lower',
    ));
    fake.assignments.add(_assignment(
      'assignment-2',
      'cara',
      nextFollowUpOn: _today(),
      lastWorkoutOn: '2026-09-26',
    ));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    // Server order wins: dev is painted above bob, bob above cara.
    expect(
      tester.getTopLeft(find.text('dev')).dy,
      lessThan(tester.getTopLeft(find.text('bob')).dy),
    );
    expect(
      tester.getTopLeft(find.text('bob')).dy,
      lessThan(tester.getTopLeft(find.text('cara')).dy),
    );

    // Bob: missed streak, overdue follow-up, new alerts, pending requests.
    expect(find.text('Missed 3d'), findsOneWidget);
    expect(find.text('Follow-up overdue'), findsOneWidget);
    expect(find.text('1 alert'), findsOneWidget);
    expect(find.text('2 requests'), findsOneWidget);
    expect(find.text('Last workout 2026-09-20 · Upper/Lower'),
        findsOneWidget);

    // Cara: only the follow-up that is due today.
    expect(find.text('Follow-up today'), findsOneWidget);
    expect(find.text('Last workout 2026-09-26'), findsOneWidget);
    expect(find.text('Missed 1d'), findsNothing);

    // Dev: never trained and nothing to attend to.
    expect(find.text('No workouts yet'), findsOneWidget);
  });

  /// A roster row with nothing to attend to renders no chip at all (#120).
  testWidgets('a calm roster row carries no chip', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment(
      'assignment-1',
      'bob',
      nextFollowUpOn: _daysFromToday(3),
      lastWorkoutOn: '2026-09-26',
    ));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    expect(find.byKey(const Key('roster_row_assignment-1')), findsOneWidget);
    expect(find.text('Last workout 2026-09-26'), findsOneWidget);
    for (final String label in <String>[
      'Follow-up today',
      'Follow-up overdue',
      '0 alerts',
      '0 requests',
    ]) {
      expect(find.text(label), findsNothing);
    }
    expect(find.textContaining(' alert'), findsNothing);
    expect(find.textContaining(' request'), findsNothing);
    expect(find.textContaining('Missed'), findsNothing);
  });

  /// The player page's alert actions: acknowledge and resolve through the
  /// existing client calls, **Log check-in** only on a follow-up that is due,
  /// and the shell's badge plus the roster row follow without a restart (#120).
  testWidgets('the player page acts on open alerts and refreshes badge and row',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment(
      'assignment-1',
      'bob',
      nextFollowUpOn: _daysFromToday(-1),
      lastWorkoutOn: '2026-09-20',
    ));
    fake.coachAlerts.add(_alert('alert-missed'));
    fake.coachAlerts.add(_alert('alert-follow', kind: 'follow_up_due',
        dueOn: _daysFromToday(-1)));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    // Two new alerts drive the Alerts tab badge and the row chip.
    expect(
      find.descendant(of: find.byType(Badge), matching: find.text('2')),
      findsOneWidget,
    );
    expect(find.text('2 alerts'), findsOneWidget);

    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Open alerts'));

    // Both open alerts render with their actions; only the due follow-up
    // offers Log check-in.
    final Finder missed = find.byKey(const Key('player_alert_alert-missed'));
    final Finder followUp = find.byKey(const Key('player_alert_alert-follow'));
    expect(missed, findsOneWidget);
    expect(followUp, findsOneWidget);
    expect(
      find.descendant(of: missed, matching: find.text('Acknowledge')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: missed, matching: find.text('Resolve')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: missed, matching: find.text('Log check-in')),
      findsNothing,
    );
    expect(
      find.descendant(of: followUp, matching: find.text('Log check-in')),
      findsOneWidget,
    );

    // Acknowledge moves the alert out of the new state.
    await tester.tap(
        find.descendant(of: missed, matching: find.text('Acknowledge')));
    await _pumpUntilGone(
        tester, find.descendant(of: missed, matching: find.text('Acknowledge')));
    await _settle(tester);
    expect(fake.coachAlerts
        .firstWhere((Map<String, dynamic> row) =>
            row['alert_id'] == 'alert-missed')['state'], 'acknowledged');
    expect(
      find.descendant(of: missed, matching: find.text('Acknowledge')),
      findsNothing,
    );

    // Resolve removes it from the open alerts at the top of the page.
    await tester.tap(find.descendant(of: missed, matching: find.text('Resolve')));
    await _pumpUntilGone(tester, missed);
    expect(missed, findsNothing);
    expect(followUp, findsOneWidget);

    // Back on the roster: one new alert left, badge and chip both updated.
    await tester.tap(find.byType(BackButton));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await _pumpUntilFound(tester, find.text('1 alert'));
    expect(find.text('1 alert'), findsOneWidget);
    expect(find.text('2 alerts'), findsNothing);
    expect(
      find.descendant(of: find.byType(Badge), matching: find.text('1')),
      findsOneWidget,
    );
  });

  /// The header **Log check-in** sheet (#120): the channel is required, the
  /// note is optional, the date is today, and saving goes through the existing
  /// create-check-in call — then the page and the roster row follow.
  testWidgets('the log check-in sheet requires a channel and saves today',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment(
      'assignment-1',
      'bob',
      nextFollowUpOn: _daysFromToday(-4),
      lastWorkoutOn: '2026-09-20',
    ));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('Follow-up overdue'), findsOneWidget);

    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Open alerts'));

    await tester.tap(find.byKey(const Key('log_check_in_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('check_in_submit_button')));
    expect(find.text('Log check-in with bob'), findsOneWidget);
    expect(find.text('Dated today · ${_today()}'), findsOneWidget);
    expect(find.text('Phone'), findsOneWidget);
    expect(find.text('Message'), findsOneWidget);
    expect(find.text('In person'), findsOneWidget);
    expect(find.text('Other'), findsOneWidget);

    // A channel is required: saving without one calls nothing.
    await tester.tap(find.byKey(const Key('check_in_submit_button')));
    await _pumpUntilFound(tester, find.text('Pick a contact channel.'));
    expect(fake.checkIns, isEmpty);

    // The note stays optional, and the save is dated today.
    await tester.tap(find.byKey(const Key('check_in_channel_phone')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('check_in_submit_button')));
    await _pumpUntilFound(tester, find.text('Check-in recorded.'));
    expect(find.byKey(const Key('check_in_submit_button')), findsNothing);

    expect(fake.checkIns, hasLength(1));
    expect(fake.checkIns.single['channel'], 'phone');
    expect(fake.checkIns.single['checked_in_on'], _today());
    expect(fake.checkIns.single['note'], isNull);

    // The page lists it under Check-ins…
    await tester.tap(find.text('Check-ins'));
    await _pumpUntilFound(tester, find.text('${_today()} · Phone'));

    // …and the roster row dropped its overdue follow-up chip.
    await tester.tap(find.byType(BackButton));
    await _pumpUntilGone(tester, find.text('Follow-up overdue'));
    await _settle(tester);
    expect(find.text('Follow-up overdue'), findsNothing);
  });

  /// Saving a check-in refreshes everything the spec names (#120): the
  /// player page's open alerts (the service resolves the satisfied
  /// follow-up), the Alerts tab badge, and the roster row.
  testWidgets('saving a check-in refreshes the page alerts and the badge',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment(
      'assignment-1',
      'bob',
      nextFollowUpOn: _daysFromToday(-2),
      lastWorkoutOn: '2026-09-20',
    ));
    fake.coachAlerts.add(_alert('alert-missed'));
    fake.coachAlerts
        .add(_alert('alert-follow', kind: 'follow_up_due', dueOn: _daysFromToday(-2)));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    final Finder missed = find.byKey(const Key('player_alert_alert-missed'));
    final Finder followUp = find.byKey(const Key('player_alert_alert-follow'));
    expect(
      find.descendant(of: find.byType(Badge), matching: find.text('2')),
      findsOneWidget,
    );
    expect(find.text('2 alerts'), findsOneWidget);

    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Open alerts'));
    expect(missed, findsOneWidget);
    expect(followUp, findsOneWidget);

    // Log a check-in from the header action.
    await tester.tap(find.byKey(const Key('log_check_in_action')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('check_in_submit_button')));
    await tester.tap(find.byKey(const Key('check_in_channel_phone')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('check_in_submit_button')));
    await _pumpUntilFound(tester, find.text('Check-in recorded.'));

    // The page refetched its alerts: the follow-up the check-in satisfied is
    // gone, the unrelated missed-day alert stays.
    await _pumpUntilGone(tester, followUp);
    expect(followUp, findsNothing);
    expect(missed, findsOneWidget);
    expect(fake.checkIns, hasLength(1));

    // Back on the roster: the badge and the row both follow without a restart.
    await tester.tap(find.byType(BackButton));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await _pumpUntilFound(tester, find.text('1 alert'));
    expect(find.text('1 alert'), findsOneWidget);
    expect(find.text('2 alerts'), findsNothing);
    expect(
      find.descendant(of: find.byType(Badge), matching: find.text('1')),
      findsOneWidget,
    );
  });

  /// History embeds the existing drill-down content and Check-ins lists the
  /// assignment's check-ins newest first (#120).
  testWidgets('the player page segments History and Check-ins',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob',
        lastWorkoutOn: '2026-09-20'));
    fake.checkIns.add(_checkInRow('check-in-1', '2026-09-01', 'phone'));
    fake.checkIns.add(_checkInRow('check-in-2', '2026-09-20', 'message'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('History'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    // History is the existing CoachPlayerHistoryScreen content, embedded.
    expect(find.text('Recent sessions'), findsOneWidget);
    expect(find.text('Personal records'), findsOneWidget);
    // The Exercises section sits below the first viewport (#120).
    final Finder exercises = find.text('Exercises');
    await tester.scrollUntilVisible(exercises, 300,
        scrollable: find.byType(Scrollable).first);
    expect(exercises, findsOneWidget);
    expect(find.text('2026-09-20 · Message'), findsNothing);

    // Back to the top so the segment control and its list are on screen.
    await tester.drag(find.byType(Scrollable).first, const Offset(0, 4000));
    await tester.pump();
    final Finder checkInsSegment = find.text('Check-ins');
    await tester.ensureVisible(checkInsSegment);
    await tester.pump();
    await tester.tap(checkInsSegment);
    await _pumpUntilFound(tester, find.text('2026-09-20 · Message'));
    expect(find.text('2026-09-01 · Phone'), findsOneWidget);
    // Newest checked_in_on first.
    expect(
      tester.getTopLeft(find.text('2026-09-20 · Message')).dy,
      lessThan(tester.getTopLeft(find.text('2026-09-01 · Phone')).dy),
    );
    expect(find.text('Volume (weighted working sets)'), findsNothing);
  });
}
