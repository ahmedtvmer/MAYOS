/// Wire models mirroring the FastAPI service contracts in `svc/schemas.py` and
/// `agent/ProgramState.py`.
library;

class Capabilities {
  const Capabilities({required this.player, required this.coach});

  factory Capabilities.fromJson(Map<String, dynamic> json) => Capabilities(
        player: json['player'] as bool? ?? false,
        coach: json['coach'] as bool? ?? false,
      );

  final bool player;
  final bool coach;
}

/// One capability's server-owned plan state. The client only displays it; it
/// never infers an entitlement from the user or the device.
class PlanState {
  const PlanState({required this.plan, required this.status});

  factory PlanState.fromJson(Map<String, dynamic> json) {
    final dynamic rawPlan = json['plan'];
    final dynamic rawStatus = json['status'];
    if (rawPlan is! String || rawStatus is! String) {
      throw const FormatException('Invalid plan state.');
    }
    final String plan = rawPlan;
    if (plan != 'free' && plan != 'pro') {
      throw FormatException('Unknown plan: $plan');
    }
    return PlanState(plan: plan, status: rawStatus);
  }

  final String plan;
  final String status;

  bool get isPro => plan == 'pro';

  bool get isFree => plan == 'free';

  String get label => isPro ? 'Pro' : 'Free';
}

/// Independent Lifter and Coach plan states. A null entry means the account
/// does not hold that capability, so it has no plan for it.
class AccountPlans {
  const AccountPlans({this.lifter, this.coach});

  factory AccountPlans.fromJson(Map<String, dynamic> json) => AccountPlans(
        lifter: _state(json['lifter']),
        coach: _state(json['coach']),
      );

  final PlanState? lifter;
  final PlanState? coach;

  static PlanState? _state(dynamic value) {
    if (value == null) return null;
    if (value is! Map<String, dynamic>) {
      throw const FormatException('Invalid plan state.');
    }
    return PlanState.fromJson(value);
  }

  AccountPlans withoutCoach() => AccountPlans(lifter: lifter);

}

/// Current account identity, capabilities, and independent plan states from
/// `GET /auth/me`.
class Account {
  const Account({
    required this.accountId,
    required this.traineeId,
    required this.capabilities,
    this.plans = const AccountPlans(),
  });

  factory Account.fromJson(Map<String, dynamic> json) {
    final Capabilities capabilities = Capabilities.fromJson(
      json['capabilities'] as Map<String, dynamic>,
    );
    final dynamic rawPlans = json['plans'];
    if (rawPlans is! Map<String, dynamic>) {
      throw const FormatException('Missing account plan states.');
    }
    return Account(
      accountId: json['account_id'] as String,
      traineeId: json['trainee_id'] as String,
      capabilities: capabilities,
      plans: AccountPlans.fromJson(rawPlans),
    );
  }

  final String accountId;

  /// The legacy wire field for the reusable username.
  final String traineeId;
  final Capabilities capabilities;
  final AccountPlans plans;

  bool get isCoach => capabilities.coach;

}

/// `GET`/`PUT /coach/profile`: coach-authored fields keyed by immutable account id.
class CoachProfile {
  const CoachProfile({
    required this.accountId,
    required this.displayName,
    required this.bio,
    required this.specialization,
    required this.capacity,
  });

  factory CoachProfile.fromJson(Map<String, dynamic> json) => CoachProfile(
        accountId: json['account_id'] as String,
        displayName: json['display_name'] as String? ?? '',
        bio: json['bio'] as String? ?? '',
        specialization: json['specialization'] as String? ?? '',
        capacity: (json['capacity'] as num?)?.toInt() ?? 1,
      );

  final String accountId;
  final String displayName;
  final String bio;
  final String specialization;
  final int capacity;
}

/// The coach's current, product-facing identity shown before consent.
class CoachIdentity {
  const CoachIdentity({
    required this.displayName,
    required this.bio,
    required this.specialization,
  });

  factory CoachIdentity.fromJson(Map<String, dynamic> json) => CoachIdentity(
        displayName: json['display_name'] as String? ?? '',
        bio: json['bio'] as String? ?? '',
        specialization: json['specialization'] as String? ?? '',
      );

  final String displayName;
  final String bio;
  final String specialization;
}

/// The exact training-data access an active assignment grants (ADR 014).
class AssignmentAccess {
  const AssignmentAccess({
    required this.scope,
    required this.includesCurrentHistory,
    required this.includesHistoricalHistory,
    required this.activeWhileAssigned,
    required this.description,
  });

  factory AssignmentAccess.fromJson(Map<String, dynamic> json) =>
      AssignmentAccess(
        scope: json['scope'] as String? ?? '',
        includesCurrentHistory:
            json['includes_current_history'] as bool? ?? false,
        includesHistoricalHistory:
            json['includes_historical_history'] as bool? ?? false,
        activeWhileAssigned: json['active_while_assigned'] as bool? ?? false,
        description: json['description'] as String? ?? '',
      );

  final String scope;
  final bool includesCurrentHistory;
  final bool includesHistoricalHistory;
  final bool activeWhileAssigned;
  final String description;
}

/// `POST /assignments/invites/preview`: identity and access, code not consumed.
class AssignmentInvitePreview {
  const AssignmentInvitePreview({
    required this.coach,
    required this.access,
    required this.expiresAt,
  });

  factory AssignmentInvitePreview.fromJson(Map<String, dynamic> json) =>
      AssignmentInvitePreview(
        coach: CoachIdentity.fromJson(json['coach'] as Map<String, dynamic>),
        access:
            AssignmentAccess.fromJson(json['access'] as Map<String, dynamic>),
        expiresAt: json['expires_at'] as String? ?? '',
      );

  final CoachIdentity coach;
  final AssignmentAccess access;
  final String expiresAt;
}

/// `GET /assignments/me`: a mutually consented coaching assignment.
class Assignment {
  const Assignment({
    required this.assignmentId,
    required this.coach,
    required this.startedAt,
    required this.status,
  });

  factory Assignment.fromJson(Map<String, dynamic> json) => Assignment(
        assignmentId: json['assignment_id'] as String,
        coach: CoachIdentity.fromJson(json['coach'] as Map<String, dynamic>),
        startedAt: json['started_at'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
      );

  final String assignmentId;
  final CoachIdentity coach;
  final String startedAt;
  final String status;
}

/// `POST /coach/assignments/invites`: the one-time code and remaining capacity.
class AssignmentInvite {
  const AssignmentInvite({
    required this.token,
    required this.expiresAt,
    required this.activeAssignments,
    required this.capacity,
  });

  factory AssignmentInvite.fromJson(Map<String, dynamic> json) =>
      AssignmentInvite(
        token: json['token'] as String,
        expiresAt: json['expires_at'] as String? ?? '',
        activeAssignments: (json['active_assignments'] as num?)?.toInt() ?? 0,
        capacity: (json['capacity'] as num?)?.toInt() ?? 0,
      );

  final String token;
  final String expiresAt;
  final int activeAssignments;
  final int capacity;

  int get remaining => capacity - activeAssignments;
}

/// An in-app assignment notice for the coach.
class AssignmentNotice {
  const AssignmentNotice({
    required this.noticeId,
    required this.kind,
    required this.message,
    required this.createdAt,
    this.readAt,
  });

  factory AssignmentNotice.fromJson(Map<String, dynamic> json) =>
      AssignmentNotice(
        noticeId: json['notice_id'] as String,
        kind: json['kind'] as String? ?? '',
        message: json['message'] as String? ?? '',
        createdAt: json['created_at'] as String? ?? '',
        readAt: json['read_at'] as String?,
      );

  final String noticeId;
  final String kind;
  final String message;
  final String createdAt;
  final String? readAt;

  bool get isUnread => readAt == null || readAt!.isEmpty;
}

/// A player's request against a coach-controlled program and its resolution
/// state (ADR 027). It pins the exact program version, day, and slot it targets;
/// creating one never changes the program.
class ProgramRequest {
  const ProgramRequest({
    required this.requestId,
    required this.assignmentId,
    required this.kind,
    required this.programVersion,
    required this.reason,
    required this.status,
    required this.createdAt,
    this.dayName,
    this.exerciseId,
    this.replacementExerciseId,
    this.desiredWeeklyFrequency,
    this.desiredSplitPreference,
    this.response,
    this.resolvedAt,
    this.resolvedBy,
  });

  factory ProgramRequest.fromJson(Map<String, dynamic> json) => ProgramRequest(
        requestId: json['request_id'] as String,
        assignmentId: json['assignment_id'] as String,
        kind: json['kind'] as String,
        programVersion: (json['program_version'] as num).toInt(),
        dayName: json['day_name'] as String?,
        exerciseId: json['exercise_id'] as String?,
        replacementExerciseId: json['replacement_exercise_id'] as String?,
        desiredWeeklyFrequency:
            (json['desired_weekly_frequency'] as num?)?.toInt(),
        desiredSplitPreference: json['desired_split_preference'] as String?,
        reason: json['reason'] as String,
        status: json['status'] as String,
        response: json['response'] as String?,
        createdAt: json['created_at'] as String,
        resolvedAt: json['resolved_at'] as String?,
        resolvedBy: json['resolved_by'] as String?,
      );

  final String requestId;
  final String assignmentId;
  final String kind;
  final int programVersion;
  final String? dayName;
  final String? exerciseId;
  final String? replacementExerciseId;
  final int? desiredWeeklyFrequency;
  final String? desiredSplitPreference;
  final String reason;
  final String status;
  final String? response;
  final String createdAt;
  final String? resolvedAt;
  final String? resolvedBy;

  bool get isPending => status == 'pending';

  bool get isExerciseSubstitution => kind == 'exercise_substitution';

  bool get hasResponse => response != null && response!.isNotEmpty;

  String get description {
    if (isExerciseSubstitution) {
      return 'Substitute $exerciseId on $dayName with $replacementExerciseId';
    }
    final String preference =
        desiredSplitPreference == null || desiredSplitPreference!.isEmpty
            ? ''
            : ' ($desiredSplitPreference)';
    return 'Change to $desiredWeeklyFrequency days/week$preference';
  }

  String get statusLabel => switch (status) {
        'pending' => 'Pending',
        'applied' => 'Applied',
        'declined' => 'Declined',
        'cancelled' => 'Cancelled',
        _ => status,
      };
}

/// `GET /coach/assignments`: active assignment identity for the coach console.
class CoachRosterEntry {
  const CoachRosterEntry({
    required this.assignmentId,
    required this.playerUsername,
    required this.startedAt,
    required this.status,
    this.alertsNew = 0,
    this.alertsAcknowledged = 0,
    this.currentMissedStreak = 0,
    this.nextFollowUpOn,
  });

  factory CoachRosterEntry.fromJson(Map<String, dynamic> json) =>
      CoachRosterEntry(
        assignmentId: json['assignment_id'] as String,
        playerUsername: json['player_username'] as String? ?? '',
        startedAt: json['started_at'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
        alertsNew: (json['alerts_new'] as num?)?.toInt() ?? 0,
        alertsAcknowledged:
            (json['alerts_acknowledged'] as num?)?.toInt() ?? 0,
        currentMissedStreak:
            (json['current_missed_streak'] as num?)?.toInt() ?? 0,
        nextFollowUpOn: json['next_follow_up_on'] as String?,
      );

  final String assignmentId;
  final String playerUsername;
  final String startedAt;
  final String status;
  final int alertsNew;
  final int alertsAcknowledged;
  final int currentMissedStreak;

  /// The next weekly follow-up due date (`YYYY-MM-DD`), computed catalog-side.
  final String? nextFollowUpOn;

  int get alertsOpen => alertsNew + alertsAcknowledged;
}

/// `GET /coach/alerts`: one catalog-side alert, of more than one kind (ADR 030/031).
///
/// `kind` is `missed_expected_days` or `follow_up_due`; the kind-specific fields
/// (`streak_start_date`/`last_missed_date`/`missed_count` vs `due_on`) are
/// flattened beside the common fields.
class CoachAlert {
  const CoachAlert({
    required this.alertId,
    required this.assignmentId,
    required this.playerUsername,
    required this.kind,
    required this.state,
    required this.createdAt,
    this.streakStartDate,
    this.lastMissedDate,
    this.missedCount = 0,
    this.dueOn,
    this.lastCheckInOn,
    this.acknowledgedAt,
    this.resolvedAt,
    this.resolvedBy,
  });

  factory CoachAlert.fromJson(Map<String, dynamic> json) => CoachAlert(
        alertId: json['alert_id'] as String,
        assignmentId: json['assignment_id'] as String? ?? '',
        playerUsername: json['player_username'] as String? ?? '',
        kind: json['kind'] as String? ?? '',
        state: json['state'] as String? ?? 'new',
        createdAt: json['created_at'] as String? ?? '',
        streakStartDate: json['streak_start_date'] as String?,
        lastMissedDate: json['last_missed_date'] as String?,
        missedCount: (json['missed_count'] as num?)?.toInt() ?? 0,
        dueOn: json['due_on'] as String?,
        lastCheckInOn: json['last_check_in_on'] as String?,
        acknowledgedAt: json['acknowledged_at'] as String?,
        resolvedAt: json['resolved_at'] as String?,
        resolvedBy: json['resolved_by'] as String?,
      );

  final String alertId;
  final String assignmentId;
  final String playerUsername;
  final String kind;
  final String state;
  final String createdAt;
  final String? streakStartDate;
  final String? lastMissedDate;
  final int missedCount;
  final String? dueOn;
  final String? lastCheckInOn;
  final String? acknowledgedAt;
  final String? resolvedAt;
  final String? resolvedBy;

  static const String followUpDueKind = 'follow_up_due';

  bool get isNew => state == 'new';
  bool get isAcknowledged => state == 'acknowledged';
  bool get isResolved => state == 'resolved';

  bool get isFollowUpDue => kind == followUpDueKind;

  /// The alert-centre description, rendered per kind.
  String get description => isFollowUpDue
      ? 'Follow-up due since ${dueOn ?? 'an earlier date'}'
      : 'Missed $missedCount expected training '
          '${missedCount == 1 ? 'day' : 'days'} '
          '(${streakStartDate ?? '?'} to ${lastMissedDate ?? '?'})';

  String get stateLabel => switch (state) {
        'new' => 'New',
        'acknowledged' => 'Acknowledged',
        'resolved' => 'Resolved',
        _ => state,
      };
}

/// One coach-recorded check-in fact (`GET /coach/assignments/{id}/check-ins`,
/// `GET /assignments/me/check-ins`). Immutable and visible to the player for
/// the life of the account, including after unassignment (ADR 031).
class CheckIn {
  const CheckIn({
    required this.checkInId,
    required this.assignmentId,
    required this.checkedInOn,
    required this.channel,
    required this.createdAt,
    this.note,
    this.coachUsername,
    this.assignmentStatus,
  });

  factory CheckIn.fromJson(Map<String, dynamic> json) => CheckIn(
        checkInId: json['check_in_id'] as String,
        assignmentId: json['assignment_id'] as String? ?? '',
        checkedInOn: json['checked_in_on'] as String? ?? '',
        channel: json['channel'] as String? ?? 'other',
        createdAt: json['created_at'] as String? ?? '',
        note: json['note'] as String?,
        coachUsername: json['coach_username'] as String?,
        assignmentStatus: json['assignment_status'] as String?,
      );

  final String checkInId;
  final String assignmentId;
  final String checkedInOn;
  final String channel;
  final String createdAt;
  final String? note;

  /// The coach's current username; present on the player's cross-assignment list.
  final String? coachUsername;

  /// `active` or `ended`; present on the player's cross-assignment list.
  final String? assignmentStatus;

  static const List<String> channels = <String>[
    'in_app',
    'in_person',
    'phone',
    'video',
    'message',
    'email',
    'other',
  ];

  String get channelLabel => switch (channel) {
        'in_app' => 'In app',
        'in_person' => 'In person',
        'phone' => 'Phone',
        'video' => 'Video',
        'message' => 'Message',
        'email' => 'Email',
        _ => 'Other',
      };
}

/// The check-ins ordered newest `checked_in_on` first (ties keep input order).
///
/// Shared so the coach drill-down stays sorted after appending a new check-in
/// rather than relying on server order or a bare prepend.
List<CheckIn> sortCheckInsNewestFirst(Iterable<CheckIn> checkIns) {
  final List<CheckIn> sorted = List<CheckIn>.of(checkIns);
  sorted.sort((CheckIn a, CheckIn b) => b.checkedInOn.compareTo(a.checkedInOn));
  return sorted;
}

/// `POST /coach/assignments/{id}/check-ins`: the recorded check-in and the
/// next follow-up date a full weekly cadence past it.
class CheckInCreation {
  const CheckInCreation({required this.checkIn, this.nextFollowUpOn});

  factory CheckInCreation.fromJson(Map<String, dynamic> json) =>
      CheckInCreation(
        checkIn: CheckIn.fromJson(json['check_in'] as Map<String, dynamic>),
        nextFollowUpOn: json['next_follow_up_on'] as String?,
      );

  final CheckIn checkIn;
  final String? nextFollowUpOn;
}

/// One exercise's working-set totals within an assigned player's session.
class CoachPlayerSessionExercise {
  const CoachPlayerSessionExercise({
    required this.name,
    required this.sets,
    required this.reps,
    required this.volumeKg,
  });

  factory CoachPlayerSessionExercise.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSessionExercise(
        name: json['name'] as String,
        sets: (json['sets'] as num).toInt(),
        reps: (json['reps'] as num).toInt(),
        volumeKg: (json['volume_kg'] as num).toDouble(),
      );

  final String name;
  final int sets;
  final int reps;
  final double volumeKg;
}

/// A factual skipped or unplanned exercise recorded in a player's session.
class CoachPlayerDivergence {
  const CoachPlayerDivergence({
    required this.kind,
    required this.exerciseId,
    required this.exerciseName,
  });

  factory CoachPlayerDivergence.fromJson(Map<String, dynamic> json) =>
      CoachPlayerDivergence(
        kind: json['kind'] as String,
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String,
      );

  final String kind;
  final String exerciseId;
  final String exerciseName;
}

/// The assigned player's current expected training weekdays and timezone.
class CoachPlayerSchedule {
  const CoachPlayerSchedule({required this.weekdays, required this.timezone});

  factory CoachPlayerSchedule.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSchedule(
        weekdays: _weekdays(json['weekdays']),
        timezone: json['timezone'] as String,
      );

  final List<int> weekdays;
  final String timezone;
}

/// An upcoming or active training pause the assigned player scheduled. No
/// reason is ever stored or returned.
class CoachPlayerPause {
  const CoachPlayerPause({required this.startsOn, required this.endsOn});

  factory CoachPlayerPause.fromJson(Map<String, dynamic> json) =>
      CoachPlayerPause(
        startsOn: json['starts_on'] as String,
        endsOn: json['ends_on'] as String,
      );

  final String startsOn;
  final String endsOn;
}

/// The assigned player's most recent committed session.
class CoachPlayerLatestSession {
  const CoachPlayerLatestSession({
    required this.sessionDate,
    required this.splitName,
    required this.setsCount,
    required this.totalVolumeKg,
    this.readinessScore,
    this.exercises = const <CoachPlayerSessionExercise>[],
    this.divergences = const <CoachPlayerDivergence>[],
  });

  factory CoachPlayerLatestSession.fromJson(Map<String, dynamic> json) =>
      CoachPlayerLatestSession(
        sessionDate: json['session_date'] as String,
        splitName: json['split_name'] as String,
        readinessScore: (json['readiness_score'] as num?)?.toInt(),
        setsCount: (json['sets_count'] as num).toInt(),
        totalVolumeKg: (json['total_volume_kg'] as num).toDouble(),
        exercises: (json['exercises'] as List<dynamic>? ?? const [])
            .map((dynamic e) => CoachPlayerSessionExercise.fromJson(
                e as Map<String, dynamic>))
            .toList(growable: false),
        divergences: (json['divergences'] as List<dynamic>? ?? const [])
            .map((dynamic d) =>
                CoachPlayerDivergence.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String sessionDate;
  final String splitName;
  final int? readinessScore;
  final int setsCount;
  final double totalVolumeKg;
  final List<CoachPlayerSessionExercise> exercises;
  final List<CoachPlayerDivergence> divergences;
}

/// A compact entry in the assigned player's recent session history.
class CoachPlayerRecentSession {
  const CoachPlayerRecentSession({
    required this.sessionId,
    required this.sessionDate,
    required this.splitName,
    required this.setsCount,
    required this.totalVolumeKg,
    this.readinessScore,
    this.divergences = const <CoachPlayerDivergence>[],
  });

  factory CoachPlayerRecentSession.fromJson(Map<String, dynamic> json) =>
      CoachPlayerRecentSession(
        sessionId: json['session_id'] as String,
        sessionDate: json['session_date'] as String,
        splitName: json['split_name'] as String,
        readinessScore: (json['readiness_score'] as num?)?.toInt(),
        setsCount: (json['sets_count'] as num).toInt(),
        totalVolumeKg: (json['total_volume_kg'] as num).toDouble(),
        divergences: (json['divergences'] as List<dynamic>? ?? const [])
            .map((dynamic d) =>
                CoachPlayerDivergence.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String sessionId;
  final String sessionDate;
  final String splitName;
  final int? readinessScore;
  final int setsCount;
  final double totalVolumeKg;
  final List<CoachPlayerDivergence> divergences;
}

/// `GET /coach/assignments/{id}/player/summary` for an actively assigned player.
class CoachPlayerSummary {
  const CoachPlayerSummary({
    required this.playerUsername,
    required this.startedAt,
    required this.status,
    required this.volume,
    this.latestSession,
    this.recentSessions = const <CoachPlayerRecentSession>[],
    this.schedule,
    this.pauses = const <CoachPlayerPause>[],
  });

  factory CoachPlayerSummary.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSummary(
        playerUsername: json['player_username'] as String,
        startedAt: json['started_at'] as String,
        status: json['status'] as String,
        volume: (json['volume'] as Map<String, dynamic>? ?? const {})
            .map((String key, dynamic value) =>
                MapEntry<String, double>(key, (value as num).toDouble())),
        latestSession: json['latest_session'] == null
            ? null
            : CoachPlayerLatestSession.fromJson(
                json['latest_session'] as Map<String, dynamic>),
        recentSessions: (json['recent_sessions'] as List<dynamic>? ?? const [])
            .map((dynamic s) =>
                CoachPlayerRecentSession.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
        schedule: json['schedule'] == null
            ? null
            : CoachPlayerSchedule.fromJson(
                json['schedule'] as Map<String, dynamic>),
        pauses: (json['pauses'] as List<dynamic>? ?? const [])
            .map((dynamic p) =>
                CoachPlayerPause.fromJson(p as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String playerUsername;
  final String startedAt;
  final String status;
  final Map<String, double> volume;
  final CoachPlayerLatestSession? latestSession;
  final List<CoachPlayerRecentSession> recentSessions;
  final CoachPlayerSchedule? schedule;
  final List<CoachPlayerPause> pauses;
}

/// One exercise the assigned player has logged.
class CoachPlayerExercise {
  const CoachPlayerExercise({required this.id, required this.name});

  factory CoachPlayerExercise.fromJson(Map<String, dynamic> json) =>
      CoachPlayerExercise(
        id: json['id'] as String,
        name: json['name'] as String,
      );

  final String id;
  final String name;
}

/// One progression point in an exercise's history.
class CoachExerciseHistoryPoint {
  const CoachExerciseHistoryPoint({
    required this.date,
    required this.weightKg,
    required this.reps,
    required this.e1rm,
    this.rpe,
  });

  factory CoachExerciseHistoryPoint.fromJson(Map<String, dynamic> json) =>
      CoachExerciseHistoryPoint(
        date: json['date'] as String,
        weightKg: (json['weight_kg'] as num).toDouble(),
        reps: (json['reps'] as num).toInt(),
        rpe: (json['rpe'] as num?)?.toDouble(),
        e1rm: (json['e1rm'] as num).toDouble(),
      );

  final String date;
  final double weightKg;
  final int reps;
  final double? rpe;
  final double e1rm;
}

/// One recorded personal record for a single exercise.
class CoachExerciseRecord {
  const CoachExerciseRecord({
    required this.recordType,
    required this.reps,
    required this.value,
    required this.achievedAt,
    this.prevValue,
  });

  factory CoachExerciseRecord.fromJson(Map<String, dynamic> json) =>
      CoachExerciseRecord(
        recordType: json['record_type'] as String,
        reps: (json['reps'] as num).toInt(),
        value: (json['value'] as num).toDouble(),
        prevValue: (json['prev_value'] as num?)?.toDouble(),
        achievedAt: json['achieved_at'] as String,
      );

  final String recordType;
  final int reps;
  final double value;
  final double? prevValue;
  final String achievedAt;
}

/// `GET /coach/assignments/{id}/player/exercises/{exercise_id}/history`.
class CoachExerciseHistory {
  const CoachExerciseHistory({
    required this.history,
    required this.records,
    this.caption,
  });

  factory CoachExerciseHistory.fromJson(Map<String, dynamic> json) =>
      CoachExerciseHistory(
        history: (json['history'] as List<dynamic>? ?? const [])
            .map((dynamic point) => CoachExerciseHistoryPoint.fromJson(
                point as Map<String, dynamic>))
            .toList(growable: false),
        caption: json['caption'] as String?,
        records: (json['records'] as List<dynamic>? ?? const [])
            .map((dynamic record) => CoachExerciseRecord.fromJson(
                record as Map<String, dynamic>))
            .toList(growable: false),
      );

  final List<CoachExerciseHistoryPoint> history;
  final String? caption;
  final List<CoachExerciseRecord> records;
}

/// An authenticated account plus onboarding and recovery-email state.
class AccountSession {
  const AccountSession({
    required this.account,
    required this.onboarded,
    required this.hasRecoveryEmail,
  });

  final Account account;
  final bool onboarded;

  /// ADR 007: a recovery email is mandatory before dashboard or onboarding.
  final bool hasRecoveryEmail;
}

/// `POST /auth/register` and `POST /auth/login` response body.
class AuthTokens {
  const AuthTokens({required this.accessToken, required this.traineeId});

  factory AuthTokens.fromJson(Map<String, dynamic> json) => AuthTokens(
        accessToken: json['access_token'] as String,
        traineeId: json['trainee_id'] as String,
      );

  final String accessToken;
  final String traineeId;
}

/// `POST /onboarding/start` and `POST /onboarding/step` response body.
class OnboardingState {
  const OnboardingState({
    required this.intakeStep,
    required this.isComplete,
    required this.messages,
  });

  factory OnboardingState.fromJson(Map<String, dynamic> json) =>
      OnboardingState(
        intakeStep: (json['intake_step'] as num?)?.toInt() ?? 1,
        isComplete: json['is_complete'] as bool? ?? false,
        messages: (json['messages'] as List<dynamic>? ?? const [])
            .map((dynamic m) => m.toString())
            .toList(growable: false),
      );

  final int intakeStep;
  final bool isComplete;
  final List<String> messages;
}

/// `POST /onboarding/complete` response body.
///
/// Both program fields are null when no program could be produced (a
/// coach-controlled completion with nothing saved), and [programMessage] carries
/// the service's explanation so the client must not announce a routine.
class OnboardingCompletion {
  const OnboardingCompletion({
    required this.programName,
    required this.weeklyFrequency,
    this.programMessage,
  });

  factory OnboardingCompletion.fromJson(Map<String, dynamic> json) =>
      OnboardingCompletion(
        programName: json['program_name'] as String?,
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt(),
        programMessage: json['program_message'] as String?,
      );

  final String? programName;
  final int? weeklyFrequency;
  final String? programMessage;

  bool get hasProgram => programName != null && weeklyFrequency != null;
}

/// `GET /profile`: the player's stored training profile. Only the fields the
/// profile editor writes are modeled; unknown keys are ignored.
class PlayerProfile {
  const PlayerProfile({
    this.repPreference = 'balanced',
    this.weeklyFrequency = 4,
  });

  factory PlayerProfile.fromJson(Map<String, dynamic> json) => PlayerProfile(
        repPreference: json['rep_preference'] as String? ?? 'balanced',
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt() ?? 4,
      );

  final String repPreference;
  final int weeklyFrequency;
}

/// `PUT /profile` response body.
///
/// [programBlocked] is true when a rebuild was warranted but the assigned coach
/// owns the active program, so nothing was regenerated and [programMessage]
/// explains that a coach request is needed.
class ProfileUpdateResult {
  const ProfileUpdateResult({
    required this.programRebuilt,
    this.programBlocked = false,
    this.programMessage,
  });

  factory ProfileUpdateResult.fromJson(Map<String, dynamic> json) =>
      ProfileUpdateResult(
        programRebuilt: json['program_rebuilt'] as bool? ?? false,
        programBlocked: json['program_blocked'] as bool? ?? false,
        programMessage: json['program_message'] as String?,
      );

  final bool programRebuilt;
  final bool programBlocked;
  final String? programMessage;
}

const List<String> weekdayLabels = <String>[
  'Mon',
  'Tue',
  'Wed',
  'Thu',
  'Fri',
  'Sat',
  'Sun',
];

List<int> _weekdays(dynamic raw) {
  if (raw is! List<dynamic>) {
    throw const FormatException('Invalid training weekdays.');
  }
  return raw.map((dynamic day) {
    if (day is! num) {
      throw const FormatException('Invalid training weekday.');
    }
    final int value = day.toInt();
    if (value < 1 || value > 7) {
      throw const FormatException('Invalid training weekday.');
    }
    return value;
  }).toList(growable: false);
}

/// One effective-dated version of the player's expected training weekdays
/// (`GET`/`PUT /profile/schedule`, ADR 029). Setting a schedule never touches
/// the program's weekly frequency or ordered training days.
class TrainingScheduleVersion {
  const TrainingScheduleVersion({
    required this.scheduleId,
    required this.weekdays,
    required this.timezone,
    required this.effectiveFrom,
    required this.createdAt,
  });

  factory TrainingScheduleVersion.fromJson(Map<String, dynamic> json) =>
      TrainingScheduleVersion(
        scheduleId: json['schedule_id'] as String,
        weekdays: _weekdays(json['weekdays']),
        timezone: json['timezone'] as String,
        effectiveFrom: json['effective_from'] as String,
        createdAt: json['created_at'] as String,
      );

  final String scheduleId;
  final List<int> weekdays;
  final String timezone;
  final String effectiveFrom;
  final String createdAt;
}

/// A prospective training pause; no reason is stored or returned.
class ScheduledPause {
  const ScheduledPause({
    required this.pauseId,
    required this.startsOn,
    required this.endsOn,
    required this.createdAt,
  });

  factory ScheduledPause.fromJson(Map<String, dynamic> json) => ScheduledPause(
        pauseId: json['pause_id'] as String,
        startsOn: json['starts_on'] as String,
        endsOn: json['ends_on'] as String,
        createdAt: json['created_at'] as String,
      );

  final String pauseId;
  final String startsOn;
  final String endsOn;
  final String createdAt;
}

/// `GET /profile/schedule`: the current version, every version, and active pauses.
class TrainingSchedule {
  const TrainingSchedule({
    this.current,
    this.versions = const <TrainingScheduleVersion>[],
    this.pauses = const <ScheduledPause>[],
  });

  factory TrainingSchedule.fromJson(Map<String, dynamic> json) =>
      TrainingSchedule(
        current: json['current'] == null
            ? null
            : TrainingScheduleVersion.fromJson(
                json['current'] as Map<String, dynamic>),
        versions: (json['versions'] as List<dynamic>? ?? const [])
            .map((dynamic v) =>
                TrainingScheduleVersion.fromJson(v as Map<String, dynamic>))
            .toList(growable: false),
        pauses: (json['pauses'] as List<dynamic>? ?? const [])
            .map((dynamic p) =>
                ScheduledPause.fromJson(p as Map<String, dynamic>))
            .toList(growable: false),
      );

  final TrainingScheduleVersion? current;
  final List<TrainingScheduleVersion> versions;
  final List<ScheduledPause> pauses;
}

/// `PUT /profile/schedule` response: the appended version and the current schedule.
class TrainingScheduleSetResult {
  const TrainingScheduleSetResult({required this.version, this.current});

  factory TrainingScheduleSetResult.fromJson(Map<String, dynamic> json) =>
      TrainingScheduleSetResult(
        version: TrainingScheduleVersion.fromJson(
            json['version'] as Map<String, dynamic>),
        current: json['current'] == null
            ? null
            : TrainingScheduleVersion.fromJson(
                json['current'] as Map<String, dynamic>),
      );

  final TrainingScheduleVersion version;
  final TrainingScheduleVersion? current;
}

/// `POST /profile/schedule/pauses` response: the stored pause and whether the
/// assigned coach was notified.
class TrainingPauseCreateResult {
  const TrainingPauseCreateResult({
    required this.pause,
    required this.noticeSent,
  });

  factory TrainingPauseCreateResult.fromJson(Map<String, dynamic> json) =>
      TrainingPauseCreateResult(
        pause: ScheduledPause.fromJson(json['pause'] as Map<String, dynamic>),
        noticeSent: json['notice_sent'] as bool? ?? false,
      );

  final ScheduledPause pause;
  final bool noticeSent;
}

class ProgramExercise {
  const ProgramExercise({
    required this.exerciseId,
    required this.exerciseName,
    required this.targetSets,
    required this.targetRepsMin,
    required this.targetRepsMax,
    required this.targetRpe,
    this.warmupSets = 0,
    this.restSeconds = 180,
    this.notes,
  });

  factory ProgramExercise.fromJson(Map<String, dynamic> json) =>
      ProgramExercise(
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String,
        targetSets: (json['target_sets'] as num?)?.toInt() ?? 2,
        targetRepsMin: (json['target_reps_min'] as num?)?.toInt() ?? 0,
        targetRepsMax: (json['target_reps_max'] as num?)?.toInt() ?? 0,
        targetRpe: (json['target_rpe'] as num?)?.toDouble() ?? 8.5,
        warmupSets: (json['warmup_sets'] as num?)?.toInt() ?? 0,
        restSeconds: (json['rest_seconds'] as num?)?.toInt() ?? 180,
        notes: json['notes'] as String?,
      );

  final String exerciseId;
  final String exerciseName;
  final int targetSets;
  final int targetRepsMin;
  final int targetRepsMax;
  final double targetRpe;

  /// Ramped warm-up sets prescribed before the working sets (0 when none).
  final int warmupSets;
  final int restSeconds;
  final String? notes;

  bool get hasNotes => notes != null && notes!.isNotEmpty;

  bool get hasWarmupSets => warmupSets > 0;

  String get prescription =>
      '$targetSets × $targetRepsMin–$targetRepsMax @ RPE ${targetRpe.toStringAsFixed(1)}';

  String get restLabel => 'rest ${restSeconds}s';
}

/// `WarmupExerciseSchema`: a general preparation movement for a training day.
class WarmupExercise {
  const WarmupExercise({
    required this.exerciseName,
    this.exerciseId,
    this.sets = 2,
    this.reps = 10,
    this.restSeconds = 45,
    this.notes,
  });

  factory WarmupExercise.fromJson(Map<String, dynamic> json) => WarmupExercise(
        exerciseName: json['exercise_name'] as String,
        exerciseId: json['exercise_id'] as String?,
        sets: (json['sets'] as num?)?.toInt() ?? 2,
        reps: (json['reps'] as num?)?.toInt() ?? 10,
        restSeconds: (json['rest_seconds'] as num?)?.toInt() ?? 45,
        notes: json['notes'] as String?,
      );

  final String? exerciseId;
  final String exerciseName;
  final int sets;
  final int reps;
  final int restSeconds;
  final String? notes;

  bool get hasNotes => notes != null && notes!.isNotEmpty;

  String get prescription => '$sets × $reps · rest ${restSeconds}s';
}

class ProgramDay {
  const ProgramDay({
    required this.dayName,
    required this.dayOrder,
    this.warmupExercises = const <WarmupExercise>[],
    required this.exercises,
    this.cardio,
  });

  factory ProgramDay.fromJson(Map<String, dynamic> json) => ProgramDay(
        dayName: json['day_name'] as String,
        dayOrder: (json['day_order'] as num).toInt(),
        warmupExercises:
            (json['warmup_exercises'] as List<dynamic>? ?? const [])
                .map((dynamic e) =>
                    WarmupExercise.fromJson(e as Map<String, dynamic>))
                .toList(growable: false),
        exercises: (json['exercises'] as List<dynamic>? ?? const [])
            .map((dynamic e) =>
                ProgramExercise.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        cardio: json['cardio'] as String?,
      );

  final String dayName;
  final int dayOrder;
  final List<WarmupExercise> warmupExercises;
  final List<ProgramExercise> exercises;
  final String? cardio;

  bool get hasWarmup => warmupExercises.isNotEmpty;

  bool get hasCardio => cardio != null && cardio!.isNotEmpty;
}

/// `GeneratedProgramSchema` from `GET /programs/active`.
class TrainingProgram {
  const TrainingProgram({
    required this.programName,
    required this.splitType,
    required this.weeklyFrequency,
    required this.days,
    this.version,
    this.publishedByCoachAccountId,
  });

  factory TrainingProgram.fromJson(Map<String, dynamic> json) =>
      TrainingProgram(
        programName: json['program_name'] as String,
        splitType: json['split_type'] as String? ?? 'custom',
        weeklyFrequency: (json['weekly_frequency'] as num).toInt(),
        days: (json['days'] as List<dynamic>? ?? const [])
            .map((dynamic d) => ProgramDay.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
        version: (json['version'] as num?)?.toInt(),
        publishedByCoachAccountId:
            json['published_by_coach_account_id'] as String?,
      );

  final String programName;
  final String splitType;
  final int weeklyFrequency;
  final List<ProgramDay> days;

  /// Stable ledger version recorded at publication; null for legacy payloads.
  final int? version;

  /// Publishing coach's account id, or null for player self-service.
  final String? publishedByCoachAccountId;

  bool get isCoachPublished => publishedByCoachAccountId != null;
}

/// `GET /dashboard/personal-records` entry.
class PersonalRecord {
  const PersonalRecord({
    required this.exerciseId,
    required this.name,
    required this.recordType,
    required this.reps,
    required this.value,
    required this.achievedAt,
  });

  factory PersonalRecord.fromJson(Map<String, dynamic> json) => PersonalRecord(
        exerciseId: json['exercise_id'] as String,
        name: json['name'] as String? ?? json['exercise_id'] as String,
        recordType: json['record_type'] as String? ?? '',
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        value: (json['value'] as num?)?.toDouble() ?? 0,
        achievedAt: json['achieved_at'] as String? ?? '',
      );

  final String exerciseId;
  final String name;
  final String recordType;
  final int reps;
  final double value;
  final String achievedAt;
}
