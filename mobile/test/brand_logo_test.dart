import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_app_header.dart';
import 'package:mayos_mobile/src/core/ui/mayos_logo.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';

/// Issues #109 and #886: the brand lockup and mark. These tests pin the red
/// dumbbell M, the word colour per theme, the fixed mark-to-word gaps and the
/// mark-only header so the old monochrome images cannot creep back.
const Color _logoRed = Color(0xFFB3001B);

Future<void> _pumpThemed(
  WidgetTester tester,
  Widget child, {
  required Brightness brightness,
  Size size = const Size(360, 640),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: brightness == Brightness.dark ? MayosTheme.dark : MayosTheme.light,
      home: Scaffold(body: Center(child: child)),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('header shows the mark alone, with no MAYOS text under it',
      (WidgetTester tester) async {
    await _pumpThemed(tester, const MayosAppHeader(), brightness: Brightness.dark);
    expect(find.byType(MayosBrandMark), findsOneWidget);
    expect(find.text('MAYOS'), findsNothing);
  });

  group('MayosBrandMark', () {
    for (final Brightness brightness in Brightness.values) {
      testWidgets('is the logo red with a 5:3 shape in ${brightness.name}',
          (WidgetTester tester) async {
        await _pumpThemed(tester, const MayosBrandMark(size: 30),
            brightness: brightness);
        final MayosBrandMark mark =
            tester.widget<MayosBrandMark>(find.byType(MayosBrandMark));
        expect(mark.color, _logoRed);
        final Size size = tester.getSize(find.byType(MayosBrandMark));
        expect(size.height, 30);
        expect(size.width, closeTo(50, 0.01));
      });
    }
  });

  group('MayosBrandLockup', () {
    Text word(WidgetTester tester) => tester.widget<Text>(find.text('MAYOS'));

    testWidgets('word uses the wordmark face (A drawn as Λ)',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(),
          brightness: Brightness.dark);
      expect(word(tester).style?.fontFamily, 'MayosWordmark');
      expect(word(tester).style?.fontWeight, FontWeight.w600);
    });

    testWidgets('dark theme draws a white word under the red mark',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(),
          brightness: Brightness.dark);
      expect(word(tester).style?.color, const Color(0xFFF5F5F4));
      expect(tester.widget<MayosBrandMark>(find.byType(MayosBrandMark)).color,
          _logoRed);
    });

    testWidgets('light theme draws a near-black word',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(),
          brightness: Brightness.light);
      expect(word(tester).style?.color, isNot(const Color(0xFFF5F5F4)));
    });

    testWidgets('an explicit white variant wins over the theme',
        (WidgetTester tester) async {
      await _pumpThemed(
        tester,
        const MayosBrandLockup(variant: MayosBrandVariant.white),
        brightness: Brightness.light,
      );
      expect(word(tester).style?.color, const Color(0xFFF5F5F4));
    });

    for (final double gap in <double>[5, 4]) {
      testWidgets('keeps a fixed ${gap.toInt()}px gap between mark and word',
          (WidgetTester tester) async {
        for (final double height in <double>[60, 120]) {
          await _pumpThemed(tester, MayosBrandLockup(height: height, gap: gap),
              brightness: Brightness.dark);
          final Rect mark = tester.getRect(find.byType(MayosBrandMark));
          final Rect text = tester.getRect(find.text('MAYOS'));
          expect(text.top - mark.bottom, closeTo(gap, 0.01),
              reason: 'height $height');
          expect(text.center.dx, closeTo(mark.center.dx, 1.0));
        }
      });
    }

    testWidgets('fits inside the requested height', (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(height: 100),
          brightness: Brightness.dark);
      expect(tester.getSize(find.byType(MayosBrandLockup)).height,
          lessThanOrEqualTo(100.5));
    });
  });

  group('header brand', () {
    Future<void> pumpHeader(WidgetTester tester, Size size,
        {double textScale = 1.0}) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      tester.platformDispatcher.textScaleFactorTestValue = textScale;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pumpWidget(
        MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: MayosTheme.light,
          home: Scaffold(
            body: Column(
              children: <Widget>[
                MayosAppHeader(
                  actions: <Widget>[
                    IconButton(
                      onPressed: () {},
                      icon: const Icon(Icons.chat_bubble_outline),
                    ),
                    IconButton(
                      onPressed: () {},
                      icon: const Icon(Icons.settings_outlined),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
      await tester.pump();
    }

    testWidgets('is centred, mark only and at most 40px tall',
        (WidgetTester tester) async {
      const Size size = Size(360, 640);
      await pumpHeader(tester, size);

      final Rect brand = tester.getRect(find.byKey(MayosAppHeader.brandKey));
      expect(brand.center.dx, closeTo(size.width / 2, 0.5));
      expect(brand.height, lessThanOrEqualTo(40));
      expect(find.byType(MayosBrandMark), findsOneWidget);
      expect(find.text('MAYOS'), findsNothing);
    });

    testWidgets('does not crowd the actions at 320px width',
        (WidgetTester tester) async {
      await pumpHeader(tester, const Size(320, 640));

      final Rect brand = tester.getRect(find.byKey(MayosAppHeader.brandKey));
      final Rect chat = tester.getRect(find.byIcon(Icons.chat_bubble_outline));
      final Rect settings =
          tester.getRect(find.byIcon(Icons.settings_outlined));
      expect(brand.center.dx, closeTo(160, 0.5));
      expect(brand.right, lessThanOrEqualTo(chat.left));
      expect(chat.right, lessThanOrEqualTo(settings.left));
    });

    testWidgets('stays clear of the actions at 320px and 2.0x text',
        (WidgetTester tester) async {
      await pumpHeader(tester, const Size(320, 640), textScale: 2.0);

      final Rect brand = tester.getRect(find.byKey(MayosAppHeader.brandKey));
      final Rect chat = tester.getRect(find.byIcon(Icons.chat_bubble_outline));
      expect(brand.right, lessThanOrEqualTo(chat.left));
    });

    testWidgets('titled sub-page keeps the back affordance, not the logo',
        (WidgetTester tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: MayosTheme.light,
          home: const Scaffold(
            body: MayosAppHeader(title: 'Settings', showBack: true),
          ),
        ),
      );
      await tester.pump();

      expect(find.byKey(MayosAppHeader.brandKey), findsNothing);
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
      expect(find.text('Settings'), findsOneWidget);
    });

    testWidgets('brand announces the localized name while showing MAYOS',
        (WidgetTester tester) async {
      for (final Locale locale in <Locale>[
        const Locale('en'),
        const Locale('ar'),
      ]) {
        await tester.pumpWidget(ProviderScope(
          key: ValueKey<String>(locale.languageCode),
          overrides: <Override>[
            displayLanguageProvider.overrideWith((ref) =>
                DisplayLanguageController(PlatformDisplayLanguageStore(),
                    systemLanguage: locale.languageCode)),
          ],
          child: MaterialApp(
            theme: MayosTheme.light,
            home: const Scaffold(body: Column(children: <Widget>[
              MayosBrandLockup(height: 80),
              MayosAppHeader(),
            ])),
          ),
        ));
        await tester.pump();
        final String expected = locale.languageCode == 'ar'
            ? 'ميوس'
            : 'MAYOS';
        final SemanticsHandle semantics = tester.ensureSemantics();
        expect(tester.getSemantics(find.byType(MayosBrandLockup)).label, expected);
        expect(tester.getSemantics(find.byKey(MayosAppHeader.brandKey)).label, expected);
        expect(find.text('MAYOS'), findsWidgets);
        if (locale.languageCode == 'ar') {
          expect(find.bySemanticsLabel('MAYOS'), findsNothing);
        }
        semantics.dispose();
      }
    });

    testWidgets('Arabic lockup does not announce fallback text twice',
        (WidgetTester tester) async {
      await tester.pumpWidget(ProviderScope(
        overrides: <Override>[
          displayLanguageProvider.overrideWith((ref) =>
              DisplayLanguageController(PlatformDisplayLanguageStore(),
                  systemLanguage: 'ar')),
        ],
        child: MaterialApp(
          theme: MayosTheme.light,
          home: Scaffold(
            body: DefaultAssetBundle(
              bundle: _FailingAssetBundle(),
              child: MayosBrandLockup(height: 80),
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      final SemanticsHandle semantics = tester.ensureSemantics();

      expect(tester.getSemantics(find.byType(MayosBrandLockup)).label,
          'ميوس');
      expect(find.bySemanticsLabel('MAYOS'), findsNothing);

      semantics.dispose();
    });
  });

  group('splash lockup', () {
    for (final Brightness brightness in <Brightness>[
      Brightness.dark,
      Brightness.light,
    ]) {
      final String theme = brightness == Brightness.dark ? 'dark' : 'light';
      testWidgets('is centred and at most 120px tall in $theme',
          (WidgetTester tester) async {
        const Size size = Size(320, 640);
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: brightness == Brightness.dark
                ? MayosTheme.dark
                : MayosTheme.light,
            home: const SplashScreen(),
          ),
        );
        await tester.pump();

        final Finder lockup = find.byType(MayosBrandLockup);
        final Rect rect = tester.getRect(lockup);
        expect(rect.height, lessThanOrEqualTo(120));
        expect(rect.height, greaterThanOrEqualTo(72));
        expect(rect.center.dx, closeTo(size.width / 2, 0.5));
        expect(rect.center.dy, closeTo(size.height / 2, 0.5));
      });
    }
  });
}

class _FailingAssetBundle extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) async {
    throw FlutterError('Asset unavailable: $key');
  }
}
