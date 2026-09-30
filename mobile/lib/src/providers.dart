import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart'
    show GlobalKey, ScaffoldMessengerState, SnackBar, Text, ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/account_data_eraser.dart';
import 'core/active_program.dart';
import 'core/active_workout.dart';
import 'core/api_client.dart';
import 'core/app_mode.dart';
import 'core/baseline_service.dart';
import 'core/baselines.dart';
import 'core/browser_key_value_store.dart';
import 'core/chat_storage.dart';
import 'core/config.dart';
import 'core/models.dart';
import 'core/personal_records.dart';
import 'core/rest_alerts.dart';
import 'core/rest_length.dart';
import 'core/theme/theme_mode_controller.dart';
import 'core/theme/theme_mode_store.dart';
import 'core/training_status_controller.dart';
import 'core/token_store.dart';
import 'core/web_active_workout_store.dart';
import 'core/workout_start_notice_store.dart';
import 'core/workout_storage.dart';
import 'features/coach/coach_assistant_state.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/auth_repository.dart';
import 'features/player/auth/google_auth_gateway.dart';
import 'features/player/workout/active_workout_controller.dart';
import 'features/player/workout/draft_sync_service.dart';
import 'features/player/workout/web_workout_committer.dart';

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
          workoutStartNotice: ref.watch(workoutStartNoticeStoreProvider),
        ),
      ),
    );

final StateNotifierProvider<AuthController, AuthState> authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
      return AuthController(
        ref.watch(authRepositoryProvider),
        ref.watch(unauthorizedEventsProvider),
        ref.watch(accountDeletedEventsProvider),
        ref.watch(googleAuthGatewayProvider),
      );
    });

/// The one seam to the Google SDK (#115): tests replace it with a fake, and
/// the web half (#127) plugs in behind the same interface.
final Provider<GoogleAuthGateway> googleAuthGatewayProvider =
    Provider<GoogleAuthGateway>((ref) => GoogleSdkAuthGateway());

/// Device-level persistence of the last Player mode / Coach mode per account
/// (issue #119).
final Provider<AppModeStore> appModeStoreProvider = Provider<AppModeStore>(
  (ref) => SecureAppModeStore(),
);

/// The effective mode for the signed-in account, resolved from the stored
/// choice and the live coach capability. Not `ready` until the account's
/// stored choice has been read, so the app never flashes the wrong shell.
final StateNotifierProvider<AppModeController, AppModeState>
appModeControllerProvider =
    StateNotifierProvider<AppModeController, AppModeState>((ref) {
      final AppModeController controller = AppModeController(
        ref.watch(appModeStoreProvider),
      );
      ref.listen<AuthState>(authControllerProvider, (
        AuthState? previous,
        AuthState next,
      ) {
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
    StateNotifierProvider<CoachAssistantController, CoachAssistantTranscript?>((
      ref,
    ) {
      final CoachAssistantController controller = CoachAssistantController();
      ref.listen<AuthState>(authControllerProvider, (
        AuthState? previous,
        AuthState next,
      ) {
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
/// Offline Workout drafts remain Android-only (ADR 022). On web, only the
/// account-scoped Active workout and its first-start notice use browser storage;
/// every other protected store stays in memory.
final Provider<bool> offlineWorkoutDraftsEnabledProvider = Provider<bool>(
  (ref) => !kIsWeb,
);

/// The web Active workout commits directly instead of becoming a Workout
/// draft. Injectable so tests can exercise the web flow on a native host.
final Provider<bool> webDirectWorkoutCommitEnabledProvider = Provider<bool>(
  (ref) => !ref.watch(offlineWorkoutDraftsEnabledProvider),
);

final Provider<BrowserKeyValueStore> browserKeyValueStoreProvider =
    Provider<BrowserKeyValueStore>((ref) => createBrowserKeyValueStore());

/// The wall clock **Workout time** reads: the top bar's label and the
/// workout summary's duration snapshot (#159). Injectable so a test can tick
/// it and pin the snapshot without waiting on the real clock.
final Provider<DateTime Function()> clockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);

/// Flutter lifecycle changes reflect browser tab visibility on web. Injectable
/// so widget tests can exercise that path on the native test host.
final Provider<bool> webPageVisibilityEnabledProvider = Provider<bool>(
  (ref) => kIsWeb,
);

/// The workout summary the logger is showing (#159): Finish takes the
/// snapshot, Back drops it. While it is set the top bar freezes Workout time
/// at the snapshot's duration, so no live clock ticks next to the summary's
/// frozen "Duration"; dropping it resumes the live tick.
final StateProvider<WorkoutSummary?> loggerSummaryProvider =
    StateProvider<WorkoutSummary?>((ref) => null);

/// Protected, account-separated storage for offline workout drafts.
final Provider<DraftStore> draftStoreProvider = Provider<DraftStore>(
  (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
      ? SecureDraftStore()
      : InMemoryDraftStore(),
);

/// Protected cache of the active program and its prescription for offline logging.
final Provider<WorkoutCacheStore> workoutCacheStoreProvider =
    Provider<WorkoutCacheStore>(
      (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
          ? SecureWorkoutCacheStore()
          : InMemoryWorkoutCacheStore(),
    );

/// Last-known server training status, loaded at app start and persisted with
/// the Android workout cache for the Finish summary (#220).
final StateNotifierProvider<TrainingStatusController, TrainingStatus?>
    trainingStatusProvider =
    StateNotifierProvider<TrainingStatusController, TrainingStatus?>((ref) {
  final TrainingStatusController controller = TrainingStatusController(
    api: ref.watch(apiClientProvider),
    cache: ref.watch(workoutCacheStoreProvider),
  );
  ref.listen<AuthState>(
    authControllerProvider,
    (AuthState? previous, AuthState next) {
      controller.syncAccount(
        next.isAuthenticated ? next.session?.account.accountId : null,
      );
    },
    fireImmediately: true,
  );
  return controller;
});

final FutureProvider<List<CheckpointReviewListItem>> checkpointReviewsProvider =
    FutureProvider<List<CheckpointReviewListItem>>(
  (ref) => ref.watch(apiClientProvider).checkpointReviews(),
);

final checkpointReviewProvider = FutureProvider.family<CheckpointReview, int>(
  (ref, int checkpoint) =>
      ref.watch(apiClientProvider).checkpointReview(checkpoint),
);

/// Protected, account-separated disclosure acceptance and chat-history cache
/// for read-only offline viewing (#37, ADR 016/036).
final Provider<ChatCacheStore> chatCacheStoreProvider =
    Provider<ChatCacheStore>(
      (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
          ? SecureChatCacheStore()
          : InMemoryChatCacheStore(),
    );

final Provider<WebActiveWorkoutStore> webActiveWorkoutStoreProvider =
    Provider<WebActiveWorkoutStore>(
      (ref) => WebActiveWorkoutStore(
        storage: ref.watch(browserKeyValueStoreProvider),
      ),
    );

final Provider<WorkoutStartNoticeStore> workoutStartNoticeStoreProvider =
    Provider<WorkoutStartNoticeStore>(
      (ref) => ref.watch(webDirectWorkoutCommitEnabledProvider)
          ? ref.watch(webActiveWorkoutStoreProvider)
          : InMemoryWorkoutStartNoticeStore(),
    );

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
final StateProvider<int> playerShellTabProvider = StateProvider<int>(
  (ref) => 0,
);

/// The number of coach alerts still in the `new` state, published by the
/// Alerts tab so the shell's badge tracks acknowledge/resolve without a second
/// fetch. It resets whenever the account changes, so one account's badge count
/// is never shown for another (#119).
final StateProvider<int> coachNewAlertsCountProvider = StateProvider<int>((
  ref,
) {
  _resetOnAccountChange(ref, () => ref.controller.state = 0);
  return 0;
});

/// Bumped whenever a coaching action changes what a roster row shows
/// (acknowledge/resolve on either the player page or the Alerts tab, and a
/// saved check-in). The Roster tab listens and reloads in the background, so
/// the row's chips track the action without a restart (#120).
///
/// Only producers bump it; the Roster tab never does, so a bump cannot loop.
final StateProvider<int> coachRosterRevisionProvider = StateProvider<int>(
  (ref) => 0,
);

class CoachLocationMemory {
  const CoachLocationMemory({required this.accountId, required this.location});

  final String accountId;
  final String location;
}

/// The latest Coach route for this signed-in account, kept in memory only.
final StateProvider<CoachLocationMemory?> coachLocationMemoryProvider =
    StateProvider<CoachLocationMemory?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

/// Shared in-memory roster data so URL selection can replace the right pane
/// without refetching or rebuilding the mounted list pane.
final StateProvider<List<CoachRosterEntry>?> coachRosterEntriesProvider =
    StateProvider<List<CoachRosterEntry>?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

final StateProvider<int?> coachRosterEntriesRevisionProvider =
    StateProvider<int?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

/// Bumped whenever a coach alert is acknowledged or resolved outside the
/// Alerts tab (the player page). The Alerts tab listens and refetches, which
/// also republishes [coachNewAlertsCountProvider] (#120).
///
/// Only the player page bumps it; the Alerts tab never does, so a bump cannot
/// loop.
final StateProvider<int> coachAlertsRevisionProvider = StateProvider<int>(
  (ref) => 0,
);

/// Shared in-memory Alerts data across coach route transitions.
final StateProvider<List<CoachAlert>?> coachAlertsListProvider =
    StateProvider<List<CoachAlert>?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

final StateProvider<int?> coachAlertsListRevisionProvider =
    StateProvider<int?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

/// The number of the coach's pending program requests, published by the
/// Requests tab so the shell's badge tracks apply/decline without a second
/// fetch. It resets whenever the account changes, so one account's badge count
/// is never shown for another (#119/#121).
final StateProvider<int> coachPendingRequestsCountProvider = StateProvider<int>(
  (ref) {
    _resetOnAccountChange(ref, () => ref.controller.state = 0);
    return 0;
  },
);

/// Shared in-memory Requests tab data across URL selection changes.
final StateProvider<List<ProgramRequest>?> coachRequestsListProvider =
    StateProvider<List<ProgramRequest>?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

final StateProvider<int?> coachRequestsListRevisionProvider =
    StateProvider<int?>((ref) {
  _resetOnAccountChange(ref, () => ref.controller.state = null);
  return null;
});

/// Bumped whenever a program request is applied or declined outside the
/// Requests tab (the player page). The Requests tab listens and refetches,
/// which also republishes [coachPendingRequestsCountProvider] (#121).
///
/// Only the player page bumps it; the Requests tab never does, so a bump
/// cannot loop.
final StateProvider<int> coachRequestsRevisionProvider = StateProvider<int>(
  (ref) => 0,
);

/// Processes the logged-in account's drafts on login, after a save, on demand,
/// and periodically while the app is in the foreground (ADR 020/033).
final ChangeNotifierProvider<DraftSyncService> draftSyncServiceProvider =
    ChangeNotifierProvider<DraftSyncService>((ref) {
      final DraftSyncService service = DraftSyncService(
        api: ref.watch(apiClientProvider),
        store: ref.watch(draftStoreProvider),
        onCommit: (String accountId, Map<String, dynamic> response) => ref
            .read(trainingStatusProvider.notifier)
            .acceptCommit(accountId, response),
      );
      ref.listen<AuthState>(authControllerProvider, (
        AuthState? previous,
        AuthState next,
      ) {
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
/// it stays in memory on web (ADR 022).
final Provider<BaselineCacheStore> baselineCacheStoreProvider =
    Provider<BaselineCacheStore>(
      (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
          ? SecureBaselineCacheStore()
          : InMemoryBaselineCacheStore(),
    );

/// Device storage for the single Active workout held per account (#123).
final Provider<ActiveWorkoutStore> activeWorkoutStoreProvider =
    Provider<ActiveWorkoutStore>(
      (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
          ? SecureActiveWorkoutStore()
          : ref.watch(webActiveWorkoutStoreProvider),
    );

/// The baselines reader: Home's fire-and-forget prefetch and the fresh →
/// cache → empty resolution a workout start freezes (#123).
final Provider<BaselinesService> baselinesServiceProvider =
    Provider<BaselinesService>(
      (ref) => BaselinesService(
        api: ref.watch(apiClientProvider),
        cache: ref.watch(baselineCacheStoreProvider),
        drafts: ref.watch(draftStoreProvider),
      ),
    );

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
    now: ref.watch(clockProvider),
    explain: (String line) => mayosMessengerKey.currentState?.showSnackBar(
      SnackBar(content: Text(line)),
    ),
  );
});

/// Device persistence for the player's per-exercise rest overrides, per
/// account (#125) — the same online/offline gate as the other protected
/// stores, so this store stays in memory on web (ADR 022).
final Provider<RestLengthStore> restLengthStoreProvider =
    Provider<RestLengthStore>(
      (ref) => ref.watch(offlineWorkoutDraftsEnabledProvider)
          ? SecureRestLengthStore()
          : InMemoryRestLengthStore(),
    );

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
        persistClientSessionId: ref.watch(
          webDirectWorkoutCommitEnabledProvider,
        ),
        // The prescription a start seeds and hints from: fresh with a short
        // timeout, else the cache, as the old logger resolved it (#123).
        loadPrescription: (String accountId, int dayOrder) =>
            loadDayPrescription(
              api: api,
              cache: cache,
              accountId: accountId,
              dayOrder: dayOrder,
            ),
        restLengths: ref.watch(restLengthStoreProvider),
        alerts: ref.watch(restAlertsProvider),
        now: ref.watch(clockProvider),
      );
      ref.listen<AuthState>(authControllerProvider, (
        AuthState? previous,
        AuthState next,
      ) {
        final String? accountId = next.session?.account.accountId;
        if (next.isAuthenticated && accountId != null) {
          controller.syncAccount(accountId);
        } else {
          controller.syncAccount(null);
        }
      }, fireImmediately: true);
      return controller;
    });

final Provider<WebWorkoutCommitter> webWorkoutCommitterProvider =
    Provider<WebWorkoutCommitter>(
      (ref) => WebWorkoutCommitter(
        api: ref.watch(apiClientProvider),
        controller: ref.watch(activeWorkoutControllerProvider.notifier),
        onCommit: (String accountId, Map<String, dynamic> response) => ref
            .read(trainingStatusProvider.notifier)
            .acceptCommit(accountId, response),
      ),
    );
