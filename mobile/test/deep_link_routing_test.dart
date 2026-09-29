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

AppModeState _mode(
  AppMode mode, {
  bool ready = true,
  String? accountId = 'account-alice',
}) =>
    AppModeState(mode: mode, ready: ready, accountId: accountId);

/// The deep link carried on a splash-hold location, as the router decodes it.
String _carried(String held) => Uri.parse(held).queryParameters['from']!;

/// One cold deep link through the startup hold: hold on splash while the
/// session (and mode) resolve, then release onto [requested].
String? _hold(String requested) => redirectFor(
    const AuthState.loading(), requested, _mode(AppMode.player));

void main() {
  test('a cold deep link to an allowed page survives the startup hold', () {
    // The requested location is carried on the splash location, query intact.
    final String held = _hold(planPath)!;
    expect(held, startsWith('$splashPath?from='));
    expect(_carried(held), planPath);

    // Once the session and mode are resolved, splash releases onto it.
    final AuthState player = _authenticated(coach: false, onboarded: true);
    expect(redirectFor(player, splashPath, _mode(AppMode.player), from: planPath),
        planPath);

    // A deep link with its own query keeps that query.
    const String withQuery = '$exerciseDetailPath/12?tab=activity';
    final String heldQuery = _hold(withQuery)!;
    expect(_carried(heldQuery), withQuery);
    expect(
      redirectFor(player, splashPath, _mode(AppMode.player),
          from: _carried(heldQuery)),
      withQuery,
    );
  });

  test('the rules still win over a carried deep link', () {
    // A player may not open the coach shell (#119/#127).
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), splashPath,
          _mode(AppMode.player), from: coachPath),
      homePath,
    );
    // ADR 007: before the recovery email there is no authenticated surface.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true,
              hasRecoveryEmail: false),
          splashPath, _mode(AppMode.player), from: planPath),
      recoveryEmailPath,
    );
    // Onboarding still gates the deferred intake.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: false), splashPath,
          _mode(AppMode.player), from: planPath),
      onboardingPath,
    );
    // The mode hold keeps the carry instead of dropping it to plain splash.
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), splashPath,
          _mode(AppMode.player, ready: false), from: planPath),
      isNull,
    );
    expect(
      redirectFor(_authenticated(coach: false, onboarded: true), planPath,
          _mode(AppMode.player, ready: false)),
      splashPath,
    );
  });

  test('splash, login and recovery-email are never carried as a target', () {
    // The hold itself is never a remembered target.
    expect(_hold(splashPath), isNull);
    expect(_hold(loginPath), splashPath);
    expect(_hold(registerPath), splashPath);
    expect(_hold(recoveryEmailPath), splashPath);
    expect(splashHold(planPath),
        '$splashPath?from=${Uri.encodeComponent(planPath)}');

    // Nor do they survive when they arrive on the splash query.
    final AuthState player = _authenticated(coach: false, onboarded: true);
    expect(
      redirectFor(player, splashPath, _mode(AppMode.player), from: splashPath),
      homePath,
    );
    expect(
      redirectFor(player, splashPath, _mode(AppMode.player), from: loginPath),
      homePath,
    );
    expect(
      redirectFor(player, splashPath, _mode(AppMode.player),
          from: registerPath),
      homePath,
    );
    expect(
      redirectFor(player, splashPath, _mode(AppMode.player),
          from: recoveryEmailPath),
      homePath,
    );
  });

  test('an unauthenticated deep link goes to login without the carry', () {
    expect(
      redirectFor(const AuthState.unauthenticated(), splashPath,
          _mode(AppMode.player), from: planPath),
      loginPath,
    );
    expect(redirectFor(const AuthState.loading(), planPath,
        _mode(AppMode.player)), splashHold(planPath));
  });

  test('a coach\u2019s deep link resolves in their own mode', () {
    final AuthState coach = _authenticated(coach: true, onboarded: false);
    expect(
      redirectFor(coach, splashPath, _mode(AppMode.coach),
          from: coachPath),
      coachPath,
    );
    // In Player mode the intake wins over the requested page.
    expect(
      redirectFor(coach, splashPath, _mode(AppMode.player), from: planPath),
      playerSetupPath,
    );
  });
}
