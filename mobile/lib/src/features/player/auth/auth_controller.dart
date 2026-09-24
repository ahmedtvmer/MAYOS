import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import 'auth_repository.dart';

enum AuthStatus { loading, unauthenticated, authenticated }

@immutable
class AuthState {
  const AuthState._(this.status, this.session);

  const AuthState.loading() : this._(AuthStatus.loading, null);

  const AuthState.unauthenticated() : this._(AuthStatus.unauthenticated, null);

  const AuthState.authenticated(AccountSession session)
      : this._(AuthStatus.authenticated, session);

  final AuthStatus status;
  final AccountSession? session;

  bool get isAuthenticated => status == AuthStatus.authenticated;

  AccountSession? get accountSession => session;
}

/// Signals a 401 observed on an authenticated request. Kept separate from the
/// API client so the two providers never depend on each other in a cycle.
class UnauthorizedEvents extends ChangeNotifier {
  void signal() => notifyListeners();
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._repository, this._events)
      : super(const AuthState.loading()) {
    _events.addListener(_onUnauthorized);
  }

  final AuthRepository _repository;
  final UnauthorizedEvents _events;

  /// Resolves a persisted session once at startup.
  Future<void> initialize() async {
    try {
      final AccountSession? session = await _repository.restore();
      state = session == null
          ? const AuthState.unauthenticated()
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
    await _repository.logout();
    state = const AuthState.unauthenticated();
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
    state = const AuthState.unauthenticated();
    // Fire-and-forget: the in-memory state already reflects the logout.
    unawaited(_repository.clearToken());
  }

  @override
  void dispose() {
    _events.removeListener(_onUnauthorized);
    super.dispose();
  }
}
