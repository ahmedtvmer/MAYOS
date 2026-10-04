import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

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

Future<void> _loadFonts() async {
  TestWidgetsFlutterBinding.ensureInitialized();
  final FontLoader serif = FontLoader('PlayfairDisplay')
    ..addFont(rootBundle.load('assets/fonts/PlayfairDisplay-Variable.ttf'));
  final FontLoader sans = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  await Future.wait<void>(<Future<void>>[serif.load(), sans.load()]);
}

FakeMayosApi _signedInFake({bool coach = false}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.coach = coach;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.coachDisplayName = 'Coach Alice';
  return fake;
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  required ThemeModeStore store,
  Size size = const Size(412, 2400),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(store),
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
  await _pumpUntilFound(
      tester, find.text(fake.coach ? 'Roster' : 'Home'));
}

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

ThemeMode _themeMode(WidgetTester tester) =>
    tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode!;

Brightness _brightness(WidgetTester tester, Finder anchor) =>
    Theme.of(tester.element(anchor)).brightness;

Future<void> _settleTheme(WidgetTester tester) async {
  // A theme-mode change rebuilds MaterialApp; pushed routes pick up the new
  // inherited theme on the following frame.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 250));
}

void main() {
  setUpAll(_loadFonts);

  testWidgets(
      'appearance defaults to System and switches Light/Dark immediately',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryThemeModeStore store = InMemoryThemeModeStore();
    await _pumpApp(tester, fake, store: store);

    expect(_themeMode(tester), ThemeMode.system);

    await _openSettings(tester);

    await tester.tap(find.text('Dark'));
    await _settleTheme(tester);
    expect(_themeMode(tester), ThemeMode.dark);
    expect(_brightness(tester, find.text('Appearance')), Brightness.dark);

    await tester.tap(find.text('Light'));
    await _settleTheme(tester);
    expect(_themeMode(tester), ThemeMode.light);
    expect(_brightness(tester, find.text('Appearance')), Brightness.light);

    await tester.tap(find.text('System'));
    await _settleTheme(tester);
    expect(_themeMode(tester), ThemeMode.system);
  });

  testWidgets('an explicit choice is persisted across a restart',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryThemeModeStore store = InMemoryThemeModeStore();

    await _pumpApp(tester, fake, store: store);
    await _openSettings(tester);
    await tester.tap(find.text('Dark'));
    await _settleTheme(tester);
    expect(_themeMode(tester), ThemeMode.dark);

    // Tear the app down and start again sharing the same device store.
    await tester.pumpWidget(const SizedBox.shrink());
    await _pumpApp(tester, fake, store: store);
    expect(_themeMode(tester), ThemeMode.dark);
    expect(_brightness(tester, find.text('Home')), Brightness.dark);
  });

  testWidgets('system bar style follows the effective theme',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryThemeModeStore store = InMemoryThemeModeStore();
    await _pumpApp(tester, fake, store: store);
    await _openSettings(tester);

    Future<SystemUiOverlayStyle> overlay() async {
      final Iterable<AnnotatedRegion<SystemUiOverlayStyle>> regions =
          tester.widgetList<AnnotatedRegion<SystemUiOverlayStyle>>(
              find.byType(AnnotatedRegion<SystemUiOverlayStyle>));
      return regions.map((r) => r.value).last;
    }

    await tester.tap(find.text('Light'));
    await _settleTheme(tester);
    final SystemUiOverlayStyle light = await overlay();
    expect(light.statusBarIconBrightness, Brightness.dark);
    expect(light.systemNavigationBarColor, MayosThemeExtension.light.canvas);

    await tester.tap(find.text('Dark'));
    await _settleTheme(tester);
    final SystemUiOverlayStyle dark = await overlay();
    expect(dark.statusBarIconBrightness, Brightness.light);
    expect(dark.systemNavigationBarColor, MayosThemeExtension.dark.canvas);
  });

  testWidgets('bottom navigation exposes Home, Program, and Progress',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpApp(tester, fake, store: InMemoryThemeModeStore());

    final MayosBottomNavigation nav = tester
        .widget<MayosBottomNavigation>(find.byType(MayosBottomNavigation));
    // Progress ships now that its flow is backed by real ledger data (#48).
    expect(nav.items.map((MayosNavItem i) => i.label),
        <String>['Home', 'Program', 'Progress']);
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Program'), findsOneWidget);
    // The Progress tab also renders its own serif title, so the label may
    // appear more than once; the nav items list above is the authoritative check.
    expect(find.text('Progress'), findsWidgets);
    // Header brand and clear affordances.
    expect(find.text('MAYOS'), findsOneWidget);
    expect(find.byIcon(Icons.settings_outlined), findsOneWidget);
    expect(find.byIcon(Icons.chat_bubble_outline), findsOneWidget);
    // No placeholder destinations.
    expect(find.text('Coach'), findsNothing);
    expect(find.text('Workout'), findsNothing);
  });

  testWidgets('Settings opens from the header and keeps entry points reachable',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake(coach: true);
    await _pumpApp(tester, fake, store: InMemoryThemeModeStore());

    // Coach mode opens Settings from the mode sheet (#119) ...
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    expect(find.text('Player mode'), findsOneWidget);
    expect(find.text('Coach mode'), findsOneWidget);
    expect(find.text('Log out'), findsOneWidget);
    await tester.tap(find.text('Settings'));
    await _pumpUntilFound(tester, find.text('Appearance'));

    // ... and keeps the shared account controls reachable beside coach-only
    // profile and plan entries.
    for (final String entry in <String>[
      'Coach profile',
      'Coach plan',
      'Notifications',
      'Account',
      'Username',
      'Linked sign-in',
      'Recovery email',
      'Display language',
      'Log out',
    ]) {
      if (find.text(entry).evaluate().isEmpty) {
        await tester.drag(
          find.byKey(const Key('settings_section_list')),
          const Offset(0, -300),
        );
        await tester.pump();
      }
      expect(find.text(entry), findsWidgets, reason: 'missing $entry');
    }
    for (final String gone in <String>[
      'Training profile',
      'Lifter plan',
      'My coach',
      'Assistant',
      'Assistant style',
      'Personalization',
      'Roster & invites',
      'Alert center',
    ]) {
      expect(find.text(gone), findsNothing, reason: 'stale $gone');
    }
  });

  testWidgets('a non-coach sees the invite entry, not coach destinations',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpApp(tester, fake, store: InMemoryThemeModeStore());
    await _openSettings(tester);

    expect(find.text('Enable coaching'), findsOneWidget);
    expect(find.text('Coach profile'), findsNothing);
    expect(find.text('Alert center'), findsNothing);
    expect(find.byType(ModeAvatarButton), findsNothing);
  });

  for (final Size size in const <Size>[
    Size(360, 640),
    Size(393, 852),
    Size(412, 915),
  ]) {
    testWidgets(
        'shell and settings have no overflow at ${size.width}x${size.height} '
        'and 1.5x text', (WidgetTester tester) async {
      final FakeMayosApi fake = _signedInFake(coach: true);
      await _pumpApp(tester, fake, store: InMemoryThemeModeStore(), size: size);

      tester.platformDispatcher.textScaleFactorTestValue = 1.5;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);

      await _openSettings(tester);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'shell has no overflow at ${size.width}x${size.height} and 2.0x text',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpApp(tester, fake, store: InMemoryThemeModeStore(), size: size);

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });
  }
}
