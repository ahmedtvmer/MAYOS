import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/core/ui/mayos_card.dart';
import 'package:mayos_mobile/src/features/coach/coach_player_history_screen.dart';
import 'package:mayos_mobile/src/features/coach/coach_shell.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

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

Future<void> _pumpApp(WidgetTester tester, FakeMayosApi fake,
    {Size size = const Size(1440, 960),
    InMemoryAppModeStore? modeStore}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider
            .overrideWithValue(modeStore ?? InMemoryAppModeStore()),
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
  await _pumpUntilFound(tester, find.text('Active assignments'));
}

GoRouter _router(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MayosApp)))
        .read(routerProvider);

String _path(WidgetTester tester) =>
    _router(tester).routeInformationProvider.value.uri.path;

Future<void> _openUrl(WidgetTester tester, String location) async {
  _router(tester).go(location);
  await tester.pumpAndSettle();
}

Finder _playerTitle(String username) => find.descendant(
      of: find.byKey(const Key('coach_player_history_app_bar')),
      matching: find.text(username),
    );

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

Map<String, dynamic> _assignment(String id, String username) =>
    <String, dynamic>{
      'assignment_id': id,
      'player_username': username,
      'started_at': '2026-09-01T10:00:00Z',
      'status': 'active',
      'current_missed_streak': 0,
      'next_follow_up_on': null,
      'pending_requests': 0,
      'last_workout_on': null,
    };

Map<String, dynamic> _request({
  String id = 'request-1',
  String assignmentId = 'assignment-1',
}) => <String, dynamic>{
      'request_id': id,
      'assignment_id': assignmentId,
      'kind': 'exercise_substitution',
      'program_version': 1,
      'day_name': 'Upper 1',
      'exercise_id': 'bench_press',
      'replacement_exercise_id': 'incline_press',
      'desired_weekly_frequency': null,
      'desired_split_preference': null,
      'reason': 'Shoulder discomfort.',
      'status': 'pending',
      'response': null,
      'created_at': '2026-09-25T12:00:00Z',
      'resolved_at': null,
      'resolved_by': null,
    };

int _calls(FakeMayosApi fake, String path) => fake.adapter.requests
    .where((request) => request.method == 'GET' && request.path == path)
    .length;

void main() {
  testWidgets('coach tabs have clean URLs and mode switching persists the URL',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore();
    await _pumpApp(tester, fake, modeStore: modeStore);

    _router(tester).go(coachPath);
    await tester.pumpAndSettle();
    expect(_path(tester), coachRosterPath);
    await tester.tap(find.text('Alerts'));
    await tester.pumpAndSettle();
    expect(_path(tester), coachAlertsPath);
    await tester.tap(find.text('Requests'));
    await tester.pumpAndSettle();
    expect(_path(tester), coachRequestsPath);
    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();
    expect(_path(tester), coachProfilePath);
    await _openUrl(tester, coachRequestsPath);
    expect(_path(tester), coachRequestsPath);
    expect(
      tester.widget<NavigationRail>(find.byType(NavigationRail)).selectedIndex,
      CoachShellTab.requests,
    );
    await _openUrl(tester, coachProfilePath);
    expect(_path(tester), coachProfilePath);

    await tester.tap(find.byType(ModeAvatarButton));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Player mode'));
    await tester.pumpAndSettle();
    expect(_path(tester), homePath);
    expect(modeStore.values['account-alice'], AppMode.player);

    await tester.tap(find.byType(ModeAvatarButton));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Coach mode'));
    await tester.pumpAndSettle();
    expect(_path(tester), coachProfilePath);
    expect(modeStore.values['account-alice'], AppMode.coach);
  });

  testWidgets('desktop roster selection updates and restores the right pane',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    fake.assignments.add(_assignment('assignment-2', 'carol'));
    await _pumpApp(tester, fake);

    await tester.tap(find.byKey(const Key('roster_row_assignment-1')));
    await _pumpUntilFound(tester, _playerTitle('bob'));
    expect(_path(tester), '$coachRosterPath/assignment-1');
    expect(_calls(fake, '/coach/assignments'), 1);
    expect(find.byType(CoachPlayerHistoryScreen), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('coach_roster_master_pane')),
        matching: find.byKey(const Key('roster_row_assignment-2')),
      ),
      findsOneWidget,
    );

    await tester.tap(
      find.descendant(
        of: find.byKey(const Key('coach_roster_master_pane')),
        matching: find.byKey(const Key('roster_row_assignment-2')),
      ),
    );
    await _pumpUntilFound(tester, _playerTitle('carol'));
    expect(_path(tester), '$coachRosterPath/assignment-2');
    expect(_playerTitle('bob'), findsNothing);
    expect(_calls(fake, '/coach/assignments'), 1);

    // A URL opened directly, as after reload, reconstructs the same selection.
    _router(tester).go('$coachRosterPath/assignment-1');
    await _pumpUntilFound(tester, _playerTitle('bob'));
    expect(_path(tester), '$coachRosterPath/assignment-1');
  });

  testWidgets('phone roster selection stays over the shell and system back restores it',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    await _pumpApp(tester, fake, size: const Size(390, 844));

    await tester.tap(find.byKey(const Key('roster_row_assignment-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_player_history_app_bar')));
    expect(_path(tester), '$coachRosterPath/assignment-1');
    expect(find.text('Active assignments'), findsNothing);
    final int alertsOnPlayerPage = _calls(fake, '/coach/alerts');
    final int requestsOnPlayerPage = _calls(fake, '/coach/program-requests');
    final container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final int rosterRevisionBeforeBack =
        container.read(coachRosterRevisionProvider);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(_path(tester), coachRosterPath);
    expect(find.byType(MayosBottomNavigation), findsOneWidget);
    expect(
      container.read(coachRosterRevisionProvider),
      rosterRevisionBeforeBack + 1,
    );
    expect(_calls(fake, '/coach/alerts'), alertsOnPlayerPage);
    expect(_calls(fake, '/coach/program-requests'), requestsOnPlayerPage);

    // A cold or reloaded player URL selects the same assignment on phones.
    _router(tester).go('$coachRosterPath/assignment-1');
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_player_history_app_bar')));
    expect(_path(tester), '$coachRosterPath/assignment-1');
  });

  testWidgets('ended and foreign assignment URLs share the generic denial',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    _router(tester).go('$coachRosterPath/ended-assignment');
    await _pumpUntilFound(tester, find.text('No active assignment.'));
    expect(find.textContaining('ended-assignment'), findsNothing);

    _router(tester).go('$coachRosterPath/foreign-assignment');
    await _pumpUntilFound(tester, find.text('No active assignment.'));
    expect(find.textContaining('foreign-assignment'), findsNothing);
    expect(find.text('No active assignment.'), findsOneWidget);
    expect(find.byKey(const Key('coach_roster_master_pane')), findsOneWidget);
    expect(find.byKey(const Key('log_check_in_action')), findsNothing);
    expect(find.byKey(const Key('player_page_actions')), findsNothing);
  });

  testWidgets('desktop requests expose URL-addressable detail and actions',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    fake.programRequests.add(_request());
    fake.programRequests.add(_request(id: 'request-2'));
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Requests'));
    await _pumpUntilFound(
        tester, find.byKey(const Key('request_card_request-1')));
    expect(_path(tester), coachRequestsPath);
    await tester.tap(find.byKey(const Key('request_card_request-1')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_request_detail_pane')));
    expect(_path(tester), '$coachRequestsPath/request-1');
    expect(find.byKey(const Key('request_apply_button')), findsOneWidget);
    expect(find.byKey(const Key('request_decline_button')), findsOneWidget);
    expect(find.byKey(const Key('request_card_request-1')), findsOneWidget);
    expect(
      tester.widget<MayosCard>(find.byKey(const Key('request_card_request-1')))
          .selected,
      isTrue,
    );
    final int requestReads = _calls(fake, '/coach/program-requests');

    await tester.tap(find.byKey(const Key('request_card_request-2')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('coach_request_detail_pane')));
    expect(_path(tester), coachRequestLocation('request-2'));
    expect(find.byKey(const Key('request_card_request-2')), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(_calls(fake, '/coach/program-requests'), requestReads);
    expect(
      tester.widget<MayosCard>(find.byKey(const Key('request_card_request-2')))
          .selected,
      isTrue,
    );
  });

  testWidgets('desktop back and forward URLs restore both roster selections',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    fake.assignments.add(_assignment('assignment-2', 'carol'));
    await _pumpApp(tester, fake);

    _router(tester).go(coachAssignmentLocation('assignment-1'));
    await _pumpUntilFound(tester, _playerTitle('bob'));
    _router(tester).go(coachAssignmentLocation('assignment-2'));
    await _pumpUntilFound(tester, _playerTitle('carol'));
    expect(_path(tester), coachAssignmentLocation('assignment-2'));
    _router(tester).go(coachAssignmentLocation('assignment-1'));
    await _pumpUntilFound(tester, _playerTitle('bob'));
    expect(_path(tester), coachAssignmentLocation('assignment-1'));
    expect(_playerTitle('carol'), findsNothing);
    _router(tester).go(coachAssignmentLocation('assignment-2'));
    await _pumpUntilFound(tester, _playerTitle('carol'));
    expect(_path(tester), coachAssignmentLocation('assignment-2'));
  });

  testWidgets('unknown request URL shows the generic denial on desktop',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    fake.programRequests.add(_request(id: 'foreign-request', assignmentId: 'other-assignment'));
    await _pumpApp(tester, fake);

    _router(tester).go(coachRequestLocation('foreign-request'));
    await _pumpUntilFound(
        tester, find.text('This request is no longer available.'));
    expect(find.byKey(const Key('coach_request_master_pane')), findsOneWidget);
    expect(find.textContaining('foreign-request'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('unknown request URL shows the generic denial on phone',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.assignments.add(_assignment('assignment-1', 'bob'));
    await _pumpApp(tester, fake, size: const Size(390, 844));

    _router(tester).go(coachRequestLocation('unknown-request'));
    await _pumpUntilFound(
        tester, find.text('This request is no longer available.'));
    expect(find.textContaining('unknown-request'), findsNothing);
    expect(find.byType(MayosBottomNavigation), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
