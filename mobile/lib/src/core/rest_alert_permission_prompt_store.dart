import 'package:flutter/services.dart'
    show MissingPluginException, PlatformException;

import 'secure_store.dart';

/// Per-account record that the rest-alert permission explanation was shown on
/// this device.
abstract class RestAlertPermissionPromptStore {
  Future<bool> wasShown(String accountId);

  Future<void> markShown(String accountId);
}

class SecureRestAlertPermissionPromptStore
    implements RestAlertPermissionPromptStore {
  SecureRestAlertPermissionPromptStore({SecureStore? store})
      : _store = store ?? SecureStore();

  final SecureStore _store;

  static String _key(String accountId) =>
      'rest_alert_permission_prompt.$accountId';

  @override
  Future<bool> wasShown(String accountId) async {
    try {
      return await _store.readString(_key(accountId)) == '1';
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  @override
  Future<void> markShown(String accountId) async {
    try {
      await _store.writeString(_key(accountId), '1');
    } on PlatformException {
      // A storage failure must not block onboarding completion.
    } on MissingPluginException {
      // A protected-storage failure must not block onboarding completion.
    }
  }
}

/// In-memory implementation for widget tests and previews.
class InMemoryRestAlertPermissionPromptStore
    implements RestAlertPermissionPromptStore {
  InMemoryRestAlertPermissionPromptStore([Set<String>? shownAccounts])
      : shownAccounts = shownAccounts ?? <String>{};

  final Set<String> shownAccounts;

  @override
  Future<bool> wasShown(String accountId) async =>
      shownAccounts.contains(accountId);

  @override
  Future<void> markShown(String accountId) async {
    shownAccounts.add(accountId);
  }
}
