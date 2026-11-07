import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/coach/coach_food_log_view.dart';
import 'package:mayos_mobile/src/features/coach/coach_nutrition_segment.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';

void main() {
  for (final (String, double, Brightness) variant in <(String, double, Brightness)>[
    ('en', 1280, Brightness.light),
    ('en', 360, Brightness.dark),
    ('ar', 360, Brightness.light),
    ('ar', 360, Brightness.dark),
  ]) {
    final String language = variant.$1;
    final bool arabic = language == 'ar';
    testWidgets('Coach day table, tags and comparisons fit $variant', (WidgetTester tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(variant.$2, 1000);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final FakeApiAdapter adapter = _adapter();
      await tester.pumpWidget(_app(adapter, language: language, brightness: variant.$3));
      await tester.pumpAndSettle();
      expect(find.byType(DataTable), findsNothing);
      expect(adapter.requests.where((FakeRequest request) => request.path.endsWith('/food-log')), isEmpty);
      await tester.tap(find.widgetWithText(ChoiceChip, arabic ? 'سجل الطعام' : 'Food log'));
      await tester.pumpAndSettle();

      expect(find.byType(DataTable), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.text(arabic ? 'كشري' : 'Koshari'), findsOneWidget);
      expect(find.text(arabic ? 'وصفة' : 'Recipe'), findsOneWidget);
      expect(find.text(arabic ? 'طعام خاص' : 'Personal food'), findsOneWidget);
      expect(find.text(arabic ? 'إضافة سريعة' : 'Quick add'), findsNWidgets(2));
      expect(find.text('Stored Quick add name'), findsNothing);
      expect(find.text('100 ${arabic ? 'جرام' : 'g'}'), findsOneWidget);
      expect(find.text('2 piece'), findsOneWidget);
      expect(find.text(arabic ? 'بعيد عن الهدف · محسوب من السجل' : 'Off · Computed from log'), findsOneWidget);
      expect(find.text('2610 · 2150\n${arabic ? 'فوق الهدف' : 'Over'}'), findsOneWidget);
      expect(find.text('128 · 165\n${arabic ? 'دون الهدف' : 'Short'}'), findsOneWidget);
      expect(find.text('301 · 224\n${arabic ? 'فوق الهدف' : 'Over'}'), findsOneWidget);
      expect(find.text('66 · 66\n${arabic ? 'على الهدف' : 'On target'}'), findsOneWidget);
      final DataTable table = tester.widget<DataTable>(find.byType(DataTable));
      expect(table.rows, hasLength(4));
      final DataRow quick = table.rows[2];
      for (final int column in <int>[2, 4, 5, 6]) {
        expect((quick.cells[column].child as Text).data, isEmpty);
      }
      expect((quick.cells[3].child as Text).data, '210');
      final BuildContext tableContext = tester.element(find.byType(DataTable));
      expect(Directionality.of(tableContext), arabic ? TextDirection.rtl : TextDirection.ltr);
      final Finder box = find.byKey(const ValueKey<String>('coach-log-table-scroll'));
      expect(tester.getSize(box).width, lessThanOrEqualTo(variant.$2));
      final ScrollableState scroll = tester.state<ScrollableState>(find.descendant(
        of: box, matching: find.byType(Scrollable)));
      if (variant.$2 == 360) {
        expect(scroll.position.maxScrollExtent, greaterThan(0));
        await tester.drag(box, Offset(arabic ? 250 : -250, 0));
        await tester.pumpAndSettle();
        expect(scroll.position.pixels, greaterThan(0));
      }
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('day navigation keeps an empty day answer and disables future navigation', (WidgetTester tester) async {
    final FakeApiAdapter adapter = _adapter();
    await tester.pumpWidget(_app(adapter));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ChoiceChip, 'Food log'));
    await tester.pumpAndSettle();
    final Finder next = find.byKey(const ValueKey<String>('coach-log-next'));
    expect(tester.widget<IconButton>(next).onPressed, isNull);
    await tester.tap(find.byKey(const ValueKey<String>('coach-log-previous')));
    await tester.pumpAndSettle();
    expect(adapter.requests.last.query['day'], '2026-11-04');
    expect(find.text('No food logged for this day.'), findsOneWidget);
    expect(find.text('Roughly · Answered'), findsOneWidget);
    expect(find.text('Day total'), findsOneWidget);
    expect(find.textContaining('Over'), findsNothing);
    expect(find.textContaining('Short'), findsNothing);
    expect(tester.widget<DataTable>(find.byType(DataTable)).rows, hasLength(1));
    await tester.tap(next);
    await tester.pumpAndSettle();
    expect(adapter.requests.last.query['day'], '2026-11-05');
    expect(tester.widget<IconButton>(next).onPressed, isNull);
    await tester.tap(find.widgetWithText(ChoiceChip, 'Targets'));
    await tester.pumpAndSettle();
    expect(find.byType(CoachFoodLogView), findsNothing);
    expect(find.byType(TextField), findsWidgets);
    expect(adapter.requests.every((FakeRequest request) => request.method == 'GET'), isTrue);
  });

  testWidgets('day picker requests a past date and a refused read can be retried', (WidgetTester tester) async {
    bool refuse = false;
    final FakeApiAdapter adapter = _adapter(refused: () => refuse);
    await tester.pumpWidget(_app(adapter));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ChoiceChip, 'Food log'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey<String>('coach-log-date')));
    await tester.pumpAndSettle();
    expect(find.byType(DatePickerDialog), findsOneWidget);
    await tester.tap(find.text('4').last);
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(adapter.requests.last.query['day'], '2026-11-04');
    refuse = true;
    await tester.tap(find.byKey(const ValueKey<String>('coach-log-next')));
    await tester.pumpAndSettle();
    expect(find.byType(DataTable), findsNothing);
    expect(find.text('Retry'), findsOneWidget);
    refuse = false;
    await tester.tap(find.widgetWithText(TextButton, 'Retry'));
    await tester.pumpAndSettle();
    expect(find.byType(DataTable), findsOneWidget);
    expect(adapter.requests.last.query['day'], '2026-11-05');
    expect(tester.takeException(), isNull);
  });
}

FakeApiAdapter _adapter({bool Function()? refused}) => FakeApiAdapter((FakeRequest request) {
  if (request.path.endsWith('/nutrition/food-log')) {
    if (refused?.call() == true) return const FakeResponse(403, <String, dynamic>{'detail': 'No active assignment.'});
    final String day = request.query['day'] as String? ?? '2026-11-05';
    final bool empty = day != '2026-11-05';
    return FakeResponse(200, <String, dynamic>{
      'date': day, 'today': '2026-11-05',
      'entries': empty ? <Map<String, dynamic>>[] : <Map<String, dynamic>>[
        _entry('library_food', 'Koshari', foodId: 'mayos:koshari', arabicName: 'كشري'),
        <String, dynamic>{..._entry('personal_food', 'Mum’s cake', foodId: 'personal:1'),
          'quantity': 2, 'unit': 'portion', 'portion_label': 'piece'},
        <String, dynamic>{..._entry('quick_add', 'Stored Quick add name'),
          'quantity': null, 'unit': null, 'grams': null,
          'nutrients': <String, dynamic>{'energy_kcal': 210, 'protein_g': null,
            'carbohydrate_g': null, 'fat_g': null}},
      ],
      'totals': <String, dynamic>{'energy_kcal': empty ? 0 : 2610, 'protein_g': empty ? 0 : 128,
        'carbohydrate_g': empty ? 0 : 301, 'fat_g': empty ? 0 : 66},
      'targets': empty ? null : <String, dynamic>{'calories': 2150, 'protein_g': 165, 'carbs_g': 224, 'fat_g': 66},
      'adherence': <String, dynamic>{'value': empty ? 'roughly' : 'off', 'source': empty ? 'answered' : 'computed'},
    });
  }
  return const FakeResponse(200, <String, dynamic>{
    'authority': 'player', 'goal': 'maintain',
    'targets': <String, dynamic>{'calories': 2000, 'protein_g': 100, 'carbs_g': 250, 'fat_g': 67},
  });
});

Map<String, dynamic> _entry(String kind, String name, {String? foodId, String? arabicName}) => <String, dynamic>{
  'kind': kind, 'food_id': foodId, 'name': name, 'arabic_name': arabicName,
  'meal_label': 'lunch', 'quantity': 100, 'unit': 'grams', 'grams': 100,
  'portion_label': null,
  'nutrients': <String, dynamic>{'energy_kcal': 200, 'protein_g': 20, 'carbohydrate_g': 30, 'fat_g': 4},
};

Widget _app(FakeApiAdapter adapter, {String language = 'en', Brightness brightness = Brightness.light}) => ProviderScope(
  overrides: <Override>[
    apiClientProvider.overrideWith((ref) {
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      tokens.save('coach-token');
      return ApiClient(tokens: tokens, baseUrl: 'http://test.local', adapter: adapter);
    }),
    systemDisplayLanguageProvider.overrideWithValue(language),
  ],
  child: MaterialApp(
    locale: Locale(language),
    supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: ThemeData(brightness: brightness),
    home: Scaffold(body: ListView(children: const <Widget>[
      CoachNutritionSegment(assignmentId: 'assignment'),
    ])),
  ),
);
