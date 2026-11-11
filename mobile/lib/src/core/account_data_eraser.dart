import 'dart:async';

import 'active_workout.dart';
import 'baselines.dart';
import 'chat_storage.dart';
import 'workout_start_notice_store.dart';
import 'workout_storage.dart';

typedef _AccountErase = ({
  Future<void> Function() erase,
  bool usesPlatformStorage,
});

/// The single place that erases every account-namespaced protected local value.
///
/// Used by both account-deletion paths (ADR 039): the deleting device calls it
/// after the server confirms deletion, and another device calls it when a
/// request reports `account_deleted`. It never touches another account's
/// storage, and a failure in one store never prevents erasing the others.
class AccountDataEraser {
  AccountDataEraser({
    required DraftStore drafts,
    required WorkoutCacheStore workoutCache,
    required ChatCacheStore chatCache,
    required BaselineCacheStore baselines,
    required ActiveWorkoutStore activeWorkout,
    required WorkoutStartNoticeStore workoutStartNotice,
  })  : _drafts = drafts,
        _workoutCache = workoutCache,
        _chatCache = chatCache,
        _baselines = baselines,
        _activeWorkout = activeWorkout,
        _workoutStartNotice = workoutStartNotice;

  final DraftStore _drafts;
  final WorkoutCacheStore _workoutCache;
  final ChatCacheStore _chatCache;
  final BaselineCacheStore _baselines;
  final ActiveWorkoutStore _activeWorkout;
  final WorkoutStartNoticeStore _workoutStartNotice;

  Future<void> erase(String accountId) async {
    final List<Future<void>> awaitForInjectedStores = <Future<void>>[];
    for (final _AccountErase erasure in _erasuresForAccount(accountId)) {
      _startErase(
        erasure.erase,
        erasure.usesPlatformStorage,
        awaitForInjectedStores,
      );
    }
    await Future.wait<void>(awaitForInjectedStores);
  }

  List<_AccountErase> _erasuresForAccount(String accountId) =>
      <_AccountErase>[
        (
          erase: () => _drafts.deleteForAccount(accountId),
          usesPlatformStorage: _usesPlatformStorage(_drafts),
        ),
        (
          erase: () => _workoutCache.deleteForAccount(accountId),
          usesPlatformStorage: _usesPlatformStorage(_workoutCache),
        ),
        (
          erase: () => _chatCache.deleteAccount(accountId),
          usesPlatformStorage: _usesPlatformStorage(_chatCache),
        ),
        (
          erase: () => _baselines.deleteForAccount(accountId),
          usesPlatformStorage: _usesPlatformStorage(_baselines),
        ),
        (
          erase: () => _activeWorkout.deleteForAccount(accountId),
          usesPlatformStorage: _usesPlatformStorage(_activeWorkout),
        ),
        (
          erase: () => _workoutStartNotice.clearWorkoutStartNotice(accountId),
          usesPlatformStorage: false,
        ),
      ];

  void _startErase(
    Future<void> Function() action,
    bool usesPlatformStorage,
    List<Future<void>> awaitForInjectedStores,
  ) {
    final Future<void> cleanup = _bestEffort(action);
    if (usesPlatformStorage) {
      unawaited(cleanup);
    } else {
      awaitForInjectedStores.add(cleanup);
    }
  }

  bool _usesPlatformStorage(Object store) => switch (store) {
        SecureDraftStore value => value.usesPlatformStorage,
        SecureWorkoutCacheStore value => value.usesPlatformStorage,
        SecureChatCacheStore value => value.usesPlatformStorage,
        SecureBaselineCacheStore value => value.usesPlatformStorage,
        SecureActiveWorkoutStore value => value.usesPlatformStorage,
        _ => false,
      };

  Future<void> _bestEffort(Future<void> Function() action) async {
    try {
      await action();
    } on Object {
      // Protection is the goal: a storage failure must never leave another
      // store's protected data behind or block the session teardown.
    }
  }
}
