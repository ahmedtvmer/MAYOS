import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_swap_copy.dart';
import 'package:mayos_mobile/src/core/display_language/food_swap_request_copy.dart';
import 'package:mayos_mobile/src/core/display_language/planned_meals_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/features/player/nutrition/today_meals.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/scroll_to_control.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets(
        '$language displays practical meals and logs foods in $brightness',
        (WidgetTester tester) async {
          tester.view.physicalSize = const Size(360, 900);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final FakeMayosApi fake = _fake();
          fake.plannedMealsState = <String, dynamic>{
            ...fake.plannedMealsState,
            'status': 'ready',
            'can_swap': true,
            'plan_version_id': 2,
            'targets': <String, dynamic>{
              'calories': 2400,
              'protein_g': 150,
              'carbs_g': 250,
              'fat_g': 70,
            },
            'day_totals': <String, dynamic>{
              'calories': 180,
              'protein_g': 45,
              'carbs_g': 0,
              'fat_g': 0,
            },
            'meals': fake.generatedMeals,
          };
          final PlannedMealsCopy copy = PlannedMealsCopy(language);
          int reloads = 0;
          await tester.pumpWidget(
            _app(
              fake,
              language,
              brightness,
              SingleChildScrollView(
                child: TodayMeals(onLogged: () => reloads++),
              ),
            ),
          );
          await tester.pumpAndSettle();
          expect(
            find.textContaining(language == 'ar' ? 'جبن قريش' : 'Areesh'),
            findsOneWidget,
          );
          expect(
            find.textContaining(copy.foodAmount(150, 'cup', 50)),
            findsOneWidget,
          );
          expect(
            find.text(
              language == 'ar'
                  ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة'
                  : 'All weights are cooked, except salad vegetables and fruit',
            ),
            findsOneWidget,
          );
          expect(find.text(copy.swapHint), findsOneWidget);
          expect(find.text(copy.foodColumn), findsOneWidget);
          expect(find.text(copy.amountColumn), findsOneWidget);
          for (final String heading in <String>['kcal', 'P', 'C', 'F']) {
            expect(find.text(heading), findsOneWidget);
          }
          expect(find.text(copy.dayTotal), findsOneWidget);
          expect(find.text(copy.target), findsOneWidget);
          final Finder targetRow = find.byKey(
            const Key('planned_meals_row_target'),
          );
          expect(
            find.descendant(of: targetRow, matching: find.text('2400')),
            findsOneWidget,
          );
          expect(
            find.descendant(of: targetRow, matching: find.text('150.0')),
            findsOneWidget,
          );
          expect(find.text('180'), findsNWidgets(3));
          expect(find.text('45.0'), findsNWidgets(3));
          expect(find.text('0.0'), findsNWidgets(6));
          final Finder numericScroller = find.descendant(
            of: find.byKey(const Key('planned_meals_numbers_food_breakfast_0')),
            matching: find.byType(Scrollable),
          );
          final ScrollPosition numericPosition = tester
              .state<ScrollableState>(numericScroller)
              .position;
          expect(numericPosition.maxScrollExtent, greaterThan(0));
          expect(numericPosition.pixels, 0);
          final Finder logButton = find.byKey(
            const Key('log_planned_breakfast'),
          );
          expect(logButton.hitTestable(), findsOneWidget);
          expect(tester.getRect(logButton).width, greaterThanOrEqualTo(44));
          expect(tester.getRect(logButton).height, greaterThanOrEqualTo(44));
          expect(
            find.byTooltip(copy.logMeal(copy.slot('breakfast'))),
            findsOneWidget,
          );
          final Finder mealFoodCell = find.byKey(
            const Key('planned_meals_food_meal_breakfast'),
          );
          expect(tester.getRect(mealFoodCell).width, closeTo(170, 2));
          expect(
            tester.getRect(mealFoodCell).contains(tester.getCenter(logButton)),
            isTrue,
          );
          await tester.tap(logButton);
          await tester.pumpAndSettle();
          expect(fake.lastPlannedMealLog, <String, dynamic>{
            'slot': 'breakfast',
            'entry_date': fake.foodLogToday,
            'plan_version_id': 2,
          });
          expect(fake.foodLogEntries[fake.foodLogToday]!.single['grams'], 150);
          expect(reloads, 1);
          expect(
            find.byKey(const Key('logged_planned_breakfast')),
            findsOneWidget,
          );
          expect(find.text('✓ ${copy.loggedLabel}'), findsOneWidget);
          expect(find.byKey(const Key('swap_breakfast_protein')), findsNothing);
          final Text mutedFood = tester.widget<Text>(
            find.textContaining(language == 'ar' ? 'جبن قريش' : 'Areesh'),
          );
          expect(
            mutedFood.style?.color,
            Theme.of(
              tester.element(
                find.textContaining(language == 'ar' ? 'جبن قريش' : 'Areesh'),
              ),
            ).colorScheme.onSurfaceVariant.withValues(alpha: 0.7),
          );
          final Finder foodName = find.textContaining(
            language == 'ar' ? 'جبن قريش' : 'Areesh',
          );
          final double fixedFoodX = tester.getTopLeft(foodName).dx;
          numericPosition.jumpTo(numericPosition.maxScrollExtent);
          await tester.pumpAndSettle();
          expect(tester.getTopLeft(foodName).dx, fixedFoodX);
          expect(
            find.textContaining(
              language == 'ar'
                  ? 'فرق الحصص العملية'
                  : 'Practical portions compared',
            ),
            findsNothing,
          );
          expect(
            Directionality.of(tester.element(find.text(copy.title))),
            language == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          );
          expect(find.text(copy.logged), findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  for (final String language in <String>['en', 'ar']) {
    testWidgets(
      '$language phone meal table saves a Food swap without horizontal scrolling',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final FakeMayosApi fake = _fake();
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': 'ready',
          'enabled': true,
          'can_swap': true,
          'plan_version_id': 2,
          'meals': fake.generatedMeals,
        };
        fake.foodSwapCandidatesState = <String, dynamic>{
          'staples': <Map<String, dynamic>>[
            <String, dynamic>{
              'food': <String, dynamic>{
                'id': 'alternative',
                'name': 'Alternative protein',
                'reviewed': true,
                'nutrients': <String, dynamic>{
                  'energy_kcal': 120,
                  'protein_g': 18.5,
                  'carbohydrate_g': 0,
                  'fat_g': 6,
                },
                'staple_roles': <String>['protein'],
                'ingredients': <dynamic>[],
              },
              'allowed': true,
              'grams': 150,
              'totals': <String, dynamic>{'calories': 180, 'protein_g': 27.75},
            },
          ],
          'search': <dynamic>[],
        };
        await tester.pumpWidget(
          _app(
            fake,
            language,
            Brightness.dark,
            SingleChildScrollView(child: TodayMeals(onLogged: () {})),
          ),
        );
        await tester.pumpAndSettle();
        final Finder swapButton = find.byKey(
          const Key('swap_breakfast_protein'),
        );
        final Finder fixedFoodCell = find.byKey(
          const Key('planned_meals_food_food_breakfast_0'),
        );
        final Finder numericScroller = find.descendant(
          of: find.byKey(const Key('planned_meals_numbers_food_breakfast_0')),
          matching: find.byType(Scrollable),
        );
        final ScrollPosition numericPosition = tester
            .state<ScrollableState>(numericScroller)
            .position;
        expect(numericPosition.pixels, 0);
        expect(numericPosition.maxScrollExtent, greaterThan(0));
        expect(swapButton.hitTestable(), findsOneWidget);
        expect(tester.getRect(swapButton).width, greaterThanOrEqualTo(44));
        expect(tester.getRect(swapButton).height, greaterThanOrEqualTo(44));
        expect(
          tester.getRect(fixedFoodCell).contains(tester.getCenter(swapButton)),
          isTrue,
        );
        expect(find.byTooltip(FoodSwapCopy(language).swap), findsOneWidget);
        await tester.tap(swapButton);
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('food_swap_options')), findsOneWidget);
        await tester.tap(find.byKey(const Key('food_swap_staple_alternative')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('save_food_swap')));
        await tester.pumpAndSettle();
        expect(
          fake.lastFoodSwapRequest,
          containsPair('food_id', 'alternative'),
        );
        expect(fake.lastFoodSwapRequest, containsPair('slot', 'breakfast'));
        expect(fake.lastFoodSwapRequest, containsPair('role', 'protein'));
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final String language in <String>['en', 'ar']) {
    testWidgets(
      '$language Coach swap request stays beside its food on a phone',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final FakeMayosApi fake = _fake();
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': 'ready',
          'author': 'Coach',
          'can_request_swap': true,
          'plan_version_id': 2,
          'meals': fake.generatedMeals,
        };
        await tester.pumpWidget(
          _app(
            fake,
            language,
            Brightness.light,
            SingleChildScrollView(child: TodayMeals(onLogged: () {})),
          ),
        );
        await tester.pumpAndSettle();
        final Finder requestButton = find.byKey(
          const Key('request_swap_breakfast_0'),
        );
        final Finder fixedFoodCell = find.byKey(
          const Key('planned_meals_food_food_breakfast_0'),
        );
        final Finder numericScroller = find.descendant(
          of: find.byKey(const Key('planned_meals_numbers_food_breakfast_0')),
          matching: find.byType(Scrollable),
        );
        final ScrollPosition numericPosition = tester
            .state<ScrollableState>(numericScroller)
            .position;
        expect(numericPosition.pixels, 0);
        expect(numericPosition.maxScrollExtent, greaterThan(0));
        expect(requestButton.hitTestable(), findsOneWidget);
        expect(tester.getRect(requestButton).width, greaterThanOrEqualTo(44));
        expect(tester.getRect(requestButton).height, greaterThanOrEqualTo(44));
        expect(
          tester
              .getRect(fixedFoodCell)
              .contains(tester.getCenter(requestButton)),
          isTrue,
        );
        expect(
          find.byTooltip(FoodSwapRequestCopy(language).request),
          findsOneWidget,
        );
        await tester.tap(requestButton);
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('send_food_swap_request')), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final String language in <String>['en', 'ar']) {
    testWidgets(
      '$language shows the day gap once and cooked weights once per Player meal',
      (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        final Map<String, String> gap = <String, String>{
          'en': 'About 120 kcal and 15 g protein under. Add a snack or a bigger portion.',
          'ar':
              'تقريبًا: نقص 120 سعرة و15 غ بروتين. أضف وجبة خفيفة أو حصة أكبر.',
        };
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': 'ready',
          'plan_version_id': 2,
          'gap_note': gap,
          'meals': <Map<String, dynamic>>[
            ...fake.generatedMeals,
            <String, dynamic>{...fake.generatedMeals.single, 'slot': 'lunch'},
          ],
        };
        await tester.pumpWidget(
          _app(
            fake,
            language,
            Brightness.light,
            SingleChildScrollView(child: TodayMeals(onLogged: () {})),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text(gap[language]!), findsOneWidget);
        expect(find.text(gap[language == 'en' ? 'ar' : 'en']!), findsNothing);
        expect(
          find.text(
            language == 'ar'
                ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة'
                : 'All weights are cooked, except salad vegetables and fruit',
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      '$language keeps Coach grams and notes without generated-meal claims',
      (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': 'ready',
          'author': 'Coach',
          'plan_version_id': 2,
          'meals': <Map<String, dynamic>>[
            <String, dynamic>{
              ...fake.generatedMeals.single,
              'note': language == 'ar' ? 'وجبة حددها المدرب' : 'Coach meal',
              'totals': <String, dynamic>{'calories': 15.6},
              'target_deviation': <String, double>{},
              'foods': <Map<String, dynamic>>[
                <String, dynamic>{
                  ...(fake.generatedMeals.single['foods']
                          as List<Map<String, dynamic>>)
                      .single,
                  'grams': 13,
                },
              ],
            },
          ],
        };
        await tester.pumpWidget(
          _app(
            fake,
            language,
            Brightness.light,
            SingleChildScrollView(child: TodayMeals(onLogged: () {})),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.textContaining(language == 'ar' ? '13 غ' : '13 g'),
          findsOneWidget,
        );
        expect(
          find.text(language == 'ar' ? 'وجبة حددها المدرب' : 'Coach meal'),
          findsOneWidget,
        );
        final Finder coachLabel = find.text(PlannedMealsCopy(language).coach);
        final Finder tableHeader = find.byKey(
          const Key('planned_meals_row_header'),
        );
        expect(coachLabel, findsOneWidget);
        expect(
          tester.getBottomLeft(coachLabel).dy,
          lessThan(tester.getTopLeft(tableHeader).dy),
        );
        expect(
          find.text(
            language == 'ar'
                ? 'كل الأوزان مطبوخة، ما عدا خضار السلطة والفاكهة'
                : 'All weights are cooked, except salad vegetables and fruit',
          ),
          findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets('unreviewed Staples show plain unavailable copy with no enable', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake()
      ..plannedMealsState = <String, dynamic>{
        'status': 'unavailable',
        'reason': 'staples',
        'enabled': true,
        'meals': <dynamic>[],
        'can_enable': true,
      };
    await tester.pumpWidget(
      _app(fake, 'en', Brightness.light, TodayMeals(onLogged: () {})),
    );
    await tester.pumpAndSettle();
    expect(find.text(const PlannedMealsCopy('en').unavailable), findsOneWidget);
    expect(find.byKey(const Key('enable_meals')), findsNothing);
    expect(find.byKey(const Key('log_planned_breakfast')), findsNothing);
  });

  testWidgets('failed log keeps the meal visible for a deliberate retry', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake()..foodWriteFails = true;
    fake.plannedMealsState = <String, dynamic>{
      ...fake.plannedMealsState,
      'status': 'ready',
      'plan_version_id': 2,
      'meals': fake.generatedMeals,
    };
    int reloads = 0;
    await tester.pumpWidget(
      _app(fake, 'en', Brightness.light, TodayMeals(onLogged: () => reloads++)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    expect(find.text('MAYOS had a problem; try again.'), findsOneWidget);
    expect(reloads, 0);
    expect(fake.foodLogEntries, isEmpty);
    fake.foodWriteFails = false;
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    expect(reloads, 1);
    expect(fake.foodLogEntries[fake.foodLogToday], hasLength(1));
  });

  testWidgets('Nutrition tab refreshes the Food log after a planned meal', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    fake.plannedMealsState = <String, dynamic>{
      ...fake.plannedMealsState,
      'status': 'ready',
      'plan_version_id': 2,
      'meals': fake.generatedMeals,
    };
    fake.nutritionState = <String, dynamic>{
      'state': 'ready',
      'author': 'Player',
      'targets': <String, dynamic>{
        'calories': 2000,
        'protein_g': 150,
        'carbs_g': 200,
        'fat_g': 60,
      },
    };
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      _app(fake, 'en', Brightness.light, const NutritionTab()),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('log_planned_breakfast')));
    await tester.tap(find.byKey(const Key('log_planned_breakfast')));
    await tester.pumpAndSettle();
    // The Food log entry uses its own ListTile, separate from the planned foods.
    await tester.scrollUntilVisible(
      find.widgetWithText(ListTile, 'Areesh'),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.widgetWithText(ListTile, 'Areesh'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'planned meals show all meals and keep logged meals in the table',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.plannedMealsState = <String, dynamic>{
        ...fake.plannedMealsState,
        'status': 'ready',
        'plan_version_id': 2,
        'meals': <Map<String, dynamic>>[
          for (final String slot in <String>['breakfast', 'lunch', 'dinner'])
            <String, dynamic>{...fake.generatedMeals.single, 'slot': slot},
        ],
      };
      await tester.pumpWidget(
        _app(
          fake,
          'en',
          Brightness.light,
          SingleChildScrollView(child: TodayMeals(onLogged: () {})),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('log_planned_breakfast')), findsOneWidget);
      expect(find.byKey(const Key('log_planned_lunch')), findsOneWidget);
      expect(find.byKey(const Key('log_planned_dinner')), findsOneWidget);
      expect(find.byKey(const Key('show_more_meals')), findsNothing);
      await tester.ensureVisible(
        find.byKey(const Key('log_planned_breakfast')),
      );
      await tester.tap(find.byKey(const Key('log_planned_breakfast')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('logged_planned_breakfast')), findsOneWidget);
      expect(find.byKey(const Key('log_planned_breakfast')), findsNothing);
      expect(fake.foodLogEntries[fake.foodLogToday], hasLength(1));
    },
  );

  testWidgets('meal table stays readable at 1.5x text scale', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(360, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final FakeMayosApi fake = _fake();
    fake.plannedMealsState = <String, dynamic>{
      ...fake.plannedMealsState,
      'status': 'ready',
      'targets': <String, dynamic>{
        'calories': 2400,
        'protein_g': 150,
        'carbs_g': 250,
        'fat_g': 70,
      },
      'day_totals': <String, dynamic>{
        'calories': 180,
        'protein_g': 45,
        'carbs_g': 0,
        'fat_g': 0,
      },
      'meals': fake.generatedMeals,
    };
    await tester.pumpWidget(
      _app(
        fake,
        'en',
        Brightness.light,
        SingleChildScrollView(child: TodayMeals(onLogged: () {})),
        textScaler: TextScaler.linear(1.5),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('planned_meals_row_header')), findsOneWidget);
    expect(
      find.byKey(const Key('planned_meals_row_day_total')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('planned_meals_row_target')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'Meals switch under Targets enables meals and refreshes Today on return',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake()
        ..nutritionState = <String, dynamic>{
          'state': 'ready',
          'goal': 'maintain',
          'targets': <String, dynamic>{
            'calories': 2000,
            'protein_g': 150,
            'carbs_g': 200,
            'fat_g': 60,
          },
        };
      await tester.pumpWidget(
        _app(fake, 'en', Brightness.light, const NutritionTab()),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('enable_meals')), findsNothing);
      await tester.tap(find.byKey(const Key('nutrition_targets')));
      await tester.pumpAndSettle();
      await scrollToControl(tester, find.byKey(const Key('meals_switch')));
      await tester.tap(find.byKey(const Key('meals_switch')));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      await scrollToControl(
        tester,
        find.byKey(const Key('log_planned_breakfast')),
      );
      expect(find.byKey(const Key('log_planned_breakfast')), findsOneWidget);
      await tester.tap(find.byKey(const Key('log_planned_breakfast')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('nutrition_targets')));
      await tester.pumpAndSettle();
      await scrollToControl(tester, find.byKey(const Key('meals_switch')));
      await tester.tap(find.byKey(const Key('meals_switch')));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('log_planned_breakfast')), findsNothing);
      await scrollToControl(tester, find.widgetWithText(ListTile, 'Areesh'));
      expect(find.widgetWithText(ListTile, 'Areesh'), findsOneWidget);
      expect(fake.foodLogEntries[fake.foodLogToday], hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('past-day planned meals use a read-only snapshot', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake()
      ..nutritionState = <String, dynamic>{
        'state': 'ready',
        'goal': 'maintain',
        'targets': <String, dynamic>{
          'calories': 2000,
          'protein_g': 150,
          'carbs_g': 200,
          'fat_g': 60,
        },
      };
    fake.foodLogPlannedMeals['2026-11-04'] = <String, dynamic>{
      'status': 'ready',
      'date': '2026-11-04',
      'author': 'Player',
      'day_type': 'rest_day',
      'can_swap': true,
      'can_request_swap': true,
      'day_totals': <String, dynamic>{
        'calories': 520,
        'protein_g': 45,
        'carbs_g': 0,
        'fat_g': 0,
      },
      'targets': <String, dynamic>{
        'calories': 2000,
        'protein_g': 100,
        'carbs_g': 250,
        'fat_g': 67,
      },
      'meals': fake.generatedMeals,
    };
    await tester.pumpWidget(
      _app(fake, 'en', Brightness.light, const NutritionTab()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Previous day'));
    await tester.pumpAndSettle();
    expect(find.text('Areesh'), findsOneWidget);
    expect(find.text('Food'), findsOneWidget);
    expect(find.text('Amount'), findsOneWidget);
    expect(
      find.byKey(const Key('planned_meals_row_food_breakfast_0')),
      findsOneWidget,
    );
    final Finder dayTotalRow = find.byKey(
      const Key('planned_meals_row_day_total'),
    );
    final Finder targetRow = find.byKey(const Key('planned_meals_row_target'));
    expect(
      find.descendant(of: dayTotalRow, matching: find.text('520')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: targetRow, matching: find.text('2000')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('log_planned_breakfast')), findsNothing);
    expect(find.byKey(const Key('swap_breakfast_protein')), findsNothing);
    expect(find.byKey(const Key('request_swap_breakfast_0')), findsNothing);
    expect(find.text(PlannedMealsCopy('en').swapHint), findsNothing);
    expect(fake.lastPlannedMealLog, isNull);
    expect(tester.takeException(), isNull);
  });
}

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'meal-token'
  ..tokenValid = true
  ..plannedMealsState = <String, dynamic>{
    'status': 'disabled',
    'can_enable': true,
    'author': 'Player',
  }
  ..generatedMeals = <Map<String, dynamic>>[
    <String, dynamic>{
      'slot': 'breakfast',
      'totals': <String, dynamic>{
        'calories': 180,
        'protein_g': 45,
        'carbs_g': 0,
        'fat_g': 0,
      },
      'target_deviation': <String, dynamic>{
        'calories': -20,
        'protein_g': 5,
        'carbs_g': 0,
        'fat_g': -1,
      },
      'foods': <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'areesh',
          'name': 'Areesh',
          'arabic_name': 'جبن قريش',
          'grams': 150,
          'portion_label': 'cup',
          'portion_grams': 50,
          'role': 'protein',
          'macros': <String, dynamic>{
            'calories': 180,
            'protein_g': 45,
            'carbs_g': 0,
            'fat_g': 0,
          },
          'nutrients_per_100g': <String, dynamic>{
            'energy_kcal': 120,
            'protein_g': 30,
            'carbohydrate_g': 0,
            'fat_g': 0,
          },
        },
      ],
    },
  ];

Widget _app(
  FakeMayosApi fake,
  String language,
  Brightness brightness,
  Widget home, {
  TextScaler? textScaler,
}) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      tokens.save('meal-token');
      return ApiClient(
        tokens: tokens,
        baseUrl: 'http://test.local',
        adapter: fake.adapter,
      );
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ],
  child: MaterialApp(
    theme: ThemeData(brightness: brightness),
    builder: textScaler == null
        ? null
        : (BuildContext context, Widget? child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: textScaler),
            child: child!,
          ),
    home: Scaffold(body: home),
  ),
);
