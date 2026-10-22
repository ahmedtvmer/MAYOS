import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/core/api_client.dart';
import 'package:myos_mobile/src/core/display_language/controller.dart';
import 'package:myos_mobile/src/core/display_language/coach_copy.dart';
import 'package:myos_mobile/src/core/program_prescription.dart';
import 'package:myos_mobile/src/core/token_store.dart';
import 'package:myos_mobile/src/features/coach/coach_program_templates_screen.dart';
import 'package:myos_mobile/src/features/coach/coach_template_assignment_screen.dart';
import 'package:myos_mobile/src/providers.dart';

import 'support/fake_myos_api.dart';
import 'support/coach_layout_harness.dart';

/// Pumps finite frames until [finder] matches, then a few more so transitions
/// settle without relying on `pumpAndSettle` (indeterminate spinners never
/// settle).
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
  expect(finder, findsWidgets);
}

Future<void> _openTemplatesFromShell(
  WidgetTester tester,
  String language,
) async {
  final String profileLabel = language == 'ar' ? 'الملف الشخصي' : 'Profile';
  final String profileTitle =
      language == 'ar' ? 'الملف الشخصي للمدرب' : 'Coach profile';
  await _pumpUntilFound(tester, find.text(profileLabel));
  await tester.tap(find.text(profileLabel).hitTestable().last);
  await _pumpUntilFound(tester, find.text(profileTitle));
  final Finder openTemplates =
      find.byKey(const Key('coach_program_templates_open'));
  final Finder profileList = find.byType(ListView).last;
  for (int attempt = 0;
      attempt < 12 && openTemplates.hitTestable().evaluate().isEmpty;
      attempt++) {
    await tester.drag(profileList, const Offset(0, -450));
    await tester.pumpAndSettle();
  }
  expect(openTemplates, findsOneWidget);
  await tester.ensureVisible(openTemplates);
  await tester.tap(openTemplates.hitTestable());
}

Future<void> _assignTemplateFromPhoneList(
  WidgetTester tester,
  String language,
) async {
  await _openTemplatesFromShell(tester, language);
  final Finder assign =
      find.byKey(const Key('program_template_assign_tmpl:upper'));
  await _pumpUntilFound(tester, assign);
  await tester.ensureVisible(assign);
  await tester.tap(assign.hitTestable());
  await _pumpUntilFound(
      tester, find.byKey(const Key('template_assignment_screen')));
  final Finder player =
      find.byKey(const Key('template_assign_player_asg:phone'));
  await tester.ensureVisible(player);
  await tester.tap(player.hitTestable());
  await tester.pumpAndSettle();
  await tester.tap(find.text(CoachCopy(language).existingDraftReplace).last);
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('template_assign_submit')).hitTestable());
  await _pumpUntilFound(
    tester,
    find.text(CoachCopy(language).templateAssignSummary(1, 0, 0, 0)),
  );
  await tester.tap(find.byType(BackButton));
  await _pumpUntilFound(tester, find.byKey(const Key('program_templates_screen')));
}

Future<void> _pumpUntilGone(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpLibrary(
  WidgetTester tester,
  FakeMyosApi fake, {
  String language = 'en',
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
        systemDisplayLanguageProvider.overrideWithValue(language),
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
      child: const MaterialApp(home: CoachProgramTemplatesScreen()),
    ),
  );
  await _pumpUntilFound(tester, find.byKey(const Key('program_templates_new')));
}

Future<void> _pumpAssignment(
  WidgetTester tester,
  FakeMyosApi fake, {
  String templateId = 'tmpl:upper',
  String templateName = 'Upper Block',
  String language = 'en',
  bool narrow = false,
}) async {
  tester.view.physicalSize = narrow ? const Size(360, 800) : const Size(1080, 2400);
  tester.view.devicePixelRatio = narrow ? 1.0 : 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        systemDisplayLanguageProvider.overrideWithValue(language),
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
      child: MaterialApp(
        home: CoachTemplateAssignmentScreen(
          templateId: templateId,
          templateName: templateName,
        ),
      ),
    ),
  );
  await _pumpUntilFound(
      tester, find.byKey(const Key('template_assign_submit')));
}

FakeMyosApi _coachFake() {
  final FakeMyosApi fake = FakeMyosApi();
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
  return fake;
}

Map<String, dynamic> _templateProgram({String name = 'Upper Block'}) {
  final Map<String, dynamic> exercise = <String, dynamic>{
    'exercise_id': 'sq',
    'exercise_name': 'Squat',
    'target_sets': 3,
    'target_reps_min': 5,
    'target_reps_max': 8,
    'target_rir': 2.0,
    'rest_seconds': 180,
    'warmup_sets': 2,
    'tempo': null,
    'notes': null,
    'suggested_substitutes': <dynamic>[],
  };
  final Map<String, dynamic> day = <String, dynamic>{
    'day_name': 'Upper 1',
    'day_order': 1,
    'week_order': 1,
    'warmup_exercises': <dynamic>[],
    'exercises': <dynamic>[exercise],
    'cardio': null,
  };
  return <String, dynamic>{
    'program_name': name,
    'split_type': 'custom',
    'weekly_frequency': 1,
    'instructions': '',
    'days': <dynamic>[day],
    'weeks': <dynamic>[
      <String, dynamic>{
        'week_name': 'Week 1',
        'week_order': 1,
        'days': <dynamic>[day],
      },
    ],
  };
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
  await _pumpUntilFound(
      tester, find.byKey(const Key('program_draft_exercise_card_0_0')));
}

void _seedTemplate(
  FakeMyosApi fake, {
  required String id,
  required String name,
  String? description,
  String? archivedAt,
}) {
  fake.programTemplates.add(<String, dynamic>{
    'template_id': id,
    'name': name,
    'description': description,
    'program': _templateProgram(name: name),
    'archived_at': archivedAt,
    'created_at': '2026-10-05T09:00:00Z',
    'updated_at': '2026-10-05T09:00:00Z',
  });
}

void main() {
  testWidgets('phone template list starts a draft from the selected template',
      (tester) async {
    late FakeMyosApi phoneFake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMyosApi fake) {
        phoneFake = fake;
        _seedTemplate(fake,
            id: 'tmpl:upper',
            name: fake.displayLanguage == 'ar' ? 'الكتلة العلوية' : 'Upper Block',
            description: 'Reusable split');
        fake.assignments.add(<String, dynamic>{
          'assignment_id': 'asg:phone',
          'player_username': 'bob',
          'started_at': '2026-10-01T00:00:00Z',
          'status': 'active',
        });
      },
      prepare: _assignTemplateFromPhoneList,
      ready: (String language) =>
          find.byKey(const Key('program_templates_screen')),
      pageScrollable: (String language) => find.descendant(
        of: find.byKey(const Key('program_templates_screen')),
        matching: find.byType(Scrollable),
      ).first,
      assertions: (WidgetTester tester, String language) async {
        final String templateName =
            language == 'ar' ? 'الكتلة العلوية' : 'Upper Block';
        expect(find.text(templateName), findsOneWidget);
        expect(phoneFake.programTemplateAssignRequests, 1);
        expect(
          phoneFake.templateAssignedDrafts['asg:phone']?['program_name'],
          templateName,
        );
        expect(tester.takeException(), isNull);
      },
    );
  });

  testWidgets('desktop template list starts a draft from the selected template',
      (tester) async {
    const String language = 'en';
    final FakeMyosApi fake = _coachFake();
    const String templateName = 'Upper Block';
    _seedTemplate(fake,
        id: 'tmpl:upper', name: templateName, description: 'Reusable split');
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'asg:desktop',
      'player_username': 'bob',
      'started_at': '2026-10-01T00:00:00Z',
      'status': 'active',
    });
    await pumpCoachApp(
      tester,
      fake,
      logicalSize: const Size(1440, 960),
      language: language,
    );
    await _openTemplatesFromShell(tester, language);
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_templates_screen')));
    final Finder assign =
        find.byKey(const Key('program_template_assign_tmpl:upper'));
    expect(find.text(templateName), findsOneWidget);
    await _pumpUntilFound(tester, assign);
    await tester.ensureVisible(assign);
    await tester.tap(assign.hitTestable());
    await _pumpUntilFound(
        tester, find.byKey(const Key('template_assignment_screen')));
    await tester.tap(
        find.byKey(const Key('template_assign_player_asg:desktop')));
    await tester.pumpAndSettle();
    await tester.tap(find.text(CoachCopy(language).existingDraftReplace).last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('template_assign_submit')));
    for (int attempt = 0;
        attempt < 40 && fake.programTemplateAssignRequests == 0;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(fake.programTemplateAssignRequests, 1);
    expect(fake.lastProgramTemplateAssignTargets, <Map<String, dynamic>>[
      <String, dynamic>{
        'assignment_id': 'asg:desktop',
        'existing_draft': 'replace',
      },
    ]);
    final Map<String, dynamic> createdDraft =
        fake.templateAssignedDrafts['asg:desktop']!;
    expect(createdDraft['program_name'], templateName);
    final List<dynamic> days = createdDraft['days'] as List<dynamic>;
    expect(days, hasLength(1));
    final Map<String, dynamic> day =
        Map<String, dynamic>.from(days.single as Map);
    expect(day['day_name'], 'Upper 1');
    final List<dynamic> exercises = day['exercises'] as List<dynamic>;
    expect(exercises, hasLength(1));
    expect((exercises.single as Map)['exercise_id'], 'sq');
    expect(tester.takeException(), isNull);
  });

  testWidgets('library lists templates and opens the editor in template mode',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake,
        id: 'tmpl:upper', name: 'Upper Block', description: 'Reusable split');

    await _pumpLibrary(tester, fake);

    expect(fake.programTemplateListRequests, 1);
    expect(find.text('Upper Block'), findsOneWidget);
    expect(find.text('Reusable split'), findsOneWidget);

    await tester.tap(find.byKey(const Key('program_template_edit_tmpl:upper')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_name')));

    expect(find.byKey(const Key('program_draft_publish')), findsNothing);
    expect(find.byKey(const Key('program_draft_discard')), findsNothing);
    expect(find.byKey(const Key('program_draft_save')), findsOneWidget);
    expect(find.byKey(const Key('program_draft_add_day')), findsOneWidget);
    expect(find.text('Write template'), findsOneWidget);

    await tester.enterText(
        find.byKey(const Key('program_template_name')), 'Upper Block v2');
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilGone(tester, find.byKey(const Key('program_template_name')));

    expect(fake.programTemplateUpdateRequests, 1);
    expect(fake.lastProgramTemplateBody?['name'], 'Upper Block v2');
    expect(find.text('Upper Block v2'), findsOneWidget);
  });

  testWidgets('creating a template with an exercise saves the prescription',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    await _pumpLibrary(tester, fake);

    expect(find.text('No Program templates yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('program_templates_new')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_name')));

    expect(find.byKey(const Key('program_draft_publish')), findsNothing);
    await tester.enterText(
        find.byKey(const Key('program_template_name')), 'Leg Day');

    // The default day starts empty, so pick a real exercise before saving.
    await tester.tap(find.byKey(const Key('program_draft_add_exercise_0')));
    await _selectCatalogExercise(tester, 'Bench Press');

    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilGone(tester, find.byKey(const Key('program_template_name')));

    expect(fake.programTemplateCreateRequests, 1);
    final Map<String, dynamic> body = fake.lastProgramTemplateBody!;
    expect(body['name'], 'Leg Day');
    final Map<String, dynamic> program = body['program'] as Map<String, dynamic>;
    final Map<String, dynamic> savedExercise =
        (((program['weeks'] as List<dynamic>)[0]
                as Map<String, dynamic>)['days'] as List<dynamic>)[0]['exercises']
            [0] as Map<String, dynamic>;
    expect(savedExercise['exercise_id'], 'bench_press');
    expect(savedExercise['target_sets'], ProgramDraftPrescription.defaultSets);
    expect(
        savedExercise['target_reps_min'], ProgramDraftPrescription.defaultMinReps);
    expect(
        savedExercise['target_reps_max'], ProgramDraftPrescription.defaultMaxReps);
    expect(savedExercise['target_rir'], ProgramDraftPrescription.defaultRir);
    expect(find.text('Leg Day'), findsOneWidget);
  });

  testWidgets('an invalid template shows server validation and stays open',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    await _pumpLibrary(tester, fake);

    await tester.tap(find.byKey(const Key('program_templates_new')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_name')));
    await tester.enterText(
        find.byKey(const Key('program_template_name')), 'Empty Day');

    // Save the empty default day; the server rejects it with a field error.
    await tester.tap(find.byKey(const Key('program_draft_save')));
    await _pumpUntilFound(
        tester, find.text('Add at least one exercise to this training day.'));

    expect(fake.programTemplateCreateRequests, 1);
    expect(fake.programTemplates, isEmpty);
    // The editor stays open with the name the coach typed.
    expect(find.byKey(const Key('program_template_name')), findsOneWidget);
    expect(find.byKey(const Key('program_draft_save')), findsOneWidget);
  });

  testWidgets('opening a template hydrates the editor from the read response',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake,
        id: 'tmpl:upper',
        name: 'Stale list name',
        description: 'Stale list description');
    fake.programTemplateReadOverrides['tmpl:upper'] = <String, dynamic>{
      'name': 'Fresh name',
      'description': 'Fresh description',
    };
    await _pumpLibrary(tester, fake);
    expect(find.text('Stale list name'), findsOneWidget);

    await tester.tap(find.byKey(const Key('program_template_edit_tmpl:upper')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_name')));

    expect(find.text('Fresh name'), findsOneWidget);
    expect(find.text('Fresh description'), findsOneWidget);
  });

  testWidgets('a description-only edit guards unsaved changes',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake,
        id: 'tmpl:upper', name: 'Upper Block', description: 'Old description');
    await _pumpLibrary(tester, fake);

    await tester.tap(find.byKey(const Key('program_template_edit_tmpl:upper')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_description')));
    await tester.enterText(
        find.byKey(const Key('program_template_description')), 'New description');

    await tester.tap(find.byTooltip('Back').hitTestable().last);
    await _pumpUntilFound(tester, find.text('Unsaved changes'));
    expect(find.byKey(const Key('program_draft_confirm_cancel')), findsOneWidget);
    await tester.tap(find.byKey(const Key('program_draft_confirm_cancel')));
    await tester.pumpAndSettle();
  });

  testWidgets('a failed archive keeps the error visible without reloading',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake);
    final int loadsBefore = fake.programTemplateListRequests;

    fake.failOffline('POST', '/coach/program-templates/tmpl:upper/archive');
    await tester.tap(
        find.byKey(const Key('program_template_archive_tmpl:upper')));
    await _pumpUntilFound(
        tester, find.textContaining('Cannot reach the service'));

    // The dropped request never reached the server, and no reload wiped the
    // surfaced failure; the row is still actionable.
    expect(fake.programTemplateListRequests, loadsBefore);
    expect(find.text('Upper Block'), findsOneWidget);
    expect(find.byKey(const Key('program_template_archive_tmpl:upper')),
        findsOneWidget);
  });

  testWidgets('a failed duplicate keeps the error visible without reloading',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake);
    final int loadsBefore = fake.programTemplateListRequests;

    fake.failOffline('POST', '/coach/program-templates/tmpl:upper/duplicate');
    await tester.tap(
        find.byKey(const Key('program_template_duplicate_tmpl:upper')));
    await _pumpUntilFound(
        tester, find.textContaining('Cannot reach the service'));

    expect(fake.programTemplateListRequests, loadsBefore);
    expect(find.byKey(const Key('program_template_duplicate_tmpl:upper')),
        findsOneWidget);
  });

  testWidgets('archives, reveals and unarchives a template', (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake);

    await tester.tap(
        find.byKey(const Key('program_template_archive_tmpl:upper')));
    await _pumpUntilFound(tester, find.text('No Program templates yet.'));
    expect(fake.programTemplateArchiveRequests, 1);

    await tester.tap(find.byKey(const Key('program_templates_show_archived')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('program_template_unarchive_tmpl:upper')));
    expect(find.text('Archived templates'), findsOneWidget);

    await tester.tap(
        find.byKey(const Key('program_template_unarchive_tmpl:upper')));
    await _pumpUntilFound(tester, find.text('Upper Block'));
    expect(fake.programTemplateUnarchiveRequests, 1);
  });

  testWidgets('duplicates a template with the server default name',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake);

    await tester.tap(
        find.byKey(const Key('program_template_duplicate_tmpl:upper')));
    await _pumpUntilFound(tester, find.text('Upper Block (copy)'));

    expect(fake.programTemplateDuplicateRequests, 1);
    expect(find.text('Duplicated Upper Block (copy).'), findsOneWidget);
  });

  testWidgets('Arabic library renders Arabic copy', (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake, language: 'ar');

    expect(find.text('قوالب البرامج التدريبية'), findsOneWidget);
    expect(find.text('قالب جديد'), findsOneWidget);
  });

  testWidgets('bulk assignment picks players and reports a per-player summary',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    fake.assignments.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'assignment_id': 'asg:1',
        'player_username': 'bob',
        'started_at': '2026-10-01T00:00:00Z',
        'status': 'active',
      },
      <String, dynamic>{
        'assignment_id': 'asg:2',
        'player_username': 'carol',
        'started_at': '2026-10-01T00:00:00Z',
        'status': 'active',
      },
    ]);
    // Carol already holds a draft, so her 'keep existing' choice is respected.
    fake.templateAssignedDrafts['asg:2'] = <String, dynamic>{
      'program_name': 'Existing',
      'days': <dynamic>[],
    };

    await _pumpAssignment(tester, fake);
    expect(find.text('bob'), findsOneWidget);
    expect(find.text('carol'), findsOneWidget);

    await tester.tap(
        find.byKey(const Key('template_assign_player_asg:1')));
    await tester.pump();
    await tester.tap(
        find.byKey(const Key('template_assign_player_asg:2')));
    await tester.pump();
    // Carol's existing draft is skipped by the safe default.
    await tester.tap(find.descendant(
      of: find.byKey(const Key('template_assign_player_asg:2')),
      matching: find.text('Skip if a draft exists'),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('template_assign_submit')));
    await _pumpUntilFound(
      tester,
      find.text('Assigned: 1 · Replaced: 0 · Kept: 1 · Rejected: 0'),
    );

    expect(fake.programTemplateAssignRequests, 1);
    final Map<String, dynamic> skipTarget =
        fake.lastProgramTemplateAssignTargets.firstWhere(
      (Map<String, dynamic> target) => target['assignment_id'] == 'asg:2',
    );
    expect(skipTarget['existing_draft'], 'skip');
    expect(fake.templateAssignedDrafts['asg:2']?['program_name'], 'Existing');
    expect(find.text('bob: Draft assigned'), findsOneWidget);
    expect(find.text('carol: Existing draft kept'), findsOneWidget);

    await tester.tap(find.byKey(const Key('template_publish_all')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('template_publish_all_confirm')));
    await tester.tap(find.byKey(const Key('template_publish_all_confirm')));
    await _pumpUntilFound(
        tester, find.text('Published: 1 · Invalid: 0 · No draft: 0 · Rejected: 0'));
    expect(fake.lastProgramTemplatePublishAllIds, <String>['asg:1']);
    expect(find.text('bob: Program published'), findsOneWidget);
    expect(find.text('carol: Existing draft kept'), findsOneWidget);
  });

  testWidgets('publish all publishes the assigned players after confirmation',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'asg:1',
      'player_username': 'bob',
      'started_at': '2026-10-01T00:00:00Z',
      'status': 'active',
    });

    await _pumpAssignment(tester, fake);
    await tester.tap(find.byKey(const Key('template_assign_player_asg:1')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('template_assign_submit')));
    await _pumpUntilFound(
      tester,
      find.text('Assigned: 1 · Replaced: 0 · Kept: 0 · Rejected: 0'),
    );

    await tester.tap(find.byKey(const Key('template_publish_all')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('template_publish_all_confirm')));
    await tester.tap(find.byKey(const Key('template_publish_all_confirm')));
    await _pumpUntilFound(
      tester,
      find.text('Published: 1 · Invalid: 0 · No draft: 0 · Rejected: 0'),
    );

    expect(fake.programTemplatePublishAllRequests, 1);
    expect(fake.lastProgramTemplatePublishAllIds, <String>['asg:1']);
  });

  testWidgets('publish all keeps player validation details and customize access',
      (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    fake.assignments.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'assignment_id': 'asg:1',
        'player_username': 'bob',
        'started_at': '2026-10-01T00:00:00Z',
        'status': 'active',
      },
      <String, dynamic>{
        'assignment_id': 'asg:2',
        'player_username': 'carol',
        'started_at': '2026-10-01T00:00:00Z',
        'status': 'active',
      },
    ]);
    fake.templatePublishResultOverrides['asg:2'] = <String, dynamic>{
      'status': 'invalid',
      'message_code': 'assignment.program_draft_invalid.v1',
      'errors': <Map<String, dynamic>>[
        <String, dynamic>{'code': 'invalid_rir'},
      ],
    };
    await _pumpAssignment(tester, fake);

    for (final String id in <String>['asg:1', 'asg:2']) {
      await tester.tap(find.byKey(Key('template_assign_player_$id')));
      await tester.pump();
    }
    await tester.tap(find.byKey(const Key('template_assign_submit')));
    await _pumpUntilFound(
        tester, find.text('Assigned: 2 · Replaced: 0 · Kept: 0 · Rejected: 0'));
    await tester.tap(find.byKey(const Key('template_publish_all')));
    await _pumpUntilFound(
        tester, find.byKey(const Key('template_publish_all_confirm')));
    await tester.tap(find.byKey(const Key('template_publish_all_confirm')));
    await _pumpUntilFound(tester, find.byKey(const Key('template_assignment_customize_asg:2')));

    expect(find.text('bob: Program published'), findsOneWidget);
    expect(find.text('carol: Draft needs correction'), findsOneWidget);
    expect(find.text('Target RIR must be from 0 to 5.'), findsOneWidget);
  });

  testWidgets('Arabic assignment screen renders Arabic copy', (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'asg:1',
      'player_username': 'bob',
      'started_at': '2026-10-01T00:00:00Z',
      'status': 'active',
    });

    await _pumpAssignment(tester, fake, language: 'ar');

    expect(
        find.text('اختر اللاعبين الذين سيتلقون نسخة مستقلة. يمكنك تعديل كل نسخة على حدة.'),
        findsOneWidget);
    expect(find.text('إسناد'), findsOneWidget);
  });

  testWidgets('Arabic assignment actions fit a narrow screen', (tester) async {
    final FakeMyosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    fake.assignments.add(<String, dynamic>{
      'assignment_id': 'asg:1',
      'player_username': 'bob',
      'started_at': '2026-10-01T00:00:00Z',
      'status': 'active',
    });
    await _pumpAssignment(tester, fake, language: 'ar', narrow: true);
    expect(find.byKey(const Key('template_assign_submit')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
