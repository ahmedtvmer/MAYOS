import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'models.dart';
import 'secure_store.dart';

/// Protected, account-separated storage for offline workout drafts (ADR 020/033).
///
/// Drafts are keyed by the immutable account id so another account on the same
/// device never sees them, and logout never deletes them. [SecureDraftStore] is
/// keystore-backed on Android; it is only used where
/// `offlineWorkoutDraftsEnabledProvider` is true, so the web client never writes
/// drafts to browser storage (ADR 022 keeps web online-only).
abstract class DraftStore {
  Future<List<WorkoutDraft>> read(String accountId);

  Future<void> write(String accountId, List<WorkoutDraft> drafts);

  /// Erases every protected draft (and any quarantined raw value) for one
  /// account. Account deletion removes the account's drafts on the deleting
  /// device and on another device once it learns the account is gone (ADR 020/039).
  Future<void> deleteForAccount(String accountId);

  /// Set when the last [read] quarantined unreadable raw storage instead of
  /// silently discarding it, so the UI can surface a warning. Cleared once a
  /// [write] for that account succeeds.
  bool isQuarantined(String accountId) => false;
}

class SecureDraftStore implements DraftStore {
  SecureDraftStore({FlutterSecureStorage? storage, DateTime Function()? now})
      : _store = SecureStore(storage: storage),
        _now = now ?? DateTime.now;

  final SecureStore _store;
  final DateTime Function() _now;
  final Set<String> _quarantined = <String>{};

  static String _key(String accountId) => 'drafts.$accountId';

  @override
  bool isQuarantined(String accountId) => _quarantined.contains(accountId);

  @override
  Future<List<WorkoutDraft>> read(String accountId) async {
    final String key = _key(accountId);
    final String? raw = await _store.readString(key);
    if (raw == null || raw.isEmpty) {
      _quarantined.remove(accountId);
      return <WorkoutDraft>[];
    }
    try {
      final dynamic decoded = jsonDecode(raw);
      if (decoded is! List<dynamic>) {
        throw const FormatException('Drafts storage must be a JSON list.');
      }
      final List<WorkoutDraft> drafts = decoded
          .map((dynamic item) =>
              WorkoutDraft.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);
      _quarantined.remove(accountId);
      return drafts;
    } on FormatException {
      await _quarantine(accountId, raw);
      return <WorkoutDraft>[];
    } on TypeError {
      await _quarantine(accountId, raw);
      return <WorkoutDraft>[];
    }
  }

  /// Moves unreadable raw storage aside instead of letting the next write
  /// silently replace it, so a corrupted value is never lost outright.
  Future<void> _quarantine(String accountId, String raw) async {
    final String quarantineKey =
        'drafts.$accountId.corrupt.${_now().millisecondsSinceEpoch}';
    await _store.writeString(quarantineKey, raw);
    _quarantined.add(accountId);
  }

  @override
  Future<void> write(String accountId, List<WorkoutDraft> drafts) async {
    await _store.writeJson(key: _key(accountId), value: <Map<String, dynamic>>[
      for (final WorkoutDraft draft in drafts) draft.toJson(),
    ]);
    _quarantined.remove(accountId);
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    await _store.deleteExactOrPrefixed(
        'drafts.$accountId', 'drafts.$accountId.');
    _quarantined.remove(accountId);
  }
}

/// In-memory fake for tests. Sharing one instance across provider containers
/// simulates an app restart reading the same protected storage.
class InMemoryDraftStore implements DraftStore {
  final Map<String, List<WorkoutDraft>> _byAccount =
      <String, List<WorkoutDraft>>{};
  final Map<String, String> _corrupt = <String, String>{};
  final Set<String> _quarantined = <String>{};

  /// Quarantined raw values, keyed by the quarantine key they were moved to,
  /// so tests can assert nothing was lost.
  final Map<String, String> quarantinedRaw = <String, String>{};

  /// Test hook: the next [read] for [accountId] finds unreadable raw storage
  /// (e.g. a value a previous app version could not have written), exercising
  /// the same quarantine path as [SecureDraftStore].
  void simulateCorruptStorage(String accountId,
      {String raw = '{not valid json'}) {
    _byAccount.remove(accountId);
    _corrupt[accountId] = raw;
  }

  @override
  bool isQuarantined(String accountId) => _quarantined.contains(accountId);

  @override
  Future<List<WorkoutDraft>> read(String accountId) async {
    final String? raw = _corrupt.remove(accountId);
    if (raw != null) {
      quarantinedRaw[
          '$accountId.corrupt.${DateTime.now().millisecondsSinceEpoch}'] = raw;
      _quarantined.add(accountId);
      return <WorkoutDraft>[];
    }
    return List<WorkoutDraft>.of(_byAccount[accountId] ?? <WorkoutDraft>[]);
  }

  @override
  Future<void> write(String accountId, List<WorkoutDraft> drafts) async {
    _byAccount[accountId] = List<WorkoutDraft>.of(drafts);
    _quarantined.remove(accountId);
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _byAccount.remove(accountId);
    _corrupt.remove(accountId);
    _quarantined.remove(accountId);
  }
}

/// Protected, account-separated cache of the active program and its
/// prescription, so the workout logger works offline (ADR 020/033). Like
/// [DraftStore], this is only used on the offline-capable (non-web) client.
abstract class WorkoutCacheStore {
  Future<TrainingProgram?> readProgram(String accountId);

  Future<void> writeProgram(String accountId, TrainingProgram program);

  Future<Prescription?> readPrescription(String accountId, int dayOrder);

  Future<void> writePrescription(
      String accountId, int dayOrder, Prescription prescription);

  /// The last-known committed session, cached so Home can derive the next day
  /// offline (#53).
  Future<LatestSession?> readLatestSession(String accountId);

  Future<void> writeLatestSession(String accountId, LatestSession session);

  /// Erases the cached active program, every cached prescription, and the
  /// cached latest session for one account (ADR 020/039).
  Future<void> deleteForAccount(String accountId);
}

class SecureWorkoutCacheStore implements WorkoutCacheStore {
  SecureWorkoutCacheStore({FlutterSecureStorage? storage})
      : _store = SecureStore(storage: storage);

  final SecureStore _store;

  @override
  Future<TrainingProgram?> readProgram(String accountId) async {
    final dynamic decoded = await _store.readJson('program.$accountId');
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    try {
      return TrainingProgram.fromJson(decoded);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> writeProgram(String accountId, TrainingProgram program) =>
      _store.writeJson(key: 'program.$accountId', value: program.toJson());

  @override
  Future<Prescription?> readPrescription(String accountId, int dayOrder) async {
    final dynamic decoded =
        await _store.readJson('prescription.$accountId.$dayOrder');
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    try {
      return Prescription.fromJson(decoded);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> writePrescription(
          String accountId, int dayOrder, Prescription prescription) =>
      _store.writeJson(
        key: 'prescription.$accountId.$dayOrder',
        value: prescription.toJson(),
      );

  @override
  Future<LatestSession?> readLatestSession(String accountId) async {
    final dynamic decoded = await _store.readJson('latest_session.$accountId');
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    try {
      return LatestSession.fromJson(decoded);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> writeLatestSession(String accountId, LatestSession session) =>
      _store.writeJson(
        key: 'latest_session.$accountId',
        value: session.toJson(),
      );

  @override
  Future<void> deleteForAccount(String accountId) async {
    await _store.deleteExactOrPrefixed(
        'program.$accountId', 'program.$accountId.');
    await _store.deleteByPrefix('prescription.$accountId.');
    await _store.deleteExactOrPrefixed(
        'latest_session.$accountId', 'latest_session.$accountId.');
  }
}

class InMemoryWorkoutCacheStore implements WorkoutCacheStore {
  final Map<String, TrainingProgram> _programs = <String, TrainingProgram>{};
  final Map<String, Prescription> _prescriptions = <String, Prescription>{};
  final Map<String, LatestSession> _latestSessions = <String, LatestSession>{};

  @override
  Future<TrainingProgram?> readProgram(String accountId) async =>
      _programs[accountId];

  @override
  Future<void> writeProgram(String accountId, TrainingProgram program) async {
    _programs[accountId] = program;
  }

  @override
  Future<Prescription?> readPrescription(
          String accountId, int dayOrder) async =>
      _prescriptions['$accountId.$dayOrder'];

  @override
  Future<void> writePrescription(
      String accountId, int dayOrder, Prescription prescription) async {
    _prescriptions['$accountId.$dayOrder'] = prescription;
  }

  @override
  Future<LatestSession?> readLatestSession(String accountId) async =>
      _latestSessions[accountId];

  @override
  Future<void> writeLatestSession(
      String accountId, LatestSession session) async {
    _latestSessions[accountId] = session;
  }

  @override
  Future<void> deleteForAccount(String accountId) async {
    _programs.remove(accountId);
    _latestSessions.remove(accountId);
    _prescriptions
        .removeWhere((String key, _) => key.startsWith('$accountId.'));
  }
}
