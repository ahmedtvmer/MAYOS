import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/food_swap_request_copy.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_requests_screen.dart';
import 'package:mayos_mobile/src/features/coach/program_publish_confirmation.dart';
import 'package:mayos_mobile/src/features/player/nutrition/today_meals.dart';
import 'package:mayos_mobile/src/features/player/nutrition/nutrition_tab.dart';
import 'package:mayos_mobile/src/features/player/nutrition/food_swap_requests.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

void main() {
  testWidgets('Training program publication only selects pending Training program requests', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()..coach = true;
    fake.assignments.add(<String, dynamic>{'assignment_id': 'a1', 'player_username': 'Player'});
    fake.programRequests.addAll(<Map<String, dynamic>>[_request(), <String, dynamic>{
      ..._request(), 'request_id': 'training-1', 'kind': 'split_change', 'program_version': 1,
      'food_swap': null, 'desired_weekly_frequency': 4, 'reason': 'Change my training days',
    }]);
    List<String>? selected;
    await tester.pumpWidget(_app(fake, 'en', Builder(builder: (BuildContext context) => TextButton(
      child: const Text('Publish Training program'), onPressed: () async {
        selected = await showProgramPublishConfirmation(context,
          ProviderScope.containerOf(context).read(apiClientProvider), 'a1',
          const ProgramPublishConfirmation(title: 'Publish', prompt: 'Publish this Training program?',
            confirmLabel: 'Publish', cancelLabel: 'Cancel'),
          onRequestsLoadError: (ApiException error) => fail(error.message));
      }))));
    await tester.tap(find.text('Publish Training program'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('publish_resolve_food-1')), findsNothing);
    expect(find.byKey(const Key('publish_resolve_training-1')), findsOneWidget);
    await tester.tap(find.byKey(const Key('program_publish_confirm')));
    await tester.pumpAndSettle();
    expect(selected, <String>['training-1']);
  });

  for (final String language in <String>['en', 'ar']) {
    testWidgets('swap history leaves first-time setup and remains available in its own screen in $language', (WidgetTester tester) async {
      final FakeMayosApi fake = _fake()
        ..nutritionState = <String, dynamic>{'state': 'not_started', 'targets': null};
      fake.programRequests.add(_request());
      final FoodSwapRequestCopy copy = FoodSwapRequestCopy(language);
      await tester.pumpWidget(_app(fake, language, const NutritionTab()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('food_swap_requests_entry')), findsNothing);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(_app(fake, language, const FoodSwapRequestsScreen()));
      await tester.pumpAndSettle();
      expect(find.text(copy.status('pending')), findsOneWidget);
      expect(Directionality.of(tester.element(find.byKey(const Key('food_swap_request_food-1')))),
        language == 'ar' ? TextDirection.rtl : TextDirection.ltr);
      expect(tester.takeException(), isNull);
    });

    testWidgets('Player requests one food and sees replies and closed status in $language', (WidgetTester tester) async {
      final FakeMayosApi fake = _fake();
      final FoodSwapRequestCopy copy = FoodSwapRequestCopy(language);
      await tester.pumpWidget(_app(fake, language, SingleChildScrollView(child: TodayMeals(onLogged: () {}))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('swap_breakfast_protein')), findsNothing);
      await tester.tap(find.byKey(const Key('request_swap_breakfast_0')));
      await tester.pumpAndSettle();
      // An optional empty reason is accepted, but a refused request stays editable.
      fake.foodWriteFails = true;
      await tester.tap(find.byKey(const Key('send_food_swap_request')));
      await tester.pumpAndSettle();
      expect(find.text('The Nutrition plan changed.'), findsOneWidget);
      fake.foodWriteFails = false;
      await tester.tap(find.byKey(const Key('send_food_swap_request')));
      await tester.pumpAndSettle();
      expect(fake.programRequests.single['reason'], '');
      expect(fake.programRequests.single['food_swap']['food_id'], 'protein');
      await tester.tap(find.byKey(const Key('food_swap_requests_entry')));
      await tester.pumpAndSettle();
      expect(find.text(copy.status('pending')), findsOneWidget);
      fake.programRequests.single.addAll(<String, dynamic>{'status': 'declined', 'response': 'Keep this food today.'});
      await tester.ensureVisible(find.text(copy.refresh));
      await tester.tap(find.text(copy.refresh));
      await tester.pumpAndSettle();
      expect(find.textContaining('Keep this food today.'), findsOneWidget);
      expect(find.text(copy.status('declined')), findsOneWidget);
      fake.programRequests.single.addAll(<String, dynamic>{'status': 'closed', 'response': null});
      await tester.tap(find.text(copy.refresh));
      await tester.pumpAndSettle();
      expect(find.text(copy.closeNote), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    for (final (double width, String decision) in <(double, String)>[(390, 'decline'), (1200, 'apply')]) {
      testWidgets('Coach $decision from the request queue at $width in $language', (WidgetTester tester) async {
        _size(tester, width);
        final FakeMayosApi fake = _fake()..coach = true;
        final FoodSwapRequestCopy copy = FoodSwapRequestCopy(language);
        fake.assignments.add(<String, dynamic>{'assignment_id': 'a1', 'player_username': 'Player',
          'status': 'active', 'started_at': '2026-11-01T12:00:00Z'});
        fake.programRequests.add(_request());
        fake.foodSearchResults = <Map<String, dynamic>>[<String, dynamic>{
          'id': 'alternative', 'name': 'Alternative', 'arabic_name': 'بديل', 'restriction_reasons': <dynamic>[]}];
        await tester.pumpWidget(_app(fake, language,
          CoachRequestsScreen(selectedRequestId: width > 600 ? 'food-1' : null)));
        await tester.pumpAndSettle();
        final ProviderContainer container = ProviderScope.containerOf(tester.element(find.byType(CoachRequestsScreen)));
        expect(container.read(coachPendingRequestsCountProvider), 1);
        if (width > 600) {
          await tester.tap(find.byKey(const Key('request_resolve_button')));
        } else {
          await tester.tap(find.byKey(const Key('request_card_food-1')));
        }
        await tester.pumpAndSettle();
        if (decision == 'apply') {
          await tester.tap(find.byKey(const Key('replacement_alternative')));
          await tester.enterText(find.byKey(const Key('food_swap_grams')), '0');
        }
        final Finder action = find.byKey(Key(decision == 'apply' ? 'apply_food_swap_request' : 'decline_food_swap'));
        await tester.ensureVisible(action);
        await tester.tap(action);
        await tester.pumpAndSettle();
        expect(find.text(copy.invalid), findsOneWidget);
        if (decision == 'apply') await tester.enterText(find.byKey(const Key('food_swap_grams')), '150');
        await tester.enterText(find.byKey(const Key('food_swap_coach_reply')), 'My reply');
        fake.foodWriteFails = true;
        await tester.ensureVisible(action);
        await tester.tap(action);
        await tester.pumpAndSettle();
        expect(find.text('The Nutrition plan changed.'), findsOneWidget);
        expect(container.read(coachPendingRequestsCountProvider), 1);
        fake.foodWriteFails = false;
        await tester.tap(action);
        await tester.pumpAndSettle();
        expect(fake.programRequests.single['status'], decision == 'apply' ? 'applied' : 'declined');
        expect(fake.programRequests.single['response'], 'My reply');
        expect(container.read(coachPendingRequestsCountProvider), 0);
        expect(find.textContaining('My reply'), findsWidgets);
        expect(tester.takeException(), isNull);
      });
    }
  }
}

Map<String, dynamic> _request() => <String, dynamic>{
  'request_id': 'food-1', 'assignment_id': 'a1', 'kind': 'food_swap', 'program_version': null,
  'status': 'pending', 'reason': 'Another protein please', 'created_at': '2026-11-08T12:00:00Z',
  'food_swap': <String, dynamic>{'plan_version_id': 2, 'day_type': 'rest_day', 'slot': 'breakfast',
    'food_index': 0, 'food_id': 'protein', 'food_name': 'Areesh', 'food_name_ar': 'جبن قريش', 'meal_name': 'Breakfast'},
};

FakeMayosApi _fake() => FakeMayosApi()
  ..issuedToken = 'swap-token'
  ..plannedMealsState = <String, dynamic>{'status': 'ready', 'author': 'Coach', 'can_request_swap': true,
    'plan_version_id': 2, 'day_type': 'rest_day', 'meals': <Map<String, dynamic>>[<String, dynamic>{
      'slot': 'breakfast', 'name': 'Breakfast', 'totals': <String, dynamic>{'calories': 180},
      'foods': <Map<String, dynamic>>[<String, dynamic>{'id': 'protein', 'name': 'Areesh',
        'arabic_name': 'جبن قريش', 'grams': 150, 'role': 'protein'}],
    }]};

Widget _app(FakeMayosApi fake, String language, Widget child) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore()..save('swap-token');
      return ApiClient(tokens: tokens, baseUrl: 'http://test.local', adapter: fake.adapter);
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ], child: MaterialApp(home: Scaffold(body: child)),
);

void _size(WidgetTester tester, double width) {
  tester.view.physicalSize = Size(width, 1100);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}
