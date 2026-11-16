import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_log_copy.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tile.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/scroll_to_control.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets(
          '$language $brightness first-time questions fit at 360 dp and show targets',
          (WidgetTester tester) async {
        _phone(tester);
        final FakeMayosApi fake = _ready()
          ..nutritionState = <String, dynamic>{
            'state': 'not_started',
            'targets': null
          };
        final FoodLogCopy copy = FoodLogCopy(language);
        await tester.pumpWidget(_app(fake, language, brightness));
        await tester.pumpAndSettle();
        expect(find.byType(NutritionCard), findsNWidgets(3));
        expect(find.byType(SegmentedButton<String>), findsOneWidget);
        expect(find.byType(RadioListTile<String>), findsNWidgets(3));
        expect(find.byType(CheckboxListTile), findsNWidgets(3));
        expect(find.byKey(const Key('meal_setup_entry')), findsNothing);
        expect(find.byKey(const Key('food_swap_requests_entry')), findsNothing);
        await tester.tap(find.text(copy.female));
        await scrollToControl(tester, find.text(copy.onFeet));
        await tester.tap(find.text(copy.onFeet));
        await scrollToControl(tester, find.text(copy.showTargets));
        expect(
            tester.getSize(find.byKey(const Key('food_log_entry_point'))).width,
            312);
        expect(find.text(copy.screeningNote), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.tap(find.text(copy.showTargets));
        await tester.pumpAndSettle();
        expect(fake.lastNutritionSetupBody?['sex'], 'female');
        expect(fake.lastNutritionSetupBody?['daily_activity'], 'on_feet');
        expect(find.widgetWithText(AppBar, copy.targetsTitle), findsOneWidget);
        expect(tester.takeException(), isNull);
      });

      for (final bool logged in <bool>[false, true]) {
        testWidgets(
            '$language $brightness ${logged ? 'logged' : 'empty'} day uses one layout at 360 dp',
            (WidgetTester tester) async {
          _phone(tester);
          final FakeMayosApi fake = _ready();
          final FoodLogCopy copy = FoodLogCopy(language);
          if (logged)
            fake.foodLogEntries[fake.foodLogToday] = <Map<String, dynamic>>[
              _entry()
            ];
          await tester.pumpWidget(_app(fake, language, brightness));
          await tester.pumpAndSettle();
          expect(find.text(logged ? '1500' : '2000'), findsOneWidget);
          expect(find.byKey(const Key('food_log_entry_point')), findsOneWidget);
          expect(find.widgetWithText(OutlinedButton, copy.quickAdd),
              findsOneWidget);
          expect(find.text('Start your day'), findsNothing);
          expect(find.byKey(const Key('nutrition_targets')), findsOneWidget);
          await scrollToControl(
              tester, find.byKey(const Key('nutrition_food_log')));
          expect(find.text(copy.nothingLogged),
              logged ? findsNothing : findsOneWidget);
          expect(find.byKey(const Key('copy_food_meal')), findsOneWidget);
          if (logged) {
            expect(find.text('08:10'), findsOneWidget);
            expect(find.text(copy.mealLabel('breakfast')), findsOneWidget);
            expect(find.byType(PopupMenuButton<String>), findsOneWidget);
          }
          await scrollToControl(
              tester, find.byKey(const Key('nutrition_check_in')));
          expect(find.text(copy.waterProgress(3, 2000)), findsOneWidget);
          final Rect water =
              tester.getRect(find.byKey(const Key('nutrition_water_row')));
          for (final String section in <String>[
            'nutrition_verdict',
            'nutrition_week'
          ]) {
            final Rect sectionRect = tester.getRect(find.byKey(Key(section)));
            expect(sectionRect.left, water.left);
            expect(sectionRect.right, water.right);
          }
          for (final String action in <String>[
            'add_water_glass',
            'remove_water_glass',
            'answer_yesterday'
          ]) {
            final Size size = tester.getSize(find.byKey(Key(action)));
            expect(size.width, greaterThanOrEqualTo(44));
            expect(size.height, greaterThanOrEqualTo(44));
          }
          expect(find.text(copy.onTargetCount(2)), findsOneWidget);
          await tester
              .ensureVisible(find.byKey(const Key('adherence_roughly')));
          await tester.tap(find.byKey(const Key('adherence_roughly')));
          await tester.pumpAndSettle();
          expect(fake.nutritionState['today_adherence'], 'roughly');
          expect(
              find.ancestor(
                  of: find.byKey(const Key('adherence_roughly')),
                  matching: find.byWidgetPredicate((Widget widget) =>
                      widget is Semantics &&
                      widget.properties.selected == true)),
              findsOneWidget);
          expect(tester.takeException(), isNull);
        });
      }

      testWidgets(
          '$language $brightness Targets opens beside the date and uses equal tiles',
          (WidgetTester tester) async {
        _phone(tester);
        final FakeMayosApi fake = _ready();
        final FoodLogCopy copy = FoodLogCopy(language);
        await tester.pumpWidget(_app(fake, language, brightness));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('nutrition_targets')));
        await tester.pumpAndSettle();
        expect(find.widgetWithText(AppBar, copy.targetsTitle), findsOneWidget);
        expect(find.text(copy.stop('maintain', 'moderate')), findsOneWidget);
        expect(find.text(copy.goalReason(<String, dynamic>{'code': 'default'})),
            findsOneWidget);
        expect(find.byKey(const Key('food_log_entry_point')), findsNothing);
        await scrollToControl(tester, find.text(copy.macrosTitle));
        final Finder tiles = find.byType(NutritionTile);
        final List<Size> macroSizes = <Size>[
          for (int index = 0; index < 3; index++)
            tester.getSize(tiles.at(index)),
        ];
        expect(macroSizes[0].width, closeTo(macroSizes[1].width, .01));
        expect(macroSizes[1].width, closeTo(macroSizes[2].width, .01));
        expect(
            macroSizes.map((Size size) => size.height).toSet(), hasLength(1));
        await scrollToControl(tester, find.text(copy.waterPrescription(2000)));
        final Finder fiber =
            find.ancestor(of: find.text(copy.coachFiber), matching: tiles);
        final Finder water = find.ancestor(
            of: find.text(copy.waterPrescription(2000)), matching: tiles);
        expect(tester.getSize(fiber), tester.getSize(water));
        expect(find.byKey(const Key('add_water_glass')), findsNothing);
        await scrollToControl(
            tester, find.byKey(const Key('meal_setup_entry')));
        expect(find.text(copy.dailyActivity), findsOneWidget);
        expect(find.text(copy.foodRestrictions), findsOneWidget);
        await tester.tap(find.byKey(const Key('meal_setup_entry')));
        await tester.pumpAndSettle();
        await scrollToControl(tester, find.byKey(const Key('save_meal_setup')));
        expect(find.byKey(const Key('save_meal_setup')), findsOneWidget);
        expect(
            Directionality.of(
                tester.element(find.byKey(const Key('save_meal_setup')))),
            language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
        expect(tester.takeException(), isNull);
      });

      for (final int daysAgo in <int>[1, 2]) {
        testWidgets(
            '$language $brightness past day $daysAgo shows eaten totals and read-only Water',
            (WidgetTester tester) async {
          _phone(tester);
          final FakeMayosApi fake = _ready();
          final FoodLogCopy copy = FoodLogCopy(language);
          final String date = DateTime.parse(fake.foodLogToday)
              .subtract(Duration(days: daysAgo))
              .toIso8601String()
              .substring(0, 10);
          fake.foodLogEntries[date] = <Map<String, dynamic>>[
            _entry(kcal: 2200)
          ];
          fake.waterGlassesByDay[date] = 5;
          await tester.pumpWidget(_app(fake, language, brightness));
          await tester.pumpAndSettle();
          for (int offset = 0; offset < daysAgo; offset++) {
            await tester.tap(find.byTooltip(copy.previousDay));
            await tester.pumpAndSettle();
          }
          expect(find.text('2200'), findsOneWidget);
          expect(find.text(copy.eatenOf(2000)), findsOneWidget);
          expect(find.text(copy.caloriesOver(200)), findsOneWidget);
          await scrollToControl(
              tester, find.byKey(const Key('nutrition_check_in')));
          expect(find.text(copy.waterProgress(5, 2000)), findsOneWidget);
          expect(find.byKey(const Key('add_water_glass')), findsNothing);
          expect(find.byKey(const Key('remove_water_glass')), findsNothing);
          expect(
              find.text(daysAgo == 1 ? copy.howYesterdayWent : copy.howDayWent),
              findsOneWidget);
          await tester.ensureVisible(find.byKey(const Key('adherence_off')));
          final InkWell off =
              tester.widget<InkWell>(find.byKey(const Key('adherence_off')));
          if (daysAgo == 1) {
            await tester.tap(find.byKey(const Key('adherence_off')));
            await tester.pumpAndSettle();
            expect(fake.nutritionState['adherence_days'],
                contains(containsPair('date', date)));
            expect(find.byTooltip('$date: ${copy.off}'), findsOneWidget);
            expect(fake.nutritionState['today_adherence'], isNull);
          } else {
            expect(off.onTap, isNull);
            expect(find.byKey(const Key('food_log_entry_point')), findsNothing);
          }
          expect(tester.takeException(), isNull);
        });
      }
    }
  }
}

void _phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(360, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

FakeMayosApi _ready() => FakeMayosApi()
  ..issuedToken = 'redesign-token'
  ..tokenValid = true
  ..currentUsername = 'redesign-player'
  ..waterGlasses = 3
  ..nutritionState = <String, dynamic>{
    'state': 'ready',
    'goal': 'maintain',
    'intensity': 'moderate',
    'daily_activity': 'mostly_sitting',
    'goal_reason': <String, dynamic>{'code': 'default'},
    'today_water_glasses': 3,
    'targets': <String, dynamic>{
      'calories': 2000,
      'protein_g': 140,
      'carbs_g': 220,
      'fat_g': 70,
      'fiber_g': 28,
      'water_ml': 2000
    },
    'adherence_days': List<Map<String, dynamic>>.generate(
        7,
        (int index) => <String, dynamic>{
              'date': DateTime(2026, 11, index - 1)
                  .toIso8601String()
                  .substring(0, 10),
              'value': index < 2 ? 'on_target' : null,
            }),
  };

Map<String, dynamic> _entry({int kcal = 500}) => <String, dynamic>{
      'id': 'breakfast-food',
      'food_id': 'egg',
      'name': 'Breakfast food',
      'arabic_name': 'طعام الإفطار',
      'quantity': 100,
      'grams': 100,
      'unit': 'grams',
      'meal_label': 'breakfast',
      'logged_time': '08:10',
      'nutrients': <String, dynamic>{
        'energy_kcal': kcal,
        'protein_g': 25,
        'carbohydrate_g': 40,
        'fat_g': 15
      },
    };

Widget _app(FakeMayosApi fake, String language, Brightness brightness) =>
    ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWith((ref) {
          final InMemoryTokenStore tokens = InMemoryTokenStore();
          tokens.save('redesign-token');
          return ApiClient(
              tokens: tokens,
              baseUrl: 'http://test.local',
              adapter: fake.adapter);
        }),
        systemDisplayLanguageProvider.overrideWithValue(language),
      ],
      child: MaterialApp(
          locale: Locale(language),
          supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          theme: brightness == Brightness.dark
              ? MayosTheme.darkForLanguage(language)
              : MayosTheme.lightForLanguage(language),
          home: const Scaffold(body: NutritionTab())),
    );
