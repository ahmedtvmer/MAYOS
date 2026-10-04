import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'app_failure.dart';
import 'baselines.dart';
import 'chat_models.dart';
import 'models.dart';
import 'sse.dart';
import 'token_store.dart';

/// Raised for any failed service call, carrying the HTTP status when there was
/// a response and a human-readable message from the service `detail` field.
class ApiException implements Exception {
  const ApiException(
    this.message, {
    this.statusCode,
    this.errorCode,
    this.failureMessage,
  });

  final String message;
  final int? statusCode;

  /// A machine-readable `error` code from the service, when it sent one.
  final String? errorCode;

  /// Keeps app failures typed and server `detail` values explicitly raw.
  final FailureMessage? failureMessage;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// The result of `POST /workouts/sessions`, carrying whether this call created
/// the session (201) or replayed an already-committed one (200).
class WorkoutCommitResult {
  const WorkoutCommitResult({required this.statusCode, required this.body});

  final int statusCode;
  final Map<String, dynamic> body;

  bool get created => statusCode == 201;
}

/// What `POST /auth/google` answered for one ID token (#113/#174).
sealed class GoogleAuthStart {
  const GoogleAuthStart();
}

/// The Google subject is already linked to a live account: here is its session.
final class GoogleAuthSession extends GoogleAuthStart {
  const GoogleAuthSession(this.tokens);

  final AuthTokens tokens;
}

/// First sign-in: no account exists yet, so the service hands back a short-lived
/// ticket, a username guess, and an optional recovery-email nudge.
final class GoogleAuthSignupTicket extends GoogleAuthStart {
  const GoogleAuthSignupTicket({
    required this.signupTicket,
    required this.suggestedUsername,
    required this.idToken,
    this.existingAccountHint = false,
  });

  final String signupTicket;
  final String suggestedUsername;
  final String idToken;

  /// True when a verified Google email matched a live recovery email (#174).
  final bool existingAccountHint;
}

/// Thin typed wrapper over the FastAPI service.
///
/// Every request except register/login/logout carries the persisted bearer
/// token. A 401 on an authenticated request invokes [onUnauthorized] so the app
/// can clear the session and route back to login.
class ApiClient {
  ApiClient({
    required TokenStore tokens,
    required String baseUrl,
    HttpClientAdapter? adapter,
  }) : _tokens = tokens {
    _dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
      ),
    );
    _dio.httpClientAdapter = adapter ?? _dio.httpClientAdapter;
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: _attachToken,
        onError: _handleError,
      ),
    );
  }

  static const String _skipAuth = 'skipAuth';
  static const String _invalidCoachHistory =
      'The service returned invalid coach history data.';
  static const String _invalidAlerts =
      'The service returned invalid alert data.';
  static const String _invalidCheckIns =
      'The service returned invalid check-in data.';
  static const String _invalidCheckpointReview =
      'The service returned invalid checkpoint review data.';
  static const String _invalidProgram =
      'The service returned invalid program data.';
  static const String _invalidNotices =
      'The service returned invalid assignment notices.';
  static const String _invalidProgramRequests =
      'The service returned invalid program request data.';
  static const String _invalidProfile =
      'The service returned invalid profile data.';
  static const String _invalidSchedule =
      'The service returned invalid training schedule data.';
  static const String _invalidChat = 'The service returned invalid chat data.';
  static const String _invalidBaselines =
      'The service returned invalid baseline data.';
  static const String _invalidTrainingStatus =
      'The service returned invalid training status data.';
  static const AppFailureMessage _invalidCheckInsFailure = AppFailureMessage(
    AppFailureId.invalidCheckInData,
    _invalidCheckIns,
  );
  static const AppFailureMessage _invalidNoticesFailure = AppFailureMessage(
    AppFailureId.invalidAssignmentNotices,
    _invalidNotices,
  );
  static const AppFailureMessage _invalidProgramRequestsFailure =
      AppFailureMessage(
    AppFailureId.invalidProgramRequestData,
    _invalidProgramRequests,
  );
  static const AppFailureMessage _invalidProfileFailure = AppFailureMessage(
    AppFailureId.invalidProfileData,
    _invalidProfile,
  );
  static const AppFailureMessage _invalidScheduleFailure = AppFailureMessage(
    AppFailureId.invalidTrainingScheduleData,
    _invalidSchedule,
  );

  static AppFailureMessage _invalidServiceDataFailure(String message) =>
      AppFailureMessage(AppFailureId.invalidServiceData, message);

  final TokenStore _tokens;
  late final Dio _dio;

  /// Invoked when an authenticated request fails with 401.
  void Function()? onUnauthorized;

  /// Invoked when an authenticated request fails with 401 carrying the
  /// `account_deleted` signal, so the app can erase that account's protected
  /// local data without the logout keep/discard prompt (ADR 039).
  void Function()? onAccountDeleted;

  Dio get dio => _dio;

  Future<void> _attachToken(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (options.extra[_skipAuth] != true) {
      final String? token = await _tokens.read();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }

  void _handleError(DioException error, ErrorInterceptorHandler handler) {
    final bool skipped = error.requestOptions.extra[_skipAuth] == true;
    if (!skipped && error.response?.statusCode == 401) {
      final dynamic data = error.response?.data;
      if (data is Map && data['error'] == 'account_deleted') {
        onAccountDeleted?.call();
      } else {
        onUnauthorized?.call();
      }
    }
    handler.next(error);
  }

  Future<Response<dynamic>> _send(
      Future<Response<dynamic>> Function() run) async {
    try {
      return await run();
    } on DioException catch (error) {
      throw _toApiException(error);
    }
  }

  static ApiException _toApiException(DioException error) {
    final int? status = error.response?.statusCode;
    final dynamic data = error.response?.data;
    if (data is Map) {
      final Map<String, dynamic> body = Map<String, dynamic>.from(data);
      if (body['detail'] is String) {
        final String detail = body['detail'] as String;
        return ApiException(
          detail,
          statusCode: status,
          errorCode: _machineCode(body),
          failureMessage: ServerFailureMessage(detail),
        );
      }
      if (body['error'] is String) {
        final String code = body['error'] as String;
        final String message = _messageForError(code);
        return ApiException(
          message,
          statusCode: status,
          errorCode: code,
          failureMessage: AppFailureMessage(
            code == 'program_version_mismatch'
                ? AppFailureId.programVersionMismatch
                : AppFailureId.serviceRejected,
            message,
          ),
        );
      }
    }
    if (status == null) {
      return const ApiException(
        'Cannot reach the service. Check your connection.',
        failureMessage: AppFailureMessage(
          AppFailureId.cannotReachService,
          'Cannot reach the service. Check your connection.',
        ),
      );
    }
    if (status >= 500) {
      return ApiException('The service is unavailable. Please retry.',
          statusCode: status,
          failureMessage: const AppFailureMessage(
            AppFailureId.serviceUnavailable,
            'The service is unavailable. Please retry.',
          ));
    }
    return ApiException(
      'Request failed ($status).',
      statusCode: status,
      failureMessage: AppFailureMessage(
        AppFailureId.requestFailed,
        'Request failed ($status).',
        value: status,
      ),
    );
  }

  /// The machine-readable code from a service error body, whether it arrives as
  /// `error` (for example `account_deleted`) or alongside a `detail` as `code`.
  static String? _machineCode(Map<String, dynamic> body) {
    final dynamic error = body['error'];
    if (error is String) {
      return error;
    }
    final dynamic code = body['code'];
    return code is String ? code : null;
  }

  static String _messageForError(String code) => switch (code) {
        'program_version_mismatch' =>
          'This workout was logged against an older program version.',
        _ => 'The service rejected this request.',
      };

  Future<AuthTokens> register({
    required String traineeId,
    required String password,
    bool rememberMe = false,
    String? coachInviteCode,
    String displayLanguage = 'en',
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/register',
        data: {
          'trainee_id': traineeId,
          'password': password,
          'remember_me': rememberMe,
          if (coachInviteCode != null) 'coach_invite_code': coachInviteCode,
          'display_language': displayLanguage,
        },
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    return AuthTokens.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AuthTokens> login({
    required String traineeId,
    required String password,
    bool rememberMe = false,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/login',
        data: {
          'trainee_id': traineeId,
          'password': password,
          'remember_me': rememberMe,
        },
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    return AuthTokens.fromJson(response.data as Map<String, dynamic>);
  }

  Future<Account> currentAccount() async {
    final response = await _send(() => _dio.get<dynamic>('/auth/me'));
    return _parseAccount(response.data);
  }

  /// The `POST /auth/google` answer (#113/#115): a session when the Google
  /// subject is already linked, otherwise the ticket that opens the picker.
  Future<GoogleAuthStart> googleSignIn({required String idToken}) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/google',
        data: <String, dynamic>{'id_token': idToken},
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      const String message =
          'The service returned an invalid Google sign-in answer.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    final dynamic ticket = data['signup_ticket'];
    if (ticket is String) {
      return GoogleAuthSignupTicket(
        signupTicket: ticket,
        idToken: idToken,
        suggestedUsername: data['suggested_username'] is String
            ? data['suggested_username'] as String
            : '',
        existingAccountHint: data['existing_account_hint'] == true,
      );
    }
    return GoogleAuthSession(AuthTokens.fromJson(data));
  }

  /// `GET /auth/username-available` for the picker (#113): the signup ticket
  /// travels as the bearer so the device's own session token is never sent.
  Future<bool> usernameAvailable(
    String username, {
    required String ticket,
  }) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/auth/username-available',
        queryParameters: <String, dynamic>{'username': username},
        options: Options(
          extra: {_skipAuth: true},
          headers: <String, dynamic>{'Authorization': 'Bearer $ticket'},
        ),
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      const String message = 'The service returned an invalid username answer.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    return data['available'] == true;
  }

  /// `POST /auth/google/complete`: creates the account and its Google link in
  /// one transaction (#113). 409 when the username is taken, 401 when the
  /// signup ticket expired.
  Future<AuthTokens> googleComplete({
    required String signupTicket,
    required String username,
    required String idToken,
    String displayLanguage = 'en',
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/google/complete',
        data: <String, dynamic>{
          'signup_ticket': signupTicket,
          'username': username,
          'id_token': idToken,
          'display_language': displayLanguage,
        },
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    return AuthTokens.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> updateDisplayLanguage(String language) async {
    await _send(() => _dio.put<dynamic>(
          '/auth/display-language',
          data: <String, dynamic>{'display_language': language},
        ));
  }

  /// Redeems a single-use Coach invite from MAYOS and returns the updated account.
  Future<Account> redeemCoachInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>('/coach/invite/redeem', data: {'token': token}),
    );
    return _parseAccount(response.data);
  }

  Account _parseAccount(dynamic responseData) => _parseBody(
        responseData,
        Account.fromJson,
        'The service returned invalid account status.',
      );

  T _parseBody<T>(
    dynamic responseData,
    T Function(Map<String, dynamic>) parse,
    String invalidMessage, {
    AppFailureMessage? failureMessage,
  }) {
    final AppFailureMessage failure =
        failureMessage ?? _invalidServiceDataFailure(invalidMessage);
    if (responseData is! Map<String, dynamic>) {
      throw ApiException(invalidMessage, failureMessage: failure);
    }
    try {
      return parse(responseData);
    } on FormatException {
      throw ApiException(invalidMessage, failureMessage: failure);
    } on TypeError {
      throw ApiException(invalidMessage, failureMessage: failure);
    }
  }

  List<T> _parseBodyList<T>(
    dynamic responseData,
    T Function(Map<String, dynamic>) parse,
    String invalidMessage, {
    AppFailureMessage? failureMessage,
  }) {
    final AppFailureMessage failure =
        failureMessage ?? _invalidServiceDataFailure(invalidMessage);
    if (responseData is! List<dynamic>) {
      throw ApiException(invalidMessage, failureMessage: failure);
    }
    try {
      return responseData.map((dynamic item) {
        if (item is! Map<String, dynamic>) {
          throw const FormatException('Invalid entry.');
        }
        return parse(item);
      }).toList(growable: false);
    } on FormatException {
      throw ApiException(invalidMessage, failureMessage: failure);
    } on TypeError {
      throw ApiException(invalidMessage, failureMessage: failure);
    }
  }

  /// The authenticated coach's profile.
  Future<CoachProfile> coachProfile() async {
    final response = await _send(() => _dio.get<dynamic>('/coach/profile'));
    return CoachProfile.fromJson(response.data as Map<String, dynamic>);
  }

  /// Updates and returns the authenticated coach's profile.
  Future<CoachProfile> updateCoachProfile({
    required String displayName,
    required String bio,
    required String specialization,
    required int capacity,
  }) async {
    final response = await _send(
      () => _dio.put<dynamic>('/coach/profile', data: {
        'display_name': displayName,
        'bio': bio,
        'specialization': specialization,
        'capacity': capacity,
      }),
    );
    return CoachProfile.fromJson(response.data as Map<String, dynamic>);
  }

  /// Previews a coach assignment invite. The code is sent in the body and is not consumed.
  Future<AssignmentInvitePreview> previewAssignmentInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/assignments/invites/preview',
        data: {'token': token},
      ),
    );
    return AssignmentInvitePreview.fromJson(
        response.data as Map<String, dynamic>);
  }

  /// Explicitly consents to and redeems a single-use assignment invite.
  Future<Assignment> redeemAssignmentInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/assignments/invites/redeem',
        data: {'token': token, 'consent': true},
      ),
    );
    final Map<String, dynamic> body = response.data as Map<String, dynamic>;
    return Assignment.fromJson(body['assignment'] as Map<String, dynamic>);
  }

  /// The caller's active assignment, or null when none is active.
  Future<Assignment?> myAssignment() async {
    final response = await _send(() => _dio.get<dynamic>('/assignments/me'));
    final dynamic data = response.data;
    if (data == null || data == '') {
      return null;
    }
    return Assignment.fromJson(data as Map<String, dynamic>);
  }

  /// Ends the caller's active assignment; access is revoked immediately.
  Future<void> endMyAssignment() async {
    await _send(() => _dio.post<dynamic>('/assignments/me/end'));
  }

  /// Coach issues a single-use, capacity-bound assignment invite.
  Future<AssignmentInvite> issueAssignmentInvite() async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/assignments/invites'));
    return AssignmentInvite.fromJson(response.data as Map<String, dynamic>);
  }

  /// Lists the coach's active assignments (identity only, no training history).
  Future<List<CoachRosterEntry>> coachAssignments() async {
    final response = await _send(() => _dio.get<dynamic>('/coach/assignments'));
    final List<dynamic> data =
        (response.data as Map<String, dynamic>)['assignments'] as List<dynamic>;
    return data
        .map((dynamic item) =>
            CoachRosterEntry.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  /// Volume and recent sessions for an actively assigned player.
  Future<CoachPlayerSummary> coachPlayerSummary(String assignmentId,
      {int days = 7}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/summary',
        queryParameters: <String, dynamic>{'days': days},
      ),
    );
    return _parseBody(
        response.data, CoachPlayerSummary.fromJson, _invalidCoachHistory);
  }

  /// The assigned player's recent personal records, newest-first.
  Future<List<PersonalRecord>> coachPlayerPersonalRecords(String assignmentId,
      {int limit = 20}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/personal-records',
        queryParameters: <String, dynamic>{'limit': limit},
      ),
    );
    return _parseBodyList(
        response.data, PersonalRecord.fromJson, _invalidCoachHistory);
  }

  Future<List<CheckpointReviewListItem>> coachCheckpointReviews(
      String assignmentId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/checkpoint-reviews',
      ),
    );
    return _parseBodyList(
      response.data,
      CheckpointReviewListItem.fromJson,
      _invalidCheckpointReview,
    );
  }

  Future<CheckpointReview> coachCheckpointReview(
      String assignmentId, int checkpoint) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/checkpoint-reviews/$checkpoint',
      ),
    );
    return _parseBody(
      response.data,
      CheckpointReview.fromJson,
      _invalidCheckpointReview,
    );
  }

  /// The distinct exercises the assigned player has logged.
  Future<List<CoachPlayerExercise>> coachPlayerExercises(
      String assignmentId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/exercises',
      ),
    );
    return _parseBody(
      response.data,
      (Map<String, dynamic> json) => (json['exercises'] as List<dynamic>)
          .map((dynamic item) =>
              CoachPlayerExercise.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      _invalidCoachHistory,
    );
  }

  /// Progression history, latest caption, and records for one logged exercise.
  Future<CoachExerciseHistory> coachPlayerExerciseHistory(
      String assignmentId, String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/exercises/$exerciseId/history',
      ),
    );
    return _parseBody(
        response.data, CoachExerciseHistory.fromJson, _invalidCoachHistory);
  }

  /// Lists the coach's assignment notices, newest-first.
  Future<List<AssignmentNotice>> coachNotices() async {
    final response =
        await _send(() => _dio.get<dynamic>('/coach/assignments/notices'));
    final List<dynamic> data =
        (response.data as Map<String, dynamic>)['notices'] as List<dynamic>;
    return data
        .map((dynamic item) =>
            AssignmentNotice.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  /// Marks all of the coach's notices read.
  Future<int> markCoachNoticesRead() async {
    final response = await _send(
        () => _dio.post<dynamic>('/coach/assignments/notices/read'));
    return ((response.data as Map<String, dynamic>)['marked_read'] as num?)
            ?.toInt() ??
        0;
  }

  /// Lists the coach's missed-day alerts (ADR 030); defaults to new + acknowledged.
  Future<List<CoachAlert>> coachAlerts({List<String>? states}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/alerts',
        queryParameters: (states == null || states.isEmpty)
            ? null
            : <String, dynamic>{'state': states},
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['alerts'] is! List<dynamic>) {
      throw ApiException(
        _invalidAlerts,
        failureMessage: _invalidServiceDataFailure(_invalidAlerts),
      );
    }
    return _parseBodyList(data['alerts'], CoachAlert.fromJson, _invalidAlerts);
  }

  /// Acknowledges one missed-day alert; already acknowledged is idempotent.
  Future<CoachAlert> acknowledgeCoachAlert(String alertId) async {
    final response = await _send(
        () => _dio.post<dynamic>('/coach/alerts/$alertId/acknowledge'));
    return _parseBody(response.data, CoachAlert.fromJson, _invalidAlerts);
  }

  /// Resolves one missed-day alert; already resolved is idempotent.
  Future<CoachAlert> resolveCoachAlert(String alertId) async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/alerts/$alertId/resolve'));
    return _parseBody(response.data, CoachAlert.fromJson, _invalidAlerts);
  }

  /// Lists an actively assigned player's check-ins, newest date first (ADR 031).
  Future<List<CheckIn>> coachCheckIns(String assignmentId) async {
    final response = await _send(
      () => _dio.get<dynamic>('/coach/assignments/$assignmentId/check-ins'),
    );
    return _parseCheckInList(response.data);
  }

  /// Records an immutable check-in for an actively assigned player (ADR 031).
  Future<CheckInCreation> createCoachCheckIn(
    String assignmentId, {
    required String checkedInOn,
    required String channel,
    String? note,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'checked_in_on': checkedInOn,
      'channel': channel,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
    };
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/check-ins',
        data: body,
      ),
    );
    return _parseBody(
      response.data,
      CheckInCreation.fromJson,
      _invalidCheckIns,
      failureMessage: _invalidCheckInsFailure,
    );
  }

  /// Lists the player's check-ins across all assignments, including ended ones.
  Future<List<CheckIn>> playerCheckIns() async {
    final response =
        await _send(() => _dio.get<dynamic>('/assignments/me/check-ins'));
    return _parseCheckInList(response.data);
  }

  List<CheckIn> _parseCheckInList(dynamic responseData) {
    if (responseData is! Map<String, dynamic> ||
        responseData['check_ins'] is! List<dynamic>) {
      throw const ApiException(
        _invalidCheckIns,
        failureMessage: _invalidCheckInsFailure,
      );
    }
    return _parseBodyList(
      responseData['check_ins'],
      CheckIn.fromJson,
      _invalidCheckIns,
      failureMessage: _invalidCheckInsFailure,
    );
  }

  /// Publishes a coach-authored program for an assigned player (ADR 026).
  ///
  /// Null overrides are omitted from the body so the pipeline applies its
  /// defaults. Returns the persisted program with its stable version and
  /// provenance. A missing/foreign/ended assignment denies.
  Future<TrainingProgram> coachPublishProgram(
    String assignmentId, {
    String? splitOverride,
    String? repPreference,
    int? frequency,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      if (splitOverride != null) 'user_split_override': splitOverride,
      if (repPreference != null) 'rep_preference_override': repPreference,
      if (frequency != null) 'frequency_override': frequency,
    };
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program',
        data: body,
      ),
    );
    return _parseBody(response.data, TrainingProgram.fromJson, _invalidProgram);
  }

  /// Lists the player's assignment notices, newest-first.
  Future<List<AssignmentNotice>> playerNotices() async {
    final response =
        await _send(() => _dio.get<dynamic>('/assignments/notices'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['notices'] is! List<dynamic>) {
      throw const ApiException(
        _invalidNotices,
        failureMessage: _invalidNoticesFailure,
      );
    }
    return _parseBodyList(
      data['notices'],
      AssignmentNotice.fromJson,
      _invalidNotices,
      failureMessage: _invalidNoticesFailure,
    );
  }

  /// Marks all of the player's notices read, returning how many were marked.
  Future<int> markPlayerNoticesRead() async {
    final response =
        await _send(() => _dio.post<dynamic>('/assignments/notices/read'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['marked_read'] is! num) {
      throw const ApiException(
        _invalidNotices,
        failureMessage: _invalidNoticesFailure,
      );
    }
    return (data['marked_read'] as num).toInt();
  }

  /// Lists the player's own program requests, newest-first (ADR 027).
  Future<List<ProgramRequest>> playerProgramRequests() async {
    final response = await _send(
        () => _dio.get<dynamic>('/assignments/me/program-requests'));
    return _parseProgramRequestList(response.data);
  }

  /// Records a pending program request against the player's coach-controlled
  /// program; the program itself is never changed by creating a request.
  Future<ProgramRequest> createPlayerProgramRequest({
    required String kind,
    String? dayName,
    String? exerciseId,
    String? replacementExerciseId,
    int? desiredWeeklyFrequency,
    String? desiredSplitPreference,
    required String reason,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'kind': kind,
      if (dayName != null) 'day_name': dayName,
      if (exerciseId != null) 'exercise_id': exerciseId,
      if (replacementExerciseId != null)
        'replacement_exercise_id': replacementExerciseId,
      if (desiredWeeklyFrequency != null)
        'desired_weekly_frequency': desiredWeeklyFrequency,
      if (desiredSplitPreference != null)
        'desired_split_preference': desiredSplitPreference,
      'reason': reason,
    };
    final response = await _send(
      () => _dio.post<dynamic>('/assignments/me/program-requests', data: body),
    );
    return _parseBody(
      response.data,
      ProgramRequest.fromJson,
      _invalidProgramRequests,
      failureMessage: _invalidProgramRequestsFailure,
    );
  }

  /// Cancels the player's own pending request.
  Future<ProgramRequest> cancelPlayerProgramRequest(String requestId) async {
    final response = await _send(
      () => _dio
          .post<dynamic>('/assignments/me/program-requests/$requestId/cancel'),
    );
    return _parseBody(
      response.data,
      ProgramRequest.fromJson,
      _invalidProgramRequests,
      failureMessage: _invalidProgramRequestsFailure,
    );
  }

  /// Lists an actively assigned player's program requests for the coach.
  Future<List<ProgramRequest>> coachProgramRequests(String assignmentId) async {
    final response = await _send(
      () => _dio
          .get<dynamic>('/coach/assignments/$assignmentId/program-requests'),
    );
    return _parseProgramRequestList(response.data);
  }

  /// Lists the coach's program requests across every active assignment
  /// (`GET /coach/program-requests`, #118/#121): pending oldest first, then
  /// answered most recently resolved first. Each row carries the requesting
  /// player's username beside the per-assignment fields, so the client resolves
  /// through [applyCoachProgramRequest] / [declineCoachProgramRequest].
  Future<List<ProgramRequest>> coachAllProgramRequests() async {
    final response =
        await _send(() => _dio.get<dynamic>('/coach/program-requests'));
    return _parseProgramRequestList(response.data);
  }

  /// Revalidates and applies a pending request, publishing a new program version.
  Future<ProgramRequest> applyCoachProgramRequest(
      String assignmentId, String requestId) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program-requests/$requestId/apply',
      ),
    );
    return _parseBody(
      response.data,
      ProgramRequest.fromJson,
      _invalidProgramRequests,
      failureMessage: _invalidProgramRequestsFailure,
    );
  }

  /// Declines a pending request with the player-visible reason (ADR 027: the
  /// decline claims pending→declined and carries a short response, so [reply]
  /// is required and the service caps it at 500 characters, #121).
  Future<ProgramRequest> declineCoachProgramRequest(
    String assignmentId,
    String requestId, {
    required String reply,
  }) async {
    final httpResponse = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program-requests/$requestId/decline',
        data: <String, dynamic>{'response': reply},
      ),
    );
    return _parseBody(
      httpResponse.data,
      ProgramRequest.fromJson,
      _invalidProgramRequests,
      failureMessage: _invalidProgramRequestsFailure,
    );
  }

  /// One coach question about [assignmentId] with the client-held transcript
  /// (`POST /coach/assignments/{id}/assistant`, issue #45, ADR 049).
  ///
  /// [history] is the in-memory transcript trimmed to the last turns: the
  /// service persists nothing about the exchange. A 404 means the feature is
  /// off server-side, a 403 that the assignment is no longer active.
  Future<String> coachAssistantAsk({
    required String assignmentId,
    required String question,
    required List<CoachAssistantTurn> history,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/assistant',
        data: <String, dynamic>{
          'question': question,
          'history': <Map<String, dynamic>>[
            for (final CoachAssistantTurn turn in history) turn.toJson(),
          ],
        },
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['answer'] is! String) {
      const String message = 'The service returned an invalid assistant answer.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    return data['answer'] as String;
  }

  List<ProgramRequest> _parseProgramRequestList(dynamic data) {
    if (data is! Map<String, dynamic> || data['requests'] is! List<dynamic>) {
      throw const ApiException(
        _invalidProgramRequests,
        failureMessage: _invalidProgramRequestsFailure,
      );
    }
    return _parseBodyList(
      data['requests'],
      ProgramRequest.fromJson,
      _invalidProgramRequests,
      failureMessage: _invalidProgramRequestsFailure,
    );
  }

  /// Coach revokes an assignment; access is revoked immediately.
  Future<void> revokeAssignment(String assignmentId) async {
    await _send(
        () => _dio.post<dynamic>('/coach/assignments/$assignmentId/revoke'));
  }

  /// Ends every assignment and disables the coach capability, preserving player data.
  Future<int> disableCoachCapability() async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/capability/disable'));
    return ((response.data as Map<String, dynamic>)['ended_assignments']
                as num?)
            ?.toInt() ??
        0;
  }

  Future<void> logout() async {
    await _send(() => _dio.post<dynamic>('/auth/logout'));
  }

  /// Password-confirmed, irreversible account deletion (`DELETE /auth/account`).
  ///
  /// A wrong password is a plain 400 refusal that changes nothing; a transport
  /// failure raises [ApiException] with a null status code. On success every
  /// server session is ended and the account's ledger removed (ADR 015/039).
  Future<void> deleteAccount(String password) async {
    await _send(
      () => _dio.delete<dynamic>(
        '/auth/account',
        data: <String, dynamic>{'password': password},
      ),
    );
  }

  /// Deletion proved by a fresh Google ID token instead of a password (#114):
  /// the only proof a Google-only account has. Every failure — stale, wrong
  /// subject, unverifiable — is the same generic 400 as a wrong password.
  Future<void> deleteAccountWithGoogle({required String googleIdToken}) async {
    await _send(
      () => _dio.delete<dynamic>(
        '/auth/account',
        data: <String, dynamic>{'google_id_token': googleIdToken},
      ),
    );
  }

  /// `POST /auth/google/link`: connects the verified Google subject to the
  /// signed-in account (#114). Both conflicts answer 409 with a message that
  /// never says which other account holds the subject.
  Future<void> linkGoogle({required String idToken}) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/google/link',
        data: <String, dynamic>{'id_token': idToken},
      ),
    );
  }

  /// `DELETE /auth/google/link`: disconnects Google, refused with 409 while
  /// the account has no password (#114). Idempotent when nothing is linked.
  Future<void> unlinkGoogle() async {
    await _send(() => _dio.delete<dynamic>('/auth/google/link'));
  }

  /// `POST /auth/set-password`: the first password for a Google-only account
  /// (#114). Refused with 409 when a password already exists; sessions survive.
  Future<void> setInitialPassword({required String newPassword}) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/set-password',
        data: <String, dynamic>{'new_password': newPassword},
      ),
    );
  }

  /// `POST /auth/change-password`: replaces an existing password. The service
  /// revokes every session, so the caller must sign in again afterwards.
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/change-password',
        data: <String, dynamic>{
          'current_password': currentPassword,
          'new_password': newPassword,
        },
      ),
    );
  }

  /// The account's recovery email, or null when none is set (ADR 007).
  Future<String?> recoveryEmail() async {
    final response = await _send(() => _dio.get<dynamic>('/auth/email'));
    return (response.data as Map<String, dynamic>)['email'] as String?;
  }

  /// Sets the recovery email and returns its normalized value and verification state.
  Future<({String email, bool verified})> setRecoveryEmail(String email) async {
    final response = await _send(
      () => _dio.post<dynamic>('/auth/email', data: {'email': email}),
    );
    final Map<String, dynamic> body = response.data as Map<String, dynamic>;
    final persistedEmail = body['email'];
    final verified = body['verified'];
    if (persistedEmail is! String || persistedEmail.isEmpty || verified is! bool) {
      throw const ApiException(
        'Could not confirm the recovery email. Please retry.',
        failureMessage: AppFailureMessage(
          AppFailureId.recoveryEmailNotConfirmed,
          'Could not confirm the recovery email. Please retry.',
        ),
      );
    }
    return (email: persistedEmail, verified: verified);
  }

  /// Sends a fresh single-use code to the saved, unverified recovery email.
  Future<void> sendRecoveryEmailVerificationCode() async {
    await _send(() => _dio.post<dynamic>('/auth/email/verification-code'));
  }

  /// Consumes the single-use code for the account's current recovery email.
  Future<void> verifyRecoveryEmail(String code) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/email/verify',
        data: <String, dynamic>{'code': code},
      ),
    );
  }

  /// Requests a reset link for [email].
  ///
  /// Always resolves to the service's constant confirmation message
  /// (anti-enumeration): nothing is disclosed about whether the email is linked.
  Future<String> forgotPassword(String email) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/forgot-password',
        data: <String, dynamic>{'email': email},
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    final dynamic message = (response.data as Map<String, dynamic>)['message'];
    return message is String ? message : '';
  }

  /// Redeems a single-use reset token for a new password.
  ///
  /// An unknown, expired, or reused token surfaces the service's one generic
  /// 400 message; a success revokes every prior session server-side.
  Future<void> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/reset-password',
        data: <String, dynamic>{'token': token, 'new_password': newPassword},
        options: Options(extra: {_skipAuth: true}),
      ),
    );
  }

  /// True when the account has completed onboarding (a profile exists).
  Future<bool> hasProfile() async {
    try {
      await _send(() => _dio.get<dynamic>('/profile'));
      return true;
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return false;
      }
      rethrow;
    }
  }

  /// The player's stored training profile.
  Future<PlayerProfile> profile() async {
    final response = await _send(() => _dio.get<dynamic>('/profile'));
    return _parseBody(
      response.data,
      PlayerProfile.fromJson,
      _invalidProfile,
      failureMessage: _invalidProfileFailure,
    );
  }

  /// Saves the player's Assistant style and optional wording instructions.
  Future<PlayerProfile> updateAssistantStyle({
    required String style,
    required String instructions,
  }) async {
    final response = await _send(
      () => _dio.put<dynamic>(
        '/profile/persona',
        data: <String, dynamic>{
          'coach_tone': style,
          'custom_instructions': instructions,
        },
      ),
    );
    return _parseAssistantStyleResponse(response.data);
  }

  PlayerProfile _parseAssistantStyleResponse(dynamic responseBody) {
    if (responseBody is! Map<String, dynamic> ||
        responseBody['profile'] is! Map<String, dynamic>) {
      throw const ApiException(
        _invalidProfile,
        failureMessage: _invalidProfileFailure,
      );
    }
    return _parseBody(
      responseBody['profile'],
      PlayerProfile.fromJson,
      _invalidProfile,
      failureMessage: _invalidProfileFailure,
    );
  }

  /// Updates the player's Training profile. Program-shaping changes may trigger
  /// a rebuild, so a coach-controlled program may stay unchanged while the
  /// profile update still applies.
  Future<ProfileUpdateResult> updateProfile({
    int? weeklyFrequency,
    String? repPreference,
    String? equipmentAccess,
    String? currentGoal,
    String? injuriesOrLimitations,
    double? weightKg,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      if (weeklyFrequency != null) 'weekly_frequency': weeklyFrequency,
      if (repPreference != null) 'rep_preference': repPreference,
      if (equipmentAccess != null) 'equipment_access': equipmentAccess,
      if (currentGoal != null) 'current_goal': currentGoal,
      if (injuriesOrLimitations != null)
        'injuries_or_limitations': injuriesOrLimitations,
      if (weightKg != null) 'weight_kg': weightKg,
    };
    final response = await _send(
      () => _dio.put<dynamic>('/profile', data: body),
    );
    return _parseBody(
      response.data,
      ProfileUpdateResult.fromJson,
      _invalidProfile,
      failureMessage: _invalidProfileFailure,
    );
  }

  /// The player's current expected training schedule, all versions, and active pauses.
  Future<TrainingSchedule> trainingSchedule() async {
    final response = await _send(() => _dio.get<dynamic>('/profile/schedule'));
    return _parseBody(
      response.data,
      TrainingSchedule.fromJson,
      _invalidSchedule,
      failureMessage: _invalidScheduleFailure,
    );
  }

  /// The player's current Weekly streak and Checkpoint progress (#220).
  Future<TrainingStatus> trainingStatus() async {
    final response = await _send(
      () => _dio.get<dynamic>('/dashboard/training-status'),
    );
    return _parseBody(
      response.data,
      TrainingStatus.fromJson,
      _invalidTrainingStatus,
    );
  }

  /// Appends a new effective-dated schedule version; the program is never touched.
  Future<TrainingScheduleSetResult> setTrainingSchedule({
    required List<int> weekdays,
    required String timezone,
    String? effectiveFrom,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'weekdays': weekdays,
      'timezone': timezone,
      if (effectiveFrom != null) 'effective_from': effectiveFrom,
    };
    final response = await _send(
      () => _dio.put<dynamic>('/profile/schedule', data: body),
    );
    return _parseBody(
      response.data,
      TrainingScheduleSetResult.fromJson,
      _invalidSchedule,
      failureMessage: _invalidScheduleFailure,
    );
  }

  /// All pauses the player has scheduled, newest-first.
  Future<List<ScheduledPause>> trainingPauses() async {
    final response =
        await _send(() => _dio.get<dynamic>('/profile/schedule/pauses'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['pauses'] is! List<dynamic>) {
      throw const ApiException(
        _invalidSchedule,
        failureMessage: _invalidScheduleFailure,
      );
    }
    return _parseBodyList(
      data['pauses'],
      ScheduledPause.fromJson,
      _invalidSchedule,
      failureMessage: _invalidScheduleFailure,
    );
  }

  /// Stores a prospective pause (max 14 days, no reason); the assigned coach is
  /// best-effort notified.
  Future<TrainingPauseCreateResult> createTrainingPause({
    required String startsOn,
    required String endsOn,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/profile/schedule/pauses',
        data: <String, dynamic>{'starts_on': startsOn, 'ends_on': endsOn},
      ),
    );
    return _parseBody(
      response.data,
      TrainingPauseCreateResult.fromJson,
      _invalidSchedule,
      failureMessage: _invalidScheduleFailure,
    );
  }

  Future<OnboardingState> startOnboarding() async {
    final response = await _send(() => _dio.post<dynamic>('/onboarding/start'));
    return OnboardingState.fromJson(response.data as Map<String, dynamic>);
  }

  Future<OnboardingState> submitOnboardingStep({
    String? content,
    bool reset = false,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/onboarding/step',
        data: {'content': content, 'reset': reset},
      ),
    );
    return OnboardingState.fromJson(response.data as Map<String, dynamic>);
  }

  Future<OnboardingCompletion> completeOnboarding() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/complete'));
    return OnboardingCompletion.fromJson(response.data as Map<String, dynamic>);
  }

  /// The structured, resumable intake contract (`GET /onboarding/intake`, #50).
  Future<OnboardingIntake> onboardingIntake({
    String invalidDataMessage =
        'The service returned invalid onboarding intake data.',
  }) async {
    final response = await _send(() => _dio.get<dynamic>('/onboarding/intake'));
    return _parseBody(
        response.data, OnboardingIntake.fromJson, invalidDataMessage);
  }

  /// Acknowledges the hosted-processing disclosure before any answer is saved
  /// (`POST /onboarding/intake/disclosure`, ADR 016/036).
  Future<OnboardingIntake> acknowledgeIntakeDisclosure() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/intake/disclosure'));
    return _parseBody(response.data, OnboardingIntake.fromJson,
        'The service returned invalid onboarding intake data.');
  }

  /// Validates and saves one named intake answer
  /// (`PUT /onboarding/intake/answers/{field}`, #50). Idempotent until confirmed.
  Future<OnboardingIntake> saveIntakeAnswer(String field, Object? value) async {
    final response = await _send(
      () => _dio.put<dynamic>(
          '/onboarding/intake/answers/${Uri.encodeComponent(field)}',
          data: <String, dynamic>{'value': value}),
    );
    return _parseBody(response.data, OnboardingIntake.fromJson,
        'The service returned invalid onboarding intake data.');
  }

  /// Writes the confirmed profile and creates the first program once
  /// (`POST /onboarding/intake/confirm`, #50).
  Future<IntakeConfirmation> confirmIntake() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/intake/confirm'));
    return _parseBody(response.data, IntakeConfirmation.fromJson,
        'The service returned invalid onboarding confirmation data.');
  }

  Future<TrainingProgram?> activeProgram() async {
    final response = await _send(() => _dio.get<dynamic>('/programs/active'));
    final dynamic data = response.data;
    if (data == null || data == '') {
      return null;
    }
    return TrainingProgram.fromJson(data as Map<String, dynamic>);
  }

  /// Permanently substitutes a program slot and returns version metadata.
  Future<ProgramSubstitutionResult> substituteProgramExercise({
    required String dayName,
    required String exerciseId,
    required String replacementExerciseId,
    bool allOccurrences = false,
    int? expectedActiveVersion,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/programs/active/substitutions',
        data: <String, dynamic>{
          'day_name': dayName,
          'exercise_id': exerciseId,
          'replacement_exercise_id': replacementExerciseId,
          'all_occurrences': allOccurrences,
          if (expectedActiveVersion != null)
            'expected_active_version': expectedActiveVersion,
        },
      ),
    );
    return _parseBody(
      response.data,
      ProgramSubstitutionResult.fromJson,
      'The service returned invalid program data.',
    );
  }

  Future<ProgramSubstitutionResult> undoProgramSubstitution({
    required int restoreVersion,
    required int expectedActiveVersion,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/programs/active/substitutions/undo',
        data: <String, dynamic>{
          'restore_version': restoreVersion,
          'expected_active_version': expectedActiveVersion,
        },
      ),
    );
    return _parseBody(
      response.data,
      ProgramSubstitutionResult.fromJson,
      'The service returned invalid program data.',
    );
  }

  Future<Map<String, double>> volume({int days = 7}) async {
    final response = await _send(
      () => _dio
          .get<dynamic>('/dashboard/volume', queryParameters: {'days': days}),
    );
    final Map<String, dynamic> data = response.data as Map<String, dynamic>;
    return data.map(
      (String key, dynamic value) =>
          MapEntry<String, double>(key, (value as num).toDouble()),
    );
  }

  Future<List<PersonalRecord>> personalRecords({int limit = 20}) async {
    final response = await _send(
      () => _dio.get<dynamic>('/dashboard/personal-records',
          queryParameters: {'limit': limit}),
    );
    final List<dynamic> data = response.data as List<dynamic>;
    return data
        .map((dynamic item) =>
            PersonalRecord.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<List<CheckpointReviewListItem>> checkpointReviews() async {
    final response =
        await _send(() => _dio.get<dynamic>('/checkpoint-reviews'));
    return _parseBodyList(
      response.data,
      CheckpointReviewListItem.fromJson,
      _invalidCheckpointReview,
    );
  }

  Future<CheckpointReview> checkpointReview(int checkpoint) async {
    final response = await _send(
      () => _dio.get<dynamic>('/checkpoint-reviews/$checkpoint'),
    );
    return _parseBody(
      response.data,
      CheckpointReview.fromJson,
      _invalidCheckpointReview,
    );
  }

  /// Auto-regulated targets for one training day (`GET /workouts/prescription`).
  Future<Prescription> prescription(int dayOrder) async {
    final response = await _send(
      () => _dio.get<dynamic>('/workouts/prescription',
          queryParameters: <String, dynamic>{'day_order': dayOrder}),
    );
    return _parseBody(response.data, Prescription.fromJson,
        'The service returned invalid prescription data.');
  }

  /// The player's exercise baselines for the frozen Active workout
  /// (`GET /workouts/baselines`, #122/#123).
  ///
  /// [receiveTimeout] bounds a workout-start fetch so the start falls back to
  /// the device cache instead of hanging. A malformed body is an
  /// [ApiException], like every other call here.
  Future<List<BaselineExercise>> baselines(
      {Duration receiveTimeout = const Duration(seconds: 15)}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/workouts/baselines',
        options: Options(receiveTimeout: receiveTimeout),
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['baselines'] is! List) {
      throw ApiException(
        _invalidBaselines,
        failureMessage: _invalidServiceDataFailure(_invalidBaselines),
      );
    }
    return _parseBodyList(
        data['baselines'], BaselineExercise.fromJson, _invalidBaselines);
  }

  /// Catalog exercises matching [query], for picking a real unplanned
  /// exercise (`GET /workouts/exercises?query=`, ADR 020/033, #34).
  ///
  /// [targetMuscle] (#162) narrows the search to one catalog muscle; with it
  /// set [query] may be empty, which lists that muscle's exercises so the
  /// Replace search opens pre-filtered before the player types.
  Future<List<ExerciseCatalogEntry>> searchExercises(
    String query, {
    String? targetMuscle,
  }) async {
    final response = await _send(
      () => _dio.get<dynamic>('/workouts/exercises',
          queryParameters: <String, dynamic>{
            'query': query,
            if (targetMuscle != null) 'target_muscle': targetMuscle,
          }),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['exercises'] is! List) {
      const String message = 'The service returned invalid exercise data.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    const String invalidExercises =
        'The service returned invalid exercise data.';
    return _parseBodyList(
      data['exercises'],
      ExerciseCatalogEntry.fromJson,
      invalidExercises,
      failureMessage: _invalidServiceDataFailure(invalidExercises),
    );
  }

  /// Read-only catalog detail for one exercise (`GET /workouts/exercises/{id}`, #53).
  Future<ExerciseCatalogDetail> exerciseCatalogDetail(String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
          '/workouts/exercises/${Uri.encodeComponent(exerciseId)}'),
    );
    return _parseBody(response.data, ExerciseCatalogDetail.fromJson,
        'The service returned invalid exercise data.');
  }

  /// The distinct exercises the player has logged working sets for
  /// (`GET /dashboard/exercises`, #48).
  Future<List<LoggedExercise>> loggedExercises() async {
    final response = await _send(
      () => _dio.get<dynamic>('/dashboard/exercises'),
    );
    return _parseBodyList(response.data, LoggedExercise.fromJson,
        'The service returned invalid exercise data.');
  }

  /// Progression history for one exercise (`GET /dashboard/exercises/{id}/history`).
  Future<ExerciseHistory> exerciseHistory(String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
          '/dashboard/exercises/${Uri.encodeComponent(exerciseId)}/history'),
    );
    return _parseBody(response.data, ExerciseHistory.fromJson,
        'The service returned invalid exercise history data.');
  }

  /// The player's most recent committed session, or null when none (#53).
  ///
  /// Home derives the next program day from this real ledger value; a 404 means
  /// the player has no committed sessions yet, not an error.
  Future<LatestSession?> latestSession() async {
    try {
      final response = await _send(
        () => _dio.get<dynamic>('/workouts/sessions/latest'),
      );
      final dynamic data = response.data;
      if (data is! Map<String, dynamic>) {
        const String message = 'The service returned invalid session data.';
        throw ApiException(
          message,
          failureMessage: _invalidServiceDataFailure(message),
        );
      }
      return LatestSession.fromJson(data);
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return null;
      }
      rethrow;
    }
  }

  /// Commits one workout, creating it (201) or replaying a stored commit (200).
  ///
  /// The body may carry the offline-sync fields; the service is idempotent on
  /// `client_session_id`.
  Future<WorkoutCommitResult> commitWorkoutSession(
      Map<String, dynamic> body) async {
    final response = await _send(
      () => _dio.post<dynamic>('/workouts/sessions', data: body),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      const String message = 'The service returned invalid session data.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    return WorkoutCommitResult(
      statusCode: response.statusCode ?? 201,
      body: data,
    );
  }

  /// The stored commit for a client session id, or null when never committed.
  ///
  /// Used to reconcile a lost response before retrying so a committed workout
  /// is never sent twice.
  Future<Map<String, dynamic>?> sessionByClientId(
      String clientSessionId) async {
    try {
      final response = await _send(
        () => _dio
            .get<dynamic>('/workouts/sessions/by-client-id/$clientSessionId'),
      );
      final dynamic data = response.data;
      if (data is! Map<String, dynamic>) {
        const String message = 'The service returned invalid session data.';
        throw ApiException(
          message,
          failureMessage: _invalidServiceDataFailure(message),
        );
      }
      return data;
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return null;
      }
      rethrow;
    }
  }

  /// Corrects a recent committed session's performed date (`PATCH
  /// /workouts/sessions/{id}/performed-date`, ADR 020/035).
  ///
  /// Requires connectivity and raises [ApiException] on refusal (400 out of
  /// window, 409 too old, 404 unknown) so the UI can surface a clear error.
  Future<Map<String, dynamic>> correctSessionPerformedDate(
      String sessionId, String performedDate) async {
    final response = await _send(
      () => _dio.patch<dynamic>(
        '/workouts/sessions/$sessionId/performed-date',
        data: <String, dynamic>{'performed_date': performedDate},
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      const String message = 'The service returned invalid session data.';
      throw ApiException(
        message,
        failureMessage: _invalidServiceDataFailure(message),
      );
    }
    return data;
  }

  /// The player's persisted assistant-chat history, oldest-first
  /// (`GET /chat/history`, ADR 016).
  Future<List<ChatMessage>> chatHistory() async {
    final response = await _send(() => _dio.get<dynamic>('/chat/history'));
    final dynamic data = response.data;
    if (data is! List<dynamic>) {
      throw ApiException(
        _invalidChat,
        failureMessage: _invalidServiceDataFailure(_invalidChat),
      );
    }
    return _parseBodyList(
      data,
      ChatMessage.fromJson,
      _invalidChat,
      failureMessage: _invalidServiceDataFailure(_invalidChat),
    );
  }

  /// Clears the player's assistant-chat history (`DELETE /chat/history`).
  Future<void> clearChatHistory() async {
    await _send(() => _dio.delete<dynamic>('/chat/history'));
  }

  /// Streams one assistant turn as decoded SSE events (`POST /chat/messages`).
  ///
  /// Tokens arrive incrementally via [ChatToken]; the final [ChatDone] reports
  /// the persisted reply and whether the program changed. A failed turn is a
  /// [ChatError] frame. Any transport failure while the stream is open — a
  /// dropped connection, or a non-2xx body such as a 429 rate limit — surfaces
  /// as an [ApiException] (network failures have a null status code) so the
  /// caller can show a needs-connection/refusal state and never treat a
  /// partial reply as finished.
  Stream<ChatStreamEvent> streamChatMessage(String content) async* {
    final Response<ResponseBody> response;
    try {
      response = await _dio.post<ResponseBody>(
        '/chat/messages',
        data: <String, dynamic>{'content': content},
        options: Options(responseType: ResponseType.stream),
      );
    } on DioException catch (error) {
      throw _toApiException(error);
    }

    final dynamic body = response.data;
    final Stream<Uint8List>? bytes = body is ResponseBody ? body.stream : null;
    if (bytes == null) {
      throw const ApiException(
          'The service returned no message stream. Check your connection.');
    }

    // A non-2xx response (e.g. 429 from CHAT_LIMIT) is still a stream: read it
    // as JSON to surface the server's `detail` instead of an empty SSE body.
    final int status = response.statusCode ?? 200;
    if (status < 200 || status >= 300) {
      final String raw = await _readStream(bytes);
      throw _errorFromResponse(status, raw);
    }

    final SseDecoder decoder = SseDecoder();
    try {
      await for (final String chunk in _decodeUtf8(bytes)) {
        for (final SseEvent event in decoder.addChunk(chunk)) {
          final ChatStreamEvent? parsed = _parseChatEvent(event);
          if (parsed != null) {
            yield parsed;
          }
        }
      }
      for (final SseEvent event in decoder.close()) {
        final ChatStreamEvent? parsed = _parseChatEvent(event);
        if (parsed != null) {
          yield parsed;
        }
      }
    } on DioException catch (error) {
      // The connection dropped mid-stream: treat it as a transient failure so
      // the screen enters its error/offline state and can retry.
      throw _toApiException(error);
    } on ApiException {
      rethrow;
    } on FormatException {
      throw const ApiException(
          'The service sent an unreadable chat stream. Please retry.');
    }
  }

  /// Decodes [bytes] as streaming UTF-8 so a multibyte character split across
  /// two network chunks is reassembled rather than mangled. [utf8.decoder] is
  /// a chunked converter, so it carries partial sequence state across chunks.
  Stream<String> _decodeUtf8(Stream<List<int>> bytes) =>
      utf8.decoder.bind(bytes);

  Future<String> _readStream(Stream<Uint8List> bytes) async {
    final List<int> collected = <int>[];
    await for (final Uint8List chunk in bytes) {
      collected.addAll(chunk);
    }
    return utf8.decode(collected, allowMalformed: true);
  }

  /// Builds an [ApiException] from a non-2xx streamed body, surfacing the
  /// server's `detail` (e.g. the rate-limit message) when present.
  ApiException _errorFromResponse(int status, String raw) {
    final String trimmed = raw.trim();
    if (trimmed.isNotEmpty) {
      try {
        final dynamic decoded = jsonDecode(trimmed);
        if (decoded is Map && decoded['detail'] is String) {
          final String detail = decoded['detail'] as String;
          return ApiException(
            detail,
            statusCode: status,
            failureMessage: ServerFailureMessage(detail),
          );
        }
      } on FormatException {
        // Fall through to the status-based message below.
      }
    }
    if (status >= 500) {
      return ApiException('The service is unavailable. Please retry.',
          statusCode: status,
          failureMessage: const AppFailureMessage(
            AppFailureId.serviceUnavailable,
            'The service is unavailable. Please retry.',
          ));
    }
    return ApiException(
      'Request failed ($status).',
      statusCode: status,
      failureMessage: AppFailureMessage(
        AppFailureId.requestFailed,
        'Request failed ($status).',
        value: status,
      ),
    );
  }

  ChatStreamEvent? _parseChatEvent(SseEvent event) {
    final dynamic decoded = jsonDecode(event.data);
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    if (event.event == 'error') {
      final dynamic detail = decoded['detail'];
      return ChatError(detail is String && detail.isNotEmpty
          ? detail
          : 'The assistant could not answer. Please retry.');
    }
    if (decoded['done'] == true) {
      final dynamic suggestion = decoded['request_suggestion'];
      final ProgramRequestDraft? requestSuggestion = suggestion is Map<String, dynamic> &&
              (suggestion['kind'] == 'exercise_substitution' ||
                  suggestion['kind'] == 'split_change')
          ? ProgramRequestDraft.fromSuggestionJson(suggestion)
          : null;
      return ChatDone(
        responseContent: decoded['response_content'] is String
            ? decoded['response_content'] as String
            : '',
        programUpdated: decoded['program_updated'] == true,
        requestSuggestion: requestSuggestion,
      );
    }
    final dynamic token = decoded['token'];
    return token is String ? ChatToken(token) : null;
  }
}
