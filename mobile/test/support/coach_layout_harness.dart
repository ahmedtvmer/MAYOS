import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/shared_program_text.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'fake_mayos_api.dart';

typedef CoachFakeSetup = void Function(FakeMayosApi fake);
typedef CoachPhonePrepare = Future<void> Function(
  WidgetTester tester,
  String language,
);
typedef CoachLayoutAssertions = FutureOr<void> Function(
  WidgetTester tester,
  String language,
);

FakeMayosApi createCoachFake({String language = 'en'}) => FakeMayosApi()
  ..issuedToken = 'token-alice'
  ..currentUsername = 'alice'
  ..tokenValid = true
  ..coach = true
  ..profileExists = true
  ..recoveryEmail = 'alice@example.com'
  ..coachDisplayName = 'Coach Alice'
  ..displayLanguage = language;

/// Shared fake API and ProviderScope setup for Coach route tests.
Future<void> pumpCoachApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  Size logicalSize = const Size(1440, 960),
  String language = 'en',
  InMemoryAppModeStore? modeStore,
  List<Override> providerOverrides = const <Override>[],
}) async {
  final double devicePixelRatio = tester.view.devicePixelRatio;
  tester.view.physicalSize = Size(
    logicalSize.width * devicePixelRatio,
    logicalSize.height * devicePixelRatio,
  );
  addTearDown(tester.view.resetPhysicalSize);
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(
          NoopSharedProgramTextSource(),
        ),
        ...providerOverrides,
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider
            .overrideWithValue(modeStore ?? InMemoryAppModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(language),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
}

/// Pumps a Coach route at 360×800 in both display languages.
///
/// [pageScrollable] identifies the page's main vertical scrollable for lazy
/// traversal. Every page descendant is checked for horizontal scrolling;
/// [allowedInnerStrips] exempts only scrollables inside marked inner strips.
Future<void> expectCoachPhoneLayout(
  WidgetTester tester, {
  required CoachFakeSetup configureFake,
  CoachPhonePrepare? prepare,
  InMemoryAppModeStore? modeStore,
  required Finder Function(String language) ready,
  required Finder Function(String language) pageScrollable,
  Finder Function(String language)? allowedInnerStrips,
  List<Override> providerOverrides = const <Override>[],
  required CoachLayoutAssertions assertions,
}) async {
  for (final String language in <String>['en', 'ar']) {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    final FakeMayosApi fake = createCoachFake(language: language);
    configureFake(fake);
    fake.displayLanguage = language;
    await pumpCoachApp(
      tester,
      fake,
      logicalSize: const Size(360, 800),
      language: language,
      modeStore: modeStore,
      providerOverrides: providerOverrides,
    );
    await prepare?.call(tester, language);
    for (int attempt = 0; attempt < 60 && ready(language).evaluate().isEmpty;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(ready(language), findsWidgets);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final BuildContext context = tester.element(ready(language).first);
    expect(
      ProviderScope.containerOf(context).read(displayLanguageProvider),
      language,
    );
    expect(
      Directionality.of(context),
      language == 'ar' ? TextDirection.rtl : TextDirection.ltr,
    );
    await _checkPageScroll(
      tester,
      pageScrollable(language),
      ready(language),
      allowedInnerStrips?.call(language) ??
          find.byKey(const Key('__no_allowed_inner_strips')),
    );
    await assertions(tester, language);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
  }
}

Future<void> _checkPageScroll(
  WidgetTester tester,
  Finder pageScrollable,
  Finder page,
  Finder allowedInnerStrips,
) async {
  expect(pageScrollable, findsOneWidget);
  final ScrollableState state = tester.state<ScrollableState>(pageScrollable);
  void expectPageScrollsAreVertical() {
    final List<Element> allowed = allowedInnerStrips.evaluate().toList();
    for (final Element element in find
        .descendant(of: page, matching: find.byType(Scrollable))
        .evaluate()) {
      final Scrollable scrollable = element.widget as Scrollable;
      if (scrollable.axisDirection == AxisDirection.left ||
          scrollable.axisDirection == AxisDirection.right) {
        bool isAllowed = false;
        element.visitAncestorElements((Element ancestor) {
          if (allowed.contains(ancestor)) {
            isAllowed = true;
            return false;
          }
          return true;
        });
        final List<String> ancestors = <String>[];
        element.visitAncestorElements((Element ancestor) {
          ancestors.add(ancestor.widget.runtimeType.toString());
          return ancestors.length < 8;
        });
        expect(isAllowed, isTrue,
            reason: 'Only caller-marked inner strips may scroll horizontally. '
                'Found ${element.widget.runtimeType} (${element.widget.key}), '
                '${scrollable.axisDirection}, ancestors $ancestors.');
      }
    }
  }

  expectPageScrollsAreVertical();
  await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
  while (state.position.pixels < state.position.maxScrollExtent) {
    await tester.drag(
      pageScrollable,
      Offset(0, -state.position.viewportDimension * 0.8),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expectPageScrollsAreVertical();
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
  }
  await tester.drag(
      pageScrollable, Offset(0, state.position.maxScrollExtent + 1));
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
  expectPageScrollsAreVertical();
  await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
}

/// Pumps the same Coach route at a wide viewport to pin desktop behavior.
Future<void> pumpCoachDesktopLayout(
  WidgetTester tester, {
  required CoachFakeSetup configureFake,
  required Finder ready,
  Size logicalSize = const Size(1280, 900),
}) async {
  final FakeMayosApi fake = createCoachFake();
  configureFake(fake);
  await pumpCoachApp(tester, fake, logicalSize: logicalSize);
  for (int attempt = 0; attempt < 60 && ready.evaluate().isEmpty; attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(ready, findsWidgets);
  expect(tester.takeException(), isNull);
}
