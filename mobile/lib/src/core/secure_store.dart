import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Shared keystore-backed storage used by the account-separated local stores
/// (offline drafts, cached program/prescription, chat disclosure + history).
///
/// One construction site (ADR 022 keeps web online-only, so these are only
/// used where `offlineWorkoutDraftsEnabledProvider` is true) and one JSON
/// read/write helper, so every store decodes the same way and cannot drift.
class SecureStore {
  SecureStore({FlutterSecureStorage? storage})
      : storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage storage;

  /// Reads and JSON-decodes [key], returning null when it is absent, empty, or
  /// unreadable (a corrupt value that a previous app version could not have
  /// written must never crash a read).
  Future<dynamic> readJson(String key) async {
    final String? raw = await storage.read(key: key);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    try {
      return jsonDecode(raw);
    } on FormatException {
      return null;
    }
  }

  Future<void> writeJson({required String key, required Object value}) =>
      storage.write(key: key, value: jsonEncode(value));

  Future<void> writeString(String key, String value) =>
      storage.write(key: key, value: value);

  Future<String?> readString(String key) => storage.read(key: key);

  Future<void> delete(String key) => storage.delete(key: key);

  /// Deletes [key] exactly and every key beginning with [prefix] (an explicit
  /// delimiter, e.g. `account.`), so one account id that is a prefix of another
  /// can never erase the other account's data (ADR 039).
  Future<void> deleteExactOrPrefixed(String key, String prefix) async {
    await storage.delete(key: key);
    await deleteByPrefix(prefix);
  }

  /// Deletes every stored key beginning with [prefix].
  ///
  /// Used to erase all account-namespaced values for one account (drafts,
  /// cached program/prescriptions, chat history/disclosure) without touching
  /// another account's protected storage (ADR 020/039).
  Future<void> deleteByPrefix(String prefix) async {
    final Map<String, String> all = await storage.readAll();
    for (final String key in all.keys.toList(growable: false)) {
      if (key.startsWith(prefix)) {
        await storage.delete(key: key);
      }
    }
  }
}
