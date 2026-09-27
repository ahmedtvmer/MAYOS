import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/account_data_eraser.dart';
import 'core/api_client.dart';
import 'core/chat_storage.dart';
import 'core/config.dart';
import 'core/token_store.dart';
import 'core/workout_storage.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/auth_repository.dart';
import 'features/player/workout/draft_sync_service.dart';

final Provider<TokenStore> tokenStoreProvider = Provider<TokenStore>(
  (ref) => SecureTokenStore(),
);

final Provider<UnauthorizedEvents> unauthorizedEventsProvider =
    Provider<UnauthorizedEvents>((ref) {
  final UnauthorizedEvents events = UnauthorizedEvents();
  ref.onDispose(events.dispose);
  return events;
});

/// Signals an `account_deleted` 401 so the app erases the account's protected
/// local data instead of offering the logout keep/discard prompt (ADR 039).
final Provider<AccountDeletedEvents> accountDeletedEventsProvider =
    Provider<AccountDeletedEvents>((ref) {
  final AccountDeletedEvents events = AccountDeletedEvents();
  ref.onDispose(events.dispose);
  return events;
});

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  final TokenStore tokens = ref.watch(tokenStoreProvider);
  final ApiClient client = ApiClient(tokens: tokens, baseUrl: apiBaseUrl);
  client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
  client.onAccountDeleted = ref.watch(accountDeletedEventsProvider).signal;
  return client;
});

final Provider<AuthRepository> authRepositoryProvider =
    Provider<AuthRepository>(
  (ref) => AuthRepository(
    api: ref.watch(apiClientProvider),
    tokens: ref.watch(tokenStoreProvider),
    chatCache: ref.watch(chatCacheStoreProvider),
    eraser: AccountDataEraser(
      drafts: ref.watch(draftStoreProvider),
      workoutCache: ref.watch(workoutCacheStoreProvider),
      chatCache: ref.watch(chatCacheStoreProvider),
    ),
  ),
);

final StateNotifierProvider<AuthController, AuthState> authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(
    ref.watch(authRepositoryProvider),
    ref.watch(unauthorizedEventsProvider),
    ref.watch(accountDeletedEventsProvider),
  );
});

/// Whether this client captures protected offline workout drafts (ADR 020).
///
/// Offline drafts are Android-only (ADR 022): the web client stays online-only
/// and must never write training data to browser storage. The web target
/// therefore falls back to in-memory stores and hides the offline entry points.
final Provider<bool> offlineWorkoutDraftsEnabledProvider =
    Provider<bool>((ref) => !kIsWeb);

/// Protected, account-separated storage for offline workout drafts.
final Provider<DraftStore> draftStoreProvider = Provider<DraftStore>((ref) =>
    ref.watch(offlineWorkoutDraftsEnabledProvider)
        ? SecureDraftStore()
        : InMemoryDraftStore());

/// Protected cache of the active program and its prescription for offline logging.
final Provider<WorkoutCacheStore> workoutCacheStoreProvider =
    Provider<WorkoutCacheStore>((ref) =>
        ref.watch(offlineWorkoutDraftsEnabledProvider)
            ? SecureWorkoutCacheStore()
            : InMemoryWorkoutCacheStore());

/// Protected, account-separated disclosure acceptance and chat-history cache
/// for read-only offline viewing (#37, ADR 016/036).
final Provider<ChatCacheStore> chatCacheStoreProvider =
    Provider<ChatCacheStore>((ref) =>
        ref.watch(offlineWorkoutDraftsEnabledProvider)
            ? SecureChatCacheStore()
            : InMemoryChatCacheStore());

/// Processes the logged-in account's drafts on login, after a save, on demand,
/// and periodically while the app is in the foreground (ADR 020/033).
final ChangeNotifierProvider<DraftSyncService> draftSyncServiceProvider =
    ChangeNotifierProvider<DraftSyncService>((ref) {
  final DraftSyncService service = DraftSyncService(
    api: ref.watch(apiClientProvider),
    store: ref.watch(draftStoreProvider),
  );
  ref.listen<AuthState>(authControllerProvider,
      (AuthState? previous, AuthState next) {
    final String? accountId = next.session?.account.accountId;
    if (next.isAuthenticated && accountId != null) {
      service.startFor(accountId);
    } else {
      service.stop();
    }
  }, fireImmediately: true);
  return service;
});
