import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_swap_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/display_language/planned_meals_copy.dart';
import 'package:mayos_mobile/src/features/player/nutrition/today_meals.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/scroll_to_control.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets(
          '$language $brightness shows preview and saves a permanent plan swap at 360 dp',
          (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final _SwapApi api = _SwapApi();
        final FoodSwapCopy copy = FoodSwapCopy(language);
        await _open(tester, api, language, brightness: brightness);
        expect(
            find.text(copy.swapFood(language == 'ar' ? 'جبن قريش' : 'Areesh')),
            findsOneWidget);
        expect(
            find.text(copy.staysWithin(
                PlannedMealsCopy(language).slot('breakfast'), 40)),
            findsOneWidget);
        expect(find.text(copy.cancel), findsOneWidget);
        expect(find.byType(Radio<String>), findsOneWidget);
        expect(find.text(copy.permanent), findsOneWidget);
        expect(find.text(copy.preview(150, 500, 40)), findsOneWidget);
        expect(Directionality.of(tester.element(find.text(copy.permanent))),
            language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
        await tester.ensureVisible(
            find.byKey(const Key('food_swap_staple_alternative')));
        await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
        await tester.pump();
        await tester.tap(find.byKey(const Key('save_food_swap')));
        await tester.pumpAndSettle();
        final FakeRequest saved = api.adapter.requests.singleWhere(
            (FakeRequest request) => request.path == '/nutrition/meals/swap');
        expect(saved.body, <String, dynamic>{
          'plan_version_id': 2,
          'day_type': 'rest_day',
          'slot': 'breakfast',
          'role': 'protein',
          'food_id': 'alternative'
        });
        expect(
            find.textContaining(
                language == 'ar' ? 'بديل البروتين' : 'Alternative protein'),
            findsOneWidget);
        expect(
            api.adapter.requests.where(
                (FakeRequest request) => request.path.contains('food-log')),
            isEmpty);
        expect(tester.takeException(), isNull);
      });
    }
  }

  testWidgets('swap guidance shows a larger actual calorie range when portions need it', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi()..replacementCalories = 650;
    await _open(tester, api, 'en');
    expect(find.text(const FoodSwapCopy('en').staysWithin('Breakfast', 150)), findsOneWidget);
    await _showSwapControl(tester, find.byKey(const Key('food_swap_staple_alternative')));
    await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const Key('save_food_swap'))).onPressed, isNotNull);
  });

  testWidgets('search shows restriction warning and blocks selection', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi();
    await _open(tester, api, 'en');
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search')));
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'Milk');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    await _showSwapControl(tester, find.text('Next Staple foods'));
    expect(find.text('Next Staple foods'), findsOneWidget);
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search_milk')));
    expect(find.text('Restricted food: Milk'), findsOneWidget);
    final ListTile blocked = tester.widget<ListTile>(find.byKey(const Key('food_swap_search_milk')));
    expect(blocked.onTap, isNull);
    expect(tester.widget<FilledButton>(find.byKey(const Key('save_food_swap'))).onPressed, isNull);
    expect(api.adapter.requests.where((FakeRequest request) => request.method == 'POST'), isEmpty);
  });

  testWidgets('search selection saves the searched food and refreshes the meal', (WidgetTester tester) async {
    final _SwapApi api = _SwapApi();
    await _open(tester, api, 'en');
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search')));
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'new');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search_new')));
    await tester.tap(find.byKey(const Key('food_swap_search_new')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    expect(api.adapter.requests.singleWhere((FakeRequest request) =>
      request.path == '/nutrition/meals/swap').body['food_id'], 'new');
    expect(find.textContaining('new food'), findsOneWidget);
  });

  testWidgets('failed save retains selection and plan for deliberate retry',
      (WidgetTester tester) async {
    final _SwapApi api = _SwapApi()..failSave = true;
    await _open(tester, api, 'en');
    await _showSwapControl(tester, find.byKey(const Key('food_swap_staple_alternative')));
    await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    await _showSwapControl(tester, find.text('Could not save Food swap.'));
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
    addTearDown(() { if (!oldSearch.isCompleted) oldSearch.complete(); });
    api.adapter.beforeRespond = (FakeRequest request) async {
      if (request.query['q'] == 'old') await oldSearch.future;
    };
    await _open(tester, api, 'en');
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search')));
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'old');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'new');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search_new')));
    expect(find.byKey(const Key('food_swap_search_new')), findsOneWidget);
    oldSearch.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('food_swap_search_new')), findsOneWidget);
    expect(find.byKey(const Key('food_swap_search_old')), findsNothing);
  });

  testWidgets('Coach authority hides the swap control',
      (WidgetTester tester) async {
    final _SwapApi api = _SwapApi()..coachPlan = true;
    await tester.pumpWidget(_app(api, 'en'));
    await tester.pumpAndSettle();
    expect(find.text('Set by your coach'), findsOneWidget);
    expect(find.byKey(const Key('swap_breakfast_protein')), findsNothing);
    expect(api.adapter.requests.map((FakeRequest request) => request.path),
        unorderedEquals(<String>['/nutrition/meals']));
    expect(
        api.adapter.requests
            .every((FakeRequest request) => request.method == 'GET'),
        isTrue);
  });

  testWidgets('keyboard leaves swap options reachable above the pinned actions', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetViewInsets);
    final _SwapApi api = _SwapApi();
    await _open(tester, api, 'en');
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    await tester.pumpAndSettle();
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search')));
    await tester.enterText(find.byKey(const Key('food_swap_search')), 'new');
    await tester.pumpAndSettle(const Duration(milliseconds: 300));
    await _showSwapControl(tester, find.byKey(const Key('food_swap_search_new')));
    final Rect optionsViewport = tester.getRect(find.byKey(const Key('food_swap_options')));
    final Rect searchedOption = tester.getRect(find.byKey(const Key('food_swap_search_new')));
    expect(searchedOption.top, greaterThanOrEqualTo(optionsViewport.top));
    expect(searchedOption.bottom, lessThanOrEqualTo(optionsViewport.bottom));
    await tester.tap(find.byKey(const Key('food_swap_search_new')));
    await tester.pump();
    expect(tester.getBottomRight(find.byKey(const Key('save_food_swap'))).dy, lessThanOrEqualTo(300));
    await tester.tap(find.byKey(const Key('save_food_swap')));
    await tester.pumpAndSettle();
    expect(api.selectedId, 'new');
    expect(tester.takeException(), isNull);
  });
}

Future<void> _showSwapControl(WidgetTester tester, Finder control) async {
  await scrollToControl(tester, control,
    list: find.byKey(const Key('food_swap_options')), delta: 120);
  expect(control.hitTestable(), findsOneWidget);
}

Future<void> _open(WidgetTester tester, _SwapApi api, String language,
    {Brightness brightness = Brightness.light}) async {
  await tester.pumpWidget(_app(api, language, brightness: brightness));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('swap_breakfast_protein')));
  await tester.pumpAndSettle();
}

Widget _app(_SwapApi api, String language,
        {Brightness brightness = Brightness.light}) =>
    ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWith((ref) {
          final InMemoryTokenStore tokens = InMemoryTokenStore();
          tokens.save('swap-token');
          return ApiClient(
              tokens: tokens,
              baseUrl: 'http://test.local',
              adapter: api.adapter);
        }),
        systemDisplayLanguageProvider.overrideWithValue(language),
      ],
      child: MaterialApp(
          theme: brightness == Brightness.dark
              ? MayosTheme.darkForLanguage(language)
              : MayosTheme.lightForLanguage(language),
          home: Scaffold(
              body: SingleChildScrollView(child: TodayMeals(onLogged: () {})))),
    );

class _SwapApi {
  _SwapApi() {
    adapter = FakeApiAdapter(_respond);
  }
  late final FakeApiAdapter adapter;
  bool failSave = false;
  bool coachPlan = false;
  double replacementCalories = 500;
  int version = 2;
  String selectedId = 'alternative';

  FakeResponse _respond(FakeRequest request) {
    switch (request.path) {
      case '/nutrition/food-swap-requests':
        return const FakeResponse(
            200, <String, dynamic>{'requests': <dynamic>[]});
      case '/nutrition/meals':
        return FakeResponse(200, <String, dynamic>{
          'status': 'ready',
          'date': '2026-11-08',
          'day_type': 'rest_day',
          'enabled': true,
          'plan_version_id': version,
          'author': coachPlan ? 'Coach' : 'Player',
          'can_swap': !coachPlan,
          'meals': <Map<String, dynamic>>[
            <String, dynamic>{
              'slot': 'breakfast',
              'totals': <String, dynamic>{'calories': 500},
              'foods': <Map<String, dynamic>>[
                <String, dynamic>{
                  'id': version == 2 ? 'protein' : selectedId,
                  'role': 'protein',
                  'grams': 150,
                  'name': version == 2
                      ? 'Areesh'
                      : selectedId == 'alternative'
                          ? 'Alternative protein'
                          : '$selectedId food',
                  'arabic_name': version == 2
                      ? 'جبن قريش'
                      : selectedId == 'alternative'
                          ? 'بديل البروتين'
                          : null,
                }
              ],
            }
          ],
        });
      case '/nutrition/meals/swap-candidates':
        final String query = request.query['q'] as String? ?? '';
        return FakeResponse(200, <String, dynamic>{
          'staples': <Map<String, dynamic>>[
            _candidate('alternative', 'Alternative protein',
                arabic: 'بديل البروتين', calories: replacementCalories)
          ],
          'search': <Map<String, dynamic>>[
            if (query == 'Milk')
              _candidate('milk', 'Milk', reasons: <String>['milk']),
            if (query == 'old' || query == 'new')
              _candidate(query, '$query food'),
          ],
        });
      case '/nutrition/meals/swap':
        if (failSave)
          return const FakeResponse(
              503, <String, dynamic>{'detail': 'Could not save Food swap.'});
        selectedId = request.body['food_id'] as String;
        version++;
        return FakeResponse(201, <String, dynamic>{'plan_version_id': version});
      default:
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Unknown test route'});
    }
  }
}

Map<String, dynamic> _candidate(String id, String name,
        {String? arabic, List<String> reasons = const <String>[], double calories = 500}) =>
    <String, dynamic>{
      'food': <String, dynamic>{
        'id': id,
        'name': name,
        'arabic_name': arabic,
        'reviewed': true,
        'restriction_reasons': reasons,
        'nutrients': <String, dynamic>{
          'energy_kcal': 120,
          'protein_g': 30,
          'carbohydrate_g': 0,
          'fat_g': 0
        }
      },
      'allowed': reasons.isEmpty,
      'grams': reasons.isEmpty ? 150 : null,
      'totals': reasons.isEmpty
          ? <String, dynamic>{'calories': calories, 'protein_g': 40}
          : null,
    };
