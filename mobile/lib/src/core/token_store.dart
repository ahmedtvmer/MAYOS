import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists the bearer token. The production implementation backs onto the
/// Android Keystore via `flutter_secure_storage`; tests use [InMemoryTokenStore].
abstract class TokenStore {
  Future<void> save(String token);

  Future<String?> read();

  Future<void> clear();
}

class SecureTokenStore implements TokenStore {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  static const String _tokenKey = 'mayos.access_token';

  final FlutterSecureStorage _storage;

  @override
  Future<void> save(String token) =>
      _storage.write(key: _tokenKey, value: token);

  @override
  Future<String?> read() => _storage.read(key: _tokenKey);

  @override
  Future<void> clear() => _storage.delete(key: _tokenKey);
}

class InMemoryTokenStore implements TokenStore {
  String? _token;

  @override
  Future<void> save(String token) async => _token = token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> clear() async => _token = null;
}
