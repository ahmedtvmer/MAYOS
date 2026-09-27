import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_app_header.dart';
import 'package:mayos_mobile/src/core/ui/mayos_logo.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';

/// Issue #109: the monochrome brand lockup. These tests pin the asset chosen
/// per theme and the header/splash geometry so the blue asset cannot creep
/// back and the small centred lockup cannot regress.

const String _whiteLockup = 'assets/brand/mayos-lockup-white.png';
const String _blackLockup = 'assets/brand/mayos-lockup-black.png';
const String _whiteMark = 'assets/brand/mayos-mark-white.png';
const String _blackMark = 'assets/brand/mayos-mark-black.png';

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
      theme: brightness == Brightness.dark ? MayosTheme.dark : MayosTheme.light,
      home: Scaffold(body: Center(child: child)),
    ),
  );
  await tester.pump();
}

void main() {
  group('MayosBrandLockup asset per theme', () {
    testWidgets('dark theme uses the white lockup',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(),
          brightness: Brightness.dark);
      expect(_assetName(tester), _whiteLockup);
    });

    testWidgets('light theme uses the black lockup',
        (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandLockup(),
          brightness: Brightness.light);
      expect(_assetName(tester), _blackLockup);
    });

    testWidgets('an explicit white variant wins over the theme',
        (WidgetTester tester) async {
      await _pumpThemed(
        tester,
        const MayosBrandLockup(variant: MayosBrandVariant.white),
        brightness: Brightness.light,
      );
      expect(_assetName(tester), _whiteLockup);
    });
  });

  group('MayosBrandMark asset per theme', () {
    testWidgets('dark theme uses the white mark', (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandMark(),
          brightness: Brightness.dark);
      expect(_assetName(tester), _whiteMark);
    });

    testWidgets('light theme uses the black mark', (WidgetTester tester) async {
      await _pumpThemed(tester, const MayosBrandMark(),
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
      // Resolve the mark so the measured width matches the real (loaded) asset
      // rather than the zero-width placeholder frames.
      await tester.runAsync(() => precacheImage(
            const AssetImage(_whiteMark),
            tester.element(find.byType(MayosAppHeader)),
          ));
      await tester.pump();
    }

    testWidgets('is centred on the screen and at most 24px tall',
        (WidgetTester tester) async {
      const Size size = Size(360, 640);
      await pumpHeader(tester, size);

      final Rect brand = tester.getRect(find.byKey(MayosAppHeader.brandKey));
      expect(brand.center.dx, closeTo(size.width / 2, 0.5));
      expect(brand.height, lessThanOrEqualTo(24));
      expect(tester.getSize(find.byType(MayosBrandMark)).height,
          lessThanOrEqualTo(24));
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
