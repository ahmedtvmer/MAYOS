import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:go_router/go_router.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/core/ui/mayos_app_header.dart';
import 'package:mayos_mobile/src/core/install_prompt_store.dart';
import 'package:mayos_mobile/src/features/shared/install_prompt.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/features/player/tour/tour_controller.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/tour/feature_list.dart';
import 'package:mayos_mobile/src/features/player/tour/spotlight_overlay.dart';
import 'package:mayos_mobile/src/features/player/tour/whats_new_screen.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_share_card.dart';
import 'package:mayos_mobile/src/features/player/dashboard/dashboard_tab.dart';
import 'package:mayos_mobile/src/features/player/tour/tour_targets.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/fake_mayos_api.dart';
import 'support/fake_api_adapter.dart';
import 'support/fake_analytics_client.dart';
import 'support/fake_tour_seen_retry_store.dart';
import 'support/fake_whats_new_seen_retry_store.dart';

Uint8List _validTestPng() => Uint8List.fromList(<int>[
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
  0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 31, 21, 196, 137,
  0, 0, 0, 13, 73, 68, 65, 84, 120, 156, 99, 248, 207, 192, 240,
  31, 0, 5, 0, 1, 255, 137, 153, 61, 29, 0, 0, 0, 0, 73, 69,
  78, 68, 174, 66, 96, 130,
]);

class _FakeInstallPromptStore implements InstallPromptStore {
  _FakeInstallPromptStore(this.environment, {this.outcome = 'unavailable'});
  final InstallPromptEnvironment environment;
  final String outcome;
  bool dismissed = false;
  int prompts = 0;
  void Function()? installed;
  void Function()? installStateChanged;
  bool installedBeforeListener = false;
  bool canPersist = true;

  @override
  Future<InstallPromptEnvironment> readEnvironment() async => environment;
  @override
  Future<void> rememberDismissal() async {
    if (canPersist) {
      dismissed = true;
    }
  }
  @override
  Future<String> promptInstall() async {
    prompts++;
    return outcome;
  }
  @override
  void listenForInstalled(void Function() onInstalled) {
    installed = onInstalled;
    if (installedBeforeListener) onInstalled();
  }
  @override
  void listenForInstallState(void Function() onInstallStateChanged) =>
      installStateChanged = onInstallStateChanged;
  @override
  bool consumeInstalled() {
    final bool wasInstalled = installedBeforeListener;
    installedBeforeListener = false;
    return wasInstalled;
  }

  void fireInstallStateChanged() => installStateChanged?.call();

  void fireInstalled() {
    if (installed == null) {
      installedBeforeListener = true;
    } else {
      installed!();
    }
  }
}

class _BlockingWhatsNewRetryStore implements WhatsNewSeenRetryStore {
  final Completer<int?> pendingRead = Completer<int?>();

  @override
  Future<int?> read(String accountId) => pendingRead.future;

  @override
  Future<void> write(String accountId, int release) async {}

  @override
  Future<void> clear(String accountId) async {}
}

class _PendingWriteWhatsNewStore implements WhatsNewSeenRetryStore {
  final Completer<void> writeStarted = Completer<void>();
  final Completer<void> releaseWrite = Completer<void>();
  final Map<String, int> pending = <String, int>{};

  @override
  Future<int?> read(String accountId) async => pending[accountId];

  @override
  Future<void> write(String accountId, int release) async {
    writeStarted.complete();
    await releaseWrite.future;
    pending[accountId] = release;
  }

  @override
  Future<void> clear(String accountId) async => pending.remove(accountId);
}

class _TrackingWorkoutCache extends InMemoryWorkoutCacheStore {
  final List<String> latestSessionWrites = <String>[];

  @override
  Future<void> writeLatestSession(String accountId, LatestSession session) {
    latestSessionWrites.add(accountId);
    return super.writeLatestSession(accountId, session);
  }
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
  fail('Timed out after $attempts attempts waiting for $finder');
}

Future<void> _pumpHome(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeModeStore? themeStore,
  DraftStore? draftStore,
  String languageCode = 'en',
  Size size = const Size(1080, 2400),
  List<Override> extraOverrides = const <Override>[],
  AppModeStore? appModeStore,
  bool waitForHome = true,
  TourSeenRetryStore? tourRetryStore,
  WhatsNewSeenRetryStore? whatsNewRetryStore,
}) async {
  fake.displayLanguage = languageCode;
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      key: UniqueKey(),
      overrides: <Override>[
        installPromptDelayProvider.overrideWithValue(Duration.zero),
        ...extraOverrides,
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(appModeStore ?? InMemoryAppModeStore()),
        themeModeStoreProvider
            .overrideWithValue(themeStore ?? InMemoryThemeModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
        tourSeenRetryStoreProvider.overrideWithValue(
            tourRetryStore ?? FakeTourSeenRetryStore()),
        whatsNewSeenRetryStoreProvider.overrideWithValue(
            whatsNewRetryStore ?? FakeWhatsNewSeenRetryStore()),
        draftStoreProvider
            .overrideWithValue(draftStore ?? InMemoryDraftStore()),
        workoutCacheStoreProvider
            .overrideWithValue(InMemoryWorkoutCacheStore()),
        activeWorkoutStoreProvider
            .overrideWithValue(InMemoryActiveWorkoutStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
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
  if (waitForHome) {
    await _pumpUntilFound(
        tester, find.text(languageCode == 'ar' ? 'الرئيسية' : 'Home'));
  }
}

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.whatsNewSeenRelease = currentFeatureRelease;
  return fake;
}

void main() {
  testWidgets('What’s new shows only unseen supported entries and Got it remembers the release', (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = 0;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final FakeWhatsNewSeenRetryStore retryStore = FakeWhatsNewSeenRetryStore();
    final FeatureEntry unsupported = FeatureEntry(
      id: 'future_feature',
      titleEn: 'Future feature',
      sentenceEn: 'This will arrive in a later release.',
      titleAr: 'ميزة مستقبلية',
      sentenceAr: 'ستصل هذه الميزة في إصدار لاحق.',
      target: 'profile',
      location: TourRouteLocation(profilePath),
      release: currentFeatureRelease + 1,
      audience: 'lifter',
    );
    await _pumpHome(tester, fake, size: const Size(390, 844), whatsNewRetryStore: retryStore, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
      featureEntriesProvider.overrideWithValue(<FeatureEntry>[...featureList, unsupported]),
    ]);
    await _pumpUntilFound(tester, find.text("What's new"));
    final Finder sheetList = find.descendant(
      of: find.byType(BottomSheet), matching: find.byType(Scrollable),
    ).first;
    for (final FeatureEntry entry in featureList.where((FeatureEntry item) => item.release == currentFeatureRelease)) {
      await tester.scrollUntilVisible(find.text(entry.titleEn), 220, scrollable: sheetList);
      expect(find.text(entry.titleEn), findsOneWidget);
    }
    expect(find.text('Future feature'), findsNothing);
    await tester.ensureVisible(find.text('Got it'));
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    expect(fake.whatsNewSeenRelease, currentFeatureRelease);
    expect(fake.whatsNewSeenWriteCount, 1);
    expect(retryStore.pending, isEmpty);
    expect(analytics.events.any((Map<String, Object> event) => event['event'] == 'whats_new_opened'), isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
    await _pumpHome(tester, fake, size: const Size(390, 844), whatsNewRetryStore: retryStore);
    expect(find.text("What's new"), findsNothing);
  });

  testWidgets("offline What's new dismissal is queued and retried after app restart", (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..whatsNewSeenRelease = 0
      ..whatsNewSeenWriteFailures = 1;
    final FakeWhatsNewSeenRetryStore retryStore = FakeWhatsNewSeenRetryStore();
    await _pumpHome(tester, fake, size: const Size(390, 844), whatsNewRetryStore: retryStore);
    await _pumpUntilFound(tester, find.text("What's new"));
    await tester.ensureVisible(find.text('Got it'));
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();

    expect(retryStore.pending['account-alice'], currentFeatureRelease);
    final ProviderContainer firstContainer = ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    expect(firstContainer.read(authControllerProvider).session?.account.whatsNewSeenRelease, currentFeatureRelease);
    expect(fake.whatsNewSeenRelease, 0);

    await tester.pumpWidget(const SizedBox.shrink());
    await _pumpHome(tester, fake, size: const Size(390, 844), whatsNewRetryStore: retryStore);
    await _pumpUntilFound(tester, find.text('Home'));
    await tester.pumpAndSettle();
    expect(fake.whatsNewSeenRelease, currentFeatureRelease);
    expect(fake.whatsNewSeenWriteCount, 2);
    expect(retryStore.pending, isEmpty);
    expect(find.text("What's new"), findsNothing);
  });

  testWidgets("What's new close marks the release seen", (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = 0;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text("What's new"));
    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();
    expect(fake.whatsNewSeenRelease, currentFeatureRelease);
    expect(fake.whatsNewSeenWriteCount, 1);
  });

  testWidgets("Profile What's new list is grouped and localized", (tester) async {
    for (final String language in <String>['en', 'ar']) {
      final FakeMayosApi fake = _signedInFake();
      final FakeAnalyticsClient analytics = FakeAnalyticsClient();
      await _pumpHome(tester, fake, languageCode: language, size: const Size(390, 844), extraOverrides: <Override>[
        analyticsClientProvider.overrideWithValue(analytics),
      ]);
      final ProviderContainer container = ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
      for (int attempt = 0; attempt < 40 && !container.read(activeWorkoutControllerProvider).ready; attempt++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(container.read(activeWorkoutControllerProvider).ready, isTrue);
      container.read(routerProvider).go(profilePath);
      await tester.pumpAndSettle();
      final String listLabel = language == 'ar' ? 'ما الجديد' : "What's new";
      await tester.ensureVisible(find.text(listLabel));
      await tester.tap(find.text(listLabel));
      await tester.pumpAndSettle();
      expect(container.read(routerProvider).routerDelegate.state.uri.path, whatsNewPath);
      for (final FeatureEntry entry in featureList.where((FeatureEntry item) => item.release == currentFeatureRelease)) {
        await tester.scrollUntilVisible(
          find.text(language == 'ar' ? entry.titleAr : entry.titleEn),
          180,
          scrollable: find.byType(Scrollable).first,
        );
        expect(find.text(language == 'ar' ? entry.titleAr : entry.titleEn), findsOneWidget, reason: entry.id);
      }
      await tester.scrollUntilVisible(
        find.text(language == 'ar' ? 'أكتوبر 2026' : 'October 2026'), 180,
        scrollable: find.byType(Scrollable).first);
      expect(find.text(language == 'ar' ? 'أكتوبر 2026' : 'October 2026'), findsOneWidget);
      expect(find.text(language == 'ar' ? 'أرني' : 'Show me'), findsWidgets);
      expect(analytics.events.any((Map<String, Object> event) =>
          event['event'] == 'whats_new_opened' &&
          (event['properties'] as Map<String, Object>)['source'] == 'profile'), isTrue);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets("What's new analytics respects the opt-out", (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..analyticsAllowed = false
      ..whatsNewSeenRelease = 0;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, size: const Size(390, 844), extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await _pumpUntilFound(tester, find.text("What's new"));
    final Finder row = find.ancestor(
      of: find.text(featureList.firstWhere((FeatureEntry entry) => entry.id == 'weak_points').titleEn),
      matching: find.byType(WhatsNewFeatureRow),
    );
    final Finder showMe = find.descendant(of: row, matching: find.text('Show me'));
    final Finder sheetList = find.descendant(
      of: find.byType(BottomSheet), matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(showMe, 180, scrollable: sheetList);
    await tester.ensureVisible(showMe);
    await tester.pumpAndSettle();
    await tester.tap(showMe);
    await tester.pumpAndSettle();
    expect(analytics.events.where((Map<String, Object> event) =>
        event['event'] == 'whats_new_opened' || event['event'] == 'show_me_tapped'), isEmpty);
  });

  testWidgets("What's new waits for an open workout to close", (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = 0;
    final _BlockingWhatsNewRetryStore retryStore = _BlockingWhatsNewRetryStore();
    await _pumpHome(tester, fake, size: const Size(390, 844), whatsNewRetryStore: retryStore);
    final ProviderContainer container = ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final ActiveWorkout workout = ActiveWorkout.fromJson(<String, dynamic>{
      'id': 'whats-new-workout',
      'account_id': 'account-alice',
      'started_at': '2026-10-28T10:00:00Z',
      'day_order': 1,
      'day_name': 'Upper 1',
      'exercises': <dynamic>[],
      'baselines': <String, dynamic>{},
    });
    container.read(activeWorkoutControllerProvider.notifier).state = ActiveWorkoutState(
      accountId: 'account-alice', ready: true, workout: workout,
    );
    retryStore.pendingRead.complete(null);
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsNothing);
    container.read(activeWorkoutControllerProvider.notifier).state = const ActiveWorkoutState(
      accountId: 'account-alice', ready: true, workout: null,
    );
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsOneWidget);
  });

  testWidgets("What's new waits until the app session after the Tour", (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..tourSeenVersion = 0
      ..whatsNewSeenRelease = 0;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text('1 OF 7'));
    expect(find.text("What's new"), findsNothing);
    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsNothing);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(routerProvider).go(workoutsPath);
    await tester.pumpAndSettle();
    container.read(routerProvider).go(homePath);
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text("What's new"));
    expect(find.text("What's new"), findsOneWidget);
  });

  testWidgets('Add exercises is omitted when a coach controls program edits', (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..coachControlsProgram = true
      ..whatsNewSeenRelease = 0;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text("What's new"));
    expect(find.text('Add exercises in the Program tab'), findsNothing);
    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();

    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(routerProvider).go(featureGuidePath);
    await tester.pumpAndSettle();
    expect(find.text('Add exercises in the Program tab'), findsNothing);
    expect(find.text('Weak points'), findsOneWidget);
  });

  testWidgets("What's new follows Player mode for a Coach-capable account", (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..coach = true
      ..tourSeenVersion = 1
      ..whatsNewSeenRelease = 0;
    final InMemoryAppModeStore modes = InMemoryAppModeStore(
      <String, AppMode>{'account-alice': AppMode.coach},
    );
    await _pumpHome(
      tester,
      fake,
      size: const Size(390, 844),
      appModeStore: modes,
      waitForHome: false,
    );
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsNothing);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    await container.read(appModeControllerProvider.notifier).setMode(
          AppMode.player,
          accountId: 'account-alice',
          isCoach: true,
        );
    await _pumpUntilFound(tester, find.text("What's new"));
    expect(find.text("What's new"), findsOneWidget);
  });

  testWidgets("What's new retry does not write Account A under Account B", (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = kReleaseShareCard - 1;
    fake.passwords['bob'] = 'password123';
    final _PendingWriteWhatsNewStore retryStore = _PendingWriteWhatsNewStore();
    await _pumpHome(
      tester,
      fake,
      size: const Size(390, 844),
      whatsNewRetryStore: retryStore,
    );
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    unawaited(container.read(tourControllerProvider.notifier).markWhatsNewSeen(currentFeatureRelease));
    await retryStore.writeStarted.future;
    unawaited(container.read(authControllerProvider.notifier).login(
          username: 'bob',
          password: 'password123',
        ));
    for (int attempt = 0;
        attempt < 40 &&
            container.read(authControllerProvider).session?.account.accountId !=
                'account-bob';
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(
      container.read(authControllerProvider).session?.account.accountId,
      'account-bob',
    );
    retryStore.releaseWrite.complete();
    await tester.pumpAndSettle();
    expect(
      fake.adapter.requests.where((request) => request.path == '/auth/whats-new-seen'),
      isEmpty,
    );
  });

  testWidgets('chat Show me waits through a delayed successful history load', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final Completer<void> historyGate = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.path == '/chat/history' && request.method == 'GET') {
        await historyGate.future;
      }
    };
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text('Home'));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(routerProvider).go(chatPath);
    await tester.pump();
    expect(find.byKey(const ValueKey<String>('tour_next')), findsNothing);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('chat_composer_bar')));
    expect(find.byKey(const ValueKey<String>('chat_composer')), findsOneWidget);
    unawaited(container.read(tourControllerProvider.notifier).showMe('assistant_why'));
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    historyGate.complete();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_next')), findsOneWidget);
  });

  testWidgets("What's new Show me is not blocked by a stalled seen request", (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = 0;
    final Completer<void> seenRequest = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.path == '/auth/whats-new-seen') await seenRequest.future;
    };
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text("What's new"));
    final Finder showMe = find.descendant(
      of: find.ancestor(
        of: find.text('Weak points'), matching: find.byType(WhatsNewFeatureRow),
      ),
      matching: find.text('Show me'),
    );
    final Finder sheetList = find.descendant(
      of: find.byType(BottomSheet), matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(showMe, 180, scrollable: sheetList);
    await tester.ensureVisible(showMe);
    await tester.pumpAndSettle();
    await tester.tap(showMe);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    expect(find.byKey(const ValueKey<String>('profile_weak_points_section')), findsOneWidget);
    seenRequest.complete();
    await tester.pumpAndSettle();
  });

  testWidgets('eligible install dialog waits for its injected delay', (tester) async {
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(
      tester,
      _signedInFake(),
      size: const Size(360, 640),
      extraOverrides: <Override>[
        installPromptStoreProvider.overrideWithValue(store),
        installPromptDelayProvider.overrideWithValue(
          const Duration(milliseconds: 1500),
        ),
      ],
    );
    expect(find.text('Install'), findsNothing);
    await tester.pump(const Duration(milliseconds: 1500));
    expect(find.text('Install'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('dialog close affordances dismiss and record the prompt', (tester) async {
    for (final String path in <String>['not now', 'close', 'barrier', 'back']) {
      final FakeAnalyticsClient analytics = FakeAnalyticsClient();
      final _FakeInstallPromptStore store = _FakeInstallPromptStore(
        const InstallPromptEnvironment(
          isIosShareBrowser: false,
          hasInstallButton: true,
          isStandalone: false,
          wasDismissed: false,
        ),
      );
      await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
        installPromptStoreProvider.overrideWithValue(store),
        analyticsClientProvider.overrideWithValue(analytics),
      ]);
      await tester.pump(const Duration(milliseconds: 1500));
      switch (path) {
        case 'not now':
          await tester.tap(find.text('Not now'));
        case 'close':
          await tester.tap(find.byTooltip('Dismiss'));
        case 'barrier':
          await tester.tapAt(const Offset(2, 2));
        case 'back':
          await tester.binding.handlePopRoute();
      }
      await tester.pumpAndSettle();
      expect(store.dismissed, isTrue, reason: path);
      expect(find.text('Install'), findsNothing, reason: path);
      expect(
        analytics.events.any((event) => event['event'] == 'install_prompt_dismissed'),
        isTrue,
        reason: path,
      );
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('Home shows install variants and reports shown analytics', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1500));
    expect(find.text('Install'), findsOneWidget);
    expect(analytics.events.any((event) => event['event'] == 'install_prompt_shown'), isTrue);
  });

  testWidgets('install prompt waits until Tour is dismissed', (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      installPromptDelayProvider.overrideWithValue(
        const Duration(milliseconds: 1500),
      ),
    ]);
    await _pumpUntilFound(
      tester,
      find.byKey(const ValueKey<String>('tour_skip')),
    );
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('Install'), findsNothing);

    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(milliseconds: 1500));
    expect(find.text('Install'), findsOneWidget);
  });

  testWidgets('install prompt waits until What’s new is dismissed',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..whatsNewSeenRelease = 0;
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      installPromptDelayProvider.overrideWithValue(Duration.zero),
    ]);
    await _pumpUntilFound(tester, find.text("What's new"));
    expect(find.text('Install'), findsNothing);
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Install'));
  });

  testWidgets('storage failure still hides a dismissed prompt this visit', (tester) async {
    const InstallPromptEnvironment eligible = InstallPromptEnvironment(
      isIosShareBrowser: true,
      hasInstallButton: false,
      isStandalone: false,
      wasDismissed: false,
    );
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(eligible)
      ..canPersist = false;
    await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    expect(find.textContaining('tap Share'), findsNothing);
    store.fireInstallStateChanged();
    await tester.pump();
    expect(find.textContaining('tap Share'), findsNothing);
  });

  testWidgets('iOS hint dismisses for this visit and records dismissal', (tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: true,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    expect(find.text('1  Tap Share'), findsOneWidget);
    expect(find.text('2  Add to Home Screen'), findsOneWidget);
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    expect(store.dismissed, isTrue);
    expect(find.text('1  Tap Share'), findsNothing);
    expect(analytics.events.any((event) => event['event'] == 'install_prompt_dismissed'), isTrue);
  });

  testWidgets('cancelling the browser dialog counts as dismissal', (tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
      outcome: 'dismissed',
    );
    await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.tap(find.text('Install'));
    await tester.pumpAndSettle();
    expect(store.prompts, 1);
    expect(store.dismissed, isTrue);
    expect(analytics.events.any((event) => event['event'] == 'install_prompt_dismissed'), isTrue);
  });

  testWidgets('accepting the browser dialog hides the prompt and is tracked', (tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: true,
        isStandalone: false,
        wasDismissed: false,
      ),
      outcome: 'accepted',
    );
    await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.tap(find.text('Install'));
    await tester.pumpAndSettle();
    expect(store.prompts, 1);
    expect(store.dismissed, isFalse);
    expect(find.text('Install'), findsNothing);
    expect(analytics.events.any((event) => event['event'] == 'install_prompt_accepted'), isTrue);
  });

  testWidgets('install events respect the analytics opt-out gate', (tester) async {
    final FakeMayosApi fake = _signedInFake()..analyticsAllowed = false;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: true,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    expect(analytics.events, isEmpty);
  });

  testWidgets('Arabic install hint is localized and app installation is tracked', (tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: true,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      ),
    );
    await _pumpHome(tester, _signedInFake(), languageCode: 'ar', extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump(const Duration(milliseconds: 1500));
    expect(find.text('١  اضغط على مشاركة'), findsOneWidget);
    expect(find.text('٢  اختر إضافة إلى الشاشة الرئيسية'), findsOneWidget);
    expect(Directionality.of(tester.element(find.text('الرئيسية'))), TextDirection.rtl);
    store.fireInstalled();
    await tester.pump();
    expect(analytics.events.any((event) => event['event'] == 'app_installed'), isTrue);
    expect(find.text('١  اضغط على مشاركة'), findsNothing);
  });

  testWidgets('installation before Dart startup is consumed with no variant', (tester) async {
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final _FakeInstallPromptStore store = _FakeInstallPromptStore(
      const InstallPromptEnvironment(
        isIosShareBrowser: false,
        hasInstallButton: false,
        isStandalone: false,
        wasDismissed: false,
      ),
    )..installedBeforeListener = true;
    await _pumpHome(tester, _signedInFake(), extraOverrides: <Override>[
      installPromptStoreProvider.overrideWithValue(store),
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await tester.pump();
    expect(analytics.events.where((event) => event['event'] == 'app_installed'), hasLength(1));
    expect(
      (analytics.events.singleWhere((event) => event['event'] == 'app_installed')['properties']
          as Map<String, Object>)['variant'],
      'none',
    );
    expect(find.text('Install MAYOS'), findsNothing);
  });

  testWidgets(
      'Arabic Home labels use RTL while server program names stay as sent',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake, languageCode: 'ar');
    await _pumpUntilFound(tester, find.textContaining('محسوبة لكل عضلة'));

    expect(find.text('الرئيسية'), findsOneWidget);
    expect(find.text('لا يوجد برنامج تدريبي نشط'), findsNothing);
    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 أيام في الأسبوع'), findsOneWidget);
    expect(find.textContaining('محسوبة لكل عضلة'), findsOneWidget);
    expect(
      find.text('تُحسب مجموعة التدريب بقيمة 1 للعضلة الأساسية و0.5 لكل عضلة مساعدة.'),
      findsOneWidget,
    );
    expect(
      Directionality.of(tester.element(find.text('الرئيسية'))),
      TextDirection.rtl,
    );
  });

  testWidgets('Arabic Home translates the pending workout draft banner',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryDraftStore drafts = InMemoryDraftStore();
    await drafts.write('account-alice', <WorkoutDraft>[
      const WorkoutDraft(
        clientSessionId: 'draft-1',
        accountId: 'account-alice',
        performedDate: '2026-10-02',
        performedTimezone: 'UTC',
        programVersion: 1,
        dayOrder: 1,
        dayName: 'Upper 1',
        capturedAt: '2026-10-02T10:00:00Z',
        exercises: <DraftExercise>[],
        readiness: 4,
        updatedAt: '2026-10-02T10:00:00Z',
        attempt: 1,
        nextAttemptAt: '2099-01-01T00:00:00Z',
      ),
    ]);
    await _pumpHome(
      tester,
      fake,
      languageCode: 'ar',
      draftStore: drafts,
    );
    await _pumpUntilFound(
      tester,
      find.text('مسودة تدريبية واحدة بانتظار المزامنة'),
    );

    expect(find.text('مسودة تدريبية واحدة بانتظار المزامنة'), findsOneWidget);
  });

  testWidgets('home maps the active program, volume, and records',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await tester.pumpWidget(const SizedBox.shrink());
    await _pumpHome(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);

    // The weekly schedule (Mon/Wed/Fri) drives the next-session label.
    expect(find.textContaining('Next session ·'), findsOneWidget);

    // Volume muscles and a personal record are real values.
    expect(find.text('Chest'), findsOneWidget);
    expect(find.text('Back'), findsOneWidget);
    expect(find.text('120 kg × 5'), findsOneWidget);
  });

  testWidgets('Tour walks all seven stops then marks completion seen',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    final Completer<void> profileRequestsStarted = Completer<void>();
    final Completer<void> releaseProfileRequests = Completer<void>();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, size: const Size(390, 844), extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/profile') {
        if (!profileRequestsStarted.isCompleted) {
          profileRequestsStarted.complete();
        }
        await releaseProfileRequests.future;
      }
    };
    await _pumpUntilFound(tester, find.text('1 OF 7'));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);
    expect(container.read(authControllerProvider).session?.account.tourSeenVersion, 0);
    expect(container.read(activeWorkoutControllerProvider).ready, isTrue);
    expect(container.read(playerChatStreamingProvider), isFalse);
    expect(find.text('Home'), findsWidgets);
    void expectSpotlightMatchesTarget(String id) {
      final Finder realControl = switch (id) {
        'home' => find.textContaining('Next session'),
        'program' => find.byKey(const ValueKey<String>('program_day_1_1')),
        'assistant' => find.byTooltip('Assistant'),
        'nutrition' => find.text('Set up Nutrition targets'),
        'progress' => find.text('Progress'),
        'profile' => find.text('Training profile').last,
        'feature_guide' => find.text('Feature guide'),
        _ => throw StateError('No real control finder for $id'),
      };
      expect(realControl, findsWidgets, reason: '$id control should be present');
      final Rect cutout = tester.getRect(
        find.byKey(const ValueKey<String>('tour_spotlight_cutout')),
      );
      expect(cutout.contains(tester.getRect(realControl.first).center), isTrue,
          reason: '$id control should be in the spotlight');
    }
    expectSpotlightMatchesTarget('home');
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(find.text('2 OF 7'), findsOneWidget);
    expectSpotlightMatchesTarget('program');
    await tester.tap(find.byKey(const ValueKey<String>('tour_back')));
    await tester.pumpAndSettle();
    expect(find.text('1 OF 7'), findsOneWidget);
    expectSpotlightMatchesTarget('home');
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(find.text('2 OF 7'), findsOneWidget);
    expectSpotlightMatchesTarget('program');
    for (int step = 3; step <= 7; step++) {
      await tester.tap(find.text('Next'));
      if (step == 6) {
        await tester.pump();
        for (int attempt = 0;
            attempt < 40 && !profileRequestsStarted.isCompleted;
            attempt++) {
          await tester.pump(const Duration(milliseconds: 100));
        }
        expect(profileRequestsStarted.isCompleted, isTrue,
            reason: 'Profile requests should start for the Tour Profile stop');
        await tester.pump(const Duration(seconds: 5));
        final TourSession loadingProfile =
            container.read(tourControllerProvider)!;
        expect(loadingProfile.index, 5);
        expect(loadingProfile.visible, isFalse);
        expect(fake.tourSeenWriteCount, 0);
        releaseProfileRequests.complete();
      }
      await tester.pumpAndSettle();
      expect(find.text('$step OF 7'), findsOneWidget);
      final String id = tourV1StopIds[step - 1];
      expectSpotlightMatchesTarget(id);
      if (step == 6) {
        await tester.tap(find.byKey(const ValueKey<String>('tour_back')));
        await tester.pumpAndSettle();
        expect(find.text('5 OF 7'), findsOneWidget);
        expect(router.routerDelegate.state.uri.path, homePath);
        expect(container.read(playerShellTabProvider), 3);
        expectSpotlightMatchesTarget('progress');
        await tester.tap(find.text('Next'));
        await tester.pumpAndSettle();
        expect(find.text('6 OF 7'), findsOneWidget);
        expect(router.routerDelegate.state.uri.path, profilePath);
        expectSpotlightMatchesTarget('profile');
      }
    }
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
    expect(container.read(authControllerProvider).session?.account.tourSeenVersion, 1);
    expect(analytics.events.map((event) => event['event']), contains('tour_completed'));

    await _pumpHome(tester, fake);
    await tester.pumpAndSettle();
    expect(find.text('1 OF 7'), findsNothing);
  });

  testWidgets('Arabic Tour follows all seven stops across real tabs and routes',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    await _pumpHome(tester, fake, languageCode: 'ar');
    const List<String> titles = <String>[
      'الرئيسية', 'البرنامج التدريبي', 'المساعد', 'التغذية', 'التقدم',
      'الملف الشخصي', 'دليل الميزات',
    ];
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final router = container.read(routerProvider);
    for (int index = 0; index < titles.length; index++) {
      await _pumpUntilFound(tester, find.text(titles[index]));
      expect(find.text(titles[index]), findsWidgets);
      if (index == 1) expect(container.read(playerShellTabProvider), 1);
      if (index == 2) expect(container.read(playerShellTabProvider), 0);
      if (index == 3) expect(container.read(playerShellTabProvider), 2);
      if (index == 4) expect(container.read(playerShellTabProvider), 3);
      if (index >= 5) expect(router.routerDelegate.state.uri.path, profilePath);
      if (index < titles.length - 1) {
        await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
        await tester.pumpAndSettle();
      }
    }
    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
  });

  testWidgets('Replay tour leaves seen state untouched and marks replay analytics',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 1;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final int writesBefore = fake.tourSeenWriteCount;
    final Future<void> replay = container
        .read(tourControllerProvider.notifier)
        .startTour(1, replay: true);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    await replay;
    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
    expect(fake.tourSeenWriteCount, writesBefore);
    expect(analytics.events.where((event) =>
        event['event'] == 'tour_started' &&
        (event['properties'] as Map<String, Object>)['replay'] == true), hasLength(1));
    expect(analytics.events.where((event) =>
        event['event'] == 'tour_skipped' &&
        (event['properties'] as Map<String, Object>)['replay'] == true), hasLength(1));
  });

  testWidgets('Tour session is cancelled when the authenticated account changes',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    await _pumpHome(tester, fake);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final AuthController auth =
        container.read(authControllerProvider.notifier);
    final TourController tour =
        container.read(tourControllerProvider.notifier);
    final Future<void> starting = tour.startTour(1);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    await starting;
    tour.suspend();
    await tester.pump();

    final AccountSession accountA = auth.state.session!;
    final AccountSession accountB = AccountSession(
      account: accountA.account.copyWith(
        accountId: 'account-bob',
        traineeId: 'bob',
        tourSeenVersion: 0,
      ),
      onboarded: true,
      hasRecoveryEmail: accountA.hasRecoveryEmail,
    );
    auth.state = const AuthState.unauthenticated();
    auth.state = AuthState.authenticated(accountB);
    await _pumpUntilFound(tester, find.text('Home'));

    expect(isTourEligible(accountB.account), isTrue);
    TourSession? session = container.read(tourControllerProvider);
    expect(session?.accountId, anyOf(isNull, 'account-bob'));
    if (session == null) {
      final Future<void> startedForB = tour.startTour(1);
      await _pumpUntilFound(
        tester,
        find.byKey(const ValueKey<String>('tour_skip')),
      );
      await startedForB;
      session = container.read(tourControllerProvider);
    }
    expect(session?.accountId, 'account-bob');
    expect(fake.tourSeenWriteCount, 0);
  });

  testWidgets('Tour controller does nothing after switching to Coach mode',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..coach = true
      ..tourSeenVersion = 1;
    await _pumpHome(
      tester,
      fake,
      appModeStore: InMemoryAppModeStore(<String, AppMode>{
        'account-alice': AppMode.player,
      }),
    );
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final Account account =
        container.read(authControllerProvider).session!.account;
    final TourController tour =
        container.read(tourControllerProvider.notifier);
    final Future<void> starting = tour.startTour(1, replay: true);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    await starting;

    await container.read(appModeControllerProvider.notifier).setMode(
          AppMode.coach,
          accountId: account.accountId,
          isCoach: true,
        );
    await tester.pumpAndSettle();
    expect(container.read(tourControllerProvider), isNull);
    expect(container.read(routerProvider).routerDelegate.state.uri.path,
        coachRosterPath);

    await tour.showMe('home');
    expect(container.read(tourControllerProvider), isNull);
  });

  testWidgets('Tour target registry follows real Profile widget disposal', (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.text('1 OF 7'));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));

    for (int step = 2; step <= 3; step++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('$step OF 7'), findsOneWidget);
    }
    final router = container.read(routerProvider);
    router.go(profilePath);
    await tester.pumpAndSettle();
    expect(container.read(tourTargetRegistryProvider), contains('profile'));
    router.go(homePath);
    await tester.pumpAndSettle();
    expect(container.read(tourTargetRegistryProvider), isNot(contains('profile')));
    expect(fake.tourSeenVersion, 0);
  });

  testWidgets('Tour Skip records seen state and Arabic mirrors Skip',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, languageCode: 'ar', extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await _pumpUntilFound(tester, find.text('تخطي'));
    expect(tester.getTopLeft(find.text('تخطي')).dx,
        lessThan(tester.view.physicalSize.width / 2));
    await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsOneWidget);
    await tester.tap(find.text('تخطي'));
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
    expect(analytics.events.map((event) => event['event']), contains('tour_skipped'));
  });

  testWidgets('Tour waits for a streaming reply and resumes on Home',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
      playerChatStreamingProvider.overrideWith((ref) => true),
    ]);
    expect(find.text('1 OF 7'), findsNothing);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(playerChatStreamingProvider.notifier).state = false;
    await _pumpUntilFound(tester, find.text('1 OF 7'));
    expect(find.text('1 OF 7'), findsOneWidget);
  });

  testWidgets('Tour pauses for a newly open workout and streaming reply until Home reopens',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));

    final ActiveWorkout workout = ActiveWorkout.fromJson(<String, dynamic>{
      'id': 'tour-workout',
      'account_id': 'account-alice',
      'started_at': '2026-10-28T10:00:00Z',
      'day_order': 1,
      'day_name': 'Upper 1',
      'exercises': <dynamic>[],
      'baselines': <String, dynamic>{},
    });
    container.read(activeWorkoutControllerProvider.notifier).state =
        ActiveWorkoutState(
      accountId: 'account-alice',
      ready: true,
      workout: workout,
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
    final int eventCountWhilePaused = analytics.events.length;

    container.read(activeWorkoutControllerProvider.notifier).state =
        const ActiveWorkoutState(
      accountId: 'account-alice',
      ready: true,
      workout: null,
    );
    container.read(playerShellTabProvider.notifier).state = 1;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    container.read(playerShellTabProvider.notifier).state = 0;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    expect(analytics.events.length, greaterThan(eventCountWhilePaused));

    container.read(playerChatStreamingProvider.notifier).state = true;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
    final int eventCountWhileStreaming = analytics.events.length;
    container.read(playerChatStreamingProvider.notifier).state = false;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
    expect(analytics.events.length, eventCountWhileStreaming);
    container.read(playerShellTabProvider.notifier).state = 1;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    container.read(playerShellTabProvider.notifier).state = 0;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));
    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
  });

  testWidgets('Tour events stay suppressed when analytics is opted out',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..tourSeenVersion = 0
      ..analyticsAllowed = false;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    await _pumpUntilFound(tester, find.text('Skip'));
    await tester.tap(find.text('Skip'));
    await tester.pumpAndSettle();
    expect(analytics.events.where((event) =>
        (event['event'] as String).startsWith('tour_')), isEmpty);
  });

  testWidgets('showMe Program from Profile opens its shell tab target',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final router = container.read(routerProvider);
    router.go(profilePath);
    await tester.pumpAndSettle();

    final Future<void> spotlight =
        container.read(tourControllerProvider.notifier).showMe('program');
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    await spotlight;

    expect(router.routerDelegate.state.uri.path, homePath);
    expect(container.read(playerShellTabProvider), 1);
    expect(find.text('Program'), findsWidgets);
    expect(fake.tourSeenVersion, 1);
  });

  testWidgets('showMe Profile from Home targets its route and unregisters on pop',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final router = container.read(routerProvider);

    final Future<void> spotlight =
        container.read(tourControllerProvider.notifier).showMe('profile');
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    await spotlight;
    expect(router.routerDelegate.state.uri.path, profilePath);
    expect(find.text('Profile'), findsWidgets);
    expect(fake.tourSeenVersion, 1);

    await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
    await tester.pumpAndSettle();
    router.go(homePath);
    await tester.pumpAndSettle();
    await tester.pump();
    expect(container.read(tourTargetRegistryProvider), isNot(contains('profile')));
  });

  testWidgets('Show me waits for Profile API responses before spotlighting',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final Completer<void> profileRequestsStarted = Completer<void>();
    final Completer<void> releaseProfileRequests = Completer<void>();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path.startsWith('/profile') ||
          request.path.startsWith('/onboarding/intake') ||
          request.path == '/auth/me') {
        if (!profileRequestsStarted.isCompleted) {
          profileRequestsStarted.complete();
        }
        await releaseProfileRequests.future;
      }
    };

    final Future<void> spotlight = container
        .read(tourControllerProvider.notifier)
        .showMe('weak_points');
    await tester.pump();
    for (int attempt = 0;
        attempt < 40 && !profileRequestsStarted.isCompleted;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(profileRequestsStarted.isCompleted, isTrue,
        reason: 'Profile requests should start for Show me');
    await tester.pump(const Duration(seconds: 5));
    final TourSession pending = container.read(tourControllerProvider)!;
    expect(pending.visible, isFalse);
    expect(pending.featureId, 'weak_points');
    expect(fake.tourSeenWriteCount, 0);

    releaseProfileRequests.complete();
    await _pumpUntilFound(
      tester,
      find.byKey(const ValueKey<String>('tour_spotlight_cutout')),
    );
    await spotlight;
    expect(find.byKey(const Key('profile_weak_points_section')), findsOneWidget);
    final Rect cutout = tester.getRect(
      find.byKey(const ValueKey<String>('tour_spotlight_cutout')),
    );
    expect(cutout.contains(tester.getRect(
      find.byKey(const Key('profile_weak_points_section')),
    ).center), isTrue);
    expect(fake.tourSeenWriteCount, 0);
  });

  testWidgets('Profile Guides rows open the Feature guide and replay the Tour',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 1;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);
    router.push(profilePath);
    await _pumpUntilFound(tester, find.text('Injuries'));
    final Finder profileList = find.byWidget(tester.widget<Scrollable>(find
        .ancestor(of: find.text('Injuries'), matching: find.byType(Scrollable))
        .first));

    await tester.scrollUntilVisible(find.text('Feature guide'), 300,
        scrollable: profileList);
    await tester.tap(find.text('Feature guide'));
    await tester.pumpAndSettle();
    expect(router.routerDelegate.state.uri.path, featureGuidePath);
    expect(find.text('Show me'), findsWidgets);

    router.pop();
    await tester.pumpAndSettle();
    final int writesBefore = fake.tourSeenWriteCount;
    await tester.scrollUntilVisible(find.text('Replay tour'), 300,
        scrollable: find.byWidget(tester.widget<Scrollable>(find
            .ancestor(
                of: find.text('Feature guide'),
                matching: find.byType(Scrollable))
            .first)));
    await tester.tap(find.text('Replay tour'));
    await _pumpUntilFound(tester, find.text('1 OF 7'));
    expect(router.routerDelegate.state.uri.path, homePath);
    expect(fake.tourSeenWriteCount, writesBefore);
    for (int step = 2; step <= 7; step++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('$step OF 7'), findsOneWidget);
    }
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
    expect(fake.tourSeenWriteCount, writesBefore);
  });

  testWidgets("What's new Show me lands and spotlights each release entry", (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    final List<FeatureEntry> entries = featureList
        .where((FeatureEntry entry) => entry.release == currentFeatureRelease)
        .toList(growable: false);

    for (final FeatureEntry entry in entries) {
      fake.whatsNewSeenRelease = 0;
      final int writesBefore = fake.whatsNewSeenWriteCount;
      await _pumpHome(tester, fake, size: const Size(390, 844), extraOverrides: <Override>[
        analyticsClientProvider.overrideWithValue(analytics),
      ]);
      await _pumpUntilFound(tester, find.text("What's new"));
      final Finder row = find.ancestor(
        of: find.text(entry.titleEn), matching: find.byType(WhatsNewFeatureRow),
      );
      final Finder showMe = find.descendant(of: row, matching: find.text('Show me'));
      final Finder sheetList = find.descendant(
        of: find.byType(BottomSheet), matching: find.byType(Scrollable),
      ).first;
      await tester.scrollUntilVisible(showMe, 180, scrollable: sheetList);
      await tester.ensureVisible(showMe);
      await tester.pumpAndSettle();
      await tester.tap(showMe);
      await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
      await tester.pumpAndSettle();

      final ProviderContainer container = ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
      final GoRouter router = container.read(routerProvider);
      expect(entry.location.matches(router.routerDelegate.state.uri.path, container.read(playerShellTabProvider)), isTrue, reason: entry.id);
      expect(find.descendant(of: find.byType(SpotlightOverlay), matching: find.text(entry.titleEn)), findsOneWidget, reason: entry.id);
      expect(find.descendant(of: find.byType(SpotlightOverlay), matching: find.text(entry.sentenceEn)), findsOneWidget, reason: entry.id);
      if (entry.id == 'brand-mayos') {
        final Finder logo = find.byKey(MayosAppHeader.brandKey);
        expect(logo, findsOneWidget);
        final Rect cutout = tester.getRect(find.byKey(const ValueKey<String>('tour_spotlight_cutout')));
        expect(cutout.contains(tester.getRect(logo).center), isTrue);
      }
      if (entry.release == currentFeatureRelease) {
        final Finder realControl = switch (entry.id) {
          'weak_points' => find.byKey(const Key('profile_weak_points_section')),
          'assistant_why' => find.byKey(const Key('chat_composer')),
          'add_exercises' => find.byKey(const Key('program_edit_day_1')),
          'edit_program_chat' => find.byKey(const Key('chat_composer_bar')),
          'movements_to_avoid' => find.byKey(const Key('profile_movement_restrictions_section')),
          'brand-mayos' => find.byKey(MayosAppHeader.brandKey),
          'workout_share_card' || 'duration_check' => find.text('Log workout'),
          'food_log' => find.byKey(const Key('food_log_entry_point')),
          'meal_setup' => find.byKey(const Key('meal_setup_entry')),
          'food_swap_requests' => find.byKey(const Key('food_swap_requests_entry')),
          'assistant_meals' => find.byTooltip('Assistant'),
          _ => find.text(entry.titleEn),
        };
        expect(realControl, findsOneWidget, reason: entry.id);
        final Rect cutout = tester.getRect(find.byKey(const ValueKey<String>('tour_spotlight_cutout')));
        expect(cutout.contains(tester.getRect(realControl).center), isTrue, reason: '${entry.id} control should be inside the spotlight');
      }
      expect(analytics.events.any((Map<String, Object> event) =>
          event['event'] == 'show_me_tapped' &&
          (event['properties'] as Map<String, Object>)['feature_id'] == entry.id &&
          (event['properties'] as Map<String, Object>)['source'] == 'whats_new'), isTrue, reason: entry.id);
      await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
      await tester.pumpAndSettle();
      expect(fake.whatsNewSeenRelease, currentFeatureRelease, reason: entry.id);
      expect(fake.whatsNewSeenWriteCount, writesBefore + 1, reason: entry.id);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('Feature guide Show me lands and spotlights every lifter feature',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    const FeatureEntry unsupported = FeatureEntry(
      id: 'future_feature',
      titleEn: 'Future feature',
      sentenceEn: 'This will arrive in a later release.',
      titleAr: 'ميزة مستقبلية',
      sentenceAr: 'ستصل هذه الميزة في إصدار لاحق.',
      target: 'profile',
      location: TourRouteLocation(profilePath),
      release: currentFeatureRelease + 1,
      audience: 'lifter',
    );
    await _pumpHome(tester, fake, size: const Size(390, 844),
        extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
      featureEntriesProvider.overrideWithValue(<FeatureEntry>[...featureList, unsupported]),
    ]);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);
    router.go(featureGuidePath);
    await tester.pumpAndSettle();
    expect(find.text('Future feature'), findsNothing);

    final List<FeatureEntry> entries = featureList
        .where((FeatureEntry entry) => entry.audience == 'lifter')
        .toList(growable: false);
    for (final FeatureEntry entry in entries) {
      final Finder button = find.text('Show me').at(entries.indexOf(entry));
      await tester.ensureVisible(button);
      await tester.tap(button);
      await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
      await tester.pumpAndSettle();

      final int shellTab = container.read(playerShellTabProvider);
      final String routePath = router.routerDelegate.state.uri.path;
      expect(entry.location.matches(routePath, shellTab), isTrue,
          reason: '${entry.id} should land at its Feature list location; '
              'route=$routePath tab=$shellTab location=${entry.location} '
              'tour=${container.read(tourControllerProvider)} '
              'feature=${container.read(tourControllerProvider)?.featureId} '
              'visible=${container.read(tourControllerProvider)?.visible} '
              'events=${analytics.events}');
      expect(
        find.descendant(
          of: find.byType(SpotlightOverlay),
          matching: find.text(entry.titleEn),
        ),
        findsOneWidget,
        reason: '${entry.id} title should appear in the spotlight',
      );

      expect(find.descendant(of: find.byType(SpotlightOverlay), matching: find.text(entry.titleEn)), findsOneWidget, reason: entry.id);
      expect(find.descendant(of: find.byType(SpotlightOverlay), matching: find.text(entry.sentenceEn)), findsOneWidget, reason: entry.id);
      if (entry.id == 'brand-mayos') {
        final Finder logo = find.byKey(MayosAppHeader.brandKey);
        expect(logo, findsOneWidget);
        final Rect cutout = tester.getRect(find.byKey(const ValueKey<String>('tour_spotlight_cutout')));
        expect(cutout.contains(tester.getRect(logo).center), isTrue);
      }
      if (entry.release == currentFeatureRelease) {
        final Finder realControl = switch (entry.id) {
          'weak_points' => find.byKey(const Key('profile_weak_points_section')),
          'assistant_why' => find.byKey(const Key('chat_composer')),
          'add_exercises' => find.byKey(const Key('program_edit_day_1')),
          'edit_program_chat' => find.byKey(const Key('chat_composer_bar')),
          'movements_to_avoid' => find.byKey(const Key('profile_movement_restrictions_section')),
          'brand-mayos' => find.byKey(MayosAppHeader.brandKey),
          'workout_share_card' || 'duration_check' => find.text('Log workout'),
          'food_log' => find.byKey(const Key('food_log_entry_point')),
          'meal_setup' => find.byKey(const Key('meal_setup_entry')),
          'food_swap_requests' => find.byKey(const Key('food_swap_requests_entry')),
          'assistant_meals' => find.byTooltip('Assistant'),
          _ => find.text(entry.titleEn),
        };
        expect(realControl, findsOneWidget, reason: entry.id);
        final Rect cutout = tester.getRect(find.byKey(const ValueKey<String>('tour_spotlight_cutout')));
        expect(cutout.contains(tester.getRect(realControl).center), isTrue, reason: '${entry.id} control should be inside the spotlight');
      }

      await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey<String>('tour_next')), findsNothing);
      router.go(featureGuidePath);
      await tester.pumpAndSettle();
    }

    expect(
      analytics.events.where((event) => event['event'] == 'show_me_tapped')
          .map((event) => (event['properties'] as Map<String, Object>)['feature_id'])
          .toList(),
      entries.map((FeatureEntry entry) => entry.id).toList(),
    );
  });

  testWidgets('Show me to Profile preserves the guide as the Back destination',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake, size: const Size(390, 844));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);
    router.go(featureGuidePath);
    await tester.pumpAndSettle();
    final List<FeatureEntry> entries = featureList
        .where((FeatureEntry entry) => entry.audience == 'lifter')
        .toList();
    final FeatureEntry profile = entries.firstWhere(
      (FeatureEntry entry) => entry.id == 'profile',
    );
    await tester.ensureVisible(find.text('Show me').at(entries.indexOf(profile)));
    await tester.tap(find.text('Show me').at(entries.indexOf(profile)));
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    await tester.pumpAndSettle();
    expect(router.routerDelegate.state.uri.path, profilePath);
    await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
    await tester.pumpAndSettle();
    router.pop();
    await tester.pumpAndSettle();
    expect(router.routerDelegate.state.uri.path, featureGuidePath);
    expect(find.text('Feature guide'), findsWidgets);
  });

  testWidgets('Show me leaves tour seen version unchanged and is blocked by workout',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 1;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);
    router.go(featureGuidePath);
    await tester.pumpAndSettle();
    final ActiveWorkout workout = ActiveWorkout.fromJson(<String, dynamic>{
      'id': 'feature-guide-workout',
      'account_id': 'account-alice',
      'started_at': '2026-10-28T10:00:00Z',
      'day_order': 1,
      'day_name': 'Upper 1',
      'exercises': <dynamic>[],
      'baselines': <String, dynamic>{},
    });
    container.read(activeWorkoutControllerProvider.notifier).state =
        ActiveWorkoutState(
      accountId: 'account-alice',
      ready: true,
      workout: workout,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show me').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_next')), findsNothing);
    expect(router.routerDelegate.state.uri.path, featureGuidePath);
    expect(fake.tourSeenVersion, 1);

    container.read(activeWorkoutControllerProvider.notifier).state =
        const ActiveWorkoutState(
      accountId: 'account-alice',
      ready: true,
      workout: null,
    );
    await tester.pumpAndSettle();
    final Account activeAccount =
        container.read(authControllerProvider).session!.account;
    final AppModeState activeMode = container.read(appModeControllerProvider);
    expect(activeMode.isResolvedFor(activeAccount.accountId), isTrue);
    expect(activeMode.mode, AppMode.player);
    await tester.tap(find.text('Show me').first);
    for (int attempt = 0;
        attempt < 40 &&
            find.byKey(const ValueKey<String>('tour_next')).evaluate().isEmpty;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(
      container.read(tourControllerProvider)?.visible,
      isTrue,
      reason: 'Show me session: ${container.read(tourControllerProvider)}; '
          'route: ${router.routerDelegate.state.uri.path}; '
          'targets: ${container.read(tourTargetRegistryProvider).keys}; '
          'workout: ${container.read(activeWorkoutControllerProvider)}',
    );
    expect(find.byKey(const ValueKey<String>('tour_next')), findsOneWidget);
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
  });

  testWidgets('Feature guide Show me analytics honors the account opt-out',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..analyticsAllowed = false;
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, size: const Size(390, 844),
        extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ]);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(routerProvider).go(featureGuidePath);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show me').first);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    expect(
      analytics.events.where((event) => event['event'] == 'show_me_tapped'),
      isEmpty,
    );
  });

  testWidgets('Tour version 2 only reaches accounts created at version 2',
      (tester) async {
    final FakeMayosApi oldAccount = _signedInFake()
      ..tourSeenVersion = 1
      ..tourCreatedVersion = 0;
    await _pumpHome(tester, oldAccount, extraOverrides: <Override>[
      tourCurrentVersionProvider.overrideWithValue(2),
    ], tourRetryStore: FakeTourSeenRetryStore());
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_next')), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    final FakeMayosApi newAccount = _signedInFake()
      ..tourSeenVersion = 1
      ..tourCreatedVersion = 2;
    await _pumpHome(tester, newAccount, extraOverrides: <Override>[
      tourCurrentVersionProvider.overrideWithValue(2),
    ], tourRetryStore: FakeTourSeenRetryStore());
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));
    expect(find.text('1 OF 7'), findsOneWidget);
  });

  testWidgets('Skip dismisses offline and retries the seen write on next Home open',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..tourSeenVersion = 0
      ..whatsNewSeenRelease = 0
      ..tourSeenWriteFailures = 5;
    final FakeTourSeenRetryStore retryStore = FakeTourSeenRetryStore();
    final FakeAnalyticsClient analytics = FakeAnalyticsClient();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      analyticsClientProvider.overrideWithValue(analytics),
    ], tourRetryStore: retryStore);
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_skip')));

    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
    expect(fake.tourSeenVersion, 0);
    expect(analytics.events.map((event) => event['event']), contains('tour_skipped'));
    expect(retryStore.pending.values, contains(1));

    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    container.read(playerShellTabProvider.notifier).state = 1;
    await tester.pumpAndSettle();
    container.read(routerProvider).go(workoutsPath);
    await tester.pumpAndSettle();
    container.read(routerProvider).go(homePath);
    await tester.pumpAndSettle();
    expect(find.text("What's new"), findsNothing);

    fake.tourSeenWriteFailures = 0;
    container.read(playerShellTabProvider.notifier).state = 1;
    await tester.pumpAndSettle();
    container.read(playerShellTabProvider.notifier).state = 0;
    await tester.pumpAndSettle();
    expect(fake.tourSeenVersion, 1);
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
  });

  testWidgets('Tour tooltip controls remain visible and tappable on a phone',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
    await _pumpHome(tester, fake, size: const Size(390, 844));
    await _pumpUntilFound(tester, find.byKey(const ValueKey<String>('tour_next')));

    final Rect nextRect = tester.getRect(find.byKey(const ValueKey<String>('tour_next')));
    final Rect skipRect = tester.getRect(find.byKey(const ValueKey<String>('tour_skip')));
    expect(nextRect.top, greaterThanOrEqualTo(0));
    expect(nextRect.bottom, lessThanOrEqualTo(844));
    expect(skipRect.top, greaterThanOrEqualTo(0));
    expect(skipRect.bottom, lessThanOrEqualTo(844));
    await tester.tap(find.byKey(const ValueKey<String>('tour_next')));
    await tester.pumpAndSettle();
    expect(find.text('2 OF 7'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('tour_skip')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey<String>('tour_skip')), findsNothing);
  });

  testWidgets('Arabic Tour tooltip actions fit 320 and 390 dp widths',
      (tester) async {
    for (final double width in <double>[320, 390]) {
      final FakeMayosApi fake = _signedInFake()..tourSeenVersion = 0;
      await _pumpHome(
        tester,
        fake,
        size: Size(width, 844),
        languageCode: 'ar',
      );
      await _pumpUntilFound(
        tester,
        find.byKey(const ValueKey<String>('tour_next')),
      );

      final Rect backRect = tester.getRect(
        find.byKey(const ValueKey<String>('tour_back')),
      );
      final Rect nextRect = tester.getRect(
        find.byKey(const ValueKey<String>('tour_next')),
      );
      expect(backRect.height, greaterThanOrEqualTo(44));
      expect(nextRect.height, greaterThanOrEqualTo(44));
      expect(backRect.left, greaterThanOrEqualTo(0));
      expect(nextRect.right, lessThanOrEqualTo(width));
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('home shows honest empty states without data', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.noActiveProgram = true;
    fake.scheduleEmpty = true;
    fake.volumeEmpty = true;
    fake.recordsEmpty = true;
    await _pumpHome(tester, fake);

    expect(find.text('No active program'), findsOneWidget);
    expect(
      find.text('Generate a program to see your next session here.'),
      findsOneWidget,
    );
    expect(find.text('Go to Program'), findsOneWidget);
    // With no program there is no next session at all — not even a placeholder.
    expect(find.text('Next session'), findsNothing);
    expect(find.text('No training day is scheduled yet.'), findsNothing);
    expect(find.text('No sets logged in the last 7 days.'), findsOneWidget);
    expect(find.text('No personal records yet.'), findsOneWidget);
  });

  testWidgets('the Personal records shelf localizes most reps and its value',
      (tester) async {
    for (final String language in <String>['en', 'ar']) {
      final FakeMayosApi fake = _signedInFake()
        ..personalRecordsBody = <Map<String, dynamic>>[
          <String, dynamic>{
            'exercise_id': 'push_up',
            'name': 'Push-up',
            'record_type': 'most_reps',
            'reps': 12,
            'value': 12,
            'prev_value': 8,
            'achieved_at': '2026-09-26T10:00:00Z',
            'session_id': 'session-2',
          },
        ];
      await _pumpHome(tester, fake, languageCode: language);

      expect(
        find.text(language == 'ar' ? 'أكبر عدد من التكرارات' : 'Most reps'),
        findsOneWidget,
      );
      expect(
          find.text(language == 'ar' ? '\u206612\u2069 تكرارًا' : '12 reps'),
          findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('the no-program action reaches the assistant from Program',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.noActiveProgram = true;
    fake.scheduleEmpty = true;
    fake.volumeEmpty = true;
    fake.recordsEmpty = true;
    await _pumpHome(tester, fake);

    await tester.tap(find.text('Go to Program'));
    await _pumpUntilFound(tester, find.text('Open assistant'));
    expect(find.text('Open assistant'), findsOneWidget);
    expect(find.text('Regenerate program'), findsNothing);

    await tester.tap(find.text('Open assistant'));
    await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
    expect(find.byKey(const Key('chat_composer')), findsOneWidget);
  });

  testWidgets('home reads the latest committed session from the ledger',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.latestSessionBody = <String, dynamic>{
      'session_id': 'sess-1',
      'session_date': '2026-09-20',
      'split_name': 'Upper 1',
      'day_order': null,
      'program_version': 1,
    };
    await _pumpHome(tester, fake);

    expect(
      fake.adapter.requests
          .any((request) => request.path == '/workouts/sessions/latest'),
      isTrue,
    );
    expect(find.text('Upper 1'), findsNWidgets(2));
  });

  testWidgets('delayed Home load does not cache Account A after switching to B',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..latestSessionBody = <String, dynamic>{
        'session_id': 'late-a',
        'session_date': '2026-09-20',
        'split_name': 'Upper 1',
        'day_order': null,
        'program_version': 1,
        'duration_seconds': 1800,
      };
    final _TrackingWorkoutCache cache = _TrackingWorkoutCache();
    final Completer<void> latestRequestStarted = Completer<void>();
    final Completer<void> releaseLatestRequest = Completer<void>();
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      workoutCacheStoreProvider.overrideWithValue(cache),
    ]);
    await _pumpUntilFound(tester, find.text('Upper 1'));
    cache.latestSessionWrites.clear();
    fake.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path == '/workouts/sessions/latest') {
        latestRequestStarted.complete();
        await releaseLatestRequest.future;
      }
    };
    await tester.drag(find.byType(ListView).first, const Offset(0, 600));
    await tester.pump();
    for (int attempt = 0;
        attempt < 40 && !latestRequestStarted.isCompleted;
        attempt++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(latestRequestStarted.isCompleted, isTrue);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    expect(container.read(authControllerProvider).session?.account.accountId,
        'account-alice');
    final AuthController auth = container.read(authControllerProvider.notifier);
    final AccountSession accountA = auth.state.session!;
    final AccountSession accountB = AccountSession(
      account: accountA.account.copyWith(
        accountId: 'account-bob',
        traineeId: 'bob',
      ),
      onboarded: true,
      hasRecoveryEmail: accountA.hasRecoveryEmail,
      recoveryEmail: accountA.recoveryEmail,
    );
    auth.state = const AuthState.unauthenticated();
    auth.state = AuthState.authenticated(accountB);
    await tester.pumpAndSettle();
    expect(container.read(authControllerProvider).session?.account.accountId,
        'account-bob');
    expect(find.byType(DashboardTab), findsOneWidget);
    releaseLatestRequest.complete();
    await tester.pumpAndSettle();
    expect(
      fake.adapter.requests
          .where((request) => request.path == '/workouts/sessions/latest')
          .length,
      greaterThanOrEqualTo(2),
    );
    expect(cache.latestSessionWrites, isNot(contains('account-alice')));
  });

  testWidgets('latest saved workout on Home offers Share to Story', (tester) async {
    int shareCalls = 0;
    WorkoutShareCard? sharedCard;
    final FakeMayosApi fake = _signedInFake()
      ..latestSessionBody = <String, dynamic>{
        'session_id': 'sess-share',
        'session_date': '2026-09-20',
        'split_name': 'Upper 1',
        'day_order': null,
        'program_version': 1,
        'duration_seconds': 3600,
        'working_sets': 3,
        'volume_kg': 1500,
        'pr_count': 2,
      };
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      workoutCardShareProvider.overrideWithValue((BuildContext context, WorkoutShareCard card) async {
        shareCalls++;
        sharedCard = card;
        return true;
      }),
    ]);
    expect(find.text('Upper 1'), findsNWidgets(2));
    expect(find.text('Share to Story'), findsOneWidget);
    await tester.ensureVisible(find.text('Share to Story'));
    await tester.tap(find.text('Share to Story'));
    await tester.pumpAndSettle();
    expect(find.text('Choose from gallery'), findsOneWidget);
    expect(find.text('No photo'), findsOneWidget);
    await tester.tap(find.text('No photo'));
    await tester.pumpAndSettle();
    expect(shareCalls, 1);
    expect(sharedCard?.performedDate, DateTime(2026, 9, 20));
  });

  testWidgets('double tapping Share to Story starts one share flow', (tester) async {
    int pickerCalls = 0;
    final FakeMayosApi fake = _signedInFake()
      ..latestSessionBody = <String, dynamic>{
        'session_id': 'sess-double-share', 'session_date': '2026-09-20',
        'split_name': 'Upper 1', 'day_order': null, 'program_version': 1,
      };
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      workoutImagePickerProvider.overrideWithValue((_) async {
        pickerCalls++;
        return null;
      }),
      workoutCardShareProvider.overrideWithValue((_, __) async => true),
    ]);
    await tester.ensureVisible(find.text('Share to Story'));
    await tester.tap(find.text('Share to Story'));
    await tester.tap(find.text('Share to Story'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Choose from gallery'));
    await tester.pumpAndSettle();
    expect(pickerCalls, 1);
    await tester.tap(find.text('No photo'));
    await tester.pumpAndSettle();
  });

  testWidgets('Home State survives app pause and resume account and policy refreshes', (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpHome(tester, fake);
    final State homeState = tester.state(find.byType(DashboardTab));
    final int policyCallsBefore = fake.adapter.requests
        .where((request) => request.path == '/app/version-policy').length;
    final int accountCallsBefore = fake.adapter.requests
        .where((request) => request.path == '/auth/me').length;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(fake.adapter.requests.where((request) => request.path == '/app/version-policy').length,
        greaterThan(policyCallsBefore));
    expect(fake.adapter.requests.where((request) => request.path == '/auth/me').length,
        greaterThan(accountCallsBefore));
    expect(tester.state(find.byType(DashboardTab)), same(homeState));
  });

  testWidgets('Home sharing survives Home disposal while the gallery is open', (tester) async {
    final Completer<XFile?> pendingPicker = Completer<XFile?>();
    final Completer<Uint8List> pendingCapture = Completer<Uint8List>();
    final Uint8List photo = _validTestPng();
    WorkoutShareCard? sharedCard;
    final FakeMayosApi fake = _signedInFake()
      ..latestSessionBody = <String, dynamic>{
        'session_id': 'sess-dispose', 'session_date': '2026-09-20',
        'split_name': 'Upper 1', 'day_order': null, 'program_version': 1,
        'duration_seconds': 3600, 'working_sets': 3, 'volume_kg': 1500,
      };
    await _pumpHome(tester, fake, extraOverrides: <Override>[
      workoutImagePickerProvider.overrideWithValue((_) => pendingPicker.future),
      workoutCardShareProvider.overrideWithValue((BuildContext context, WorkoutShareCard card) async {
        sharedCard = card;
        return captureAndPreviewWorkoutCard(context, card,
          capture: () => pendingCapture.future, feedback: card.feedback);
      }),
    ]);
    final GoRouter router = ProviderScope.containerOf(tester.element(find.text('Share to Story')))
        .read(routerProvider);
    await tester.tap(find.text('Share to Story'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Choose from gallery'));
    await tester.pumpAndSettle();
    router.go(workoutsPath);
    await tester.pumpAndSettle();
    expect(find.byType(DashboardTab), findsNothing);
    pendingPicker.complete(XFile.fromData(photo));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(await sharedCard?.photoFile?.readAsBytes(), orderedEquals(photo));
    expect(find.text('Preparing your card…'), findsOneWidget);
    pendingCapture.complete(_validTestPng());
    await tester.pumpAndSettle();
    expect(find.text('Save image'), findsOneWidget);
    expect(await sharedCard?.photoFile?.readAsBytes(), orderedEquals(photo));
    await tester.tap(find.byTooltip('Close'));
    await tester.pumpAndSettle();
  });

  testWidgets('home opens an unopened Checkpoint review and clears its card',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..checkpointReviewRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'checkpoint': 10,
          'period_start': '2026-01-01',
          'period_end': '2026-09-30',
          'rating': <Map<String, dynamic>>[
            <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
          ],
          'opened': false,
        },
      ]
      ..checkpointReviewDetails[10] = <String, dynamic>{
        'checkpoint': 10,
        'period_start': '2026-01-01',
        'period_end': '2026-09-30',
        'facts': <String, dynamic>{'workouts_in_period': 10},
        'rating': <Map<String, dynamic>>[
          <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
        ],
        'text':
            'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'text_is_template': true,
      };
    await _pumpHome(tester, fake);
    final ProviderContainer container =
        ProviderScope.containerOf(tester.element(find.byType(MayosApp)));
    final GoRouter router = container.read(routerProvider);

    expect(find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
        findsOneWidget);
    await tester.tap(
      find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const ValueKey<String>('checkpoint.review.title')),
    );
    expect(find.text('Consistency'), findsOneWidget);
    expect(find.text('Strong'), findsOneWidget);
    expect(
      find.text(
        'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
      ),
      findsOneWidget,
    );

    router.pop();
    await tester.pumpAndSettle();
    expect(router.routerDelegate.state.uri.path, homePath);
    expect(find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
        findsNothing);
  });

  testWidgets('Arabic Checkpoint title keeps its ordinal and date range LTR',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..checkpointReviewRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'checkpoint': 10,
          'period_start': '2026-01-01',
          'period_end': '2026-09-30',
          'rating': <Map<String, dynamic>>[
            <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
          ],
          'opened': false,
        },
      ]
      ..checkpointReviewDetails[10] = <String, dynamic>{
        'checkpoint': 10,
        'period_start': '2026-01-01',
        'period_end': '2026-09-30',
        'facts': <String, dynamic>{'workouts_in_period': 10},
        'rating': <Map<String, dynamic>>[
          <String, dynamic>{'part': 'Consistency', 'label': 'Strong'},
        ],
        'text':
            'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'text_is_template': true,
      };
    await _pumpHome(tester, fake, languageCode: 'ar');
    await tester.tap(
      find.byKey(const ValueKey<String>('dashboard.checkpoint-review')),
    );
    await _pumpUntilFound(
      tester,
      find.byKey(const ValueKey<String>('checkpoint.review.title')),
    );

    expect(
      find.byKey(const ValueKey<String>('checkpoint.review.title')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey<String>('checkpoint.review.checkpoint')),
      findsOneWidget,
    );
    final Text period = tester.widget<Text>(
      find.byKey(const ValueKey<String>('checkpoint.review.period')),
    );
    expect(period.data, '2026-01-01 – 2026-09-30');
    expect(period.textDirection, TextDirection.ltr);
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets('home renders in ${mode.name} theme without overflow',
        (tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpHome(
        tester,
        fake,
        themeStore: InMemoryThemeModeStore(mode),
        size: const Size(360, 640),
      );

      // Let the home data and the persisted theme settle before checking for
      // layout overflow at the largest supported text scale.
      await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));
      expect(
        Theme.of(tester.element(find.text('Upper/Lower 4x'))).brightness,
        mode == ThemeMode.dark ? Brightness.dark : Brightness.light,
      );

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });
  }
}
