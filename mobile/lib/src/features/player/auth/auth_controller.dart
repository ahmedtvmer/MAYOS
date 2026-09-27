import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import 'auth_repository.dart';

enum AuthStatus { loading, unauthenticated, authenticated }

@immutable
class AuthState {
  const AuthState._(this.status, this.session, this.notice);

  const AuthState.loading() : this._(AuthStatus.loading, null, null);

  const AuthState.unauthenticated([String? notice])
      : this._(AuthStatus.unauthenticated, null, notice);

  const AuthState.authenticated(AccountSession session, {String? notice})
      : this._(AuthStatus.authenticated, session, notice);

  final AuthStatus status;
  final AccountSession? session;

  /// A one-shot message to show on the login screen (for example, after account
  /// deletion). It is not a session: [isAuthenticated] ignores it.
  final String? notice;

  bool get isAuthenticated => status == AuthStatus.authenticated;

  AccountSession? get accountSession => session;
}

/// Signals a 401 observed on an authenticated request. Kept separate from the
/// API client so the two providers never depend on each other in a cycle.
class UnauthorizedEvents extends ChangeNotifier {
  void signal() => notifyListeners();
}

/// Signals a 401 carrying `account_deleted` for a validly signed token, so the
/// app erases that account's protected data instead of offering the logout
/// keep/discard choice (ADR 039).
class AccountDeletedEvents extends ChangeNotifier {
  void signal() => notifyListeners();
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._repository, this._events, this._accountDeletedEvents)
      : super(const AuthState.loading()) {
    _events.addListener(_onUnauthorized);
    _accountDeletedEvents.addListener(_onAccountDeleted);
  }

  final AuthRepository _repository;
  final UnauthorizedEvents _events;
  final AccountDeletedEvents _accountDeletedEvents;

  /// Resolves a persisted session once at startup.
  Future<void> initialize() async {
    try {
      final AccountSession? session = await _repository.restore();
      // Preserve a notice an account-deleted signal may have set mid-restore so
      // the login screen can explain why the session ended (ADR 039).
      state = session == null
          ? AuthState.unauthenticated(state.notice)
          : AuthState.authenticated(session);
    } on ApiException {
      // Network failure during restore: keep the token, ask the user to retry.
      state = const AuthState.unauthenticated();
    }
  }

  Future<void> register({
    required String username,
    required String password,
    bool rememberMe = false,
  }) async {
    final AccountSession session = await _repository.register(
      username: username,
      password: password,
      rememberMe: rememberMe,
    );
    state = AuthState.authenticated(session);
  }

  Future<void> login({
    required String username,
    required String password,
    bool rememberMe = false,
  }) async {
    final AccountSession session = await _repository.login(
      username: username,
      password: password,
      rememberMe: rememberMe,
    );
    state = AuthState.authenticated(session);
  }

  Future<void> logout() async {
    final String? accountId = state.session?.account.accountId;
    await _repository.logout(accountId: accountId);
    state = const AuthState.unauthenticated();
  }

  /// Password-confirmed account deletion: on success the server has ended every
  /// session and removed the ledger, and the repository erased this device's
  /// protected data. The state moves to login with a confirmation (ADR 039).
  Future<void> deleteAccount(String password) async {
    await _repository.deleteAccount(password);
    state = const AuthState.unauthenticated(
        'Your account was deleted. Create a new account or sign in.');
  }

  /// Requests a reset link and returns the service's constant confirmation.
  Future<String> requestPasswordReset(String email) =>
      _repository.forgotPassword(email);

  /// Completes a logged-out password reset and drops any local session.
  ///
  /// The reset revokes every prior session server-side (ADR 006), so the
  /// in-memory state is cleared as well as the stored token.
  Future<void> completePasswordReset({
    required String token,
    required String newPassword,
  }) async {
    final String? accountId = state.session?.account.accountId;
    await _repository.resetPassword(
      token: token,
      newPassword: newPassword,
      accountId: accountId,
    );
    state = const AuthState.unauthenticated();
  }

  /// Redeems an owner-issued coach invite and applies the returned account.
  ///
  /// The grant response is authoritative: onboarding and recovery-email flags
  /// are carried over from the current session, and no follow-up read is issued,
  /// so a transient later failure cannot make a committed grant look failed.
  Future<void> redeemCoachInvite(String token) async {
    final AccountSession? current = state.session;
    if (current == null) {
      return;
    }
    final Account account = await _repository.redeemCoachInvite(token);
    if (!state.isAuthenticated ||
        state.session?.account.accountId != current.account.accountId) {
      return;
    }
    state = AuthState.authenticated(
      AccountSession(
        account: account,
        onboarded: current.onboarded,
        hasRecoveryEmail: current.hasRecoveryEmail,
      ),
    );
  }

  /// Re-reads live capabilities on app resume; grants/revocations can happen
  /// elsewhere. Onboarding and recovery-email flags are preserved.
  ///
  /// A transient network failure leaves the current session untouched. A 401 is
  /// handled by the auth interceptor's unauthorized event, not here.
  Future<void> refreshAccount() async {
    final AccountSession? current = state.session;
    if (!state.isAuthenticated || current == null) {
      return;
    }
    try {
      final Account account = await _repository.currentAccount();
      if (!state.isAuthenticated ||
          state.session?.account.accountId != current.account.accountId) {
        return;
      }
      state = AuthState.authenticated(
        AccountSession(
          account: account,
          onboarded: current.onboarded,
          hasRecoveryEmail: current.hasRecoveryEmail,
        ),
      );
    } on ApiException {
      // Transient failure: keep the current session and capabilities.
    }
  }

  /// Applies a successful coach disable immediately, even if a later account read fails.
  void markCoachDisabled() {
    final AccountSession? current = state.session;
    if (!state.isAuthenticated || current == null) return;
    final Account account = current.account;
    state = AuthState.authenticated(
      AccountSession(
        account: Account(
          accountId: account.accountId,
          traineeId: account.traineeId,
          capabilities: Capabilities(
            player: account.capabilities.player,
            coach: false,
          ),
          plans: account.plans.withoutCoach(),
        ),
        onboarded: current.onboarded,
        hasRecoveryEmail: current.hasRecoveryEmail,
      ),
    );
  }

  /// Saves the mandatory recovery email, then releases the ADR 007 gate.
  Future<void> setRecoveryEmail(String email) async {
    await _repository.setRecoveryEmail(email);
    final AccountSession? session = state.session;
    if (state.isAuthenticated && session != null) {
      state = AuthState.authenticated(
        AccountSession(
          account: session.account,
          onboarded: session.onboarded,
          hasRecoveryEmail: true,
        ),
      );
    }
  }

  /// Called after `POST /onboarding/complete` succeeds.
  void markOnboarded() {
    final AccountSession? session = state.session;
    if (state.isAuthenticated && session != null) {
      state = AuthState.authenticated(
        AccountSession(
          account: session.account,
          onboarded: true,
          hasRecoveryEmail: session.hasRecoveryEmail,
        ),
      );
    }
  }

  void _onUnauthorized() {
    if (!state.isAuthenticated) {
      return;
    }
    final String? accountId = state.session?.account.accountId;
    state = const AuthState.unauthenticated();
    // Fire-and-forget: the in-memory state already reflects the logout. The
    // token is already invalid, so only the local state is dropped here.
    unawaited(_repository.clearSession(accountId: accountId));
  }

  /// A 401 carrying `account_deleted`: erase the account's protected local data
  /// (no keep/discard prompt) and end the session with an explanation (ADR 039).
  void _onAccountDeleted() {
    state = const AuthState.unauthenticated(
        'This account was deleted. Its data was removed from this device.');
    unawaited(_repository.handleAccountDeleted());
  }

  @override
  void dispose() {
    _events.removeListener(_onUnauthorized);
    _accountDeletedEvents.removeListener(_onAccountDeleted);
    super.dispose();
  }
}
