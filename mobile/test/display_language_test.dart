import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language.dart';
import 'package:mayos_mobile/src/core/display_language/assignment_copy.dart';
import 'package:mayos_mobile/src/core/display_language/workout_copy.dart';
import 'package:mayos_mobile/src/core/browser_key_value_store.dart';
import 'package:mayos_mobile/src/core/training_status_projection.dart';

class _BrowserStore implements BrowserKeyValueStore {
  final Map<String, String> values = <String, String>{};
  @override
  String? getItem(String key) => values[key];
  @override
  void setItem(String key, String value) => values[key] = value;
  @override
  void removeItem(String key) => values.remove(key);
}

class _FailingStore extends InMemoryDisplayLanguageStore {
  @override
  Future<void> write(String language) async => throw StateError('offline');
}

void main() {
  test('Arabic workout prescription isolates numeric spans', () {
    const WorkoutCopy copy = WorkoutCopy('ar');
    expect(copy.prescriptionReps(6, 8), contains('\u{2066}6–8\u{2069}'));
    expect(
        copy.prescriptionWeight('62.5'), contains('\u{2066}62.5 kg\u{2069}'));
  });

  test('workout status copy renders typed facts in both languages', () {
    const WorkoutCopy arabic = WorkoutCopy('ar');
    const WorkoutCopy english = WorkoutCopy('en');
    const WeeklyStreakSummaryLine streak = WeeklyStreakSummaryLine(3);
    const WeeklyCompletionSummaryLine completion =
        WeeklyCompletionSummaryLine(completed: 2, target: 3);
    const CheckpointProgressSummaryLine checkpoint =
        CheckpointProgressSummaryLine(remaining: 3, checkpoint: 10);

    expect(english.trainingStatusLine(streak), 'Weekly streak: 3 weeks');
    expect(
      english.trainingStatusLine(checkpoint),
      '3 workouts to your 10th',
    );
    expect(
      arabic.trainingStatusLine(streak),
      'أسابيع الالتزام المتتالية: \u{2066}3\u{2069}',
    );
    expect(
      arabic.trainingStatusLine(completion),
      'هذا الأسبوع: \u{2066}2\u{2069} من \u{2066}3\u{2069} مكتملة',
    );
    expect(
      arabic.trainingStatusLine(checkpoint),
      '\u{2066}3\u{2069} حصص تدريبية للوصول إلى محطة التقدم رقم \u{2066}10\u{2069}',
    );
  });

  test('assignment copy keeps substitution requests distinct from swaps', () {
    const AssignmentCopy arabic = AssignmentCopy('ar');
    const AssignmentCopy english = AssignmentCopy('en');

    expect(arabic.exerciseSubstitutionRequest, 'طلب تبديل تمرين من المدرب');
    expect(english.exerciseSubstitutionRequest, 'Exercise substitution');
    expect(
      arabic.programRequestDescription(
        kind: 'exercise_substitution',
        exercise: 'Bench Press',
        day: 'Upper A',
        replacement: 'Incline Press',
        frequency: null,
        preference: null,
      ),
      'طلب تبديل تمرين من المدرب: \u2066Bench Press\u2069 في \u2066Upper A\u2069 إلى \u2066Incline Press\u2069',
    );
    expect(
      english.programRequestDescription(
        kind: 'exercise_substitution',
        exercise: 'Bench Press',
        day: 'Upper A',
        replacement: 'Incline Press',
        frequency: null,
        preference: null,
      ),
      'Substitute Bench Press on Upper A with Incline Press',
    );
  });

  test('unplanned exercise dialog title is localized by workout copy', () {
    expect(
        const WorkoutCopy('ar').addUnplannedExercise, 'إضافة تمرين غير مخطط');
    expect(
        const WorkoutCopy('en').addUnplannedExercise, 'Add unplanned exercise');
  });

  testWidgets('system Arabic initializes selector to Arabic', (tester) async {
    final store = InMemoryDisplayLanguageStore();
    final container = ProviderContainer(overrides: [
      displayLanguageStoreProvider.overrideWithValue(store),
      systemDisplayLanguageProvider.overrideWithValue('ar'),
    ]);
    await container.read(displayLanguageProvider.notifier).initialize();
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: DisplayLanguageSelector())),
    ));
    expect(find.text('العربية'), findsOneWidget);
  });

  testWidgets('unsupported system locale falls back to English',
      (tester) async {
    final store = InMemoryDisplayLanguageStore();
    final container = ProviderContainer(overrides: [
      displayLanguageStoreProvider.overrideWithValue(store),
      systemDisplayLanguageProvider.overrideWithValue('fr'),
    ]);
    await container.read(displayLanguageProvider.notifier).initialize();
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: DisplayLanguageSelector())),
    ));
    expect(find.text('English'), findsOneWidget);
    // Only a manual choice is persisted; a system-derived default is not.
    expect(store.value, isNull);
  });

  testWidgets(
      'manual choice survives a later logged-out launch and system change',
      (tester) async {
    final store = InMemoryDisplayLanguageStore();
    var container = ProviderContainer(overrides: [
      displayLanguageStoreProvider.overrideWithValue(store),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]);
    await container.read(displayLanguageProvider.notifier).initialize();
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: DisplayLanguageSelector())),
    ));
    await tester.tap(find.byKey(const Key('display_language_selector')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Arabic').last);
    await tester.pumpAndSettle();
    expect(store.value, 'ar');
    await tester.pumpWidget(const SizedBox.shrink());
    container.dispose();
    container = ProviderContainer(overrides: [
      displayLanguageStoreProvider.overrideWithValue(store),
      systemDisplayLanguageProvider.overrideWithValue('en'),
    ]);
    await container.read(displayLanguageProvider.notifier).initialize();
    expect(container.read(displayLanguageProvider), 'ar');
    container
        .read(displayLanguageProvider.notifier)
        .systemLanguageChanged('en');
    expect(container.read(displayLanguageProvider), 'ar');
    container.dispose();
  });

  test('signed account language takes precedence and remains account-scoped',
      () async {
    final store = InMemoryDisplayLanguageStore()..value = 'ar';
    store.accountValues['account-b'] = 'en';
    final controller = DisplayLanguageController(store, systemLanguage: 'fr');
    await controller.useAccount('account-a', 'ar');
    // Logout leaves the account cache isolated; restoring another account
    // replaces the visible value with that account's confirmed choice.
    await controller.initialize(accountId: 'account-b');
    expect(controller.state, 'en');
    expect(await store.readAccount('account-a'), 'ar');
    await store.deleteAccount('account-a');
    expect(await store.readAccount('account-a'), isNull);
    expect(await store.readAccount('account-b'), 'en');
  });

  testWidgets('Arabic catalog retains Western digits and product labels',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      locale: Locale('ar'),
      home: Scaffold(body: Text('0123456789 · MAYOS · Free · Pro · RIR')),
    ));
    expect(find.text('0123456789 · MAYOS · Free · Pro · RIR'), findsOneWidget);
  });

  test('failed local persistence keeps the manual choice active in memory',
      () async {
    final controller =
        DisplayLanguageController(_FailingStore(), systemLanguage: 'en');
    await controller.choose('ar');
    expect(controller.state, 'ar');
  });

  test('web uses browser storage and Android uses secure-storage adapter',
      () async {
    final browser = _BrowserStore();
    final web =
        PlatformDisplayLanguageStore(browserStorage: browser, isWeb: true);
    await web.write('ar');
    await web.writeAccount('account', 'ar');
    expect(await web.read(), 'ar');
    expect(await web.readAccount('account'), 'ar');
    await web.deleteAccount('account');
    expect(await web.readAccount('account'), isNull);

    // Exercise the secure-storage branch directly without a browser framework.
    FlutterSecureStorage.setMockInitialValues(<String, String>{});
    final android = PlatformDisplayLanguageStore(isWeb: false);
    await android.write('en');
    await android.writeAccount('account', 'ar');
    expect(await android.read(), 'en');
    expect(await android.readAccount('account'), 'ar');
    await android.deleteAccount('account');
    expect(await android.readAccount('account'), isNull);
  });
}
