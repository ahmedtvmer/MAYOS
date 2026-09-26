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
  String lifterPlan = 'free';
  String coachPlan = 'free';
  bool profileExists = false;
  String? recoveryEmail;
  // Player profile fields written through `PUT /profile` (#27).
  String repPreference = 'balanced';
  int weeklyFrequency = 4;
  // Forces a coach-controlled profile-update response even with no publication.
  bool profileBlocked = false;
  String coachDisplayName = '';
  String coachBio = '';
  String coachSpecialization = '';
  int coachCapacity = 10;
  String? validCoachInviteToken;
  bool coachProfileLoadFails = false;

  // Assignment lifecycle (#24).
  String? pendingAssignmentToken;
  String pendingCoachDisplayName = 'Coach Alice';
  String pendingCoachSpecialization = 'Powerlifting';
  String? issuedAssignmentToken;
  String? activeAssignmentId;
  String? activeCoachDisplayName;
  String? activeCoachSpecialization;
  bool myAssignmentFails = false;
  final List<Map<String, dynamic>> assignmentNotices = <Map<String, dynamic>>[];
  final List<Map<String, dynamic>> assignments = <Map<String, dynamic>>[];

  // Coach program publication and player notices (#26).
  int _publishedVersion = 0;
  int? programVersion;
  String? programPublishedByCoachAccountId;
  bool coachControlsProgram = false;
  final List<Map<String, dynamic>> playerNotices = <Map<String, dynamic>>[];

  // Player program requests and coach resolution (#28).
  final List<Map<String, dynamic>> programRequests = <Map<String, dynamic>>[];
  bool staleProgramRequest = false;
  int _programRequestSeq = 0;

  // Coach drill-down (#25). Denied mirrors a revoked/foreign assignment.
  bool coachHistoryDenied = false;
  Map<String, dynamic> coachPlayerSummary = _defaultCoachSummary();
  List<Map<String, dynamic>> coachPlayerRecords =
      _defaultCoachRecords();
  List<Map<String, dynamic>> coachPlayerExercises =
      _defaultCoachExercises();
  Map<String, Map<String, dynamic>> coachPlayerHistories =
      _defaultCoachHistories();

  /// When true, `GET /auth/me` fails with a transient 500 (token still valid).
  bool meFails = false;
  int _answeredSteps = 0;
  List<String> _assistantMessages = <String>[];
  bool _onboardingComplete = false;
  // When true, completion returns null program fields (coach-controlled edge).
  bool nullOnboardingProgram = false;

  FakeResponse _handle(FakeRequest request) {
    final String path = request.path;
    if (path.startsWith('/coach/assignments/') &&
        path.contains('/program-requests')) {
      return _coachProgramRequests(request);
    }
    if (path.startsWith('/assignments/me/program-requests')) {
      return _playerProgramRequests(request);
    }
    if (path.startsWith('/coach/assignments/') && path.endsWith('/revoke')) {
      return _revokeAssignment(request);
    }
    if (path.startsWith('/coach/assignments/') && path.endsWith('/program')) {
      return _publishProgram(request);
    }
    if (path.startsWith('/coach/assignments/') && path.contains('/player/')) {
      return _coachPlayerHistory(request);
    }
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
      case '/coach/assignments':
        return _coachAssignments(request);
      case '/coach/assignments/invites':
        return _issueAssignmentInvite(request);
      case '/coach/assignments/notices':
        return _coachNotices(request);
      case '/coach/assignments/notices/read':
        return _markNoticesRead(request);
      case '/coach/capability/disable':
        return _disableCoach(request);
      case '/assignments/invites/preview':
        return _previewAssignment(request);
      case '/assignments/invites/redeem':
        return _redeemAssignment(request);
      case '/assignments/me':
        return _myAssignment(request);
      case '/assignments/me/end':
        return _endMyAssignment(request);
      case '/assignments/notices':
        return _playerNotices(request);
      case '/assignments/notices/read':
        return _markPlayerNoticesRead(request);
      case '/programs/generate':
        return _playerGenerateProgram(request);
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
      'plans': _plansBody(),
    });
  }

  Map<String, dynamic> _plansBody() => <String, dynamic>{
        'lifter': <String, dynamic>{'plan': lifterPlan, 'status': 'active'},
        if (coach) 'coach': <String, dynamic>{'plan': coachPlan, 'status': 'active'},
      };

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
      'plans': _plansBody(),
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

  Map<String, dynamic> _identity(String name, String specialization) =>
      <String, dynamic>{
        'display_name': name,
        'bio': 'Strength coach.',
        'specialization': specialization,
      };

  Map<String, dynamic> _assignmentBody() => <String, dynamic>{
        'assignment_id': activeAssignmentId,
        'coach': _identity(
          activeCoachDisplayName ?? 'Coach Alice',
          activeCoachSpecialization ?? 'Powerlifting',
        ),
        'started_at': '2026-09-24T10:00:00Z',
        'status': 'active',
      };

  FakeResponse _issueAssignmentInvite(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    if (assignments.length >= coachCapacity) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'Your roster is full. End an assignment before issuing another invite.'
      });
    }
    issuedAssignmentToken = 'assignment-invite-token-123456';
    return FakeResponse(200, <String, dynamic>{
      'token': issuedAssignmentToken,
      'expires_at': '2026-09-27T10:00:00Z',
      'active_assignments': assignments.length,
      'capacity': coachCapacity,
    });
  }

  FakeResponse _coachAssignments(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    return FakeResponse(
        200, <String, dynamic>{'assignments': List<Map<String, dynamic>>.from(assignments)});
  }

  FakeResponse _coachNotices(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    return FakeResponse(
        200, <String, dynamic>{'notices': List<Map<String, dynamic>>.from(assignmentNotices)});
  }

  FakeResponse _markNoticesRead(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    int marked = 0;
    for (final Map<String, dynamic> notice in assignmentNotices) {
      if (notice['read_at'] == null) {
        notice['read_at'] = '2026-09-24T11:00:00Z';
        marked++;
      }
    }
    return FakeResponse(200, <String, dynamic>{'marked_read': marked});
  }

  FakeResponse _revokeAssignment(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final String id = request.path
        .replaceFirst('/coach/assignments/', '')
        .replaceFirst('/revoke', '');
    assignments.removeWhere((Map<String, dynamic> entry) =>
        entry['assignment_id'] == id);
    return FakeResponse(200, <String, dynamic>{
      'assignment_id': id,
      'status': 'ended',
      'ended_at': '2026-09-24T11:00:00Z',
    });
  }

  FakeResponse _coachPlayerHistory(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    if (coachHistoryDenied) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    final String path = request.path;
    if (path.endsWith('/player/summary')) {
      return FakeResponse(200, coachPlayerSummary);
    }
    if (path.endsWith('/player/personal-records')) {
      return FakeResponse(200, List<Map<String, dynamic>>.from(coachPlayerRecords));
    }
    if (path.endsWith('/player/exercises')) {
      return FakeResponse(
          200, <String, dynamic>{'exercises': coachPlayerExercises});
    }
    if (path.contains('/player/exercises/') && path.endsWith('/history')) {
      final String exerciseId =
          path.split('/player/exercises/')[1].split('/history')[0];
      return FakeResponse(
          200,
          coachPlayerHistories[exerciseId] ??
              <String, dynamic>{'history': <dynamic>[], 'caption': null, 'records': <dynamic>[]});
    }
    return const FakeResponse(
        404, <String, dynamic>{'detail': 'Not found.'});
  }

  static Map<String, dynamic> _defaultCoachSummary() => <String, dynamic>{
        'player_username': 'bob',
        'started_at': '2026-09-24T10:00:00Z',
        'status': 'active',
        'volume': <String, dynamic>{'Chest': 12.5, 'Back': 9.0},
        'latest_session': <String, dynamic>{
          'session_date': '2026-09-25',
          'split_name': 'Upper 1',
          'readiness_score': 4,
          'sets_count': 12,
          'total_volume_kg': 4200.0,
          'exercises': <Map<String, dynamic>>[
            <String, dynamic>{
              'name': 'Bench Press',
              'sets': 3,
              'reps': 15,
              'volume_kg': 2000.0,
            },
          ],
        },
        'recent_sessions': <Map<String, dynamic>>[
          <String, dynamic>{
            'session_id': 's2',
            'session_date': '2026-09-25',
            'split_name': 'Upper 1',
            'readiness_score': 4,
            'sets_count': 12,
            'total_volume_kg': 4200.0,
          },
          <String, dynamic>{
            'session_id': 's1',
            'session_date': '2026-09-23',
            'split_name': 'Lower 1',
            'readiness_score': 3,
            'sets_count': 10,
            'total_volume_kg': 3900.0,
          },
        ],
      };

  static List<Map<String, dynamic>> _defaultCoachRecords() =>
      <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': 'bench_press',
          'name': 'Bench Press',
          'record_type': 'e1RM',
          'reps': 5,
          'value': 120.0,
          'achieved_at': '2026-09-20T10:00:00Z',
        },
      ];

  static List<Map<String, dynamic>> _defaultCoachExercises() =>
      <Map<String, dynamic>>[
        <String, dynamic>{'id': 'bench_press', 'name': 'Bench Press'},
      ];

  static Map<String, Map<String, dynamic>> _defaultCoachHistories() =>
      <String, Map<String, dynamic>>{
        'bench_press': <String, dynamic>{
          'history': <Map<String, dynamic>>[
            <String, dynamic>{
              'date': '2026-09-20',
              'weight_kg': 100.0,
              'reps': 5,
              'rpe': 8.0,
              'e1rm': 120.0,
            },
          ],
          'caption': 'Latest Recorded: **100.0 kg × 5 reps @ RPE 8.0**',
          'records': <Map<String, dynamic>>[
            <String, dynamic>{
              'record_type': 'max_weight',
              'reps': 5,
              'value': 100.0,
              'achieved_at': '2026-09-20T10:00:00Z',
            },
          ],
        },
      };

  FakeResponse _disableCoach(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final int ended = assignments.length;
    assignments.clear();
    coach = false;
    return FakeResponse(
        200, <String, dynamic>{'coach': false, 'ended_assignments': ended});
  }

  Map<String, dynamic> _accessBody() => <String, dynamic>{
        'scope': 'current_and_historical_training_data',
        'includes_current_history': true,
        'includes_historical_history': true,
        'active_while_assigned': true,
        'description':
            'While this assignment is active, your coach can view all of your training data.',
      };

  FakeResponse _previewAssignment(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String? token = request.body['token'] as String?;
    if (pendingAssignmentToken == null || token != pendingAssignmentToken) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired invite code.'});
    }
    return FakeResponse(200, <String, dynamic>{
      'coach': _identity(pendingCoachDisplayName, pendingCoachSpecialization),
      'access': _accessBody(),
      'expires_at': '2026-09-27T10:00:00Z',
    });
  }

  FakeResponse _redeemAssignment(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String? token = request.body['token'] as String?;
    if (request.body['consent'] != true) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'You must explicitly accept the assignment to redeem this invite.'
      });
    }
    if (pendingAssignmentToken == null || token != pendingAssignmentToken) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired invite code.'});
    }
    activeAssignmentId = 'assignment-1';
    activeCoachDisplayName = pendingCoachDisplayName;
    activeCoachSpecialization = pendingCoachSpecialization;
    pendingAssignmentToken = null;
    return FakeResponse(200, <String, dynamic>{
      'assignment': _assignmentBody(),
      'notices_created': 1,
      'email_sent': true,
    });
  }

  FakeResponse _myAssignment(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (myAssignmentFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    if (activeAssignmentId == null) {
      return const FakeResponse(200);
    }
    return FakeResponse(200, _assignmentBody());
  }

  FakeResponse _endMyAssignment(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (activeAssignmentId == null) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'You have no active coaching assignment.'
      });
    }
    final String endedId = activeAssignmentId!;
    activeAssignmentId = null;
    return FakeResponse(200, <String, dynamic>{
      'assignment_id': endedId,
      'status': 'ended',
      'ended_at': '2026-09-24T11:00:00Z',
    });
  }

  FakeResponse _publishProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final String id = request.path
        .replaceFirst('/coach/assignments/', '')
        .replaceFirst('/program', '');
    final bool owned = assignments
        .any((Map<String, dynamic> entry) => entry['assignment_id'] == id);
    if (!owned) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    _publishedVersion++;
    programVersion = _publishedVersion;
    programPublishedByCoachAccountId = 'account-$currentUsername';
    coachControlsProgram = true;
    playerNotices.insert(0, <String, dynamic>{
      'notice_id': 'notice-$_publishedVersion',
      'assignment_id': id,
      'kind': 'program_published',
      'message': 'Your coach published program version $programVersion.',
      'created_at': '2026-09-24T11:00:00Z',
      'read_at': null,
    });
    return FakeResponse(200, _activeProgramBody());
  }

  FakeResponse _playerProgramRequests(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String path = request.path;
    if (path.endsWith('/cancel')) {
      final String id = path.split('/program-requests/')[1].split('/cancel')[0];
      final int index = programRequests
          .indexWhere((Map<String, dynamic> r) => r['request_id'] == id);
      if (index < 0) {
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Request not found.'});
      }
      if (programRequests[index]['status'] != 'pending') {
        return const FakeResponse(400,
            <String, dynamic>{'detail': 'This request is no longer pending.'});
      }
      programRequests[index]['status'] = 'cancelled';
      programRequests[index]['resolved_at'] = '2026-09-26T12:00:00Z';
      programRequests[index]['resolved_by'] = 'player';
      return FakeResponse(200, programRequests[index]);
    }
    if (request.method == 'POST') {
      return _createPlayerProgramRequest(request);
    }
    return FakeResponse(200, <String, dynamic>{
      'requests': List<Map<String, dynamic>>.from(programRequests),
    });
  }

  FakeResponse _createPlayerProgramRequest(FakeRequest request) {
    final String? kind = request.body['kind'] as String?;
    final String reason = (request.body['reason'] as String?)?.trim() ?? '';
    if (reason.isEmpty) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'A reason is required.'});
    }
    final Map<String, dynamic> row = <String, dynamic>{
      'request_id': 'request-${++_programRequestSeq}',
      'assignment_id': activeAssignmentId ?? 'assignment-1',
      'kind': kind,
      'program_version': programVersion ?? 0,
      'day_name': null,
      'exercise_id': null,
      'replacement_exercise_id': null,
      'desired_weekly_frequency': null,
      'desired_split_preference': null,
      'reason': reason,
      'status': 'pending',
      'response': null,
      'created_at': '2026-09-26T12:00:00Z',
      'resolved_at': null,
      'resolved_by': null,
    };
    if (kind == 'exercise_substitution') {
      final String day = (request.body['day_name'] as String?)?.trim() ?? '';
      final String? exercise = request.body['exercise_id'] as String?;
      final String? replacement =
          request.body['replacement_exercise_id'] as String?;
      if (day.isEmpty || exercise == null || replacement == null) {
        return const FakeResponse(400, <String, dynamic>{
          'detail': 'Pick the day, the exercise, and its replacement.'
        });
      }
      if (replacement == exercise) {
        return const FakeResponse(400, <String, dynamic>{
          'detail': 'Choose a different replacement exercise.'
        });
      }
      row['day_name'] = day;
      row['exercise_id'] = exercise;
      row['replacement_exercise_id'] = replacement;
    } else if (kind == 'split_change') {
      final int? frequency =
          (request.body['desired_weekly_frequency'] as num?)?.toInt();
      if (frequency == null || frequency < 1 || frequency > 5) {
        return const FakeResponse(400, <String, dynamic>{
          'detail': 'Weekly frequency must be between 1 and 5.'
        });
      }
      row['desired_weekly_frequency'] = frequency;
      row['desired_split_preference'] =
          request.body['desired_split_preference'] as String?;
    } else {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'Choose an exercise substitution or a split change.'
      });
    }
    programRequests.insert(0, row);
    return FakeResponse(200, row);
  }

  FakeResponse _coachProgramRequests(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final List<String> parts = request.path
        .replaceFirst('/coach/assignments/', '')
        .split('/');
    final String assignmentId = parts.isNotEmpty ? parts[0] : '';
    final bool owned = assignments.any(
        (Map<String, dynamic> entry) => entry['assignment_id'] == assignmentId);
    if (!owned) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    if (request.path.endsWith('/apply') || request.path.endsWith('/decline')) {
      final String id = parts.length > 2 ? parts[2] : '';
      final int index = programRequests
          .indexWhere((Map<String, dynamic> r) => r['request_id'] == id);
      if (index < 0) {
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Request not found.'});
      }
      if (programRequests[index]['status'] != 'pending') {
        return const FakeResponse(400,
            <String, dynamic>{'detail': 'This request is no longer pending.'});
      }
      if (request.path.endsWith('/apply')) {
        if (staleProgramRequest) {
          return const FakeResponse(400, <String, dynamic>{
            'detail':
                'The program changed since this request was created. Ask the player to update it.'
          });
        }
        programRequests[index]['status'] = 'applied';
        programRequests[index]['resolved_at'] = '2026-09-26T12:30:00Z';
        programRequests[index]['resolved_by'] = 'account-$currentUsername';
        programVersion = (programVersion ?? 0) + 1;
        _publishedVersion = programVersion!;
        programPublishedByCoachAccountId = 'account-$currentUsername';
        coachControlsProgram = true;
        return FakeResponse(200, programRequests[index]);
      }
      final String response =
          (request.body['response'] as String?)?.trim() ?? '';
      if (response.isEmpty) {
        return const FakeResponse(
            400, <String, dynamic>{'detail': 'A response is required.'});
      }
      programRequests[index]['status'] = 'declined';
      programRequests[index]['response'] = response;
      programRequests[index]['resolved_at'] = '2026-09-26T12:30:00Z';
      programRequests[index]['resolved_by'] = 'account-$currentUsername';
      return FakeResponse(200, programRequests[index]);
    }
    return FakeResponse(200, <String, dynamic>{
      'requests': List<Map<String, dynamic>>.from(programRequests),
    });
  }

  FakeResponse _playerNotices(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return FakeResponse(200, <String, dynamic>{
      'notices': List<Map<String, dynamic>>.from(playerNotices),
    });
  }

  FakeResponse _markPlayerNoticesRead(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    int marked = 0;
    for (final Map<String, dynamic> notice in playerNotices) {
      if (notice['read_at'] == null) {
        notice['read_at'] = '2026-09-24T11:05:00Z';
        marked++;
      }
    }
    return FakeResponse(200, <String, dynamic>{'marked_read': marked});
  }

  FakeResponse _playerGenerateProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (coachControlsProgram) {
      return const FakeResponse(403, <String, dynamic>{
        'detail': 'Your assigned coach controls your program. Ask your coach for changes.'
      });
    }
    return FakeResponse(200, _activeProgramBody());
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
    if (request.method == 'PUT') {
      return _updateProfile(request);
    }
    return FakeResponse(200, _profileBody());
  }

  Map<String, dynamic> _profileBody() => <String, dynamic>{
        'rep_preference': repPreference,
        'weekly_frequency': weeklyFrequency,
      };

  FakeResponse _updateProfile(FakeRequest request) {
    final int? frequency = (request.body['weekly_frequency'] as num?)?.toInt();
    final String? preference = request.body['rep_preference'] as String?;
    final bool rebuildWarranted = (frequency != null && frequency != weeklyFrequency) ||
        (preference != null && preference != repPreference);
    if (frequency != null) weeklyFrequency = frequency;
    if (preference != null) repPreference = preference;

    if (rebuildWarranted && (coachControlsProgram || profileBlocked)) {
      return FakeResponse(200, <String, dynamic>{
        'profile': _profileBody(),
        'program_rebuilt': false,
        'program': null,
        'program_blocked': true,
        'program_message':
            'Your assigned coach controls your program. Ask your coach for changes.',
      });
    }
    return FakeResponse(200, <String, dynamic>{
      'profile': _profileBody(),
      'program_rebuilt': rebuildWarranted,
      'program': rebuildWarranted ? _activeProgramBody() : null,
      'program_blocked': false,
      'program_message': null,
    });
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
    if (nullOnboardingProgram) {
      return const FakeResponse(200, <String, dynamic>{
        'program_name': null,
        'weekly_frequency': null,
        'program_message':
            'Your assigned coach controls your program. Ask your coach for changes.',
      });
    }
    return const FakeResponse(200, <String, dynamic>{
      'program_name': 'Upper/Lower 4x',
      'weekly_frequency': 4,
    });
  }

  Map<String, dynamic> _activeProgramBody() => <String, dynamic>{
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
      if (programVersion != null) 'version': programVersion,
      if (programPublishedByCoachAccountId != null)
        'published_by_coach_account_id': programPublishedByCoachAccountId,
    };

  FakeResponse _activeProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return FakeResponse(200, _activeProgramBody());
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
      lifterPlan = 'free';
      coachPlan = 'free';
      profileExists = false;
      recoveryEmail = null;
      repPreference = 'balanced';
      weeklyFrequency = 4;
      profileBlocked = false;
      coachDisplayName = '';
      coachBio = '';
      coachSpecialization = '';
      coachCapacity = 10;
      validCoachInviteToken = null;
      coachProfileLoadFails = false;
      pendingAssignmentToken = null;
      pendingCoachDisplayName = 'Coach Alice';
      pendingCoachSpecialization = 'Powerlifting';
      issuedAssignmentToken = null;
      activeAssignmentId = null;
      activeCoachDisplayName = null;
      activeCoachSpecialization = null;
      myAssignmentFails = false;
      assignmentNotices.clear();
      assignments.clear();
      _publishedVersion = 0;
      programVersion = null;
      programPublishedByCoachAccountId = null;
      coachControlsProgram = false;
      playerNotices.clear();
      programRequests.clear();
      staleProgramRequest = false;
      _programRequestSeq = 0;
      coachHistoryDenied = false;
      coachPlayerSummary = _defaultCoachSummary();
      coachPlayerRecords = _defaultCoachRecords();
      coachPlayerExercises = _defaultCoachExercises();
      coachPlayerHistories = _defaultCoachHistories();
      _answeredSteps = 0;
      _assistantMessages = <String>[];
      _onboardingComplete = false;
      nullOnboardingProgram = false;
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
