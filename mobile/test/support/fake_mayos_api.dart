import 'dart:convert';

import 'package:mayos_mobile/src/core/models.dart';

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
  bool loginNetworkFails = false;
  bool displayLanguageUpdateFails = false;
  bool coach = false;
  bool playerCapability = true;
  // Account deletion (issue #40). `accountDeleted` makes every authenticated
  // request answer 401 `{"error": "account_deleted"}`, as a device holding an
  // old token would see; the password delete endpoint is handled below.
  bool accountDeleted = false;
  int deleteAccountRequests = 0;
  String? lastDeletePassword;
  String lifterPlan = 'free';
  String coachPlan = 'free';
  bool profileExists = false;
  String? recoveryEmail;
  bool recoveryEmailVerified = true;
  String? currentRecoveryEmailCode;
  int recoveryEmailCodesSent = 0;
  // Password recovery (#38).
  String resetConfirmation =
      'If this email is linked to a ledger, a reset link is on its way.';
  String? validResetToken;
  int forgotRequests = 0;
  String? lastForgotEmail;
  // Player profile fields written through `PUT /profile` (#27).
  String repPreference = 'balanced';
  int weeklyFrequency = 4;
  String equipmentAccess = equipmentAccessCommercialGym;
  String currentGoal = 'Get stronger';
  String injuriesOrLimitations = 'None';
  double weightKg = 75;
  final List<Map<String, dynamic>> profileUpdateBodies =
      <Map<String, dynamic>>[];
  int profileRebuildCalls = 0;
  int _profileProgramRevision = 0;
  String assistantStyle = defaultAssistantStyle;
  String assistantInstructions = '';
  // Forces a coach-controlled profile-update response even with no publication.
  bool profileBlocked = false;
  String coachDisplayName = '';
  String coachBio = '';
  String coachSpecialization = '';
  int coachCapacity = 10;
  String? validCoachInviteToken;
  String? validNewAccountCoachInviteCode;
  String? lastRegistrationCoachInviteCode;
  bool coachProfileLoadFails = false;
  bool coachAssignmentsNetworkFails = false;
  String? currentAccountDisplayLanguageOverride;

  // Google sign-in and the username picker (#115).
  /// The ID token that answers with a session instead of a signup ticket.
  String googleLinkedIdToken = 'google-linked-id-token';

  /// The account a linked Google subject resolves to.
  String googleLinkedUsername = 'alice';
  String googleSuggestedUsername = 'alice';
  String googleSignupTicket = 'signup-ticket-1';
  bool googleExistingAccountHint = false;
  bool googleTicketExpired = false;

  /// Answers `POST /auth/google/complete` with the service's other 409 — the
  /// subject was linked while the ticket was open (#113).
  bool googleCompleteAlreadyLinked = false;
  final Set<String> googleTakenUsernames = <String>{};
  int googleSignInRequests = 0;
  int usernameAvailableRequests = 0;
  int googleCompleteRequests = 0;
  bool googleCompleteRecoveryEmailVerified = false;
  final List<String> googleCompletedUsernames = <String>[];
  final List<String> googleCompletedIdTokens = <String>[];

  // Sign-in methods in Settings (#114/#116): what `GET /auth/me` reports and
  // what the connect/disconnect/set-password/change-password routes do.
  /// Mirrors `auth_service.account_has_password` for the signed-in account.
  bool hasPassword = true;
  String displayLanguage = 'en';
  String? registeredDisplayLanguage;

  /// Provider names on `linked_sign_ins` (never a subject).
  final Set<String> linkedSignIns = <String>{};
  int linkGoogleRequests = 0;
  int unlinkGoogleRequests = 0;
  int setPasswordRequests = 0;
  int changePasswordRequests = 0;
  String? lastLinkGoogleIdToken;
  String? lastSetPassword;
  String? lastChangePasswordNew;

  /// Scripts the two `POST /auth/google/link` 409 conflicts (#114).
  bool googleLinkConflictElsewhere = false;
  bool googleLinkConflictDifferent = false;

  /// The Google ID token `DELETE /auth/account` accepts as proof; any other
  /// answer is the same generic 400 a wrong password gets.
  String googleDeleteIdToken = 'fake-google-id-token';
  String? lastDeleteGoogleIdToken;

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

  // Coach missed-day alerts (#31).
  final List<Map<String, dynamic>> coachAlerts = <Map<String, dynamic>>[];

  // Coach check-ins and follow-ups (#32).
  final List<Map<String, dynamic>> checkIns = <Map<String, dynamic>>[];
  int _checkInSeq = 0;

  // Coach program publication and player notices (#26).
  int _publishedVersion = 0;
  int? programVersion;
  String? programPublishedByCoachAccountId;
  bool repeatBenchPressOnOtherDays = false;
  List<Map<String, dynamic>>? programDaysOverride;
  final List<Map<String, dynamic>> programSubstitutionRequests =
      <Map<String, dynamic>>[];
  final List<Map<String, dynamic>> programSubstitutionUndoRequests =
      <Map<String, dynamic>>[];
  final Map<int, List<Map<String, dynamic>>> _programDaysByVersion =
      <int, List<Map<String, dynamic>>>{};
  // When true, `GET /programs/active` fails with a transient 500 (offline
  // simulation for the Program tab's cache fallback, ADR 020/033).
  bool activeProgramFails = false;
  bool coachControlsProgram = false;
  bool substitutionVersionConflict = false;
  // When true `GET /programs/active` returns an empty body (no active program).
  bool noActiveProgram = false;

  /// Per-exercise `target_rpe` overrides for `GET /workouts/prescription`, so a
  /// test can pin a different target cap than the default program fixture and
  /// assert its equivalent minimum RIR (#111).
  final Map<String, double> prescriptionTargetRpe = <String, double>{};
  bool prescriptionOffline = false;
  Map<String, dynamic> prescriptionDeload = <String, dynamic>{
    'state': 'none',
    'reason': null,
    'volume_multiplier': 1.0,
    'intensity_cap_rpe': null,
  };
  // When true the volume and personal-records endpoints return empty, so the
  // Home empty states can be captured and tested.
  bool volumeEmpty = false;
  bool recordsEmpty = false;
  List<Map<String, dynamic>>? personalRecordsBody;
  List<Map<String, dynamic>> checkpointReviewRows = <Map<String, dynamic>>[];
  final Map<int, Map<String, dynamic>> checkpointReviewDetails =
      <int, Map<String, dynamic>>{};
  // Progress (#48). `GET /dashboard/exercises` lists the exercises the player
  // has logged; `dashboardExerciseHistories` supplies each one's progression
  // points; `volumeDaysRequests` records every `days` value the client asked
  // for so period switching is assertable.
  List<Map<String, dynamic>> loggedExercises = _defaultLoggedExercises();
  bool loggedExercisesFails = false;
  Map<String, Map<String, dynamic>> dashboardExerciseHistories =
      _defaultDashboardHistories();
  final List<int> volumeDaysRequests = <int>[];
  Map<int, Map<String, dynamic>>? volumeByDays;
  // `GET /workouts/sessions/latest` (#53): null means "no committed sessions"
  // (404); when set, the map is returned as the player's latest session.
  Map<String, dynamic>? latestSessionBody;
  bool latestSessionFails = false;

  /// Weekly streak and Checkpoint response for issue #220.
  Map<String, dynamic>? trainingStatusBody;
  bool trainingStatusFails = false;
  int trainingStatusRequests = 0;

  // Exercise baselines (`GET /workouts/baselines`, #122/#123): the rows the
  // device freezes into its Active workout. `baselinesRequests` counts every
  // authorized hit so prefetch vs start fetches are assertable; `baselinesFails`
  // answers 500 and `baselinesMalformed` a wrong-shaped body.
  List<Map<String, dynamic>> baselinesBody = <Map<String, dynamic>>[];
  bool baselinesFails = false;
  bool baselinesMalformed = false;
  int baselinesRequests = 0;

  final List<Map<String, dynamic>> playerNotices = <Map<String, dynamic>>[];

  // Player program requests and coach resolution (#28).
  final List<Map<String, dynamic>> programRequests = <Map<String, dynamic>>[];
  bool staleProgramRequest = false;
  // When true the coach program-request responses carry a wrong-shaped body,
  // so the client's fail-closed parsing is assertable (#121).
  bool malformedProgramRequests = false;
  int _programRequestSeq = 0;

  // Offline workout sync (#34). ``sessionCommits`` is the idempotency record;
  // ``committedSessions`` excludes replayed retries.
  final List<Map<String, dynamic>> committedSessions = <Map<String, dynamic>>[];
  final Map<String, Map<String, dynamic>> sessionCommits =
      <String, Map<String, dynamic>>{};
  int commitRequests = 0;
  bool commitFails = false;
  bool commitResponseLost = false;
  Map<String, dynamic>? checkpointOnCommit;
  int? commitRefusalStatusCode;
  String commitRefusalMessage = 'The workout could not be recorded.';
  String? commitRefusalErrorCode;
  // Performed-date corrections (#36): when true every correction is refused 409,
  // emulating a session outside the window.
  bool correctionRefused = false;
  final Map<String, Map<String, dynamic>> correctedSessions =
      <String, Map<String, dynamic>>{};
  int _sessionSeq = 0;

  // Hosted player-assistant chat (#37).
  final List<Map<String, dynamic>> chatHistory = <Map<String, dynamic>>[];
  int _chatSeq = 0;
  // When true, chat reads/sends fail as a dropped connection (offline).
  bool chatOffline = false;
  // When true, `POST /chat/messages` emits an SSE error frame after the user
  // message is stored (a failed turn; no assistant reply is persisted).
  bool chatSendError = false;
  // When true, the done frame reports `program_updated: true`.
  bool chatProgramUpdated = false;
  Map<String, dynamic>? chatRequestSuggestion;
  List<String> chatReplyChunks = <String>['Keep your ', 'elbows tucked.'];

  // Exact method+path pairs that fail as a dropped connection (offline
  // program-changing action, spec AC3). Add via ``failOffline('POST', path)``.
  final Set<String> offlineRequests = <String>{};

  /// Test hook: make one method+path fail as a network error.
  void failOffline(String method, String path) {
    offlineRequests.add('${method.toUpperCase()} $path');
  }

  bool _isOfflineRequest(FakeRequest request) =>
      offlineRequests.contains('${request.method} ${request.path}');

  // Player training schedule and pauses (#30).
  List<Map<String, dynamic>> scheduleVersions = _defaultScheduleVersions();
  List<Map<String, dynamic>> trainingPauses = _defaultTrainingPauses();
  int _scheduleSeq = 0;
  int _pauseSeq = 0;
  // When true the player has no schedule yet, so no version is current.
  bool scheduleEmpty = false;

  // Coach drill-down (#25). Denied mirrors a revoked/foreign assignment.
  bool coachHistoryDenied = false;
  Map<String, dynamic> coachPlayerSummary = _defaultCoachSummary();
  List<Map<String, dynamic>> coachPlayerRecords = _defaultCoachRecords();
  List<Map<String, dynamic>> coachPlayerExercises = _defaultCoachExercises();
  Map<String, Map<String, dynamic>> coachPlayerHistories =
      _defaultCoachHistories();

  // Coach AI assistant (#45). `coachAiEnabled` is the effective feature state
  // reported on `/auth/me` AND enforced on the assistant route, so flipping it
  // off mid-session reproduces the service answering 404 to a stale entry.
  bool coachAiEnabled = false;
  // When true the assistant route denies with the generic 403 of an assignment
  // that is no longer active (revoked/foreign).
  bool coachAssistantDenied = false;
  // When true the assistant route answers the app-wide model-limit 429.
  bool coachAssistantRateLimited = false;
  String coachAssistantAnswer =
      'Volume is steady and the records are trending up. Keep the current split.';

  /// Every assistant request body the app sent, for history assertions.
  final List<Map<String, dynamic>> coachAssistantRequests =
      <Map<String, dynamic>>[];

  /// When true, `GET /auth/me` fails with a transient 500 (token still valid).
  bool meFails = false;
  int _answeredSteps = 0;
  List<String> _assistantMessages = <String>[];
  bool _onboardingComplete = false;
  // When true, completion returns null program fields (coach-controlled edge).
  bool nullOnboardingProgram = false;

  // Structured, resumable onboarding intake (#50).
  bool intakeDisclosureAcknowledged = false;
  String intakeStatus = 'in_progress';
  Map<String, Object?> intakeAnswers = <String, Object?>{};
  Map<String, dynamic>? intakeProgram;
  // When true, `GET /onboarding/intake` omits the required `fields` key.
  bool intakeMalformed = false;
  bool legacyEquipmentIntakeContract = false;
  final Map<String, Map<String, dynamic>> intakeFieldOverrides =
      <String, Map<String, dynamic>>{};
  final Set<String> omittedIntakeFields = <String>{};
  // When set, the next answer for this field is refused 400 with a server
  // message, so the UI's inline server-error path can be exercised.
  String? intakeRejectField;
  String intakeRejectMessage =
      'The service rejected this answer. Adjust it and try again.';

  FakeResponse _handle(FakeRequest request) {
    final String path = request.path;
    if (_isOfflineRequest(request)) {
      return const FakeResponse.networkFailure();
    }
    // Once an account is deleted, every authenticated request reports the
    // account_deleted signal (a validly signed but dead token), including the
    // draft-sync lookups and commits.
    if (accountDeleted && request.headers['Authorization'] is String) {
      return const FakeResponse(
          401, <String, dynamic>{'error': 'account_deleted'});
    }
    if (path == '/dashboard/training-status') {
      return _trainingStatus(request);
    }
    if (path.startsWith('/checkpoint-reviews')) {
      return _checkpointReview(request);
    }
    if (path == '/chat/history') {
      return _chatHistoryResponse(request);
    }
    if (path == '/chat/messages') {
      return _chatMessage(request);
    }
    if (path.startsWith('/coach/assignments/') && path.endsWith('/assistant')) {
      return _coachAssistant(request);
    }
    if (path.startsWith('/workouts/sessions/by-client-id/')) {
      return _sessionByClientId(request);
    }
    if (path == '/workouts/sessions/latest') {
      return _latestSession(request);
    }
    if (path.startsWith('/workouts/sessions/') &&
        path.endsWith('/performed-date')) {
      return _correctPerformedDate(request);
    }
    if (path == '/workouts/prescription') {
      return _prescription(request);
    }
    if (path == '/workouts/baselines') {
      return _baselines(request);
    }
    if (path == '/workouts/exercises') {
      return _searchExercises(request);
    }
    if (path.startsWith('/workouts/exercises/')) {
      return _exerciseDetail(request);
    }
    if (path == '/dashboard/exercises') {
      return _loggedExercises(request);
    }
    if (path.startsWith('/dashboard/exercises/') && path.endsWith('/history')) {
      return _dashboardExerciseHistory(request);
    }
    if (path == '/workouts/sessions') {
      return _commitSession(request);
    }
    if (path == '/assignments/me/check-ins') {
      return _playerCheckIns(request);
    }
    if (path.startsWith('/coach/assignments/') && path.endsWith('/check-ins')) {
      return _coachCheckIns(request);
    }
    if (path.startsWith('/coach/assignments/') &&
        path.contains('/program-requests')) {
      return _coachProgramRequests(request);
    }
    if (path.startsWith('/coach/alerts/')) {
      return _coachAlertAction(request);
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
    if (path.startsWith('/onboarding/intake')) {
      return _onboardingIntake(request);
    }
    switch (path) {
      case '/auth/register':
        return _register(request);
      case '/auth/google':
        return _googleSignIn(request);
      case '/auth/google/complete':
        return _googleComplete(request);
      case '/auth/google/link':
        return _googleLink(request);
      case '/auth/set-password':
        return _setPassword(request);
      case '/auth/change-password':
        return _changePassword(request);
      case '/auth/username-available':
        return _usernameAvailable(request);
      case '/auth/login':
        return _login(request);
      case '/auth/logout':
        return _authorized(request)
            ? const FakeResponse(204)
            : const FakeResponse(
                401, <String, dynamic>{'detail': 'Token has been revoked.'});
      case '/auth/me':
        return _me(request);
      case '/auth/display-language':
        return _updateDisplayLanguage(request);
      case '/auth/email':
        return _recoveryEmail(request);
      case '/auth/email/verification-code':
        return _sendRecoveryEmailCode(request);
      case '/auth/email/verify':
        return _verifyRecoveryEmail(request);
      case '/auth/forgot-password':
        return _forgotPassword(request);
      case '/auth/reset-password':
        return _resetPassword(request);
      case '/auth/account':
        return _deleteAccount(request);
      case '/coach/invite/redeem':
        return _redeemCoachInvite(request);
      case '/coach/profile':
        return _coachProfile(request);
      case '/coach/program-requests':
        return _coachCrossRosterProgramRequests(request);
      case '/coach/assignments':
        return _coachAssignments(request);
      case '/coach/assignments/invites':
        return _issueAssignmentInvite(request);
      case '/coach/assignments/notices':
        return _coachNotices(request);
      case '/coach/assignments/notices/read':
        return _markNoticesRead(request);
      case '/coach/alerts':
        return _listCoachAlerts(request);
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
      case '/profile/schedule':
        return _schedule(request);
      case '/profile/schedule/pauses':
        return _schedulePauses(request);
      case '/profile/persona':
        return _profilePersona(request);
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
      case '/programs/active/substitutions':
        return _substituteActiveProgram(request);
      case '/programs/active/substitutions/undo':
        return _undoActiveProgramSubstitution(request);
      case '/dashboard/volume':
        return _volume(request);
      case '/dashboard/personal-records':
        return _personalRecords(request);
      default:
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Not found.'});
    }
  }

  static final RegExp googleUsernamePattern = RegExp(r'^[a-z0-9_-]{3,30}$');
  static const String _invalidUsername =
      'Username must be 3–30 characters of a–z, 0–9, _ or - (lowercase).';

  FakeResponse _googleSignIn(FakeRequest request) {
    googleSignInRequests++;
    final String? idToken = request.body['id_token'] as String?;
    if (idToken == null ||
        idToken.isEmpty ||
        idToken == 'google-invalid-id-token') {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Invalid Google credentials.'});
    }
    if (idToken == googleLinkedIdToken) {
      _beginSession(googleLinkedUsername);
      return FakeResponse(200, _tokenBody(googleLinkedUsername));
    }
    // An unlinked subject gets no account and no session yet: only the short
    // ticket that opens the picker (#113).
    return FakeResponse(200, <String, dynamic>{
      'signup_ticket': googleSignupTicket,
      'suggested_username': googleSuggestedUsername,
      'existing_account_hint': googleExistingAccountHint,
    });
  }

  FakeResponse _usernameAvailable(FakeRequest request) {
    usernameAvailableRequests++;
    final dynamic authorization = request.headers['Authorization'];
    if (googleTicketExpired || authorization != 'Bearer $googleSignupTicket') {
      return const FakeResponse(401,
          <String, dynamic>{'detail': 'Invalid or expired signup ticket.'});
    }
    final String? username = request.query['username'] as String?;
    if (username == null || !googleUsernamePattern.hasMatch(username)) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': _invalidUsername});
    }
    if (googleTakenUsernames.contains(username)) {
      return const FakeResponse(
          200, <String, dynamic>{'available': false, 'reason': 'taken'});
    }
    return const FakeResponse(200, <String, dynamic>{'available': true});
  }

  FakeResponse _googleComplete(FakeRequest request) {
    googleCompleteRequests++;
    final String? ticket = request.body['signup_ticket'] as String?;
    final String? username = request.body['username'] as String?;
    final String? idToken = request.body['id_token'] as String?;
    if (googleTicketExpired || ticket != googleSignupTicket) {
      return const FakeResponse(401,
          <String, dynamic>{'detail': 'Invalid or expired signup ticket.'});
    }
    if (username == null || !googleUsernamePattern.hasMatch(username)) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': _invalidUsername});
    }
    if (googleCompleteAlreadyLinked) {
      return const FakeResponse(409, <String, dynamic>{
        'detail': 'This Google account is already linked to a MAYOS account.',
      });
    }
    if (googleTakenUsernames.contains(username)) {
      return const FakeResponse(
          409, <String, dynamic>{'detail': 'That username is taken.'});
    }
    if (idToken != null && idToken.isEmpty) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Invalid Google credentials.'});
    }
    googleCompletedUsernames.add(username);
    if (idToken != null) {
      googleCompletedIdTokens.add(idToken);
    }
    displayLanguage = request.body['display_language'] == 'ar' ? 'ar' : 'en';
    // A fresh Google sign-up creates a Google-only account (#113).
    hasPassword = false;
    linkedSignIns
      ..clear()
      ..add('google');
    _beginSession(username, fresh: true);
    if (googleCompleteRecoveryEmailVerified && idToken != null) {
      recoveryEmail = 'google@example.com';
      recoveryEmailVerified = true;
    }
    return FakeResponse(200, _tokenBody(username));
  }

  /// `POST`/`DELETE /auth/google/link` (#114): connect is idempotent for the
  /// same subject and refuses both conflicts with 409; disconnect is refused
  /// with 409 while the account has no password.
  FakeResponse _googleLink(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.method == 'DELETE') {
      unlinkGoogleRequests++;
      if (!linkedSignIns.contains('google')) {
        return const FakeResponse(200,
            <String, dynamic>{'message': 'No Google account was connected.'});
      }
      if (!hasPassword) {
        return const FakeResponse(409, <String, dynamic>{
          'detail':
              'Set a password before disconnecting Google, so you can still sign in.'
        });
      }
      linkedSignIns.remove('google');
      return const FakeResponse(
          200, <String, dynamic>{'message': 'Google account disconnected.'});
    }
    linkGoogleRequests++;
    final String? idToken = request.body['id_token'] as String?;
    lastLinkGoogleIdToken = idToken;
    if (idToken == null ||
        idToken.isEmpty ||
        idToken == 'google-invalid-id-token') {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Invalid Google credentials.'});
    }
    if (googleLinkConflictElsewhere) {
      return const FakeResponse(409, <String, dynamic>{
        'detail':
            'This Google account is already connected to another MAYOS account'
      });
    }
    if (googleLinkConflictDifferent) {
      return const FakeResponse(409, <String, dynamic>{
        'detail':
            'This account already has a different Google account connected. Disconnect it first.'
      });
    }
    linkedSignIns.add('google');
    return const FakeResponse(
        200, <String, dynamic>{'message': 'Google account connected.'});
  }

  /// `POST /auth/set-password`: first password only, never an epoch bump (#114).
  FakeResponse _setPassword(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    setPasswordRequests++;
    final String? password = request.body['new_password'] as String?;
    lastSetPassword = password;
    if (hasPassword) {
      return const FakeResponse(409, <String, dynamic>{
        'detail': 'A password is already set. Use change-password to change it.'
      });
    }
    if (password == null || password.length < 8) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Password is too short.'});
    }
    hasPassword = true;
    passwords[currentUsername ?? ''] = password;
    return const FakeResponse(
        200, <String, dynamic>{'message': 'Password set.'});
  }

  /// `POST /auth/change-password`: replaces an existing password and revokes
  /// every session, so the fake invalidates the token it just used.
  FakeResponse _changePassword(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    changePasswordRequests++;
    final String? current = request.body['current_password'] as String?;
    final String? password = request.body['new_password'] as String?;
    lastChangePasswordNew = password;
    if (!hasPassword || passwords[currentUsername] != current) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid credentials.'});
    }
    if (password == null || password.length < 8) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Password is too short.'});
    }
    passwords[currentUsername ?? ''] = password;
    tokenValid = false;
    issuedToken = null;
    return const FakeResponse(
        200, <String, dynamic>{'message': 'Password updated.'});
  }

  FakeResponse _register(FakeRequest request) {
    final String? username = request.body['trainee_id'] as String?;
    final String? password = request.body['password'] as String?;
    if (username == null || password == null || password.length < 8) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Password is too short.'});
    }
    final String? coachInviteCode =
        request.body['coach_invite_code'] as String?;
    registeredDisplayLanguage = request.body['display_language'] as String?;
    displayLanguage = registeredDisplayLanguage == 'ar' ? 'ar' : 'en';
    lastRegistrationCoachInviteCode = coachInviteCode;
    if (coachInviteCode != null &&
        coachInviteCode != validNewAccountCoachInviteCode) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': "This coach invite code isn't valid for this username",
      });
    }
    passwords[username] = password;
    hasPassword = true;
    linkedSignIns.clear();
    _beginSession(username, fresh: true);
    if (coachInviteCode != null) coach = true;
    return FakeResponse(201, _tokenBody(username));
  }

  FakeResponse _login(FakeRequest request) {
    if (loginNetworkFails) {
      return const FakeResponse.networkFailure();
    }
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
    if (meFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return FakeResponse(200, <String, dynamic>{
      'account_id': 'account-$currentUsername',
      'trainee_id': currentUsername,
      'capabilities': <String, dynamic>{
        'player': playerCapability,
        'coach': coach,
      },
      'plans': _plansBody(),
      'coach_ai_enabled': coachAiEnabled,
      'has_password': hasPassword,
      'linked_sign_ins': linkedSignIns.toList(growable: false),
      'display_language':
          currentAccountDisplayLanguageOverride ?? displayLanguage,
      'recovery_email_verified':
          recoveryEmail != null && recoveryEmailVerified,
    });
  }

  FakeResponse _updateDisplayLanguage(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (displayLanguageUpdateFails) {
      return const FakeResponse(503, <String, dynamic>{'detail': 'offline'});
    }
    final language = request.body['display_language'];
    if (language != 'en' && language != 'ar') {
      return const FakeResponse(
          422, <String, dynamic>{'detail': 'Invalid display language.'});
    }
    displayLanguage = language as String;
    return FakeResponse(
        200, <String, dynamic>{'display_language': displayLanguage});
  }

  Map<String, dynamic> _plansBody() => <String, dynamic>{
        'lifter': <String, dynamic>{'plan': lifterPlan, 'status': 'active'},
        if (coach)
          'coach': <String, dynamic>{'plan': coachPlan, 'status': 'active'},
      };

  FakeResponse _recoveryEmail(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.method == 'GET') {
      return FakeResponse(200, <String, dynamic>{
        'email': recoveryEmail,
        'verified': recoveryEmail != null && recoveryEmailVerified,
      });
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
    if (normalized != recoveryEmail) {
      recoveryEmail = normalized;
      recoveryEmailVerified = false;
      currentRecoveryEmailCode = null;
    }
    return FakeResponse(200, <String, dynamic>{
      'email': normalized,
      'verified': recoveryEmailVerified,
    });
  }

  FakeResponse _sendRecoveryEmailCode(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (recoveryEmail == null || recoveryEmailVerified) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired verification code.'});
    }
    recoveryEmailCodesSent++;
    currentRecoveryEmailCode = recoveryEmailCodesSent.toString().padLeft(6, '0');
    return const FakeResponse(
        200, <String, dynamic>{'message': 'A verification code has been sent.'});
  }

  FakeResponse _verifyRecoveryEmail(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.body['code'] != currentRecoveryEmailCode ||
        currentRecoveryEmailCode == null) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired verification code.'});
    }
    recoveryEmailVerified = true;
    currentRecoveryEmailCode = null;
    return const FakeResponse(
        200, <String, dynamic>{'message': 'Recovery email verified.'});
  }

  FakeResponse _forgotPassword(FakeRequest request) {
    forgotRequests++;
    lastForgotEmail = request.body['email'] as String?;
    // Anti-enumeration: always the same constant message, known or unknown.
    return FakeResponse(202, <String, dynamic>{'message': resetConfirmation});
  }

  FakeResponse _resetPassword(FakeRequest request) {
    final String? token = request.body['token'] as String?;
    final String? password = request.body['new_password'] as String?;
    if (password == null || password.length < 8) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Password is too short.'});
    }
    if (validResetToken == null || token != validResetToken) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid or expired reset code.'});
    }
    validResetToken = null;
    // A successful reset revokes every prior session.
    tokenValid = false;
    issuedToken = null;
    return FakeResponse(
        200, <String, dynamic>{'message': 'Password reset. Please log in.'});
  }

  FakeResponse _deleteAccount(FakeRequest request) {
    deleteAccountRequests++;
    lastDeletePassword = request.body['password'] as String?;
    lastDeleteGoogleIdToken = request.body['google_id_token'] as String?;
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    // Exactly one proof (#114): a password, or a fresh Google ID token. Every
    // refusal is the same generic 400.
    final String? googleIdToken = lastDeleteGoogleIdToken;
    if (googleIdToken != null
        ? googleIdToken != googleDeleteIdToken
        : passwords[currentUsername] != lastDeletePassword) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'Invalid credentials.'});
    }
    // The account is gone: all sessions are dead and every authenticated
    // request now answers account_deleted.
    accountDeleted = true;
    tokenValid = false;
    issuedToken = null;
    return FakeResponse(200, <String, dynamic>{'message': 'Account deleted.'});
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
      'display_language': displayLanguage,
      'coach_ai_enabled': coachAiEnabled,
      'recovery_email_verified':
          recoveryEmail != null && recoveryEmailVerified,
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
        'detail':
            'Your roster is full. End an assignment before issuing another invite.'
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
    if (coachAssignmentsNetworkFails) {
      return const FakeResponse.networkFailure();
    }
    // The service derives the urgency basis on every fetch (#118/#120): alert
    // badges from the alerts table unless a test states them explicitly, and
    // the follow-up date a weekly cadence past the newest check-in.
    return FakeResponse(200, <String, dynamic>{
      'assignments': <Map<String, dynamic>>[
        for (final Map<String, dynamic> row in assignments)
          _rosterBasis(Map<String, dynamic>.of(row)),
      ],
    });
  }

  Map<String, dynamic> _rosterBasis(Map<String, dynamic> row) {
    final String id = row['assignment_id'] as String;
    if (row['pending_requests'] == null) {
      row['pending_requests'] = programRequests
          .where((Map<String, dynamic> request) =>
              request['assignment_id'] == id && request['status'] == 'pending')
          .length;
    }
    if (row['alerts_new'] == null || row['alerts_acknowledged'] == null) {
      int alertsNew = 0;
      int alertsAcknowledged = 0;
      for (final Map<String, dynamic> alert in coachAlerts) {
        if (alert['assignment_id'] != id) {
          continue;
        }
        if (alert['state'] == 'new') {
          alertsNew++;
        } else if (alert['state'] == 'acknowledged') {
          alertsAcknowledged++;
        }
      }
      row['alerts_new'] = alertsNew;
      row['alerts_acknowledged'] = alertsAcknowledged;
    }
    final List<Map<String, dynamic>> checkInsForAssignment = checkIns
        .where((Map<String, dynamic> checkIn) => checkIn['assignment_id'] == id)
        .toList(growable: false);
    if (checkInsForAssignment.isNotEmpty) {
      String newest = checkInsForAssignment.first['checked_in_on'] as String;
      for (final Map<String, dynamic> checkIn in checkInsForAssignment) {
        final String on = checkIn['checked_in_on'] as String;
        if (on.compareTo(newest) > 0) {
          newest = on;
        }
      }
      row['next_follow_up_on'] = _addDays(newest, 7);
    }
    return row;
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
    return FakeResponse(200, <String, dynamic>{
      'notices': List<Map<String, dynamic>>.from(assignmentNotices)
    });
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

  FakeResponse _listCoachAlerts(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final dynamic states = request.query['state'];
    final Set<String> wanted = states is List
        ? states.map((dynamic value) => '$value').toSet()
        : states == null
            ? <String>{'new', 'acknowledged'}
            : <String>{'$states'};
    final List<Map<String, dynamic>> rows = coachAlerts
        .where((Map<String, dynamic> alert) =>
            wanted.contains(alert['state'] as String))
        .toList(growable: false);
    return FakeResponse(200, <String, dynamic>{'alerts': rows});
  }

  FakeResponse _coachAlertAction(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final bool acknowledge = request.path.endsWith('/acknowledge');
    final String id = request.path
        .replaceFirst('/coach/alerts/', '')
        .replaceFirst(RegExp(r'/(acknowledge|resolve)$'), '');
    final int index = coachAlerts
        .indexWhere((Map<String, dynamic> alert) => alert['alert_id'] == id);
    if (index < 0) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    final Map<String, dynamic> alert = coachAlerts[index];
    if (acknowledge && alert['state'] == 'new') {
      alert['state'] = 'acknowledged';
      alert['acknowledged_at'] = '2026-09-26T12:00:00Z';
    } else if (!acknowledge && alert['state'] != 'resolved') {
      alert['state'] = 'resolved';
      alert['resolved_at'] = '2026-09-26T12:00:00Z';
      alert['resolved_by'] = 'coach';
    }
    return FakeResponse(200, alert);
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
    assignments.removeWhere(
        (Map<String, dynamic> entry) => entry['assignment_id'] == id);
    return FakeResponse(200, <String, dynamic>{
      'assignment_id': id,
      'status': 'ended',
      'ended_at': '2026-09-24T11:00:00Z',
    });
  }

  /// `POST /coach/assignments/{id}/assistant` (issue #45): the feature gate
  /// answers 404 first, then the ADR 025 pair (coach capability + an owned,
  /// active assignment), then the model-limit 429, then the request bounds.
  FakeResponse _coachAssistant(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    if (!coachAiEnabled) {
      return const FakeResponse(
          404, <String, dynamic>{'detail': 'Coach AI is not available.'});
    }
    final String id = request.path
        .replaceFirst('/coach/assignments/', '')
        .replaceFirst('/assistant', '');
    final bool owned = assignments
        .any((Map<String, dynamic> entry) => entry['assignment_id'] == id);
    if (coachAssistantDenied || !owned) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    if (coachAssistantRateLimited) {
      return const FakeResponse(429, <String, dynamic>{
        'detail': 'Too many AI requests. Please wait a minute and try again.'
      });
    }
    final String question = request.body['question'] as String? ?? '';
    final List<dynamic> history =
        request.body['history'] as List<dynamic>? ?? const <dynamic>[];
    final bool badTurn = history.any((dynamic turn) {
      final dynamic content =
          turn is Map<String, dynamic> ? turn['content'] : null;
      return content is! String || content.isEmpty || content.length > 2000;
    });
    if (question.isEmpty ||
        question.length > 1000 ||
        history.length > 12 ||
        badTurn) {
      return const FakeResponse(
          422, <String, dynamic>{'detail': 'Invalid assistant request.'});
    }
    coachAssistantRequests.add(request.body);
    return FakeResponse(200, <String, dynamic>{'answer': coachAssistantAnswer});
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
    if (path.endsWith('/player/checkpoint-reviews')) {
      return FakeResponse(
          200, List<Map<String, dynamic>>.from(checkpointReviewRows));
    }
    if (path.contains('/player/checkpoint-reviews/')) {
      final int? checkpoint = int.tryParse(path.split('/').last);
      final Map<String, dynamic>? review =
          checkpoint == null ? null : checkpointReviewDetails[checkpoint];
      return review == null
          ? const FakeResponse(404, <String, dynamic>{'detail': 'Not found.'})
          : FakeResponse(200, review);
    }
    if (path.endsWith('/player/summary')) {
      return FakeResponse(200, coachPlayerSummary);
    }
    if (path.endsWith('/player/personal-records')) {
      return FakeResponse(
          200, List<Map<String, dynamic>>.from(coachPlayerRecords));
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
              <String, dynamic>{
                'history': <dynamic>[],
                'caption': null,
                'records': <dynamic>[]
              });
    }
    return const FakeResponse(404, <String, dynamic>{'detail': 'Not found.'});
  }

  FakeResponse _coachCheckIns(FakeRequest request) {
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
        .replaceFirst('/check-ins', '');
    final bool owned = assignments
        .any((Map<String, dynamic> entry) => entry['assignment_id'] == id);
    if (!owned) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    if (request.method == 'POST') {
      return _createCheckIn(request, id);
    }
    return FakeResponse(200, <String, dynamic>{
      'check_ins': checkIns
          .where((Map<String, dynamic> row) => row['assignment_id'] == id)
          .toList(growable: false),
    });
  }

  FakeResponse _createCheckIn(FakeRequest request, String assignmentId) {
    final String? checkedInOn = request.body['checked_in_on'] as String?;
    final String? channel = request.body['channel'] as String?;
    final String? note = (request.body['note'] as String?)?.trim();
    const List<String> channels = <String>[
      'in_app',
      'in_person',
      'phone',
      'video',
      'message',
      'email',
      'other',
    ];
    if (channel == null || !channels.contains(channel)) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'channel is not a recognized contact method.'
      });
    }
    final DateTime? date =
        checkedInOn == null ? null : DateTime.tryParse(checkedInOn);
    if (date == null) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'checked_in_on must be an ISO date (YYYY-MM-DD).'
      });
    }
    if (checkedInOn!.compareTo(_todayIso()) > 0) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'A check-in cannot be dated in the future.'
      });
    }
    if (note != null && note.length > 500) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'A check-in note can be at most 500 characters.'
      });
    }
    final Map<String, dynamic> row = <String, dynamic>{
      'check_in_id': 'check-in-${++_checkInSeq}',
      'assignment_id': assignmentId,
      'checked_in_on': checkedInOn,
      'channel': channel,
      'note': note == null || note.isEmpty ? null : note,
      'created_at': '2026-09-26T12:00:00Z',
      'coach_username': currentUsername,
      'assignment_status': 'active',
    };
    checkIns.insert(0, row);
    // The service resolves the open follow-up alert a new check-in satisfies
    // (service.check_ins.evaluate_follow_up); mirror it so a client sees the
    // same open alerts after saving (#120).
    for (final Map<String, dynamic> alert in coachAlerts) {
      if (alert['assignment_id'] == assignmentId &&
          alert['kind'] == 'follow_up_due' &&
          alert['state'] != 'resolved') {
        alert['state'] = 'resolved';
        alert['resolved_at'] = '2026-09-26T12:00:00Z';
        alert['resolved_by'] = 'system';
      }
    }
    return FakeResponse(200, <String, dynamic>{
      'check_in': row,
      'next_follow_up_on': _addDays(checkedInOn, 7),
    });
  }

  FakeResponse _playerCheckIns(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    return FakeResponse(200, <String, dynamic>{
      'check_ins': List<Map<String, dynamic>>.from(checkIns),
    });
  }

  FakeResponse _chatHistoryResponse(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (chatOffline) {
      return const FakeResponse.networkFailure();
    }
    if (request.method == 'DELETE') {
      chatHistory.clear();
      return const FakeResponse(204);
    }
    // The service annotates each message with its `kind` (ADR 036), so the
    // client renders a debrief card without re-deriving the wording.
    return FakeResponse(
      200,
      <Map<String, dynamic>>[
        for (final Map<String, dynamic> row in chatHistory)
          <String, dynamic>{
            ...row,
            'kind': _chatKind(
              row['role'] as String? ?? '',
              row['content'] as String? ?? '',
            ),
          },
      ],
    );
  }

  static String _chatKind(String role, String content) {
    final bool pointer = role == 'assistant' &&
        content.trimLeft().startsWith('📋') &&
        content.contains('**Session Logged:**');
    return pointer ? 'debrief' : 'message';
  }

  FakeResponse _chatMessage(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (chatOffline) {
      return const FakeResponse.networkFailure();
    }
    final String content = (request.body['content'] as String?)?.trim() ?? '';
    if (content.isEmpty) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'content is required'});
    }
    // Idempotent retry: a failed turn leaves the user message unanswered, so a
    // retry of the same content already the last stored message reuses it
    // rather than inserting a duplicate (service/chat.py::prepare_user_turn).
    final bool alreadyStored = chatHistory.isNotEmpty &&
        chatHistory.last['role'] == 'user' &&
        chatHistory.last['content'] == content;
    if (!alreadyStored) {
      chatHistory.add(<String, dynamic>{
        'id': 'chat-${++_chatSeq}',
        'role': 'user',
        'content': content,
        'created_at': '2026-09-26T12:00:00Z',
      });
    }
    if (chatSendError) {
      return const FakeResponse(200, null, <String>[
        'event: error\ndata: {"detail": "The assistant is temporarily unavailable."}\n\n',
      ]);
    }
    final String reply = chatReplyChunks.join();
    final String suggestionJson = chatRequestSuggestion == null
        ? ''
        : ', "request_suggestion": ${jsonEncode(chatRequestSuggestion)}';
    chatHistory.add(<String, dynamic>{
      'id': 'chat-${++_chatSeq}',
      'role': 'assistant',
      'content': reply,
      'created_at': '2026-09-26T12:00:01Z',
    });
    return FakeResponse(200, null, <String>[
      for (final String chunk in chatReplyChunks)
        'data: {"token": ${jsonEncode(chunk)}}\n\n',
      'data: {"done": true, "response_content": ${jsonEncode(reply)}, '
          '"program_updated": ${chatProgramUpdated ? 'true' : 'false'}'
          '$suggestionJson}\n\n',
    ]);
  }

  String _addDays(String iso, int days) {
    final DateTime? date = DateTime.tryParse(iso);
    if (date == null) {
      return iso;
    }
    final DateTime shifted = date.add(Duration(days: days));
    return '${shifted.year.toString().padLeft(4, '0')}-'
        '${shifted.month.toString().padLeft(2, '0')}-'
        '${shifted.day.toString().padLeft(2, '0')}';
  }

  /// Newest-first schedule versions, including a past edit (#30).
  static List<Map<String, dynamic>> _defaultScheduleVersions() =>
      <Map<String, dynamic>>[
        <String, dynamic>{
          'schedule_id': 'schedule-2',
          'weekdays': <int>[1, 3, 5],
          'timezone': 'Europe/London',
          'effective_from': '2026-09-01',
          'created_at': '2026-08-25T10:00:00Z',
        },
        <String, dynamic>{
          'schedule_id': 'schedule-1',
          'weekdays': <int>[1, 2, 4, 6],
          'timezone': 'Europe/London',
          'effective_from': '2026-08-01',
          'created_at': '2026-07-25T10:00:00Z',
        },
      ];

  /// One active pause, matching the seeded current schedule.
  static List<Map<String, dynamic>> _defaultTrainingPauses() =>
      <Map<String, dynamic>>[
        <String, dynamic>{
          'pause_id': 'pause-1',
          'starts_on': '2026-09-24',
          'ends_on': '2026-10-01',
          'created_at': '2026-09-20T09:00:00Z',
        },
      ];

  static Map<String, dynamic> _defaultCoachSummary() => <String, dynamic>{
        'player_username': 'bob',
        'started_at': '2026-09-24T10:00:00Z',
        'status': 'active',
        'volume': <String, dynamic>{'Chest': 12.5, 'Back': 9.0},
        'schedule': <String, dynamic>{
          'weekdays': <int>[1, 3, 5],
          'timezone': 'Europe/London',
        },
        'pauses': <Map<String, dynamic>>[
          <String, dynamic>{
            'starts_on': '2026-09-28',
            'ends_on': '2026-10-02',
          },
        ],
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
          'divergences': <Map<String, dynamic>>[
            <String, dynamic>{
              'kind': 'skipped',
              'exercise_id': 'squat',
              'exercise_name': 'Squat',
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
            'divergences': <Map<String, dynamic>>[
              <String, dynamic>{
                'kind': 'unplanned',
                'exercise_id': 'lat_pulldown',
                'exercise_name': 'Lat Pulldown',
              },
            ],
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
          'caption': 'Latest Recorded: **100.0 kg × 5 reps @ RIR 2**',
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
        'detail':
            'You must explicitly accept the assignment to redeem this invite.'
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
    if (!coachControlsProgram) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'You can change your own program directly.',
        'code': 'player_controls_program',
      });
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
    final List<String> parts =
        request.path.replaceFirst('/coach/assignments/', '').split('/');
    final String assignmentId = parts.isNotEmpty ? parts[0] : '';
    final bool owned = assignments.any(
        (Map<String, dynamic> entry) => entry['assignment_id'] == assignmentId);
    if (!owned) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'No active assignment.'});
    }
    if (request.path.endsWith('/apply') || request.path.endsWith('/decline')) {
      if (malformedProgramRequests) {
        return FakeResponse(200, <String, dynamic>{'status': 'applied'});
      }
      final String id = parts.length > 2 ? parts[2] : '';
      final int index = programRequests
          .indexWhere((Map<String, dynamic> r) => r['request_id'] == id);
      if (index < 0) {
        return const FakeResponse(
            404, <String, dynamic>{'detail': 'Request not found.'});
      }
      if (programRequests[index]['assignment_id'] != assignmentId) {
        return const FakeResponse(
            403, <String, dynamic>{'detail': 'No active assignment.'});
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
    if (malformedProgramRequests) {
      return FakeResponse(200, <String, dynamic>{'requests': 'not-a-list'});
    }
    return FakeResponse(200, <String, dynamic>{
      'requests': <Map<String, dynamic>>[
        for (final Map<String, dynamic> row in programRequests)
          if (row['assignment_id'] == assignmentId) row,
      ],
    });
  }

  /// `GET /coach/program-requests` (#118): every request across the coach's
  /// active assignments, pending oldest first, then answered most recently
  /// resolved first, each row carrying the requesting player's username.
  FakeResponse _coachCrossRosterProgramRequests(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (!coach) {
      return const FakeResponse(
          403, <String, dynamic>{'detail': 'Coach capability required.'});
    }
    final Map<String, String> usernameByAssignment = <String, String>{
      for (final Map<String, dynamic> entry in assignments)
        entry['assignment_id'] as String: entry['player_username'] as String,
    };
    final List<Map<String, dynamic>> rows = <Map<String, dynamic>>[
      for (final Map<String, dynamic> row in programRequests)
        if (usernameByAssignment.containsKey(row['assignment_id']))
          <String, dynamic>{
            ...row,
            'player_username': usernameByAssignment[row['assignment_id']],
          },
    ];
    final List<Map<String, dynamic>> pending = rows
        .where((Map<String, dynamic> row) => row['status'] == 'pending')
        .toList(growable: false)
      ..sort((Map<String, dynamic> a, Map<String, dynamic> b) {
        final int byDate =
            (a['created_at'] as String).compareTo(b['created_at'] as String);
        return byDate != 0
            ? byDate
            : (a['request_id'] as String).compareTo(b['request_id'] as String);
      });
    final List<Map<String, dynamic>> answered = rows
        .where((Map<String, dynamic> row) => row['status'] != 'pending')
        .toList(growable: false)
      ..sort((Map<String, dynamic> a, Map<String, dynamic> b) {
        final String resolvedA =
            (a['resolved_at'] ?? a['created_at']) as String;
        final String resolvedB =
            (b['resolved_at'] ?? b['created_at']) as String;
        final int byDate = resolvedB.compareTo(resolvedA);
        return byDate != 0
            ? byDate
            : (a['request_id'] as String).compareTo(b['request_id'] as String);
      });
    if (malformedProgramRequests) {
      return FakeResponse(200, <String, dynamic>{'requests': 'not-a-list'});
    }
    return FakeResponse(200, <String, dynamic>{
      'requests': <Map<String, dynamic>>[...pending, ...answered],
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
        'equipment_access': equipmentAccess,
        'current_goal': currentGoal,
        'injuries_or_limitations': injuriesOrLimitations,
        'weight_kg': weightKg,
        'coach_tone': assistantStyle,
        'custom_instructions': assistantInstructions,
        'player_controls_program': !coachControlsProgram,
      };

  FakeResponse _profilePersona(FakeRequest request) {
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
    assistantStyle =
        request.body['coach_tone'] as String? ?? defaultAssistantStyle;
    assistantInstructions =
        (request.body['custom_instructions'] as String? ?? '').trim();
    return FakeResponse(200, <String, dynamic>{'profile': _profileBody()});
  }

  FakeResponse _updateProfile(FakeRequest request) {
    profileUpdateBodies.add(Map<String, dynamic>.from(request.body));
    final int? frequency = (request.body['weekly_frequency'] as num?)?.toInt();
    final String? preference = request.body['rep_preference'] as String?;
    final String? access = request.body['equipment_access'] as String?;
    final String? injuries = request.body['injuries_or_limitations'] as String?;
    final Map<String, Object?> proposed = <String, Object?>{
      'weekly_frequency': frequency,
      'rep_preference': preference,
      'equipment_access': access,
      'injuries_or_limitations': injuries,
    };
    final Map<String, Object?> before = <String, Object?>{
      'weekly_frequency': weeklyFrequency,
      'rep_preference': repPreference,
      'equipment_access': equipmentAccess,
      'injuries_or_limitations': injuriesOrLimitations,
    };
    final bool rebuildWarranted = _profileRebuildFields.any(
      (String field) =>
          proposed[field] != null && proposed[field] != before[field],
    );
    if (frequency != null) weeklyFrequency = frequency;
    if (preference != null) repPreference = preference;
    if (access != null) equipmentAccess = access;
    if (injuries != null) injuriesOrLimitations = injuries;
    final String? goal = request.body['current_goal'] as String?;
    final num? weight = request.body['weight_kg'] as num?;
    if (goal != null) currentGoal = goal;
    if (weight != null) weightKg = weight.toDouble();

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
    if (rebuildWarranted) {
      profileRebuildCalls++;
      _profileProgramRevision++;
    }
    return FakeResponse(200, <String, dynamic>{
      'profile': _profileBody(),
      'program_rebuilt': rebuildWarranted,
      'program': rebuildWarranted ? _activeProgramBody() : null,
      'program_blocked': false,
      'program_message': null,
    });
  }

  FakeResponse _schedule(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.method == 'PUT') {
      return _setSchedule(request);
    }
    final Map<String, dynamic>? current =
        (scheduleEmpty || scheduleVersions.isEmpty)
            ? null
            : scheduleVersions.first;
    return FakeResponse(200, <String, dynamic>{
      'current': current,
      'versions': scheduleEmpty
          ? <Map<String, dynamic>>[]
          : List<Map<String, dynamic>>.from(scheduleVersions),
      'pauses': List<Map<String, dynamic>>.from(trainingPauses),
    });
  }

  FakeResponse _setSchedule(FakeRequest request) {
    final dynamic raw = request.body['weekdays'];
    final String timezone = (request.body['timezone'] as String?)?.trim() ?? '';
    if (raw is! List<dynamic> || raw.isEmpty) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'Pick at least one expected training weekday.'
      });
    }
    final List<int> weekdays = <int>[];
    for (final dynamic day in raw) {
      if (day is! int || day < 1 || day > 7) {
        return const FakeResponse(400, <String, dynamic>{
          'detail':
              'Expected training weekdays must be integers from 1 (Mon) to 7 (Sun).'
        });
      }
      weekdays.add(day);
    }
    if (weekdays.toSet().length != weekdays.length) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'Expected training weekdays must be unique.'
      });
    }
    if (timezone.isEmpty) {
      return const FakeResponse(
          400, <String, dynamic>{'detail': 'A timezone is required.'});
    }
    final String effectiveFrom =
        request.body['effective_from'] as String? ?? _todayIso();
    final Map<String, dynamic> version = <String, dynamic>{
      'schedule_id': 'schedule-new-${++_scheduleSeq}',
      'weekdays': (weekdays..sort()),
      'timezone': timezone,
      'effective_from': effectiveFrom,
      'created_at': '2026-09-26T12:00:00Z',
    };
    scheduleVersions.insert(0, version);
    scheduleEmpty = false;
    return FakeResponse(
        200, <String, dynamic>{'version': version, 'current': version});
  }

  FakeResponse _schedulePauses(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.method == 'POST') {
      return _createPause(request);
    }
    return FakeResponse(200, <String, dynamic>{
      'pauses': List<Map<String, dynamic>>.from(trainingPauses),
    });
  }

  FakeResponse _createPause(FakeRequest request) {
    final String? startsOn = request.body['starts_on'] as String?;
    final String? endsOn = request.body['ends_on'] as String?;
    final DateTime? start =
        startsOn == null ? null : DateTime.tryParse(startsOn);
    final DateTime? end = endsOn == null ? null : DateTime.tryParse(endsOn);
    if (start == null || end == null) {
      return const FakeResponse(400,
          <String, dynamic>{'detail': 'Dates must be ISO dates (YYYY-MM-DD).'});
    }
    final DateTime now = DateTime.now();
    final DateTime today = DateTime(now.year, now.month, now.day);
    if (start.isBefore(today)) {
      return const FakeResponse(400,
          <String, dynamic>{'detail': 'A pause must start today or later.'});
    }
    if (end.isBefore(start)) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'A pause must end on or after it starts.'
      });
    }
    if (end.difference(start).inDays + 1 > 14) {
      return const FakeResponse(400,
          <String, dynamic>{'detail': 'A pause can last at most 14 days.'});
    }
    final Map<String, dynamic> pause = <String, dynamic>{
      'pause_id': 'pause-new-${++_pauseSeq}',
      'starts_on': startsOn,
      'ends_on': endsOn,
      'created_at': '2026-09-26T12:00:00Z',
    };
    trainingPauses.insert(0, pause);
    return FakeResponse(201, <String, dynamic>{
      'pause': pause,
      'notice_sent': activeAssignmentId != null,
    });
  }

  String _todayIso() {
    final DateTime now = DateTime.now();
    return '${now.year.toString().padLeft(4, '0')}-'
        '${now.month.toString().padLeft(2, '0')}-'
        '${now.day.toString().padLeft(2, '0')}';
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

  // The named decision contract mirrored from service/intake.py (#50).
  static const List<String> _profileRebuildFields = <String>[
    'injuries_or_limitations',
    'equipment_access',
    'weekly_frequency',
    'rep_preference',
  ];

  static const List<Map<String, dynamic>> _intakeSchema =
      <Map<String, dynamic>>[
    <String, dynamic>{
      'name': 'gender',
      'type': 'enum',
      'required': true,
      'profile_field': 'gender',
      'allowed_values': <String>['male', 'female'],
      'explanation':
          'Your specialization is required and selects the default split family.',
      'option_descriptions': <String, String>{
        'male': 'Balanced upper- and lower-body training by frequency: full '
            'body at 1-3 days, upper/lower at 4 days, Arnold-style at 5 days.',
        'female': 'Glute- and lower-body-focused by frequency: '
            'glute-specialised full body at 1-3 days, lower-body (glute bias) '
            'and upper body + core at 4-5 days.',
      },
    },
    <String, dynamic>{
      'name': 'proportions',
      'type': 'enum',
      'required': true,
      'profile_field': 'proportions',
      'allowed_values': <String>['long_legs', 'balanced', 'long_torso'],
      'explanation':
          'Relative leg and torso length is coaching context only and does not change the program.',
      'option_descriptions': <String, String>{
        'long_legs': 'Longer legs, shorter torso',
        'balanced': 'Proportional upper and lower body',
        'long_torso': 'Longer torso, shorter legs',
      },
    },
    <String, dynamic>{
      'name': 'age',
      'type': 'int',
      'required': true,
      'profile_field': 'age',
      'minimum': 12,
      'maximum': 100
    },
    <String, dynamic>{
      'name': 'height_cm',
      'type': 'float',
      'required': true,
      'profile_field': 'height_cm',
      'minimum': 100,
      'maximum': 250
    },
    <String, dynamic>{
      'name': 'weight_kg',
      'type': 'float',
      'required': true,
      'profile_field': 'weight_kg',
      'minimum': 30,
      'maximum': 250
    },
    <String, dynamic>{
      'name': 'training_age_years',
      'type': 'float',
      'required': true,
      'profile_field': 'training_age_years',
      'minimum': 0,
      'maximum': 70
    },
    <String, dynamic>{
      'name': 'current_goal',
      'type': 'text',
      'required': true,
      'profile_field': 'current_goal',
      'hint': 'What are you training for right now?',
      'examples': <String>['build glutes and legs', 'get stronger', 'lose fat'],
    },
    <String, dynamic>{
      'name': 'long_term_goal',
      'type': 'text',
      'required': true,
      'profile_field': 'long_term_goal',
      'hint': 'What do you want to achieve over the longer term?',
      'examples': <String>[
        'stronger and more muscular',
        'stay healthy and pain-free'
      ],
    },
    <String, dynamic>{
      'name': 'weekly_frequency',
      'type': 'int',
      'required': true,
      'profile_field': 'weekly_frequency',
      'minimum': 1,
      'maximum': 5
    },
    <String, dynamic>{
      'name': 'equipment_access',
      'type': 'enum',
      'required': true,
      'profile_field': 'equipment_access',
      'allowed_values': <String>[
        equipmentAccessCommercialGym,
        equipmentAccessHomeGym,
        equipmentAccessBodyweightOnly,
      ],
      'option_descriptions': <String, String>{
        equipmentAccessCommercialGym: 'A fully equipped commercial gym.',
        equipmentAccessHomeGym:
            'Equipment you keep at home, such as weights or machines.',
        equipmentAccessBodyweightOnly:
            'No gym equipment; train with your bodyweight.',
      },
    },
    <String, dynamic>{
      'name': 'injuries_or_limitations',
      'type': 'text',
      'required': true,
      'profile_field': 'injuries_or_limitations',
      'hint': "List any injuries or limitations. 'None' is a valid answer.",
      'examples': <String>['None', 'left knee pain on deep squats'],
    },
    <String, dynamic>{
      'name': 'stress_and_sleep',
      'type': 'text',
      'required': true,
      'profile_field': 'stress_and_sleep',
      'hint': 'How are your stress and sleep?',
      'examples': <String>[
        'moderate stress, 7 hours sleep',
        'low stress, 8 hours sleep'
      ],
    },
    <String, dynamic>{
      'name': 'rep_preference',
      'type': 'enum',
      'required': false,
      'profile_field': 'rep_preference',
      'allowed_values': <String>['low', 'balanced', 'high'],
      'option_descriptions': <String, String>{
        'low': 'Lower rep targets: compounds 5-8, isolation 8-12.',
        'balanced': 'Default rep targets: compounds 6-10, isolation 10-15.',
        'high': 'Higher rep targets: compounds 8-12, isolation 12-20.',
      }
    },
  ];

  Map<String, dynamic> _intakeView() {
    final List<Map<String, dynamic>> fields = _intakeSchema
        .where((spec) => !omittedIntakeFields.contains(spec['name']))
        .map((spec) {
      final String name = spec['name'] as String;
      final bool answered = intakeAnswers.containsKey(name);
      return <String, dynamic>{
        ...spec,
        if (name == 'equipment_access' && legacyEquipmentIntakeContract)
          'type': 'text',
        if (name == 'equipment_access' && legacyEquipmentIntakeContract)
          'allowed_values': <String>[],
        'minimum': spec['minimum'],
        'maximum': spec['maximum'],
        if (spec['type'] == 'text') 'minimum_length': 2,
        if (spec['type'] == 'text') 'maximum_length': 500,
        'explanation': spec['explanation'],
        'answer': intakeAnswers[name],
        'prefilled': false,
        'answered': answered,
        'updated_at': answered ? '2026-01-01T00:00:00+00:00' : null,
        ...?intakeFieldOverrides[name],
      };
    }).toList(growable: false);
    final List<String> required = _intakeSchema
        .where((Map<String, dynamic> s) => s['required'] == true)
        .map((Map<String, dynamic> s) => s['name'] as String)
        .toList(growable: false);
    final int answeredRequired =
        required.where(intakeAnswers.containsKey).length;
    String? nextUnanswered;
    for (final String name in required) {
      if (!intakeAnswers.containsKey(name)) {
        nextUnanswered = name;
        break;
      }
    }
    return <String, dynamic>{
      'status': intakeStatus,
      'disclosure_acknowledged': intakeDisclosureAcknowledged,
      'fields': fields,
      'profile_rebuild_fields': _profileRebuildFields,
      'progress': <String, dynamic>{
        'answered_required': answeredRequired,
        'required_total': required.length,
        'answered': intakeAnswers.length,
        'total_fields': _intakeSchema.length,
        'next_unanswered': nextUnanswered,
      },
      'program': intakeStatus == 'confirmed' ? intakeProgram : null,
    };
  }

  String? _validateIntakeAnswer(String field, Object? value) {
    Map<String, dynamic>? spec;
    for (final Map<String, dynamic> candidate in _intakeSchema) {
      if (candidate['name'] == field) {
        spec = candidate;
        break;
      }
    }
    if (spec == null) {
      return "Unknown onboarding field '$field'.";
    }
    final String type = spec['type'] as String;
    if (type == 'enum') {
      final List<String> allowed =
          (spec['allowed_values'] as List<String>?) ?? const <String>[];
      final bool allowedValue = value is String &&
          (field == 'equipment_access'
              ? allowed.any((String option) =>
                  option.toLowerCase() == value.toLowerCase())
              : allowed.contains(value.toLowerCase()));
      if (!allowedValue) {
        return "Invalid value for '$field': must be one of ${allowed.join(', ')}.";
      }
    } else if (type == 'int' || type == 'float') {
      final num? parsed = value is num ? value : num.tryParse('$value');
      if (parsed == null) {
        return "Invalid value for '$field': must be a number.";
      }
      if (type == 'int' && parsed != parsed.roundToDouble()) {
        return "Invalid value for '$field': must be a whole number.";
      }
      final num? min = spec['minimum'] as num?;
      final num? max = spec['maximum'] as num?;
      if ((min != null && parsed < min) || (max != null && parsed > max)) {
        return "Invalid value for '$field': out of range.";
      }
    } else {
      if (value is! String || value.trim().length < 2) {
        return "Invalid value for '$field': must be at least 2 characters.";
      }
    }
    return null;
  }

  FakeResponse _onboardingIntake(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String path = request.path;
    if (path == '/onboarding/intake' && request.method == 'GET') {
      if (intakeMalformed) {
        // Missing the required `fields` key; the client must fail parsing.
        return const FakeResponse(200, <String, dynamic>{
          'status': 'in_progress',
          'disclosure_acknowledged': false,
        });
      }
      return FakeResponse(200, _intakeView());
    }
    if (path == '/onboarding/intake/disclosure' && request.method == 'POST') {
      intakeDisclosureAcknowledged = true;
      return FakeResponse(200, _intakeView());
    }
    if (path == '/onboarding/intake/confirm' && request.method == 'POST') {
      if (intakeStatus == 'confirmed') {
        return FakeResponse(200, <String, dynamic>{
          'status': 'confirmed',
          'program_name': intakeProgram?['program_name'],
          'weekly_frequency': intakeProgram?['weekly_frequency'],
          'program_message': intakeProgram?['program_message'],
        });
      }
      if (!intakeDisclosureAcknowledged) {
        return const FakeResponse(403, <String, dynamic>{
          'detail':
              'Acknowledge the hosted-processing disclosure before creating your program.'
        });
      }
      final List<String> missing = _intakeSchema
          .where((Map<String, dynamic> s) => s['required'] == true)
          .map((Map<String, dynamic> s) => s['name'] as String)
          .where((String name) => !intakeAnswers.containsKey(name))
          .toList(growable: false);
      if (missing.isNotEmpty) {
        return FakeResponse(400, <String, dynamic>{
          'detail':
              'Missing required onboarding answers: ${missing.join(', ')}.'
        });
      }
      intakeStatus = 'confirmed';
      profileExists = true;
      intakeProgram = nullOnboardingProgram
          ? <String, dynamic>{
              'program_name': null,
              'weekly_frequency': null,
              'program_message':
                  'Your coach controls your program, so none was generated.',
            }
          : <String, dynamic>{
              'program_name': 'Upper/Lower 4x',
              'weekly_frequency': 4,
              'program_message': null,
            };
      return FakeResponse(200, <String, dynamic>{
        'status': 'confirmed',
        ...intakeProgram!,
      });
    }
    if (path.startsWith('/onboarding/intake/answers/') &&
        request.method == 'PUT') {
      if (intakeStatus == 'confirmed') {
        return const FakeResponse(409, <String, dynamic>{
          'detail':
              'This intake is already confirmed and can no longer be edited.'
        });
      }
      if (!intakeDisclosureAcknowledged) {
        return const FakeResponse(403, <String, dynamic>{
          'detail':
              'Acknowledge the hosted-processing disclosure before saving onboarding answers.'
        });
      }
      final String field = Uri.decodeComponent(
          path.substring('/onboarding/intake/answers/'.length));
      final Object? value = request.body['value'];
      if (intakeRejectField == field) {
        intakeRejectField = null;
        return FakeResponse(
            400, <String, dynamic>{'detail': intakeRejectMessage});
      }
      final String? error = _validateIntakeAnswer(field, value);
      if (error != null) {
        return FakeResponse(400, <String, dynamic>{'detail': error});
      }
      final bool lowercased = field == 'gender' ||
          field == 'proportions' ||
          field == 'rep_preference';
      intakeAnswers[field] =
          value is String && lowercased ? value.toLowerCase() : value;
      return FakeResponse(200, _intakeView());
    }
    return const FakeResponse(404, <String, dynamic>{'detail': 'Not found.'});
  }

  Map<String, dynamic> _activeProgramBody() => <String, dynamic>{
        'program_name': _profileProgramRevision == 0
            ? 'Upper/Lower 4x'
            : 'Rebuilt program $_profileProgramRevision',
        'split_type': 'Upper/Lower',
        'weekly_frequency': 4,
        'instructions': '',
        'days': programDaysOverride ??
            <Map<String, dynamic>>[
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
                    'suggested_substitutes': <Map<String, String>>[
                      <String, String>{
                        'exercise_id': 'incline_db_press',
                        'exercise_name': 'Incline DB Press',
                      },
                    ],
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
              if (repeatBenchPressOnOtherDays)
                for (int order = 2; order <= 3; order++)
                  <String, dynamic>{
                    'day_name': 'Upper $order',
                    'day_order': order,
                    'warmup_exercises': <Map<String, dynamic>>[],
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
                  },
            ],
        if (programVersion != null) 'version': programVersion,
        if (programPublishedByCoachAccountId != null)
          'published_by_coach_account_id': programPublishedByCoachAccountId,
        'player_controls_program': !coachControlsProgram,
      };

  FakeResponse _activeProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (activeProgramFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    if (noActiveProgram) {
      return const FakeResponse(200);
    }
    return FakeResponse(200, _activeProgramBody());
  }

  FakeResponse _substituteActiveProgram(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (coachControlsProgram) {
      return const FakeResponse(403, <String, dynamic>{
        'detail':
            'Your assigned coach controls your program. Ask your coach for changes.',
        'code': 'coach_controlled',
      });
    }
    if (substitutionVersionConflict) {
      return const FakeResponse(409, <String, dynamic>{
        'detail': 'The active program version changed.',
        'code': 'program_version_conflict',
      });
    }
    final Map<String, dynamic> payload =
        Map<String, dynamic>.from(request.body);
    programSubstitutionRequests.add(payload);
    final int previousVersion = programVersion ?? 1;
    final List<Map<String, dynamic>> priorDays =
        List<Map<String, dynamic>>.from(
      (programDaysOverride ??
              _activeProgramBody()['days'] as List<Map<String, dynamic>>)
          .map((Map<String, dynamic> day) => Map<String, dynamic>.from(
                jsonDecode(jsonEncode(day)) as Map<String, dynamic>,
              )),
    );
    _programDaysByVersion[previousVersion] = priorDays;
    final String dayName = '${payload['day_name'] ?? ''}';
    final String sourceId = '${payload['exercise_id'] ?? ''}';
    final String replacementId = '${payload['replacement_exercise_id'] ?? ''}';
    final bool allOccurrences = payload['all_occurrences'] == true;
    final Map<String, String> names = <String, String>{
      'bench_press': 'Bench Press',
      'cable_fly': 'Cable Fly',
    };
    final List<Map<String, dynamic>> days = programDaysOverride ??
        List<Map<String, dynamic>>.from(
          (_activeProgramBody()['days'] as List<dynamic>).map(
            (dynamic day) => Map<String, dynamic>.from(
              jsonDecode(jsonEncode(day)) as Map<String, dynamic>,
            ),
          ),
        );
    programDaysOverride = days;
    for (final Map<String, dynamic> day in days) {
      if (!allOccurrences && day['day_name'] != dayName) continue;
      for (final dynamic rawExercise in day['exercises'] as List<dynamic>) {
        final Map<String, dynamic> exercise =
            rawExercise as Map<String, dynamic>;
        if (exercise['exercise_id'] != sourceId) continue;
        exercise['exercise_id'] = replacementId;
        exercise['exercise_name'] = names[replacementId] ?? replacementId;
        exercise['notes'] = replacementId == 'cable_fly'
            ? 'Bring the handles together.'
            : 'Pause on the chest.';
        exercise['image_path'] = 'images/$replacementId.jpg';
        if (!allOccurrences) break;
      }
    }
    programVersion = previousVersion + 1;
    return FakeResponse(200, <String, dynamic>{
      ..._activeProgramBody(),
      'previous_version': previousVersion,
    });
  }

  FakeResponse _undoActiveProgramSubstitution(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final Map<String, dynamic> payload =
        Map<String, dynamic>.from(request.body);
    programSubstitutionUndoRequests.add(payload);
    final int previousVersion = programVersion ?? 1;
    final int restoreVersion = (payload['restore_version'] as num).toInt();
    final List<Map<String, dynamic>>? restore =
        _programDaysByVersion[restoreVersion];
    if (restore == null) {
      return const FakeResponse(
          404, <String, dynamic>{'detail': 'No active program.'});
    }
    _programDaysByVersion[previousVersion] = List<Map<String, dynamic>>.from(
      (programDaysOverride ?? <Map<String, dynamic>>[]).map(
        (Map<String, dynamic> day) => Map<String, dynamic>.from(
          jsonDecode(jsonEncode(day)) as Map<String, dynamic>,
        ),
      ),
    );
    programDaysOverride = List<Map<String, dynamic>>.from(
      restore.map((Map<String, dynamic> day) => Map<String, dynamic>.from(
          jsonDecode(jsonEncode(day)) as Map<String, dynamic>)),
    );
    programVersion = previousVersion + 1;
    return FakeResponse(200, <String, dynamic>{
      ..._activeProgramBody(),
      'previous_version': previousVersion,
    });
  }

  /// `GET /workouts/baselines` (#122/#123): the player's per-exercise
  /// baselines, with the fail modes the client's fallback must survive.
  FakeResponse _baselines(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    baselinesRequests++;
    if (baselinesFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    if (baselinesMalformed) {
      return const FakeResponse(
          200, <String, dynamic>{'baselines': 'not-a-list'});
    }
    return FakeResponse(200, <String, dynamic>{
      'baselines': <Map<String, dynamic>>[
        for (final Map<String, dynamic> row in baselinesBody)
          Map<String, dynamic>.from(row),
      ],
    });
  }

  FakeResponse _prescription(FakeRequest request) {
    if (prescriptionOffline) return const FakeResponse.networkFailure();
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final int dayOrder = int.tryParse('${request.query['day_order']}') ?? 1;
    final List<dynamic> days = _activeProgramBody()['days'] as List<dynamic>;
    final Map<String, dynamic> day = days.firstWhere(
      (dynamic entry) =>
          (entry as Map<String, dynamic>)['day_order'] == dayOrder,
      orElse: () => days.first as Map<String, dynamic>,
    ) as Map<String, dynamic>;
    final List<dynamic> exercises = day['exercises'] as List<dynamic>;
    return FakeResponse(200, <String, dynamic>{
      'fatigue_info': <String, dynamic>{
        'deload_recommended': false,
        'severity': 'NORMAL',
        'volume_multiplier': 1.0,
        'intensity_cap_rpe': null,
        'recent_readiness_avg': null,
      },
      'deload': Map<String, dynamic>.from(prescriptionDeload),
      'targets': <Map<String, dynamic>>[
        for (final dynamic entry in exercises)
          <String, dynamic>{
            'exercise_id': (entry as Map<String, dynamic>)['exercise_id'],
            'exercise_name': entry['exercise_name'],
            'is_barbell': (entry['exercise_name'] as String)
                .toLowerCase()
                .contains('barbell'),
            'effective_sets': entry['target_sets'],
            'target_rpe_cap': prescriptionTargetRpe[entry['exercise_id']] ??
                (entry['target_rpe'] as num).toDouble(),
            'projected_weight': 60.0,
            'last_perf': <dynamic>[],
          },
      ],
    });
  }

  FakeResponse _searchExercises(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String query = '${request.query['query'] ?? ''}'.trim().toLowerCase();
    // `target_muscle` mirrors the real `find_exercises_by_name` row, so the
    // Replace exercise pre-filter can be tested against it (#162).
    const List<Map<String, dynamic>> catalog = <Map<String, dynamic>>[
      <String, dynamic>{
        'id': 'bicep_curl',
        'name': 'Bicep Curl',
        'equipment': 'dumbbell',
        'target_muscle': 'Biceps',
        'body_part': 'Upper Arms',
        'image_path': 'images/bicep_curl.jpg',
      },
      <String, dynamic>{
        'id': 'cable_fly',
        'name': 'Cable Fly',
        'equipment': 'cable',
        'target_muscle': 'Chest',
        'body_part': 'Chest',
        'image_path': 'images/cable_fly.jpg',
      },
      <String, dynamic>{
        'id': 'bench_press',
        'name': 'Bench Press',
        'equipment': 'barbell',
        'target_muscle': 'Chest',
        'body_part': 'Chest',
        'image_path': 'images/bench_press.jpg',
      },
    ];
    // Mirrors the real endpoint (#162): a name query, a muscle, or both —
    // never an unfiltered dump, and the muscle listing needs no query.
    final String muscle =
        '${request.query['target_muscle'] ?? ''}'.trim().toLowerCase();
    if (query.isEmpty && muscle.isEmpty) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'Provide query, target_muscle, or both.'
      });
    }
    bool matchesMuscle(Map<String, dynamic> entry) =>
        muscle.isEmpty ||
        '${entry['target_muscle'] ?? ''}'.trim().toLowerCase() == muscle;
    final List<Map<String, dynamic>> matches = query.isEmpty
        ? catalog.where(matchesMuscle).toList(growable: false)
        : catalog
            .where((Map<String, dynamic> entry) =>
                (entry['name'] as String).toLowerCase().contains(query) &&
                matchesMuscle(entry))
            .toList(growable: false);
    // The real SQL orders the LIKE tier by name length (#162's muscle list).
    matches.sort((Map<String, dynamic> a, Map<String, dynamic> b) =>
        (a['name'] as String).length.compareTo((b['name'] as String).length));
    return FakeResponse(200, <String, dynamic>{
      'exercises': List<Map<String, dynamic>>.from(matches)
    });
  }

  /// ExerciseDB-derived catalog detail for `GET /workouts/exercises/{id}`.
  static const Map<String, Map<String, dynamic>> _exerciseDetails =
      <String, Map<String, dynamic>>{
    'bench_press': <String, dynamic>{
      'id': 'bench_press',
      'name': 'Bench Press',
      'category': 'Chest',
      'body_part': 'Chest',
      'equipment': 'barbell',
      'primary_muscles': <String>['Chest'],
      'secondary_muscles': <String>['Triceps', 'Shoulders'],
      'instructions': 'Lie on a flat bench with your feet on the floor.\n'
          'Grip the bar slightly wider than shoulder width.\n'
          'Lower the bar to your chest, then press it back up.',
      'image_path': 'images/bench_press.jpg',
      'gif_path': 'videos/bench_press.gif',
    },
    'overhead_press': <String, dynamic>{
      'id': 'overhead_press',
      'name': 'Overhead Press',
      'category': 'Shoulders',
      'body_part': 'Shoulders',
      'equipment': 'barbell',
      'primary_muscles': <String>['Shoulders'],
      'secondary_muscles': <String>['Triceps'],
      'instructions': 'Press the bar overhead from shoulder height.',
      'image_path': 'images/overhead_press.jpg',
      'gif_path': 'videos/overhead_press.gif',
    },
    'barbell_row': <String, dynamic>{
      'id': 'barbell_row',
      'name': 'Barbell Row',
      'category': 'Back',
      'body_part': 'Back',
      'equipment': 'barbell',
      'primary_muscles': <String>['Back'],
      'secondary_muscles': <String>['Biceps'],
      'instructions': 'Hinge at the hips and row the bar to your torso.',
      'image_path': 'images/barbell_row.jpg',
      'gif_path': 'videos/barbell_row.gif',
    },
    'lat_pulldown': <String, dynamic>{
      'id': 'lat_pulldown',
      'name': 'Lat Pulldown',
      'category': 'Back',
      'body_part': 'Back',
      'equipment': 'cable',
      'primary_muscles': <String>['Back'],
      'secondary_muscles': <String>['Biceps'],
      'instructions': 'Pull the bar down to your upper chest.',
      'image_path': 'images/lat_pulldown.jpg',
      'gif_path': 'videos/lat_pulldown.gif',
    },
    'band_pull_apart': <String, dynamic>{
      'id': 'band_pull_apart',
      'name': 'Band Pull-Apart',
      'category': 'Shoulders',
      'body_part': 'Shoulders',
      'equipment': 'band',
      'primary_muscles': <String>['Shoulders'],
      'secondary_muscles': <String>['Upper Back'],
      'instructions': 'Hold a band in front and pull the ends apart.',
      'image_path': 'images/band_pull_apart.jpg',
      'gif_path': 'videos/band_pull_apart.gif',
    },
    'bicep_curl': <String, dynamic>{
      'id': 'bicep_curl',
      'name': 'Bicep Curl',
      'category': 'Upper Arms',
      'body_part': 'Upper Arms',
      'equipment': 'dumbbell',
      'primary_muscles': <String>['Biceps'],
      'secondary_muscles': <String>[],
      'instructions': 'Curl the weight up and lower it under control.',
      'image_path': 'images/bicep_curl.jpg',
      'gif_path': 'videos/bicep_curl.gif',
    },
    'cable_fly': <String, dynamic>{
      'id': 'cable_fly',
      'name': 'Cable Fly',
      'category': 'Chest',
      'body_part': 'Chest',
      'equipment': 'cable',
      'primary_muscles': <String>['Chest'],
      'secondary_muscles': <String>[],
      'instructions': 'Bring the cable handles together in front of you.',
      'image_path': 'images/cable_fly.jpg',
      'gif_path': 'videos/cable_fly.gif',
    },
    'machine_row': <String, dynamic>{
      'id': 'machine_row',
      'name': 'Machine Row',
      'category': 'Back',
      'body_part': 'Back',
      'equipment': 'machine',
      'primary_muscles': <String>['Back'],
      'secondary_muscles': <String>[],
      'instructions': '',
      'image_path': 'images/machine_row.jpg',
      'gif_path': 'videos/machine_row.gif',
    },
  };

  FakeResponse _exerciseDetail(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String id = request.path.replaceFirst('/workouts/exercises/', '');
    final Map<String, dynamic>? detail = _exerciseDetails[id];
    if (detail == null) {
      return const FakeResponse(
          404, <String, dynamic>{'detail': 'Unknown exercise id.'});
    }
    return FakeResponse(200, detail);
  }

  /// `GET /dashboard/exercises`: the exercises the player has logged.
  FakeResponse _loggedExercises(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (loggedExercisesFails) {
      return const FakeResponse.networkFailure();
    }
    return FakeResponse(200, List<Map<String, dynamic>>.from(loggedExercises));
  }

  /// `GET /dashboard/exercises/{id}/history`: progression points from the
  /// configurable [dashboardExerciseHistories]; unknown ids return empty.
  FakeResponse _dashboardExerciseHistory(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String id = request.path
        .replaceFirst('/dashboard/exercises/', '')
        .replaceFirst('/history', '');
    final Map<String, dynamic>? history = dashboardExerciseHistories[id];
    if (history != null) {
      return FakeResponse(200, history);
    }
    return FakeResponse(200, <String, dynamic>{
      'history': <dynamic>[],
      'caption': null,
      'records': <dynamic>[],
    });
  }

  static List<Map<String, dynamic>> _defaultLoggedExercises() =>
      <Map<String, dynamic>>[
        <String, dynamic>{'id': 'bench_press', 'name': 'Bench Press'},
        <String, dynamic>{'id': 'overhead_press', 'name': 'Overhead Press'},
      ];

  /// One real progression point for Bench Press by default, so the
  /// exercise-detail History tab still renders; other ids have no history.
  static Map<String, Map<String, dynamic>> _defaultDashboardHistories() =>
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
          'caption': 'Latest Recorded: **100.0 kg × 5 reps @ RIR 2**',
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

  FakeResponse _commitSession(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    commitRequests++;
    if (commitFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    final int? refusalStatus = commitRefusalStatusCode;
    if (refusalStatus != null) {
      final String? errorCode = commitRefusalErrorCode;
      return FakeResponse(
        refusalStatus,
        errorCode == null
            ? <String, dynamic>{'detail': commitRefusalMessage}
            : <String, dynamic>{'error': errorCode},
      );
    }
    final Map<String, dynamic> body = request.body;
    final String? clientId = body['client_session_id'] as String?;
    if (clientId != null) {
      final Map<String, dynamic>? stored = sessionCommits[clientId];
      if (stored != null) {
        return FakeResponse(200, stored);
      }
      // ADR 034: a captured version at or below the active one (and present in
      // the ledger, emulated as >= 1) is accepted; a newer or unknown version
      // is refused.
      final int requested = (body['program_version'] as num?)?.toInt() ?? -1;
      final int active = programVersion ?? 0;
      if (requested < 1 || requested > active) {
        return FakeResponse(409, <String, dynamic>{
          'error': 'program_version_mismatch',
          'active_version': active,
        });
      }
    }
    final Map<String, dynamic> session = _sessionResponse(body);
    if (clientId != null) {
      sessionCommits[clientId] = session;
      committedSessions.add(session);
      if (commitResponseLost) return const FakeResponse.networkFailure();
    }
    return FakeResponse(201, session);
  }

  Map<String, dynamic> _sessionResponse(Map<String, dynamic> body) {
    final List<dynamic> sets =
        body['sets'] as List<dynamic>? ?? const <dynamic>[];
    int working = 0;
    for (final dynamic entry in sets) {
      working +=
          ((entry as Map<String, dynamic>)['sets'] as List<dynamic>).length;
    }
    final int requested = (body['program_version'] as num?)?.toInt() ?? 0;
    final int active = programVersion ?? 0;
    _sessionSeq++;
    return <String, dynamic>{
      'session_id': 'session-$_sessionSeq',
      'session_date': body['performed_date'],
      'total_tonnage_kg': 1000.0,
      'total_working_sets': working,
      'exercise_summaries': <dynamic>[],
      'debrief': 'Great work!',
      'pointer': 'Session logged.',
      'fatigue_post': <String, dynamic>{'deload_recommended': false},
      'new_prs': <dynamic>[],
      'divergences': <dynamic>[],
      'warmup_movements': body['warmup_movements'] ?? <dynamic>[],
      'program_version': requested,
      'active_program_version_at_sync': active,
      'is_historical_program': requested > 0 && requested < active,
      if (trainingStatusBody != null) 'training_status': trainingStatusBody,
      if (checkpointOnCommit != null) 'checkpoint': checkpointOnCommit,
    };
  }

  FakeResponse _trainingStatus(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    trainingStatusRequests++;
    if (trainingStatusFails || trainingStatusBody == null) {
      return const FakeResponse(
          503, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    return FakeResponse(200, trainingStatusBody!);
  }

  /// `GET /workouts/sessions/latest` (#53): the most recent committed session,
  /// or 404 when [latestSessionBody] is null.
  FakeResponse _latestSession(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (latestSessionFails) {
      return const FakeResponse(
          503, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    final Map<String, dynamic>? body = latestSessionBody;
    if (body == null) {
      return const FakeResponse(
          404, <String, dynamic>{'detail': 'No committed sessions.'});
    }
    return FakeResponse(200, body);
  }

  FakeResponse _sessionByClientId(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final String id =
        request.path.replaceFirst('/workouts/sessions/by-client-id/', '');
    final Map<String, dynamic>? stored = sessionCommits[id];
    if (stored == null) {
      return const FakeResponse(404, <String, dynamic>{
        'detail': 'No committed session for this client session id.'
      });
    }
    final Map<String, dynamic>? correction =
        correctedSessions[stored['session_id']];
    if (correction == null) {
      return FakeResponse(200, stored);
    }
    return FakeResponse(200, <String, dynamic>{
      ...stored,
      'session_date': correction['session_date'],
      'edited_at': correction['edited_at'],
      'performed_date_corrections': correction['corrections'],
    });
  }

  FakeResponse _correctPerformedDate(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (commitFails) {
      return const FakeResponse(
          500, <String, dynamic>{'detail': 'The service is unavailable.'});
    }
    if (correctionRefused) {
      return const FakeResponse(409, <String, dynamic>{
        'detail':
            'A performed date can be corrected only within 3 days of the workout.'
      });
    }
    final String id = request.path
        .replaceFirst('/workouts/sessions/', '')
        .replaceFirst('/performed-date', '');
    Map<String, dynamic>? session;
    for (final Map<String, dynamic> row in committedSessions) {
      if (row['session_id'] == id) {
        session = row;
        break;
      }
    }
    final String? performed = request.body['performed_date'] as String?;
    if (session == null) {
      return const FakeResponse(
          404, <String, dynamic>{'detail': 'No such session.'});
    }
    if (performed == null ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(performed)) {
      return const FakeResponse(400, <String, dynamic>{
        'detail': 'performed_date must be an ISO date (YYYY-MM-DD).'
      });
    }
    final String previous = session['session_date'] as String? ?? performed;
    final bool changed = previous != performed;
    final String? editedAt = changed
        ? (session['edited_at'] as String? ?? '2026-09-26T12:00:00Z')
        : session['edited_at'] as String?;
    final List<dynamic> corrections = changed
        ? <dynamic>[
            ...(correctedSessions[id]?['corrections'] as List<dynamic>? ??
                const <dynamic>[]),
            <String, dynamic>{
              'previous_date': previous,
              'corrected_date': performed,
              'corrected_at': editedAt,
            },
          ]
        : <dynamic>[];
    session['session_date'] = performed;
    session['edited_at'] = editedAt;
    final Map<String, dynamic> result = <String, dynamic>{
      'session_id': id,
      'session_date': performed,
      'previous_date': previous,
      'edited_at': editedAt,
      'changed': changed,
      'corrections': corrections,
    };
    correctedSessions[id] = result;
    return FakeResponse(200, result);
  }

  FakeResponse _checkpointReview(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    if (request.path == '/checkpoint-reviews') {
      return FakeResponse(
          200, List<Map<String, dynamic>>.from(checkpointReviewRows));
    }
    final int? checkpoint = int.tryParse(request.path.split('/').last);
    final Map<String, dynamic>? review =
        checkpoint == null ? null : checkpointReviewDetails[checkpoint];
    if (review == null) {
      return const FakeResponse(404, <String, dynamic>{'detail': 'Not found.'});
    }
    for (final Map<String, dynamic> row in checkpointReviewRows) {
      if (row['checkpoint'] == checkpoint) row['opened'] = true;
    }
    return FakeResponse(200, review);
  }

  FakeResponse _volume(FakeRequest request) {
    if (!_authorized(request)) {
      return const FakeResponse(
          401, <String, dynamic>{'detail': 'Token has been revoked.'});
    }
    final int days = int.tryParse('${request.query['days']}') ?? 7;
    volumeDaysRequests.add(days);
    if (volumeEmpty) {
      return const FakeResponse(200, <String, dynamic>{});
    }
    final Map<String, dynamic>? byDays = volumeByDays?[days];
    if (byDays != null) {
      return FakeResponse(200, byDays);
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
    if (recordsEmpty) {
      return const FakeResponse(200, <Map<String, dynamic>>[]);
    }
    if (personalRecordsBody != null) {
      return FakeResponse(200, personalRecordsBody!);
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
    accountDeleted = false;
    if (fresh) {
      coach = false;
      lifterPlan = 'free';
      coachPlan = 'free';
      profileExists = false;
      recoveryEmail = null;
      repPreference = 'balanced';
      weeklyFrequency = 4;
      equipmentAccess = equipmentAccessCommercialGym;
      currentGoal = 'Get stronger';
      injuriesOrLimitations = 'None';
      weightKg = 75;
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
      coachAlerts.clear();
      checkIns.clear();
      _checkInSeq = 0;
      _publishedVersion = 0;
      programVersion = null;
      programPublishedByCoachAccountId = null;
      activeProgramFails = false;
      coachControlsProgram = false;
      noActiveProgram = false;
      volumeEmpty = false;
      recordsEmpty = false;
      checkpointReviewRows = <Map<String, dynamic>>[];
      checkpointReviewDetails.clear();
      loggedExercises = _defaultLoggedExercises();
      loggedExercisesFails = false;
      dashboardExerciseHistories = _defaultDashboardHistories();
      volumeDaysRequests.clear();
      volumeByDays = null;
      latestSessionBody = null;
      latestSessionFails = false;
      playerNotices.clear();
      programRequests.clear();
      staleProgramRequest = false;
      _programRequestSeq = 0;
      scheduleVersions = _defaultScheduleVersions();
      trainingPauses = _defaultTrainingPauses();
      _scheduleSeq = 0;
      _pauseSeq = 0;
      scheduleEmpty = false;
      coachHistoryDenied = false;
      coachPlayerSummary = _defaultCoachSummary();
      coachPlayerRecords = _defaultCoachRecords();
      coachPlayerExercises = _defaultCoachExercises();
      coachPlayerHistories = _defaultCoachHistories();
      _answeredSteps = 0;
      _assistantMessages = <String>[];
      _onboardingComplete = false;
      nullOnboardingProgram = false;
      intakeDisclosureAcknowledged = false;
      intakeStatus = 'in_progress';
      intakeAnswers = <String, Object?>{};
      intakeProgram = null;
      committedSessions.clear();
      sessionCommits.clear();
      commitRequests = 0;
      commitFails = false;
      commitResponseLost = false;
      checkpointOnCommit = null;
      commitRefusalStatusCode = null;
      commitRefusalMessage = 'The workout could not be recorded.';
      commitRefusalErrorCode = null;
      correctionRefused = false;
      correctedSessions.clear();
      _sessionSeq = 0;
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
