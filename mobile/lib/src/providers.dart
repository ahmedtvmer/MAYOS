import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart'
    show GlobalKey, ScaffoldMessengerState, SnackBar, Text, ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/account_data_eraser.dart';
import 'core/active_workout.dart';
import 'core/api_client.dart';
import 'core/app_mode.dart';
import 'core/baseline_service.dart';
import 'core/baselines.dart';
import 'core/chat_storage.dart';
import 'core/config.dart';
import 'core/models.dart';
import 'core/personal_records.dart';
import 'core/rest_alerts.dart';
import 'core/rest_length.dart';
import 'core/theme/theme_mode_controller.dart';
import 'core/theme/theme_mode_store.dart';
import 'core/token_store.dart';
import 'core/workout_storage.dart';
import 'features/coach/coach_assistant_state.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/auth_repository.dart';
import 'features/player/workout/active_workout_controller.dart';
import 'features/player/workout/draft_sync_service.dart';

final Provider<TokenStore> tokenStoreProvider = Provider<TokenStore>(
  (ref) => SecureTokenStore(),
);

/// Device-level appearance persistence (System/Light/Dark).
final Provider<ThemeModeStore> themeModeStoreProvider =
    Provider<ThemeModeStore>((ref) => SecureThemeModeStore());

final StateNotifierProvider<ThemeModeController, ThemeMode>
    themeModeControllerProvider =
    StateNotifierProvider<ThemeModeController, ThemeMode>((ref) {
  return ThemeModeController(ref.watch(themeModeStoreProvider));
});

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
      baselines: ref.watch(baselineCacheStoreProvider),
      activeWorkout: ref.watch(activeWorkoutStoreProvider),
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

/// Device-level persistence of the last Player mode / Coach mode per account
/// (issue #119).
final Provider<AppModeStore> appModeStoreProvider =
    Provider<AppModeStore>((ref) => SecureAppModeStore());

/// The effective mode for the signed-in account, resolved from the stored
/// choice and the live coach capability. Not `ready` until the account's
/// stored choice has been read, so the app never flashes the wrong shell.
final StateNotifierProvider<AppModeController, AppModeState>
    appModeControllerProvider =
    StateNotifierProvider<AppModeController, AppModeState>((ref) {
  final AppModeController controller =
      AppModeController(ref.watch(appModeStoreProvider));
  ref.listen<AuthState>(authControllerProvider,
      (AuthState? previous, AuthState next) {
    final Account? account = next.session?.account;
    controller.syncAccount(
      accountId: account?.accountId,
      isCoach: account?.isCoach ?? false,
    );
  }, fireImmediately: true);
  return controller;
});

/// The coach assistant's in-memory transcript for ONE selected player (#45).
///
/// It is never written to secure storage, caches, shared preferences, or logs,
/// so nothing survives app close. The auth listener below clears it on logout,
/// session teardown, loss of the coach capability, and loss of the feature flag
/// (a resumed app re-reads `GET /auth/me`); `CoachAssistantController` clears it
/// on player switch and on a revoked/ended assignment; `MayosApp` clears it on
/// `AppLifecycleState.detached`.
final StateNotifierProvider<CoachAssistantController, CoachAssistantTranscript?>
    coachAssistantControllerProvider =
    StateNotifierProvider<CoachAssistantController, CoachAssistantTranscript?>(
        (ref) {
  final CoachAssistantController controller = CoachAssistantController();
  ref.listen<AuthState>(authControllerProvider,
      (AuthState? previous, AuthState next) {
    final Account? account = next.session?.account;
    // A signed-out session, a lost coach capability, or a switched-off feature
    // all end the assistant's context (issue #45).
    if (!next.isAuthenticated ||
        account == null ||
        !account.isCoach ||
        !account.coachAiEnabled) {
      controller.clear();
    }
  });
  return controller;
});

/// Whether this client captures protected offline workout drafts (ADR 020).
///
/// Offline drafts are Android-only (ADR 022): the web client stays online-only
/// and must never write training data to browser storage. The web target
/// therefore falls back to in-memory stores and hides the offline entry points.
final Provider<bool> offlineWorkoutDraftsEnabledProvider =
    Provider<bool>((ref) => !kIsWeb);

/// The wall clock **Workout time** reads: the top bar's label and the
/// workout summary's duration snapshot (#159). Injectable so a test can tick
/// it and pin the snapshot without waiting on the real clock.
final Provider<DateTime Function()> clockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);

/// The workout summary the logger is showing (#159): Finish takes the
/// snapshot, Back drops it. While it is set the top bar freezes Workout time
/// at the snapshot's duration, so no live clock ticks next to the summary's
/// frozen "Duration"; dropping it resumes the live tick.
final StateProvider<WorkoutSummary?> loggerSummaryProvider =
    StateProvider<WorkoutSummary?>((ref) => null);

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

/// Runs [reset] whenever the signed-in account changes or the session ends.
///
/// The listener sits on the auth state itself, so the reset lands with the
/// same synchronous notification that changes the session and no rebuilt shell
/// can read the previous account's value (#119).
void _resetOnAccountChange(Ref ref, void Function() reset) {
  String? account = ref.read(authControllerProvider).session?.account.accountId;
  ref.listen<AuthState>(authControllerProvider, (_, AuthState next) {
    final String? nextAccount = next.session?.account.accountId;
    if (nextAccount != account) {
      account = nextAccount;
      reset();
    }
  });
}

/// The selected bottom-navigation tab in the player shell (0 = Home,
/// 1 = Program, 2 = Progress). Home's no-program state points at Program so the
/// player can generate a program through the existing Program-tab flow.
final StateProvider<int> playerShellTabProvider =
    StateProvider<int>((ref) => 0);

/// The selected bottom-navigation tab in the coach shell (0 = Roster,
/// 1 = Alerts, 2 = Requests, 3 = Profile; the named constants live in
/// `coach_shell.dart`). The shell opens on Roster, and so does a newly
/// signed-in account: the tab resets whenever the account changes (#119).
final StateProvider<int> coachShellTabProvider = StateProvider<int>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = 0);
  return 0;
});

/// The number of coach alerts still in the `new` state, published by the
/// Alerts tab so the shell's badge tracks acknowledge/resolve without a second
/// fetch. It resets whenever the account changes, so one account's badge count
/// is never shown for another (#119).
final StateProvider<int> coachNewAlertsCountProvider =
    StateProvider<int>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = 0);
  return 0;
});

/// Bumped whenever a coaching action changes what a roster row shows
/// (acknowledge/resolve on either the player page or the Alerts tab, and a
/// saved check-in). The Roster tab listens and reloads in the background, so
/// the row's chips track the action without a restart (#120).
///
/// Only producers bump it; the Roster tab never does, so a bump cannot loop.
final StateProvider<int> coachRosterRevisionProvider =
    StateProvider<int>((ref) => 0);

/// Bumped whenever a coach alert is acknowledged or resolved outside the
/// Alerts tab (the player page). The Alerts tab listens and refetches, which
/// also republishes [coachNewAlertsCountProvider] (#120).
///
/// Only the player page bumps it; the Alerts tab never does, so a bump cannot
/// loop.
final StateProvider<int> coachAlertsRevisionProvider =
    StateProvider<int>((ref) => 0);

/// The number of the coach's pending program requests, published by the
/// Requests tab so the shell's badge tracks apply/decline without a second
/// fetch. It resets whenever the account changes, so one account's badge count
/// is never shown for another (#119/#121).
final StateProvider<int> coachPendingRequestsCountProvider =
    StateProvider<int>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = 0);
  return 0;
});

/// Bumped whenever a program request is applied or declined outside the
/// Requests tab (the player page). The Requests tab listens and refetches,
/// which also republishes [coachPendingRequestsCountProvider] (#121).
///
/// Only the player page bumps it; the Requests tab never does, so a bump
/// cannot loop.
final StateProvider<int> coachRequestsRevisionProvider =
    StateProvider<int>((ref) => 0);

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

/// Protected, account-separated cache of the last successful
/// `GET /workouts/baselines` fetch (#123). Same offline gate as the drafts:
/// the web client never writes training data to browser storage (ADR 022).
final Provider<BaselineCacheStore> baselineCacheStoreProvider =
    Provider<BaselineCacheStore>((ref) =>
        ref.watch(offlineWorkoutDraftsEnabledProvider)
            ? SecureBaselineCacheStore()
            : InMemoryBaselineCacheStore());

/// Device storage for the single Active workout held per account (#123).
final Provider<ActiveWorkoutStore> activeWorkoutStoreProvider =
    Provider<ActiveWorkoutStore>((ref) =>
        ref.watch(offlineWorkoutDraftsEnabledProvider)
            ? SecureActiveWorkoutStore()
            : InMemoryActiveWorkoutStore());

/// The baselines reader: Home's fire-and-forget prefetch and the fresh →
/// cache → empty resolution a workout start freezes (#123).
final Provider<BaselinesService> baselinesServiceProvider =
    Provider<BaselinesService>((ref) => BaselinesService(
          api: ref.watch(apiClientProvider),
          cache: ref.watch(baselineCacheStoreProvider),
          drafts: ref.watch(draftStoreProvider),
        ));

/// The root scaffold messenger, so a one-line explanation raised outside any
/// screen's own messenger — the rest-alarm permission ask (#125) — still has
/// somewhere to appear.
final GlobalKey<ScaffoldMessengerState> mayosMessengerKey =
    GlobalKey<ScaffoldMessengerState>();

/// The one seam to the platform's rest-alert machinery (notification, alarm,
/// end-of-rest sound/vibration, #125): the real Android implementation on
/// Android, in-app-only no-op elsewhere (web included).
final Provider<RestAlerts> restAlertsProvider = Provider<RestAlerts>((ref) {
  return platformRestAlerts(
    explain: (String line) =>
        mayosMessengerKey.currentState?.showSnackBar(
      SnackBar(content: Text(line)),
    ),
  );
});

/// Device persistence for the player's per-exercise rest overrides, per
/// account (#125) — the same online/offline gate as the other protected
/// stores, so web never writes to browser storage (ADR 022).
final Provider<RestLengthStore> restLengthStoreProvider =
    Provider<RestLengthStore>((ref) =>
        ref.watch(offlineWorkoutDraftsEnabledProvider)
            ? SecureRestLengthStore()
            : InMemoryRestLengthStore());

/// The signed-in account's Active workout, restored from device storage when
/// the session resolves and persisted after every change (#123).
final StateNotifierProvider<ActiveWorkoutController, ActiveWorkoutState>
    activeWorkoutControllerProvider =
    StateNotifierProvider<ActiveWorkoutController, ActiveWorkoutState>((ref) {
  final ApiClient api = ref.watch(apiClientProvider);
  final WorkoutCacheStore cache = ref.watch(workoutCacheStoreProvider);
  final ActiveWorkoutController controller = ActiveWorkoutController(
    store: ref.watch(activeWorkoutStoreProvider),
    baselines: ref.watch(baselinesServiceProvider),
    // The prescription a start seeds and hints from: fresh with a short
    // timeout, else the cache, as the old logger resolved it (#123).
    loadPrescription: (String accountId, int dayOrder) => prescriptionAtStart(
      api: api,
      cache: cache,
      accountId: accountId,
      dayOrder: dayOrder,
    ),
    restLengths: ref.watch(restLengthStoreProvider),
    alerts: ref.watch(restAlertsProvider),
  );
  ref.listen<AuthState>(authControllerProvider,
      (AuthState? previous, AuthState next) {
    final String? accountId = next.session?.account.accountId;
    if (next.isAuthenticated && accountId != null) {
      controller.syncAccount(accountId);
    } else {
      controller.syncAccount(null);
    }
  }, fireImmediately: true);
  return controller;
});
