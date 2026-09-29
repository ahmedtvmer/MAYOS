/// Per-account acknowledgement for the web workout logging notice.
abstract interface class WorkoutStartNoticeStore {
  Future<bool> hasSeenWorkoutStartNotice(String accountId);

  Future<void> markWorkoutStartNoticeSeen(String accountId);

  Future<void> clearWorkoutStartNotice(String accountId);
}

class InMemoryWorkoutStartNoticeStore implements WorkoutStartNoticeStore {
  final Set<String> _seen = <String>{};

  @override
  Future<bool> hasSeenWorkoutStartNotice(String accountId) async =>
      _seen.contains(accountId);

  @override
  Future<void> markWorkoutStartNoticeSeen(String accountId) async {
    _seen.add(accountId);
  }

  @override
  Future<void> clearWorkoutStartNotice(String accountId) async {
    _seen.remove(accountId);
  }
}
