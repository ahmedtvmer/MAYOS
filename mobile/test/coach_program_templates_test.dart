import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/program_prescription.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_program_templates_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

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
  FakeMayosApi fake, {
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
  await _pumpUntilFound(tester, find.byKey(const Key('program_draft_sets_0_0')));
}

void _seedTemplate(
  FakeMayosApi fake, {
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
  testWidgets('library lists templates and opens the editor in template mode',
      (tester) async {
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
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
    final FakeMayosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake);

    await tester.tap(
        find.byKey(const Key('program_template_duplicate_tmpl:upper')));
    await _pumpUntilFound(tester, find.text('Upper Block (copy)'));

    expect(fake.programTemplateDuplicateRequests, 1);
    expect(find.text('Duplicated Upper Block (copy).'), findsOneWidget);
  });

  testWidgets('Arabic library renders Arabic copy', (tester) async {
    final FakeMayosApi fake = _coachFake();
    _seedTemplate(fake, id: 'tmpl:upper', name: 'Upper Block');
    await _pumpLibrary(tester, fake, language: 'ar');

    expect(find.text('قوالب البرامج التدريبية'), findsOneWidget);
    expect(find.text('قالب جديد'), findsOneWidget);
  });
}
