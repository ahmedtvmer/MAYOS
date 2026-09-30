import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';

import 'support/auth_harness.dart';
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
  fake.coachBio = 'Strength coach.';
  fake.coachSpecialization = 'Powerlifting';
  fake.coachCapacity = 12;
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-09-24T10:00:00Z',
    'status': 'active',
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-1',
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'kind': 'missed_day',
    'state': 'new',
    'created_at': '2026-09-24T08:00:00Z',
    'streak_start_date': '2026-09-20',
    'last_missed_date': '2026-09-21',
    'missed_count': 2,
    'acknowledged_at': null,
    'resolved_at': null,
    'resolved_by': null,
  });
  fake.coachAlerts.add(<String, dynamic>{
    'alert_id': 'alert-2',
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'kind': 'missed_day',
    'state': 'resolved',
    'created_at': '2026-09-20T08:00:00Z',
    'streak_start_date': '2026-09-15',
    'last_missed_date': '2026-09-17',
    'missed_count': 3,
    'acknowledged_at': '2026-09-21T08:00:00Z',
    'resolved_at': '2026-09-22T08:00:00Z',
    'resolved_by': 'coach',
  });
  return fake;
}

void main() {
  testWidgets(
      'the coach shell opens on Roster with Roster · Alerts · Profile tabs '
      'and an alerts count badge', (WidgetTester tester) async {
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore();
    await _pumpApp(tester, _coachFake(), modeStore);
    await _pumpUntilFound(tester, find.text('Active assignments'));

    // The shell lands on Roster.
    expect(find.text('Roster'), findsOneWidget);
    expect(find.text('Alerts'), findsOneWidget);
    expect(find.text('Profile'), findsOneWidget);
    expect(find.text('bob'), findsOneWidget);
    // One new alert drives the badge on the Alerts tab.
    expect(
      find.descendant(
        of: find.byType(Badge),
        matching: find.text('1'),
      ),
      findsOneWidget,
    );

    // Alerts tab: the "Show resolved" filter hides resolved rows by default.
    await tester.tap(find.text('Alerts'));
    await _pumpUntilFound(tester, find.text('Show resolved'));
    const String open = 'Missed 2 expected training days (2026-09-20 to 2026-09-21)';
    const String resolved =
        'Missed 3 expected training days (2026-09-15 to 2026-09-17)';
    expect(find.text(open), findsOneWidget);
    expect(find.text(resolved), findsNothing);
    await tester.tap(find.text('Show resolved'));
    await _pumpUntilFound(tester, find.text(resolved));
    expect(find.text(resolved), findsOneWidget);

    // Profile tab: name, bio, capacity, and the player invite.
    await tester.tap(find.text('Profile'));
    await _pumpUntilFound(tester, find.text('Coach profile'));
    expect(find.text('Strength coach.'), findsOneWidget);
    expect(find.text('Invite a player'), findsOneWidget);
    expect(find.text('Create player invite'), findsOneWidget);
  });

  testWidgets(
      'the mode sheet offers both modes with the current one ticked, plus '
      'Settings and Log out', (WidgetTester tester) async {
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore();
    await _pumpApp(tester, _coachFake(), modeStore);
    await _pumpUntilFound(tester, find.byType(ModeAvatarButton));

    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Player mode'));

    expect(find.text('Coach mode'), findsOneWidget);
    expect(find.text('alice'), findsOneWidget);
    expect(find.text('Switch mode'), findsOneWidget);
    expect(find.text('Settings'), findsOneWidget);
    expect(find.text('Log out'), findsOneWidget);
    // The current mode carries the tick.
    expect(
      find.descendant(
        of: find.widgetWithText(ListTile, 'Coach mode'),
        matching: find.byIcon(Icons.check_circle),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.widgetWithText(ListTile, 'Player mode'),
        matching: find.byIcon(Icons.check_circle),
      ),
      findsNothing,
    );
    // One-line summaries for both modes.
    expect(
      find.descendant(
        of: find.widgetWithText(ListTile, 'Coach mode'),
        matching: find.text('Your roster, alerts, and profile'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('switching to Player mode lands on the player shell and the '
      'badge reads P', (WidgetTester tester) async {
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore();
    await _pumpApp(tester, _coachFake(), modeStore);
    await _pumpUntilFound(tester, find.byType(ModeAvatarButton));
    expect(
      find.descendant(
        of: find.byKey(ModeAvatarButton.badgeKey),
        matching: find.text('C'),
      ),
      findsOneWidget,
    );

    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Player mode'));
    await tester.tap(find.text('Player mode'));

    await _pumpUntilFound(tester, find.text('Home'));
    expect(find.text('Roster'), findsNothing);
    expect(
      find.descendant(
        of: find.byKey(ModeAvatarButton.badgeKey),
        matching: find.text('P'),
      ),
      findsOneWidget,
    );
    // The choice is stored for this account only.
    expect(modeStore.values, <String, AppMode>{
      'account-alice': AppMode.player,
    });

    // And back to Coach mode.
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Coach mode'));
    await tester.tap(find.text('Coach mode'));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(modeStore.values, <String, AppMode>{
      'account-alice': AppMode.coach,
    });
  });

  testWidgets(
      'a coach in Player mode without onboarding gets the setup screen with '
      'Start intake and Back to Coach mode', (WidgetTester tester) async {
    final FakeMayosApi fake = _coachFake();
    // No profile yet: the player intake has never been completed.
    fake.profileExists = false;
    final InMemoryAppModeStore modeStore =
        InMemoryAppModeStore(<String, AppMode>{
      'account-alice': AppMode.player,
    });
    await _pumpApp(tester, fake, modeStore);

    // Deferred player onboarding: the coach is not forced to /onboarding (#119).
    await _pumpUntilFound(tester, find.text('Set up your own training'));
    expect(find.text('Start intake'), findsOneWidget);
    expect(find.text('Back to Coach mode'), findsOneWidget);
    expect(find.text('Hosted AI processing'), findsNothing);

    // Back to Coach mode returns to the shell without starting the intake.
    await tester.tap(find.text('Back to Coach mode'));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    expect(modeStore.values['account-alice'], AppMode.coach);

    // Start intake reaches the onboarding flow (which stays gated by the
    // recovery email, already satisfied here).
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Player mode'));
    await tester.tap(find.text('Player mode'));
    await _pumpUntilFound(tester, find.text('Set up your own training'));
    await tester.tap(find.text('Start intake'));
    await _pumpUntilFound(tester, find.text('Hosted AI processing'));
  });

  test('the coach alerts badge resets when the account changes',
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

    // This account has a non-zero alerts badge.
    container.read(coachNewAlertsCountProvider.notifier).state = 3;
    expect(container.read(coachNewAlertsCountProvider), 3);

    // Signing out resets the badge for whoever signs in next.
    await container.read(authControllerProvider.notifier).logout();
    expect(container.read(coachNewAlertsCountProvider), 0);

    // A direct account switch never shows the previous account's badge.
    container.read(coachNewAlertsCountProvider.notifier).state = 7;
    await container
        .read(authControllerProvider.notifier)
        .login(username: 'bob', password: 'pw-bob');
    expect(container.read(authControllerProvider).session?.account.accountId,
        'account-bob');
    expect(container.read(coachNewAlertsCountProvider), 0);
  });

  testWidgets('a non-coach account sees no mode badge', (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    fake.issuedToken = 'token-alice';
    fake.currentUsername = 'alice';
    fake.tokenValid = true;
    fake.coach = false;
    fake.profileExists = true;
    fake.recoveryEmail = 'alice@example.com';
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore();
    await _pumpApp(tester, fake, modeStore);
    await _pumpUntilFound(tester, find.text('Home'));

    expect(find.byType(ModeAvatarButton), findsNothing);
    expect(modeStore.values, isEmpty);
  });
}
