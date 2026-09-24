import 'package:flutter_test/flutter_test.dart';
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
    expect(redirectFor(const AuthState.loading(), loginPath), splashPath);
    expect(redirectFor(const AuthState.loading(), splashPath), isNull);
    expect(redirectFor(const AuthState.unauthenticated(), homePath), loginPath);
    expect(redirectFor(const AuthState.unauthenticated(), loginPath), isNull);
    expect(
        redirectFor(const AuthState.unauthenticated(), registerPath), isNull);
  });

  test('recovery email gates the authenticated area (ADR 007)', () {
    final AuthState gated =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: false);
    expect(redirectFor(gated, homePath), recoveryEmailPath);
    expect(redirectFor(gated, onboardingPath), recoveryEmailPath);
    expect(redirectFor(gated, recoveryEmailPath), isNull);

    // Saving the email releases the gate to onboarding, then home.
    final AuthState set =
        _authenticated(coach: false, onboarded: false, hasRecoveryEmail: true);
    expect(redirectFor(set, recoveryEmailPath), onboardingPath);
    final AuthState done =
        _authenticated(coach: false, onboarded: true, hasRecoveryEmail: true);
    expect(redirectFor(done, recoveryEmailPath), homePath);
  });

  test('onboarding gates the authenticated area', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), homePath),
      onboardingPath,
    );
    expect(
      redirectFor(
          _authenticated(coach: false, onboarded: true), onboardingPath),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), homePath),
      isNull,
    );
  });

  test('coach route requires the coach capability', () {
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachPath),
      homePath,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachPath),
      isNull,
    );
  });

  test('coach invite route is open to authenticated players', () {
    // Any onboarded account may redeem an owner invite, coach or not.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), coachInvitePath),
      isNull,
    );
    expect(
      redirectFor(_authenticated(coach: true, onboarded: true), coachInvitePath),
      isNull,
    );
    // Onboarding still gates it, like every authenticated surface.
    expect(
      redirectFor(
          _authenticated(coach: false, onboarded: false), coachInvitePath),
      onboardingPath,
    );
  });
}
