import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/models.dart';
import 'auth_repository.dart';
import 'google_auth_gateway.dart';

enum AuthStatus { loading, unauthenticated, authenticated }

/// The first Google sign-up waiting for its nudge or username choice (#174).
class PendingGoogleSignup {
  const PendingGoogleSignup({
    required this.signupTicket,
    required this.suggestedUsername,
    required this.idToken,
    this.existingAccountHint = false,
  });

  final String signupTicket;
  final String suggestedUsername;
  final String idToken;
  final bool existingAccountHint;
}

/// What one "Continue with Google" tap produced (#115).
sealed class ContinueWithGoogleResult {
  const ContinueWithGoogleResult();
}

/// The Google subject was already linked: the session is applied.
final class GoogleSignInDone extends ContinueWithGoogleResult {
  const GoogleSignInDone();
}

/// No account exists yet: open the username picker.
final class GoogleSignUpPrompt extends ContinueWithGoogleResult {
  const GoogleSignUpPrompt();
}

/// The person dismissed the Google sheet; nothing happened.
final class GoogleSignInDismissed extends ContinueWithGoogleResult {
  const GoogleSignInDismissed();
}

/// The SDK refused; [message] explains it on the sign-in screen.
final class GoogleSignInRefused extends ContinueWithGoogleResult {
  const GoogleSignInRefused(this.message, {this.failureMessage});

  final String message;
  final FailureMessage? failureMessage;
}

/// What `POST /auth/google/complete` produced (#115).
sealed class CompleteGoogleSignupResult {
  const CompleteGoogleSignupResult();
}

/// The account was created and the device signed in.
final class GoogleSignupDone extends CompleteGoogleSignupResult {
  const GoogleSignupDone();
}

/// The picked username is already taken; the live check shows the same error.
final class GoogleUsernameTaken extends CompleteGoogleSignupResult {
  const GoogleUsernameTaken();
}

/// The signup ticket aged out: back to sign-in with a short explanation.
final class GoogleSignupTicketExpired extends CompleteGoogleSignupResult {
  const GoogleSignupTicketExpired();
}

/// Any other refusal; [message] explains it on the picker.
final class GoogleSignupRefused extends CompleteGoogleSignupResult {
  const GoogleSignupRefused(this.message, {this.failureMessage});

  final String message;
  final FailureMessage? failureMessage;
}

/// The subject turned out to be linked after all: the ticket is dead and the
/// person belongs on sign-in, not on the picker.
final class GoogleAccountAlreadyLinked extends CompleteGoogleSignupResult {
  const GoogleAccountAlreadyLinked();
}

/// One short line for every "the signup ticket aged out" exit (#115).
const String kGoogleSignupExpiredMessage =
    'Your Google sign-up expired. Please try again.';

/// What `POST /auth/google/link` produced for the Settings section (#116).
sealed class ConnectGoogleResult {
  const ConnectGoogleResult();
}

/// The subject is connected to this account now.
final class GoogleConnectDone extends ConnectGoogleResult {
  const GoogleConnectDone();
}

/// The person dismissed the Google sheet; nothing happened.
final class GoogleConnectDismissed extends ConnectGoogleResult {
  const GoogleConnectDismissed();
}

/// The SDK or the service refused; [message] explains it in the section. Both
/// connect conflicts (409) arrive here verbatim (#114).
final class GoogleConnectRefused extends ConnectGoogleResult {
  const GoogleConnectRefused(this.message, {this.failureMessage});

  final String message;
  final FailureMessage? failureMessage;
}

/// What deleting a Google-only account produced (#116).
sealed class DeleteWithGoogleResult {
  const DeleteWithGoogleResult();
}

/// The account is deleted and the Google SDK's own state was dropped too.
final class DeleteWithGoogleDone extends DeleteWithGoogleResult {
  const DeleteWithGoogleDone();
}

/// The person dismissed the Google sheet; nothing was deleted.
final class DeleteWithGoogleDismissed extends DeleteWithGoogleResult {
  const DeleteWithGoogleDismissed();
}

/// The SDK or the service refused; [message] explains it in the dialog.
final class DeleteWithGoogleRefused extends DeleteWithGoogleResult {
  const DeleteWithGoogleRefused(this.message, {this.failureMessage});

  final String message;
  final FailureMessage? failureMessage;
}

/// The deletion dialog's line for a dismissed Google sheet (#116).
const String kGoogleDeleteCancelledMessage =
    'Google sign-in was cancelled. Your account was not deleted.';

/// `service/google_sign_in.py::ALREADY_LINKED`, echoed verbatim by
/// `POST /auth/google/complete` as a 409 (#113). The service sends no machine
/// code with it, so the detail is what distinguishes this from a taken
/// username.
const String kGoogleAlreadyLinkedMessage =
    'This Google account is already linked to a MAYOS account.';

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
  AuthController(
    this._repository,
    this._events,
    this._accountDeletedEvents,
    this._google,
  ) : super(const AuthState.loading()) {
    _events.addListener(_onUnauthorized);
    _accountDeletedEvents.addListener(_onAccountDeleted);
  }

  final AuthRepository _repository;
  final UnauthorizedEvents _events;
  final AccountDeletedEvents _accountDeletedEvents;
  final GoogleAuthGateway _google;

  PendingGoogleSignup? _pendingSignup;
  int _displayLanguageRevision = 0;

  /// The sign-up the username picker is completing, or null when none is open.
  PendingGoogleSignup? get pendingSignup => _pendingSignup;

  /// Resolves a persisted session once at startup.
  /// Returns true when startup definitively has no session; false for an
  /// authenticated restore or a transient failure where the cached token stays.
  Future<bool> initialize() async {
    try {
      final AccountSession? session = await _repository.restore();
      // Preserve a notice an account-deleted signal may have set mid-restore so
      // the login screen can explain why the session ended (ADR 039).
      state = session == null
          ? AuthState.unauthenticated(state.notice)
          : AuthState.authenticated(session);
      return session == null;
    } on Object {
      // Any transport or non-401 service failure is transient. Keep the token
      // and account-language cache so the user can retry when connectivity is
      // restored. AuthRepository converts definitive 401s to a null session.
      state = const AuthState.unauthenticated();
      return false;
    }
  }

  Future<void> register({
    required String username,
    required String password,
    bool rememberMe = false,
    String? coachInviteCode,
    String displayLanguage = 'en',
  }) async {
    final AccountSession session = await _repository.register(
      username: username,
      password: password,
      rememberMe: rememberMe,
      coachInviteCode: coachInviteCode,
      displayLanguage: displayLanguage,
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
    // The MAYOS session is over, so the Google SDK's own is too (#115).
    await _google.clearSdkState();
    state = const AuthState.unauthenticated();
  }

  /// Applies a server-confirmed Display language without changing Account
  /// capability, plan, or Player/Coach mode state.
  bool ownsAccount(String accountId) =>
      state.session?.account.accountId == accountId;

  bool confirmDisplayLanguage(String accountId, String language) {
    final AccountSession? session = state.session;
    if (session == null ||
        !ownsAccount(accountId) ||
        !isSupportedDisplayLanguage(language)) {
      return false;
    }
    _displayLanguageRevision++;
    state = AuthState.authenticated(
      AccountSession(
        account: session.account.withDisplayLanguage(language),
        onboarded: session.onboarded,
        hasRecoveryEmail: session.hasRecoveryEmail,
        recoveryEmail: session.recoveryEmail,
      ),
      notice: state.notice,
    );
    return true;
  }

  Future<bool> updateAnalyticsAllowed(String accountId, bool allowed) async {
    if (!ownsAccount(accountId)) return false;
    await _repository.updateAnalyticsAllowed(allowed);
    final AccountSession? session = state.session;
    if (session == null || !ownsAccount(accountId)) return false;
    state = AuthState.authenticated(
      AccountSession(
        account: session.account.copyWith(analyticsAllowed: allowed),
        onboarded: session.onboarded,
        hasRecoveryEmail: session.hasRecoveryEmail,
        recoveryEmail: session.recoveryEmail,
      ),
      notice: state.notice,
    );
    return true;
  }

  /// One "Continue with Google" tap: get an ID token, then hand it to
  /// `POST /auth/google`. A linked subject signs in exactly like password
  /// login; any other subject parks a signup ticket for the picker.
  Future<ContinueWithGoogleResult> continueWithGoogle() async {
    final GoogleAuthOutcome outcome = await _google.authenticate();
    return continueWithGoogleOutcome(outcome);
  }

  /// Applies a completed web-button event through the same sign-in flow.
  Future<ContinueWithGoogleResult> continueWithGoogleOutcome(
      GoogleAuthOutcome outcome) async {
    return _handleGoogleOutcome(
      outcome,
      onCanceled: () => const GoogleSignInDismissed(),
      onFailed: (GoogleAuthFailed failure) => GoogleSignInRefused(
        failure.message,
        failureMessage: failure.failureMessage,
      ),
      onIdToken: _continueWithGoogleToken,
    );
  }

  Future<ContinueWithGoogleResult> _continueWithGoogleToken(
      String idToken) async {
    try {
      final GoogleSignInFlowResult result =
          await _repository.signInWithGoogle(idToken: idToken);
      if (result case GoogleAccountReady(:final session)) {
        state = AuthState.authenticated(session);
        return const GoogleSignInDone();
      }
      final GoogleUsernameRequired required = result as GoogleUsernameRequired;
      _pendingSignup = PendingGoogleSignup(
        signupTicket: required.signupTicket,
        suggestedUsername: required.suggestedUsername,
        idToken: required.idToken,
        existingAccountHint: required.existingAccountHint,
      );
      return const GoogleSignUpPrompt();
    } on ApiException catch (error) {
      return GoogleSignInRefused(
        error.message,
        failureMessage: apiFailureMessage(error),
      );
    }
  }

  /// Live availability for the picker, authorised by the pending ticket.
  Future<bool> googleUsernameAvailable(String username) {
    final PendingGoogleSignup? pending = _pendingSignup;
    if (pending == null) {
      throw const ApiException(
          'Your Google sign-up expired. Please try again.');
    }
    return _repository.googleUsernameAvailable(
      signupTicket: pending.signupTicket,
      username: username,
    );
  }

  /// Picks the username and creates the account behind the pending ticket.
  Future<CompleteGoogleSignupResult> completeGoogleSignup(
      {required String username, String displayLanguage = 'en'}) async {
    final PendingGoogleSignup? pending = _pendingSignup;
    if (pending == null) {
      return const GoogleSignupTicketExpired();
    }
    try {
      final AccountSession session = await _repository.completeGoogleSignup(
        signupTicket: pending.signupTicket,
        username: username,
        idToken: pending.idToken,
        displayLanguage: displayLanguage,
      );
      _pendingSignup = null;
      state = AuthState.authenticated(session);
      return const GoogleSignupDone();
    } on ApiException catch (error) {
      if (error.statusCode == 401) {
        await _expireGoogleSignup();
        return const GoogleSignupTicketExpired();
      }
      if (error.statusCode == 409) {
        // Same status for both conflicts; only the detail tells them apart.
        if (error.message == kGoogleAlreadyLinkedMessage) {
          await abandonGoogleSignup(notice: kGoogleAlreadyLinkedMessage);
          return const GoogleAccountAlreadyLinked();
        }
        return const GoogleUsernameTaken();
      }
      return GoogleSignupRefused(
        error.message,
        failureMessage: apiFailureMessage(error),
      );
    }
  }

  /// Drops the pending ticket, signs the Google SDK out, and optionally hands
  /// [notice] to the sign-in screen (#115). No account is ever created here.
  Future<void> abandonGoogleSignup({String? notice}) async {
    if (_pendingSignup == null && notice == null) {
      return;
    }
    _pendingSignup = null;
    await _google.clearSdkState();
    if (notice != null) {
      state = AuthState.unauthenticated(notice);
    }
  }

  /// The ticket aged out: drop it and send the person back to sign-in with a
  /// short explanation (#115).
  Future<void> _expireGoogleSignup() =>
      abandonGoogleSignup(notice: kGoogleSignupExpiredMessage);

  /// Password-confirmed account deletion: on success the server has ended every
  /// session and removed the ledger, and the repository erased this device's
  /// protected data. The state moves to login with a confirmation (ADR 039).
  Future<void> deleteAccount(String password) async {
    await _repository.deleteAccount(password);
    state = const AuthState.unauthenticated(
        'Your account was deleted. Create a new account or sign in.');
  }

  /// Deletion of a Google-only account: re-run the Google flow for a fresh ID
  /// token, hand it to `DELETE /auth/account`, and drop the SDK's own state —
  /// the account and its link are gone, so nothing may linger on this device
  /// (#114/#116). A dismissed sheet deletes nothing.
  Future<DeleteWithGoogleResult> deleteAccountWithGoogle() async {
    final GoogleAuthOutcome outcome = await _google.authenticate();
    return deleteAccountWithGoogleOutcome(outcome);
  }

  /// Confirms deletion from Google's rendered web-button event.
  Future<DeleteWithGoogleResult> deleteAccountWithGoogleOutcome(
      GoogleAuthOutcome outcome) async {
    return _handleGoogleOutcome(
      outcome,
      onCanceled: () => const DeleteWithGoogleDismissed(),
      onFailed: (GoogleAuthFailed failure) => DeleteWithGoogleRefused(
        failure.message,
        failureMessage: failure.failureMessage,
      ),
      onIdToken: _deleteAccountWithGoogleToken,
    );
  }

  Future<DeleteWithGoogleResult> _deleteAccountWithGoogleToken(
      String googleIdToken) async {
    try {
      await _repository.deleteAccountWithGoogle(googleIdToken: googleIdToken);
    } on ApiException catch (error) {
      final FailureMessage failure = mutationFailureMessage(error);
      return DeleteWithGoogleRefused(
        failure.englishText,
        failureMessage: failure,
      );
    }
    await _google.clearSdkState();
    state = const AuthState.unauthenticated(
        'Your account was deleted. Create a new account or sign in.');
    return const DeleteWithGoogleDone();
  }

  /// One "Connect Google" tap in Settings: get an ID token from the SDK, then
  /// hand it to `POST /auth/google/link`. Cancellation is not an error; both
  /// service conflicts come back as [GoogleConnectRefused] messages.
  Future<ConnectGoogleResult> connectGoogle() async {
    final GoogleAuthOutcome outcome = await _google.authenticate();
    return connectGoogleOutcome(outcome);
  }

  /// Connects the Google identity delivered by the rendered web button.
  Future<ConnectGoogleResult> connectGoogleOutcome(
      GoogleAuthOutcome outcome) async {
    return _handleGoogleOutcome(
      outcome,
      onCanceled: () => const GoogleConnectDismissed(),
      onFailed: (GoogleAuthFailed failure) => GoogleConnectRefused(
        failure.message,
        failureMessage: failure.failureMessage,
      ),
      onIdToken: _connectGoogleToken,
    );
  }

  Future<T> _handleGoogleOutcome<T>(
    GoogleAuthOutcome outcome, {
    required T Function() onCanceled,
    required T Function(GoogleAuthFailed failure) onFailed,
    required Future<T> Function(String idToken) onIdToken,
  }) async {
    if (outcome is GoogleAuthCanceled) {
      return onCanceled();
    }
    if (outcome is GoogleAuthFailed) {
      return onFailed(outcome);
    }
    return onIdToken((outcome as GoogleAuthIdToken).idToken);
  }

  Future<ConnectGoogleResult> _connectGoogleToken(String googleIdToken) async {
    try {
      await _repository.linkGoogle(idToken: googleIdToken);
      return const GoogleConnectDone();
    } on ApiException catch (error) {
      return GoogleConnectRefused(
        error.message,
        failureMessage: apiFailureMessage(error),
      );
    }
  }

  /// Disconnects Google from Settings; the service refuses while the account
  /// has no password (#114), which the section already prevents.
  Future<void> disconnectGoogle() => _repository.unlinkGoogle();

  /// Gives a Google-only account its first password (#114). No session ends,
  /// so this device stays signed in and the section just re-reads `/auth/me`.
  Future<void> setInitialPassword(String newPassword) =>
      _repository.setInitialPassword(newPassword: newPassword);

  /// Replaces an existing password. The service revokes every session
  /// (ADR 006), so the local session ends here with an explanation.
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    await _repository.changePassword(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    state = const AuthState.unauthenticated(
        'Password changed. Please sign in again.');
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

  /// Redeems a Coach invite from MAYOS and applies the returned account.
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
        recoveryEmail: current.recoveryEmail,
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
    final int languageRevision = _displayLanguageRevision;
    try {
      final Account account = await _repository.currentAccount();
      if (!state.isAuthenticated ||
          state.session?.account.accountId != current.account.accountId) {
        return;
      }
      final Account refreshedAccount =
          _displayLanguageRevision == languageRevision
              ? account
              : account.copyWith(
                  displayLanguage: state.session!.account.displayLanguage,
                );
      state = AuthState.authenticated(
        AccountSession(
          account: refreshedAccount,
          onboarded: current.onboarded,
          hasRecoveryEmail: current.hasRecoveryEmail,
          recoveryEmail: current.recoveryEmail,
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
        account: account.copyWith(
          capabilities: Capabilities(
            player: account.capabilities.player,
            coach: false,
          ),
          plans: account.plans.withoutCoach(),
        ),
        onboarded: current.onboarded,
        hasRecoveryEmail: current.hasRecoveryEmail,
        recoveryEmail: current.recoveryEmail,
      ),
    );
  }

  /// Saves or corrects the recovery email while keeping the verification gate closed.
  Future<bool> setRecoveryEmail(String email) async {
    final AccountSession? before = state.session;
    final ({String email, bool verified}) saved =
        await _repository.setRecoveryEmail(email);
    final AccountSession? session = state.session;
    if (state.isAuthenticated &&
        before != null &&
        session?.account.accountId == before.account.accountId) {
      state = AuthState.authenticated(
        AccountSession(
          account: session!.account.copyWith(
            recoveryEmailVerified: saved.verified,
          ),
          onboarded: session.onboarded,
          hasRecoveryEmail: saved.email.isNotEmpty,
          recoveryEmail: saved.email,
        ),
      );
    }
    return saved.verified;
  }

  /// Sends a fresh code to the saved recovery email.
  Future<void> sendRecoveryEmailVerificationCode() async {
    await _repository.sendRecoveryEmailVerificationCode();
  }

  /// Verifies the saved recovery email and releases the authenticated gate.
  Future<void> verifyRecoveryEmail(String code) async {
    final AccountSession? before = state.session;
    await _repository.verifyRecoveryEmail(code);
    final AccountSession? session = state.session;
    if (state.isAuthenticated &&
        before != null &&
        session?.account.accountId == before.account.accountId) {
      state = AuthState.authenticated(
        AccountSession(
          account: session!.account.copyWith(recoveryEmailVerified: true),
          onboarded: session.onboarded,
          hasRecoveryEmail: session.hasRecoveryEmail,
          recoveryEmail: session.recoveryEmail,
        ),
      );
    }
  }

  /// Updates the local account summary after Settings completes a verified swap.
  void recoveryEmailChanged(String email) {
    final AccountSession? session = state.session;
    if (!state.isAuthenticated || session == null) return;
    state = AuthState.authenticated(
      AccountSession(
        account: session.account.copyWith(
          recoveryEmailVerified: true,
        ),
        onboarded: session.onboarded,
        hasRecoveryEmail: true,
        recoveryEmail: email,
      ),
    );
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
          recoveryEmail: session.recoveryEmail,
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
    unawaited(_google.clearSdkState());
  }

  /// A 401 carrying `account_deleted`: erase the account's protected local data
  /// (no keep/discard prompt) and end the session with an explanation (ADR 039).
  void _onAccountDeleted() {
    state = const AuthState.unauthenticated(
        'This account was deleted. Its data was removed from this device.');
    unawaited(_repository.handleAccountDeleted());
    unawaited(_google.clearSdkState());
  }

  @override
  void dispose() {
    _events.removeListener(_onUnauthorized);
    _accountDeletedEvents.removeListener(_onAccountDeleted);
    super.dispose();
  }
}
