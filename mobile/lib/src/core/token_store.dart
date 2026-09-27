import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists the bearer token. The production implementation backs onto the
/// Android Keystore via `flutter_secure_storage`; tests use [InMemoryTokenStore].
///
/// The immutable account id is persisted alongside the token so a device that
/// discovers its account was deleted can erase that account's protected local
/// data even before it has a live session (ADR 039).
abstract class TokenStore {
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
            );

  static const String _tokenKey = 'mayos.access_token';
  static const String _accountIdKey = 'mayos.account_id';

  final FlutterSecureStorage _storage;

  @override
  Future<void> save(String token) =>
      _storage.write(key: _tokenKey, value: token);

  @override
  Future<String?> read() => _storage.read(key: _tokenKey);

  @override
  Future<void> saveAccountId(String accountId) =>
      _storage.write(key: _accountIdKey, value: accountId);

  @override
  Future<String?> readAccountId() => _storage.read(key: _accountIdKey);

  @override
  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _accountIdKey);
  }
}

class InMemoryTokenStore implements TokenStore {
  String? _token;
  String? _accountId;

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
