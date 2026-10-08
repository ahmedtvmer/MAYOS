import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/program_import_files.dart';
import 'package:mayos_mobile/src/features/coach/coach_exercise_table.dart';
import 'package:mayos_mobile/src/features/player/workout/logger_card_widgets.dart'
    show ExerciseCatalogThumbnail;
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_media_http.dart';
import 'support/fake_mayos_api.dart';

const List<String> _programActionKeys = <String>[
  'coach_program_approve_as_is',
  'coach_program_edit_active',
  'generate_draft_action',
  'write_program_action',
  'program_import_action',
  'program_template_download_action',
];

const List<String> _programActionLabels = <String>[
  'Approve as is',
  'Edit',
  'Generate draft',
  'Write program',
  'Import',
  'Download template',
];

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
  double logicalWidth = 540,
  List<Override> providerOverrides = const <Override>[],
}) async {
  tester.view.physicalSize = Size(logicalWidth * 2, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        ...providerOverrides,
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
        programSpreadsheetPickerProvider.overrideWithValue(() async =>
            PlatformFile(
              name: 'plan.csv',
              size: 4,
              bytes: Uint8List.fromList(<int>[100, 97, 121, 10]),
            )),
        programTemplateSaverProvider
            .overrideWithValue((Uint8List bytes, String name) async {
          fake.savedProgramTemplateNames.add(name);
          return name;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

Future<void> _expectProgramActionsAtWidth(
  WidgetTester tester,
  double logicalWidth,
) async {
  tester.view.physicalSize = Size(logicalWidth * 2, 2400);
  await tester.pump(const Duration(milliseconds: 100));

  final List<MapEntry<String, Rect>> actions = _programActionKeys
      .map(
        (String key) =>
            MapEntry<String, Rect>(key, tester.getRect(find.byKey(Key(key)))),
      )
      .toList();
  actions.sort((MapEntry<String, Rect> first, MapEntry<String, Rect> second) {
    final double verticalDelta = first.value.top - second.value.top;
    return verticalDelta.abs() > 1
        ? first.value.top.compareTo(second.value.top)
        : first.value.left.compareTo(second.value.left);
  });
  expect(
    actions.map((MapEntry<String, Rect> action) => action.key),
    orderedEquals(_programActionKeys),
  );

  for (int i = 0; i < _programActionKeys.length; i++) {
    final Finder action = find.byKey(Key(_programActionKeys[i]));
    final Rect actionRect = tester.getRect(action);
    final Finder label = find.descendant(
      of: action,
      matching: find.text(_programActionLabels[i]),
    );
    expect(label, findsOneWidget);
    expect(
      tester.renderObject<RenderParagraph>(label).didExceedMaxLines,
      isFalse,
    );
    expect(actionRect.left, greaterThanOrEqualTo(0));
    expect(actionRect.right, lessThanOrEqualTo(logicalWidth));
    expect(actionRect.height, greaterThanOrEqualTo(48));
  }
  expect(tester.takeException(), isNull);
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

Future<void> _selectCatalogExercise(
  WidgetTester tester,
  String name,
) async {
  await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
  await tester.enterText(find.byType(TextField).last, name);
  await tester.tap(find.byKey(const Key('coach_exercise_search')));
  await _pumpUntilFound(tester, find.text(name));
  await tester.tap(find.text(name).last);
}

Future<void> _expectDraftUnsaved(WidgetTester tester) async {
  await tester.tap(find.byTooltip('Back').hitTestable().last);
  await _pumpUntilFound(tester, find.text('Unsaved changes'));
  expect(find.byKey(const Key('program_draft_confirm_cancel')), findsOneWidget);
  await tester.tap(find.byKey(const Key('program_draft_confirm_cancel')));
  await tester.pumpAndSettle();
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

  testWidgets('coach picker sends the replaced exercise id only for Swap',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
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
            ],
            'cardio': null,
          },
        ],
      };
    await _openProgramEditor(tester, fake);

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_swap_0_0')),
    );
    await tester.tap(find.byKey(const Key('program_draft_exercise_swap_0_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.enterText(find.byType(TextField).last, 'Machine Row');
    await tester.tap(find.byKey(const Key('coach_exercise_search')));
    await _pumpUntilFound(
      tester,
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Machine Row'),
      ),
    );
    final swapRequest = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(swapRequest.query['replacing_exercise_id'], 'bench_press');
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Cancel'),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.enterText(find.byType(TextField).last, 'Bench Press');
    await tester.tap(find.byKey(const Key('coach_exercise_search')));
    await _pumpUntilFound(
      tester,
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Bench Press'),
      ),
    );
    final addRequest = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(addRequest.query.containsKey('replacing_exercise_id'), isFalse);
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Cancel'),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.enterText(find.byType(TextField).last, 'Machine Row');
    await tester.tap(find.byKey(const Key('coach_exercise_search')));
    await _pumpUntilFound(
      tester,
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Machine Row'),
      ),
    );
    final insertRequest = fake.adapter.requests.lastWhere(
      (request) => request.path == '/coach/exercises',
    );
    expect(insertRequest.query.containsKey('replacing_exercise_id'), isFalse);
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog).last,
        matching: find.text('Cancel'),
      ),
    );
    await tester.pumpAndSettle();
  });

  testWidgets('coach player page shows automatic program and pending draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(
        provenance: 'automatic',
        hasDraft: true,
      );
    await _pumpApp(tester, fake, logicalWidth: 1440);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Generated automatically'));

    expect(find.text('Draft pending'), findsOneWidget);
    expect(find.byKey(const Key('coach_program_edit_active')), findsOneWidget);
    expect(find.text('v7'), findsOneWidget);
    expect(find.text('Active'), findsOneWidget);
    expect(find.text('Active since 2026-10-04'), findsOneWidget);
    expect(find.text('Squat'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('coach_program_stat_working_sets')),
        matching: find.text('4'),
      ),
      findsOneWidget,
    );
    expect(find.text('6 – 8'), findsOneWidget);
    expect(find.text('≥ 2'), findsOneWidget);
    expect(find.text('rest 150s'), findsOneWidget);
    expect(find.text('Equipment'), findsOneWidget);
    expect(find.text('Sets'), findsOneWidget);
    expect(find.text('Reps'), findsOneWidget);
    expect(find.text('RIR'), findsOneWidget);
    expect(find.text('Rest'), findsOneWidget);
    expect(find.text('Tempo: 3-1-1 · Notes: Brace before each rep.'), findsOneWidget);

    await tester.tap(find.text('History').first);
    await _pumpUntilFound(tester, find.text('Since 2026-09-24T10:00:00Z'));
    expect(find.byKey(const Key('coach_program_edit_active')), findsNothing);
    expect(find.text('v7'), findsNothing);
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
    expect(find.text('Draft pending'), findsNothing);
  });

  testWidgets('program header counts rows and day tabs switch exercises',
      (tester) async {
    final Map<String, dynamic> active =
        _coachActiveProgram(provenance: 'coach', hasDraft: true);
    final Map<String, dynamic> program =
        active['program'] as Map<String, dynamic>;
    final List<Map<String, dynamic>> days =
        program['days'] as List<Map<String, dynamic>>;
    (days.first['exercises'] as List<Map<String, dynamic>>).first
      ..['warmup_sets'] = 1
      ..['image_path'] = null;
    days.add(<String, dynamic>{
      'day_name': 'Lower B',
      'day_order': 2,
      'exercises': <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': 'deadlift',
          'exercise_name': 'Deadlift',
          'target_sets': 3,
          'target_reps_min': 5,
          'target_reps_max': 7,
          'target_rpe': 9,
          'equipment': 'Barbell',
        },
      ],
    });
    final FakeMayosApi fake = _coachFake()..coachActiveProgram = active;
    await _pumpApp(tester, fake, logicalWidth: 1440);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Full A'));

    expect(
      find.descendant(
        of: find.byKey(const Key('coach_program_stat_training_days')),
        matching: find.text('2'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('coach_program_stat_total_exercises')),
        matching: find.text('2'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('coach_program_stat_working_sets')),
        matching: find.text('7'),
      ),
      findsOneWidget,
    );
    expect(find.text('Training days'), findsOneWidget);
    expect(find.text('Total exercises'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.byKey(const Key('coach_program_pending_draft')), findsOneWidget);
    expect(find.text('4 (+1 warm-up)'), findsOneWidget);
    expect(find.bySemanticsLabel('No picture'), findsOneWidget);
    expect(find.text('Equipment'), findsOneWidget);
    expect(find.text('#'), findsOneWidget);
    expect(find.text('Exercise'), findsOneWidget);
    expect(find.text('Sets'), findsOneWidget);
    expect(find.text('Reps'), findsOneWidget);
    expect(find.text('RIR'), findsOneWidget);
    expect(find.text('Rest'), findsOneWidget);
    expect(find.text('1 exercise • 4 working sets'), findsOneWidget);
    expect(
      find.byKey(const Key('coach_program_show_remaining')),
      findsNothing,
    );
    expect(find.text('Deadlift'), findsNothing);

    await tester.tap(find.text('Lower B').first);
    await tester.pumpAndSettle();
    expect(find.text('Deadlift'), findsOneWidget);
    expect(find.text('Barbell'), findsOneWidget);
    expect(find.text('rest 120s'), findsOneWidget);
    expect(find.text('Full A'), findsOneWidget);
  });

  testWidgets('long program day expands the remaining exercise rows',
      (tester) async {
    final Map<String, dynamic> active =
        _coachActiveProgram(provenance: 'automatic');
    final List<Map<String, dynamic>> exercises =
        (active['program'] as Map<String, dynamic>)['days']![0]['exercises']
            as List<Map<String, dynamic>>;
    for (int index = 1; index < 10; index++) {
      exercises.add(<String, dynamic>{
        'exercise_id': 'exercise-$index',
        'exercise_name': 'Exercise $index',
        'target_sets': 1,
        'target_reps_min': 8,
        'target_reps_max': 8,
        'target_rpe': 9,
      });
    }
    ((active['program'] as Map<String, dynamic>)['days']
            as List<Map<String, dynamic>>)
        .add(<String, dynamic>{
      'day_name': 'Short Day',
      'day_order': 2,
      'exercises': <Map<String, dynamic>>[],
    });
    final FakeMayosApi fake = _coachFake()..coachActiveProgram = active;
    await _pumpApp(tester, fake, logicalWidth: 1440);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Show remaining 2 exercises'));

    expect(find.text('Exercise 8'), findsNothing);
    await tester.tap(find.text('Show remaining 2 exercises'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('coach_program_show_remaining')), findsNothing);
    expect(find.text('Squat'), findsOneWidget);
    for (int index = 1; index < 10; index++) {
      expect(find.text('Exercise $index'), findsOneWidget);
    }
    expect(find.text('Exercise 8'), findsOneWidget);
    expect(find.text('Exercise 9'), findsOneWidget);
    await tester.tap(find.text('Short Day').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('coach_program_show_remaining')), findsNothing);
    await tester.tap(find.text('Full A').first);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('coach_program_show_remaining')),
      findsOneWidget,
    );
    expect(find.text('Exercise 8'), findsNothing);
  });

  testWidgets('program compact rows fit a 360dp phone', (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake, logicalWidth: 360);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Squat'));

    expect(find.text('4 × 6 – 8 · RIR ≥ 2 · rest 150s · —'), findsOneWidget);
    expect(find.text('Equipment'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed program picture keeps the catalog thumbnail layout',
      (tester) async {
    final FakeMediaCatalog media = FakeMediaCatalog()..install();
    try {
    final Map<String, dynamic> active =
        _coachActiveProgram(provenance: 'automatic');
    final List<Map<String, dynamic>> exercises =
        (active['program'] as Map<String, dynamic>)['days']![0]['exercises']
            as List<Map<String, dynamic>>;
    exercises.first['image_path'] = 'images/program_failed.jpg';
    exercises.add(<String, dynamic>{
      'exercise_id': 'missing-image',
      'exercise_name': 'Press',
      'target_sets': 4,
      'target_reps_min': 6,
      'target_reps_max': 8,
      'target_rpe': 8.0,
      'tempo': '3-1-1',
      'notes': 'Brace before each rep.',
    });
    final FakeMayosApi fake = _coachFake()..coachActiveProgram = active;
    await _pumpApp(
      tester,
      fake,
      logicalWidth: 1440,
      providerOverrides: <Override>[
        offlineWorkoutDraftsEnabledProvider.overrideWithValue(false),
      ],
    );
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Squat'));
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 150)),
    );
    await tester.pump(const Duration(milliseconds: 100));

    final Finder thumbnails = find.byType(ExerciseCatalogThumbnail);
    final Finder rows = find.byType(CoachExerciseTableRow);
    expect(media.requestCount('images/program_failed.jpg'), 1);
    expect(
      find.byWidgetPredicate(
        (Widget widget) =>
            widget is Icon && widget.semanticLabel == 'Picture unavailable',
      ),
      findsOneWidget,
    );
    expect(tester.getSize(thumbnails.first), const Size(48, 48));
    expect(tester.getSize(thumbnails.last), const Size(48, 48));
    expect(tester.getSize(rows.first).height, tester.getSize(rows.last).height);
    expect(tester.takeException(), isNull);
    } finally {
      FakeMediaCatalog.uninstall();
    }
  });

  testWidgets('program header and day tabs mirror in Arabic',
      (tester) async {
    final Map<String, dynamic> active =
        _coachActiveProgram(provenance: 'automatic');
    (active['program'] as Map<String, dynamic>)['days'].add(<String, dynamic>{
      'day_name': 'Lower B',
      'day_order': 2,
      'exercises': <Map<String, dynamic>>[],
    });
    final FakeMayosApi fake = _coachFake()
      ..displayLanguage = 'ar'
      ..coachActiveProgram = active;
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await _pumpUntilFound(tester, find.text('أيام التدريب'));

    expect(find.text('نشط'), findsOneWidget);
    expect(find.text('إجمالي التمارين'), findsOneWidget);
    expect(find.text('مجموعات العمل'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text('Squat'))),
      TextDirection.rtl,
    );
    expect(
      tester.getRect(find.text('Full A').first).center.dx,
      greaterThan(tester.getRect(find.text('Lower B').first).center.dx),
    );
    expect(
      tester.getRect(find.byIcon(Icons.fitness_center).first).center.dx,
      greaterThan(tester.getRect(find.text('Squat')).center.dx),
    );
  });

  testWidgets('program summary and table render with dark theme',
      (tester) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake, logicalWidth: 1440);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Training days'));

    expect(
      Theme.of(tester.element(find.text('Training days'))).brightness,
      Brightness.dark,
    );
    expect(find.text('Squat'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('coach player page shows an empty program state', (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('No active program.'));

    expect(find.text('No active program.'), findsOneWidget);
    expect(find.byKey(const Key('coach_program_edit_active')), findsNothing);
    expect(find.byKey(const Key('coach_program_approve_as_is')), findsNothing);
    expect(find.byKey(const Key('write_program_action')), findsOneWidget);
    expect(find.byKey(const Key('generate_draft_action')), findsOneWidget);
    expect(find.byKey(const Key('program_import_action')), findsOneWidget);
    expect(find.byKey(const Key('program_template_download_action')), findsOneWidget);
    expect(
      tester.widget<MayosButton>(
        find.byKey(const Key('generate_draft_action')),
      ).variant,
      MayosButtonVariant.primary,
    );
  });

  testWidgets('Program actions wrap naturally at desktop widths',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake, logicalWidth: 1440);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Program actions'));
    expect(find.text("Manage this Player's Training program"), findsOneWidget);
    expect(find.text('Import'), findsOneWidget);
    expect(find.text('Download template'), findsOneWidget);

    await _expectProgramActionsAtWidth(tester, 1440);
    await _expectProgramActionsAtWidth(tester, 1024);
  });

  testWidgets('Program actions wrap on a 360dp phone without shrinking targets',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake, logicalWidth: 360);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Program actions'));

    final List<Rect> rects = _programActionKeys
        .map((String key) => tester.getRect(find.byKey(Key(key))))
        .toList(growable: false);
    expect((rects[0].center.dy - rects[1].center.dy).abs(), lessThan(1));
    expect(rects.skip(2).every((Rect rect) => rect.center.dy > rects[0].center.dy), isTrue);
    expect((rects[2].center.dy - rects[3].center.dy).abs(), lessThan(1));
    expect((rects[4].center.dy - rects[5].center.dy).abs(), lessThan(1));
    expect(rects.every((Rect rect) => rect.height >= 48), isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Approve is disabled without an active program version',
      (tester) async {
    final Map<String, dynamic> active =
        _coachActiveProgram(provenance: 'automatic');
    (active['program'] as Map<String, dynamic>)['version'] = null;
    final FakeMayosApi fake = _coachFake()..coachActiveProgram = active;
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_as_is')));

    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    expect(find.byKey(const Key('coach_program_approve_confirm')), findsNothing);
    expect(fake.programApproveRequests, 0);

    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));
    expect(fake.programDraftCopyRequests, 1);
  });

  testWidgets('Edit and Approve are locked while the active program is copied',
      (tester) async {
    final Completer<void> copyResponse = Completer<void>();
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path.endsWith('/program-draft/copy-active')) {
        await copyResponse.future;
      }
    };
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('coach_program_edit_active')));

    final Finder editSpinner = find.descendant(
      of: find.byKey(const Key('coach_program_edit_active')),
      matching: find.byType(CircularProgressIndicator),
    );
    await _pumpUntilFound(tester, editSpinner);
    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    expect(
      fake.adapter.requests.where(
        (FakeRequest request) =>
            request.path.endsWith('/program-draft/copy-active'),
      ),
      hasLength(1),
    );
    expect(
      fake.adapter.requests.where(
        (FakeRequest request) => request.path.endsWith('/program/approve'),
      ),
      isEmpty,
    );

    copyResponse.complete();
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));
  });

  testWidgets('Approve and Edit are locked while approval is in progress',
      (tester) async {
    final Completer<void> approveResponse = Completer<void>();
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path.endsWith('/program/approve')) {
        await approveResponse.future;
      }
    };
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_program_approve_confirm')));
    await tester.tap(find.byKey(const Key('coach_program_approve_confirm')));

    final Finder approveSpinner = find.descendant(
      of: find.byKey(const Key('coach_program_approve_as_is')),
      matching: find.byType(CircularProgressIndicator),
    );
    await _pumpUntilFound(tester, approveSpinner);
    await tester.tap(find.byKey(const Key('coach_program_edit_active')));
    await tester.tap(find.byKey(const Key('coach_program_approve_as_is')));
    expect(
      fake.adapter.requests.where(
        (FakeRequest request) => request.path.endsWith('/program-draft/copy-active'),
      ),
      isEmpty,
    );
    expect(
      fake.adapter.requests.where(
        (FakeRequest request) => request.path.endsWith('/program/approve'),
      ),
      hasLength(1),
    );

    approveResponse.complete();
    await _pumpUntilFound(tester, find.text('Published program version 8'));
  });

  testWidgets('Program actions are localized and mirror in Arabic',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..displayLanguage = 'ar'
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await _pumpUntilFound(tester, find.text('إجراءات البرنامج'));

    expect(find.text('إدارة البرنامج التدريبي لهذا اللاعب'), findsOneWidget);
    expect(find.text('استيراد'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.text('إجراءات البرنامج'))),
      TextDirection.rtl,
    );
    final Rect approveRect = tester.getRect(
      find.byKey(const Key('coach_program_approve_as_is')),
    );
    final Rect editRect = tester.getRect(
      find.byKey(const Key('coach_program_edit_active')),
    );
    expect(approveRect.center.dx, greaterThan(editRect.center.dx));
    expect(tester.takeException(), isNull);
  });

  testWidgets('Program actions render with the dark theme', (tester) async {
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    final FakeMayosApi fake = _coachFake()
      ..coachActiveProgram = _coachActiveProgram(provenance: 'automatic');
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.ensureVisible(find.text('bob'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await _pumpUntilFound(tester, find.text('Program actions'));

    expect(
      Theme.of(tester.element(find.text('Program actions'))).brightness,
      Brightness.dark,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('spreadsheet import reviews rows and opens the Program editor',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    await _pumpUntilFound(tester, find.text('Rows: 1 · valid: 1'));

    expect(find.textContaining('Push · 3 sets · 6-8 reps · RIR 2.0'), findsOneWidget);
    await tester.tap(find.byKey(const Key('program_import_create_draft')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));

    expect(fake.programImportRequests, 1);
    expect(fake.programImportDraftRequests, hasLength(1));
    expect(fake.programDraft!['program_name'], 'plan');
  });

  testWidgets('spreadsheet import asks for a workbook tab before review',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programImportRequiresTabChoice = true;
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_tab_picker')));

    await tester.tap(find.byKey(const Key('program_import_tab_picker')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Notes').last);
    await tester.pumpAndSettle();
    final Finder readSheet = find.byKey(const Key('program_import_read_sheet'));
    await tester.ensureVisible(readSheet);
    await tester.tap(readSheet);
    await _pumpUntilFound(tester, find.text('Rows: 1 · valid: 1'));
    expect(fake.programImportRequests, 2);
  });

  for (final bool arabic in <bool>[false, true]) {
    testWidgets(
        'spreadsheet weeks switch locally after layout confirmation in ${arabic ? 'Arabic' : 'English'}',
        (tester) async {
      final FakeMayosApi fake = _coachFake();
      fake.displayLanguage = arabic ? 'ar' : 'en';
      final Map<String, dynamic> weekOne = Map<String, dynamic>.from(
        (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single,
      )..['week'] = 'Week 1';
      final Map<String, dynamic> weekTwo = Map<String, dynamic>.from(weekOne)
        ..['source_row'] = 3
        ..['week'] = 'Week 2'
        ..['exercise_name'] = 'Squat'
        ..['exercise_id'] = 'squat'
        ..['day_name'] = 'Pull';
      fake.programImportResult['rows'] = <Map<String, dynamic>>[
        weekOne,
        weekTwo,
      ];
      fake.programImportResult.addAll(<String, dynamic>{
        'freeform_available': false,
        'detected_weeks': <String>['Week 1', 'Week 2'],
        'selected_week': 'Week 1',
        'weeks_not_imported': <String>['Week 2'],
        'confirm_layout': true,
        'layout_days': <Map<String, dynamic>>[
          <String, dynamic>{'day': 1, 'name': 'Push'},
          <String, dynamic>{'day': 2, 'name': 'Pull'},
        ],
      });
      await _pumpApp(tester, fake);
      await _pumpUntilFound(
          tester, find.text(arabic ? 'علاقات التدريب النشطة' : 'Active assignments'));
      await tester.tap(find.text('bob'));
      await _openProgramSegment(tester,
          label: arabic ? 'البرنامج التدريبي' : 'Program');
      await tester.tap(find.byKey(const Key('program_import_action')));
      await _pumpUntilFound(
          tester, find.byKey(const Key('program_import_pick_file')));
      await tester.tap(find.byKey(const Key('program_import_pick_file')));
      await _pumpUntilFound(
          tester, find.byKey(const Key('program_import_layout_confirmation')));

      expect(find.byKey(const Key('program_import_row_2')), findsNothing);
      expect(find.textContaining(arabic ? 'الأيام المكتشفة' : 'Days found'), findsOneWidget);
      expect(find.textContaining(arabic ? 'توزيع الصفوف' : 'Week 1: rows 2'), findsOneWidget);
      expect(find.text(arabic ? 'تأكيد ومتابعة' : 'Confirm and continue'), findsOneWidget);
      expect(find.text(arabic
          ? 'الاستيراد بالتنسيق الحر غير متاح الآن. استخدم قالب MAYOS.'
          : 'Free-form import is unavailable right now. Use the MAYOS template.'), findsNothing);
      await tester.tap(find.byKey(const Key('program_import_layout_confirm')));
      await _pumpUntilFound(tester, find.byKey(const Key('program_import_week_picker')));
      expect(find.text('Week 1'), findsWidgets);
      expect(find.textContaining('Week 2'), findsWidgets);
      expect(find.byKey(const Key('program_import_row_2')), findsOneWidget);
      expect(find.byKey(const Key('program_import_row_3')), findsNothing);

      final Finder weekPicker = find.byKey(const Key('program_import_week_picker'));
      await tester.ensureVisible(weekPicker);
      await tester.tap(weekPicker);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Week 2').last);
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('program_import_row_2')), findsNothing);
      expect(find.byKey(const Key('program_import_row_3')), findsOneWidget);
      expect(find.textContaining('Week 1'), findsWidgets);

      final Finder createDraft =
          find.byKey(const Key('program_import_create_draft'));
      await tester.ensureVisible(createDraft);
      await tester.tap(createDraft);
      await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));
      final List<dynamic> createdRows =
          fake.programImportDraftRequests.single['rows'] as List<dynamic>;
      expect(createdRows, hasLength(1));
      expect((createdRows.single as Map<String, dynamic>)['exercise_name'], 'Squat');
    });
  }

  for (final bool arabic in <bool>[false, true]) {
    testWidgets('uncertain layout can be rejected in ${arabic ? 'Arabic' : 'English'}',
        (tester) async {
      final FakeMayosApi fake = _coachFake()..displayLanguage = arabic ? 'ar' : 'en';
      fake.programImportResult['confirm_layout'] = true;
      fake.programImportResult['layout_days'] = <Map<String, dynamic>>[
        <String, dynamic>{'day': 1, 'name': 'Push'},
      ];
      await _pumpApp(tester, fake);
      await _pumpUntilFound(
          tester, find.text(arabic ? 'علاقات التدريب النشطة' : 'Active assignments'));
      await tester.tap(find.text('bob'));
      await _openProgramSegment(tester,
          label: arabic ? 'البرنامج التدريبي' : 'Program');
      await tester.tap(find.byKey(const Key('program_import_action')));
      await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
      await tester.tap(find.byKey(const Key('program_import_pick_file')));
      await _pumpUntilFound(tester, find.byKey(const Key('program_import_layout_not_right')));
      await tester.tap(find.byKey(const Key('program_import_layout_not_right')));
      await tester.pumpAndSettle();

      expect(find.text(arabic
          ? 'ألغِ هذا الاستيراد وعدّل الورقة أو اختر ورقة عمل أخرى.'
          : 'Import cancelled. Adjust the sheet or choose another tab before trying again.'), findsOneWidget);
      expect(find.byKey(const Key('program_import_create_draft')), findsNothing);
    });
  }

  testWidgets('spreadsheet row errors use Arabic display copy', (tester) async {
    final FakeMayosApi fake = _coachFake()..displayLanguage = 'ar';
    final Map<String, dynamic> original =
        (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single;
    fake.programImportResult['rows'] = <Map<String, dynamic>>[
      <String, dynamic>{
        ...original,
        'valid': false,
        'exercise_id': null,
        'errors': <Map<String, dynamic>>[
          <String, dynamic>{'source_row': 2, 'column': 'reps', 'code': 'program_import.invalid_reps.v1'},
        ],
      },
    ];
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    await _pumpUntilFound(tester, find.textContaining('الصف 2'));

    expect(find.textContaining('التكرارات'), findsOneWidget);
    expect(find.text('لا توجد صفوف صالحة للاستيراد بعد.'), findsOneWidget);
  });

  testWidgets('import result can create an unresolved Coach exercise',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    final Map<String, dynamic> row = Map<String, dynamic>.from(
      (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single,
    )
      ..['exercise_name'] = 'Floor press'
      ..['exercise_id'] = null
      ..['resolution'] = 'unresolved'
      ..['suggestions'] = <dynamic>[]
      ..['warnings'] = <Map<String, dynamic>>[
        <String, dynamic>{
          'source_row': 2,
          'column': 'exercise',
          'code': 'program_import.exercise_unresolved.v1',
        },
      ];
    fake.programImportResult['rows'] = <Map<String, dynamic>>[row];
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    await _pumpUntilFound(tester,
        find.byKey(const Key('program_import_create_exercise_2')));
    await tester.tap(find.byKey(const Key('program_import_create_exercise_2')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_create_draft')));
    await tester.tap(find.byKey(const Key('program_import_create_draft')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));

    final Map<String, dynamic> sentRow =
        (fake.programImportDraftRequests.single['rows'] as List<dynamic>).single
            as Map<String, dynamic>;
    expect(sentRow['exercise_id'], startsWith('coach:'));
    expect(sentRow.containsKey('raw_cells'), isFalse);
  });

  testWidgets('import result lets the coach choose an ambiguous suggestion',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    final Map<String, dynamic> row = Map<String, dynamic>.from(
      (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single,
    )
      ..['exercise_name'] = 'Smith incline'
      ..['exercise_id'] = null
      ..['resolution'] = 'ambiguous'
      ..['suggestions'] = <Map<String, dynamic>>[
        <String, dynamic>{'exercise_id': 'sq', 'name': 'Squat match'},
        <String, dynamic>{'exercise_id': 'bp', 'name': 'Bench match'},
      ]
      ..['warnings'] = <Map<String, dynamic>>[
        <String, dynamic>{
          'source_row': 2,
          'column': 'exercise',
          'code': 'program_import.exercise_ambiguous.v1',
        },
      ];
    fake.programImportResult['rows'] = <Map<String, dynamic>>[row];
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    final Finder match = find.byKey(const Key('program_import_match_2'));
    await _pumpUntilFound(tester, match);
    await tester.tap(match);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Squat match').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('program_import_create_draft')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));

    final Map<String, dynamic> sentRow =
        (fake.programImportDraftRequests.single['rows'] as List<dynamic>).single
            as Map<String, dynamic>;
    expect(sentRow['exercise_id'], 'sq');
  });

  testWidgets('import replacement requires confirmation and creates the draft',
      (tester) async {
    final FakeMayosApi fake = _coachFake()..programImportDraftExists = true;
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_create_draft')));
    await tester.tap(find.byKey(const Key('program_import_create_draft')));
    await _pumpUntilFound(tester, find.text('Replace the current Program draft?'));
    expect(fake.programImportDraftRequests, isEmpty);
    await tester.tap(find.text('Replace draft'));
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_add_day')));

    expect(fake.programImportReplaceRequests, <bool>[true]);
  });

  testWidgets('import warnings use specific row and column copy', (tester) async {
    final FakeMayosApi fake = _coachFake();
    final Map<String, dynamic> row = Map<String, dynamic>.from(
      (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single,
    )
      ..['notes'] = 'load: 60'
      ..['warnings'] = <Map<String, dynamic>>[
        <String, dynamic>{
          'source_row': 2,
          'column': 'load_kg',
          'code': 'program_import.load_preserved_as_note.v1',
        },
      ];
    fake.programImportResult['rows'] = <Map<String, dynamic>>[row];
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    final Finder rowCard = find.byKey(const Key('program_import_row_2'));
    await _pumpUntilFound(tester, rowCard);
    await tester.ensureVisible(rowCard);

    expect(find.textContaining('Row 2 · load:'), findsOneWidget);
    expect(find.textContaining('Load is not supported yet; it was kept in the exercise notes.'), findsOneWidget);
  });

  testWidgets('Program template download uses the shared downloader',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('Active assignments'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester);
    final Finder download = find.byKey(const Key('program_template_download_action'));
    await tester.ensureVisible(download);
    await tester.tap(download);
    await _pumpUntilFound(tester, find.text('The Program template is ready to download.'));

    expect(fake.programTemplateDownloadRequests, 1);
    expect(fake.savedProgramTemplateNames, <String>['mayos-program-template.xlsx']);
  });

  testWidgets('Arabic import result localizes the warning and column label',
      (tester) async {
    final FakeMayosApi fake = _coachFake()..displayLanguage = 'ar';
    final Map<String, dynamic> row = Map<String, dynamic>.from(
      (fake.programImportResult['rows'] as List<Map<String, dynamic>>).single,
    )
      ..['warnings'] = <Map<String, dynamic>>[
        <String, dynamic>{
          'source_row': 2,
          'column': 'rpe',
          'code': 'program_import.rpe_converted.v1',
        },
      ];
    fake.programImportResult['rows'] = <Map<String, dynamic>>[row];
    await _pumpApp(tester, fake);
    await _pumpUntilFound(tester, find.text('علاقات التدريب النشطة'));
    await tester.tap(find.text('bob'));
    await _openProgramSegment(tester, label: 'البرنامج التدريبي');
    await tester.tap(find.byKey(const Key('program_import_action')));
    await _pumpUntilFound(tester, find.byKey(const Key('program_import_pick_file')));
    await tester.tap(find.byKey(const Key('program_import_pick_file')));
    final Finder rowCard = find.byKey(const Key('program_import_row_2'));
    await _pumpUntilFound(tester, rowCard);
    await tester.ensureVisible(rowCard);

    expect(find.textContaining('RPE:'), findsOneWidget);
    expect(find.textContaining('تم تحويل RPE إلى RIR؛ راجع الملاحظة.'), findsOneWidget);
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

    expect(find.byTooltip('Exercise actions'), findsNWidgets(2));
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_duplicate_0_0')),
    );
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

  testWidgets('coach swaps an exercise in place and keeps edited prescription',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
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
                'body_part': 'Chest',
                'equipment': 'barbell',
                'note': 'Old identity note',
                'video_url': 'https://example.com/old',
                'is_coach_exercise': true,
                'image_path': 'old/image.jpg',
                'target_sets': 3,
                'target_reps_min': 6,
                'target_reps_max': 8,
                'target_rir': 2,
                'warmup_sets': 2,
                'rest_seconds': 120,
                'tempo': '2-0-2',
                'notes': 'Old prescription note',
                'suggested_substitutes': <String>['cable_fly'],
              },
              <String, dynamic>{
                'exercise_id': 'cable_fly',
                'exercise_name': 'Cable Fly',
                'target_sets': 2,
                'target_reps_min': 10,
                'target_reps_max': 12,
                'target_rir': 2,
              },
            ],
            'cardio': null,
          },
        ],
      };
    await _openProgramEditor(tester, fake);

    await tester.enterText(
      find.byKey(const Key('program_draft_sets_0_0')),
      '5',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_reps_0_0')),
      '4-6',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_rir_0_0')),
      '1.5',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_warmup_sets_0_0')),
      '3',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_rest_0_0')),
      '90',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_tempo_0_0')),
      '3-1-1',
    );
    await tester.enterText(
      find.byKey(const Key('program_draft_notes_0_0')),
      'Keep the pause.',
    );
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_swap_0_0')),
    );
    await tester.tap(find.byKey(const Key('program_draft_exercise_swap_0_0')));
    await _selectCatalogExercise(tester, 'Machine Row');
    await _pumpUntilFound(tester, find.text('Machine Row'));
    expect(find.byKey(const Key('program_draft_sets_0_0')), findsOneWidget);
    await _expectDraftUnsaved(tester);

    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));
    final List<dynamic> exercises =
        ((fake.programDraft!['days'] as List<dynamic>).single
                as Map<String, dynamic>)['exercises']
            as List<dynamic>;
    final Map<String, dynamic> swapped =
        exercises.first as Map<String, dynamic>;
    expect(exercises, hasLength(2));
    expect(swapped['exercise_id'], 'machine_row');
    expect(swapped['exercise_name'], 'Machine Row');
    expect(swapped['body_part'], 'Back');
    expect(swapped['equipment'], 'leverage machine');
    expect(swapped['image_path'], 'images/machine_row.jpg');
    expect(swapped['video_url'], isNull);
    expect(swapped['is_coach_exercise'], isFalse);
    expect(swapped['note'], isNull);
    expect(swapped['target_sets'], 5);
    expect(swapped['target_reps_min'], 4);
    expect(swapped['target_reps_max'], 6);
    expect(swapped['target_rir'], 1.5);
    expect(swapped['warmup_sets'], 3);
    expect(swapped['rest_seconds'], 90);
    expect(swapped['tempo'], '3-1-1');
    expect(swapped['notes'], 'Keep the pause.');
    expect(swapped['suggested_substitutes'], isEmpty);
    expect((exercises[1] as Map<String, dynamic>)['exercise_id'], 'cable_fly');
  });

  testWidgets('canceling Swap exercise leaves the Program draft unchanged',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
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
            ],
            'cardio': null,
          },
        ],
      };
    await _openProgramEditor(tester, fake);

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_swap_0_0')),
    );
    await tester.tap(find.byKey(const Key('program_draft_exercise_swap_0_0')));
    await _pumpUntilFound(tester, find.byKey(const Key('coach_exercise_search')));
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();

    expect(find.text('Bench Press'), findsOneWidget);
    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('write_program_action')),
    );
    expect(find.text('Unsaved changes'), findsNothing);
    final Map<String, dynamic> originalExercise =
        (((fake.programDraft!['days'] as List<dynamic>).single
                    as Map<String, dynamic>)['exercises']
                as List<dynamic>)
            .single as Map<String, dynamic>;
    expect(originalExercise['exercise_id'], 'bench_press');
    expect(originalExercise['exercise_name'], 'Bench Press');
  });

  testWidgets('coach inserts exercises above and below and can cancel',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
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
                'target_sets': 4,
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
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('coach_exercise_search')),
    );
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('program_draft_exercise_menu_0_1')),
      findsNothing,
    );

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_insert_above_0_0')),
    );
    await _selectCatalogExercise(tester, 'Bicep Curl');
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_0')));
    final Finder originalMenu =
        find.byKey(const Key('program_draft_exercise_menu_0_1'));
    await tester.ensureVisible(originalMenu);
    await tester.tap(
      originalMenu,
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_insert_below_0_1')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_insert_below_0_1')),
    );
    await _selectCatalogExercise(tester, 'Cable Fly');
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_2')));
    await _expectDraftUnsaved(tester);
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final List<dynamic> exercises =
        ((fake.programDraft!['days'] as List<dynamic>).single
                as Map<String, dynamic>)['exercises']
            as List<dynamic>;
    expect(
      exercises.map((dynamic exercise) => (exercise as Map)['exercise_id']),
      <String>['bicep_curl', 'bench_press', 'cable_fly'],
    );
    expect(
      exercises.map((dynamic exercise) => (exercise as Map)['exercise_name']),
      <String>['Bicep Curl', 'Bench Press', 'Cable Fly'],
    );
    expect((exercises.first as Map)['target_sets'], 2);
    expect((exercises.first as Map)['target_reps_min'], 8);
    expect((exercises.first as Map)['target_reps_max'], 12);
    expect((exercises.first as Map)['target_rir'], 2);
    expect((exercises.first as Map)['warmup_sets'], 0);
    expect((exercises.first as Map)['rest_seconds'], 180);
    expect((exercises.first as Map)['suggested_substitutes'], isEmpty);
  });

  testWidgets('coach exercise menu duplicates and deletes exercises',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..programDraft = <String, dynamic>{
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
            ],
            'cardio': null,
          },
        ],
      };
    await _openProgramEditor(tester, fake);

    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_exercise_swap_0_0')),
    );
    expect(find.text('Swap exercise'), findsOneWidget);
    expect(find.text('Insert exercise above'), findsOneWidget);
    expect(find.text('Insert exercise below'), findsOneWidget);
    expect(find.text('Duplicate'), findsOneWidget);
    expect(find.text('Delete'), findsOneWidget);
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_duplicate_0_0')),
    );
    await _pumpUntilFound(tester, find.byKey(const Key('program_draft_exercise_menu_0_1')));
    await tester.tap(
      find.byKey(const Key('program_draft_exercise_menu_0_1')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_remove_0_1')),
    );
    await tester.tap(find.byKey(const Key('program_draft_remove_0_1')));
    await tester.pumpAndSettle();
    final Finder save = find.byKey(const Key('program_draft_save'));
    await tester.ensureVisible(save);
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Draft saved.'));

    final List<dynamic> exercises =
        ((fake.programDraft!['days'] as List<dynamic>).single
                as Map<String, dynamic>)['exercises']
            as List<dynamic>;
    expect(exercises, hasLength(1));
    expect((exercises.single as Map)['exercise_id'], 'bench_press');
  });

  testWidgets('warm-up menu inserts and removes empty movements in Arabic',
      (tester) async {
    final FakeMayosApi fake = _coachFake()
      ..displayLanguage = 'ar'
      ..programDraft = <String, dynamic>{
        'program_name': 'برنامج تدريبي',
        'split_type': 'custom',
        'weekly_frequency': 1,
        'instructions': '',
        'days': <Map<String, dynamic>>[
          <String, dynamic>{
            'day_name': 'Upper A',
            'day_order': 1,
            'warmup_exercises': <Map<String, dynamic>>[
              <String, dynamic>{
                'exercise_name': 'Cat-Cow',
                'sets': 2,
                'reps': 8,
                'rest_seconds': 30,
                'notes': null,
              },
            ],
            'exercises': <dynamic>[],
            'cardio': null,
          },
        ],
      };
    await _openProgramEditor(tester, fake);
    tester.view.physicalSize = const Size(720, 1600);
    await tester.pump(const Duration(milliseconds: 100));

    final Finder firstMovementMenu =
        find.byKey(const Key('program_draft_warmup_menu_0_0'));
    expect(find.byTooltip('إجراءات حركة الإحماء'), findsOneWidget);
    await tester.tap(firstMovementMenu);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_insert_below_0_0')),
    );
    expect(find.text('إضافة حركة إحماء قبل'), findsOneWidget);
    expect(find.text('إضافة حركة إحماء بعد'), findsOneWidget);
    await tester.tap(
      find.byKey(const Key('program_draft_warmup_insert_below_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_name_0_1')),
    );
    await tester.pumpAndSettle();
    await tester.tap(firstMovementMenu);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_insert_above_0_0')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_warmup_insert_above_0_0')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_name_0_2')),
    );
    expect(tester.takeException(), isNull);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<TextField>(
            find.byKey(const Key('program_draft_warmup_name_0_0')),
          )
          .controller!
          .text,
      '',
    );
    expect(
      tester
          .widget<TextField>(
            find.byKey(const Key('program_draft_warmup_name_0_1')),
          )
          .controller!
          .text,
      'Cat-Cow',
    );
    await tester.tap(firstMovementMenu);
    await _pumpUntilFound(
      tester,
      find.byKey(const Key('program_draft_warmup_remove_0_0')),
    );
    await tester.tap(
      find.byKey(const Key('program_draft_warmup_remove_0_0')),
    );
    await tester.pumpAndSettle();
    final Finder save = find.byKey(const Key('program_draft_save'));
    await tester.ensureVisible(save);
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('تم حفظ المسودة.'));

    final List<dynamic> warmups =
        ((fake.programDraft!['days'] as List<dynamic>).single
                as Map<String, dynamic>)['warmup_exercises']
            as List<dynamic>;
    expect(
      warmups.map((dynamic movement) => (movement as Map)['exercise_name']),
      <String>['Cat-Cow', ''],
    );
    expect((warmups.last as Map)['sets'], 2);
    expect((warmups.last as Map)['reps'], 10);
    expect((warmups.last as Map)['rest_seconds'], 45);
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
