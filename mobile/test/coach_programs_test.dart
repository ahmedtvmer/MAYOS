import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
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

Future<void> _openProgramSegment(
  WidgetTester tester, {
  String label = 'Program',
}) async {
  await _pumpUntilFound(
    tester,
    find.text(
      label == 'البرنامج التدريبي'
          ? 'مجموعات محسوبة لكل عضلة'
          : 'Volume (weighted working sets)',
    ),
  );
  await tester.tap(find.text(label).first);
  await tester.pump();
}

Future<void> _openProgramEditor(WidgetTester tester, FakeMayosApi fake) async {
  final bool isArabic = fake.displayLanguage == 'ar';
  await _pumpApp(tester, fake);
  await _pumpUntilFound(
    tester,
    find.text(isArabic ? 'علاقات التدريب النشطة' : 'Active assignments'),
  );
  await tester.tap(find.text('bob'));
  await _pumpUntilFound(
    tester,
    find.text(
      isArabic ? 'مجموعات محسوبة لكل عضلة' : 'Volume (weighted working sets)',
    ),
  );
  await _openProgramSegment(
    tester,
    label: isArabic ? 'البرنامج التدريبي' : 'Program',
  );
  await tester.tap(find.byKey(const Key('write_program_action')));
  await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));
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

Map<String, dynamic> _coachActiveProgram({
  required String provenance,
  bool hasDraft = false,
  bool editedByPlayer = false,
}) =>
    <String, dynamic>{
      'has_draft': hasDraft,
      if (editedByPlayer) 'edited_by_player': true,
      'program': <String, dynamic>{
        'program_name': 'Full Body',
        'split_type': 'Full Body',
        'weekly_frequency': 1,
        'instructions': '',
        'version': 7,
        'provenance': provenance,
        'active_since': '2026-10-04T10:00:00Z',
        'days': <Map<String, dynamic>>[
          <String, dynamic>{
            'day_name': 'Full A',
            'day_order': 1,
            'exercises': <Map<String, dynamic>>[
              <String, dynamic>{
                'exercise_id': 'sq',
                'exercise_name': 'Squat',
                'target_sets': 4,
                'target_reps_min': 6,
                'target_reps_max': 8,
                'target_rpe': 8.0,
                'rest_seconds': 150,
                'tempo': '3-1-1',
                'notes': 'Brace before each rep.',
              },
            ],
          },
        ],
      },
    };

Map<String, dynamic> _pendingSubstitutionRequest(
  String requestId, {
  String? exerciseName = 'Squat',
}) =>
    <String, dynamic>{
      'request_id': requestId,
      'assignment_id': 'assignment-1',
      'kind': 'exercise_substitution',
      'program_version': 7,
      'exercise_id': 'sq',
      'exercise_name': exerciseName,
      'reason': 'Please change this exercise.',
      'status': 'pending',
      'created_at': '2026-10-02T10:00:00Z',
    };

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
  testWidgets('coach picker sends Equipment category and Load type filters',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _openProgramEditor(tester, fake);
    await tester.tap(find.byKey(const Key('program_draft_add_day')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_add_exercise_0')),
    );
    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));

    await tester.tap(
      find.byKey(const Key('exercise_equipment_category_filter')),
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('equipment_category_option_Machine')),
    );
    await tester.tap(
      find.byKey(const Key('exercise_equipment_category_done')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('exercise_load_type_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('load_type_option_selectorized')));
    await tester.tap(find.byKey(const Key('exercise_load_type_done')));
    await _pumpUntilFound(tester, find.text('Machine Row'));

    final request = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(request.query['equipment_category'], <String>['Machine']);
    expect(request.query['load_type'], <String>['selectorized']);
  });

  testWidgets('coach player page shows automatic program and pending draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'automatic',
        hasDraft: true,
      );
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Generated automatically'));

    expect(find.text('Program draft pending'), findsOneWidget);
    expect(find.byKey(const Key('coach_program_edit_active')), findsOneWidget);
    expect(find.text('program v7'), findsOneWidget);
    expect(find.text('Active since 2026-10-04'), findsOneWidget);
    expect(find.text('Squat'), findsOneWidget);
    expect(find.text('4 sets · 6–8 reps · RIR ≥ 2 · Rest 150 s'), findsOneWidget);
    expect(find.text('Tempo: 3-1-1'), findsOneWidget);
    expect(find.text('Notes: Brace before each rep.'), findsOneWidget);

    await tester.tap(find.text('History').first);
    await _pumpUntilFound(tester, find.text('Since 2026-09-24T10:00:00Z'));
    expect(find.byKey(const Key('coach_program_edit_active')), findsNothing);
    expect(find.text('program v7'), findsNothing);
    expect(find.text('Generated automatically'), findsNothing);
    expect(find.text('Active since 2026-10-04'), findsNothing);
  });

  testWidgets('coach player page labels current coach program and player edit',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'coach',
        editedByPlayer: true,
      );
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Published by you'));

    expect(find.text('Edited by the player'), findsOneWidget);
    expect(find.text('Program draft pending'), findsNothing);
  });

  testWidgets('coach player page shows an empty program state', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('No active program.'));

    expect(find.text('No active program.'), findsOneWidget);
  });

  testWidgets('Edit copies the active program into a draft before opening it',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_edit_active')));

    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise_0')));

    expect(fake.programDraftCopyRequests, 1);
    expect(fake.programDraft!['program_name'], 'Full Body');
    expect((fake.programDraft!['days'] as List<dynamic>).first['day_name'], 'Full A');
    final Map<String, dynamic> exercise =
        ((fake.programDraft!['days'] as List<dynamic>).first['exercises']
            as List<dynamic>).first as Map<String, dynamic>;
    expect(exercise['target_rir'], 2);
    expect(exercise['notes'], 'Brace before each rep.');
  });

  testWidgets('Edit lets the coach continue an existing Program draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'automatic',
        hasDraft: true,
      )
      ..programDraft = <String, dynamic>{
        'program_name': 'Saved draft',
        'split_type': 'Full Body',
        'weekly_frequency': 1,
        'instructions': '',
        'days': <Map<String, dynamic>>[
          <String, dynamic>{
            'day_name': 'Saved day',
            'day_order': 1,
            'warmup_exercises': <dynamic>[],
            'exercises': <Map<String, dynamic>>[
              <String, dynamic>{
                'exercise_id': 'sq',
                'exercise_name': 'Squat',
                'warmup_sets': 0,
                'target_sets': 3,
                'target_reps_min': 6,
                'target_reps_max': 8,
                'target_rir': 2,
                'rest_seconds': 180,
                'notes': null,
              },
            ],
            'cardio': null,
          },
        ],
      };
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_edit_active')));

    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_continue_draft')));
    await tester.tap(find.byKey(const Key('coach_program_continue_draft')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_day_name_0')));

    expect(fake.programDraftCopyRequests, 0);
    expect(
      tester.widget<TextField>(find.byKey(const Key('program_draft_day_name_0')))
          .controller?.text,
      'Saved day',
    );
  });

  testWidgets('Edit can replace an existing Program draft from the active one',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'automatic',
        hasDraft: true,
      )
      ..programDraft = <String, dynamic>{'program_name': 'Saved draft'};
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_edit_active')));

    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_replace_draft')));
    await tester.tap(find.byKey(const Key('coach_program_replace_draft')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise_0')));

    expect(fake.programDraftCopyRequests, 1);
    expect(fake.programDraft!['program_name'], 'Full Body');
  });

  testWidgets('Approve as is confirms before publishing a new coach version',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'automatic',
        hasDraft: true,
      )
      ..programDraft = <String, dynamic>{'program_name': 'Saved draft'}
      ..programRequests.addAll(<Map<String, dynamic>>[
        _pendingSubstitutionRequest('request-1'),
        _pendingSubstitutionRequest('request-2'),
      ]);
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));
    expect(find.textContaining('pending Program draft'), findsNothing);
    for (final String requestId in <String>['request-1', 'request-2']) {
      final Finder requestRow =
          find.byKey(Key('publish_resolve_$requestId'));
      expect(
        find.descendant(
          of: requestRow,
          matching: find.textContaining('Substitution request'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: requestRow,
          matching: find.textContaining('2026-10-02'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: requestRow,
          matching: find.text('Squat · Date: \u20662026-10-02\u2069'),
        ),
        findsOneWidget,
      );
    }
    expect(
      tester.widget<CheckboxListTile>(
        find.byKey(const Key('publish_resolve_request-1')),
      ).value,
      isTrue,
    );
    await tester.tap(find.byKey(const Key('publish_resolve_request-2')));
    expect(fake.programVersion, isNull);
    await tester.tap(find.byKey(const Key('coach_program_approve_confirm')));
    await _pumpUntilFound(
      tester,
      find.text('Published program version 8 · Resolved 1 request'),
    );

    expect(fake.programApproveRequests, 1);
    expect(fake.lastProgramApproveExpectedVersion, 7);
    expect(fake.lastProgramApproveResolveRequestIds, <String>['request-1']);
    expect(fake.programDraftCopyRequests, 0);
    expect(fake.programVersion, 8);
    expect(fake.programPublishedByCoachAccountId, 'account-alice');
    expect(fake.coachActiveProgram['program']?['provenance'], 'coach');
    expect(fake.programDraft?['program_name'], 'Saved draft');
  });

  testWidgets('failed Approve as is leaves selected requests open without a count',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic')
      ..programApproveMismatchVersion = 8
      ..programRequests.add(_pendingSubstitutionRequest('request-1'));
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));
    await tester.tap(find.byKey(const Key('coach_program_approve_confirm')));
    await _pumpUntilFound(
      tester,
      find.text('The player\'s program changed. Review it and approve again.'),
    );

    expect(fake.programRequests.single['status'], 'pending');
    expect(fake.lastProgramApproveResolveRequestIds, <String>['request-1']);
    expect(find.textContaining('Resolved 1 request'), findsNothing);
    expect(find.textContaining('Published program version'), findsNothing);
  });

  testWidgets('Approve as is request confirmation renders Arabic copy',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..displayLanguage = 'ar'
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic')
      ..programRequests.addAll(<Map<String, dynamic>>[
        _pendingSubstitutionRequest('request-1'),
        _pendingSubstitutionRequest('request-missing', exerciseName: null),
      ]);
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('قائمة اللاعبين'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));

    final Finder requestRow =
        find.byKey(const Key('publish_resolve_request-1'));
    expect(
      find.descendant(
        of: requestRow,
        matching: find.textContaining('طلب تبديل تمرين من المدرب'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: requestRow,
        matching: find.text('Squat · التاريخ: \u20662026-10-02\u2069'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: requestRow,
        matching: find.textContaining('2026-10-02'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('publish_resolve_request-missing')),
        matching: find.text('التمرين · التاريخ: \u20662026-10-02\u2069'),
      ),
      findsOneWidget,
    );
    expect(
      tester.widget<CheckboxListTile>(
        find.byKey(const Key('publish_resolve_request-1')),
      ).value,
      isTrue,
    );
  });

  testWidgets('publish confirmation uses a localized fallback for a missing name',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic')
      ..programRequests.add(
        _pendingSubstitutionRequest('request-missing', exerciseName: null),
      );
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));

    final Finder requestRow =
        find.byKey(const Key('publish_resolve_request-missing'));
    expect(
      find.descendant(
        of: requestRow,
        matching: find.text('Exercise · Date: \u20662026-10-02\u2069'),
      ),
      findsOneWidget,
    );
    expect(find.text('sq'), findsNothing);
  });

  testWidgets('stale Approve as is reloads the program before retrying',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic')
      ..programApproveMismatchVersion = 8
      ..programApproveMismatchName = 'Updated Full Body';
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));
    await tester.tap(find.byKey(const Key('coach_program_approve_confirm')));
    await _pumpUntilFound(tester, find.text('Updated Full Body'));
    await _pumpUntilFound(tester, find.text('program v8'));
    await _pumpUntilFound(
      tester,
      find.text("The player's program changed. Review it and approve again."),
    );

    expect(fake.programApproveExpectedVersions, <int?>[7]);
    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));
    await tester.tap(find.byKey(const Key('coach_program_approve_confirm')));
    await _pumpUntilFound(tester, find.text('Published program version 9'));

    expect(fake.programApproveExpectedVersions, <int?>[7, 8]);
    expect(fake.programDraftCopyRequests, 0);
  });

  testWidgets('coach creates and reuses a Coach exercise from the picker',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('write_program_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise_0')));

    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.enterText(find.byType(TextField).last, 'Pin Squat');
    await tester.tap(find.byKey(const Key('coach_exercise_search')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_create_exercise_open')));
    await tester.tap(find.byKey(const Key('coach_create_exercise_open')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_name')));
    await tester.enterText(find.byKey(const Key('coach_exercise_note')), 'Pause on the pins.');
    await tester.enterText(
      find.byKey(const Key('coach_exercise_video')),
      'https://example.com/pin-squat',
    );
    await tester.tap(find.byKey(const Key('coach_exercise_create')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_0')));
    expect(fake.coachExerciseRows.single['image_path'], isNull);
    expect(fake.coachExerciseRows.single['video_url'], 'https://example.com/pin-squat');

    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    expect(
      find.byKey(const Key('exercise_primary_muscle_filter')),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('exercise_primary_muscle_filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(
      const Key('primary_muscle_option_Biceps'),
    ));
    await tester.tap(find.byKey(
      const Key('exercise_primary_muscle_done'),
    ));
    await _pumpUntilFound(tester, find.text('Bicep Curl'));
    expect(find.text('Cable Fly'), findsNothing);
    expect(find.text('Bench Press'), findsNothing);
    expect(
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Pin Squat'),
      ),
      findsNothing,
    );
    final coachFilterRequest = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(coachFilterRequest.query['primary_muscle'], <String>['Biceps']);

    final Finder actionFilter =
        find.byKey(const Key('exercise_primary_action_filter'));
    await tester.ensureVisible(actionFilter);
    await tester.tap(actionFilter);
    await tester.pumpAndSettle();
    final Finder elbowFlexion = find.byKey(
      const Key('primary_action_option_Elbow Flexion'),
    );
    await tester.ensureVisible(elbowFlexion);
    await tester.tap(elbowFlexion);
    await tester.tap(find.byKey(const Key('exercise_primary_action_done')));
    await _pumpUntilFound(tester, find.text('Bicep Curl'));
    expect(
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Pin Squat'),
      ),
      findsNothing,
    );
    final actionRequest = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(actionRequest.query['primary_action'], <String>['Elbow Flexion']);
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.enterText(find.byType(TextField).last, 'Pin Squat');
    await tester.tap(find.byKey(const Key('coach_exercise_search')));
    await _pumpUntilFound(tester, find.text('Your exercise'));
    await tester.tap(find.text('Pin Squat').last);
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_1')));
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final List<dynamic> days = fake.programDraft!['days'] as List<dynamic>;
    final List<dynamic> exercises =
        (days.single as Map<String, dynamic>)['exercises'] as List<dynamic>;
    expect(exercises, hasLength(2));
    expect((exercises.first as Map<String, dynamic>)['exercise_id'], startsWith('coach:'));
    expect((exercises.first as Map<String, dynamic>)['note'], 'Pause on the pins.');
    expect((exercises.first as Map<String, dynamic>)['video_url'], 'https://example.com/pin-squat');
  });

  testWidgets('coach builds one training day and publishes a Program draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programRequests.addAll(<Map<String, dynamic>>[
        _pendingSubstitutionRequest('draft-request-1'),
        _pendingSubstitutionRequest('draft-request-2'),
      ]);
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('write_program_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise_0')));
    await tester.enterText(find.byKey(const Key('program_draft_day_name_0')), 'Full A');

    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.text('Search'));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('Bench Press'));
    await tester.tap(find.text('Bench Press').last);
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_0')));
    await tester.enterText(find.byKey(const Key('program_draft_sets_0_0')), '3');
    await tester.enterText(find.byKey(const Key('program_draft_reps_0_0')), '6-8');
    await tester.enterText(find.byKey(const Key('program_draft_rir_0_0')), '1');
    await tester.enterText(
      find.byKey(const Key('program_draft_warmup_sets_0_0')),
      '2',
    );
    await tester.enterText(find.byKey(const Key('program_draft_rest_0_0')), '150');
    await tester.enterText(find.byKey(const Key('program_draft_tempo_0_0')), '3-1-1');
    await tester.enterText(
      find.byKey(const Key('program_draft_notes_0_0')),
      'Pause on the chest',
    );
    await tester.tap(find.byKey(const Key('program_draft_publish')));
    await _pumpUntilFound(tester,
        find.text('Publish this Training program now? It will become the active program.'));
    expect(find.textContaining('Substitution request'), findsNWidgets(2));
    expect(
      tester.widget<CheckboxListTile>(
        find.byKey(const Key('publish_resolve_draft-request-1')),
      ).value,
      isTrue,
    );
    await tester.tap(find.byKey(const Key('publish_resolve_draft-request-2')));
    await tester.tap(find.text('Publish').last);
    await _pumpUntilFound(
      tester,
      find.text('Published program version 1 · Resolved 1 request'),
    );

    expect(fake.programVersion, 1);
    expect(fake.lastProgramDraftResolveRequestIds, <String>['draft-request-1']);
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
    expect(exercise['warmup_sets'], 2);
    expect(exercise['rest_seconds'], 150);
    expect(exercise['tempo'], '3-1-1');
    expect(exercise['notes'], 'Pause on the chest');
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
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('write_program_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_exercise_0')));
    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.text('Search'));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('Bench Press'));
    await tester.tap(find.text('Bench Press').last);
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_reps_0_0')));
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
    expect(find.byKey(const Key('program_draft_reps_0_0')), findsOneWidget);
  });

  testWidgets('coach sees Save validation beside the warm-up movement',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraftReplaceError = <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'less_than_equal',
          'loc': <Object>[
            'body', 'days', 0, 'warmup_exercises', 0, 'sets',
          ],
          'msg': 'Input should be less than or equal to 3',
        },
        <String, dynamic>{
          'type': 'greater_than_equal',
          'loc': <Object>['body', 'days', 0, 'day_order'],
          'msg': 'Input should be greater than or equal to 1',
        },
      ];
    await _openProgramEditor(tester, fake);
    await tester.tap(find.byKey(const Key('program_draft_warmup_add_0')));
    await tester.tap(find.byKey(const Key('program_draft_save')));

    await _pumpUntilFound(
      tester,
      find.text('Warm-up movements need 1 to 3 sets.'),
    );
    expect(find.text('Warm-up movements need 1 to 3 sets.'), findsOneWidget);
    expect(find.text('A program must have 1 to 5 training days.'), findsOneWidget);
  });

  testWidgets('coach validates ramped warm-up sets before saving',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _openProgramEditor(tester, fake);
    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.text('Search'));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('Bench Press'));
    await tester.tap(find.text('Bench Press').last);
    final Finder warmupSets =
        find.byKey(const Key('program_draft_warmup_sets_0_0'));
    await _pumpUntilFound(tester, warmupSets);
    await tester.enterText(warmupSets, '5');
    await tester.tap(find.byKey(const Key('program_draft_save')));

    await _pumpUntilFound(
      tester,
      find.text('Warm-up sets must be from 0 to 4.'),
    );
    final List<dynamic> savedDays = fake.programDraft!['days'] as List<dynamic>;
    expect(savedDays, hasLength(1));
    expect((savedDays.single as Map)['exercises'], isEmpty);
  });

  testWidgets('unsaved program edits ask before leaving', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _openProgramEditor(tester, fake);
    await tester.enterText(
      find.byKey(const Key('program_draft_day_name_0')),
      'Changed day',
    );
    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(tester, find.text('Unsaved changes'));
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(TextButton),
      ),
      findsNWidgets(2),
    );
    await tester.tap(find.byKey(const Key('program_draft_confirm_cancel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('program_draft_save')), findsOneWidget);

    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_confirm_action')),
    );
    await tester.tap(find.byKey(const Key('program_draft_confirm_action')));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
  });

  testWidgets('coach reorders and duplicates training days', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _openProgramEditor(tester, fake);

    await tester.tap(find.byKey(const Key('program_draft_add_day')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_day_name_1')));
    await tester.enterText(
      find.byKey(const Key('program_draft_day_name_1')),
      'Lower A',
    );
    await tester.tap(find.byKey(const Key('program_draft_day_duplicate_1')));
    await tester.drag(find.byType(ListView).first, const Offset(0, -900));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_day_up_2')));
    await tester.tap(find.byKey(const Key('program_draft_day_up_2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final List<dynamic> days = fake.programDraft!['days'] as List<dynamic>;
    expect(days.map((dynamic day) => (day as Map)['day_name']), <String>[
      'Day 1',
      'Lower A copy',
      'Lower A',
    ]);
    expect(days.map((dynamic day) => (day as Map)['day_order']), <int>[1, 2, 3]);
    expect(fake.programDraft!['weekly_frequency'], 3);
  });

  testWidgets('coach saves warm-up movements and the day cardio note',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _openProgramEditor(tester, fake);

    await tester.tap(find.byKey(const Key('program_draft_warmup_add_0')));
    final Finder movementName =
        find.byKey(const Key('program_draft_warmup_name_0_0'));
    await _pumpUntilFound(tester, movementName);
    await tester.ensureVisible(movementName);
    await tester.enterText(movementName, 'Band Pull Apart');
    final Finder movementNotes =
        find.byKey(const Key('program_draft_warmup_notes_0_0'));
    await _pumpUntilFound(tester, movementNotes);
    await tester.ensureVisible(movementNotes);
    await tester.enterText(movementNotes, 'Easy pace');
    await tester.ensureVisible(
      find.byKey(const Key('program_draft_warmup_add_0')),
    );
    await tester.tap(find.byKey(const Key('program_draft_warmup_add_0')));
    final Finder secondMovementName =
        find.byKey(const Key('program_draft_warmup_name_0_1'));
    await _pumpUntilFound(tester, secondMovementName);
    await tester.ensureVisible(secondMovementName);
    await tester.enterText(secondMovementName, 'Cat-Cow');
    final Finder moveWarmupUp =
        find.byKey(const Key('program_draft_warmup_up_0_1'));
    await tester.ensureVisible(moveWarmupUp);
    await tester.tap(moveWarmupUp);
    final Finder cardio = find.byKey(const Key('program_draft_cardio_0'));
    await _pumpUntilFound(tester, cardio);
    await tester.ensureVisible(cardio);
    await tester.enterText(cardio, 'Cycle for 10 minutes');
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final Map<String, dynamic> day =
        (fake.programDraft!['days'] as List<dynamic>).single
            as Map<String, dynamic>;
    final List<dynamic> movements = day['warmup_exercises'] as List<dynamic>;
    expect(
      movements.map((dynamic movement) => (movement as Map)['exercise_name']),
      <String>['Cat-Cow', 'Band Pull Apart'],
    );
    final Map<String, dynamic> bandMovement =
        movements[1] as Map<String, dynamic>;
    expect(bandMovement['sets'], 2);
    expect(bandMovement['reps'], 10);
    expect(bandMovement['rest_seconds'], 45);
    expect(bandMovement['notes'], 'Easy pace');
    expect(day['cardio'], 'Cycle for 10 minutes');

    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('write_program_action')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_name_0_0')),
    );
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('program_draft_warmup_name_0_0')))
          .controller!
          .text,
      'Cat-Cow',
    );
    expect(
      tester.widget<TextField>(find.byKey(const Key('program_draft_cardio_0')))
          .controller!
          .text,
      'Cycle for 10 minutes',
    );
  });

  testWidgets('coach reorders and duplicates exercises within a training day',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programDraft = <String, dynamic>{
      'program_name': 'Custom program',
      'split_type': 'custom',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': 'Upper A',
          'day_order': 1,
          'warmup_exercises': <dynamic>[],
          'exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_id': 'bench_press',
              'exercise_name': 'Bench Press',
              'target_sets': 3,
              'target_reps_min': 6,
              'target_reps_max': 8,
              'target_rir': 2,
            },
            <String, dynamic>{
              'exercise_id': 'barbell_row',
              'exercise_name': 'Barbell Row',
              'target_sets': 3,
              'target_reps_min': 8,
              'target_reps_max': 10,
              'target_rir': 2,
            },
          ],
          'cardio': null,
        },
      ],
    };
    await _openProgramEditor(tester, fake);

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_duplicate_0_0')),
    );
    final Finder moveDuplicateDown =
        find.byKey(const Key('program_draft_exercise_down_0_1'));
    await _pumpUntilFound(tester, moveDuplicateDown);
    await tester.ensureVisible(moveDuplicateDown);
    await tester.tap(moveDuplicateDown);
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final List<dynamic> exercises =
        ((fake.programDraft!['days'] as List<dynamic>).single
                as Map<String, dynamic>)['exercises']
            as List<dynamic>;
    expect(
      exercises.map((dynamic exercise) => (exercise as Map)['exercise_id']),
      <String>['bench_press', 'barbell_row', 'bench_press'],
    );
  });

  testWidgets('coach editor localizes prescription fields and follows Arabic RTL',
      (tester) async {
    final FakeMayosApi fake = _coachFake()..displayLanguage = 'ar';
    fake.programDraft = <String, dynamic>{
      'program_name': 'برنامج تدريبي',
      'split_type': 'custom',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': 'Upper A',
          'day_order': 1,
          'warmup_exercises': <dynamic>[],
          'exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_id': 'bench_press',
              'exercise_name': 'Bench Press',
              'target_sets': 2,
              'target_reps_min': 8,
              'target_reps_max': 10,
              'target_rir': 2,
            },
          ],
          'cardio': null,
        },
      ],
    };
    await _openProgramEditor(tester, fake);

    expect(find.text('مجموعات العمل'), findsOneWidget);
    expect(find.text('التكرارات أو النطاق'), findsOneWidget);
    expect(find.text('RIR المستهدف'), findsOneWidget);
    expect(find.text('ملاحظة اللياقة (اختيارية)'), findsOneWidget);
    expect(
      Directionality.of(
        tester.element(find.byKey(const Key('program_draft_day_name_0'))),
      ),
      TextDirection.rtl,
    );
  });

  testWidgets('coach editor lays out at phone and desktop widths',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    fake.programDraft = <String, dynamic>{
      'program_name': 'Custom program',
      'split_type': 'custom',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': 'Upper A',
          'day_order': 1,
          'warmup_exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_name': 'Band Pull Apart',
              'sets': 2,
              'reps': 10,
              'rest_seconds': 45,
              'notes': 'Easy pace',
            },
          ],
          'exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_id': 'bench_press',
              'exercise_name': 'Bench Press',
              'target_sets': 3,
              'target_reps_min': 6,
              'target_reps_max': 8,
              'target_rir': 2,
              'warmup_sets': 2,
              'rest_seconds': 150,
              'tempo': '3-1-1',
              'notes': 'Pause on the chest',
            },
          ],
          'cardio': 'Cycle for 10 minutes',
        },
      ],
    };
    await _openProgramEditor(tester, fake);

    tester.view.physicalSize = const Size(720, 1600);
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.takeException(), isNull);

    tester.view.physicalSize = const Size(2560, 1800);
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.takeException(), isNull);
  });

  testWidgets('coach sees validation beside the offending training day',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraftPublishError = <String, dynamic>{
        'errors': <Map<String, dynamic>>[
          <String, dynamic>{
            'code': 'invalid_day_order',
            'location': <String, dynamic>{
              'day_index': 1,
              'exercise_index': null,
              'field': 'day_order',
            },
          },
        ],
      };
    await _openProgramEditor(tester, fake);
    await tester.tap(find.byKey(const Key('program_draft_add_day')));
    await tester.tap(find.byKey(const Key('program_draft_publish')));
    await _pumpUntilFound(
      tester,
      find.text('Publish this Training program now? It will become the active program.'),
    );
    await tester.tap(find.text('Publish').last);

    await _pumpUntilFound(
      tester,
      find.text('A program must have 1 to 5 training days.'),
    );
    expect(
      find.text('A program must have 1 to 5 training days.'),
      findsOneWidget,
    );
  });

  testWidgets('coach generates a draft, edits it, then publishes it',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);

    // The coach shell opens on the Roster tab (#119).
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));

    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('generate_draft_action')));
    await _pumpUntilFound(tester, find.text('Rep range preference'));

    expect(find.text('Days per week'), findsOneWidget);
    expect(find.text('Split'), findsOneWidget);
    await tester.tap(find.byKey(const Key('generate_draft_confirm_button')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_save')));

    expect(fake.programVersion, isNull);
    expect(fake.programDraftGenerationRequests, 1);
    await tester.enterText(
      find.byKey(const Key('program_draft_day_name_0')),
      'Edited Full A',
    );
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));
    expect((fake.programDraft!['days'] as List<dynamic>).first['day_name'], 'Edited Full A');
    await tester.tap(find.byKey(const Key('program_draft_publish')));
    await _pumpUntilFound(
      tester,
      find.text('Publish this Training program now? It will become the active program.'),
    );
    await tester.tap(find.text('Publish').last);
    await _pumpUntilFound(tester, find.text('Published program version 1'));

    expect(find.text('Published program version 1'), findsOneWidget);
    expect(fake.programVersion, 1);
    expect(fake.programPublishedByCoachAccountId, 'account-alice');
    expect(fake.programDraft, isNull);
    expect(fake.programDaysOverride!.first['day_name'], 'Edited Full A');
  });

  testWidgets('generating over a draft asks before replacing it', (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
        'program_name': 'Existing plan',
        'split_type': 'Full Body',
        'weekly_frequency': 1,
        'instructions': '',
        'days': <Map<String, dynamic>>[
          <String, dynamic>{
            'day_name': 'Saved day',
            'day_order': 1,
            'warmup_exercises': <dynamic>[],
            'exercises': <dynamic>[],
            'cardio': null,
          },
        ],
      };
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('generate_draft_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('generate_draft_confirm_button')));
    await tester.tap(find.byKey(const Key('generate_draft_confirm_button')));
    await _pumpUntilFound(tester, find.text('Replace the current Program draft?'));
    expect(fake.programDraft!['program_name'], 'Existing plan');
    await tester.tap(find.byKey(const Key('generate_draft_replace_confirm')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_save')));

    final List<FakeRequest> generationRequests = fake.adapter.requests
        .where((FakeRequest request) => request.path.endsWith('/program-draft/generate'))
        .toList(growable: false);
    expect(generationRequests, hasLength(2));
    expect(generationRequests.first.query, isNot(containsPair('replace', true)));
    expect(generationRequests.last.query, containsPair('replace', true));
    expect(fake.programVersion, isNull);
  });

  testWidgets(
      'declining replacement keeps the existing draft and sends no second request',
      (tester) async {
    final Map<String, dynamic> existingDraft = <String, dynamic>{
      'program_name': 'Existing plan',
      'split_type': 'Full Body',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': 'Saved day',
          'day_order': 1,
          'warmup_exercises': <dynamic>[],
          'exercises': <dynamic>[],
          'cardio': null,
        },
      ],
    };
    final FakeMayosApi fake = _coachFake()..programDraft = existingDraft;
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('Volume (weighted working sets)'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('generate_draft_action')));
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('generate_draft_confirm_button')),
    );
    await tester.tap(find.byKey(const Key('generate_draft_confirm_button')));
    await _pumpUntilFound(tester, find.text('Replace the current Program draft?'));

    expect(fake.programDraft!['program_name'], 'Existing plan');
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();

    final List<FakeRequest> generationRequests = fake.adapter.requests
        .where((FakeRequest request) => request.path.endsWith('/program-draft/generate'))
        .toList(growable: false);
    expect(generationRequests, hasLength(1));
    expect(fake.programDraft!['program_name'], 'Existing plan');
    expect(fake.programDraft!['days'], existingDraft['days']);
    expect(find.byKey(const Key('program_draft_save')), findsNothing);
  });

  testWidgets('Generate draft labels are localized in Arabic', (tester) async {
    final FakeMayosApi fake = _coachFake()..displayLanguage = 'ar';
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
    await tester.tap(find.text('bob'));
    await _pumpUntilFound(tester, find.text('مجموعات محسوبة لكل عضلة'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await tester.tap(find.byKey(const Key('generate_draft_action')));
    await _pumpUntilFound(tester, find.text('تفضيل نطاق التكرارات'));

    expect(find.text('أيام التدريب أسبوعيًا'), findsOneWidget);
    expect(find.text('التقسيمة'), findsOneWidget);
    expect(find.text('إنشاء'), findsOneWidget);
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
      'program_change_summary': <String, dynamic>{
        'version': 1,
        'unchanged': false,
        'changes': <Map<String, dynamic>>[
          <String, dynamic>{
            'type': 'exercise_replaced',
            'day': 'Lower 1',
            'before': 'Back Squat',
            'after': 'Safety Bar Squat',
          },
        ],
      },
    });
    await _pumpApp(tester, fake);

    await _openSettings(tester);

    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(
        tester, find.text('Your coach published program version 1.'));

    expect(
        find.text('Your coach published program version 1.'), findsOneWidget);
    expect(
      find.textContaining('Back Squat → Safety Bar Squat on Lower 1'),
      findsOneWidget,
    );
    expect(find.text('View program'), findsOneWidget);
    expect(find.textContaining('program_published'), findsOneWidget);

    await tester.tap(find.text('Mark all read'));
    await _pumpUntilFound(tester, find.byIcon(Icons.notifications_none));
    expect(fake.playerNotices.first['read_at'], isNotNull);

    await tester.tap(find.text('View program'));
    await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));
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
