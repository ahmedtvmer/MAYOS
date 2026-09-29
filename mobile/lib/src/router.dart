import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/app_mode.dart';
import 'core/models.dart';
import 'core/ui/mayos_scaffold.dart';
import 'features/coach/coach_invite_screen.dart';
import 'features/coach/coach_shell.dart';
import 'features/player/assignment/player_assignment_screen.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/forgot_password_screen.dart';
import 'features/player/auth/google_signup_screen.dart';
import 'features/player/auth/login_screen.dart';
import 'features/player/auth/recovery_email_screen.dart';
import 'features/player/auth/register_screen.dart';
import 'features/player/auth/reset_password_screen.dart';
import 'features/player/chat/chat_screen.dart';
import 'features/player/exercise/exercise_detail_screen.dart';
import 'features/player/onboarding/onboarding_screen.dart';
import 'features/player/plan/plan_screen.dart';
import 'features/player/profile/profile_screen.dart';
import 'features/player/setup/player_setup_screen.dart';
import 'features/player/shell/player_shell.dart';
import 'features/player/workout/logger_top_bar.dart';
import 'features/player/workout/workout_drafts_screen.dart';
import 'features/player/workout/workout_logger_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/shared/not_found_screen.dart';
import 'features/shared/splash_screen.dart';
import 'providers.dart';

const String loginPath = '/login';
const String registerPath = '/register';
const String googleSignupPath = '/google-signup';
const String forgotPasswordPath = '/forgot-password';
const String resetPasswordPath = '/reset-password';
const String recoveryEmailPath = '/recovery-email';
const String onboardingPath = '/onboarding';
const String homePath = '/home';
const String settingsPath = '/settings';
const String planPath = '/plan';
const String profilePath = '/profile';
const String coachPath = '/coach';
const String coachInvitePath = '/coach-invite';
const String playerSetupPath = '/player-setup';
const String assignmentPath = '/assignment';
const String workoutsPath = '/workouts';
const String logWorkoutPath = '/log-workout';
const String exerciseDetailPath = '/exercise';
const String chatPath = '/chat';
const String splashPath = '/splash';

/// Pure routing decision, kept separate so capability gating is unit-testable.
///
/// [mode] is this account's resolved Player/Coach mode (#119).
///
/// [location] is the requested location: its path drives every rule, while the
/// full string (query included) is what a cold deep link is carried on (#127).
///
/// [from] is the deep link carried on a splash hold (`/splash?from=…`): the
/// location the user originally asked for, remembered across the startup
/// resolution so it is not lost to `landing()` (#127).
///
/// Returns the location to redirect to, or null to stay.
String? redirectFor(AuthState auth, String location, AppModeState mode,
    {String? from}) {
  final String path = _pathOf(location);
  switch (auth.status) {
    case AuthStatus.loading:
      // A password-recovery deep link must survive the startup resolution, so
      // it is not bounced to splash before the session is known.
      if (_isPasswordRecoveryPage(path)) {
        return null;
      }
      // A plain splash start holds with no carry; splash, the auth screens and
      // the recovery-email gate are never a target to remember.
      if (path == splashPath) {
        return null;
      }
      if (!_isCarryable(path)) {
        return splashPath;
      }
      // Carry the whole requested location (query included) on the splash
      // hold, so a cold deep link still lands where the user asked for (#127).
      return splashHold(location);
    case AuthStatus.unauthenticated:
      final bool atAuthPage = path == loginPath ||
          path == registerPath ||
          path == googleSignupPath ||
          _isPasswordRecoveryPage(path);
      return atAuthPage ? null : loginPath;
    case AuthStatus.authenticated:
      // Password recovery is public; it must work even for a signed-in device,
      // and its success clears the session and returns to login.
      if (_isPasswordRecoveryPage(path)) {
        return null;
      }
      final AccountSession accountSession = auth.session!;
      final bool onboarded = accountSession.onboarded;
      final bool isCoach = accountSession.account.isCoach;
      // The capability caps the mode: a lost coach capability always resolves
      // to Player mode, whatever is stored.
      final bool coachMode = isCoach && mode.mode == AppMode.coach;
      final bool atAuthPage = path == loginPath ||
          path == registerPath ||
          path == googleSignupPath;

      // ADR 007: a recovery email is mandatory before dashboard or onboarding.
      // It stays first, ahead of the mode and onboarding rules (#119).
      if (!accountSession.hasRecoveryEmail) {
        return path == recoveryEmailPath ? null : recoveryEmailPath;
      }

      // Hold on splash until this account's stored mode is known, so the app
      // opens in the stored mode instead of flashing the capability default.
      // The check is account-scoped, so it does not depend on whether the
      // router's or the mode controller's listener runs first (#119).
      if (!mode.isResolvedFor(accountSession.account.accountId)) {
        // On a splash hold the query is the only record of the carried deep
        // link, so staying must not rewrite the location to plain splash (#127).
        if (path == splashPath && _carriedTarget(from) != null) {
          return null;
        }
        return splashPath;
      }

      /// Where this account opens: Coach mode owns the coach shell; Player
      /// mode lands on the home shell, or on the deferred player-onboarding
      /// surfaces when the intake is still missing.
      String landing() {
        if (coachMode) {
          return coachPath;
        }
        if (onboarded) {
          return homePath;
        }
        return isCoach ? playerSetupPath : onboardingPath;
      }

      if (path == recoveryEmailPath || atAuthPage) {
        return landing();
      }
      if (path == splashPath) {
        final String? target = _carriedTarget(from);
        if (target != null) {
          // Release the hold onto the requested location, but only after every
          // rule has run against it: the recovery gate, onboarding and the
          // mode/capability checks still win over a deep link (#127). The
          // rules read the path; the target keeps its own query.
          return redirectFor(auth, target, mode) ?? target;
        }
        return landing();
      }
      // Each mode owns its top-level shell: the coach routes need the coach
      // capability *and* Coach mode, and Coach mode never sits on the player
      // shell.
      if (path == coachPath) {
        return coachMode ? null : landing();
      }
      if (path == homePath && coachMode) {
        return coachPath;
      }
      // The deferred-intake screen is only for a coach in Player mode who has
      // not completed onboarding (#119).
      if (path == playerSetupPath) {
        if (isCoach && !onboarded && !coachMode) {
          return null;
        }
        return landing();
      }
      if (path == onboardingPath) {
        if (onboarded) {
          return landing();
        }
        // The intake belongs to Player mode; Coach mode never waits for it.
        return coachMode ? coachPath : null;
      }
      if (!onboarded) {
        // Deferred player onboarding (#119): a coach reaches Coach mode
        // without it; in Player mode they get the setup screen instead.
        if (coachMode) {
          return null;
        }
        return isCoach ? playerSetupPath : onboardingPath;
      }
      return null;
  }
}

/// The logged-out password-recovery surfaces reachable without a session.
bool _isPasswordRecoveryPage(String location) =>
    location == forgotPasswordPath || location == resetPasswordPath;

/// The location part of [location], without its query (#127).
String _pathOf(String location) {
  final int cut = location.indexOf('?');
  return cut == -1 ? location : location.substring(0, cut);
}

/// Whether [path] is a page a splash hold may remember as its target (#127).
///
/// Splash, the auth screens and the recovery-email gate are never carried:
/// they are the hold itself or the gates the hold exists to pass.
bool _isCarryable(String path) =>
    path.startsWith('/') &&
    path != splashPath &&
    path != loginPath &&
    path != registerPath &&
    path != googleSignupPath &&
    path != recoveryEmailPath;

/// The carried deep link on a splash hold, or null when there is none (#127).
String? _carriedTarget(String? from) =>
    from != null && _isCarryable(_pathOf(from)) ? from : null;

/// The splash location carrying [location] across the startup hold (#127):
/// `'/splash?from=<encoded location>'`, decoded by the router's redirect.
String splashHold(String location) =>
    '$splashPath?from=${Uri.encodeComponent(location)}';

final Provider<GoRouter> routerProvider = Provider<GoRouter>((ref) {
  final ValueNotifier<int> refresh = ValueNotifier<int>(0);
  // Either dependency can change the destination. Which listener fires first
  // does not matter: redirectFor holds on splash until the mode state belongs
  // to the signed-in account (#119).
  ref.listen<AppModeState>(
      appModeControllerProvider, (_, __) => refresh.value++);
  ref.listen<AuthState>(authControllerProvider, (_, __) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: splashPath,
    refreshListenable: refresh,
    redirect: (BuildContext context, GoRouterState state) {
      // The root-relative location (query included) carries a cold deep link
      // across the splash hold; the rules themselves only ever read its path
      // (#127). A platform-reported absolute URL (an app link) keeps only its
      // path and query, as `matchedLocation` did before.
      final Uri uri = state.uri;
      final String location =
          uri.hasQuery ? '${uri.path}?${uri.query}' : uri.path;
      return redirectFor(
          ref.read(authControllerProvider),
          location,
          ref.read(appModeControllerProvider),
          from: uri.queryParameters['from']);
    },
    // Unknown locations land on a branded page, never a blank screen (#127).
    errorBuilder: (BuildContext context, GoRouterState state) =>
        const NotFoundScreen(),
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
        path: googleSignupPath,
        builder: (BuildContext context, GoRouterState state) =>
            const GoogleSignupScreen(),
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
            const PlayerShell(),
      ),
      GoRoute(
        path: settingsPath,
        builder: (BuildContext context, GoRouterState state) =>
            const SettingsScreen(),
      ),
      GoRoute(
        path: planPath,
        builder: (BuildContext context, GoRouterState state) =>
            const MayosScaffold(
          title: 'Plan',
          showBack: true,
          body: PlanScreen(),
        ),
      ),
      GoRoute(
        path: profilePath,
        builder: (BuildContext context, GoRouterState state) =>
            const MayosScaffold(
          title: 'Profile',
          showBack: true,
          body: ProfileScreen(),
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
        builder: (BuildContext context, GoRouterState state) =>
            const CoachShell(),
      ),
      GoRoute(
        path: playerSetupPath,
        builder: (BuildContext context, GoRouterState state) =>
            const PlayerSetupScreen(),
      ),
      GoRoute(
        path: assignmentPath,
        builder: (BuildContext context, GoRouterState state) =>
            const MayosScaffold(
          title: 'Coaching',
          showBack: true,
          body: PlayerAssignmentScreen(),
        ),
      ),
      GoRoute(
        path: workoutsPath,
        builder: (BuildContext context, GoRouterState state) =>
            const MayosScaffold(
          title: 'Workouts',
          showBack: true,
          body: WorkoutDraftsScreen(),
        ),
      ),
      GoRoute(
        path: '$logWorkoutPath/:day',
        builder: (BuildContext context, GoRouterState state) => MayosScaffold(
          // The logger draws its own compact top bar — Back, live Workout
          // time and the discard menu (#159) — so the frame supplies no
          // header of its own.
          header: const LoggerTopBar(),
          // The logger's bottom elements (bar, keypad) take the system-nav
          // inset themselves, inside their own surface, so the bar's colour
          // runs under the inset with no seam (#160).
          safeBottom: false,
          body: WorkoutLoggerScreen(
            dayOrder: int.tryParse(state.pathParameters['day'] ?? '') ?? 1,
          ),
        ),
      ),
      GoRoute(
        path: '$exerciseDetailPath/:id',
        builder: (BuildContext context, GoRouterState state) =>
            ExerciseDetailScreen(
          exerciseId: state.pathParameters['id'] ?? '',
          dayOrder: int.tryParse(state.uri.queryParameters['day'] ?? ''),
          initialTab: state.uri.queryParameters['tab'] ?? 'overview',
        ),
      ),
    ],
  );
});
