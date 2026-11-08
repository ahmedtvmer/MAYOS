import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_swap_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/today_meals.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    testWidgets('$language shows preview and saves a permanent plan swap', (WidgetTester tester) async {
      final _SwapApi api = _SwapApi();
      final FoodSwapCopy copy = FoodSwapCopy(language);
      await _open(tester, api, language);
      expect(find.text(copy.permanent), findsOneWidget);
      expect(find.text(copy.preview(150, 500, 40)), findsOneWidget);
      expect(Directionality.of(tester.element(find.text(copy.permanent))),
        language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
      await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('save_food_swap')));
      await tester.pumpAndSettle();
      final FakeRequest saved = api.adapter.requests.singleWhere((FakeRequest request) =>
        request.path == '/nutrition/meals/swap');
      expect(saved.body, <String, dynamic>{'plan_version_id': 2, 'day_type': 'rest_day',
        'slot': 'breakfast', 'role': 'protein', 'food_id': 'alternative'});
      expect(find.textContaining(language == 'ar' ? 'بديل البروتين' : 'Alternative protein'), findsOneWidget);
      expect(api.adapter.requests.where((FakeRequest request) => request.path.contains('food-log')), isEmpty);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('search shows restriction warning and blocks selection', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi();
    await _open(tester, api, 'en');
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'Milk');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    expect(find.text('Restricted food: Milk'), findsOneWidget);
    expect(find.text('Next Staple foods'), findsOneWidget);
    final ListTile blocked = tester.widget<ListTile>(find.byKey(const Key('food_swap_search_milk')));
    expect(blocked.onTap, isNull);
    expect(tester.widget<FilledButton>(find.byKey(const Key('save_food_swap'))).onPressed, isNull);
    expect(api.adapter.requests.where((FakeRequest request) => request.method == 'POST'), isEmpty);
  });

  testWidgets('search selection saves the searched food and refreshes the meal', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi();
    await _open(tester, api, 'en');
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'new');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('food_swap_search_new')));
    await tester.tap(find.byKey(const Key('food_swap_search_new')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    expect(api.adapter.requests.singleWhere((FakeRequest request) =>
      request.path == '/nutrition/meals/swap').body['food_id'], 'new');
    expect(find.textContaining('new food'), findsOneWidget);
  });

  testWidgets('failed save retains selection and plan for deliberate retry', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi()..failSave = true;
    await _open(tester, api, 'en');
    await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    expect(find.text('Could not save Food swap.'), findsOneWidget);
    expect(api.version, 2);
    api.failSave = false;
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    expect(api.version, 3);
    expect(find.textContaining('Alternative protein'), findsOneWidget);
  });

  testWidgets('an older search cannot replace the latest results', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi();
    final Completer<void> oldSearch = Completer<void>();
    api.adapter.beforeRespond = (FakeRequest request) async {
      if (request.query['q'] == 'old') await oldSearch.future;
    };
    await _open(tester, api, 'en');
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'old');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'new');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('food_swap_search_new')), findsOneWidget);
    oldSearch.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('food_swap_search_new')), findsOneWidget);
    expect(find.byKey(const Key('food_swap_search_old')), findsNothing);
  });

  testWidgets('Coach authority hides the swap control', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi()..coachPlan = true;
    await tester.pumpWidget(_app(api, 'en'));
    await tester.pumpAndSettle();
    expect(find.text('Set by your coach'), findsOneWidget);
    expect(find.byKey(const Key('swap_breakfast_protein')), findsNothing);
    expect(api.adapter.requests.map((FakeRequest request) => request.path),
      unorderedEquals(<String>['/nutrition/meals', '/nutrition/food-swap-requests']));
    expect(api.adapter.requests.every((FakeRequest request) => request.method == 'GET'), isTrue);
  });
}

Future<void> _open(WidgetTester tester, _SwapApi api, String language) async {
  await tester.pumpWidget(_app(api, language));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('swap_breakfast_protein')));
  await tester.pumpAndSettle();
}

Widget _app(_SwapApi api, String language) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      tokens.save('swap-token');
      return ApiClient(tokens: tokens, baseUrl: 'http://test.local', adapter: api.adapter);
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ],
  child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: TodayMeals(onLogged: () {})))),
);

class _SwapApi {
  _SwapApi() { adapter = FakeApiAdapter(_respond); }
  late final FakeApiAdapter adapter;
  bool failSave = false;
  bool coachPlan = false;
  int version = 2;
  String selectedId = 'alternative';

  FakeResponse _respond(FakeRequest request) {
    switch (request.path) {
      case '/nutrition/food-swap-requests':
        return const FakeResponse(200, <String, dynamic>{'requests': <dynamic>[]});
      case '/nutrition/meals':
        return FakeResponse(200, <String, dynamic>{
          'status': 'ready', 'date': '2026-11-08', 'day_type': 'rest_day', 'enabled': true,
          'plan_version_id': version, 'author': coachPlan ? 'Coach' : 'Player', 'can_swap': !coachPlan,
          'meals': <Map<String, dynamic>>[<String, dynamic>{
            'slot': 'breakfast', 'totals': <String, dynamic>{'calories': 500},
            'foods': <Map<String, dynamic>>[<String, dynamic>{
              'id': version == 2 ? 'protein' : selectedId, 'role': 'protein', 'grams': 150,
              'name': version == 2 ? 'Areesh' : selectedId == 'alternative' ? 'Alternative protein' : '$selectedId food',
              'arabic_name': version == 2 ? 'جبن قريش' : selectedId == 'alternative' ? 'بديل البروتين' : null,
            }],
          }],
        });
      case '/nutrition/meals/swap-candidates':
        final String query = request.query['q'] as String? ?? '';
        return FakeResponse(200, <String, dynamic>{
          'staples': <Map<String, dynamic>>[_candidate('alternative', 'Alternative protein', arabic: 'بديل البروتين')],
          'search': <Map<String, dynamic>>[
            if (query == 'Milk') _candidate('milk', 'Milk', reasons: <String>['milk']),
            if (query == 'old' || query == 'new') _candidate(query, '$query food'),
          ],
        });
      case '/nutrition/meals/swap':
        if (failSave) return const FakeResponse(503, <String, dynamic>{'detail': 'Could not save Food swap.'});
        selectedId = request.body['food_id'] as String;
        version++;
        return FakeResponse(201, <String, dynamic>{'plan_version_id': version});
      default:
        return const FakeResponse(404, <String, dynamic>{'detail': 'Unknown test route'});
    }
  }
}

Map<String, dynamic> _candidate(String id, String name, {String? arabic, List<String> reasons = const <String>[]}) =>
  <String, dynamic>{
    'food': <String, dynamic>{'id': id, 'name': name, 'arabic_name': arabic,
      'reviewed': true, 'restriction_reasons': reasons,
      'nutrients': <String, dynamic>{'energy_kcal': 120, 'protein_g': 30, 'carbohydrate_g': 0, 'fat_g': 0}},
    'allowed': reasons.isEmpty, 'grams': reasons.isEmpty ? 150 : null,
    'totals': reasons.isEmpty ? <String, dynamic>{'calories': 500, 'protein_g': 40} : null,
  };
