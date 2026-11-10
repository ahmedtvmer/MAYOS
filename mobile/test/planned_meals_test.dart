import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/planned_meals_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/features/player/nutrition/today_meals.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets('$language enables meals and copies foods in $brightness', (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        final PlannedMealsCopy copy = PlannedMealsCopy(language);
        int reloads = 0;
        await tester.pumpWidget(_app(fake, language, brightness,
          SingleChildScrollView(child: TodayMeals(onLogged: () => reloads++))));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('enable_meals')));
        await tester.pumpAndSettle();
        expect(find.textContaining(language == 'ar' ? 'جبن قريش' : 'Areesh'), findsOneWidget);
        expect(find.textContaining('150 g'), language == 'ar' ? findsNothing : findsOneWidget);
        expect(find.text(language == 'ar' ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة' : 'All weights are cooked, except salad vegetables and fruit'), findsOneWidget);
        expect(find.textContaining(language == 'ar' ? 'فرق الحصص العملية' : 'Practical portions compared'), findsNothing);
        expect(Directionality.of(tester.element(find.text(copy.title))),
          language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
        await tester.tap(find.byKey(const Key('log_planned_breakfast')));
        await tester.pumpAndSettle();
        expect(fake.lastPlannedMealLog, <String, dynamic>{
          'slot': 'breakfast', 'entry_date': fake.foodLogToday, 'plan_version_id': 2});
        expect(fake.foodLogEntries[fake.foodLogToday]!.single['grams'], 150);
        expect(reloads, 1);
        expect(find.text(copy.logged), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }

  for (final String language in <String>['en', 'ar']) {
    testWidgets('$language shows the day gap once and cooked weights once per Player meal', (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      final Map<String, String> gap = <String, String>{
        'en': 'About 120 kcal and 15 g protein under. Add a snack or a bigger portion.',
        'ar': 'تقريبًا: نقص 120 سعرة و15 غ بروتين. أضف وجبة خفيفة أو حصة أكبر.',
      };
      fake.plannedMealsState = <String, dynamic>{...fake.plannedMealsState,
        'status': 'ready', 'plan_version_id': 2, 'gap_note': gap,
        'meals': <Map<String, dynamic>>[...fake.generatedMeals,
          <String, dynamic>{...fake.generatedMeals.single, 'slot': 'lunch'}]};
      await tester.pumpWidget(_app(fake, language, Brightness.light,
        SingleChildScrollView(child: TodayMeals(onLogged: () {}))));
      await tester.pumpAndSettle();
      expect(find.text(gap[language]!), findsOneWidget);
      expect(find.text(gap[language == 'en' ? 'ar' : 'en']!), findsNothing);
      expect(find.text(language == 'ar' ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة' : 'All weights are cooked, except salad vegetables and fruit'), findsNWidgets(2));
      expect(tester.takeException(), isNull);
    });

    testWidgets('$language keeps Coach grams and notes without generated-meal claims', (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.plannedMealsState = <String, dynamic>{...fake.plannedMealsState,
        'status': 'ready', 'author': 'Coach', 'plan_version_id': 2,
        'meals': <Map<String, dynamic>>[<String, dynamic>{...fake.generatedMeals.single,
          'note': language == 'ar' ? 'وجبة حددها المدرب' : 'Coach meal',
          'totals': <String, dynamic>{'calories': 15.6}, 'target_deviation': <String, double>{},
          'foods': <Map<String, dynamic>>[<String, dynamic>{
            ...(fake.generatedMeals.single['foods'] as List<Map<String, dynamic>>).single, 'grams': 13}]}]};
      await tester.pumpWidget(_app(fake, language, Brightness.light,
        SingleChildScrollView(child: TodayMeals(onLogged: () {}))));
      await tester.pumpAndSettle();
      expect(find.textContaining(language == 'ar' ? '13 غ' : '13 g'), findsOneWidget);
      expect(find.text(language == 'ar' ? 'وجبة حددها المدرب' : 'Coach meal'), findsOneWidget);
      expect(find.text(language == 'ar' ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة' : 'All weights are cooked, except salad vegetables and fruit'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('unreviewed Staples show plain unavailable copy with no enable', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..plannedMealsState = <String, dynamic>{
      'status': 'unavailable', 'reason': 'staples', 'meals': <dynamic>[], 'can_enable': true};
    await tester.pumpWidget(_app(fake, 'en', Brightness.light, TodayMeals(onLogged: () {})));
    await tester.pumpAndSettle();
    expect(find.text(const PlannedMealsCopy('en').unavailable), findsOneWidget);
    expect(find.byKey(const Key('enable_meals')), findsNothing);
    expect(find.byKey(const Key('log_planned_breakfast')), findsNothing);
  });

  testWidgets('failed log keeps the meal visible for a deliberate retry', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..foodWriteFails = true;
    fake.plannedMealsState = <String, dynamic>{...fake.plannedMealsState,
      'status': 'ready', 'plan_version_id': 2, 'meals': fake.generatedMeals};
    int reloads = 0;
    await tester.pumpWidget(_app(fake, 'en', Brightness.light, TodayMeals(onLogged: () => reloads++)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    expect(find.text('Could not save food.'), findsOneWidget);
    expect(reloads, 0);
    expect(fake.foodLogEntries, isEmpty);
    fake.foodWriteFails = false;
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    expect(reloads, 1);
    expect(fake.foodLogEntries[fake.foodLogToday], hasLength(1));
  });

  testWidgets('Nutrition tab refreshes the Food log after a planned meal', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    fake.plannedMealsState = <String, dynamic>{...fake.plannedMealsState,
      'status': 'ready', 'plan_version_id': 2, 'meals': fake.generatedMeals};
    fake.nutritionState = <String, dynamic>{'state': 'ready', 'author': 'Player',
      'targets': <String, dynamic>{'calories': 2000, 'protein_g': 150, 'carbs_g': 200, 'fat_g': 60}};
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(_app(fake, 'en', Brightness.light, const NutritionTab()));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('log_planned_breakfast')));
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    // The Food log entry uses its own ListTile, separate from the planned foods.
    await tester.scrollUntilVisible(find.widgetWithText(ListTile, 'Areesh'), 250,
      scrollable: find.byType(Scrollable).first);
    expect(find.widgetWithText(ListTile, 'Areesh'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'meal-token'
  ..tokenValid = true
  ..plannedMealsState = <String, dynamic>{'status': 'disabled', 'can_enable': true, 'author': 'Player'}
  ..generatedMeals = <Map<String, dynamic>>[<String, dynamic>{
    'slot': 'breakfast', 'totals': <String, dynamic>{'calories': 180},
    'target_deviation': <String, dynamic>{'calories': -20, 'protein_g': 5, 'carbs_g': 0, 'fat_g': -1},
    'foods': <Map<String, dynamic>>[<String, dynamic>{
      'id': 'areesh', 'name': 'Areesh', 'arabic_name': 'جبن قريش', 'grams': 150,
      'portion_label': null, 'portion_grams': null,
      'nutrients_per_100g': <String, dynamic>{'energy_kcal': 120, 'protein_g': 30, 'carbohydrate_g': 0, 'fat_g': 0},
    }],
  }];

Widget _app(FakeMayosApi fake, String language, Brightness brightness, Widget home) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      tokens.save('meal-token');
      return ApiClient(tokens: tokens, baseUrl: 'http://test.local', adapter: fake.adapter);
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ],
  child: MaterialApp(theme: ThemeData(brightness: brightness), home: Scaffold(body: home)),
);
