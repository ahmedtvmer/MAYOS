import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
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

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  testWidgets('coach builds one training day and publishes a Program draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await tester.tap(find.byKey(const Key('player_page_actions')));
    await _pumpUntilFound(tester, find.text('Write program'));
    await tester.tap(find.text('Write program'));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise')));
    await tester.enterText(find.byKey(const Key('program_draft_day_name')), 'Full A');

    await tester.tap(find.byKey(const Key('program_draft_add_exercise')));
    await _pumpUntilFound(tester, find.text('Search'));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('Bench Press'));
    await tester.tap(find.text('Bench Press').last);
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0')));
    await tester.enterText(find.byKey(const Key('program_draft_sets_0')), '3');
    await tester.enterText(find.byKey(const Key('program_draft_reps_0')), '6-8');
    await tester.enterText(find.byKey(const Key('program_draft_rir_0')), '1');
    await tester.tap(find.byKey(const Key('program_draft_publish')));
    await _pumpUntilFound(tester,
        find.text('Publish this Training program now? It will become the active program.'));
    await tester.tap(find.text('Publish').last);
    await _pumpUntilFound(tester, find.text('Published program version 1'));

    expect(fake.programVersion, 1);
    expect(fake.programPublishedByCoachAccountId, 'account-alice');
    expect(fake.programDraft, isNull);
    expect(fake.programDaysOverride!.single['day_name'], 'Full A');
    final Map<String, dynamic> exercise =
        (fake.programDaysOverride!.single['exercises'] as List<dynamic>).single
            as Map<String, dynamic>;
    expect(exercise['target_sets'], 3);
    expect(exercise['target_reps_min'], 6);
    expect(exercise['target_reps_max'], 8);
    expect(exercise['target_rpe'], 9);
  });

  testWidgets('coach sees localized server validation beside the exercise field',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraftPublishError = <String, dynamic>{
        'errors': <Map<String, dynamic>>[
          <String, dynamic>{
            'code': 'invalid_reps',
            'message': 'Reps must be from 4 to 30.',
            'location': <String, dynamic>{
              'day_index': 0,
              'exercise_index': 0,
              'field': 'target_reps_min',
            },
          },
        ],
      };
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await tester.tap(find.byKey(const Key('player_page_actions')));
    await _pumpUntilFound(tester, find.text('Write program'));
    await tester.tap(find.text('Write program'));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise')));
    await tester.tap(find.byKey(const Key('program_draft_add_exercise')));
    await _pumpUntilFound(tester, find.text('Search'));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('Bench Press'));
    await tester.tap(find.text('Bench Press').last);
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_reps_0')));
    await tester.tap(find.byKey(const Key('program_draft_publish')));
    await _pumpUntilFound(
      tester,
      find.text('Publish this Training program now? It will become the active program.'),
    );
    await tester.tap(find.text('Publish').last);

    await _pumpUntilFound(
      tester,
      find.text('Enter 4–30 reps or a range such as 6-8.'),
    );
    expect(find.text('Enter 4–30 reps or a range such as 6-8.'), findsOneWidget);
    expect(find.byKey(const Key('program_draft_reps_0')), findsOneWidget);
  });

  testWidgets('coach publishes a program and sees the published version',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    // The coach shell opens on the Roster tab (#119).
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    // The player page keeps Publish program behind an overflow menu (#G).
    await tester.tap(find.byKey(const Key('player_page_actions')));
    await _pumpUntilFound(tester, find.text('Publish program'));
    await tester.tap(find.text('Publish program'));
    await _pumpUntilFound(tester, find.text('Rep preference'));
    await tester.tap(find.byKey(const Key('publish_confirm_button')));
    await _pumpUntilFound(tester, find.text('Published program version 1'));

    expect(find.text('Published program version 1'), findsOneWidget);
    expect(fake.programVersion, 1);
    expect(fake.programPublishedByCoachAccountId, 'account-alice');
  });

  testWidgets('profile shows and saves the intake rep preference values',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.repPreference = 'low';
    await _pumpApp(tester, fake);

    await _openSettings(tester);
    await tester.tap(find.text('Training profile'));
    await _pumpUntilFound(tester, find.text('Rep preference'));

    expect(tester.takeException(), isNull);
    expect(find.text('Low'), findsOneWidget);

    await tester.tap(find.text('Low'));
    await _pumpUntilFound(tester, find.text('High'));
    await tester.tap(find.text('High').last);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    await _pumpUntilFound(tester, find.text('High'));

    expect(fake.repPreference, 'high');
  });

  testWidgets('profile confirms changed Equipment access and rebuilds',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.equipmentAccess = 'Home gym';
    await _pumpApp(tester, fake);

    await _openSettings(tester);
    await tester.tap(find.text('Training profile'));
    await _pumpUntilFound(tester, find.text('Equipment access'));

    expect(find.text('Home gym'), findsOneWidget);
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('Profile saved.'));
    expect(fake.profileUpdateBodies.last, isNot(contains('equipment_access')));

    await tester.tap(find.byKey(const Key('equipment_access_dropdown')));
    await _pumpUntilFound(tester, find.text('Bodyweight only'));
    await tester.tap(find.text('Bodyweight only').last);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('Save profile'));
    await _pumpUntilFound(tester, find.text('This rebuilds your program'));
    await tester.tap(find.byKey(const Key('profile_rebuild_confirm_button')));
    await _pumpUntilFound(tester, find.text('Program rebuilt.'));

    expect(fake.equipmentAccess, 'Bodyweight only');
    expect(fake.profileUpdateBodies.last['equipment_access'], 'Bodyweight only');
    expect(fake.profileRebuildCalls, 1);
    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(tester, find.text('Appearance'));
    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(tester, find.text('Home'));
    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Rebuilt program 1'));
    expect(find.text('Rebuilt program 1'), findsOneWidget);
  });

  testWidgets('player program hides the version and keeps coach provenance',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Former coach'));

    expect(find.text('Version 6'), findsNothing);
    expect(find.text('Former coach'), findsOneWidget);
  });

  testWidgets('coach-controlled programs direct changes to the request flow',
      (tester) async {
    final FakeMayosApi fake = _playerFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    fake.coachControlsProgram = true;
    fake.activeAssignmentId = 'assignment-1';
    fake.activeCoachDisplayName = 'Coach Alice';
    await _pumpApp(tester, fake);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Your coach manages this program.'));

    expect(find.text('Request a change'), findsOneWidget);
    expect(find.text('Published by your coach'), findsOneWidget);
    expect(find.text('Regenerate program'), findsNothing);

    await tester.tap(find.text('Request a change'));
    await tester.pumpAndSettle();
    expect(find.text('Request a program change'), findsOneWidget);
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

    await _openSettings(tester);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(
        tester, find.text('Your coach published program version 1.'));

    expect(
        find.text('Your coach published program version 1.'), findsOneWidget);
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
