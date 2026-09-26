import '../../../core/api_client.dart';
import '../../../core/chat_storage.dart';
import '../../../core/models.dart';
import '../../../core/token_store.dart';

/// Coordinates the API and the persisted token for the auth lifecycle.
class AuthRepository {
  AuthRepository({
    required ApiClient api,
    required TokenStore tokens,
    ChatCacheStore? chatCache,
  })  : _api = api,
        _tokens = tokens,
        _chatCache = chatCache;

  final ApiClient _api;
  final TokenStore _tokens;
  final ChatCacheStore? _chatCache;

  Future<AccountSession> register({
    required String username,
    required String password,
    bool rememberMe = false,
  }) {
    return _establishSession(
      () => _api.register(
          traineeId: username, password: password, rememberMe: rememberMe),
    );
  }

  Future<AccountSession> login({
    required String username,
    required String password,
    bool rememberMe = false,
  }) {
    return _establishSession(
      () => _api.login(
          traineeId: username, password: password, rememberMe: rememberMe),
    );
  }

  /// Restores a persisted session, or returns null when there is no live one.
  ///
  /// A 401 clears the stale token; any other failure (for example, no network)
  /// propagates so the caller can keep the token for a later retry.
  Future<AccountSession?> restore() async {
    final String? token = await _tokens.read();
    if (token == null || token.isEmpty) {
      return null;
    }
    try {
      return await _currentSession();
    } on ApiException catch (error) {
      if (error.statusCode == 401) {
        await _tokens.clear();
        return null;
      }
      rethrow;
    }
  }

  Future<String> setRecoveryEmail(String email) => _api.setRecoveryEmail(email);

  /// Requests a reset link, returning the service's constant confirmation.
  Future<String> forgotPassword(String email) => _api.forgotPassword(email);

  /// Redeems a single-use reset token, then drops the local session.
  ///
  /// The server revokes every prior session on success; clearing the device's
  /// stored token (and cached chat) keeps a bearer that is now invalid from
  /// lingering, so the next launch starts logged out.
  Future<void> resetPassword({
    required String token,
    required String newPassword,
    String? accountId,
  }) async {
    await _api.resetPassword(token: token, newPassword: newPassword);
    await clearSession(accountId: accountId);
  }

  /// Redeems an owner-issued coach invite and returns the updated account.
  ///
  /// The redeem response already carries the new capabilities, so no follow-up
  /// reads are issued: a transient failure after a committed grant must never
  /// make the one-use code look unredeemed.
  Future<Account> redeemCoachInvite(String token) =>
      _api.redeemCoachInvite(token);

  /// Re-reads the current account (live capabilities) for a resume refresh.
  Future<Account> currentAccount() => _api.currentAccount();

  Future<void> clearToken() => _tokens.clear();

  /// Ends the session and drops the account's cached chat history.
  ///
  /// History lives server-side, so clearing the local cache loses nothing; it
  /// keeps a private conversation from being readable by whoever holds the
  /// device next (ADR 036). Disclosure acceptance stays per account.
  Future<void> logout({String? accountId}) async {
    try {
      await _api.logout();
    } on ApiException {
      // Local session is cleared regardless; the server revokes on best effort.
    }
    await _clearChatCache(accountId);
    await _tokens.clear();
  }

  /// Drops the local session without a server call (the token is already
  /// invalid, e.g. after a 401): clears the account's cached chat history and
  /// the persisted token.
  Future<void> clearSession({String? accountId}) async {
    await _clearChatCache(accountId);
    await _tokens.clear();
  }

  Future<void> _clearChatCache(String? accountId) async {
    final ChatCacheStore? cache = _chatCache;
    if (cache == null || accountId == null) {
      return;
    }
    try {
      await cache.clearHistory(accountId);
    } on Object {
      // Best effort: a storage failure must never block logout.
    }
  }

  /// Persists the token issued by register/login, then resolves the session.
  Future<AccountSession> _establishSession(
      Future<AuthTokens> Function() authenticate) async {
    final AuthTokens auth = await authenticate();
    await _tokens.save(auth.accessToken);
    return _currentSession();
  }

  Future<AccountSession> _currentSession() async {
    final Account account = await _api.currentAccount();
    final bool onboarded = await _api.hasProfile();
    final String? email = await _api.recoveryEmail();
    return AccountSession(
      account: account,
      onboarded: onboarded,
      hasRecoveryEmail: email != null && email.isNotEmpty,
    );
  }
}
