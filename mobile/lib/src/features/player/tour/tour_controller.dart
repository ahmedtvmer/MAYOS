import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:go_router/go_router.dart';

import '../../../core/analytics_client.dart';
import '../../../core/api_client.dart';
import '../../../core/app_mode.dart';
import '../../../core/models.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../auth/auth_controller.dart';
import '../workout/active_workout_controller.dart';
import 'tour_targets.dart';
import 'feature_list.dart';

const Duration _targetRegistrationWait = Duration(seconds: 2);
// Profile and media reads can outlast the initial target registration window.
const Duration _loadingDestinationWait = Duration(seconds: 35);

class TourSession {
  const TourSession({
    required this.stopIds,
    required this.index,
    required this.visible,
    required this.singleStop,
    required this.version,
    required this.accountId,
    this.replay = false,
  });

  final List<String> stopIds;
  final int index;
  final bool visible;
  final bool singleStop;
  final int version;
  final String accountId;
  final bool replay;

  String get featureId => stopIds[index];

  TourSession copyWith({int? index, bool? visible}) => TourSession(
        stopIds: stopIds,
        index: index ?? this.index,
        visible: visible ?? this.visible,
        singleStop: singleStop,
        version: version,
        accountId: accountId,
        replay: replay,
      );
}

abstract interface class TourSeenRetryStore {
  Future<int?> read(String accountId);
  Future<void> write(String accountId, int version);
  Future<void> clear(String accountId);
}

class SecureTourSeenRetryStore implements TourSeenRetryStore {
  SecureTourSeenRetryStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  String _key(String accountId) => 'mayos.tour_seen_pending.$accountId';

  @override
  Future<int?> read(String accountId) async {
    final String? value = await _storage.read(key: _key(accountId));
    return int.tryParse(value ?? '');
  }

  @override
  Future<void> write(String accountId, int version) =>
      _storage.write(key: _key(accountId), value: '$version');

  @override
  Future<void> clear(String accountId) =>
      _storage.delete(key: _key(accountId));
}

final Provider<TourSeenRetryStore> tourSeenRetryStoreProvider =
    Provider<TourSeenRetryStore>((ref) => SecureTourSeenRetryStore());

abstract interface class WhatsNewSeenRetryStore {
  Future<int?> read(String accountId);
  Future<void> write(String accountId, int release);
  Future<void> clear(String accountId);
}

class SecureWhatsNewSeenRetryStore implements WhatsNewSeenRetryStore {
  SecureWhatsNewSeenRetryStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  String _key(String accountId) => 'mayos.whats_new_seen_pending.$accountId';

  @override
  Future<int?> read(String accountId) async =>
      int.tryParse(await _storage.read(key: _key(accountId)) ?? '');

  @override
  Future<void> write(String accountId, int release) =>
      _storage.write(key: _key(accountId), value: '$release');

  @override
  Future<void> clear(String accountId) => _storage.delete(key: _key(accountId));
}

final Provider<WhatsNewSeenRetryStore> whatsNewSeenRetryStoreProvider =
    Provider<WhatsNewSeenRetryStore>((ref) => SecureWhatsNewSeenRetryStore());

final Provider<int> tourCurrentVersionProvider =
    Provider<int>((ref) => tourCurrentVersion);

final StateNotifierProvider<TourController, TourSession?>
    tourControllerProvider = StateNotifierProvider<TourController, TourSession?>(
  (ref) => TourController(ref),
);

class TourController extends StateNotifier<TourSession?> {
  TourController(this._ref) : super(null) {
    _ref.listen<AuthState>(authControllerProvider, (previous, next) {
      final TourSession? current = state;
      if (current != null &&
          next.session?.account.accountId != current.accountId) {
        _operation++;
        state = null;
      }
    });
    _ref.listen<AppModeState>(appModeControllerProvider, (_, next) {
      final TourSession? current = state;
      if (current != null &&
          (!next.isResolvedFor(current.accountId) ||
              next.mode != AppMode.player)) {
        _operation++;
        state = null;
      }
    });
  }

  final Ref _ref;
  int _operation = 0;
  bool _starting = false;
  bool _focusing = false;
  String? _pendingAccountId;
  int? _pendingVersion;
  String? _pendingWhatsNewAccountId;
  int? _pendingWhatsNewRelease;
  final Set<String> _tourShownThisSession = <String>{};

  bool hasPendingSeenWriteFor(String accountId) =>
      _pendingAccountId == accountId && _pendingVersion != null;

  bool hasShownTourThisSession(String accountId) =>
      _tourShownThisSession.contains(accountId) ||
      hasPendingSeenWriteFor(accountId);

  Future<void> retryPendingWhatsNewSeen() async {
    final Account? account = _ref.read(authControllerProvider).session?.account;
    if (account == null) return;
    final String accountId = account.accountId;
    final AuthController auth = _ref.read(authControllerProvider.notifier);
    final WhatsNewSeenRetryStore store =
        _ref.read(whatsNewSeenRetryStoreProvider);
    try {
      final int? release = await store.read(accountId);
      if (!mounted || !auth.ownsAccount(accountId) || release == null) return;
      _pendingWhatsNewAccountId = accountId;
      _pendingWhatsNewRelease = release;
      auth.confirmWhatsNewSeenRelease(accountId, release);
      await _persistWhatsNewSeen(accountId, store, auth: auth);
    } on Object {
      // Secure-store failures leave any in-memory write pending for this session.
    }
  }

  Future<void> markWhatsNewSeen(int release) async {
    final Account? account = _ref.read(authControllerProvider).session?.account;
    if (account == null) return;
    final String accountId = account.accountId;
    final int nextRelease = release > account.whatsNewSeenRelease
        ? release
        : account.whatsNewSeenRelease;
    final AuthController auth = _ref.read(authControllerProvider.notifier);
    final WhatsNewSeenRetryStore store =
        _ref.read(whatsNewSeenRetryStoreProvider);
    _pendingWhatsNewAccountId = accountId;
    _pendingWhatsNewRelease = nextRelease;
    auth.confirmWhatsNewSeenRelease(accountId, nextRelease);
    try {
      await store.write(accountId, nextRelease);
    } on Object {
      // Keep the in-memory dismissal and attempt the network write now.
    }
    if (!auth.ownsAccount(accountId)) return;
    await _persistWhatsNewSeen(accountId, store, auth: auth);
  }

  Future<void> _persistWhatsNewSeen(
    String accountId,
    WhatsNewSeenRetryStore store, {
    required AuthController auth,
  }) async {
    final int? release = _pendingWhatsNewRelease;
    if (release == null ||
        _pendingWhatsNewAccountId != accountId ||
        !auth.ownsAccount(accountId)) {
      return;
    }
    try {
      final int savedRelease =
          await _ref.read(apiClientProvider).markWhatsNewSeen(release);
      if (!mounted || !auth.ownsAccount(accountId)) return;
      auth.confirmWhatsNewSeenRelease(accountId, savedRelease);
      _pendingWhatsNewAccountId = null;
      _pendingWhatsNewRelease = null;
      await store.clear(accountId);
    } on ApiException {
      // The local dismissal remains in secure storage and retries next app open.
    }
  }

  Future<void> startTour(int version, {bool replay = false}) async {
    if (state != null || _starting) return;
    final Account? account = _ref.read(authControllerProvider).session?.account;
    if (account == null) return;
    final AppModeState mode = _ref.read(appModeControllerProvider);
    if (!mode.isResolvedFor(account.accountId) || mode.mode != AppMode.player) {
      return;
    }
    if (!replay && account.tourSeenVersion >= version &&
        _pendingAccountId != account.accountId) {
      return;
    }
    _starting = true;
    final String accountId = account.accountId;
    final TourSeenRetryStore retryStore = _ref.read(tourSeenRetryStoreProvider);
    final AuthController auth = _ref.read(authControllerProvider.notifier);
    final ApiClient api = _ref.read(apiClientProvider);
    try {
      if (!replay && _pendingAccountId == accountId && _pendingVersion != null) {
        await _persistPending(accountId, retryStore, auth: auth, api: api);
        if (!mounted || !auth.ownsAccount(accountId)) return;
        if (_pendingVersion != null && _pendingVersion! >= version) return;
      }
      final int? persisted = replay ? null : await retryStore.read(accountId);
      if (!mounted || !auth.ownsAccount(accountId)) return;
      if (persisted != null) {
        _pendingAccountId = accountId;
        _pendingVersion = persisted;
        await _persistPending(accountId, retryStore, auth: auth, api: api);
        if (persisted >= version && _pendingVersion == null) return;
        if (_pendingVersion != null && _pendingVersion! >= version) return;
      }
    } on Object {
      // A secure-store failure must not prevent the Tour from being offered.
    } finally {
      _starting = false;
    }
    if (!mounted || !auth.ownsAccount(accountId)) return;
    final Account? currentAccount =
        _ref.read(authControllerProvider).session?.account;
    if (!auth.ownsAccount(accountId) ||
        currentAccount == null ||
        (!replay && !isTourEligible(currentAccount, currentVersion: version))) {
      return;
    }
    state = TourSession(
      stopIds: tourV1StopIds,
      index: 0,
      visible: false,
      singleStop: false,
      version: version,
      accountId: accountId,
      replay: replay,
    );
    _tourShownThisSession.add(accountId);
    await _focusCurrent(started: true);
  }

  Future<void> showMe(String featureId, {String? source}) async {
    FeatureEntry? entry;
    for (final FeatureEntry candidate in featureList) {
      if (candidate.id == featureId) {
        entry = candidate;
        break;
      }
    }
    if (entry == null ||
        entry.release > currentFeatureRelease ||
        entry.audience != 'lifter') {
      return;
    }
    final Account? account =
        _ref.read(authControllerProvider).session?.account;
    final AppModeState mode = _ref.read(appModeControllerProvider);
    if (account == null ||
        !mode.isResolvedFor(account.accountId) ||
        mode.mode != AppMode.player) {
      return;
    }
    final ActiveWorkoutState workout =
        _ref.read(activeWorkoutControllerProvider);
    if (!workout.ready || workout.hasWorkout) return;
    _ref.read(analyticsClientProvider).showMeTapped(featureId, source: source);
    _operation++;
    state = TourSession(
      stopIds: <String>[featureId],
      index: 0,
      visible: false,
      singleStop: true,
      version: tourCurrentVersion,
      accountId: account.accountId,
    );
    _tourShownThisSession.add(account.accountId);
    await _focusCurrent();
  }

  Future<void> next() async {
    final TourSession? current = state;
    if (current == null || !current.visible) return;
    if (current.singleStop) {
      state = null;
      return;
    }
    if (current.index == current.stopIds.length - 1) {
      await _dismiss(skipped: false);
      return;
    }
    state = current.copyWith(index: current.index + 1, visible: false);
    await _focusCurrent();
  }

  Future<void> back() async {
    final TourSession? current = state;
    if (current == null || !current.visible || current.index == 0) return;
    state = current.copyWith(index: current.index - 1, visible: false);
    await _focusCurrent();
  }

  Future<void> skip() => _dismiss(skipped: true);

  void suspend() {
    final TourSession? current = state;
    if (current != null) {
      _operation++;
      state = current.copyWith(visible: false);
    }
  }

  Future<void> resume() async {
    if (state == null || state!.visible || _focusing) return;
    await _focusCurrent();
  }

  Future<void> _focusCurrent({bool started = false}) async {
    final TourSession? current = state;
    if (current == null || _focusing) return;
    _focusing = true;
    final int operation = ++_operation;
    final FeatureEntry entry = featureList.firstWhere(
      (FeatureEntry feature) => feature.id == current.featureId,
    );
    final StateController<int> tabController =
        _ref.read(playerShellTabProvider.notifier);
    final GoRouter router = _ref.read(routerProvider);
    final AuthController auth = _ref.read(authControllerProvider.notifier);
    final AnalyticsClient analytics = _ref.read(analyticsClientProvider);
    final String accountId = current.accountId;
    try {
      final ActiveWorkoutState initialWorkout =
          _ref.read(activeWorkoutControllerProvider);
      if (!initialWorkout.ready ||
          initialWorkout.hasWorkout ||
          (!current.singleStop && _ref.read(playerChatStreamingProvider))) {
        return;
      }
      entry.location.navigate(router, tabController);
      final TourTargetHandle? target = await _waitForTarget(entry, operation);
      if (!mounted || operation != _operation || state == null) return;
      BuildContext? targetContext = target?.key.currentContext;
      if (target == null || targetContext == null || !targetContext.mounted) {
        if (current.singleStop) {
          state = null;
        } else if (current.index < current.stopIds.length - 1) {
          state = current.copyWith(index: current.index + 1, visible: false);
          scheduleMicrotask(_focusCurrent);
        } else {
          state = null;
        }
        return;
      }
      await Scrollable.ensureVisible(
        targetContext,
        alignment: 0.35,
        duration: const Duration(milliseconds: 160),
        curve: Curves.easeOut,
      );
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted || operation != _operation || state == null) return;
      if (!targetContext.mounted) {
        final BuildContext? refreshedTargetContext =
            _ref.read(tourTargetRegistryProvider)[entry.target]?.key.currentContext;
        if (refreshedTargetContext == null || !refreshedTargetContext.mounted) {
          return;
        }
        targetContext = refreshedTargetContext;
        await Scrollable.ensureVisible(
          refreshedTargetContext,
          alignment: 0.35,
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOut,
        );
        await WidgetsBinding.instance.endOfFrame;
        if (!mounted || operation != _operation || state == null ||
            !refreshedTargetContext.mounted) {
          return;
        }
      }
      final String routePath = currentTourRoutePath(router);
      final ActiveWorkoutState workout =
          _ref.read(activeWorkoutControllerProvider);
      if (!entry.location.matches(routePath, tabController.state) ||
          !workout.ready ||
          workout.hasWorkout ||
          (!current.singleStop && _ref.read(playerChatStreamingProvider))) {
        return;
      }
      if (!auth.ownsAccount(accountId)) {
        state = null;
        return;
      }
      state = state!.copyWith(visible: true);
      if (current.singleStop) return;
      if (started) analytics.tourEvent('tour_started', replay: current.replay);
      analytics.tourEvent('tour_step', step: state!.index + 1, replay: current.replay);
    } finally {
      _focusing = false;
    }
  }

  Future<TourTargetHandle?> _waitForTarget(
    FeatureEntry entry,
    int operation,
  ) async {
    bool waitExpired = false;
    bool extendedForLoading = false;
    bool loadingResolved = false;
    Timer targetWaitTimer = Timer(_targetRegistrationWait, () {
      waitExpired = true;
    });
    final String? loadingDestination = entry.location is TourRouteLocation
        ? (entry.location as TourRouteLocation).path
        : null;
    try {
      while (!waitExpired) {
        await WidgetsBinding.instance.endOfFrame;
        if (!mounted || operation != _operation || state == null) return null;
        final TourTargetHandle? target =
            _ref.read(tourTargetRegistryProvider)[entry.target];
        final BuildContext? targetContext = target?.key.currentContext;
        if (targetContext != null && targetContext.mounted) return target;
        final bool destinationLoading = loadingDestination != null &&
            _ref.read(tourLoadingDestinationsProvider)
                .contains(loadingDestination);
        final bool targetLoading =
            _ref.read(tourLoadingTargetsProvider).contains(entry.target);
        if (!extendedForLoading && (destinationLoading || targetLoading)) {
          targetWaitTimer.cancel();
          targetWaitTimer = Timer(_loadingDestinationWait, () {
            waitExpired = true;
          });
          extendedForLoading = true;
        } else if (extendedForLoading &&
            !loadingResolved &&
            !destinationLoading &&
            !targetLoading) {
          targetWaitTimer.cancel();
          targetWaitTimer = Timer(_targetRegistrationWait, () {
            waitExpired = true;
          });
          loadingResolved = true;
        }
      }
      return null;
    } finally {
      targetWaitTimer.cancel();
    }
  }

  Future<void> _dismiss({required bool skipped}) async {
    final TourSession? current = state;
    if (current == null || !current.visible) return;
    _operation++;
    state = null;
    if (current.singleStop) return;
    final String accountId = current.accountId;
    final AuthController auth = _ref.read(authControllerProvider.notifier);
    final TourSeenRetryStore retryStore = _ref.read(tourSeenRetryStoreProvider);
    final ApiClient api = _ref.read(apiClientProvider);
    _ref.read(analyticsClientProvider).tourEvent(
          skipped ? 'tour_skipped' : 'tour_completed', replay: current.replay,
        );
    if (current.replay) return;
    if (!auth.ownsAccount(accountId)) return;
    _pendingAccountId = accountId;
    _pendingVersion = current.version;
    auth.confirmTourSeenVersion(accountId, current.version);
    unawaited(
      _queueAndPersist(accountId, current.version, auth, retryStore, api),
    );
  }

  Future<void> _queueAndPersist(
    String accountId,
    int version,
    AuthController auth,
    TourSeenRetryStore retryStore,
    ApiClient api,
  ) async {
    try {
      await retryStore.write(accountId, version);
    } on Object {
      // Keep the in-memory pending marker and retry at the next Home open.
    }
    if (!auth.ownsAccount(accountId)) return;
    await _persistPending(accountId, retryStore, auth: auth, api: api);
  }

  Future<void> _persistPending(
    String accountId,
    TourSeenRetryStore retryStore, {
    AuthController? auth,
    ApiClient? api,
  }) async {
    final int? version = _pendingVersion;
    if (version == null || _pendingAccountId != accountId) return;
    final ApiClient client = api ?? _ref.read(apiClientProvider);
    final AuthController authController = auth ??
        _ref.read(authControllerProvider.notifier);
    if (!authController.ownsAccount(accountId)) return;
    try {
      final int savedVersion = await client.markTourSeen(version);
      if (!authController.ownsAccount(accountId)) return;
      authController.confirmTourSeenVersion(accountId, savedVersion);
      _pendingAccountId = null;
      _pendingVersion = null;
      await retryStore.clear(accountId);
    } on ApiException {
      // The Tour stays dismissed; the queued version retries at the next open.
    }
  }
}
