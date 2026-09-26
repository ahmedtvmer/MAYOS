import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/models.dart';
import 'features/coach/coach_alerts_screen.dart';
import 'features/coach/coach_assignments_screen.dart';
import 'features/coach/coach_invite_screen.dart';
import 'features/coach/coach_profile_screen.dart';
import 'features/player/assignment/player_assignment_screen.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/forgot_password_screen.dart';
import 'features/player/auth/login_screen.dart';
import 'features/player/auth/recovery_email_screen.dart';
import 'features/player/auth/register_screen.dart';
import 'features/player/auth/reset_password_screen.dart';
import 'features/player/chat/chat_screen.dart';
import 'features/player/home/player_home_screen.dart';
import 'features/player/onboarding/onboarding_screen.dart';
import 'features/player/plan/plan_screen.dart';
import 'features/player/profile/profile_screen.dart';
import 'features/player/workout/workout_drafts_screen.dart';
import 'features/player/workout/workout_logger_screen.dart';
import 'features/shared/splash_screen.dart';
import 'providers.dart';

const String loginPath = '/login';
const String registerPath = '/register';
const String forgotPasswordPath = '/forgot-password';
const String resetPasswordPath = '/reset-password';
const String recoveryEmailPath = '/recovery-email';
const String onboardingPath = '/onboarding';
const String homePath = '/home';
const String planPath = '/plan';
const String profilePath = '/profile';
const String coachPath = '/coach';
const String coachInvitePath = '/coach-invite';
const String coachAssignmentsPath = '/coach/assignments';
const String coachAlertsPath = '/coach/alerts';
const String assignmentPath = '/assignment';
const String workoutsPath = '/workouts';
const String logWorkoutPath = '/log-workout';
const String chatPath = '/chat';
const String splashPath = '/splash';

/// Pure routing decision, kept separate so capability gating is unit-testable.
///
/// Returns the location to redirect to, or null to stay.
String? redirectFor(AuthState auth, String location) {
  switch (auth.status) {
    case AuthStatus.loading:
      // A password-recovery deep link must survive the startup resolution, so
      // it is not bounced to splash before the session is known.
      if (_isPasswordRecoveryPage(location)) {
        return null;
      }
      return location == splashPath ? null : splashPath;
    case AuthStatus.unauthenticated:
      final bool atAuthPage = location == loginPath ||
          location == registerPath ||
          _isPasswordRecoveryPage(location);
      return atAuthPage ? null : loginPath;
    case AuthStatus.authenticated:
      // Password recovery is public; it must work even for a signed-in device,
      // and its success clears the session and returns to login.
      if (_isPasswordRecoveryPage(location)) {
        return null;
      }
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
      // Coach capability gates the coach surfaces (#23 hosts the module).
      final bool atCoachSurface = location == coachPath ||
          location == coachAssignmentsPath ||
          location == coachAlertsPath;
      if (atCoachSurface && !accountSession.account.isCoach) {
        return homePath;
      }
      return null;
  }
}

/// The logged-out password-recovery surfaces reachable without a session.
bool _isPasswordRecoveryPage(String location) =>
    location == forgotPasswordPath || location == resetPasswordPath;

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
        path: forgotPasswordPath,
        builder: (BuildContext context, GoRouterState state) =>
            const ForgotPasswordScreen(),
      ),
      GoRoute(
        path: resetPasswordPath,
        builder: (BuildContext context, GoRouterState state) =>
            ResetPasswordScreen(
          token: state.uri.queryParameters['token'] ?? '',
        ),
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
        path: planPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Plan')),
          body: const PlanScreen(),
        ),
      ),
      GoRoute(
        path: profilePath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Profile')),
          body: const ProfileScreen(),
        ),
      ),
      GoRoute(
        path: chatPath,
        builder: (BuildContext context, GoRouterState state) =>
            const ChatScreen(),
      ),
      GoRoute(
        path: coachInvitePath,
        builder: (BuildContext context, GoRouterState state) =>
            const CoachInviteScreen(),
      ),
      GoRoute(
        path: coachPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Coach')),
          body: const CoachProfileScreen(),
        ),
      ),
      GoRoute(
        path: coachAssignmentsPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Assignments')),
          body: const CoachAssignmentsScreen(),
        ),
      ),
      GoRoute(
        path: coachAlertsPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Alert center')),
          body: const CoachAlertsScreen(),
        ),
      ),
      GoRoute(
        path: assignmentPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Coaching')),
          body: const PlayerAssignmentScreen(),
        ),
      ),
      GoRoute(
        path: workoutsPath,
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Workouts')),
          body: const WorkoutDraftsScreen(),
        ),
      ),
      GoRoute(
        path: '$logWorkoutPath/:day',
        builder: (BuildContext context, GoRouterState state) => Scaffold(
          appBar: AppBar(title: const Text('Log workout')),
          body: WorkoutLoggerScreen(
            dayOrder: int.tryParse(state.pathParameters['day'] ?? '') ?? 1,
          ),
        ),
      ),
    ],
  );
});
