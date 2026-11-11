import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'browser_key_value_store.dart';
import 'models.dart';
import 'secure_store.dart';

/// Last successful Player reads, never pending writes (ADR 112). Android uses
/// the same keystore helper as chat; web uses account-scoped browser storage.
/// Cache I/O is best effort: unavailable storage means no offline snapshot.
class SavedPlayerDataStore extends ChangeNotifier {
  SavedPlayerDataStore({BrowserKeyValueStore? browser, SecureStore? secure})
      : _browser = browser,
        _secure = browser == null ? secure ?? SecureStore() : null;

  final BrowserKeyValueStore? _browser;
  final SecureStore? _secure;
  int _generation = 0;
  Future<void> _storageQueue = Future<void>.value();
  bool _offline = false;
  bool _disposed = false;

  bool get offline => _offline;
  int get generation => _generation;

  void useSavedData() {
    if (_offline || _disposed) return;
    _offline = true;
    notifyListeners();
  }

  void confirmSession() {
    if (!_offline || _disposed) return;
    _offline = false;
    notifyListeners();
  }

  static String _key(String accountId) =>
      'saved_player_data.${Uri.encodeComponent(accountId)}';

  Future<T> _serialized<T>(Future<T> Function() action) {
    final Completer<T> completion = Completer<T>();
    _storageQueue = _storageQueue.then((_) async {
      try {
        completion.complete(await action());
      } catch (error, stack) {
        completion.completeError(error, stack);
      }
    });
    return completion.future;
  }

  Future<Map<String, dynamic>> _readAccount(String accountId) async {
    try {
      final BrowserKeyValueStore? browser = _browser;
      final dynamic decoded = browser == null
          ? await _secure!.readJson(_key(accountId))
          : jsonDecode(browser.getItem(_key(accountId)) ?? '{}');
      return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    } on Object {
      return <String, dynamic>{};
    }
  }

  Future<Map<String, dynamic>?> read(String accountId, String resource) =>
      _serialized(() async {
        final Map<String, dynamic> snapshots = await _readAccount(accountId);
        final dynamic snapshot = snapshots[resource];
        return snapshot is Map<String, dynamic> ? snapshot : null;
      });

  Future<void> write(String accountId, String resource,
      Map<String, dynamic> snapshot, int expectedGeneration) =>
      _serialized(() async {
        if (generation != expectedGeneration) return;
        final Map<String, dynamic> snapshots = await _readAccount(accountId);
        snapshots[resource] = snapshot;
        try {
          final BrowserKeyValueStore? browser = _browser;
          if (browser != null) {
            browser.setItem(_key(accountId), jsonEncode(snapshots));
          } else {
            await _secure!.writeJson(key: _key(accountId), value: snapshots);
          }
        } on Object {
          // The online result still succeeds when storage is unavailable.
        }
      });

  /// Invalidate outstanding reads before erasure so a late response cannot
  /// recreate an account's saved data after logout or deletion.
  Future<void> clearAccount(String accountId) {
    _generation++;
    return _serialized(() async {
      try {
        final BrowserKeyValueStore? browser = _browser;
        if (browser != null) {
          browser.removeItem(_key(accountId));
        } else {
          await _secure!.delete(_key(accountId));
        }
      } on Object {
        // Like chat cleanup, a storage failure must not block logout.
      }
    });
  }

  Future<void> saveSession(
    AccountSession session, {
    int? expectedGeneration,
  }) async {
    final String accountId = session.account.accountId;
    final int revision = expectedGeneration ?? generation;
    if (generation != revision) return;
    final Map<String, dynamic>? account = await read(accountId, '/auth/me');
    if (account == null || generation != revision) return;
    await write(accountId, 'session', <String, dynamic>{
      'account': account['body'],
      'onboarded': session.onboarded,
      'has_recovery_email': session.hasRecoveryEmail,
      'recovery_email': session.recoveryEmail,
    }, revision);
  }

  Future<AccountSession?> session(String accountId) async {
    final Map<String, dynamic>? snapshot = await read(accountId, 'session');
    if (snapshot == null) return null;
    try {
      final Account account =
          Account.fromJson(snapshot['account'] as Map<String, dynamic>);
      if (account.accountId != accountId) return null;
      return AccountSession(
        account: account,
        onboarded: snapshot['onboarded'] as bool,
        hasRecoveryEmail: snapshot['has_recovery_email'] as bool,
        recoveryEmail: snapshot['recovery_email'] as String?,
      );
    } on Object {
      // A corrupt or older snapshot must never select an account.
      return null;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
