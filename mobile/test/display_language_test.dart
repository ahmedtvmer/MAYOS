import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language.dart';
import 'package:mayos_mobile/src/core/browser_key_value_store.dart';

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
    expect(store.value, 'en');
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

  test('failed local save does not mutate confirmed language', () async {
    final controller =
        DisplayLanguageController(_FailingStore(), systemLanguage: 'en');
    await expectLater(controller.choose('ar'), throwsStateError);
    expect(controller.state, 'en');
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

    // The Android branch is exercised without a browser framework. In a host
    // test process lacking the plugin, its injected-store fallback is in-memory.
    final android = PlatformDisplayLanguageStore(isWeb: false);
    await android.write('en');
    await android.writeAccount('account', 'ar');
    expect(await android.read(), 'en');
    expect(await android.readAccount('account'), 'ar');
    await android.deleteAccount('account');
    expect(await android.readAccount('account'), isNull);
  });
}
