import 'dart:async';

import '../../../core/account_data_eraser.dart';
import '../../../core/api_client.dart';
import '../../../core/chat_storage.dart';
import '../../../core/display_language/store.dart';
import '../../../core/first_touch.dart';
import '../../../core/models.dart';
import '../../../core/saved_player_data.dart';
import '../../../core/token_store.dart';
import '../../../core/token_subject.dart';

/// What the first Google sign-in needs from the screens (#115/#174).
sealed class GoogleSignInFlowResult {
  const GoogleSignInFlowResult();
}

/// A linked Google subject: the session is already applied.
final class GoogleAccountReady extends GoogleSignInFlowResult {
  const GoogleAccountReady(this.session);

  final AccountSession session;
}

/// No account yet: show the optional nudge before the picker for this ticket.
final class GoogleUsernameRequired extends GoogleSignInFlowResult {
  const GoogleUsernameRequired({
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

/// Coordinates the API and the persisted token for the auth lifecycle.
class AuthRepository {
  AuthRepository({
    required ApiClient api,
    required TokenStore tokens,
    required AccountDataEraser eraser,
    ChatCacheStore? chatCache,
    SavedPlayerDataStore? savedData,
    DisplayLanguageStore? displayLanguageStore,
    Future<FirstTouch?> Function()? readFirstTouch,
    Future<void> Function()? clearFirstTouch,
  })  : _api = api,
        _tokens = tokens,
        _eraser = eraser,
        _chatCache = chatCache,
        _savedData = savedData,
        _displayLanguageStore = displayLanguageStore,
        _readFirstTouch = readFirstTouch,
        _clearFirstTouch = clearFirstTouch;

  final ApiClient _api;
  final TokenStore _tokens;
  final AccountDataEraser _eraser;
  final ChatCacheStore? _chatCache;
  final SavedPlayerDataStore? _savedData;
  final DisplayLanguageStore? _displayLanguageStore;
  final Future<FirstTouch?> Function()? _readFirstTouch;
  final Future<void> Function()? _clearFirstTouch;
  final Set<Future<void>> _restoreWrites = <Future<void>>{};
  int _restoreRevision = 0;
  bool _sessionEnded = false;
  String? _knownAccountId;

  /// Only used after a transport failure, never to choose another account.
  Future<AccountSession?> savedSession() async {
    try {
      return await _readSavedSession();
    } on Object {
      // The bearer may be readable later even when its storage is unavailable now.
      return null;
    }
  }

  Future<AccountSession?> _readSavedSession() async {
    if (_sessionEnded) return null;
    final String? token = await _tokens.read();
    if (token == null || token.isEmpty) return null;
    final String? accountId = await _localAccountId();
    if (accountId == null) return null;
    final AccountSession? session = await _savedData?.session(accountId);
    if (await _tokens.read() != token) return null;
    return session;
  }

  Future<void> saveSession(
    AccountSession session, {
    int? expectedGeneration,
  }) async {
    final SavedPlayerDataStore? savedData = _savedData;
    if (savedData == null || _sessionEnded) return;
    final int dataGeneration = expectedGeneration ?? savedData.generation;
    try {
      await savedData.saveSession(
        session,
        expectedGeneration: dataGeneration,
      );
    } on Object {
      // A local snapshot failure cannot undo a server-confirmed session.
    }
  }

  void useSavedData() => _savedData?.useSavedData();

  void _invalidateRestores() => _restoreRevision++;

  Future<void> _endSession() async {
    _invalidateRestores();
    _sessionEnded = true;
    await _api.cancelAuthenticatedRequests();
  }

  Future<bool> _canPersistRestore(
    String token,
    int revision,
    int dataGeneration,
  ) async =>
      revision == _restoreRevision &&
      !_sessionEnded &&
      await _tokens.read() == token &&
      (_savedData?.generation ?? 0) == dataGeneration;

  Future<void> _persistRestoredSession(
    AccountSession session,
    String token,
    int revision,
    int dataGeneration,
  ) async {
    final Completer<void> completion = Completer<void>();
    final Future<void> pending = completion.future;
    _restoreWrites.add(pending);
    try {
      if (!await _canPersistRestore(token, revision, dataGeneration)) return;
      final Future<void> accountIdWrite =
          _saveAccountId(session.account.accountId);
      if (_usesPlatformTokenStorage) {
        // A restore must not wait for a platform-channel write. The token
        // store queues this write and invalidates it if teardown starts first.
        unawaited(accountIdWrite);
      } else {
        await accountIdWrite;
      }
      if (!await _canPersistRestore(token, revision, dataGeneration)) return;
      // Not awaited: a slow or unavailable store must not hold up sign-in. The
      // generation check drops this write if the session ends first.
      unawaited(saveSession(session, expectedGeneration: dataGeneration));
    } finally {
      _restoreWrites.remove(pending);
      completion.complete();
    }
  }

  Future<void> _waitForRestoreWrites() async {
    while (_restoreWrites.isNotEmpty) {
      await Future.wait<void>(List<Future<void>>.of(_restoreWrites));
    }
  }

  Future<Map<String, String>?> _registrationFirstTouch() async {
    final Future<FirstTouch?> Function()? readFirstTouch = _readFirstTouch;
    if (readFirstTouch == null) return null;
    try {
      final FirstTouch? touch = await Future<FirstTouch?>.sync(readFirstTouch)
          .timeout(firstTouchCaptureTimeout);
      return touch?.toJson();
    } catch (_) {
      return null;
    }
  }

  Future<void> _clearFirstTouchAfterRegistration() async {
    final Future<void> Function()? clearFirstTouch = _clearFirstTouch;
    if (clearFirstTouch == null) return;
    try {
      await clearFirstTouch().timeout(firstTouchCaptureTimeout);
    } catch (_) {
      // A storage failure must not fail a successful registration.
    }
  }

  Future<AccountSession> register({
    required String username,
    required String password,
    bool rememberMe = false,
    String? coachInviteCode,
    String displayLanguage = 'en',
  }) async {
    final Map<String, String>? firstTouch = await _registrationFirstTouch();
    return _establishSession(() async {
      final AuthTokens tokens = await _api.register(
        traineeId: username,
        password: password,
        rememberMe: rememberMe,
        coachInviteCode: coachInviteCode,
        displayLanguage: displayLanguage,
        firstTouch: firstTouch,
      );
      await _clearFirstTouchAfterRegistration();
      return tokens;
    });
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

  /// Exchanges a Google ID token for either a session or a signup ticket
  /// (#113/#115). A session is applied through the same path password login
  /// uses, so a Google sign-in lands exactly like a password one.
  Future<GoogleSignInFlowResult> signInWithGoogle(
      {required String idToken}) async {
    final GoogleAuthStart start = await _api.googleSignIn(idToken: idToken);
    if (start case GoogleAuthSession(:final tokens)) {
      return GoogleAccountReady(await _establishSession(() async => tokens));
    }
    final GoogleAuthSignupTicket ticket = start as GoogleAuthSignupTicket;
    return GoogleUsernameRequired(
      signupTicket: ticket.signupTicket,
      suggestedUsername: ticket.suggestedUsername,
      idToken: ticket.idToken,
      existingAccountHint: ticket.existingAccountHint,
    );
  }

  /// Creates the account behind a signup ticket and signs the device in.
  Future<AccountSession> completeGoogleSignup({
    required String signupTicket,
    required String username,
    required String idToken,
    String displayLanguage = 'en',
  }) async {
    final Map<String, String>? firstTouch = await _registrationFirstTouch();
    return _establishSession(() async {
      final AuthTokens tokens = await _api.googleComplete(
        signupTicket: signupTicket,
        username: username,
        idToken: idToken,
        displayLanguage: displayLanguage,
        firstTouch: firstTouch,
      );
      await _clearFirstTouchAfterRegistration();
      return tokens;
    });
  }

  /// Asks whether [username] is still free, authorised by the signup ticket.
  Future<bool> googleUsernameAvailable({
    required String signupTicket,
    required String username,
  }) =>
      _api.usernameAvailable(username, ticket: signupTicket);

  /// Restores a persisted session, or returns null when there is no live one.
  /// A 401 ends the session; other failures propagate for the controller to
  /// classify. Only a transport failure may fall back to a saved session. A
  /// 401 carrying `account_deleted` also erases protected local data (ADR 039).
  Future<AccountSession?> restore() async {
    if (_sessionEnded) return null;
    final int revision = _restoreRevision;
    final int dataGeneration = _savedData?.generation ?? 0;
    final String? token = await _tokens.read();
    if (revision != _restoreRevision || token == null || token.isEmpty) {
      return null;
    }
    try {
      final AccountSession session = await _currentSession();
      if (!await _canPersistRestore(token, revision, dataGeneration)) {
        return null;
      }
      _knownAccountId = session.account.accountId;
      await _persistRestoredSession(
        session,
        token,
        revision,
        dataGeneration,
      );
      if (!await _canPersistRestore(token, revision, dataGeneration)) {
        return null;
      }
      _savedData?.confirmSession();
      return session;
    } on ApiException catch (error) {
      if (error.statusCode == 401 || error.errorCode == 'account_deleted') {
        final String? accountId = unverifiedTokenSubject(token) ??
            _knownAccountId ??
            await _localAccountIdForCleanup();
        if (error.errorCode == 'account_deleted') {
          await handleAccountDeleted(accountId: accountId);
        } else {
          await clearSession(accountId: accountId);
        }
        return null;
      }
      rethrow;
    }
  }

  /// Confirms deletion with the password, then erases this account's protected
  /// local data and clears the session.
  ///
  /// The server call must succeed first, so a wrong password or an offline
  /// attempt changes nothing locally (ADR 039).
  Future<void> deleteAccount(String password) async {
    final String? accountId = _knownAccountId ?? await _localAccountId();
    await _api.deleteAccount(password);
    await _endSession();
    await _erasePrivateAccountData(accountId);
    if (!_usesPlatformTokenStorage) await _waitForRestoreWrites();
    await _clearPersistedTokens();
    _deleteDisplayLanguageCacheBestEffort(accountId);
  }

  /// The Google-proof deletion a Google-only account uses (#114): the same
  /// erase path, only the proof differs. A refusal changes nothing locally.
  Future<void> deleteAccountWithGoogle({required String googleIdToken}) async {
    final String? accountId = _knownAccountId ?? await _localAccountId();
    await _api.deleteAccountWithGoogle(googleIdToken: googleIdToken);
    await _endSession();
    await _erasePrivateAccountData(accountId);
    if (!_usesPlatformTokenStorage) await _waitForRestoreWrites();
    await _clearPersistedTokens();
    _deleteDisplayLanguageCacheBestEffort(accountId);
  }

  /// Connects the Google subject verified from [idToken] to this account.
  Future<void> linkGoogle({required String idToken}) =>
      _api.linkGoogle(idToken: idToken);

  /// Disconnects Google; the service refuses with 409 while the account has
  /// no password (#114).
  Future<void> unlinkGoogle() => _api.unlinkGoogle();

  /// Gives a passwordless account its first password (#114). The session
  /// epoch is untouched, so this device stays signed in.
  Future<void> setInitialPassword({required String newPassword}) =>
      _api.setInitialPassword(newPassword: newPassword);

  /// Replaces an existing password. The service revokes every session, so the
  /// local token is dropped too and the person signs in again (ADR 006).
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final String? accountId = _knownAccountId ?? await _localAccountId();
    await _api.changePassword(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    await clearSession(accountId: accountId);
  }

  /// Handles a request that reported `account_deleted`: erase the account's
  /// protected local data and clear the local session (ADR 039).
  Future<void> handleAccountDeleted({String? accountId}) async {
    await _endSession();
    final String? localAccountId =
        accountId ?? _knownAccountId ?? await _localAccountIdForCleanup();
    await _erasePrivateAccountData(localAccountId);
    if (!_usesPlatformTokenStorage) await _waitForRestoreWrites();
    await _clearPersistedTokens();
    _deleteDisplayLanguageCacheBestEffort(localAccountId);
  }

  /// Clears the account's private local data before dropping its credentials.
  Future<void> _erasePrivateAccountData(String? accountId) async {
    if (accountId == null || accountId.isEmpty) {
      return;
    }
    final SavedPlayerDataStore? savedData = _savedData;
    if (savedData != null) {
      final Future<void> savedDataCleanup = savedData.clearAccount(accountId);
      savedData.confirmSession();
      await _completeStorageCleanup(
        savedDataCleanup,
        usesPlatformStorage: savedData.usesPlatformStorage,
      );
    }
    await _eraser.erase(accountId);
  }

  bool get _usesPlatformTokenStorage => switch (_tokens) {
        SecureTokenStore store => store.usesPlatformStorage,
        _ => false,
      };

  Future<void> _completeStorageCleanup(
    Future<void> cleanup, {
    required bool usesPlatformStorage,
  }) async {
    if (usesPlatformStorage) {
      unawaited(cleanup.catchError((Object _) {}));
      return;
    }
    try {
      await cleanup;
    } on Object {
      // Cleanup is best effort; storage failure must not keep the session open.
    }
  }

  void _trackCleanup(
    Future<void> cleanup,
    bool usesPlatformStorage,
    List<Future<void>> awaitForInjectedStores,
  ) {
    final Future<void> bestEffort = cleanup.catchError((Object _) {});
    if (usesPlatformStorage) {
      unawaited(bestEffort);
    } else {
      awaitForInjectedStores.add(bestEffort);
    }
  }

  /// Language-cache cleanup is non-critical and must not hold up session teardown.
  void _deleteDisplayLanguageCacheBestEffort(String? accountId) {
    if (accountId == null || accountId.isEmpty) return;
    final DisplayLanguageStore? store = _displayLanguageStore;
    if (store == null) return;
    unawaited(store.deleteAccount(accountId).catchError((Object _) {
      // Best effort: language preference cleanup must never block or fail teardown.
    }));
  }

  /// The immutable account id for local-key lookup, from the bearer subject or
  /// the persisted id when the subject is unavailable.
  ///
  /// The claim is decoded without signature verification and used only to find
  /// this device's account-namespaced keys; it never authorises a request.
  Future<String?> _localAccountId() async {
    final String? subject = unverifiedTokenSubject(await _tokens.read());
    if (subject != null && subject.isNotEmpty) {
      _knownAccountId = subject;
      return subject;
    }
    final String? stored = await _tokens.readAccountId();
    if (stored != null && stored.isNotEmpty) {
      _knownAccountId = stored;
      return stored;
    }
    final String? fallback = unverifiedTokenSubject(await _tokens.read());
    _knownAccountId = fallback;
    return fallback;
  }

  Future<void> _saveAccountId(String accountId) async {
    try {
      await _tokens.saveAccountId(accountId);
    } on Object {
      // The account id is a convenience for deletion; never block a session.
    }
  }

  Future<({String email, bool verified})> setRecoveryEmail(String email) =>
      _api.setRecoveryEmail(email);

  Future<bool> setProductEmailConsent(bool optedIn) =>
      _api.setProductEmailConsent(optedIn);

  Future<void> sendRecoveryEmailVerificationCode() =>
      _api.sendRecoveryEmailVerificationCode();

  Future<void> verifyRecoveryEmail(String code) =>
      _api.verifyRecoveryEmail(code);

  /// Requests a reset link, returning the service's constant confirmation.
  Future<String> forgotPassword(
    String email, {
    required String displayLanguage,
  }) =>
      _api.forgotPassword(email, displayLanguage: displayLanguage);

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

  /// Redeems a Coach invite from MAYOS and returns the updated account.
  ///
  /// The redeem response already carries the new capabilities, so no follow-up
  /// reads are issued: a transient failure after a committed grant must never
  /// make the one-use code look unredeemed.
  Future<Account> redeemCoachInvite(String token) =>
      _api.redeemCoachInvite(token);

  /// Re-reads the current account (live capabilities) for a resume refresh.
  Future<Account> currentAccount() => _api.currentAccount();

  Future<void> updateDisplayLanguage(String language) =>
      _api.updateDisplayLanguage(language);

  Future<void> clearToken() => _tokens.clear();

  /// Ends the session and drops the account's cached chat history.
  ///
  /// History lives server-side, so clearing the local cache loses nothing; it
  /// keeps a private conversation from being readable by whoever holds the
  /// device next (ADR 036). Disclosure acceptance stays per account.
  Future<void> logout({String? accountId}) async {
    await _endSession();
    final int teardownRevision = _restoreRevision;
    final Future<void> readCacheCleanup = _clearReadCaches(accountId);
    try {
      await _api.logout();
    } on ApiException {
      // Local session is cleared regardless; the server revokes on best effort.
    }
    await readCacheCleanup;
    if (!_usesPlatformTokenStorage) await _waitForRestoreWrites();
    if (teardownRevision == _restoreRevision) {
      await _clearPersistedTokens();
    }
  }

  /// Drops the local session without a server call (the token is already
  /// invalid, e.g. after a 401): clears the account's cached chat history and
  /// the persisted token.
  Future<void> clearSession({String? accountId}) async {
    await _endSession();
    await _clearReadCaches(accountId);
    if (!_usesPlatformTokenStorage) await _waitForRestoreWrites();
    await _clearPersistedTokens();
  }

  Future<void> _clearPersistedTokens() async {
    await _completeStorageCleanup(
      _tokens.clear(),
      usesPlatformStorage: _usesPlatformTokenStorage,
    );
  }

  Future<String?> _bestEffortLocalAccountId() async {
    try {
      return await _localAccountId();
    } on Object {
      // Cache lookup failure must not prevent dropping the bearer on logout.
      return null;
    }
  }

  Future<String?> _localAccountIdForCleanup() async {
    if (_usesPlatformTokenStorage) return null;
    return _bestEffortLocalAccountId();
  }

  Future<void> _clearReadCaches(String? accountId) async {
    final String? localAccountId = accountId ??
        _knownAccountId ??
        await _localAccountIdForCleanup();
    await _clearSavedReads(localAccountId);
  }

  Future<void> _clearSavedReads(String? localAccountId) async {
    final List<Future<void>> awaitForInjectedStores = <Future<void>>[];
    if (localAccountId != null) {
      _startSavedDataClear(localAccountId, awaitForInjectedStores);
      _startChatCacheClear(localAccountId, awaitForInjectedStores);
    }
    _savedData?.confirmSession();
    await Future.wait<void>(awaitForInjectedStores);
  }

  void _startSavedDataClear(
    String accountId,
    List<Future<void>> awaitForInjectedStores,
  ) {
    final SavedPlayerDataStore? savedData = _savedData;
    if (savedData == null) return;
    _trackCleanup(
      savedData.clearAccount(accountId),
      savedData.usesPlatformStorage,
      awaitForInjectedStores,
    );
  }

  void _startChatCacheClear(
    String accountId,
    List<Future<void>> awaitForInjectedStores,
  ) {
    final ChatCacheStore? cache = _chatCache;
    if (cache == null) return;
    _trackCleanup(
      cache.clearHistory(accountId),
      cache is SecureChatCacheStore && cache.usesPlatformStorage,
      awaitForInjectedStores,
    );
  }

  /// Persists the token issued by register/login, then resolves the session.
  Future<AccountSession> _establishSession(
      Future<AuthTokens> Function() authenticate) async {
    _invalidateRestores();
    final AuthTokens auth = await authenticate();
    // A new bearer must never inherit the previous account's local key lookup.
    await _tokens.clear();
    await _tokens.save(auth.accessToken);
    final AccountSession session = await _currentSession();
    _knownAccountId = session.account.accountId;
    await _saveAccountId(session.account.accountId);
    _sessionEnded = false;
    unawaited(saveSession(session));
    _savedData?.confirmSession();
    return session;
  }

  Future<AccountSession> _currentSession() async {
    final Account account = await _api.currentAccount();
    final bool onboarded = await _api.hasProfile();
    final String? email = (await _api.recoveryEmailDetails()).email;
    return AccountSession(
      account: account,
      onboarded: onboarded,
      hasRecoveryEmail: email != null && email.isNotEmpty,
      recoveryEmail: email,
    );
  }
}
