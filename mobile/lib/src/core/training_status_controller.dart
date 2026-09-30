import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'models.dart';
import 'workout_storage.dart';

/// Loads the player's latest Weekly streak and Checkpoint progress, keeping an
/// account-scoped copy in the protected workout cache for offline summaries.
class TrainingStatusController extends StateNotifier<TrainingStatus?> {
  TrainingStatusController({
    required ApiClient api,
    required WorkoutCacheStore cache,
  }) : _api = api,
       _cache = cache,
       super(null);

  final ApiClient _api;
  final WorkoutCacheStore _cache;

  String? _accountId;
  int _generation = 0;

  void syncAccount(String? accountId) {
    if (!_switchAccount(accountId)) {
      return;
    }
    if (accountId != null) {
      unawaited(refresh(accountId));
    }
  }

  /// Refreshes from the service after first exposing the last stored value.
  Future<void> refresh(String accountId) async {
    _switchAccount(accountId);
    final int generation = _generation;
    await _restoreFromCacheIfEmpty(accountId, generation);
    await _refreshFromService(accountId, generation);
  }

  Future<void> _restoreFromCacheIfEmpty(String accountId, int generation) async {
    if (state != null) {
      return;
    }
    try {
      final TrainingStatus? cached = await _cache.readTrainingStatus(accountId);
      if (_isCurrent(accountId, generation) && state == null && cached != null) {
        state = cached;
      }
    } on PlatformException {
      // A protected-cache read failure does not block the live request.
    } on MissingPluginException {
      // The live request can still provide a status when storage is unavailable.
    }
  }

  Future<void> _refreshFromService(String accountId, int generation) async {
    try {
      final TrainingStatus fresh = await _api.trainingStatus();
      if (!_isCurrent(accountId, generation)) {
        return;
      }
      state = fresh;
      await _write(accountId, fresh);
    } on ApiException {
      // Keep the last known status for an offline workout summary.
    }
  }

  /// Returns the last value already loaded or stored without waiting on network.
  Future<TrainingStatus?> statusForSummary(String accountId) async {
    _switchAccount(accountId);
    final TrainingStatus? current = state;
    if (current != null) {
      return current;
    }
    final int generation = _generation;
    await _restoreFromCacheIfEmpty(accountId, generation);
    return _isCurrent(accountId, generation) ? state : null;
  }

  /// Replaces the cache with the post-commit outcome returned by the service.
  Future<void> acceptCommit(
    String accountId,
    Map<String, dynamic> response,
  ) async {
    if (_accountId != accountId) {
      return;
    }
    final dynamic raw = response['training_status'];
    if (raw is! Map<String, dynamic>) {
      return;
    }
    try {
      final TrainingStatus status = TrainingStatus.fromJson(raw);
      state = status;
      await _write(accountId, status);
    } on FormatException {
      // Ignore an invalid optional field while keeping the current cache.
    } on TypeError {
      // Ignore an invalid optional field while keeping the current cache.
    }
  }

  bool _isCurrent(String accountId, int generation) =>
      _accountId == accountId && _generation == generation;

  bool _switchAccount(String? accountId) {
    if (_accountId == accountId) {
      return false;
    }
    _accountId = accountId;
    _generation += 1;
    state = null;
    return true;
  }

  Future<void> _write(String accountId, TrainingStatus status) async {
    try {
      await _cache.writeTrainingStatus(accountId, status);
    } on PlatformException {
      // The in-memory status remains useful if protected storage is unavailable.
    } on MissingPluginException {
      // The in-memory status remains useful if storage is temporarily unavailable.
    }
  }
}
