import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_nutrition_draft_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/scroll_to_control.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final double width in <double>[390, 1200]) {
      testWidgets('editor autosaves and shows live totals at $width in $language', (WidgetTester tester) async {
        final _DraftServer server = _DraftServer();
        _size(tester, width);
        await tester.pumpWidget(_app(server, language));
        await tester.pumpAndSettle();
        final Finder editor = find.byType(CoachNutritionDraftScreen);
        final Finder target = find.byKey(const Key('target_daily_calories'));
        await scrollToControl(tester, target);
        await tester.enterText(target, '2300');
        await tester.pump(const Duration(milliseconds: 650));
        await tester.pumpAndSettle();
        expect(server.saves.single['draft']['targets']['daily']['calories'], 2300);
        expect(server.saves.single['revision'], 1);
        final Finder grams = find.byKey(const ValueKey<String>('breakfast_protein'));
        await scrollToControl(tester, grams);
        await tester.enterText(grams, '300');
        await tester.pump(const Duration(milliseconds: 650));
        await tester.pumpAndSettle();
        expect(server.saves.last['revision'], 2);
        expect(server.saves.last['draft']['variants']['daily'][0]['foods'][0]['grams'], 300);
        expect(find.textContaining('600 / 2300'), findsNWidgets(2));
        final Directionality direction = tester.widget<Directionality>(find.descendant(
          of: editor, matching: find.byType(Directionality)).first);
        expect(direction.textDirection, language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
        expect(tester.takeException(), isNull);
      });
    }
  }

  testWidgets('edits made during autosave survive the in-flight response', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer();
    final Completer<void> release = Completer<void>();
    server.adapter.beforeRespond = (FakeRequest request) async {
      if (request.method == 'PUT' && server.saves.isEmpty) await release.future;
    };
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    final Finder target = find.byKey(const Key('target_daily_calories'));
    await tester.enterText(target, '2200');
    await tester.pump(const Duration(milliseconds: 650));
    await tester.enterText(target, '2400');
    release.complete();
    await tester.pumpAndSettle();
    expect(server.saves, hasLength(2));
    expect(server.saves.last['draft']['targets']['daily']['calories'], 2400);
    expect(server.saves.last['revision'], 2);
    await tester.pump(const Duration(milliseconds: 700));
  });

  testWidgets('failed autosave stays editable and publish waits for an explicit retry', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer()..failSave = true;
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('target_daily_calories')), '2100');
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    expect(find.text('Could not save draft.'), findsOneWidget);
    await scrollToControl(tester, find.byKey(const Key('publish_nutrition_draft')));
    expect(tester.widget<FilledButton>(find.byKey(const Key('publish_nutrition_draft'))).onPressed, isNull);
    server.failSave = false;
    await scrollToControl(tester, find.text('Retry save'), delta: -200);
    await tester.tap(find.text('Retry save'));
    await tester.pumpAndSettle();
    expect(find.text('All changes saved'), findsOneWidget);
    expect(server.saves.last['draft']['targets']['daily']['calories'], 2100);
  });

  testWidgets('training and rest variants keep independent targets and portions', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer();
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(SwitchListTile, 'Training / rest variants'));
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('target_training_day_calories')), '2500');
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    expect(server.draft['targets']['training_day']['calories'], 2500);
    expect(server.draft['targets']['rest_day']['calories'], 2000);
    final Finder grams = find.descendant(
      of: find.byKey(const ValueKey<String>('training_day_breakfast')),
      matching: find.byKey(const ValueKey<String>('breakfast_protein')));
    await scrollToControl(tester, grams);
    await tester.enterText(grams, '150');
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    expect(server.draft['variants']['training_day'][0]['foods'][0]['grams'], 150);
    expect(server.draft['variants']['rest_day'][0]['foods'][0]['grams'], 100);
    expect(tester.takeException(), isNull);
  });

  testWidgets('invalid draft exposes publish errors without a publish request', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer()..publishable = false;
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    await scrollToControl(tester, find.byKey(const Key('publish_nutrition_draft')));
    expect(find.textContaining('totals must be within 15%'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('publish_nutrition_draft'))).onPressed, isNull);
    expect(server.publications, isEmpty);
  });

  testWidgets('publishing confirms authority takeover and sends the saved revision', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer();
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    await scrollToControl(tester, find.byKey(const Key('publish_nutrition_draft')));
    await tester.tap(find.byKey(const Key('publish_nutrition_draft')));
    await tester.pumpAndSettle();
    expect(find.textContaining('gives you Nutrition authority'), findsOneWidget);
    expect(server.publications, isEmpty);
    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.byType(FilledButton)));
    await tester.pumpAndSettle();
    expect(server.publications.single, <String, dynamic>{'revision': 1, 'confirm_takeover': true});
  });

  testWidgets('restricted food stays searchable with a warning and can be added to review', (WidgetTester tester) async {
    final _DraftServer server = _DraftServer();
    await tester.pumpWidget(_app(server, 'en'));
    await tester.pumpAndSettle();
    await scrollToControl(tester, find.text('Add Staple food'));
    await tester.tap(find.text('Add Staple food'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Food restriction: milk'), findsOneWidget);
    await tester.tap(find.text('Areesh'));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(milliseconds: 650));
    await tester.pumpAndSettle();
    expect(find.text('⚠ Food restriction'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

void _size(WidgetTester tester, double width) {
  tester.view.physicalSize = Size(width, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Widget _app(_DraftServer server, String language) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) => ApiClient(tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local', adapter: server.adapter)),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ],
  child: const MaterialApp(home: CoachNutritionDraftScreen(assignmentId: 'assignment')),
);

class _DraftServer {
  _DraftServer() { adapter = FakeApiAdapter(_reply); }
  late final FakeApiAdapter adapter;
  bool failSave = false;
  bool publishable = true;
  int revision = 1;
  final List<Map<String, dynamic>> saves = <Map<String, dynamic>>[];
  final List<Map<String, dynamic>> publications = <Map<String, dynamic>>[];
  Map<String, dynamic> draft = <String, dynamic>{
    'goal': 'maintain', 'daily_activity': 'mostly_sitting',
    'targets': <String, dynamic>{'daily': <String, dynamic>{'calories': 2000, 'protein_g': 150, 'carbs_g': 200, 'fat_g': 60}},
    'variants': <String, dynamic>{'daily': <dynamic>[<String, dynamic>{
      'slot': 'breakfast', 'name': 'Breakfast', 'note': '', 'log_label': 'breakfast',
      'foods': <dynamic>[<String, dynamic>{'id': 'protein', 'grams': 100}],
    }]},
  };
  final Map<String, dynamic> food = <String, dynamic>{
    'id': 'protein', 'name': 'Areesh', 'arabic_name': 'جبن قريش', 'grams': 100,
    'restriction_reasons': <String>[],
    'nutrients_per_100g': <String, dynamic>{'energy_kcal': 200, 'protein_g': 20, 'carbohydrate_g': 20, 'fat_g': 5},
  };

  Map<String, dynamic> _record() => <String, dynamic>{
    'revision': revision, 'draft': draft, 'targets_changed': false,
    'evaluation': <String, dynamic>{'can_publish': publishable, 'calorie_floor': 1500,
      'errors': publishable ? <String>[] : <String>['daily: totals must be within 15% of every target.'],
      'variants': <String, dynamic>{'daily': <String, dynamic>{'meals': <dynamic>[
        <String, dynamic>{'foods': <dynamic>[food]},
      ]}},
    },
  };

  FakeResponse _reply(FakeRequest request) {
    if (request.path.endsWith('/foods')) {
      food['restriction_reasons'] = <String>['milk'];
      return FakeResponse(200, <String, dynamic>{'foods': <dynamic>[food]});
    }
    if (request.path.endsWith('/publish')) {
      publications.add(request.body);
      return const FakeResponse(200, <String, dynamic>{'plan_version_id': 2, 'with_meals': true});
    }
    if (request.method == 'PUT') {
      if (failSave) return const FakeResponse(503, <String, dynamic>{'detail': 'Could not save draft.'});
      saves.add(jsonDecode(jsonEncode(request.body)) as Map<String, dynamic>);
      draft = request.body['draft'] as Map<String, dynamic>;
      revision++;
    }
    return FakeResponse(200, _record());
  }
}
