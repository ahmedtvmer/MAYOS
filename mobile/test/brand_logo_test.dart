import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:myos_mobile/src/core/display_language/controller.dart';
import 'package:myos_mobile/src/core/display_language/store.dart';
import 'package:myos_mobile/src/core/theme/myos_theme.dart';
import 'package:myos_mobile/src/core/ui/myos_app_header.dart';
import 'package:myos_mobile/src/core/ui/myos_logo.dart';
import 'package:myos_mobile/src/features/shared/splash_screen.dart';

/// Issue #109: the monochrome brand lockup. These tests pin the asset chosen
/// per theme and the header/splash geometry so the blue asset cannot creep
/// back and the small centred lockup cannot regress.

const String _whiteLockup = 'assets/brand/myos-lockup-white.png';
const String _blackLockup = 'assets/brand/myos-lockup-black.png';
const String _whiteMark = 'assets/brand/myos-mark-white.png';
const String _blackMark = 'assets/brand/myos-mark-black.png';

String _assetName(WidgetTester tester) {
  final Image image = tester.widget<Image>(find.byType(Image));
  final ImageProvider<Object> provider = image.image;
  expect(provider, isA<AssetImage>());
  return (provider as AssetImage).assetName;
}

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
      theme: brightness == Brightness.dark ? MyosTheme.dark : MyosTheme.light,
      home: Scaffold(body: Center(child: child)),
    ),
  );
  await tester.pump();
}

void main() {
  group('MyosBrandLockup asset per theme', () {
    testWidgets('dark theme uses the white lockup',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MyosBrandLockup(),
          brightness: Brightness.dark);
      expect(_assetName(tester), _whiteLockup);
    });

    testWidgets('light theme uses the black lockup',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MyosBrandLockup(),
          brightness: Brightness.light);
      expect(_assetName(tester), _blackLockup);
    });

    testWidgets('an explicit white variant wins over the theme',
        (WidgetTester tester) async {
      await _pumpThemed(
        tester,
        const MyosBrandLockup(variant: MyosBrandVariant.white),
        brightness: Brightness.light,
      );
      expect(_assetName(tester), _whiteLockup);
    });
  });

  group('MyosBrandMark asset per theme', () {
    testWidgets('dark theme uses the white mark', (WidgetTester tester) async {
      await _pumpThemed(tester, const MyosBrandMark(),
          brightness: Brightness.dark);
      expect(_assetName(tester), _whiteMark);
    });

    testWidgets('light theme uses the black mark', (WidgetTester tester) async {
      await _pumpThemed(tester, const MyosBrandMark(),
          brightness: Brightness.light);
      expect(_assetName(tester), _blackMark);
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
          theme: MyosTheme.light,
          home: Scaffold(
            body: Column(
              children: <Widget>[
                MyosAppHeader(
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
      // Resolve the mark so the measured width matches the real (loaded) asset
      // rather than the zero-width placeholder frames.
      await tester.runAsync(() => precacheImage(
            const AssetImage(_whiteMark),
            tester.element(find.byType(MyosAppHeader)),
          ));
      await tester.pump();
    }

    testWidgets('is centred on the screen and at most 24px tall',
        (WidgetTester tester) async {
      const Size size = Size(360, 640);
      await pumpHeader(tester, size);

      final Rect brand = tester.getRect(find.byKey(MyosAppHeader.brandKey));
      expect(brand.center.dx, closeTo(size.width / 2, 0.5));
      expect(brand.height, lessThanOrEqualTo(24));
      expect(tester.getSize(find.byType(MyosBrandMark)).height,
          lessThanOrEqualTo(24));
    });

    testWidgets('does not crowd the actions at 320px width',
        (WidgetTester tester) async {
      await pumpHeader(tester, const Size(320, 640));

      final Rect brand = tester.getRect(find.byKey(MyosAppHeader.brandKey));
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

      final Rect brand = tester.getRect(find.byKey(MyosAppHeader.brandKey));
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
          theme: MyosTheme.light,
          home: const Scaffold(
            body: MyosAppHeader(title: 'Settings', showBack: true),
          ),
        ),
      );
      await tester.pump();

      expect(find.byKey(MyosAppHeader.brandKey), findsNothing);
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
      expect(find.text('Settings'), findsOneWidget);
    });

    testWidgets('brand announces the localized name while showing MYOS',
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
            theme: MyosTheme.light,
            home: const Scaffold(body: Column(children: <Widget>[
              MyosBrandLockup(height: 80),
              MyosAppHeader(),
            ])),
          ),
        ));
        await tester.pump();
        final String expected = locale.languageCode == 'ar'
            ? 'ميوس'
            : 'MYOS';
        final SemanticsHandle semantics = tester.ensureSemantics();
        expect(tester.getSemantics(find.byType(MyosBrandLockup)).label, expected);
        expect(tester.getSemantics(find.byKey(MyosAppHeader.brandKey)).label, expected);
        expect(find.text('MYOS'), findsWidgets);
        if (locale.languageCode == 'ar') {
          expect(find.bySemanticsLabel('MYOS'), findsNothing);
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
          theme: MyosTheme.light,
          home: Scaffold(
            body: DefaultAssetBundle(
              bundle: _FailingAssetBundle(),
              child: MyosBrandLockup(height: 80),
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      final SemanticsHandle semantics = tester.ensureSemantics();

      expect(tester.getSemantics(find.byType(MyosBrandLockup)).label,
          'ميوس');
      expect(find.bySemanticsLabel('MYOS'), findsNothing);

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
                ? MyosTheme.dark
                : MyosTheme.light,
            home: const SplashScreen(),
          ),
        );
        await tester.pump();

        final Finder lockup = find.byType(MyosBrandLockup);
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
