import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'fake_analytics_client.dart';
import 'fake_google_auth.dart';
import 'fake_mayos_api.dart';

/// A [ProviderContainer] wired to [fake] with an in-memory token store, for the
/// non-widget auth tests.
ProviderContainer authContainerFor(
    FakeMayosApi fake, InMemoryTokenStore tokens,
    {FakeAnalyticsClient? analytics, FakeGoogleAuthGateway? google}) {
  final FakeAnalyticsClient fakeAnalytics = analytics ?? FakeAnalyticsClient();
  return ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      analyticsClientProvider.overrideWithValue(fakeAnalytics),
      if (google != null) googleAuthGatewayProvider.overrideWithValue(google),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
      displayLanguageStoreProvider
          .overrideWithValue(InMemoryDisplayLanguageStore()),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      apiClientProvider.overrideWith((ref) {
        final ApiClient client = ApiClient(
          tokens: ref.watch(tokenStoreProvider),
          baseUrl: 'http://test.local',
          adapter: fake.adapter,
        );
        client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
        client.onAppUpdateRequired = (AppVersionPolicy policy) {
          ref
              .read(appUpdateRequiredProvider.notifier)
              .requireUpdate(policy);
        };
        return client;
      }),
    ],
  );
}

/// The full app under test wired to [fake], for the widget auth tests.
///
/// [extraOverrides] lets a test replace a provider the auth screens reach for
/// (for example the privacy-policy browser hand-off) without forking the
/// harness.
Widget authApp(FakeMayosApi fake, InMemoryTokenStore tokens,
    {List<Override> extraOverrides = const <Override>[],
    FakeAnalyticsClient? analytics,
    InMemoryAppModeStore? modeStore}) {
  final FakeAnalyticsClient fakeAnalytics = analytics ?? FakeAnalyticsClient();
  return ProviderScope(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      analyticsClientProvider.overrideWithValue(fakeAnalytics),
      appModeStoreProvider
          .overrideWithValue(modeStore ?? InMemoryAppModeStore()),
      displayLanguageStoreProvider
          .overrideWithValue(InMemoryDisplayLanguageStore()),
      chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
      apiClientProvider.overrideWith((ref) {
        final ApiClient client = ApiClient(
          tokens: ref.watch(tokenStoreProvider),
          baseUrl: 'http://test.local',
          adapter: fake.adapter,
        );
        client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
        client.onAppUpdateRequired = (AppVersionPolicy policy) {
          ref
              .read(appUpdateRequiredProvider.notifier)
              .requireUpdate(policy);
        };
        return client;
      }),
      ...extraOverrides,
    ],
    child: const MayosApp(),
  );
}
