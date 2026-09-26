import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'models.dart';

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

  /// Set when the last [read] quarantined unreadable raw storage instead of
  /// silently discarding it, so the UI can surface a warning. Cleared once a
  /// [write] for that account succeeds.
  bool isQuarantined(String accountId) => false;
}

class SecureDraftStore implements DraftStore {
  SecureDraftStore({FlutterSecureStorage? storage, DateTime Function()? now})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            ),
        _now = now ?? DateTime.now;

  final FlutterSecureStorage _storage;
  final DateTime Function() _now;
  final Set<String> _quarantined = <String>{};

  static String _key(String accountId) => 'drafts.$accountId';

  @override
  bool isQuarantined(String accountId) => _quarantined.contains(accountId);

  @override
  Future<List<WorkoutDraft>> read(String accountId) async {
    final String key = _key(accountId);
    final String? raw = await _storage.read(key: key);
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
    await _storage.write(key: quarantineKey, value: raw);
    _quarantined.add(accountId);
  }

  @override
  Future<void> write(String accountId, List<WorkoutDraft> drafts) async {
    final String raw = jsonEncode(<Map<String, dynamic>>[
      for (final WorkoutDraft draft in drafts) draft.toJson(),
    ]);
    await _storage.write(key: _key(accountId), value: raw);
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
  void simulateCorruptStorage(String accountId, {String raw = '{not valid json'}) {
    _byAccount.remove(accountId);
    _corrupt[accountId] = raw;
  }

  @override
  bool isQuarantined(String accountId) => _quarantined.contains(accountId);

  @override
  Future<List<WorkoutDraft>> read(String accountId) async {
    final String? raw = _corrupt.remove(accountId);
    if (raw != null) {
      quarantinedRaw['$accountId.corrupt.${DateTime.now().millisecondsSinceEpoch}'] = raw;
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
}

class SecureWorkoutCacheStore implements WorkoutCacheStore {
  SecureWorkoutCacheStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  @override
  Future<TrainingProgram?> readProgram(String accountId) async {
    final String? raw = await _storage.read(key: 'program.$accountId');
    if (raw == null || raw.isEmpty) {
      return null;
    }
    try {
      return TrainingProgram.fromJson(
          jsonDecode(raw) as Map<String, dynamic>);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> writeProgram(String accountId, TrainingProgram program) =>
      _storage.write(
          key: 'program.$accountId', value: jsonEncode(program.toJson()));

  @override
  Future<Prescription?> readPrescription(String accountId, int dayOrder) async {
    final String? raw =
        await _storage.read(key: 'prescription.$accountId.$dayOrder');
    if (raw == null || raw.isEmpty) {
      return null;
    }
    try {
      return Prescription.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  @override
  Future<void> writePrescription(
          String accountId, int dayOrder, Prescription prescription) =>
      _storage.write(
        key: 'prescription.$accountId.$dayOrder',
        value: jsonEncode(prescription.toJson()),
      );
}

class InMemoryWorkoutCacheStore implements WorkoutCacheStore {
  final Map<String, TrainingProgram> _programs = <String, TrainingProgram>{};
  final Map<String, Prescription> _prescriptions = <String, Prescription>{};

  @override
  Future<TrainingProgram?> readProgram(String accountId) async =>
      _programs[accountId];

  @override
  Future<void> writeProgram(String accountId, TrainingProgram program) async {
    _programs[accountId] = program;
  }

  @override
  Future<Prescription?> readPrescription(String accountId, int dayOrder) async =>
      _prescriptions['$accountId.$dayOrder'];

  @override
  Future<void> writePrescription(
      String accountId, int dayOrder, Prescription prescription) async {
    _prescriptions['$accountId.$dayOrder'] = prescription;
  }
}
