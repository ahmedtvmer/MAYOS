import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:myos_mobile/src/core/app_update_store.dart';
import 'package:myos_mobile/src/core/display_language/controller.dart';
import 'package:myos_mobile/src/core/display_language/store.dart';
import 'package:myos_mobile/src/core/ui/app_update_toast.dart';
import 'package:myos_mobile/src/router.dart' show logWorkoutPath;

class _FakeUpdateStore implements AppUpdateStore {
  final StreamController<bool> events = StreamController<bool>.broadcast();
  int applyCount = 0;

  @override
  Stream<bool> get updateWaiting => events.stream;

  @override
  Future<void> applyUpdate() async => applyCount++;
}

void main() {
  late GoRouter router;
  late _FakeUpdateStore store;
  final GlobalKey<ScaffoldMessengerState> messengerKey =
      GlobalKey<ScaffoldMessengerState>();

  Future<void> pump(WidgetTester tester, {String language = 'en'}) async {
    router = GoRouter(
      initialLocation: '/home',
      routes: <RouteBase>[
        GoRoute(path: '/home', builder: (_, __) => Scaffold(
          body: Builder(builder: (context) => Column(children: <Widget>[
            const Text('Home screen'),
            TextButton(
              onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Regular app message')),
              ),
              child: const Text('Show app snackbar'),
            ),
          ])),
        )),
        GoRoute(path: '/log-workout/:day', builder: (_, __) => const Scaffold(body: Text('Logger'))),
      ],
    );
    store = _FakeUpdateStore();
    await tester.pumpWidget(ProviderScope(
      overrides: <Override>[
        appUpdateStoreProvider.overrideWithValue(store),
        displayLanguageProvider.overrideWith((ref) =>
            DisplayLanguageController(InMemoryDisplayLanguageStore(),
                systemLanguage: language)),
      ],
      child: MaterialApp.router(
        routerConfig: router,
        locale: Locale(language),
        supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => ScaffoldMessenger(
          key: messengerKey,
          child: AppUpdateToast(
            router: router,
            child: child!,
          ),
        ),
      ),
    ));
    await tester.pump();
  }

  tearDown(() {
    router.dispose();
    store.events.close();
  });

  testWidgets('shows update toast and Refresh applies the update', (tester) async {
    await pump(tester);
    store.events.add(true);
    await tester.pumpAndSettle();
    expect(find.text('New version available'), findsOneWidget);
    await tester.tap(find.text('Refresh'));
    await tester.pump();
    expect(store.applyCount, 1);
  });

  testWidgets('waits through logger, then appears after leaving', (tester) async {
    await pump(tester);
    router.go('$logWorkoutPath/today');
    await tester.pumpAndSettle();
    store.events.add(true);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump();
    expect(find.text('New version available'), findsNothing);
    router.go('/home');
    await tester.pumpAndSettle();
    expect(find.text('New version available'), findsOneWidget);
  });

  testWidgets('false waiting signal hides the toast without applying', (tester) async {
    await pump(tester);
    store.events.add(true);
    await tester.pumpAndSettle();
    expect(find.text('New version available'), findsOneWidget);
    store.events.add(false);
    await tester.pumpAndSettle();
    expect(find.text('New version available'), findsNothing);
    expect(store.applyCount, 0);
  });

  testWidgets('native stub does not show an update toast', (tester) async {
    router = GoRouter(
      initialLocation: '/home',
      routes: <RouteBase>[
        GoRoute(path: '/home', builder: (_, __) => const Scaffold(body: Text('Home screen'))),
      ],
    );
    await tester.pumpWidget(ProviderScope(
      overrides: <Override>[
        displayLanguageProvider.overrideWith((ref) =>
            DisplayLanguageController(InMemoryDisplayLanguageStore())),
      ],
      child: MaterialApp.router(
        routerConfig: router,
        locale: const Locale('en'),
        supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => ScaffoldMessenger(
          key: messengerKey,
          child: AppUpdateToast(
            router: router,
            child: child!,
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('New version available'), findsNothing);
  });

  testWidgets('dismissal does not apply the update and copy is Arabic', (tester) async {
    final SemanticsHandle semantics = tester.ensureSemantics();
    await pump(tester, language: 'ar');
    store.events.add(true);
    await tester.pumpAndSettle();
    expect(find.text('يتوفر إصدار جديد'), findsOneWidget);
    expect(Directionality.of(tester.element(find.text('يتوفر إصدار جديد'))), TextDirection.rtl);
    expect(
      find.byWidgetPredicate((Widget widget) =>
          widget is Semantics &&
          widget.properties.label == 'إغلاق إشعار التحديث'),
      findsOneWidget,
    );
    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();
    expect(store.applyCount, 0);
    store.events.add(true);
    await tester.pumpAndSettle();
    expect(find.text('يتوفر إصدار جديد'), findsNothing);
    semantics.dispose();
  });

  testWidgets('regular app snackbar appears while update toast is visible', (tester) async {
    await pump(tester);
    store.events.add(true);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show app snackbar'));
    await tester.pumpAndSettle();
    expect(find.text('Regular app message'), findsOneWidget);
    expect(find.text('New version available'), findsOneWidget);
  });
}
