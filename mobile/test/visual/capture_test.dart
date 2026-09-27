@Tags(<String>['capture'])
library;

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/shared/splash_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import '../support/fake_mayos_api.dart';

/// Visual review harness for issue #49.
///
/// Skipped by default so the normal test suite stays fast and headless. Run:
///
///   cd mobile
///   CAPTURE=1 flutter test --tags capture test/visual/capture_test.dart
///
/// PNGs are written to `docs/design-review/49/` at the repo root.
final bool _enabled = Platform.environment['CAPTURE'] == '1';
const Key _boundaryKey = Key('mayos.capture');

class _Surface {
  const _Surface(this.name, this.tab);
  final String name;
  final int? tab;
}

Future<void> _loadFonts() async {
  TestWidgetsFlutterBinding.ensureInitialized();
  final FontLoader serif = FontLoader('PlayfairDisplay')
    ..addFont(rootBundle.load('assets/fonts/PlayfairDisplay-Variable.ttf'));
  final FontLoader sans = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  // The test bundle ships the Material icon font; without it, icons render as
  // Ahem boxes in captures.
  final FontLoader icons = FontLoader('MaterialIcons')
    ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await Future.wait<void>(
      <Future<void>>[serif.load(), sans.load(), icons.load()]);
}

FakeMayosApi _fake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  return fake;
}

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void _setSize(WidgetTester tester, Size size) {
  tester.view.physicalSize = size * 2;
  tester.view.devicePixelRatio = 2.0;
}

/// Decodes all bundled brand images before capture so a frame never races the
/// async image decode (which otherwise leaves a logo blank in the PNG).
Future<void> _precacheBrandImages(WidgetTester tester) async {
  final BuildContext context = tester.element(find.byType(MaterialApp));
  const List<String> assets = <String>[
    'assets/brand/mayos-lockup-white.png',
    'assets/brand/mayos-lockup-blue.png',
    'assets/brand/mayos-lockup-black.png',
    'assets/brand/mayos-mark-white.png',
    'assets/brand/mayos-mark-blue.png',
    'assets/brand/mayos-mark-black.png',
  ];
  await tester.runAsync(() async {
    for (final String asset in assets) {
      await precacheImage(AssetImage(asset), context);
    }
  });
  await tester.pump();
}

Future<void> _writeCapture(WidgetTester tester, String name) async {
  final RenderRepaintBoundary boundary =
      tester.renderObject<RenderRepaintBoundary>(find.byKey(_boundaryKey));
  // Widget tests run under a fake-async zone, so all real IO (directory
  // creation, encoding, file writes) must happen inside runAsync.
  await tester.runAsync(() async {
    final Directory out =
        Directory('${Directory.current.parent.path}/docs/design-review/49');
    await out.create(recursive: true);
    final ui.Image image = await boundary.toImage(pixelRatio: 2.0);
    final ByteData? data =
        await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (data == null) {
      return;
    }
    await File('${out.path}/$name.png').writeAsBytes(data.buffer.asUint8List());
  });
}

Future<void> _pumpSplash(WidgetTester tester, Size size, ThemeMode mode) async {
  _setSize(tester, size);
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: mode,
        home: const SplashScreen(),
      ),
    ),
  );
  await tester.pump(const Duration(milliseconds: 300));
  await _precacheBrandImages(tester);
}

Future<void> _pumpShell(
    WidgetTester tester, _Surface surface, Size size, ThemeMode mode) async {
  _setSize(tester, size);
  final FakeMayosApi fake = _fake();
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    RepaintBoundary(
      key: _boundaryKey,
      child: ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          themeModeStoreProvider
              .overrideWithValue(InMemoryThemeModeStore(mode)),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          apiClientProvider.overrideWith((ref) {
            final ApiClient client = ApiClient(
              tokens: ref.watch(tokenStoreProvider),
              baseUrl: 'http://test.local',
              adapter: fake.adapter,
            );
            client.onUnauthorized =
                ref.watch(unauthorizedEventsProvider).signal;
            return client;
          }),
        ],
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));

  if (surface.tab != null) {
    await tester.tap(find.text(surface.tab == 0 ? 'Home' : 'Program'));
    await tester.pump(const Duration(milliseconds: 400));
    await _pumpUntilFound(
        tester,
        surface.tab == 0
            ? find.text('Weekly weighted sets')
            : find.text('Upper/Lower 4x'));
  }
  if (surface.name == 'settings') {
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));
  }
  await _precacheBrandImages(tester);
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  setUpAll(_loadFonts);

  const List<Size> sizes = <Size>[Size(360, 640), Size(412, 915)];
  const List<ThemeMode> modes = <ThemeMode>[ThemeMode.light, ThemeMode.dark];
  const List<_Surface> surfaces = <_Surface>[
    _Surface('home', 0),
    _Surface('program', 1),
    _Surface('settings', null),
  ];

  // Set CAPTURE=1 (with --tags capture) to render design-review captures.
  final bool skipCapture = !_enabled;

  for (final Size size in sizes) {
    for (final ThemeMode mode in modes) {
      final String theme = mode == ThemeMode.dark ? 'dark' : 'light';
      final String sizeTag = '${size.width.toInt()}x${size.height.toInt()}';

      testWidgets('splash $theme $sizeTag', (WidgetTester tester) async {
        await _pumpSplash(tester, size, mode);
        await _writeCapture(tester, 'splash-$theme-$sizeTag');
      }, skip: skipCapture);

      for (final _Surface surface in surfaces) {
        testWidgets('${surface.name} $theme $sizeTag',
            (WidgetTester tester) async {
          await _pumpShell(tester, surface, size, mode);
          await _writeCapture(tester, '${surface.name}-$theme-$sizeTag');
        }, skip: skipCapture);
      }
    }
  }
}
