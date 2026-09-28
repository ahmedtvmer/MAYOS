import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/router.dart';

Account _account({required bool coach}) => Account(
      accountId: 'account-alice',
      traineeId: 'alice',
      capabilities: Capabilities(player: true, coach: coach),
    );

AuthState _authenticated({
  required bool coach,
  required bool onboarded,
  bool hasRecoveryEmail = true,
}) =>
    AuthState.authenticated(
      AccountSession(
        account: _account(coach: coach),
        onboarded: onboarded,
        hasRecoveryEmail: hasRecoveryEmail,
      ),
    );

/// A resolved mode state for [account-alice], the session these tests build.
///
/// `ready` / `accountId` model the startup gate: until the stored choice for
/// the signed-in account has been read, redirectFor holds on splash (#119).
AppModeState _mode(
  AppMode mode, {
  bool ready = true,
  String? accountId = 'account-alice',
}) =>
    AppModeState(mode: mode, ready: ready, accountId: accountId);

void main() {
  test('loading holds on splash and unauthenticated users go to login', () {
    expect(redirectFor(const AuthState.loading(), loginPath, _mode(AppMode.player)),
        splashPath);
    expect(
        redirectFor(const AuthState.loading(), splashPath, _mode(AppMode.player)),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), homePath, _mode(AppMode.player)),
        loginPath);
    expect(
        redirectFor(const AuthState.unauthenticated(), loginPath, _mode(AppMode.player)),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), registerPath,
            _mode(AppMode.player)),
        isNull);
  });

  test('password-recovery pages stay public through startup and login', () {
    // A deep link must survive the loading→unauthenticated startup resolution.
    expect(
        redirectFor(const AuthState.loading(), resetPasswordPath, _mode(AppMode.player)),
        isNull);
    expect(
        redirectFor(
            const AuthState.loading(), forgotPasswordPath, _mode(AppMode.player)),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), resetPasswordPath,
            _mode(AppMode.player)),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), forgotPasswordPath,
            _mode(AppMode.player)),
        isNull);
    // And it remains reachable for a signed-in device (success clears session).
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true),
          resetPasswordPath, _mode(AppMode.coach)),
      isNull,
    );
    expect(
      redirectFor(
          _authenticated(
              coach: false, onboarded: false, hasRecoveryEmail: false),
          forgotPasswordPath, _mode(AppMode.player)),
      isNull,
    );
  });

  test('recovery email gates the authenticated area (ADR 007)', () {
    final AuthState gated =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: false);
    expect(redirectFor(gated, homePath, _mode(AppMode.player)), recoveryEmailPath);
    expect(redirectFor(gated, onboardingPath, _mode(AppMode.player)),
        recoveryEmailPath);
    expect(redirectFor(gated, recoveryEmailPath, _mode(AppMode.player)), isNull);

    // Saving the email releases the gate to onboarding, then home.
    final AuthState set =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: true);
    expect(redirectFor(set, recoveryEmailPath, _mode(AppMode.player)), onboardingPath);
    final AuthState done =
        _authenticated(coach: false, onboarded: true, hasRecoveryEmail: true);
    expect(redirectFor(done, recoveryEmailPath, _mode(AppMode.player)), homePath);
  });

  test('recovery email stays ahead of the mode and deferred onboarding', () {
    // A coach in Coach mode without a recovery email still hits the ADR 007
    // gate first, even though Coach mode would otherwise ignore onboarding.
    final AuthState gated = _authenticated(
        coach: true, onboarded: false, hasRecoveryEmail: false);
    expect(redirectFor(gated, coachPath, _mode(AppMode.coach)), recoveryEmailPath);
    expect(redirectFor(gated, splashPath, _mode(AppMode.coach)), recoveryEmailPath);
    expect(redirectFor(gated, recoveryEmailPath, _mode(AppMode.coach)), isNull);
    // Releasing the gate then lands the coach in Coach mode.
    final AuthState released = _authenticated(
        coach: true, onboarded: false, hasRecoveryEmail: true);
    expect(redirectFor(released, recoveryEmailPath, _mode(AppMode.coach)), coachPath);
    expect(redirectFor(released, splashPath, _mode(AppMode.coach)), coachPath);
  });

  test('onboarding gates the authenticated area for players', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), homePath,
          _mode(AppMode.player)),
      onboardingPath,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), onboardingPath,
          _mode(AppMode.player)),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), homePath,
          _mode(AppMode.player)),
      isNull,
    );
  });

  test('a coach reaches Coach mode without completing player onboarding', () {
    final AuthState coach = _authenticated(coach: true, onboarded: false);
    // No forced trip to /onboarding: splash, recovery release and the player
    // shell all lead to the coach shell.
    expect(redirectFor(coach, splashPath, _mode(AppMode.coach)), coachPath);
    expect(redirectFor(coach, homePath, _mode(AppMode.coach)), coachPath);
    expect(redirectFor(coach, onboardingPath, _mode(AppMode.coach)), coachPath);
    // The coach shell itself is the landing.
    expect(redirectFor(coach, coachPath, _mode(AppMode.coach)), isNull);
    // Awaiting the intake in Player mode is allowed too (the setup screen).
    expect(redirectFor(coach, playerSetupPath, _mode(AppMode.player)), isNull);
  });

  test('a coach in Player mode without onboarding gets the setup screen', () {
    final AuthState coach = _authenticated(coach: true, onboarded: false);
    expect(redirectFor(coach, splashPath, _mode(AppMode.player)), playerSetupPath);
    expect(redirectFor(coach, homePath, _mode(AppMode.player)), playerSetupPath);
    expect(redirectFor(coach, recoveryEmailPath, _mode(AppMode.player)),
        playerSetupPath);
    // Once the intake completes, Player mode lands on the home shell.
    final AuthState onboarded = _authenticated(coach: true, onboarded: true);
    expect(redirectFor(onboarded, splashPath, _mode(AppMode.player)), homePath);
    expect(redirectFor(onboarded, playerSetupPath, _mode(AppMode.player)), homePath);
    expect(redirectFor(onboarded, onboardingPath, _mode(AppMode.player)), homePath);
  });

  test('coach route requires the coach capability and Coach mode', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachPath,
          _mode(AppMode.player)),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachPath,
          _mode(AppMode.coach)),
      isNull,
    );
    // A coach sitting in Player mode leaves the coach shell for their landing.
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachPath,
          _mode(AppMode.player)),
      homePath,
    );
  });

  test('coach invite route is open to authenticated players', () {
    // Any onboarded account may redeem an owner invite, coach or not.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachInvitePath,
          _mode(AppMode.player)),
      isNull,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachInvitePath,
          _mode(AppMode.player)),
      isNull,
    );
    // Onboarding still gates it for a plain player, like every surface.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), coachInvitePath,
          _mode(AppMode.player)),
      onboardingPath,
    );
  });

  test('any onboarded account may manage their own coaching assignment', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), assignmentPath,
          _mode(AppMode.player)),
      isNull,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), assignmentPath,
          _mode(AppMode.coach)),
      isNull,
    );
    // Onboarding still gates it, like every authenticated surface.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), assignmentPath,
          _mode(AppMode.player)),
      onboardingPath,
    );
  });

  test('the app holds on splash until this account\u2019s mode is resolved', () {
    final AuthState coach = _authenticated(coach: true, onboarded: true);
    // The stored choice is still being read: no shell may mount yet, so a
    // coach whose stored mode is Player never flashes Coach mode (#119).
    expect(redirectFor(coach, homePath, _mode(AppMode.coach, ready: false)),
        splashPath);
    expect(redirectFor(coach, coachPath, _mode(AppMode.coach, ready: false)),
        splashPath);
    // A resolved state belonging to another account (or to no account) is
    // equally unusable, which is what makes the decision independent of which
    // Riverpod listener runs first.
    expect(
      redirectFor(coach, homePath,
          _mode(AppMode.coach, accountId: 'account-other')),
      splashPath,
    );
    expect(
      redirectFor(coach, splashPath, _mode(AppMode.player, accountId: null)),
      splashPath,
    );
    // The recovery-email gate still comes first, mode pending or not.
    final AuthState gated =
        _authenticated(coach: true, onboarded: true, hasRecoveryEmail: false);
    expect(redirectFor(gated, homePath, _mode(AppMode.coach, ready: false)),
        recoveryEmailPath);
    // Once resolved for this account, the usual decision applies.
    expect(redirectFor(coach, splashPath, _mode(AppMode.coach)), coachPath);
    expect(redirectFor(coach, homePath, _mode(AppMode.coach)), coachPath);
  });
}
