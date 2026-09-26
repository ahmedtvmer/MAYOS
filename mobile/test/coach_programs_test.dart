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

FakeMayosApi _playerFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = false;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

void main() {
  testWidgets('coach publishes a program and sees the published version',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.handshake_outlined));
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(
        tester, find.text('Volume (weighted working sets)'));

    await tester.tap(find.text('Publish program'));
    await _pumpUntilFound(tester, find.text('Rep preference'));
    await tester.tap(find.byKey(const Key('publish_confirm_button')));
    await _pumpUntilFound(
        tester, find.text('Published program version 1'));

    expect(find.text('Published program version 1'), findsOneWidget);
    expect(fake.programVersion, 1);
    expect(fake.programPublishedByCoachAccountId, 'account-alice');
  });

  testWidgets('player program shows the version and coach provenance',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Version 6'));

    expect(find.text('Version 6'), findsOneWidget);
    expect(find.text('Published by your coach'), findsOneWidget);
  });

  testWidgets('self-service regeneration is refused with the server message',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    fake.coachControlsProgram = true;
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Regenerate program'));
    await tester.tap(find.text('Regenerate program'));
    await _pumpUntilFound(
      tester,
      find.text(
          'Your assigned coach controls your program. Ask your coach for changes.'),
    );

    expect(
      find.text(
          'Your assigned coach controls your program. Ask your coach for changes.'),
      findsOneWidget,
    );
  });

  testWidgets('player sees a program_published notice and can mark it read',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.playerNotices.add(<String, dynamic>{
      'notice_id': 'notice-1',
      'assignment_id': 'assignment-1',
      'kind': 'program_published',
      'message': 'Your coach published program version 1.',
      'created_at': '2026-09-24T11:00:00Z',
      'read_at': null,
    });
    await _pumpApp(tester, fake);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(
        tester, find.text('Your coach published program version 1.'));

    expect(find.text('Your coach published program version 1.'),
        findsOneWidget);
    expect(find.textContaining('program_published'), findsOneWidget);

    await tester.tap(find.text('Mark all read'));
    await _pumpUntilFound(tester, find.byIcon(Icons.notifications_none));
    expect(fake.playerNotices.first['read_at'], isNotNull);
  });

  test('malformed player-notice payloads fail closed with ApiException',
      () async {
    final FakeMayosApi fake = _playerFake();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('token-alice');
    final ApiClient client = ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

    fake.playerNotices.add(<String, dynamic>{'notice_id': 7});
    await expectLater(
      client.playerNotices(),
      throwsA(isA<ApiException>()),
    );
  });
}
