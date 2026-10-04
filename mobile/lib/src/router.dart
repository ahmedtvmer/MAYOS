import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/app_mode.dart';
import 'core/display_language/catalog.dart';
import 'core/display_language/controller.dart';
import 'core/models.dart';
import 'core/display_language/settings_copy.dart';
import 'core/ui/mayos_scaffold.dart';
import 'features/coach/coach_alerts_screen.dart';
import 'features/coach/coach_invite_screen.dart';
import 'features/coach/coach_player_history_screen.dart';
import 'features/coach/coach_profile_screen.dart';
import 'features/coach/coach_requests_screen.dart';
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
import 'features/player/progress/checkpoint_review_screen.dart';
import 'features/player/setup/player_setup_screen.dart';
import 'features/player/shell/player_shell.dart';
import 'features/player/workout/logger_top_bar.dart';
import 'features/player/workout/workout_drafts_screen.dart';
import 'features/player/workout/workout_logger_screen.dart';
import 'features/settings/personalization_screen.dart';
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
const String personalizationPath = '/personalization';
const String planPath = '/plan';
const String profilePath = '/profile';
const String coachPath = '/coach';
const String coachRosterRoutePath = 'roster';
const String coachAssignmentRoutePath = ':assignmentId';
const String coachAlertsRoutePath = 'alerts';
const String coachRequestsRoutePath = 'requests';
const String coachRequestRoutePath = ':requestId';
const String coachProfileRoutePath = 'profile';
const String coachAssignmentParameter = 'assignmentId';
const String coachRequestParameter = 'requestId';
const String coachRosterPath = '$coachPath/$coachRosterRoutePath';
const String coachAlertsPath = '$coachPath/$coachAlertsRoutePath';
const String coachRequestsPath = '$coachPath/$coachRequestsRoutePath';
const String coachProfilePath = '$coachPath/$coachProfileRoutePath';
const String coachInvitePath = '/coach-invite';
const String playerSetupPath = '/player-setup';
const String assignmentPath = '/assignment';
const String workoutsPath = '/workouts';
const String logWorkoutPath = '/log-workout';
const String exerciseDetailPath = '/exercise';
const String checkpointReviewPath = '/checkpoint-review';
const String chatPath = '/chat';
const String splashPath = '/splash';

/// Pure routing decision, kept separate so capability gating is unit-testable.
///
/// [mode] is this account's resolved Player/Coach mode (#119).
///
/// [location] is the requested location: its path drives every rule, while the
/// full string (query included) is what a cold deep link is carried on (#127).
///
/// [from] is the deep link carried through splash and sign-in gates
/// (`/splash?from=…`, `/login?from=…`, or `/recovery-email?from=…`): the
/// location the user originally asked for, remembered until all routing rules
/// have resolved it (#127/#172).
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
        final String? target = _carriedTarget(from);
        return target == null ? splashPath : splashHold(target);
      }
      // Carry the whole requested location (query included) on the splash
      // hold, so a cold deep link still lands where the user asked for (#127).
      return splashHold(location);
    case AuthStatus.unauthenticated:
      final bool atAuthPage = path == loginPath ||
          path == registerPath ||
          path == googleSignupPath ||
          _isPasswordRecoveryPage(path);
      if (atAuthPage) {
        return null;
      }
      // A cold deep link reaches here from splash with its validated target.
      // Never remember the current authenticated route on logout: that could
      // carry one account's page into the next account's sign-in.
      final String? target = path == splashPath ? _carriedTarget(from) : null;
      return target == null ? loginPath : _locationWithCarry(loginPath, target);
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
      final bool atAuthPage =
          path == loginPath || path == registerPath || path == googleSignupPath;
      final bool atRecoveryGate = path == recoveryEmailPath;
      final String? target = path == splashPath || atAuthPage || atRecoveryGate
          ? _carriedTarget(from)
          : null;

      // ADR 007: a verified recovery email is mandatory before dashboard or onboarding.
      // It stays first, ahead of the mode and onboarding rules.
      if (!accountSession.account.recoveryEmailVerified) {
        if (path == recoveryEmailPath) {
          return null;
        }
        return target == null
            ? recoveryEmailPath
            : _locationWithCarry(recoveryEmailPath, target);
      }

      // Hold on splash until this account's stored mode is known, so the app
      // opens in the stored mode instead of flashing the capability default.
      // The check is account-scoped, so it does not depend on whether the
      // router's or the mode controller's listener runs first (#119).
      if (!mode.isResolvedFor(accountSession.account.accountId)) {
        // On a splash hold the query is the only record of the carried deep
        // link, so staying must not rewrite the location to plain splash (#127).
        if (path == splashPath && target != null) {
          return null;
        }
        if (target != null) {
          return splashHold(target);
        }
        return splashPath;
      }

      /// Where this account opens: Coach mode owns the coach shell; Player
      /// mode lands on the home shell, or on the deferred player-onboarding
      /// surfaces when the intake is still missing.
      String landing() {
        if (coachMode) {
          return coachRosterPath;
        }
        if (onboarded) {
          return homePath;
        }
        return isCoach ? playerSetupPath : onboardingPath;
      }

      if (path == splashPath || path == recoveryEmailPath || atAuthPage) {
        if (target != null) {
          // Re-run the full rule set before releasing a target carried through
          // sign-in or the recovery-email gate. Unknown routes reach not-found.
          return redirectFor(auth, target, mode) ?? target;
        }
        return landing();
      }
      // Each mode owns its top-level shell: the coach routes need the coach
      // capability *and* Coach mode, and Coach mode never sits on the player
      // shell.
      if (_isCoachPath(path)) {
        return coachMode ? null : landing();
      }
      if (path == homePath && coachMode) {
        return coachRosterPath;
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
        return coachMode ? coachRosterPath : null;
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

bool _isCoachPath(String path) =>
    path == coachPath || path.startsWith('$coachPath/');

/// The route path without its query or fragment.
String _pathOf(String location) {
  final int queryStart = location.indexOf('?');
  final int fragmentStart = location.indexOf('#');
  int pathEnd = location.length;
  if (queryStart >= 0 && queryStart < pathEnd) {
    pathEnd = queryStart;
  }
  if (fragmentStart >= 0 && fragmentStart < pathEnd) {
    pathEnd = fragmentStart;
  }
  return location.substring(0, pathEnd);
}

/// Whether [path] can be carried through a startup or sign-in gate (#127/#172).
///
/// Splash, the auth screens and the recovery-email gate are never carried:
/// they are the hold itself or the gates the hold exists to pass.
bool _isCarryable(String path) =>
    path.startsWith('/') &&
    !path.startsWith('//') &&
    path != splashPath &&
    path != loginPath &&
    path != registerPath &&
    path != googleSignupPath &&
    path != recoveryEmailPath &&
    !_isPasswordRecoveryPage(path);

/// A validated carried deep link, or null when there is none (#127/#172).
String? _carriedTarget(String? from) =>
    from != null && _isCarryable(_pathOf(from)) ? from : null;

/// Adds a validated carry to a sign-in flow destination.
String withCarry(String destination, String? target) {
  final String? carry = _carriedTarget(target);
  return carry == null ? destination : _locationWithCarry(destination, carry);
}

/// Builds an auth-flow destination while retaining its validated `from` value.
String carryingLocation(BuildContext context, String destination) => withCarry(
      destination,
      GoRouterState.of(context).uri.queryParameters['from'],
    );

/// The splash location carrying [location] across the startup hold (#127):
/// `'/splash?from=<encoded location>'`, decoded by the router's redirect.
String splashHold(String location) => _locationWithCarry(splashPath, location);

String coachAssignmentLocation(String id) =>
    '$coachRosterPath/${Uri.encodeComponent(id)}';

String coachRequestLocation(String id) =>
    '$coachRequestsPath/${Uri.encodeComponent(id)}';

String _locationWithCarry(String route, String target) =>
    '$route?from=${Uri.encodeComponent(target)}';

Widget _localizedPlayerPage({
  required String Function(String languageCode) title,
  required Widget body,
}) =>
    Consumer(
      builder: (BuildContext context, WidgetRef ref, Widget? child) {
        final String languageCode = ref.watch(displayLanguageProvider);
        return MayosScaffold(
          title: title(languageCode),
          showBack: true,
          body: body,
        );
      },
    );

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
      return redirectFor(ref.read(authControllerProvider), location,
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
        path: personalizationPath,
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) =>
              SettingsCopy(languageCode).personalization,
          body: const PersonalizationScreen(),
        ),
      ),
      GoRoute(
        path: planPath,
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) => SettingsCopy(languageCode).plan,
          body: const PlanScreen(),
        ),
      ),
      GoRoute(
        path: profilePath,
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) => SettingsCopy(languageCode).profile,
          body: ProfileScreen(),
        ),
      ),
      GoRoute(
        path: chatPath,
        builder: (BuildContext context, GoRouterState state) =>
            const ChatScreen(),
      ),
      GoRoute(
        path: '$checkpointReviewPath/:checkpoint',
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) =>
              MayosCopy(languageCode).checkpointReview,
          body: CheckpointReviewScreen(
            key: ValueKey<String>(
              '${state.pathParameters['checkpoint']}:${state.uri.queryParameters['assignment_id'] ?? ''}',
            ),
            checkpoint:
                int.tryParse(state.pathParameters['checkpoint'] ?? '') ?? 0,
            assignmentId: state.uri.queryParameters['assignment_id'],
          ),
        ),
      ),
      GoRoute(
        path: coachInvitePath,
        builder: (BuildContext context, GoRouterState state) =>
            const CoachInviteScreen(),
      ),
      ShellRoute(
        builder: (BuildContext context, GoRouterState state, Widget child) =>
            CoachShell(
          child: child,
          assignmentId: state.pathParameters[coachAssignmentParameter],
        ),
        routes: <RouteBase>[
          GoRoute(
            path: coachPath,
            redirect: (BuildContext context, GoRouterState state) =>
                state.uri.path == coachPath ? coachRosterPath : null,
            routes: <RouteBase>[
              GoRoute(
                path: coachRosterRoutePath,
                builder: (BuildContext context, GoRouterState state) =>
                    const SizedBox.shrink(),
                routes: <RouteBase>[
                  GoRoute(
                    path: coachAssignmentRoutePath,
                    builder: (BuildContext context, GoRouterState state) =>
                        CoachPlayerHistoryScreen(
                      key: ValueKey<String>(
                        state.pathParameters[coachAssignmentParameter] ?? '',
                      ),
                      assignmentId:
                          state.pathParameters[coachAssignmentParameter] ?? '',
                      entry: state.extra is CoachRosterEntry
                          ? state.extra! as CoachRosterEntry
                          : null,
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: coachAlertsRoutePath,
                builder: (BuildContext context, GoRouterState state) =>
                    const CoachAlertsScreen(),
              ),
              GoRoute(
                path: coachRequestsRoutePath,
                builder: (BuildContext context, GoRouterState state) =>
                    const CoachRequestsScreen(),
                routes: <RouteBase>[
                  GoRoute(
                    path: coachRequestRoutePath,
                    builder: (BuildContext context, GoRouterState state) =>
                        CoachRequestsScreen(
                      selectedRequestId:
                          state.pathParameters[coachRequestParameter] ?? '',
                    ),
                  ),
                ],
              ),
              GoRoute(
                path: coachProfileRoutePath,
                builder: (BuildContext context, GoRouterState state) =>
                    const CoachProfileScreen(),
              ),
            ],
          ),
        ],
      ),
      GoRoute(
        path: playerSetupPath,
        builder: (BuildContext context, GoRouterState state) =>
            const PlayerSetupScreen(),
      ),
      GoRoute(
        path: assignmentPath,
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) => SettingsCopy(languageCode).coaching,
          body: const PlayerAssignmentScreen(),
        ),
      ),
      GoRoute(
        path: workoutsPath,
        builder: (BuildContext context, GoRouterState state) =>
            _localizedPlayerPage(
          title: (String languageCode) => SettingsCopy(languageCode).workouts,
          body: const WorkoutDraftsScreen(),
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
          showProgram: state.uri.queryParameters['library'] != '1',
          initialTab: state.uri.queryParameters['tab'] ?? 'overview',
        ),
      ),
    ],
  );
});
