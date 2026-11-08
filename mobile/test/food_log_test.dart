import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_log_copy.dart';
import 'package:mayos_mobile/src/core/food_log_models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_amount_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_search_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/personal_food_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/quick_add_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      for (final bool logged in <bool>[false, true]) {
        testWidgets('$language $brightness day layout at 360 dp with logged=$logged (#659)', (WidgetTester tester) async {
          tester.view.physicalSize = const Size(360, 800);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final FakeMayosApi fake = _fake();
          if (logged) fake.foodLogEntries[fake.foodLogToday] = <Map<String, dynamic>>[_entry('breakfast')];
          final FoodLogCopy copy = FoodLogCopy(language);
          await tester.pumpWidget(_app(fake, language: language, brightness: brightness));
          await tester.pumpAndSettle();
          expect(find.text(logged ? '1900' : '2000'), findsOneWidget);
          expect(find.text(copy.leftOf(2000)), findsOneWidget);
          for (final String macro in <String>[copy.protein, copy.carbs, copy.fat]) {
            expect(find.text(copy.macroLeft(macro)), findsOneWidget);
          }
          expect(find.text(copy.macrosTitle), findsNothing);
          expect(find.text(copy.adjust), findsNothing);
          expect(find.byKey(const Key('food_log_entry_point')), findsOneWidget);
          expect(find.widgetWithText(OutlinedButton, copy.quickAdd), findsOneWidget);
          if (logged) {
            expect(find.text(language == 'ar' ? 'بيضة' : 'Egg'), findsOneWidget);
            expect(find.text(copy.startDay), findsNothing);
          } else {
            expect(find.text(copy.startDay), findsOneWidget);
            await tester.tap(find.byKey(const Key('empty_day_search')));
            await tester.pumpAndSettle();
            expect(find.byType(FoodSearchScreen), findsOneWidget);
            await tester.pageBack();
            await tester.pumpAndSettle();
            await tester.tap(find.widgetWithText(TextButton, copy.quickAdd));
            await tester.pumpAndSettle();
            expect(find.byType(QuickAddScreen), findsOneWidget);
            await tester.pageBack();
            await tester.pumpAndSettle();
          }
          await tester.scrollUntilVisible(find.text(copy.howTodayWent), 150,
            scrollable: find.byType(Scrollable).first);
          expect(find.widgetWithText(ChoiceChip, copy.onTarget), findsOneWidget);
          await tester.scrollUntilVisible(find.text(copy.lastSevenDays), 150,
            scrollable: find.byType(Scrollable).first);
          expect(find.textContaining(copy.waterLog), findsOneWidget);
          await tester.scrollUntilVisible(find.byKey(const Key('nutrition_targets')), 150,
            scrollable: find.byType(Scrollable).first);
          expect(find.text(copy.targetsTitle), findsOneWidget);
          expect(tester.widgetList<Directionality>(find.byType(Directionality))
            .map((Directionality direction) => direction.textDirection),
            contains(language == 'ar' ? TextDirection.rtl : TextDirection.ltr));
          await tester.tap(find.byKey(const Key('nutrition_targets')));
          await tester.pumpAndSettle();
          expect(find.text(copy.goal('maintain')), findsOneWidget);
          expect(find.text(copy.adjust), findsOneWidget);
          await tester.scrollUntilVisible(find.text(copy.macrosTitle), 150,
            scrollable: find.byType(Scrollable).first);
          expect(find.text(copy.protein), findsOneWidget);
          expect(find.text(copy.fat), findsOneWidget);
          expect(tester.takeException(), isNull);
        });
      }
      testWidgets('$language Quick add keeps optional Macros blank in $brightness', (WidgetTester tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final FakeMayosApi fake = _fake();
        final FoodLogCopy copy = FoodLogCopy(language);
        await tester.pumpWidget(_app(fake, language: language, brightness: brightness));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('copy_food_meal')), findsNothing);
        await tester.tap(find.widgetWithText(OutlinedButton, copy.quickAdd));
        await tester.pumpAndSettle();
        expect(find.byType(QuickAddScreen), findsOneWidget);
        expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, copy.add)).onPressed, isNull);
        await tester.enterText(find.byKey(const Key('food_energy_kcal')), language == 'ar' ? '٣٠٠' : '300');
        await tester.enterText(find.byKey(const Key('food_fat_g')), '0');
        await tester.ensureVisible(find.widgetWithText(FilledButton, copy.add));
        await tester.tap(find.widgetWithText(FilledButton, copy.add));
        await tester.pumpAndSettle();
        expect(find.text('1700'), findsOneWidget);
        expect(find.textContaining('${copy.protein}:  ·'), findsOneWidget);
        final Map<String, dynamic> nutrients = fake.foodLogEntries[fake.foodLogToday]!.single['nutrients'] as Map<String, dynamic>;
        expect(nutrients['protein_g'], isNull);
        expect(nutrients['carbohydrate_g'], isNull);
        expect(nutrients['fat_g'], 0);
        await tester.ensureVisible(find.widgetWithText(ListTile, copy.quickAdd));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(ListTile, copy.quickAdd));
        await tester.pumpAndSettle();
        expect(tester.widget<TextField>(find.byKey(const Key('food_protein_g'))).controller!.text, isEmpty);
        await tester.enterText(find.byKey(const Key('food_energy_kcal')), '400');
        await tester.enterText(find.byKey(const Key('food_protein_g')), '20');
        await tester.tap(find.byType(DropdownButtonFormField<String>));
        await tester.pumpAndSettle();
        await tester.tap(find.text(copy.mealLabel('snack')).last);
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.widgetWithText(FilledButton, copy.save));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, copy.save));
        await tester.pumpAndSettle();
        await tester.dragUntilVisible(find.text('1600'), find.byType(ListView), const Offset(0, 200));
        expect(find.text('1600'), findsOneWidget);
        expect(fake.foodLogEntries[fake.foodLogToday]!.single['meal_label'], 'snack');
        expect(tester.takeException(), isNull);
      });
    }
    for (final String basis in <String>['100g', 'portion']) {
      testWidgets('$language creates a Personal food per $basis and logs it', (WidgetTester tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final FakeMayosApi fake = _fake();
        final FoodLogCopy copy = FoodLogCopy(language);
        await tester.pumpWidget(_app(fake, language: language,
          brightness: basis == 'portion' ? Brightness.dark : Brightness.light));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('food_log_entry_point')));
        await tester.pumpAndSettle();
        expect(find.widgetWithText(TextButton, copy.quickAdd), findsOneWidget);
        await tester.enterText(find.byType(TextField), 'My bowl');
        await tester.pumpAndSettle(const Duration(milliseconds: 300));
        expect(find.text(copy.noResults), findsOneWidget);
        await tester.tap(find.byKey(const Key('create_personal_food')));
        await tester.pumpAndSettle();
        expect(find.byType(PersonalFoodScreen), findsOneWidget);
        expect(tester.widget<TextField>(find.byKey(const Key('personal_food_name'))).controller!.text, 'My bowl');
        if (basis == 'portion') {
          await tester.tap(find.byType(DropdownButtonFormField<String>));
          await tester.pumpAndSettle();
          await tester.tap(find.text(copy.portion).last);
          await tester.pumpAndSettle();
          await tester.enterText(find.byKey(const Key('personal_portion_name')), 'bowl');
          await tester.enterText(find.byKey(const Key('personal_portion_grams')), '200');
        }
        for (final (String key, String value) in <(String, String)>[
          ('energy_kcal', '300'), ('protein_g', '30'), ('carbohydrate_g', '20'), ('fat_g', '10'),
        ]) {
          await tester.ensureVisible(find.byKey(Key('food_$key')));
          await tester.enterText(find.byKey(Key('food_$key')), value);
        }
        await tester.ensureVisible(find.widgetWithText(FilledButton, copy.save));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, copy.save));
        await tester.pumpAndSettle();
        expect(find.byType(FoodAmountScreen), findsOneWidget);
        expect(find.text('My bowl'), findsOneWidget);
        await tester.ensureVisible(find.widgetWithText(FilledButton, copy.add));
        await tester.tap(find.widgetWithText(FilledButton, copy.add));
        await tester.pumpAndSettle();
        expect(find.text(basis == 'portion' ? '1850' : '1700'), findsOneWidget);
        expect(fake.foodLogEntries[fake.foodLogToday]!.single['kind'], 'personal_food');
        await tester.tap(find.byKey(const Key('food_log_entry_point')));
        await tester.pumpAndSettle();
        expect(find.text('My bowl'), findsOneWidget);
        await tester.ensureVisible(find.byKey(const Key('create_personal_food')));
        expect(find.byKey(const Key('create_personal_food')), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }

  for (final String entryPoint in <String>['day', 'search']) {
    testWidgets('copy a meal from $entryPoint sends one request while busy', (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.foodLogEntries['2026-11-04'] = <Map<String, dynamic>>[
        _entry('one'), _entry('two'), <String, dynamic>{..._entry('other'), 'meal_label': 'lunch'},
      ];
      final Completer<void> pending = Completer<void>();
      addTearDown(() { if (!pending.isCompleted) pending.complete(); });
      fake.adapter.beforeRespond = (request) async {
        if (request.path == '/nutrition/food-log/copy-meal') await pending.future;
      };
      await tester.pumpWidget(_app(fake));
      await tester.pumpAndSettle();
      if (entryPoint == 'search') {
        await tester.tap(find.byKey(const Key('food_log_entry_point')));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.byKey(const Key('copy_food_meal')));
      await tester.pumpAndSettle();
      expect(find.text('Breakfast'), findsOneWidget);
      expect(find.text('Lunch'), findsOneWidget);
      expect(find.text('Dinner'), findsNothing);
      await tester.tap(find.text('Breakfast'));
      await tester.pumpAndSettle();
      expect(tester.widget<TextButton>(find.byKey(const Key('copy_food_meal'))).onPressed, isNull);
      expect(tester.widget<ListTile>(find.widgetWithText(ListTile, 'Breakfast')).onTap, isNull);
      await tester.tap(find.text('Breakfast'));
      await tester.pump();
      expect(fake.adapter.requests.where((request) => request.path == '/nutrition/food-log/copy-meal'), hasLength(1));
      pending.complete();
      await tester.pumpAndSettle();
      expect(find.byType(FoodSearchScreen), findsNothing);
      expect(find.text('1800'), findsOneWidget);
      expect(fake.foodLogEntries[fake.foodLogToday], hasLength(2));
      expect(fake.foodLogEntries['2026-11-04'], hasLength(3));
    });
  }

  testWidgets('Quick add from search keeps input after failure and prevents duplicate saves', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..foodWriteFails = true;
    await tester.pumpWidget(_app(fake));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Quick add'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('food_energy_kcal')), '250');
    await tester.ensureVisible(find.widgetWithText(FilledButton, 'Add'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Add'));
    await tester.pumpAndSettle();
    expect(find.byType(QuickAddScreen), findsOneWidget);
    expect(find.text('Could not save food.'), findsOneWidget);
    expect(tester.widget<TextField>(find.byKey(const Key('food_energy_kcal'))).controller!.text, '250');
    fake.foodWriteFails = false;
    final Completer<void> pending = Completer<void>();
    addTearDown(() { if (!pending.isCompleted) pending.complete(); });
    fake.adapter.beforeRespond = (request) async {
      if (request.path == '/nutrition/food-log/quick-add') await pending.future;
    };
    await tester.tap(find.widgetWithText(FilledButton, 'Add'));
    await tester.pump();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Saving…')).onPressed, isNull);
    pending.complete();
    await tester.pumpAndSettle();
    expect(find.byType(FoodSearchScreen), findsNothing);
    expect(find.text('1750'), findsOneWidget);
    expect(fake.foodLogEntries[fake.foodLogToday], hasLength(1));
  });

  testWidgets(
    'search, amount preview, local portions and meal add update the day',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      await tester.pumpWidget(_app(fake));
      await tester.pumpAndSettle();
      expect(find.text('2000'), findsOneWidget);
      expect(find.text('Protein left'), findsOneWidget);
      await tester.tap(find.byType(TextField));
      await tester.pumpAndSettle();
      expect(find.byType(FoodSearchScreen), findsOneWidget);
      expect(find.text('Recent and frequent foods'), findsOneWidget);
      await tester.enterText(find.byType(TextField), 'Egg');
      await tester.pumpAndSettle(const Duration(milliseconds: 300));
      expect(find.text('Staple'), findsOneWidget);
      expect(find.text('100 kcal / 100 g'), findsOneWidget);
      expect(find.textContaining('20 g protein per 100 g'), findsOneWidget);
      await tester.tap(_resultNamed('Egg'));
      await tester.pumpAndSettle();
      expect(find.text('1900 kcal left after adding'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '200');
      await tester.pump();
      expect(find.text('1800 kcal left after adding'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('large egg (50.0 g)').last);
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '4.00',
      );
      await tester.enterText(find.byType(TextField), '2');
      await tester.pump();
      expect(find.text('1900 kcal left after adding'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Lunch').last);
      await tester.pumpAndSettle();
      await _scrollAmountTo(tester, find.widgetWithText(FilledButton, 'Add'));
      await tester.tap(find.widgetWithText(FilledButton, 'Add'));
      await tester.pumpAndSettle();
      expect(find.byType(FoodSearchScreen), findsNothing);
      expect(find.text('1900'), findsOneWidget);
      expect(find.text('kcal left of 2000'), findsOneWidget);
      expect(find.text('Macros'), findsNothing);
      expect(find.textContaining('2 large egg · Lunch'), findsOneWidget);
      expect(fake.foodLogEntries[fake.foodLogToday]!.single['grams'], 100);
      expect(
        fake.foodLogEntries[fake.foodLogToday]!.single['meal_label'],
        'lunch',
      );
      await tester.ensureVisible(find.text('On target'));
      await tester.tap(find.text('On target'));
      await tester.pumpAndSettle();
      expect(fake.nutritionAdherenceValues, <String>['on_target']);
    },
  );

  testWidgets(
    'empty search and no matches are readable and errors can be retried',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake()
        ..foodSearchResults = <Map<String, dynamic>>[];
      await tester.pumpWidget(
        _app(
          fake,
          home: const FoodSearchScreen(
            day: '2026-11-05',
            kcalLeft: 2000,
            mealLabel: 'dinner',
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Add to Dinner'), findsOneWidget);
      expect(
        find.text('Search for a food to start your Food log.'),
        findsOneWidget,
      );
      expect(find.byKey(const Key('create_personal_food')), findsOneWidget);
      expect(find.byKey(const Key('copy_food_meal')), findsNothing);
      fake.foodSearchFails = true;
      await tester.enterText(find.byType(TextField), 'unknown');
      await tester.pumpAndSettle(const Duration(milliseconds: 300));
      expect(find.text('Retry'), findsOneWidget);
      fake.foodSearchFails = false;
      await tester.tap(find.text('Retry'));
      await tester.pumpAndSettle();
      expect(find.text('No matching foods.'), findsOneWidget);
    },
  );

  testWidgets(
    'day totals, ordered rows and navigation keep older days read-only',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.foodLogEntries['2026-11-05'] = <Map<String, dynamic>>[
        _entry('late', name: 'Late egg', time: '20:00'),
        _entry('early', name: 'Early egg', time: '08:10'),
      ];
      fake.foodLogEntries['2026-11-03'] = <Map<String, dynamic>>[_entry('old')];
      await tester.pumpWidget(_app(fake));
      await tester.pumpAndSettle();
      expect(find.text('1800'), findsOneWidget);
      expect(find.text('Protein left'), findsOneWidget);
      expect(find.text('100 g'), findsOneWidget);
      expect(
        tester.getTopLeft(find.text('Early egg')).dy,
        lessThan(tester.getTopLeft(find.text('Late egg')).dy),
      );
      expect(
        _nextDayButton(tester).onPressed,
        isNull,
      );
      await tester.tap(find.byTooltip('Previous day'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Yesterday,'), findsOneWidget);
      expect(find.text('No food logged for this day.'), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);
      await tester.tap(find.byTooltip('Previous day'));
      await tester.pumpAndSettle();
      expect(find.text('This day is read-only'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.byType(PopupMenuButton<String>), findsNothing);
      await tester.tap(find.byTooltip('Next day'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Next day'));
      await tester.pumpAndSettle();
      expect(find.text('1800'), findsOneWidget);
      expect(
        _nextDayButton(tester).onPressed,
        isNull,
      );
    },
  );

  testWidgets('resume refreshes today while Nutrition stays in an IndexedStack', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    DateTime now = DateTime(2026, 11, 5, 23, 50);
    final ValueNotifier<int> tab = ValueNotifier<int>(0);
    addTearDown(tab.dispose);
    fake.foodLogEntries['2026-11-05'] = <Map<String, dynamic>>[
      _entry('old', name: 'November 5 breakfast'),
    ];
    fake.foodLogEntries['2026-11-06'] = <Map<String, dynamic>>[
      _entry('new', name: 'November 6 breakfast'),
    ];
    await tester.pumpWidget(_app(fake, now: () => now,
      home: ValueListenableBuilder<int>(
        valueListenable: tab,
        builder: (_, int index, __) => IndexedStack(index: index,
          children: const <Widget>[NutritionTab(), Text('Other tab')]),
      )));
    await tester.pumpAndSettle();
    expect(find.text('November 5 breakfast'), findsOneWidget);
    tab.value = 1;
    await tester.pumpAndSettle();
    _pauseApp(tester);
    fake.foodLogToday = '2026-11-06';
    now = DateTime(2026, 11, 6, 8);
    _resumeApp(tester);
    await tester.pumpAndSettle();
    tab.value = 0;
    await tester.pumpAndSettle();
    expect(find.text('November 5 breakfast'), findsNothing);
    expect(find.text('November 6 breakfast'), findsOneWidget);
    _expectToday(tester, DateTime(2026, 11, 6));
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pumpAndSettle();
    expect(tester.widget<FoodSearchScreen>(find.byType(FoodSearchScreen)).day,
      '2026-11-06');
  });

  testWidgets('foreground midnight refreshes today before opening food search', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    // The Account's timezone can be a day ahead of the device's timezone.
    DateTime now = DateTime(2026, 11, 4, 23, 59);
    await tester.pumpWidget(_app(fake, now: () => now));
    await tester.pumpAndSettle();
    final Completer<void> refresh = Completer<void>();
    addTearDown(() { if (!refresh.isCompleted) refresh.complete(); });
    fake.adapter.beforeRespond = (request) async {
      if (request.path == '/nutrition/food-log') await refresh.future;
    };
    fake.foodLogToday = '2026-11-06';
    now = DateTime(2026, 11, 5, 0, 1);
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pump();
    expect(find.byType(FoodSearchScreen), findsNothing);
    refresh.complete();
    await tester.pumpAndSettle();
    expect(tester.widget<FoodSearchScreen>(find.byType(FoodSearchScreen)).day,
      '2026-11-06');
    final request = fake.adapter.requests.lastWhere(
      (request) => request.path == '/nutrition/food-log');
    expect(request.query['day'], isNull);
  });

  testWidgets('Quick add asks the server for the day even when the device date has not changed', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    await tester.pumpWidget(_app(fake));
    await tester.pumpAndSettle();
    fake.foodLogToday = '2026-11-06';
    await tester.tap(find.widgetWithText(OutlinedButton, 'Quick add'));
    await tester.pumpAndSettle();
    expect(tester.widget<QuickAddScreen>(find.byType(QuickAddScreen)).day, '2026-11-06');
  });

  testWidgets('the meal picker reads yesterday fresh after the day changes', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    fake.foodLogEntries['2026-11-04'] = <Map<String, dynamic>>[_entry('one')];
    await tester.pumpWidget(_app(fake));
    await tester.pumpAndSettle();
    fake.foodLogEntries['2026-11-04'] = <Map<String, dynamic>>[
      <String, dynamic>{..._entry('other'), 'meal_label': 'dinner'},
    ];
    await tester.tap(find.byKey(const Key('copy_food_meal')));
    await tester.pumpAndSettle();
    expect(find.text('Dinner'), findsOneWidget);
    expect(find.text('Breakfast'), findsNothing);
  });

  testWidgets('a failed midnight refresh shows Retry without opening search', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    DateTime now = DateTime(2026, 11, 5, 23, 59);
    await tester.pumpWidget(_app(fake, now: () => now));
    await tester.pumpAndSettle();
    fake.foodLogToday = '2026-11-06';
    fake.foodLogFails = true;
    now = DateTime(2026, 11, 6, 0, 1);
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pumpAndSettle();
    expect(find.byType(FoodSearchScreen), findsNothing);
    expect(find.text('Retry'), findsOneWidget);
    fake.foodLogFails = false;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    _expectToday(tester, DateTime(2026, 11, 6));
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pumpAndSettle();
    expect(tester.widget<FoodSearchScreen>(find.byType(FoodSearchScreen)).day,
      '2026-11-06');
  });

  testWidgets('resume preserves the older day the Player selected', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    DateTime now = DateTime(2026, 11, 5, 23, 50);
    fake.foodLogEntries['2026-11-04'] = <Map<String, dynamic>>[
      _entry('older', name: 'November 4 breakfast'),
    ];
    fake.foodLogEntries['2026-11-06'] = <Map<String, dynamic>>[
      _entry('today', name: 'November 6 breakfast'),
    ];
    await tester.pumpWidget(_app(fake, now: () => now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Previous day'));
    await tester.pumpAndSettle();
    expect(find.text('November 4 breakfast'), findsOneWidget);
    _pauseApp(tester);
    fake.foodLogToday = '2026-11-06';
    now = DateTime(2026, 11, 6, 8);
    _resumeApp(tester);
    await tester.pumpAndSettle();
    expect(find.text('November 4 breakfast'), findsOneWidget);
    expect(find.text('November 6 breakfast'), findsNothing);
    expect(find.textContaining('Today,'), findsNothing);
    expect(find.text('This day is read-only'), findsOneWidget);
    final request = fake.adapter.requests.lastWhere(
      (request) => request.path == '/nutrition/food-log');
    expect(request.query['day'], '2026-11-04');
  });

  testWidgets('Next day back to today resumes following the server day', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    DateTime now = DateTime(2026, 11, 5, 23, 50);
    fake.foodLogEntries['2026-11-06'] = <Map<String, dynamic>>[
      _entry('new', name: 'November 6 breakfast'),
    ];
    await tester.pumpWidget(_app(fake, now: () => now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Previous day'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Next day'));
    await tester.pumpAndSettle();
    _expectToday(tester, DateTime(2026, 11, 5));
    _pauseApp(tester);
    fake.foodLogToday = '2026-11-06';
    now = DateTime(2026, 11, 6, 8);
    _resumeApp(tester);
    await tester.pumpAndSettle();
    expect(find.text('November 6 breakfast'), findsOneWidget);
    _expectToday(tester, DateTime(2026, 11, 6));
    await tester.tap(find.byKey(const Key('food_log_entry_point')));
    await tester.pumpAndSettle();
    expect(tester.widget<FoodSearchScreen>(find.byType(FoodSearchScreen)).day,
      '2026-11-06');
  });

  testWidgets(
    'editing uses snapshot density and deleting the last entry keeps the day layout',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.foodLogEntries[fake.foodLogToday] = <Map<String, dynamic>>[
        _entry('entry'),
      ];
      await tester.pumpWidget(_app(fake));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Egg'));
      await tester.pumpAndSettle();
      expect(find.text('1900 kcal left after saving'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '50');
      await tester.pump();
      expect(find.text('1950 kcal left after saving'), findsOneWidget);
      await _scrollAmountTo(tester, find.widgetWithText(FilledButton, 'Save'));
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pumpAndSettle();
      expect(find.text('1950'), findsOneWidget);
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
      await tester.pumpAndSettle();
      expect(fake.foodLogEntries[fake.foodLogToday], isEmpty);
      expect(find.text('Protein left'), findsOneWidget);
      expect(find.text('Start your day with your first meal.'), findsOneWidget);
      expect(find.text('2000'), findsOneWidget);
    },
  );

  testWidgets(
    'invalid amounts disable save and a failed write keeps the entered amount',
    (WidgetTester tester) async {
      final FakeMayosApi fake = _fake()..foodWriteFails = true;
      await tester.pumpWidget(
        _app(
          fake,
          home: FoodAmountScreen(
            food: FoodLibraryItem.fromJson(_food()),
            day: fake.foodLogToday,
            kcalLeft: 2000,
            mealLabel: 'breakfast',
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '0');
      await tester.pump();
      await _scrollAmountTo(tester, find.widgetWithText(FilledButton, 'Add'));
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Add'))
            .onPressed,
        isNull,
      );
      await _scrollAmountTo(tester, find.byType(TextField), delta: -200);
      await tester.enterText(find.byType(TextField), '150');
      await tester.pump();
      await _scrollAmountTo(tester, find.widgetWithText(FilledButton, 'Add'));
      expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Add'))
        .onPressed, isNotNull);
      await tester.tap(find.widgetWithText(FilledButton, 'Add'));
      await tester.pumpAndSettle();
      expect(find.byType(FoodAmountScreen), findsOneWidget);
      await _scrollAmountTo(tester, find.byType(TextField), delta: -200);
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '150',
      );
      expect(find.text('1850 kcal left after adding'), findsOneWidget);
      expect(fake.foodLogEntries, isEmpty);
    },
  );

  testWidgets('a slow previous search cannot replace the latest results', (
    WidgetTester tester,
  ) async {
    final FakeMayosApi fake = _fake();
    final Completer<void> delayed = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.path == '/nutrition/foods' && request.query['q'] == 'Egg')
        await delayed.future;
    };
    await tester.pumpWidget(
      _app(
        fake,
        home: const FoodSearchScreen(
          day: '2026-11-05',
          kcalLeft: 2000,
          mealLabel: 'dinner',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Egg');
    await tester.pump(const Duration(milliseconds: 300));
    await tester.enterText(find.byType(TextField), 'no match');
    await tester.pumpAndSettle(const Duration(milliseconds: 300));
    expect(find.text('No matching foods.'), findsOneWidget);
    delayed.complete();
    await tester.pumpAndSettle();
    expect(find.text('No matching foods.'), findsOneWidget);
    expect(find.text('Egg'), findsNothing);
  });

  for (final String language in <String>['en', 'ar']) {
    for (final int burned in <int>[0, 301]) {
      testWidgets('$language logged day shows Cardio burned $burned only when positive', (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        fake.nutritionState['cardio_burned_kcal'] = burned;
        fake.foodLogEntries[fake.foodLogToday] = <Map<String, dynamic>>[_entry('entry')];
        final FoodLogCopy copy = FoodLogCopy(language);
        final String cardioLine = language == 'ar'
            ? 'السعرات المحروقة بالكارديو ~$burned سعرة'
            : 'Cardio burned ~$burned kcal';
        await tester.pumpWidget(_app(fake, language: language));
        await tester.pumpAndSettle();
        expect(find.text('1900'), findsOneWidget);
        expect(find.text(cardioLine), burned > 0 ? findsOneWidget : findsNothing);
        await tester.tap(find.byTooltip(copy.previousDay));
        await tester.pumpAndSettle();
        expect(find.text(cardioLine), findsNothing);
      });
    }
    for (final Brightness brightness in Brightness.values) {
      testWidgets(
        '$language food log, search and amount fit a phone in $brightness',
        (WidgetTester tester) async {
          tester.view.physicalSize = const Size(390, 844);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final FakeMayosApi fake = _fake();
          fake.foodLogEntries[fake.foodLogToday] = <Map<String, dynamic>>[
            _entry('entry'),
          ];
          final FoodLogCopy copy = FoodLogCopy(language);
          await tester.pumpWidget(
            _app(fake, language: language, brightness: brightness),
          );
          await tester.pumpAndSettle();
          expect(find.text('1900'), findsOneWidget);
          expect(find.text(copy.macroLeft(copy.protein)), findsOneWidget);
          expect(tester.takeException(), isNull,
            reason: 'The Food log day view must fit the phone.');
          expect(
            tester
                .widget<Directionality>(find.byType(Directionality).last)
                .textDirection,
            language == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          );
          await tester.tap(find.byType(TextField));
          await tester.pumpAndSettle();
          expect(find.text(copy.searchFoods), findsOneWidget);
          await tester.enterText(
            find.byType(TextField),
            language == 'ar' ? 'بيضة' : 'Egg',
          );
          await tester.pumpAndSettle(const Duration(milliseconds: 300));
          expect(tester.takeException(), isNull,
            reason: 'Food search results must fit the phone.');
          await tester.tap(_resultNamed(language == 'ar' ? 'بيضة' : 'Egg'));
          await tester.pumpAndSettle();
          expect(find.text('1800 ${copy.afterAdding}'), findsOneWidget);
          expect(tester.takeException(), isNull,
            reason: 'The amount screen must fit before editing the amount.');
          if (language == 'ar') {
            await tester.enterText(find.byType(TextField), '١٥٠');
            await tester.pump();
            expect(find.text('1750 ${copy.afterAdding}'), findsOneWidget);
            await tester.tap(find.byType(DropdownButtonFormField<String>).last);
            await tester.pumpAndSettle();
            await tester.tap(find.text('large egg (50.0 ${copy.grams})').last);
            await tester.pumpAndSettle();
            expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
              '3.00');
            expect(find.text('1750 ${copy.afterAdding}'), findsOneWidget);
          }
          expect(
            tester
                .widget<Directionality>(find.byType(Directionality).last)
                .textDirection,
            language == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          );
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  for (final (DateTime instant, String expectedMeal) in <(DateTime, String)>[
    (DateTime(2026, 11, 5, 10, 59), 'Breakfast'),
    (DateTime(2026, 11, 5, 11), 'Lunch'),
  ]) {
    testWidgets('default meal at $instant uses the injected clock', (WidgetTester tester) async {
      await tester.pumpWidget(_app(_fake(), now: () => instant));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('food_log_entry_point')));
      await tester.pumpAndSettle();
      expect(find.text('Add to $expectedMeal'), findsOneWidget);
    });
  }
}

Future<void> _scrollAmountTo(WidgetTester tester, Finder target, {double delta = 200}) async {
  final Finder list = find.descendant(
    of: find.byType(FoodAmountScreen), matching: find.byType(ListView));
  await tester.scrollUntilVisible(target, delta,
    scrollable: find.descendant(of: list, matching: find.byType(Scrollable)).first);
  await tester.pumpAndSettle();
}

void _pauseApp(WidgetTester tester) {
  for (final AppLifecycleState state in <AppLifecycleState>[
    AppLifecycleState.inactive, AppLifecycleState.hidden, AppLifecycleState.paused,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

void _resumeApp(WidgetTester tester) {
  for (final AppLifecycleState state in <AppLifecycleState>[
    AppLifecycleState.hidden, AppLifecycleState.inactive, AppLifecycleState.resumed,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

// The search field also holds the typed text, so match the result row only.
Finder _resultNamed(String name) => find.descendant(
  of: find.byType(ListTile), matching: find.text(name));

IconButton _nextDayButton(WidgetTester tester) => tester.widget<IconButton>(find.ancestor(
  of: find.byTooltip('Next day'), matching: find.byType(IconButton)));

void _expectToday(WidgetTester tester, DateTime date) {
  final MaterialLocalizations copy = MaterialLocalizations.of(
    tester.element(find.byType(NutritionTab)));
  expect(find.text('Today, ${copy.formatMediumDate(date)}'), findsOneWidget);
  expect(_nextDayButton(tester).onPressed, isNull);
}

Map<String, dynamic> _food() => <String, dynamic>{
  'id': 'egg',
  'name': 'Egg',
  'arabic_name': 'بيضة',
  'reviewed': true,
  'nutrients': <String, dynamic>{
    'energy_kcal': 100,
    'protein_g': 20,
    'carbohydrate_g': 5,
    'fat_g': 2,
  },
  'portion_label': 'large egg',
  'portion_grams': 50,
  'staple_roles': <String>['protein'],
};

Map<String, dynamic> _entry(
  String id, {
  String name = 'Egg',
  String time = '08:10',
}) => <String, dynamic>{
  'id': id,
  'food_id': 'egg',
  'name': name,
  'arabic_name': 'بيضة',
  'quantity': 100,
  'grams': 100,
  'unit': 'grams',
  'meal_label': 'breakfast',
  'logged_time': time,
  'portion_label': 'large egg',
  'portion_grams': 50,
  'nutrients_per_100g': _food()['nutrients'],
  'nutrients': _food()['nutrients'],
};

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'food-token'
  ..tokenValid = true
  ..currentUsername = 'food-player'
  ..foodSearchResults = <Map<String, dynamic>>[_food()]
  ..nutritionState = <String, dynamic>{
    'state': 'ready',
    'goal': 'maintain',
    'daily_activity': 'mostly_sitting',
    'targets': <String, dynamic>{
      'calories': 2000,
      'protein_g': 140,
      'carbs_g': 220,
      'fat_g': 70,
    },
  };

Widget _app(
  FakeMayosApi fake, {
  String language = 'en',
  Brightness brightness = Brightness.light,
  Widget? home,
  DateTime Function()? now,
}) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      tokens.save('food-token');
      return ApiClient(
        tokens: tokens,
        baseUrl: 'http://test.local',
        adapter: fake.adapter,
      );
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
    if (now != null) clockProvider.overrideWithValue(now),
  ],
  child: MaterialApp(
    theme: ThemeData(brightness: brightness),
    home: Scaffold(body: home ?? const NutritionTab()),
  ),
);
