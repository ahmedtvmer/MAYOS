import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_nutrition_draft_screen.dart';
import 'package:mayos_mobile/src/features/coach/coach_nutrition_templates_screen.dart';
import 'package:mayos_mobile/src/features/coach/nutrition_template_actions.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/scroll_to_control.dart';

void main() {
  testWidgets('saving a template flushes edits and pins the resulting draft revision', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer();
    await tester.pumpWidget(_app(server, const CoachNutritionDraftScreen(assignmentId: 'assignment')));
    await tester.pumpAndSettle();
    await scrollToControl(tester, find.byKey(const Key('target_daily_calories')));
    await tester.enterText(find.byKey(const Key('target_daily_calories')), '2400');
    await scrollToControl(tester, find.byKey(const Key('save_nutrition_template')), delta: -200);
    await tester.tap(find.byKey(const Key('save_nutrition_template')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('nutrition_template_name')), 'Weekly meals');
    await tester.pump();
    await tester.tap(find.byKey(const Key('confirm_save_nutrition_template')));
    await tester.pumpAndSettle();
    final FakeRequest saved = server.adapter.requests.singleWhere((FakeRequest request) => request.path.endsWith('/save-template'));
    expect(saved.body, <String, dynamic>{'name': 'Weekly meals', 'description': '',
      'source': 'draft', 'revision': 2, 'include_targets': false});
    expect(server.draft['targets']['daily']['calories'], 2400);
    expect(find.text('Nutrition template saved'), findsOneWidget);
  });

  testWidgets('a published plan is saved with its reviewed version and optional targets', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer();
    await tester.pumpWidget(_app(server, const Scaffold(body: NutritionTemplateActions(assignmentId: 'assignment'))));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save current plan as Nutrition template'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('nutrition_template_name')), 'Published meals');
    await tester.pump();
    await tester.tap(find.widgetWithText(SwitchListTile, 'Include targets'));
    await tester.pump();
    await tester.tap(find.byKey(const Key('confirm_save_nutrition_template')));
    await tester.pumpAndSettle();
    final Map<String, dynamic> saved = server.adapter.requests
      .singleWhere((FakeRequest request) => request.path.endsWith('/save-template')).body;
    expect(saved['source'], 'current');
    expect(saved['plan_version_id'], 7);
    expect(saved['include_targets'], isTrue);
    expect(saved.containsKey('revision'), isFalse);
  });

  testWidgets('applying to a new draft displays server portions without publishing', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer()..hasDraft = false;
    await tester.pumpWidget(_app(server, const CoachNutritionDraftScreen(assignmentId: 'assignment')));
    await tester.pumpAndSettle();
    await _chooseTemplate(tester);
    expect(server.adapter.requests.singleWhere((FakeRequest request) => request.path.endsWith('/apply')).body,
      <String, dynamic>{'assignment_id': 'assignment'});
    await scrollToControl(tester, find.byKey(const ValueKey<String>('breakfast_protein')));
    expect(tester.widget<TextFormField>(find.byKey(const ValueKey<String>('breakfast_protein'))).initialValue, '250');
    expect(server.adapter.requests.where((FakeRequest request) => request.path.endsWith('/publish')), isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('replacing an existing draft requires confirmation and sends its revision', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer();
    await tester.pumpWidget(_app(server, const CoachNutritionDraftScreen(assignmentId: 'assignment')));
    await tester.pumpAndSettle();
    await _chooseTemplate(tester);
    expect(find.text('Replace this draft?'), findsOneWidget);
    expect(server.adapter.requests.where((FakeRequest request) => request.path.endsWith('/apply')), isEmpty);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    await _chooseTemplate(tester);
    await tester.tap(find.text('Replace draft'));
    await tester.pumpAndSettle();
    expect(server.adapter.requests.singleWhere((FakeRequest request) => request.path.endsWith('/apply')).body,
      <String, dynamic>{'assignment_id': 'assignment', 'revision': 1});
  });

  testWidgets('template editing saves catalog content without Assignment calls', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer();
    await tester.pumpWidget(_app(server, const CoachNutritionDraftScreen.template(templateId: 'template')));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, 'Template name'), 'Revised meals');
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    final FakeRequest saved = server.adapter.requests.singleWhere((FakeRequest request) => request.method == 'PUT');
    expect(saved.path, '/coach/nutrition-templates/template');
    expect(saved.body['name'], 'Revised meals');
    expect(saved.body['nutrition']['targets'], isEmpty);
    expect(saved.body['nutrition']['variants']['daily'][0]['note'], 'Before training');
    expect(server.adapter.requests.where((FakeRequest request) => request.path.contains('/assignments/')), isEmpty);
    expect(find.byKey(const Key('publish_nutrition_draft')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('library deletion keeps the template until confirmation', (WidgetTester tester) async {
    final _TemplateServer server = _TemplateServer();
    await tester.pumpWidget(_app(server, const CoachNutritionTemplatesScreen()));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Delete template'));
    await tester.pumpAndSettle();
    expect(server.adapter.requests.where((FakeRequest request) => request.method == 'DELETE'), isEmpty);
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('Reusable meals'), findsNothing);
    expect(server.adapter.requests.singleWhere((FakeRequest request) => request.method == 'DELETE').path,
      '/coach/nutrition-templates/template');
  });
}

Future<void> _chooseTemplate(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('apply_nutrition_template')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Reusable meals'));
  await tester.pumpAndSettle();
}

Widget _app(_TemplateServer server, Widget screen) => ProviderScope(overrides: <Override>[
  apiClientProvider.overrideWith((ref) => ApiClient(tokens: InMemoryTokenStore(),
    baseUrl: 'http://test.local', adapter: server.adapter)),
  systemDisplayLanguageProvider.overrideWithValue('en'),
], child: MaterialApp(home: screen));

class _TemplateServer {
  _TemplateServer() { adapter = FakeApiAdapter(_reply); }
  late final FakeApiAdapter adapter;
  bool hasDraft = true;
  bool deleted = false;
  int revision = 1;
  final Map<String, dynamic> food = <String, dynamic>{
    'id': 'protein', 'name': 'Areesh', 'arabic_name': 'جبن قريش', 'grams': 100,
    'restriction_reasons': <String>[],
    'nutrients_per_100g': <String, dynamic>{'energy_kcal': 200, 'protein_g': 20, 'carbohydrate_g': 20, 'fat_g': 5},
  };
  Map<String, dynamic> draft = <String, dynamic>{
    'goal': 'maintain', 'daily_activity': 'mostly_sitting',
    'targets': <String, dynamic>{'daily': <String, dynamic>{'calories': 2000, 'protein_g': 150, 'carbs_g': 200, 'fat_g': 60}},
    'variants': <String, dynamic>{'daily': <dynamic>[<String, dynamic>{
      'slot': 'breakfast', 'name': 'Breakfast', 'note': 'Before training', 'log_label': 'breakfast',
      'foods': <dynamic>[<String, dynamic>{'id': 'protein', 'grams': 100}],
    }]},
  };

  Map<String, dynamic> _template() => <String, dynamic>{
    'template_id': 'template', 'name': 'Reusable meals', 'description': 'Reusable description',
    'nutrition': <String, dynamic>{...draft, 'targets': <String, dynamic>{}}, 'foods': <dynamic>[food],
  };

  Map<String, dynamic> _record() => <String, dynamic>{
    'draft': draft, 'revision': revision, 'targets_changed': false,
    'evaluation': <String, dynamic>{'can_publish': true, 'errors': <String>[],
      'variants': <String, dynamic>{'daily': <String, dynamic>{'meals': <dynamic>[
        <String, dynamic>{'foods': <dynamic>[food]},
      ]}}},
  };

  FakeResponse _reply(FakeRequest request) {
    if (request.path.endsWith('/save-template')) return FakeResponse(201, _template());
    if (request.path.endsWith('/template-source')) {
      return FakeResponse(200, <String, dynamic>{'plan_version_id': 7, 'nutrition': draft});
    }
    if (request.path == '/coach/nutrition-templates') {
      return FakeResponse(200, <String, dynamic>{'templates': deleted ? <dynamic>[] : <dynamic>[_template()]});
    }
    if (request.path.endsWith('/apply')) {
      hasDraft = true;
      draft['variants']['daily'][0]['foods'][0]['grams'] = 250;
      return FakeResponse(200, _record());
    }
    if (request.path == '/coach/nutrition-templates/template') {
      if (request.method == 'DELETE') { deleted = true; return const FakeResponse(204); }
      return FakeResponse(200, _template());
    }
    if (request.path.endsWith('/draft')) {
      if (!hasDraft) return const FakeResponse(404, <String, dynamic>{'detail': 'Nutrition draft not found.'});
      if (request.method == 'PUT') {
        draft = jsonDecode(jsonEncode(request.body['draft'])) as Map<String, dynamic>;
        revision++;
      }
      return FakeResponse(200, _record());
    }
    return const FakeResponse(404, <String, dynamic>{'detail': 'Unexpected request'});
  }
}
