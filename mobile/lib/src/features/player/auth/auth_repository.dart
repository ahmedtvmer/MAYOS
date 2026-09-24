import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/token_store.dart';

/// Coordinates the API and the persisted token for the auth lifecycle.
class AuthRepository {
  AuthRepository({required ApiClient api, required TokenStore tokens})
      : _api = api,
        _tokens = tokens;

  final ApiClient _api;
  final TokenStore _tokens;

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

  Future<void> logout() async {
    try {
      await _api.logout();
    } on ApiException {
      // Local session is cleared regardless; the server revokes on best effort.
    }
    await _tokens.clear();
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
