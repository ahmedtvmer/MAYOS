import 'dart:convert';

import 'active_workout.dart';
import 'browser_key_value_store.dart';
import 'workout_start_notice_store.dart';

/// Web-only persistence for the one unfinished Active workout per account.
/// If the browser denies storage, the workout continues in memory for this tab.
class WebActiveWorkoutStore
    implements ActiveWorkoutStore, WorkoutStartNoticeStore {
  WebActiveWorkoutStore({
    required BrowserKeyValueStore storage,
    ActiveWorkoutStore? fallback,
    WorkoutStartNoticeStore? noticeFallback,
  })  : _storage = storage,
        _fallback = fallback ?? InMemoryActiveWorkoutStore(),
        _noticeFallback = noticeFallback ?? InMemoryWorkoutStartNoticeStore();

  final BrowserKeyValueStore _storage;
  final ActiveWorkoutStore _fallback;
  final WorkoutStartNoticeStore _noticeFallback;
  bool _storageFailed = false;

  static String _workoutKey(String accountId) =>
      'mayos.activeWorkout.$accountId';
  static String _noticeKey(String accountId) =>
      'mayos.activeWorkout.startNoticeSeen.$accountId';

  @override
  Future<ActiveWorkout?> read(String accountId) async {
    if (_storageFailed) return _fallback.read(accountId);
    try {
      final String? raw = _storage.getItem(_workoutKey(accountId));
      if (raw == null || raw.isEmpty) return null;
      final dynamic decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) return null;
      return ActiveWorkout.fromJson(decoded);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    } on Object {
      _storageFailed = true;
      return _fallback.read(accountId);
    }
  }

  @override
  Future<void> write(String accountId, ActiveWorkout workout) async {
    if (_storageFailed) return _fallback.write(accountId, workout);
    try {
      _storage.setItem(_workoutKey(accountId), jsonEncode(workout.toJson()));
    } on Object {
      _storageFailed = true;
      await _fallback.write(accountId, workout);
    }
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    if (_storageFailed) return _fallback.deleteForAccount(accountId);
    try {
      _storage.removeItem(_workoutKey(accountId));
      await _fallback.deleteForAccount(accountId);
    } on Object {
      _storageFailed = true;
      await _fallback.deleteForAccount(accountId);
    }
  }

  @override
  Future<bool> hasSeenWorkoutStartNotice(String accountId) async {
    if (_storageFailed) {
      return _noticeFallback.hasSeenWorkoutStartNotice(accountId);
    }
    try {
      return _storage.getItem(_noticeKey(accountId)) == 'true';
    } on Object {
      _storageFailed = true;
      return _noticeFallback.hasSeenWorkoutStartNotice(accountId);
    }
  }

  @override
  Future<void> markWorkoutStartNoticeSeen(String accountId) async {
    if (_storageFailed) {
      return _noticeFallback.markWorkoutStartNoticeSeen(accountId);
    }
    try {
      _storage.setItem(_noticeKey(accountId), 'true');
    } on Object {
      _storageFailed = true;
      await _noticeFallback.markWorkoutStartNoticeSeen(accountId);
    }
  }

  @override
  Future<void> clearWorkoutStartNotice(String accountId) async {
    if (_storageFailed) {
      return _noticeFallback.clearWorkoutStartNotice(accountId);
    }
    try {
      _storage.removeItem(_noticeKey(accountId));
      await _noticeFallback.clearWorkoutStartNotice(accountId);
    } on Object {
      _storageFailed = true;
      await _noticeFallback.clearWorkoutStartNotice(accountId);
    }
  }
}
