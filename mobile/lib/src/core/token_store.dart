import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists the bearer token. The production implementation backs onto the
/// Android Keystore via `flutter_secure_storage`; tests use [InMemoryTokenStore].
///
/// The immutable account id is persisted alongside the token so a device that
/// discovers its account was deleted can erase that account's protected local
/// data even before it has a live session (ADR 039).
abstract class TokenStore {
  /// Account id already known by this process, without reading device storage.
  String? get lastKnownAccountId;

  Future<void> save(String token);

  Future<String?> read();

  Future<void> saveAccountId(String accountId);

  Future<String?> readAccountId();

  Future<void> clear();
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            ),
        _usesPlatformStorage = storage == null;

  static const String _tokenKey = 'mayos.access_token';
  static const String _accountIdKey = 'mayos.account_id';

  final FlutterSecureStorage _storage;
  String? _lastKnownAccountId;
  int _accountIdRevision = 0;
  final bool _usesPlatformStorage;
  Future<void> _writeQueue = Future<void>.value();
  int _generation = 0;

  @override
  String? get lastKnownAccountId => _lastKnownAccountId;

  bool get usesPlatformStorage => _usesPlatformStorage;

  Future<void> _serializeWrite(Future<void> Function() write) {
    final Future<void> pending = _writeQueue.then((_) => write());
    _writeQueue = pending.catchError((Object _) {});
    return pending;
  }

  @override
  Future<void> save(String token) {
    final int generation = _generation;
    return _serializeWrite(() async {
      if (generation != _generation) return;
      await _storage.write(key: _tokenKey, value: token);
    });
  }

  @override
  Future<String?> read() => _storage.read(key: _tokenKey);

  @override
  Future<void> saveAccountId(String accountId) {
    _accountIdRevision++;
    _lastKnownAccountId = accountId;
    final int generation = _generation;
    return _serializeWrite(() async {
      if (generation != _generation) return;
      await _storage.write(key: _accountIdKey, value: accountId);
    });
  }

  @override
  Future<String?> readAccountId() async {
    final int revision = _accountIdRevision;
    await _writeQueue;
    final String? accountId = await _storage.read(key: _accountIdKey);
    if (revision == _accountIdRevision) {
      _lastKnownAccountId = accountId;
    }
    return accountId;
  }

  @override
  Future<void> clear() {
    _accountIdRevision++;
    _lastKnownAccountId = null;
    final int generation = ++_generation;
    return _serializeWrite(() async {
      await _storage.delete(key: _tokenKey);
      if (generation != _generation) return;
      await _storage.delete(key: _accountIdKey);
    });
  }
}

class InMemoryTokenStore implements TokenStore {
  String? _token;
  String? _accountId;

  @override
  String? get lastKnownAccountId => _accountId;

  @override
  Future<void> save(String token) async => _token = token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> saveAccountId(String accountId) async => _accountId = accountId;

  @override
  Future<String?> readAccountId() async => _accountId;

  @override
  Future<void> clear() async {
    _token = null;
    _accountId = null;
  }
}
