import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/meal_setup_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_amount_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_restriction_badge.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_search_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/meal_setup_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets('$language saves Meal setup and specific dislikes in $brightness', (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        final MealSetupCopy copy = MealSetupCopy(language);
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(_app(fake, language, brightness, const MealSetupEntry()));
        await tester.tap(find.byKey(const Key('meal_setup_entry')));
        await tester.pumpAndSettle();
        expect(Directionality.of(tester.element(find.byType(ListView))),
          language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
        await tester.tap(find.byKey(const Key('meal_count_5')));
        expect(find.text(copy.slotLayout(5)), findsOneWidget);
        await tester.tap(find.byKey(const Key('meal_training_time')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(copy.timeLabel('afternoon')).last);
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const Key('allergy_eggs')));
        await tester.tap(find.byKey(const Key('allergy_eggs')));
        await tester.ensureVisible(find.byKey(const Key('meal_vegetarian')));
        await tester.tap(find.byKey(const Key('meal_vegetarian')));
        await tester.ensureVisible(find.byKey(const Key('add_disliked_food')));
        await tester.tap(find.byKey(const Key('add_disliked_food')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(language == 'ar' ? 'بيضة' : 'Egg'));
        await tester.pumpAndSettle();
        expect(find.byType(MealSetupScreen), findsOneWidget);
        await tester.ensureVisible(find.byKey(const Key('save_meal_setup')));
        await tester.tap(find.byKey(const Key('save_meal_setup')));
        await tester.pumpAndSettle();
        expect(find.byType(MealSetupScreen), findsNothing);
        await tester.tap(find.byKey(const Key('meal_setup_entry')));
        await tester.pumpAndSettle();
        expect(tester.widget<ChoiceChip>(find.byKey(const Key('meal_count_5'))).selected, isTrue);
        expect(find.text(copy.timeLabel('afternoon')), findsOneWidget);
        expect(tester.widget<FilterChip>(find.byKey(const Key('allergy_eggs'))).selected, isTrue);
        expect(tester.widget<SwitchListTile>(find.byKey(const Key('meal_vegetarian'))).value, isTrue);
        expect(find.text(language == 'ar' ? 'بيضة' : 'Egg'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });

      testWidgets('$language search keeps foods with reason badges in $brightness', (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        final MealSetupCopy copy = MealSetupCopy(language);
        fake.foodSearchResults.single['restriction_reasons'] = <String>['eggs', 'vegetarian', 'disliked'];
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(_app(fake, language, brightness, const FoodSearchScreen(
          day: '2026-11-05', kcalLeft: 2000, mealLabel: 'breakfast')));
        await tester.pumpAndSettle();
        expect(find.byType(FoodRestrictionBadge), findsOneWidget);
        expect(find.text('${copy.restricted}: ${<String>['eggs', 'vegetarian', 'disliked'].map(copy.reason).join(', ')}'), findsOneWidget);
        await tester.tap(find.text(language == 'ar' ? 'بيضة' : 'Egg'));
        await tester.pumpAndSettle();
        expect(find.byType(FoodAmountScreen), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }

  testWidgets('failed Meal setup save keeps edits for retry', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..mealSetupSaveFails = true;
    await tester.pumpWidget(_app(fake, 'en', Brightness.light, const MealSetupEntry()));
    await tester.tap(find.byKey(const Key('meal_setup_entry')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meal_count_4')));
    await tester.ensureVisible(find.byKey(const Key('save_meal_setup')));
    await tester.tap(find.byKey(const Key('save_meal_setup')));
    await tester.pumpAndSettle();
    expect(find.byType(MealSetupScreen), findsOneWidget);
    expect(find.text('Could not save Meal setup.'), findsOneWidget);
    fake.mealSetupSaveFails = false;
    await tester.ensureVisible(find.byKey(const Key('save_meal_setup')));
    await tester.tap(find.byKey(const Key('save_meal_setup')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meal_setup_entry')));
    await tester.pumpAndSettle();
    expect(tester.widget<ChoiceChip>(find.byKey(const Key('meal_count_4'))).selected, isTrue);
  });
}

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'meal-token'
  ..tokenValid = true
  ..foodSearchResults = <Map<String, dynamic>>[<String, dynamic>{
    'id': 'egg', 'name': 'Egg', 'arabic_name': 'بيضة', 'reviewed': true,
    'nutrients': <String, dynamic>{'energy_kcal': 100, 'protein_g': 10, 'carbohydrate_g': 0, 'fat_g': 5},
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
