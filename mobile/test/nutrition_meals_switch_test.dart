import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/nutrition_copy.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/nutrition/meal_setup_screen.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/scroll_to_control.dart';

void main() {
  for (final String language in <String>['en', 'ar']) {
    for (final Brightness brightness in Brightness.values) {
      testWidgets(
          '$language $brightness Meals switch turns on and off while the row opens setup at 360 dp',
          (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        final NutritionCopy copy = NutritionCopy(language);
        await _pumpTargets(tester, fake, language, brightness);
        expect(_switch(tester).value, isFalse);
        expect(find.text(copy.mealsOff), findsOneWidget);
        await tester.tap(find.byKey(const Key('meals_switch')));
        await tester.pumpAndSettle();
        expect(_switch(tester).value, isTrue);
        expect(find.text(copy.mealsOn), findsOneWidget);
        expect(fake.plannedMealsState['enabled'], isTrue);
        expect(find.byType(MealSetupScreen), findsNothing);

        await tester.tap(find.byKey(const Key('meals_switch')));
        await tester.pumpAndSettle();
        expect(_switch(tester).value, isFalse);
        expect(find.text(copy.mealsOff), findsOneWidget);
        expect(fake.plannedMealsState['enabled'], isFalse);
        await tester.tap(find.text(copy.meals));
        await tester.pumpAndSettle();
        expect(find.byType(MealSetupScreen), findsOneWidget);
        await scrollToControl(tester, find.byKey(const Key('save_meal_setup')));
        expect(find.byKey(const Key('enable_meals')), findsNothing);
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(_switch(tester).value, isFalse);
        expect(
            fake.adapter.requests
                .where((request) => request.path == '/nutrition/meals/enable'),
            hasLength(1));
        expect(
            fake.adapter.requests
                .where((request) => request.path == '/nutrition/meals/disable'),
            hasLength(1));
        expect(tester.takeException(), isNull);
      });
    }

    for (final String reason in <String>[
      'staples',
      'coach',
      'targets',
      'unknown'
    ]) {
      testWidgets(
          '$language unavailable meals explain $reason and disable the switch',
          (WidgetTester tester) async {
        final FakeMayosApi fake = _fake();
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': 'unavailable',
          'reason': reason,
          'author': reason == 'coach' ? 'Coach' : 'Player',
          'can_enable': reason != 'coach'
        };
        await _pumpTargets(tester, fake, language, Brightness.light);
        expect(_switch(tester).onChanged, isNull);
        expect(find.text(NutritionCopy(language).mealsUnavailable(reason)),
            findsOneWidget);
        expect(
            tester
                .widget<ListTile>(find.byKey(const Key('meal_setup_entry')))
                .onTap,
            isNotNull);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets(
        '$language returning from Food restrictions refreshes meal availability',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      final NutritionCopy copy = NutritionCopy(language);
      await _pumpTargets(tester, fake, language, Brightness.light);
      await scrollToControl(tester, find.text(copy.foodRestrictions));
      await tester.tap(find.text(copy.foodRestrictions));
      await tester.pumpAndSettle();
      expect(find.byType(MealSetupScreen), findsOneWidget);
      fake.plannedMealsState = <String, dynamic>{
        ...fake.plannedMealsState,
        'status': 'unavailable',
        'reason': 'staples'
      };
      await tester.pageBack();
      await tester.pumpAndSettle();
      await scrollToControl(tester, find.byKey(const Key('meals_switch')));
      expect(_switch(tester).onChanged, isNull);
      expect(find.text(copy.mealsUnavailable('staples')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        '$language Coach-authored meals remain on and cannot be switched off',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      fake.plannedMealsState = <String, dynamic>{
        ...fake.plannedMealsState,
        'status': 'ready',
        'enabled': true,
        'author': 'Coach',
        'can_enable': false
      };
      await _pumpTargets(tester, fake, language, Brightness.dark);
      expect(_switch(tester).value, isTrue);
      expect(_switch(tester).onChanged, isNull);
      expect(find.text(NutritionCopy(language).mealsUnavailable('coach')),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    for (final bool initiallyEnabled in <bool>[false, true]) {
      testWidgets(
          '$language ${initiallyEnabled ? 'disable' : 'enable'} stays busy then reverts on error',
          (WidgetTester tester) async {
        final FakeMayosApi fake = _fake()..foodWriteFails = true;
        fake.plannedMealsState = <String, dynamic>{
          ...fake.plannedMealsState,
          'status': initiallyEnabled ? 'ready' : 'disabled',
          'enabled': initiallyEnabled
        };
        final Completer<void> pending = Completer<void>();
        addTearDown(() {
          if (!pending.isCompleted) pending.complete();
        });
        final String endpoint =
            '/nutrition/meals/${initiallyEnabled ? 'disable' : 'enable'}';
        fake.adapter.beforeRespond = (request) async {
          if (request.path == endpoint) await pending.future;
        };
        await _pumpTargets(tester, fake, language,
            initiallyEnabled ? Brightness.dark : Brightness.light);
        await tester.tap(find.byKey(const Key('meals_switch')));
        await tester.pump();
        expect(_switch(tester).value, !initiallyEnabled);
        expect(_switch(tester).onChanged, isNull);
        expect(find.text(NutritionCopy(language).saving), findsOneWidget);
        expect(
            tester
                .widget<ListTile>(find.byKey(const Key('meal_setup_entry')))
                .onTap,
            isNull);
        expect(
            fake.adapter.requests.where((request) => request.path == endpoint),
            hasLength(1));
        pending.complete();
        await tester.pumpAndSettle();
        expect(_switch(tester).value, initiallyEnabled);
        expect(_switch(tester).onChanged, isNotNull);
        expect(find.text('Could not update meals.'), findsOneWidget);
        expect(fake.plannedMealsState['enabled'], initiallyEnabled);
        fake.foodWriteFails = false;
        await tester.tap(find.byKey(const Key('meals_switch')));
        await tester.pumpAndSettle();
        expect(_switch(tester).value, !initiallyEnabled);
        expect(tester.takeException(), isNull);
      });
    }
  }
}

Switch _switch(WidgetTester tester) =>
    tester.widget<Switch>(find.byKey(const Key('meals_switch')));

Future<void> _pumpTargets(WidgetTester tester, FakeMayosApi fake,
    String language, Brightness brightness) async {
  tester.view.physicalSize = const Size(360, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(ProviderScope(
      overrides: <Override>[
        apiClientProvider.overrideWith((ref) {
          final InMemoryTokenStore tokens = InMemoryTokenStore();
          tokens.save('meals-switch-token');
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
          home: const Scaffold(body: NutritionTab(targetsOnly: true)))));
  await tester.pumpAndSettle();
  await scrollToControl(tester, find.byKey(const Key('meals_switch')));
}

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'meals-switch-token'
  ..tokenValid = true
  ..currentUsername = 'meals-switch-player'
  ..nutritionState = <String, dynamic>{
    'state': 'ready',
    'goal': 'maintain',
    'targets': <String, dynamic>{
      'calories': 2000,
      'protein_g': 150,
      'carbs_g': 200,
      'fat_g': 60
    }
  }
  ..plannedMealsState = <String, dynamic>{
    'status': 'disabled',
    'author': 'Player',
    'can_enable': true,
    'enabled': false,
    'plan_version_id': 1,
    'meals': <dynamic>[]
  }
  ..generatedMeals = <Map<String, dynamic>>[
    <String, dynamic>{
      'slot': 'breakfast',
      'totals': <String, dynamic>{'calories': 500},
      'foods': <Map<String, dynamic>>[
        <String, dynamic>{'id': 'egg', 'name': 'Egg', 'grams': 100}
      ],
    }
  ];
