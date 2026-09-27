import 'chat_storage.dart';
import 'workout_storage.dart';

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
  })  : _drafts = drafts,
        _workoutCache = workoutCache,
        _chatCache = chatCache;

  final DraftStore _drafts;
  final WorkoutCacheStore _workoutCache;
  final ChatCacheStore _chatCache;

  Future<void> erase(String accountId) async {
    await _bestEffort(() => _drafts.deleteForAccount(accountId));
    await _bestEffort(() => _workoutCache.deleteForAccount(accountId));
    await _bestEffort(() => _chatCache.deleteAccount(accountId));
  }

  Future<void> _bestEffort(Future<void> Function() action) async {
    try {
      await action();
    } on Object {
      // Protection is the goal: a storage failure must never leave another
      // store's protected data behind or block the session teardown.
    }
  }
}
