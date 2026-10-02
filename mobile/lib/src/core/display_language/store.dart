import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../browser_key_value_store.dart';
import '../secure_store.dart';

abstract interface class DisplayLanguageStore {
  Future<String?> read();
  Future<void> write(String language);
  Future<String?> readAccount(String accountId);
  Future<void> writeAccount(String accountId, String language);
  Future<void> deleteAccount(String accountId);
}

final displayLanguageStoreProvider = Provider<DisplayLanguageStore>(
  (ref) => PlatformDisplayLanguageStore(),
);

class PlatformDisplayLanguageStore implements DisplayLanguageStore {
  PlatformDisplayLanguageStore(
      {SecureStore? secureStore,
      BrowserKeyValueStore? browserStorage,
      bool? isWeb})
      : _secure = secureStore ?? SecureStore(),
        _browser = browserStorage ?? createBrowserKeyValueStore(),
        _isWeb = isWeb ?? kIsWeb;
  final SecureStore _secure;
  final BrowserKeyValueStore _browser;
  final bool _isWeb;
  static const _key = 'mayos.display_language';
  static const _accountPrefix = 'mayos.display_language.account.';

  Future<String?> _secureRead(String key) async {
    try {
      return await _secure.readString(key);
    } on Object {
      // A keystore read failure must fall back to the system preference.
      return null;
    }
  }

  Future<void> _secureWrite(String key, String value) async {
    try {
      await _secure.writeString(key, value);
    } on Object {
      // Persistence is best-effort; the in-memory choice still applies.
    }
  }

  Future<void> _secureDelete(String key) async {
    try {
      await _secure.delete(key);
    } on Object {
      // Account cleanup must not prevent session teardown.
    }
  }

  @override
  Future<String?> read() async =>
      _isWeb ? _browser.getItem(_key) : _secureRead(_key);
  @override
  Future<void> write(String value) async {
    if (_isWeb) {
      _browser.setItem(_key, value);
    } else {
      await _secureWrite(_key, value);
    }
  }

  @override
  Future<String?> readAccount(String id) async => _isWeb
      ? _browser.getItem('$_accountPrefix$id')
      : _secureRead('$_accountPrefix$id');
  @override
  Future<void> writeAccount(String id, String value) async {
    if (_isWeb) {
      _browser.setItem('$_accountPrefix$id', value);
    } else {
      await _secureWrite('$_accountPrefix$id', value);
    }
  }

  @override
  Future<void> deleteAccount(String id) async {
    if (_isWeb) {
      _browser.removeItem('$_accountPrefix$id');
    } else {
      await _secureDelete('$_accountPrefix$id');
    }
  }
}

class InMemoryDisplayLanguageStore implements DisplayLanguageStore {
  String? value;
  final Map<String, String> accountValues = <String, String>{};
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String language) async => value = language;
  @override
  Future<String?> readAccount(String id) async => accountValues[id];
  @override
  Future<void> writeAccount(String id, String language) async =>
      accountValues[id] = language;
  @override
  Future<void> deleteAccount(String id) async {
    accountValues.remove(id);
  }
}
