import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/effort.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_segmented_control.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../core/workout_equipment.dart';
import '../../providers.dart';
import '../../router.dart';
import 'coach_assistant_screen.dart';
import 'coach_check_in_sheet.dart';
import 'coach_program_draft_screen.dart';
import 'coach_request_sheet.dart';
import 'program_publish_confirmation.dart';
import 'coach_shared.dart';

/// The player page (#120): one assigned player's open coach alerts on top,
/// then the **History · Check-ins** segments.
///
/// History carries this drill-down's original content — sessions, volume,
/// personal records, program requests, and per-exercise history — embedded
/// here rather than duplicated, so the roster row opens one page instead of a
/// second screen. Every read is gated by the active assignment server-side, so
/// a revoked or foreign assignment yields a denial and no training data.
/// Player-assistant chats never appear here.
class CoachPlayerHistoryScreen extends ConsumerStatefulWidget {
  const CoachPlayerHistoryScreen({
    super.key,
    required this.assignmentId,
    this.entry,
  });

  final CoachRosterEntry? entry;
  final String assignmentId;

  @override
  ConsumerState<CoachPlayerHistoryScreen> createState() =>
      _CoachPlayerHistoryScreenState();
}

class _GenerateDraftRequest {
  const _GenerateDraftRequest({
    required this.split,
    required this.repPreference,
    required this.frequency,
  });

  final String split;
  final String repPreference;
  final int frequency;

  Map<String, dynamic> toJson() => <String, dynamic>{
        if (split.isNotEmpty) 'user_split_override': split,
        'rep_preference_override': repPreference,
        'frequency_override': frequency,
      };
}

class _GenerateDraftDialog extends StatefulWidget {
  const _GenerateDraftDialog();

  @override
  State<_GenerateDraftDialog> createState() => _GenerateDraftDialogState();
}

class _GenerateDraftDialogState extends State<_GenerateDraftDialog> {
  final TextEditingController _split = TextEditingController();
  String _repPreference = 'balanced';
  int _frequency = 4;

  @override
  void dispose() {
    _split.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final copy = coachCopyOf(context);
    return AlertDialog(
      title: Text(copy.generateDraft),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          TextField(
            key: const Key('generate_draft_split_field'),
            controller: _split,
            decoration: InputDecoration(
              labelText: copy.split,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.md),
          DropdownButtonFormField<String>(
            key: const Key('generate_draft_rep_field'),
            initialValue: _repPreference,
            decoration: InputDecoration(
              labelText: copy.repRangePreference,
              border: const OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<String>>[
              DropdownMenuItem<String>(value: 'low', child: Text(copy.low)),
              DropdownMenuItem<String>(
                value: 'balanced',
                child: Text(copy.balanced),
              ),
              DropdownMenuItem<String>(value: 'high', child: Text(copy.high)),
            ],
            onChanged: (String? value) => setState(
              () => _repPreference = value ?? _repPreference,
            ),
          ),
          const SizedBox(height: MayosSpacing.md),
          DropdownButtonFormField<int>(
            key: const Key('generate_draft_frequency_field'),
            initialValue: _frequency,
            decoration: InputDecoration(
              labelText: copy.daysPerWeek,
              border: const OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<int>>[
              for (int day = 1; day <= 5; day++)
                DropdownMenuItem<int>(
                  value: day,
                  child: Text('$day', textDirection: TextDirection.ltr),
                ),
            ],
            onChanged: (int? value) => setState(
              () => _frequency = value ?? _frequency,
            ),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(copy.cancel),
        ),
        MayosButton(
          key: const Key('generate_draft_confirm_button'),
          label: copy.generate,
          expand: false,
          onPressed: () => Navigator.of(context).pop(
            _GenerateDraftRequest(
              split: _split.text.trim(),
              repPreference: _repPreference,
              frequency: _frequency,
            ),
          ),
        ),
      ],
    );
  }
}

class _CoachPlayerHistoryScreenState
    extends ConsumerState<CoachPlayerHistoryScreen> {
  late CoachRosterEntry _entry;
  bool _loading = true;
  FailureMessage? _error;
  bool _assignmentDenied = false;
  CoachPlayerSummary? _summary;
  CoachActiveProgram? _activeProgram;
  List<PersonalRecord> _records = const <PersonalRecord>[];
  List<CheckpointReviewListItem> _checkpointReviews =
      const <CheckpointReviewListItem>[];
  List<CoachPlayerExercise> _exercises = const <CoachPlayerExercise>[];
  final Map<String, CoachExerciseHistory> _histories =
      <String, CoachExerciseHistory>{};
  String? _openExerciseId;
  bool _loadingHistory = false;
  bool _generatingDraft = false;
  FailureMessage? _generateError;
  bool _copyingActiveProgram = false;
  bool _approvingActiveProgram = false;
  FailureMessage? _programActionError;
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  FailureMessage? _requestError;
  List<CheckIn> _checkIns = const <CheckIn>[];
  String? _nextFollowUpOn;
  List<CoachAlert> _alerts = const <CoachAlert>[];
  String? _busyAlertId;
  _PlayerSegment _segment = _PlayerSegment.history;

  /// Sequence numbers so a slower, older response can never overwrite the
  /// result of a newer one when revision bumps start overlapping loads (#120).
  int _loadSeq = 0;
  int _alertsSeq = 0;
  int _requestsSeq = 0;

  @override
  void initState() {
    super.initState();
    _entry = _routeEntry();
    _nextFollowUpOn = _entry.nextFollowUpOn;
    _load();
  }

  CoachRosterEntry _routeEntry() =>
      widget.entry ??
      CoachRosterEntry(
        assignmentId: widget.assignmentId,
        playerUsername: '',
        startedAt: '',
        status: 'active',
      );

  /// This assignment's open (new or acknowledged) alerts, as the player page
  /// shows them (#120).
  List<CoachAlert> _openAlerts(Iterable<CoachAlert> alerts) => alerts
      .where((CoachAlert alert) => alert.assignmentId == _entry.assignmentId)
      .toList(growable: false);

  Future<void> _load() async {
    final int seq = ++_loadSeq;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      await _loadRouteEntry(api, seq);
      if (!mounted || seq != _loadSeq) return;
      final List<Object> playerData = await _loadPlayerData(api);
      if (!mounted || seq != _loadSeq) return;
      _applyPlayerData(playerData);
    } on ApiException catch (error) {
      _showLoadError(error, seq);
    }
  }

  Future<void> _loadRouteEntry(ApiClient api, int seq) async {
    if (widget.entry != null) return;
    final List<CoachRosterEntry> roster = await api.coachAssignments();
    if (!mounted || seq != _loadSeq) return;
    for (final CoachRosterEntry row in roster) {
      if (row.assignmentId == widget.assignmentId) {
        _entry = row;
        break;
      }
    }
    if (mounted && seq == _loadSeq) {
      setState(() => _nextFollowUpOn = _entry.nextFollowUpOn);
    }
  }

  Future<List<Object>> _loadPlayerData(ApiClient api) =>
      Future.wait<Object>(<Future<Object>>[
        api.coachAlerts(states: <String>['new', 'acknowledged']),
        api.coachPlayerSummary(_entry.assignmentId),
        api.coachPlayerPersonalRecords(_entry.assignmentId),
        api.coachCheckpointReviews(_entry.assignmentId),
        api.coachPlayerExercises(_entry.assignmentId),
        api.coachProgramRequests(_entry.assignmentId),
        api.coachCheckIns(_entry.assignmentId),
        api.coachActiveProgram(_entry.assignmentId),
      ]);

  void _applyPlayerData(List<Object> playerData) {
    setState(() {
      _alerts = _openAlerts(playerData[0] as List<CoachAlert>);
      _summary = playerData[1] as CoachPlayerSummary;
      _records = playerData[2] as List<PersonalRecord>;
      _checkpointReviews = playerData[3] as List<CheckpointReviewListItem>;
      _exercises = playerData[4] as List<CoachPlayerExercise>;
      _programRequests =
          sortCoachRequests(playerData[5] as List<ProgramRequest>);
      _checkIns = sortCheckInsNewestFirst(playerData[6] as List<CheckIn>);
      _activeProgram = playerData[7] as CoachActiveProgram;
      _loading = false;
      _assignmentDenied = false;
      _requestError = null;
    });
  }

  void _showLoadError(ApiException error, int seq) {
    if (!mounted || seq != _loadSeq) return;
    if (error.statusCode == 403) {
      ref
          .read(coachAssistantControllerProvider.notifier)
          .clearFor(_entry.assignmentId);
    }
    setState(() {
      _loading = false;
      _assignmentDenied = error.statusCode == 403;
      _error = error.statusCode == 403 ? null : apiFailureMessage(error);
    });
  }

  /// Refetches only the open alerts: saving a check-in can resolve a
  /// follow-up on the service side, and the page must show that (#120).
  Future<void> _loadAlerts() async {
    final int seq = ++_alertsSeq;
    try {
      final List<CoachAlert> alerts = await ref
          .read(apiClientProvider)
          .coachAlerts(states: <String>['new', 'acknowledged']);
      if (!mounted || seq != _alertsSeq) return;
      setState(() => _alerts = _openAlerts(alerts));
    } on ApiException {
      // Keep the alerts already on screen; the Alerts tab refetches its own
      // copy from the revision bump this save published.
    }
  }

  /// Refetches only this assignment's program requests: a refused resolve
  /// must refresh the list so a request answered elsewhere shows its true
  /// state (#121), without blanking the whole page.
  Future<void> _loadRequests() async {
    final int seq = ++_requestsSeq;
    try {
      final List<ProgramRequest> requests = sortCoachRequests(await ref
          .read(apiClientProvider)
          .coachProgramRequests(_entry.assignmentId));
      if (!mounted || seq != _requestsSeq) return;
      setState(() {
        _programRequests = requests;
        _requestError = null;
      });
    } on ApiException catch (error) {
      if (!mounted || seq != _requestsSeq) return;
      // A failed refresh is surfaced like every other load error (#121).
      setState(() => _requestError = apiFailureMessage(error));
    }
  }

  Future<void> _toggleExercise(CoachPlayerExercise exercise) async {
    if (_openExerciseId == exercise.id) {
      setState(() => _openExerciseId = null);
      return;
    }
    setState(() {
      _openExerciseId = exercise.id;
      _loadingHistory = true;
    });
    if (_histories.containsKey(exercise.id)) {
      setState(() => _loadingHistory = false);
      return;
    }
    try {
      final CoachExerciseHistory history = await ref
          .read(apiClientProvider)
          .coachPlayerExerciseHistory(_entry.assignmentId, exercise.id);
      if (!mounted) return;
      setState(() {
        _histories[exercise.id] = history;
        _loadingHistory = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingHistory = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  Future<void> _openGenerateDraftDialog() async {
    final _GenerateDraftRequest? request = await showDialog<_GenerateDraftRequest>(
      context: context,
      builder: (BuildContext context) => const _GenerateDraftDialog(),
    );
    if (request == null || !mounted) return;
    await _generateDraft(request);
  }

  Future<void> _generateDraft(_GenerateDraftRequest request) async {
    setState(() {
      _generatingDraft = true;
      _generateError = null;
    });
    try {
      try {
        await ref.read(apiClientProvider).coachGenerateProgramDraft(
              _entry.assignmentId,
              generationOverrides: request.toJson(),
            );
      } on ApiException catch (error) {
        if (error.statusCode != 409) rethrow;
        final bool replace = await _confirmProgramDraftReplacement();
        if (!mounted || !replace) return;
        await ref.read(apiClientProvider).coachReplaceGeneratedProgramDraft(
              _entry.assignmentId,
              generationOverrides: request.toJson(),
            );
      }
      if (!mounted) return;
      _openProgramDraft();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _generateError = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _generatingDraft = false);
    }
  }

  Future<bool> _confirmProgramDraftReplacement() async {
    final copy = coachCopyOf(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text(copy.replaceProgramDraftTitle),
            content: Text(copy.replaceProgramDraftPrompt),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(copy.cancel),
              ),
              TextButton(
                key: const Key('generate_draft_replace_confirm'),
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(copy.replaceProgramDraftAction),
              ),
            ],
          ),
        ) ??
        false;
  }

  /// Opens the resolve sheet and runs the shared post-resolve flow (#121):
  /// snackbar, the Requests badge and roster chip revisions, the page's own
  /// refresh, and — on a refusal (an already-answered request, a stale
  /// target) — the readable message it refreshes from.
  Future<void> _resolveRequest(ProgramRequest request) async {
    setState(() => _requestError = null);
    final CoachRequestResolution result = await showCoachRequestResolveSheet(
      context,
      request: request,
      playerUsername: _entry.playerUsername,
    );
    if (!mounted) return;
    await applyCoachRequestAction(
      ref,
      context: context,
      result: result,
      // An applied request republishes the program, so the whole page
      // refetches; a refusal only needs this segment's list back.
      reload: () => result.resolved ? _load() : _loadRequests(),
      showError: (FailureMessage failure) =>
          setState(() => _requestError = failure),
      // The Requests tab listens on its revision and republishes the badge.
      notifyRequestsTab: true,
    );
  }

  /// The header **Log check-in** action and the Check-ins segment's button
  /// open the same sheet (#120): channel, optional note, dated today.
  Future<void> _openCheckInSheet() async {
    await showLogCheckInSheet(
      context,
      assignmentId: _entry.assignmentId,
      playerUsername: _entry.playerUsername,
      onSaved: _onCheckInSaved,
    );
  }

  /// Saves land here: the check-in list and the next follow-up update
  /// immediately, the open alerts are refetched (the service may resolve the
  /// follow-up this check-in satisfied), and both the Alerts tab badge and the
  /// roster row are told to refetch (#120).
  void _onCheckInSaved(CheckInCreation created) {
    if (!mounted) return;
    setState(() {
      _checkIns =
          sortCheckInsNewestFirst(<CheckIn>[created.checkIn, ..._checkIns]);
      if (created.nextFollowUpOn != null) {
        _nextFollowUpOn = created.nextFollowUpOn;
      }
    });
    _loadAlerts();
    ref.read(coachAlertsRevisionProvider.notifier).state++;
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(coachCopyOf(context).checkInRecorded)),
    );
  }

  /// Acknowledge / resolve through the existing alert client calls, then
  /// publish the shared badge and revision updates and drop a resolved alert
  /// from the open list (#120).
  Future<void> _applyAlert(
    CoachAlert alert,
    Future<CoachAlert> Function() action,
  ) async {
    setState(() => _busyAlertId = alert.alertId);
    try {
      final CoachAlert updated = await applyCoachAlertAction(
        ref,
        action,
        wasNew: alert.isNew,
      );
      if (!mounted) return;
      setState(() {
        _busyAlertId = null;
        _alerts = updated.isResolved
            ? _alerts
                .where((CoachAlert row) => row.alertId != updated.alertId)
                .toList(growable: false)
            : _alerts
                .map((CoachAlert row) =>
                    row.alertId == updated.alertId ? updated : row)
                .toList(growable: false);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _busyAlertId = null);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            displayCopyOf(context).failureMessage(apiFailureMessage(error)),
          ),
        ),
      );
    }
  }

  Widget _checkInsSegment(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          copy.nextFollowUpLabel(_nextFollowUpOn),
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: MayosButton(
            key: const Key('record_check_in_button'),
            label: copy.logCheckIn,
            icon: Icons.note_add_outlined,
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: _openCheckInSheet,
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (_checkIns.isEmpty)
          Text(
            copy.noRecordedCheckIns,
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final CheckIn checkIn in _checkIns)
            MayosSettingsTile(
              key: Key('check_in_${checkIn.checkInId}'),
              icon: Icons.forum_outlined,
              title: copy.checkInTitle(
                checkIn.checkedInOn,
                copy.checkInChannel(checkIn.channel),
              ),
              subtitle: checkIn.note == null || checkIn.note!.isEmpty
                  ? null
                  : checkIn.note!,
            ),
      ],
    );
  }

  /// The **Requests (count)** segment (#121): this assignment's program
  /// requests in the tab's order, with the shared resolve sheet. A pending
  /// row opens the sheet; answered rows are read-only.
  Widget _requestsSegment(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: copy.programRequests),
        if (_requestError != null) ...<Widget>[
          Text(
            displayCopyOf(context).failureMessage(_requestError!),
            style: MayosTypography.bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_programRequests.isEmpty)
          Text(
            copy.noProgramRequests,
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final ProgramRequest request in _programRequests)
            CoachRequestCard(
              request: request,
              playerUsername: _entry.playerUsername,
              onTap: () => _resolveRequest(request),
            ),
      ],
    );
  }

  /// One card of the History segment: a [MayosSectionHeader] over its
  /// children, so every section heading in this drill-down is the shared
  /// component (#121).
  Widget _section(BuildContext context, String title, List<Widget> children) {
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MayosSectionHeader(
            title: title,
            padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
          ),
          ...children,
        ],
      ),
    );
  }

  Widget _volumeCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final Map<String, double> volume = _summary!.volume;
    final List<MapEntry<String, double>> entries = volume.entries
        .where((MapEntry<String, double> entry) => entry.value > 0)
        .toList(growable: false);
    return _section(
      context,
      copy.playerVolume,
      entries.isEmpty
          ? <Widget>[Text(copy.noVolume)]
          : <Widget>[
              for (final MapEntry<String, double> entry in entries)
                Text(copy.volumeValue(entry.key, '${entry.value}')),
            ],
    );
  }

  Widget _scheduleCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final CoachPlayerSchedule? schedule = _summary!.schedule;
    final List<Widget> children = <Widget>[];
    if (schedule != null) {
      final String days = schedule.weekdays.map(copy.weekday).join(', ');
      children.add(Text(copy.expectedDays(days)));
      children.add(Text(copy.timezone(schedule.timezone)));
    }
    for (final CoachPlayerPause pause in _summary!.pauses) {
      children.add(Text(copy.pauseDates(pause.startsOn, pause.endsOn)));
    }
    return _section(context, copy.trainingSchedule, children);
  }

  Widget _latestSessionCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final CoachPlayerLatestSession? latest = _summary!.latestSession;
    if (latest == null) {
      return _section(
          context, copy.latestSession, <Widget>[Text(copy.noSessions)]);
    }
    final String? versionNote = copy.historicalProgramIfNeeded(
      latest.programVersion,
      latest.activeProgramVersionAtSync,
      latest.isHistoricalProgram,
    );
    return _section(context, copy.latestSession, <Widget>[
      Text(copy.sessionTitle(latest.splitName, latest.sessionDate)),
      Text(copy.setsAndVolume(
          latest.setsCount, latest.totalVolumeKg.toStringAsFixed(1))),
      if (latest.warmupMovements.isNotEmpty)
        Text(copy.movementCount(latest.warmupMovements.length)),
      if (latest.cardio != null)
        Text(copy.cardioMinutes(latest.cardio!.minutes)),
      if (latest.readinessScore != null)
        Text(copy.readiness(latest.readinessScore!)),
      if (versionNote != null) Text(versionNote),
      for (final PerformedDateCorrection correction in latest.corrections)
        Text(copy.correctedDate(
            correction.previousDate, correction.correctedDate)),
      const SizedBox(height: MayosSpacing.xs),
      for (final CoachPlayerSessionExercise exercise in latest.exercises)
        Text(copy.sessionExercise(exercise.name, exercise.sets,
            exercise.volumeKg.toStringAsFixed(1))),
      for (final CoachPlayerDivergence divergence in latest.divergences)
        Text(_divergenceLabel(divergence)),
    ]);
  }

  String _divergenceLabel(CoachPlayerDivergence divergence) {
    final String kind = switch (divergence.kind) {
      'skipped' => 'Skipped',
      'unplanned' => 'Unplanned',
      _ => divergence.kind,
    };
    return coachCopyOf(context).divergence(kind, divergence.exerciseName);
  }

  Widget _recentSessionsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final List<CoachPlayerRecentSession> sessions = _summary!.recentSessions;
    return _section(
      context,
      copy.recentSessions,
      sessions.isEmpty
          ? <Widget>[Text(copy.noSessions)]
          : <Widget>[
              for (final CoachPlayerRecentSession session in sessions)
                _recentSessionTile(session),
            ],
    );
  }

  Widget _recentSessionTile(CoachPlayerRecentSession session) {
    final copy = coachCopyOf(context);
    final String? versionNote = copy.historicalProgramIfNeeded(
      session.programVersion,
      session.activeProgramVersionAtSync,
      session.isHistoricalProgram,
    );
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      title: Text(copy.sessionTitle(session.splitName, session.sessionDate)),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(copy.setsAndVolume(
              session.setsCount, session.totalVolumeKg.toStringAsFixed(1))),
          if (session.warmupMovements.isNotEmpty)
            Text(copy.movementCount(session.warmupMovements.length)),
          if (session.cardio != null)
            Text(copy.cardioMinutes(session.cardio!.minutes)),
          if (versionNote != null) Text(versionNote),
          for (final PerformedDateCorrection correction in session.corrections)
            Text(copy.correctedDate(
                correction.previousDate, correction.correctedDate)),
          for (final CoachPlayerDivergence divergence in session.divergences)
            Text(_divergenceLabel(divergence)),
        ],
      ),
    );
  }

  Widget _recordsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    return _section(
      context,
      copy.personalRecordsTitle,
      _records.isEmpty
          ? <Widget>[Text(copy.noPersonalRecords)]
          : <Widget>[
              for (final PersonalRecord record in _records)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(record.name),
                  subtitle: Text(copy.recordSummary(
                      record.recordType, '${record.value}', record.reps)),
                ),
            ],
    );
  }

  Widget _checkpointReviewsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    return _section(
      context,
      copy.checkpoints,
      _checkpointReviews.isEmpty
          ? <Widget>[Text(copy.noCheckpoints)]
          : <Widget>[
              for (final CheckpointReviewListItem review in _checkpointReviews)
                ListTile(
                  key:
                      ValueKey<String>('coach.checkpoint.${review.checkpoint}'),
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(copy.checkpointNumber(review.checkpoint)),
                  subtitle: Text(copy.checkpointPeriod(
                      review.periodStart, review.periodEnd)),
                  trailing: Icon(
                    Directionality.of(context) == TextDirection.rtl
                        ? Icons.chevron_left
                        : Icons.chevron_right,
                  ),
                  onTap: () => context.push(
                    '$checkpointReviewPath/${review.checkpoint}'
                    '?assignment_id=${_entry.assignmentId}',
                  ),
                ),
            ],
    );
  }

  Widget _exerciseDetail(BuildContext context, String exerciseId) {
    final copy = coachCopyOf(context);
    if (_loadingHistory) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final CoachExerciseHistory? history = _histories[exerciseId];
    if (history == null) {
      return const SizedBox.shrink();
    }
    final CoachExerciseHistoryPoint? latest =
        history.history.isEmpty ? null : history.history.last;
    final bool latestZeroLoadUsesEquipmentLabel = latest != null &&
        zeroLoadLabelKind(latest.weightKg, history.equipment) != null;

    Widget historyPoint(CoachExerciseHistoryPoint point) {
      final WorkoutEquipmentKind? labelKind =
          zeroLoadLabelKind(point.weightKg, history.equipment);
      return Text(copy.exerciseHistoryPoint(
        point.date,
        labelKind == null
            ? '${point.weightKg}'
            : workoutCopyOf(context).zeroLoadWeightLabel(labelKind),
        point.reps,
        weightUnit: exerciseWeightUnit(point.weightKg, history.equipment),
        rir: point.rpe == null ? null : rirLabel(point.rpe!),
        e1rm: labelKind == null ? '${point.e1rm}' : null,
      ));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (history.caption != null && !latestZeroLoadUsesEquipmentLabel)
          Text(history.caption!),
        const SizedBox(height: MayosSpacing.xxs),
        if (history.history.isEmpty)
          Text(copy.noExerciseSets)
        else
          for (final CoachExerciseHistoryPoint point in history.history)
            // Effort is hidden when nobody rated the set, as this line always
            // was; a rated one reads as RIR (#111).
            historyPoint(point),
        if (history.records.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          Text(copy.records),
          for (final CoachExerciseRecord record in history.records)
            Text(copy.recordHistory(record.recordType, '${record.value}',
                record.reps, record.achievedAt)),
        ],
      ],
    );
  }

  Widget _exercisesCard(BuildContext context) {
    final copy = coachCopyOf(context);
    return _section(
      context,
      copy.exercises,
      _exercises.isEmpty
          ? <Widget>[Text(copy.noExercisesLogged)]
          : <Widget>[
              for (final CoachPlayerExercise exercise in _exercises)
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  initiallyExpanded: _openExerciseId == exercise.id,
                  onExpansionChanged: (_) => _toggleExercise(exercise),
                  title: Text(exercise.name),
                  children: <Widget>[_exerciseDetail(context, exercise.id)],
                ),
            ],
    );
  }

  Widget _programCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final CoachActiveProgram active = _activeProgram!;
    final List<Widget> children = <Widget>[
      if (active.hasDraft) _pendingProgramDraftBadge(context),
    ];
    if (active.program == null) {
      children.add(
        Text(
          copy.noActiveProgram,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
      );
    } else {
      children.addAll(_programDetails(context, active, active.program!));
      children.add(const SizedBox(height: MayosSpacing.sm));
      children.add(_activeProgramActions(context));
    }
    if (_programActionError != null) {
      children.addAll(<Widget>[
        const SizedBox(height: MayosSpacing.sm),
        Text(
          displayCopyOf(context).failureMessage(_programActionError!),
          style: MayosTypography.bodySecondary.copyWith(color: c.danger),
        ),
      ]);
    }
    return _section(context, copy.program, children);
  }

  Widget _activeProgramActions(BuildContext context) {
    final copy = coachCopyOf(context);
    final bool busy = _copyingActiveProgram || _approvingActiveProgram;
    final bool canApprove = _activeProgram?.program?.version != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosButton(
          key: const Key('coach_program_edit_active'),
          label: copy.editActiveProgram,
          icon: Icons.edit_outlined,
          variant: MayosButtonVariant.secondary,
          loading: _copyingActiveProgram,
          onPressed: busy ? null : _editActiveProgram,
        ),
        const SizedBox(height: MayosSpacing.xs),
        MayosButton(
          key: const Key('coach_program_approve_as_is'),
          label: copy.approveProgramAsIs,
          icon: Icons.check,
          loading: _approvingActiveProgram,
          onPressed: busy || !canApprove ? null : _approveActiveProgramAsIs,
        ),
      ],
    );
  }

  Widget _pendingProgramDraftBadge(BuildContext context) => Align(
        alignment: AlignmentDirectional.centerStart,
        child: Chip(
          key: const Key('coach_program_pending_draft'),
          label: Text(coachCopyOf(context).pendingProgramDraft),
        ),
      );

  List<Widget> _programDetails(
    BuildContext context,
    CoachActiveProgram active,
    TrainingProgram program,
  ) {
    final copy = coachCopyOf(context);
    final String? activeDate = active.activeSince?.split('T').first;
    return <Widget>[
      Text(active.provenance == 'coach'
          ? copy.publishedByYou
          : copy.generatedAutomatically),
      if (active.editedByPlayer) Text(copy.editedByPlayer),
      if (program.version != null) Text(copy.programVersion(program.version!)),
      if (activeDate != null) Text(copy.activeProgramSince(activeDate)),
      Text(program.programName),
      for (final ProgramDay day in program.days) _programDay(context, day),
    ];
  }

  Widget _programDay(BuildContext context, ProgramDay day) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            day.dayName,
            style: MayosTypography.body.copyWith(color: c.textPrimary),
          ),
          for (final ProgramExercise exercise in day.exercises)
            _programExercise(context, exercise),
        ],
      ),
    );
  }

  Widget _programExercise(BuildContext context, ProgramExercise exercise) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(start: MayosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: _programExerciseDetails(context, exercise),
      ),
    );
  }

  List<Widget> _programExerciseDetails(
    BuildContext context,
    ProgramExercise exercise,
  ) {
    final copy = coachCopyOf(context);
    return <Widget>[
      Text(exercise.exerciseName),
      Text(
        copy.programPrescription(
          copy.programWorkingSets(exercise.targetSets),
          copy.programRepRange(
            exercise.targetRepsMin,
            exercise.targetRepsMax,
          ),
          minRirLabel(exercise.targetRpe),
          exercise.restSecondsOrDefault,
        ),
        style: MayosTypography.bodySecondary,
      ),
      if (exercise.tempo != null && exercise.tempo!.isNotEmpty)
        Text(copy.programTempo(exercise.tempo!)),
      if (exercise.notes != null && exercise.notes!.isNotEmpty)
        Text(copy.programNotes(exercise.notes!)),
    ];
  }

  /// The segment label counts what still needs the coach (#121): the pending
  /// requests, or no number once nothing is waiting.
  int get _pendingRequests => _programRequests
      .where((ProgramRequest request) => request.isPending)
      .length;

  @override
  Widget build(BuildContext context) {
    final CoachRosterEntry entry = _entry;
    final copy = coachCopyOf(context);
    final bool assistantEnabled =
        ref.watch(authControllerProvider).session?.account.coachAiEnabled ??
            false;
    final bool phoneAssignmentRoute = !isDesktopLayout(context);
    return PopScope<void>(
      onPopInvokedWithResult: (bool didPop, _) {
        if (didPop) {
          ref.read(coachRosterRevisionProvider.notifier).state++;
        }
      },
      child: Scaffold(
        appBar: AppBar(
          key: const Key('coach_player_history_app_bar'),
          automaticallyImplyLeading: false,
          leading: phoneAssignmentRoute
              ? BackButton(
                  onPressed: () {
                    if (GoRouter.of(context).canPop()) {
                      context.pop();
                    } else {
                      ref.read(coachRosterRevisionProvider.notifier).state++;
                      context.go(coachRosterPath);
                    }
                  },
                )
              : null,
          title: Text(entry.playerUsername),
          actions: _assignmentDenied
              ? const <Widget>[]
              : <Widget>[
                  TextButton(
                    key: const Key('log_check_in_action'),
                    onPressed: _loading ? null : _openCheckInSheet,
                    child: Text(copy.logCheckInAction),
                  ),
                  PopupMenuButton<_PlayerAction>(
                    key: const Key('player_page_actions'),
                    icon: const Icon(Icons.more_vert),
                    onSelected: (_PlayerAction action) {
                      switch (action) {
                        case _PlayerAction.writeProgram:
                          _openProgramDraft();
                        case _PlayerAction.generateDraft:
                          if (!_generatingDraft) {
                            _openGenerateDraftDialog();
                          }
                        case _PlayerAction.askAssistant:
                          _openAssistant();
                      }
                    },
                    itemBuilder: (BuildContext context) =>
                        <PopupMenuEntry<_PlayerAction>>[
                      PopupMenuItem<_PlayerAction>(
                        key: const Key('write_program_action'),
                        value: _PlayerAction.writeProgram,
                        child: Text(copy.writeProgram),
                      ),
                      PopupMenuItem<_PlayerAction>(
                        key: const Key('generate_draft_action'),
                        value: _PlayerAction.generateDraft,
                        enabled: !_generatingDraft,
                        child: Text(copy.generateDraft),
                      ),
                      if (assistantEnabled)
                        PopupMenuItem<_PlayerAction>(
                          key: Key('coach_assistant_entry'),
                          value: _PlayerAction.askAssistant,
                          child: Text(copy.askAssistant),
                        ),
                    ],
                  ),
                ],
        ),
        body: Column(
          children: <Widget>[
            const OfflineBannerSlot(),
            Expanded(child: _buildBody(context)),
          ],
        ),
      ),
    );
  }

  /// Opens the in-memory coach assistant for this one player (#45). The entry
  /// exists only when the service reports the feature enabled.
  void _openAssistant() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachAssistantScreen(entry: _entry),
      ),
    );
  }

  void _openProgramDraft() {
    Navigator.of(context)
        .push<TrainingProgram>(
      MaterialPageRoute<TrainingProgram>(
        builder: (BuildContext context) => CoachProgramDraftScreen(
          assignmentId: _entry.assignmentId,
          playerUsername: _entry.playerUsername,
        ),
      ),
    )
        .then((TrainingProgram? program) async {
      if (!mounted) return;
      if (program != null) {
        ref.read(coachRosterRevisionProvider.notifier).state++;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              coachCopyOf(context).programPublished(program.version),
            ),
          ),
        );
      }
      await _load();
    });
  }

  Future<void> _editActiveProgram() async {
    final CoachActiveProgram? active = _activeProgram;
    if (active?.program == null) return;
    final _ExistingDraftChoice? choice = active!.hasDraft
        ? await _chooseExistingDraftAction()
        : _ExistingDraftChoice.copyActive;
    if (!mounted || choice == null) return;
    if (choice == _ExistingDraftChoice.continueDraft) {
      _openProgramDraft();
      return;
    }
    await _copyActiveProgramDraft(
      replace: choice == _ExistingDraftChoice.replaceWithActive,
    );
  }

  Future<void> _copyActiveProgramDraft({bool replace = false}) async {
    setState(() {
      _copyingActiveProgram = true;
      _programActionError = null;
    });
    try {
      await ref.read(apiClientProvider).coachCopyActiveProgramToDraft(
            _entry.assignmentId,
            replace: replace,
          );
      if (mounted) _openProgramDraft();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _copyingActiveProgram = false);
    }
  }

  Future<_ExistingDraftChoice?> _chooseExistingDraftAction() =>
      showDialog<_ExistingDraftChoice>(
        context: context,
        builder: (BuildContext context) {
          final copy = coachCopyOf(context);
          return AlertDialog(
            title: Text(copy.programDraftChoiceTitle),
            content: Text(copy.programDraftChoicePrompt),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text(copy.cancel),
              ),
              TextButton(
                key: const Key('coach_program_continue_draft'),
                onPressed: () => Navigator.of(context)
                    .pop(_ExistingDraftChoice.continueDraft),
                child: Text(copy.continueProgramDraft),
              ),
              TextButton(
                key: const Key('coach_program_replace_draft'),
                onPressed: () => Navigator.of(context)
                    .pop(_ExistingDraftChoice.replaceWithActive),
                child: Text(copy.replaceDraftWithActiveProgram),
              ),
            ],
          );
        },
      );

  Future<void> _approveActiveProgramAsIs() async {
    final CoachActiveProgram? active = _activeProgram;
    final int? expectedVersion = active?.program?.version;
    if (expectedVersion == null) return;
    List<ProgramRequest> requests;
    try {
      requests = (await ref
              .read(apiClientProvider)
              .coachProgramRequests(_entry.assignmentId))
          .where((ProgramRequest request) => request.isPending)
          .toList(growable: false);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
      return;
    }
    if (!mounted) return;
    final List<String>? resolveRequestIds =
        await _confirmApproveActiveProgram(requests);
    if (!mounted || resolveRequestIds == null) return;
    await _publishActiveProgramAsIs(
      expectedVersion,
      resolveRequestIds: resolveRequestIds,
    );
  }

  Future<void> _publishActiveProgramAsIs(
    int expectedActiveVersion, {
    required List<String> resolveRequestIds,
  }) async {
    setState(() {
      _approvingActiveProgram = true;
      _programActionError = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final TrainingProgram published = await api.coachApproveActiveProgram(
        _entry.assignmentId,
        expectedActiveVersion: expectedActiveVersion,
        resolveRequestIds: resolveRequestIds,
      );
      if (mounted) await _showPublishedProgram(published);
    } on ApiException catch (error) {
      if (error.errorCode == 'program_version_mismatch') {
        await _load();
        if (mounted) {
          setState(
            () => _programActionError = const AppFailureMessage(
              AppFailureId.coachProgramChanged,
              "The player's program changed. Review it and approve again.",
            ),
          );
        }
      } else if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _approvingActiveProgram = false);
    }
  }

  Future<void> _showPublishedProgram(TrainingProgram published) async {
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(coachCopyOf(context).programPublished(published.version)),
      ),
    );
    await _load();
  }

  Future<List<String>?> _confirmApproveActiveProgram(
    List<ProgramRequest> requests,
  ) async {
    final copy = coachCopyOf(context);
    return showProgramPublishConfirmation(
      context,
      ProgramPublishConfirmation(
        title: copy.confirmApproveProgramTitle,
        prompt: copy.approveProgramAsIsPrompt,
        confirmLabel: copy.confirmApproveProgram,
        cancelLabel: copy.cancel,
        confirmKey: 'coach_program_approve_confirm',
        requests: requests,
      ),
    );
  }

  /// One open coach alert with its actions (#120): acknowledge and resolve
  /// through the existing alert client calls, plus **Log check-in** while a
  /// follow-up is due.
  Widget _alertCard(BuildContext context, CoachAlert alert) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final bool busy = _busyAlertId == alert.alertId;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('player_alert_${alert.alertId}'),
        borderColor: alert.isNew ? c.danger : c.border,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: FirstStrongDirection(
                    text: alert.description,
                    child: Text(
                      alert.description,
                      style:
                          MayosTypography.body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ),
                coachAlertStateChip(context, alert),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            Wrap(
              spacing: MayosSpacing.xs,
              runSpacing: MayosSpacing.xs,
              children: <Widget>[
                if (alert.isFollowUpDue)
                  MayosButton(
                    label: copy.logCheckInAction,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : _openCheckInSheet,
                  ),
                if (alert.isNew)
                  MayosButton(
                    label: copy.acknowledge,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy
                        ? null
                        : () => _applyAlert(
                              alert,
                              () => ref
                                  .read(apiClientProvider)
                                  .acknowledgeCoachAlert(alert.alertId),
                            ),
                  ),
                if (!alert.isResolved)
                  MayosButton(
                    label: copy.resolve,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    loading: busy,
                    onPressed: busy
                        ? null
                        : () => _applyAlert(
                              alert,
                              () => ref
                                  .read(apiClientProvider)
                                  .resolveCoachAlert(alert.alertId),
                            ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null || _assignmentDenied) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                  _assignmentDenied
                      ? copy.noActiveAssignment
                      : displayCopyOf(context).failureMessage(_error!),
                  textAlign: TextAlign.center,
                  style: MayosTypography.body.copyWith(color: c.textPrimary)),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: copy.retry,
                expand: false,
                onPressed: _load,
              ),
            ],
          ),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(MayosSpacing.md),
      children: <Widget>[
        if (_generateError != null) ...<Widget>[
          Text(
            displayCopyOf(context).failureMessage(_generateError!),
            style: MayosTypography.bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_alerts.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Text(copy.openAlerts,
              style: MayosTypography.sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          for (final CoachAlert alert in _alerts) _alertCard(context, alert),
        ],
        const SizedBox(height: MayosSpacing.md),
        MayosSegmentedControl<_PlayerSegment>(
          segments: <MayosSegment<_PlayerSegment>>[
            MayosSegment<_PlayerSegment>(
                value: _PlayerSegment.history, label: copy.history),
            MayosSegment<_PlayerSegment>(
                value: _PlayerSegment.checkIns, label: copy.checkIns),
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.requests,
              label: _pendingRequests > 0
                  ? copy.requestsWithCount(_pendingRequests)
                  : copy.requests,
            ),
          ],
          selected: _segment,
          onChanged: (_PlayerSegment value) => setState(() => _segment = value),
        ),
        const SizedBox(height: MayosSpacing.md),
        if (_segment == _PlayerSegment.history)
          ..._historyChildren(context)
        else if (_segment == _PlayerSegment.checkIns)
          _checkInsSegment(context)
        else
          _requestsSegment(context),
      ],
    );
  }

  /// The original drill-down content (#25), embedded as the History segment
  /// of the player page (#120) instead of being duplicated here.
  List<Widget> _historyChildren(BuildContext context) {
    final CoachPlayerSummary summary = _summary!;
    return <Widget>[
      Text(coachCopyOf(context).since(summary.startedAt),
          style: MayosTypography.bodySecondary),
      const SizedBox(height: MayosSpacing.sm),
      _programCard(context),
      const SizedBox(height: MayosSpacing.sm),
      _volumeCard(context),
      const SizedBox(height: MayosSpacing.sm),
      if (summary.schedule != null || summary.pauses.isNotEmpty) ...<Widget>[
        _scheduleCard(context),
        const SizedBox(height: MayosSpacing.sm),
      ],
      _latestSessionCard(context),
      const SizedBox(height: MayosSpacing.sm),
      _recentSessionsCard(context),
      const SizedBox(height: MayosSpacing.sm),
      _recordsCard(context),
      const SizedBox(height: MayosSpacing.sm),
      _checkpointReviewsCard(context),
      const SizedBox(height: MayosSpacing.sm),
      _exercisesCard(context),
    ];
  }
}

/// The player page's segments (#120/#121).
enum _PlayerSegment {
  history,
  checkIns,
  requests,
}

/// The player page's overflow actions (#G).
enum _PlayerAction {
  writeProgram,
  generateDraft,
  askAssistant,
}

enum _ExistingDraftChoice {
  copyActive,
  continueDraft,
  replaceWithActive,
}
