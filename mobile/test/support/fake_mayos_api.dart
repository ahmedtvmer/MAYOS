import 'fake_api_adapter.dart';

/// In-memory stand-in for the FastAPI service, mimicking the real route
/// contracts: paths, the legacy `trainee_id` wire field, capability JSON, and
/// the fail-closed 401 behavior of the registry-backed auth dependency.
class FakeMayosApi {
  FakeMayosApi() {
    adapter = FakeApiAdapter(_handle);
  }

  late final FakeApiAdapter adapter;

  final Map<String, String> passwords = <String, String>{};
  String? issuedToken;
  String? currentUsername;
  bool tokenValid = true;
  bool coach = false;
  bool profileExists = false;
  String? recoveryEmail;
  String coachDisplayName = '';
  String coachBio = '';
  String coachSpecialization = '';
  int coachCapacity = 10;
  String? validCoachInviteToken;
  bool coachProfileLoadFails = false;

  /// When true, `GET /auth/me` fails with a transient 500 (token still valid).
  bool meFails = false;
  int _answeredSteps = 0;
  List<String> _assistantMessages = <String>[];
  bool _onboardingComplete = false;

  FakeResponse _handle(FakeRequest request) {
    final String path = request.path;
    switch (path) {
      case '/auth/register':
        return _register(request);
      case '/auth/login':
        return _login(request);
      case '/auth/logout':
        return _authorized(request)
            ? const FakeResponse(204)
            : const FakeResponse(
                401, <String, dynamic>{'detail': 'Token has been revoked.'});
      case '/auth/me':
        return _me(request);
      case '/auth/email':
        return _recoveryEmail(request);
      case '/coach/invite/redeem':
        return _redeemCoachInvite(request);
      case '/coach/profile':
        return _coachProfile(request);
      case '/profile':
        return _profile(request);
      case '/onboarding/start':
        return _startOnboarding(request);
      case '/onboarding/step':
        return _onboardingStep(request);
      case '/onboarding/complete':
        return _completeOnboarding(request);
      case '/programs/active':
        return _activeProgram(request);
      case '/dashboard/volume':
        return _volume(request);
      case '/dashboard/personal-records':
        return _personalRecords(request);
      default:
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Not found.'});
    }
  }

  FakeResponse _register(FakeRequest request) {
    final String? username = request.body['trainee_id'] as String?;
    final String? password = request.body['password'] as String?;
    if (username == null || password == null || password.length < 8) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Password is too short.'});
    }
    passwords[username] = password;
    _beginSession(username, fresh: true);
    return FakeResponse(201, _tokenBody(username));
  }

  FakeResponse _login(FakeRequest request) {
    final String? username = request.body['trainee_id'] as String?;
    final String? password = request.body['password'] as String?;
    if (username == null || passwords[username] != password) {
      return const FakeResponse(
        401,
        <String, dynamic>{'detail': 'Invalid username or password.'},
      );
    }
    _beginSession(username);
    return FakeResponse(200, _tokenBody(username));
  }

  FakeResponse _me(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (meFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    return FakeResponse(200, <String, dynamic>{
      'account_id': 'account-$currentUsername',
      'trainee_id': currentUsername,
      'capabilities': <String, dynamic>{'player': true, 'coach': coach},
    });
  }

  FakeResponse _recoveryEmail(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.method == 'GET') {
      return FakeResponse(200, <String, dynamic>{'email': recoveryEmail});
    }
    final String? raw = request.body['email'] as String?;
    final String? normalized = raw?.trim().toLowerCase();
    if (normalized == null ||
        normalized.length < 3 ||
        !normalized.contains('@') ||
        !normalized.contains('.')) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Enter a valid email address.'});
    }
    recoveryEmail = normalized;
    return FakeResponse(200, <String, dynamic>{'email': normalized});
  }

  FakeResponse _redeemCoachInvite(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String? token = request.body['token'] as String?;
    if (validCoachInviteToken == null || token != validCoachInviteToken) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired invite code.'});
    }
    coach = true;
    coachDisplayName = currentUsername ?? '';
    coachBio = '';
    coachSpecialization = '';
    coachCapacity = 10;
    validCoachInviteToken = null;
    return FakeResponse(200, <String, dynamic>{
      'account_id': 'account-$currentUsername',
      'trainee_id': currentUsername,
      'capabilities': <String, dynamic>{'player': true, 'coach': true},
    });
  }

  Map<String, dynamic> _coachProfileBody() => <String, dynamic>{
        'account_id': 'account-$currentUsername',
        'display_name': coachDisplayName,
        'bio': coachBio,
        'specialization': coachSpecialization,
        'capacity': coachCapacity,
      };

  FakeResponse _coachProfile(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    if (request.method == 'GET') {
      if (coachProfileLoadFails) {
        return const FakeResponse(
            500, <String, dynamic>{'detail': 'The service is unavailable.'});
      }
      return FakeResponse(200, _coachProfileBody());
    }
    coachDisplayName = (request.body['display_name'] as String?)?.trim() ?? '';
    coachBio = request.body['bio'] as String? ?? '';
    coachSpecialization = request.body['specialization'] as String? ?? '';
    coachCapacity = (request.body['capacity'] as num?)?.toInt() ?? 1;
    return FakeResponse(200, _coachProfileBody());
  }

  FakeResponse _profile(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!profileExists) {
      return const FakeResponse(
        404,
        <String, dynamic>{'detail': 'No profile yet; complete onboarding.'},
      );
    }
    return const FakeResponse(
        200, <String, dynamic>{'current_goal': 'Build muscle'});
  }

  FakeResponse _startOnboarding(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    // Load-or-start: a second call (app restart) resumes saved progress and
    // returns the full assistant conversation, matching the service contract.
    if (_assistantMessages.isEmpty) {
      _assistantMessages = <String>['Hi! What is your main goal?'];
    }
    return FakeResponse(200, <String, dynamic>{
      'intake_step': _answeredSteps + 1,
      'is_complete': _onboardingComplete,
      'messages': List<String>.from(_assistantMessages),
    });
  }

  FakeResponse _onboardingStep(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    _answeredSteps++;
    _onboardingComplete = _answeredSteps >= 2;
    final String reply = _onboardingComplete
        ? 'Great, I have what I need.'
        : 'Got it. How many days per week?';
    _assistantMessages.add(reply);
    return FakeResponse(200, <String, dynamic>{
      'intake_step': _answeredSteps + 1,
      'is_complete': _onboardingComplete,
      'messages': <String>[reply],
    });
  }

  FakeResponse _completeOnboarding(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    profileExists = true;
    _onboardingComplete = true;
    return const FakeResponse(200, <String, dynamic>{
      'program_name': 'Upper/Lower 4x',
      'weekly_frequency': 4,
    });
  }

  FakeResponse _activeProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return const FakeResponse(200, <String, dynamic>{
      'program_name': 'Upper/Lower 4x',
      'split_type': 'Upper/Lower',
      'weekly_frequency': 4,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': 'Upper 1',
          'day_order': 1,
          'warmup_exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_id': 'band_pull_apart',
              'exercise_name': 'Band Pull-Apart',
              'sets': 2,
              'reps': 15,
              'rest_seconds': 45,
              'notes': 'Squeeze at the top.',
            },
          ],
          'exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'exercise_id': 'bench_press',
              'exercise_name': 'Bench Press',
              'warmup_sets': 2,
              'target_sets': 3,
              'target_reps_min': 5,
              'target_reps_max': 8,
              'target_rpe': 8.5,
              'rest_seconds': 180,
              'notes': 'Pause on the chest.',
            },
            <String, dynamic>{
              'exercise_id': 'overhead_press',
              'exercise_name': 'Overhead Press',
              'warmup_sets': 1,
              'target_sets': 3,
              'target_reps_min': 6,
              'target_reps_max': 10,
              'target_rpe': 8.0,
              'rest_seconds': 150,
              'notes': null,
            },
            <String, dynamic>{
              'exercise_id': 'barbell_row',
              'exercise_name': 'Barbell Row',
              'warmup_sets': 1,
              'target_sets': 3,
              'target_reps_min': 6,
              'target_reps_max': 10,
              'target_rpe': 8.0,
              'rest_seconds': 150,
              'notes': null,
            },
            <String, dynamic>{
              'exercise_id': 'lat_pulldown',
              'exercise_name': 'Lat Pulldown',
              'warmup_sets': 0,
              'target_sets': 3,
              'target_reps_min': 8,
              'target_reps_max': 12,
              'target_rpe': 8.0,
              'rest_seconds': 120,
              'notes': null,
            },
          ],
          'cardio': '10 min incline walk',
        },
      ],
    });
  }

  FakeResponse _volume(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    // Weighted working-set counts (primary 1.0, secondary +0.5), not kilograms.
    return const FakeResponse(
        200, <String, dynamic>{'Chest': 12.5, 'Back': 9.0});
  }

  FakeResponse _personalRecords(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return const FakeResponse(200, <Map<String, dynamic>>[
      <String, dynamic>{
        'exercise_id': 'bench_press',
        'name': 'Bench Press',
        'record_type': 'e1RM',
        'reps': 5,
        'value': 120.0,
        'prev_value': 117.5,
        'achieved_at': '2026-09-20T10:00:00Z',
        'session_id': 3,
      },
    ]);
  }

  void _beginSession(String username, {bool fresh = false}) {
    currentUsername = username;
    issuedToken = 'token-$username';
    tokenValid = true;
    if (fresh) {
      coach = false;
      profileExists = false;
      recoveryEmail = null;
      coachDisplayName = '';
      coachBio = '';
      coachSpecialization = '';
      coachCapacity = 10;
      validCoachInviteToken = null;
      coachProfileLoadFails = false;
      _answeredSteps = 0;
      _assistantMessages = <String>[];
      _onboardingComplete = false;
    }
  }

  bool _authorized(FakeRequest request) {
    final dynamic header = request.headers['Authorization'];
    return tokenValid && issuedToken != null && header == 'Bearer $issuedToken';
  }

  Map<String, dynamic> _tokenBody(String username) => <String, dynamic>{
        'access_token': issuedToken,
        'token_type': 'bearer',
        'trainee_id': username,
      };
}
