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

void main() {
  test('loading holds on splash and unauthenticated users go to login', () {
    expect(redirectFor(const AuthState.loading(), loginPath, AppMode.player),
        splashPath);
    expect(
        redirectFor(const AuthState.loading(), splashPath, AppMode.player),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), homePath, AppMode.player),
        loginPath);
    expect(
        redirectFor(const AuthState.unauthenticated(), loginPath, AppMode.player),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), registerPath,
            AppMode.player),
        isNull);
    // The claim surface is public while logged out, and a signed-in device
    // leaves it for the authenticated area.
    expect(
        redirectFor(const AuthState.unauthenticated(), claimPath, AppMode.player),
        isNull);
    expect(
      redirectFor(
          _authenticated(coach: false, onboarded: true), claimPath,
          AppMode.player),
      homePath,
    );
  });

  test('password-recovery pages stay public through startup and login', () {
    // A deep link must survive the loading→unauthenticated startup resolution.
    expect(
        redirectFor(const AuthState.loading(), resetPasswordPath, AppMode.player),
        isNull);
    expect(
        redirectFor(
            const AuthState.loading(), forgotPasswordPath, AppMode.player),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), resetPasswordPath,
            AppMode.player),
        isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), forgotPasswordPath,
            AppMode.player),
        isNull);
    // And it remains reachable for a signed-in device (success clears session).
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true),
          resetPasswordPath, AppMode.coach),
      isNull,
    );
    expect(
      redirectFor(
          _authenticated(
              coach: false, onboarded: false, hasRecoveryEmail: false),
          forgotPasswordPath, AppMode.player),
      isNull,
    );
  });

  test('recovery email gates the authenticated area (ADR 007)', () {
    final AuthState gated =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: false);
    expect(redirectFor(gated, homePath, AppMode.player), recoveryEmailPath);
    expect(redirectFor(gated, onboardingPath, AppMode.player),
        recoveryEmailPath);
    expect(redirectFor(gated, recoveryEmailPath, AppMode.player), isNull);

    // Saving the email releases the gate to onboarding, then home.
    final AuthState set =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: true);
    expect(redirectFor(set, recoveryEmailPath, AppMode.player), onboardingPath);
    final AuthState done =
        _authenticated(coach: false, onboarded: true, hasRecoveryEmail: true);
    expect(redirectFor(done, recoveryEmailPath, AppMode.player), homePath);
  });

  test('recovery email stays ahead of the mode and deferred onboarding', () {
    // A coach in Coach mode without a recovery email still hits the ADR 007
    // gate first, even though Coach mode would otherwise ignore onboarding.
    final AuthState gated = _authenticated(
        coach: true, onboarded: false, hasRecoveryEmail: false);
    expect(redirectFor(gated, coachPath, AppMode.coach), recoveryEmailPath);
    expect(redirectFor(gated, splashPath, AppMode.coach), recoveryEmailPath);
    expect(redirectFor(gated, recoveryEmailPath, AppMode.coach), isNull);
    // Releasing the gate then lands the coach in Coach mode.
    final AuthState released = _authenticated(
        coach: true, onboarded: false, hasRecoveryEmail: true);
    expect(redirectFor(released, recoveryEmailPath, AppMode.coach), coachPath);
    expect(redirectFor(released, splashPath, AppMode.coach), coachPath);
  });

  test('onboarding gates the authenticated area for players', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), homePath,
          AppMode.player),
      onboardingPath,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), onboardingPath,
          AppMode.player),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), homePath,
          AppMode.player),
      isNull,
    );
  });

  test('a coach reaches Coach mode without completing player onboarding', () {
    final AuthState coach = _authenticated(coach: true, onboarded: false);
    // No forced trip to /onboarding: splash, recovery release and the player
    // shell all lead to the coach shell.
    expect(redirectFor(coach, splashPath, AppMode.coach), coachPath);
    expect(redirectFor(coach, homePath, AppMode.coach), coachPath);
    expect(redirectFor(coach, onboardingPath, AppMode.coach), coachPath);
    // The coach shell itself is the landing.
    expect(redirectFor(coach, coachPath, AppMode.coach), isNull);
    // Awaiting the intake in Player mode is allowed too (the setup screen).
    expect(redirectFor(coach, playerSetupPath, AppMode.player), isNull);
  });

  test('a coach in Player mode without onboarding gets the setup screen', () {
    final AuthState coach = _authenticated(coach: true, onboarded: false);
    expect(redirectFor(coach, splashPath, AppMode.player), playerSetupPath);
    expect(redirectFor(coach, homePath, AppMode.player), playerSetupPath);
    expect(redirectFor(coach, recoveryEmailPath, AppMode.player),
        playerSetupPath);
    // Once the intake completes, Player mode lands on the home shell.
    final AuthState onboarded = _authenticated(coach: true, onboarded: true);
    expect(redirectFor(onboarded, splashPath, AppMode.player), homePath);
    expect(redirectFor(onboarded, playerSetupPath, AppMode.player), homePath);
    expect(redirectFor(onboarded, onboardingPath, AppMode.player), homePath);
  });

  test('coach route requires the coach capability and Coach mode', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachPath,
          AppMode.player),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachPath,
          AppMode.coach),
      isNull,
    );
    // A coach sitting in Player mode leaves the coach shell for their landing.
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachPath,
          AppMode.player),
      homePath,
    );
  });

  test('coach invite route is open to authenticated players', () {
    // Any onboarded account may redeem an owner invite, coach or not.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachInvitePath,
          AppMode.player),
      isNull,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachInvitePath,
          AppMode.player),
      isNull,
    );
    // Onboarding still gates it for a plain player, like every surface.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), coachInvitePath,
          AppMode.player),
      onboardingPath,
    );
  });
}
