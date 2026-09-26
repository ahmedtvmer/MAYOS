import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'chat_models.dart';
import 'secure_store.dart';

/// Protected, account-separated storage for the hosted-processing disclosure
/// acceptance and a read-only cache of the player's chat history (#37).
///
/// Both are keyed by the immutable account id, so a new account on the same
/// device sees the disclosure again and never reads another account's history.
/// Like [DraftStore], this is only keystore-backed on the offline-capable
/// (non-web) client; web falls back to memory.
abstract class ChatCacheStore {
  Future<List<ChatMessage>> readHistory(String accountId);

  Future<void> writeHistory(String accountId, List<ChatMessage> messages);

  Future<void> clearHistory(String accountId);

  Future<bool> readDisclosureAccepted(String accountId);

  Future<void> writeDisclosureAccepted(String accountId);
}

class SecureChatCacheStore implements ChatCacheStore {
  SecureChatCacheStore({FlutterSecureStorage? storage})
      : _store = SecureStore(storage: storage);

  final SecureStore _store;

  static String _historyKey(String accountId) => 'chat_history.$accountId';

  static String _disclosureKey(String accountId) =>
      'chat_disclosure.$accountId';

  @override
  Future<List<ChatMessage>> readHistory(String accountId) async {
    final dynamic decoded = await _store.readJson(_historyKey(accountId));
    if (decoded is! List<dynamic>) {
      return <ChatMessage>[];
    }
    try {
      return decoded
          .whereType<Map<String, dynamic>>()
          .map(ChatMessage.fromJson)
          .toList(growable: false);
    } on FormatException {
      return <ChatMessage>[];
    } on TypeError {
      return <ChatMessage>[];
    }
  }

  @override
  Future<void> writeHistory(String accountId, List<ChatMessage> messages) =>
      _store
          .writeJson(key: _historyKey(accountId), value: <Map<String, dynamic>>[
        for (final ChatMessage message in messages) message.toJson(),
      ]);

  @override
  Future<void> clearHistory(String accountId) =>
      _store.delete(_historyKey(accountId));

  @override
  Future<bool> readDisclosureAccepted(String accountId) async =>
      await _store.readString(_disclosureKey(accountId)) == 'true';

  @override
  Future<void> writeDisclosureAccepted(String accountId) =>
      _store.writeString(_disclosureKey(accountId), 'true');
}

class InMemoryChatCacheStore implements ChatCacheStore {
  final Map<String, List<ChatMessage>> _history = <String, List<ChatMessage>>{};
  final Set<String> _accepted = <String>{};

  /// Test helper: seed an account's cached history directly.
  void seedHistory(String accountId, List<ChatMessage> messages) {
    _history[accountId] = List<ChatMessage>.of(messages);
  }

  @override
  Future<List<ChatMessage>> readHistory(String accountId) async =>
      List<ChatMessage>.of(_history[accountId] ?? <ChatMessage>[]);

  @override
  Future<void> writeHistory(
      String accountId, List<ChatMessage> messages) async {
    _history[accountId] = List<ChatMessage>.of(messages);
  }

  @override
  Future<void> clearHistory(String accountId) async {
    _history[accountId] = <ChatMessage>[];
  }

  @override
  Future<bool> readDisclosureAccepted(String accountId) async =>
      _accepted.contains(accountId);

  @override
  Future<void> writeDisclosureAccepted(String accountId) async {
    _accepted.add(accountId);
  }
}
