import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/models.dart';
import 'features/coach/coach_placeholder_screen.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/login_screen.dart';
import 'features/player/auth/recovery_email_screen.dart';
import 'features/player/auth/register_screen.dart';
import 'features/player/home/player_home_screen.dart';
import 'features/player/onboarding/onboarding_screen.dart';
import 'features/shared/splash_screen.dart';
import 'providers.dart';

const String loginPath = '/login';
const String registerPath = '/register';
const String recoveryEmailPath = '/recovery-email';
const String onboardingPath = '/onboarding';
const String homePath = '/home';
const String coachPath = '/coach';
const String splashPath = '/splash';

/// Pure routing decision, kept separate so capability gating is unit-testable.
///
/// Returns the location to redirect to, or null to stay.
String? redirectFor(AuthState auth, String location) {
  switch (auth.status) {
    case AuthStatus.loading:
      return location == splashPath ? null : splashPath;
    case AuthStatus.unauthenticated:
      final bool atAuthPage = location == loginPath || location == registerPath;
      return atAuthPage ? null : loginPath;
    case AuthStatus.authenticated:
      final AccountSession accountSession = auth.session!;
      final bool onboarded = accountSession.onboarded;
      final bool atAuthPage = location == loginPath || location == registerPath;

      // ADR 007: a recovery email is mandatory before dashboard or onboarding.
      if (!accountSession.hasRecoveryEmail) {
        return location == recoveryEmailPath ? null : recoveryEmailPath;
      }
      if (location == recoveryEmailPath) {
        return onboarded ? homePath : onboardingPath;
      }
      if (location == splashPath || atAuthPage) {
        return onboarded ? homePath : onboardingPath;
      }
      if (!onboarded && location != onboardingPath) {
        return onboardingPath;
      }
      if (onboarded && location == onboardingPath) {
        return homePath;
      }
      // Coach capability gates the coach surface (#23 hosts the module).
      if (location == coachPath && !accountSession.account.isCoach) {
        return homePath;
      }
      return null;
  }
}

final Provider<GoRouter> routerProvider = Provider<GoRouter>((ref) {
  final ValueNotifier<int> refresh = ValueNotifier<int>(0);
  ref.listen<AuthState>(authControllerProvider, (_, __) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: splashPath,
    refreshListenable: refresh,
    redirect: (BuildContext context, GoRouterState state) {
      return redirectFor(
          ref.read(authControllerProvider), state.matchedLocation);
    },
    routes: <RouteBase>[
      GoRoute(
        path: splashPath,
        builder: (BuildContext context, GoRouterState state) =>
            const SplashScreen(),
      ),
      GoRoute(
        path: loginPath,
        builder: (BuildContext context, GoRouterState state) =>
            const LoginScreen(),
      ),
      GoRoute(
        path: registerPath,
        builder: (BuildContext context, GoRouterState state) =>
            const RegisterScreen(),
      ),
      GoRoute(
        path: recoveryEmailPath,
        builder: (BuildContext context, GoRouterState state) =>
            const RecoveryEmailScreen(),
      ),
      GoRoute(
        path: onboardingPath,
        builder: (BuildContext context, GoRouterState state) =>
            const OnboardingScreen(),
      ),
      GoRoute(
        path: homePath,
        builder: (BuildContext context, GoRouterState state) =>
            const PlayerHomeScreen(),
      ),
      GoRoute(
        path: coachPath,
        builder: (BuildContext context, GoRouterState state) =>
            const CoachPlaceholderScreen(),
      ),
    ],
  );
});
