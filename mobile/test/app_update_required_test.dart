import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/external_url_launcher.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/shared/app_update_required_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/auth_harness.dart';
import 'support/fake_mayos_api.dart';

class _RecordingLauncher {
  final List<String> urls = <String>[];

  Future<bool> open(String url) async {
    urls.add(url);
    return true;
  }
}

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 50}) async {
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

void main() {
  for (final String language in <String>['en', 'ar']) {
    testWidgets('minimum build policy blocks in $language', (tester) async {
      final FakeMayosApi fake = FakeMayosApi()..appMinBuild = 2;
      final _RecordingLauncher launcher = _RecordingLauncher();
      final InMemoryDisplayLanguageStore languageStore =
          InMemoryDisplayLanguageStore()..value = language;
      tester.view.physicalSize = const Size(393, 852);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(authApp(
        fake,
        InMemoryTokenStore(),
        extraOverrides: <Override>[
          displayLanguageStoreProvider.overrideWithValue(languageStore),
          systemDisplayLanguageProvider.overrideWithValue('en'),
          androidBuildNumberProvider.overrideWithValue(1),
          externalUrlLauncherProvider.overrideWithValue(launcher.open),
        ],
      ));
      await _pumpUntilFound(
        tester,
        find.byKey(AppUpdateRequiredScreen.storeButtonKey),
      );

      final MayosCopy copy = MayosCopy(language);
      expect(find.text(copy.updateRequiredTitle), findsOneWidget);
      expect(find.text(copy.updateRequiredMessage), findsOneWidget);
      expect(find.text(copy.updateRequiredButton), findsOneWidget);
      expect(fake.appVersionPolicyRequests, 1);
      expect(find.text('Log in'), findsNothing);
      expect(
        Directionality.of(
          tester.element(find.text(copy.updateRequiredTitle)),
        ),
        language == 'ar' ? TextDirection.rtl : TextDirection.ltr,
      );

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      for (int i = 0; i < 4; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(fake.appVersionPolicyRequests, 2);

      await tester.tap(find.byKey(AppUpdateRequiredScreen.storeButtonKey));
      await tester.pump();
      expect(launcher.urls, <String>[fake.appStoreUrl]);

      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(find.text(copy.updateRequiredTitle), findsOneWidget);
    });
  }

  testWidgets('a 426 from any API request opens the blocking route',
      (tester) async {
    final FakeMayosApi fake = FakeMayosApi();
    await tester.pumpWidget(authApp(fake, InMemoryTokenStore()));
    await _pumpUntilFound(tester, find.text('Log in'));

    fake.appMinBuild = 2;
    fake.appUpdateRequiredForRequests = true;
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.byType(MayosApp)),
    );
    await tester.runAsync(() async {
      try {
        await container
            .read(apiClientProvider)
            .dio
            .get<dynamic>('/test/update');
      } on DioException {
        // The update screen is driven by the response interceptor.
      }
    });
    await tester.pump();
    await _pumpUntilFound(
      tester,
      find.byKey(AppUpdateRequiredScreen.storeButtonKey),
    );

    expect(find.text(const MayosCopy('en').updateRequiredTitle), findsOneWidget);
    expect(fake.adapter.requests.last.path, '/test/update');
  });

  for (final AppMode mode in <AppMode>[AppMode.player, AppMode.coach]) {
    testWidgets('a 426 blocks the logged-in ${mode.name} shell',
        (tester) async {
      final FakeMayosApi fake = FakeMayosApi()
        ..issuedToken = 'token-alice'
        ..currentUsername = 'alice'
        ..tokenValid = true
        ..profileExists = true
        ..recoveryEmail = 'alice@example.com'
        ..coach = mode == AppMode.coach;
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await tokens.save('token-alice');
      final InMemoryAppModeStore modeStore = InMemoryAppModeStore(
        mode == AppMode.coach
            ? <String, AppMode>{'account-alice': AppMode.coach}
            : null,
      );

      await tester.pumpWidget(authApp(
        fake,
        tokens,
        extraOverrides: <Override>[
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        ],
        modeStore: modeStore,
      ));
      final Finder shell = find.text(mode == AppMode.coach ? 'Roster' : 'Home');
      await _pumpUntilFound(tester, shell);
      expect(shell, findsOneWidget);

      fake.appMinBuild = 2;
      fake.appUpdateRequiredForRequests = true;
      final ProviderContainer container = ProviderScope.containerOf(
        tester.element(find.byType(MayosApp)),
      );
      await tester.runAsync(() async {
        try {
          await container.read(apiClientProvider).dio.get<dynamic>('/test/update');
        } on DioException {
          // The response interceptor sets the app-wide update state.
        }
      });
      await tester.pump();
      await _pumpUntilFound(
        tester,
        find.byKey(AppUpdateRequiredScreen.storeButtonKey),
      );

      expect(
        find.text(const MayosCopy('en').updateRequiredTitle),
        findsOneWidget,
      );
    });
  }

  testWidgets('a null Android build is not blocked by a high policy',
      (tester) async {
    final FakeMayosApi fake = FakeMayosApi()..appMinBuild = 999;
    await tester.pumpWidget(authApp(
      fake,
      InMemoryTokenStore(),
      extraOverrides: <Override>[
        androidBuildNumberProvider.overrideWithValue(null),
      ],
    ));

    await _pumpUntilFound(tester, find.text('Log in'));

    expect(fake.appVersionPolicyRequests, 1);
    expect(find.byKey(AppUpdateRequiredScreen.storeButtonKey), findsNothing);
  });

  testWidgets('a failed policy check leaves the app usable', (tester) async {
    final FakeMayosApi fake = FakeMayosApi()..appVersionPolicyFails = true;
    await tester.pumpWidget(authApp(fake, InMemoryTokenStore()));

    await _pumpUntilFound(tester, find.text('Log in'));

    expect(fake.appVersionPolicyRequests, 1);
    expect(find.byKey(const Key('login_submit')), findsOneWidget);
    expect(find.byKey(AppUpdateRequiredScreen.storeButtonKey), findsNothing);
  });
}
