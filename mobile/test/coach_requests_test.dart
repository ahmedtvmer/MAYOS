import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/features/coach/coach_shell.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

/// Coach program requests in the shell (#121): the four client calls, the
/// Requests tab and its resolve sheet, and the badge/chip refresh.

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      await _settle(tester);
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpUntilGone(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isEmpty) {
      await _settle(tester);
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _settle(WidgetTester tester) async {
  for (int i = 0; i < 6; i++) {
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
    'last_workout_on': '2026-09-26',
  });
  return fake;
}

Map<String, dynamic> _request({
  required String id,
  required String status,
  String kind = 'exercise_substitution',
  String? response,
  String dayName = 'Upper 1',
  String exerciseId = 'bench_press',
  String replacementExerciseId = 'incline_press',
  int? desiredWeeklyFrequency,
  String? desiredSplitPreference,
  String reason = 'Shoulder discomfort.',
  String createdAt = '2026-09-25T12:00:00Z',
}) =>
    <String, dynamic>{
      'request_id': id,
      'assignment_id': 'assignment-1',
      'kind': kind,
      'program_version': 1,
      'day_name': kind == 'split_change' ? null : dayName,
      'exercise_id': kind == 'split_change' ? null : exerciseId,
      'replacement_exercise_id':
          kind == 'split_change' ? null : replacementExerciseId,
      'desired_weekly_frequency': desiredWeeklyFrequency,
      'desired_split_preference': desiredSplitPreference,
      'reason': reason,
      'status': status,
      'response': response,
      'created_at': createdAt,
      'resolved_at': status == 'pending' ? null : '2026-09-25T13:00:00Z',
      'resolved_by': status == 'pending' ? null : 'account-alice',
    };

/// Everything inside the open resolve sheet, so sheet text is never confused
/// with the same text on the cards behind it.
Finder _sheet(Finder finder) => find.descendant(
      of: find.byKey(const Key('resolve_request_sheet')),
      matching: finder,
    );

int _requestsBadge(WidgetTester tester) => tester
    .widget<MayosBottomNavigation>(find.byType(MayosBottomNavigation))
    .items[CoachShellTab.requests].badge;

Future<ApiClient> _clientFor(FakeMayosApi fake) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  return ApiClient(
    tokens: tokens,
    baseUrl: 'http://test.local',
    adapter: fake.adapter,
  );
}

void main() {
  group('client', () {
    test('the four coach program-request calls succeed', () async {
      final FakeMayosApi fake = _coachFake();
      fake.programRequests.add(_request(
        id: 'req-pending',
        status: 'pending',
        createdAt: '2026-09-24T12:00:00Z',
      ));
      fake.programRequests.add(_request(
        id: 'req-newer-pending',
        status: 'pending',
        createdAt: '2026-09-26T12:00:00Z',
        reason: 'Knee pain.',
      ));
      fake.programRequests.add(_request(
        id: 'req-answered',
        status: 'declined',
        response: 'Rest that shoulder first.',
      ));
      final ApiClient client = await _clientFor(fake);

      // 1. Cross-roster list: pending oldest first, then answered, each row
      //    carrying the requesting player (#118).
      final List<ProgramRequest> all = await client.coachAllProgramRequests();
      expect(all.map((ProgramRequest r) => r.requestId).toList(),
          <String>['req-pending', 'req-newer-pending', 'req-answered']);
      expect(
          all.every((ProgramRequest r) => r.playerUsername == 'bob'), isTrue);
      expect(all.last.status, 'declined');

      // 2. Per-assignment list.
      final List<ProgramRequest> forAssignment =
          await client.coachProgramRequests('assignment-1');
      expect(forAssignment.map((ProgramRequest r) => r.requestId).toSet(),
          <String>{'req-pending', 'req-newer-pending', 'req-answered'});

      // 3. Apply.
      final ProgramRequest applied = await client.applyCoachProgramRequest(
          'assignment-1', 'req-pending');
      expect(applied.status, 'applied');

      // 4. Decline with an optional reply of up to 500 characters.
      final ProgramRequest declined = await client.declineCoachProgramRequest(
        'assignment-1',
        'req-newer-pending',
        reply: 'Rest that shoulder first.',
      );
      expect(declined.status, 'declined');
      expect(declined.response, 'Rest that shoulder first.');
      expect(
        fake.programRequests
            .firstWhere((Map<String, dynamic> r) =>
                r['request_id'] == 'req-newer-pending')['response'],
        'Rest that shoulder first.',
      );
    });

    test('malformed coach program-request payloads fail closed', () async {
      final FakeMayosApi fake = _coachFake();
      fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
      fake.malformedProgramRequests = true;
      final ApiClient client = await _clientFor(fake);

      await expectLater(
        client.coachAllProgramRequests(),
        throwsA(isA<ApiException>()),
      );
      await expectLater(
        client.coachProgramRequests('assignment-1'),
        throwsA(isA<ApiException>()),
      );
      await expectLater(
        client.applyCoachProgramRequest('assignment-1', 'req-1'),
        throwsA(isA<ApiException>()),
      );
      await expectLater(
        client.declineCoachProgramRequest('assignment-1', 'req-1', reply: 'No.'),
        throwsA(isA<ApiException>()),
      );
    });
  });

  test('the pending-requests badge and the shell tab reset per account',
      () async {
    final FakeMayosApi fake = _coachFake();
    fake.passwords['alice'] = 'pw-alice';
    fake.passwords['bob'] = 'pw-bob';
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final ProviderContainer container = authContainerFor(fake, tokens);
    await container.read(authControllerProvider.notifier).initialize();
    expect(container.read(authControllerProvider).session?.account.accountId,
        'account-alice');

    container.read(coachShellTabProvider.notifier).state =
        CoachShellTab.requests;
    container.read(coachPendingRequestsCountProvider.notifier).state = 4;
    expect(container.read(coachShellTabProvider), CoachShellTab.requests);
    expect(container.read(coachPendingRequestsCountProvider), 4);

    await container.read(authControllerProvider.notifier).logout();
    expect(container.read(coachShellTabProvider), 0);
    expect(container.read(coachPendingRequestsCountProvider), 0);
  });

  testWidgets(
      'the shell is Roster · Alerts · Requests · Profile with a pending '
      'requests badge', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    fake.programRequests
        .add(_request(id: 'req-2', status: 'pending', reason: 'Knee pain.'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    final MayosBottomNavigation nav = tester
        .widget<MayosBottomNavigation>(find.byType(MayosBottomNavigation));
    expect(nav.items.map((MayosNavItem item) => item.label).toList(),
        <String>['Roster', 'Alerts', 'Requests', 'Profile']);
    expect(nav.items[CoachShellTab.requests].badge, 2);

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));
    expect(find.text('Answered'), findsOneWidget);
    expect(find.text('bench_press → incline_press'), findsNWidgets(2));
    expect(find.text('Nothing answered yet.'), findsOneWidget);
  });

  testWidgets(
      'pending requests are listed before answered ones, oldest pending '
      'first', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(
      id: 'req-old',
      status: 'pending',
      createdAt: '2026-09-20T12:00:00Z',
      reason: 'Old ask.',
    ));
    fake.programRequests.add(_request(
      id: 'req-new',
      status: 'pending',
      createdAt: '2026-09-26T12:00:00Z',
      reason: 'New ask.',
    ));
    fake.programRequests.add(_request(
      id: 'req-done',
      status: 'declined',
      response: 'Not now.',
      createdAt: '2026-09-21T12:00:00Z',
    ));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));

    // The two pending rows sit above the answered one, oldest pending first.
    expect(
      tester.getTopLeft(find.byKey(const Key('request_card_req-old'))).dy,
      lessThan(tester.getTopLeft(find.byKey(const Key('request_card_req-new'))).dy),
    );
    expect(
      tester.getTopLeft(find.byKey(const Key('request_card_req-new'))).dy,
      lessThan(tester.getTopLeft(find.byKey(const Key('request_card_req-done'))).dy),
    );
    // The answered row is read-only: tapping it opens no sheet.
    await tester.tap(find.byKey(const Key('request_card_req-done')));
    await _settle(tester);
    expect(find.text('bob asks'), findsNothing);
    expect(find.text('Apply swap'), findsNothing);
    expect(find.text('You: Not now.'), findsOneWidget);
  });

  testWidgets(
      'the resolve sheet shows the player, swap, reason, and reply counter, '
      'and apply refreshes the badge and the roster chip',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    fake.programRequests
        .add(_request(id: 'req-2', status: 'pending', reason: 'Knee pain.'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('2 requests'), findsOneWidget);
    expect(_requestsBadge(tester), 2);

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));

    await tester.tap(find.byKey(const Key('request_card_req-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    expect(_sheet(find.text('bob asks')), findsOneWidget);
    expect(
        _sheet(find.text('bench_press → incline_press')), findsOneWidget);
    expect(_sheet(find.text('Upper 1 · program v1')), findsOneWidget);
    expect(_sheet(find.text('“Shoulder discomfort.”')), findsOneWidget);
    expect(_sheet(find.text('Apply swap')), findsOneWidget);
    expect(_sheet(find.text('Decline')), findsOneWidget);
    expect(find.byKey(const Key('request_reply_field')), findsOneWidget);
    // The reply is capped at 500 characters and counts them down.
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('request_reply_field')))
          .maxLength,
      500,
    );
    expect(find.text('0/500'), findsOneWidget);

    await tester.enterText(
        find.byKey(const Key('request_reply_field')), 'Try incline press.');
    await tester.pump();
    expect(find.text('18/500'), findsOneWidget);
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_apply_button')));
    await _settle(tester);

    expect(
      fake.programRequests
          .firstWhere((Map<String, dynamic> r) =>
              r['request_id'] == 'req-1')['status'],
      'applied',
    );

    // The badge and the roster row's chip both follow without a restart.
    expect(_requestsBadge(tester), 1);
    await tester.tap(find.text('Roster'));
    await _pumpUntilGone(tester, find.text('2 requests'));
    expect(find.text('1 request'), findsOneWidget);

    // The answered request moved to the read-only section with no actions.
    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Answered'));
    expect(
      find.descendant(
        of: find.byKey(const Key('request_card_req-1')),
        matching: find.text('Applied'),
      ),
      findsOneWidget,
    );
    expect(find.text('Apply swap'), findsNothing);
    expect(find.text('Decline'), findsNothing);
  });

  testWidgets('a split-change request offers Apply (rebuilds program)',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(
      id: 'req-split',
      status: 'pending',
      kind: 'split_change',
      desiredWeeklyFrequency: 4,
      desiredSplitPreference: 'Upper/Lower',
      reason: 'More recovery.',
    ));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Split change → 4 days/week'));

    await tester.tap(find.byKey(const Key('request_card_req-split')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    expect(
      _sheet(find.text('Split change → 4 days/week · Upper/Lower')),
      findsOneWidget,
    );
    expect(_sheet(find.text('Apply (rebuilds program)')), findsOneWidget);
    expect(_sheet(find.text('Apply swap')), findsNothing);

    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_apply_button')));
    await _settle(tester);

    expect(fake.programRequests.single['status'], 'applied');
    expect(find.text('Answered'), findsOneWidget);
    expect(_requestsBadge(tester), 0);
  });

  testWidgets(
      'declining with a reply moves the request to Answered and clears the '
      'badge', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('1 request'), findsOneWidget);

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));
    await tester.tap(find.byKey(const Key('request_card_req-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_decline_button')));

    await tester.enterText(
        find.byKey(const Key('request_reply_field')), 'Rest first.');
    await tester.pump();
    await tester.tap(find.byKey(const Key('request_decline_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_decline_button')));
    await _settle(tester);

    expect(fake.programRequests.single['status'], 'declined');
    expect(fake.programRequests.single['response'], 'Rest first.');
    // Answered is read-only and the pending badge is gone.
    expect(find.text('Declined'), findsOneWidget);
    expect(find.text('You: Rest first.'), findsOneWidget);
    expect(find.text('Apply swap'), findsNothing);
    expect(_requestsBadge(tester), 0);
    await tester.tap(find.text('Roster'));
    await _pumpUntilGone(tester, find.text('1 request'));
    expect(find.text('1 request'), findsNothing);
  });

  testWidgets(
      'a refused resolve shows a readable message and refreshes the list',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(tester, find.text('Pending'));
    await tester.tap(find.byKey(const Key('request_card_req-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));

    // The request is answered elsewhere while the sheet is open: the service
    // refuses the apply with a readable message (#121).
    fake.programRequests.single['status'] = 'declined';
    fake.programRequests.single['response'] = 'Not now.';
    fake.programRequests.single['resolved_at'] = '2026-09-26T12:30:00Z';
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilFound(tester, find.textContaining('no longer pending'));

    // The list refreshed to the request's true state and is read-only now.
    await _pumpUntilFound(tester, find.text('Declined'));
    expect(find.text('Declined'), findsOneWidget);
    expect(find.text('Apply swap'), findsNothing);
    expect(find.byKey(const Key('request_reply_field')), findsNothing);
    expect(_requestsBadge(tester), 0);
  });

  testWidgets(
      'the player page has a Requests (count) segment that resolves through '
      'the same sheet and refreshes the badge and roster chip',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programRequests.add(_request(id: 'req-1', status: 'pending'));
    await _pumpApp(tester, fake, InMemoryAppModeStore());
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(find.text('1 request'), findsOneWidget);

    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('History'));
    await _pumpUntilFound(tester, find.text('Requests (1)'));

    await tester.tap(find.text('Requests (1)'));
    await _pumpUntilFound(tester, find.text('Program requests'));
    expect(find.text('bench_press → incline_press'), findsOneWidget);

    await tester.tap(find.byKey(const Key('request_card_req-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_apply_button')));
    expect(_sheet(find.text('bob asks')), findsOneWidget);
    expect(_sheet(find.text('Apply swap')), findsOneWidget);
    await tester.tap(find.byKey(const Key('request_apply_button')));
    await _pumpUntilGone(
        tester, find.byKey(const Key('request_apply_button')));
    await _settle(tester);

    // The page follows: the row is answered in place.
    expect(find.text('Applied'), findsOneWidget);
    expect(find.text('Requests (1)'), findsOneWidget);

    // Back on the shell: badge and roster chip both cleared without restart.
    await tester.tap(find.byType(BackButton));
    await _pumpUntilGone(tester, find.text('1 request'));
    expect(find.text('1 request'), findsNothing);
    expect(_requestsBadge(tester), 0);
  });
}
