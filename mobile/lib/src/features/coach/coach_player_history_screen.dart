import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/connectivity.dart';
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
import '../../providers.dart';
import '../../router.dart';
import 'coach_assistant_screen.dart';
import 'coach_check_in_sheet.dart';
import 'coach_request_sheet.dart';
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

class _PublishRequest {
  const _PublishRequest({
    required this.split,
    required this.repPreference,
    required this.frequency,
  });

  final String split;
  final String repPreference;
  final int frequency;
}

class _CoachPlayerHistoryScreenState
    extends ConsumerState<CoachPlayerHistoryScreen> {
  late CoachRosterEntry _entry;
  bool _loading = true;
  String? _error;
  bool _assignmentDenied = false;
  CoachPlayerSummary? _summary;
  List<PersonalRecord> _records = const <PersonalRecord>[];
  List<CheckpointReviewListItem> _checkpointReviews =
      const <CheckpointReviewListItem>[];
  List<CoachPlayerExercise> _exercises = const <CoachPlayerExercise>[];
  final Map<String, CoachExerciseHistory> _histories =
      <String, CoachExerciseHistory>{};
  String? _openExerciseId;
  bool _loadingHistory = false;
  bool _publishing = false;
  String? _publishError;
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  String? _requestError;
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

  CoachRosterEntry _routeEntry() => widget.entry ??
      CoachRosterEntry(
        assignmentId: widget.assignmentId,
        playerUsername: '',
        startedAt: '',
        status: 'active',
      );

  /// This assignment's open (new or acknowledged) alerts, as the player page
  /// shows them (#120).
  List<CoachAlert> _openAlerts(Iterable<CoachAlert> alerts) => alerts
      .where(
          (CoachAlert alert) => alert.assignmentId == _entry.assignmentId)
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
      _error = error.statusCode == 403
          ? 'No active assignment.'
          : error.message;
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
      setState(() => _requestError = error.message);
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
        _error = error.message;
      });
    }
  }

  Future<void> _openPublishDialog() async {
    final TextEditingController split = TextEditingController();
    String repPreference = 'balanced';
    int frequency = 4;
    final _PublishRequest? request = await showDialog<_PublishRequest>(
      context: context,
      builder: (BuildContext context) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: const Text('Publish program'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              TextField(
                key: const Key('publish_split_field'),
                controller: split,
                decoration: const InputDecoration(
                  labelText: 'Split override (optional)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: MayosSpacing.md),
              DropdownButtonFormField<String>(
                key: const Key('publish_rep_field'),
                initialValue: repPreference,
                decoration: const InputDecoration(
                    labelText: 'Rep preference', border: OutlineInputBorder()),
                items: const <DropdownMenuItem<String>>[
                  DropdownMenuItem<String>(value: 'low', child: Text('Low')),
                  DropdownMenuItem<String>(
                      value: 'balanced', child: Text('Balanced')),
                  DropdownMenuItem<String>(value: 'high', child: Text('High')),
                ],
                onChanged: (String? value) => setDialogState(
                    () => repPreference = value ?? repPreference),
              ),
              const SizedBox(height: MayosSpacing.md),
              DropdownButtonFormField<int>(
                key: const Key('publish_frequency_field'),
                initialValue: frequency,
                decoration: const InputDecoration(
                    labelText: 'Days per week', border: OutlineInputBorder()),
                items: <DropdownMenuItem<int>>[
                  for (int day = 1; day <= 5; day++)
                    DropdownMenuItem<int>(value: day, child: Text('$day')),
                ],
                onChanged: (int? value) =>
                    setDialogState(() => frequency = value ?? frequency),
              ),
            ],
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Cancel'),
            ),
            MayosButton(
              key: const Key('publish_confirm_button'),
              label: 'Publish',
              expand: false,
              onPressed: () => Navigator.of(context).pop(
                _PublishRequest(
                  split: split.text.trim(),
                  repPreference: repPreference,
                  frequency: frequency,
                ),
              ),
            ),
          ],
        ),
      ),
    );
    split.dispose();
    if (request == null || !mounted) return;
    setState(() {
      _publishing = true;
      _publishError = null;
    });
    try {
      final TrainingProgram program =
          await ref.read(apiClientProvider).coachPublishProgram(
                _entry.assignmentId,
                splitOverride: request.split.isEmpty ? null : request.split,
                repPreference: request.repPreference,
                frequency: request.frequency,
              );
      if (!mounted) return;
      setState(() => _publishing = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Published program version ${program.version}')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _publishing = false;
        _publishError = error.message;
      });
    }
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
      showError: (String message) => setState(() => _requestError = message),
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
      const SnackBar(content: Text('Check-in recorded.')),
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
        SnackBar(content: Text(error.message)),
      );
    }
  }

  Widget _checkInsSegment(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          'Next follow-up: ${_nextFollowUpOn ?? 'not scheduled'}',
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Align(
          alignment: Alignment.centerLeft,
          child: MayosButton(
            key: const Key('record_check_in_button'),
            label: 'Log check-in',
            icon: Icons.note_add_outlined,
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: _openCheckInSheet,
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (_checkIns.isEmpty)
          Text(
            'No check-ins recorded yet.',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final CheckIn checkIn in _checkIns)
            MayosSettingsTile(
              key: Key('check_in_${checkIn.checkInId}'),
              icon: Icons.forum_outlined,
              title: '${checkIn.checkedInOn} · ${checkIn.channelLabel}',
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const MayosSectionHeader(title: 'Program requests'),
        if (_requestError != null) ...<Widget>[
          Text(
            _requestError!,
            style: MayosTypography.bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_programRequests.isEmpty)
          Text(
            'No program requests yet.',
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
    final Map<String, double> volume = _summary!.volume;
    final List<MapEntry<String, double>> entries = volume.entries
        .where((MapEntry<String, double> entry) => entry.value > 0)
        .toList(growable: false);
    return _section(
      context,
      'Volume (weighted working sets)',
      entries.isEmpty
          ? <Widget>[const Text('No volume recorded yet.')]
          : <Widget>[
              for (final MapEntry<String, double> entry in entries)
                Text('${entry.key}: ${entry.value}'),
            ],
    );
  }

  Widget _scheduleCard(BuildContext context) {
    final CoachPlayerSchedule? schedule = _summary!.schedule;
    final List<Widget> children = <Widget>[];
    if (schedule != null) {
      final String days =
          schedule.weekdays.map((int day) => weekdayLabels[day - 1]).join(', ');
      children.add(Text('Expected: $days'));
      children.add(Text('Timezone: ${schedule.timezone}'));
    }
    for (final CoachPlayerPause pause in _summary!.pauses) {
      children.add(Text('Pause: ${pause.startsOn} → ${pause.endsOn}'));
    }
    return _section(context, 'Training schedule', children);
  }

  Widget _latestSessionCard(BuildContext context) {
    final CoachPlayerLatestSession? latest = _summary!.latestSession;
    if (latest == null) {
      return _section(context, 'Latest session',
          <Widget>[const Text('No sessions logged yet.')]);
    }
    final String? versionNote = historicalProgramLabel(latest.programVersion,
        latest.activeProgramVersionAtSync, latest.isHistoricalProgram);
    return _section(context, 'Latest session', <Widget>[
      Text('${latest.splitName} · ${latest.sessionDate}'),
      Text(
          '${latest.setsCount} sets · ${latest.totalVolumeKg.toStringAsFixed(1)} kg'),
      if (latest.warmupMovements.isNotEmpty)
        Text('Warm-up: ${latest.warmupMovements.length} movements'),
      if (latest.cardio != null) Text('Cardio: ${latest.cardio!.minutes} min'),
      if (latest.readinessScore != null)
        Text('Readiness ${latest.readinessScore}/5'),
      if (versionNote != null) Text(versionNote),
      for (final PerformedDateCorrection correction in latest.corrections)
        Text(correction.label),
      const SizedBox(height: MayosSpacing.xs),
      for (final CoachPlayerSessionExercise exercise in latest.exercises)
        Text(
            '${exercise.name}: ${exercise.sets} sets · ${exercise.volumeKg.toStringAsFixed(1)} kg'),
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
    return '$kind: ${divergence.exerciseName}';
  }

  Widget _recentSessionsCard(BuildContext context) {
    final List<CoachPlayerRecentSession> sessions = _summary!.recentSessions;
    return _section(
      context,
      'Recent sessions',
      sessions.isEmpty
          ? <Widget>[const Text('No sessions logged yet.')]
          : <Widget>[
              for (final CoachPlayerRecentSession session in sessions)
                _recentSessionTile(session),
            ],
    );
  }

  Widget _recentSessionTile(CoachPlayerRecentSession session) {
    final String? versionNote = historicalProgramLabel(session.programVersion,
        session.activeProgramVersionAtSync, session.isHistoricalProgram);
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      title: Text('${session.splitName} · ${session.sessionDate}'),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
              '${session.setsCount} sets · ${session.totalVolumeKg.toStringAsFixed(1)} kg'),
          if (session.warmupMovements.isNotEmpty)
            Text('Warm-up: ${session.warmupMovements.length} movements'),
          if (session.cardio != null)
            Text('Cardio: ${session.cardio!.minutes} min'),
          if (versionNote != null) Text(versionNote),
          for (final PerformedDateCorrection correction in session.corrections)
            Text(correction.label),
          for (final CoachPlayerDivergence divergence in session.divergences)
            Text(_divergenceLabel(divergence)),
        ],
      ),
    );
  }

  Widget _recordsCard(BuildContext context) {
    return _section(
      context,
      'Personal records',
      _records.isEmpty
          ? <Widget>[const Text('No personal records yet.')]
          : <Widget>[
              for (final PersonalRecord record in _records)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(record.name),
                  subtitle: Text(
                      '${record.recordType} · ${record.value} kg × ${record.reps} reps'),
                ),
            ],
    );
  }

  Widget _checkpointReviewsCard(BuildContext context) {
    return _section(
      context,
      'Checkpoints',
      _checkpointReviews.isEmpty
          ? <Widget>[const Text('No Checkpoints yet.')]
          : <Widget>[
              for (final CheckpointReviewListItem review in _checkpointReviews)
                ListTile(
                  key: ValueKey<String>(
                      'coach.checkpoint.${review.checkpoint}'),
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('Checkpoint ${review.checkpoint}'),
                  subtitle: Text('${review.periodStart} – ${review.periodEnd}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => context.push(
                    '$checkpointReviewPath/${review.checkpoint}'
                    '?assignment_id=${_entry.assignmentId}',
                  ),
                ),
            ],
    );
  }

  Widget _exerciseDetail(BuildContext context, String exerciseId) {
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (history.caption != null) Text(history.caption!),
        const SizedBox(height: MayosSpacing.xxs),
        if (history.history.isEmpty)
          const Text('No recorded sets for this exercise.')
        else
          for (final CoachExerciseHistoryPoint point in history.history)
            // Effort is hidden when nobody rated the set, as this line always
            // was; a rated one reads as RIR (#111).
            Text('${point.date}: ${point.weightKg} kg × ${point.reps}'
                '${point.rpe == null ? '' : ' @ RIR ${rirLabel(point.rpe)}'}'
                ' (e1RM ${point.e1rm})'),
        if (history.records.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          const Text('Records'),
          for (final CoachExerciseRecord record in history.records)
            Text(
                '${record.recordType} · ${record.value} kg × ${record.reps} reps (${record.achievedAt})'),
        ],
      ],
    );
  }

  Widget _exercisesCard(BuildContext context) {
    return _section(
      context,
      'Exercises',
      _exercises.isEmpty
          ? <Widget>[const Text('No exercises logged yet.')]
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

  /// The segment label counts what still needs the coach (#121): the pending
  /// requests, or no number once nothing is waiting.
  int get _pendingRequests => _programRequests
      .where((ProgramRequest request) => request.isPending)
      .length;

  @override
  Widget build(BuildContext context) {
    final CoachRosterEntry entry = _entry;
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
                    child: const Text('Log check-in'),
                  ),
                  PopupMenuButton<_PlayerAction>(
                    key: const Key('player_page_actions'),
                    icon: const Icon(Icons.more_vert),
                    onSelected: (_PlayerAction action) {
                      switch (action) {
                        case _PlayerAction.publishProgram:
                          if (!_publishing) {
                            _openPublishDialog();
                          }
                        case _PlayerAction.askAssistant:
                          _openAssistant();
                      }
                    },
                    itemBuilder: (BuildContext context) =>
                        <PopupMenuEntry<_PlayerAction>>[
                      PopupMenuItem<_PlayerAction>(
                        key: const Key('publish_program_action'),
                        value: _PlayerAction.publishProgram,
                        enabled: !_publishing,
                        child: const Text('Publish program'),
                      ),
                      if (assistantEnabled)
                        const PopupMenuItem<_PlayerAction>(
                          key: Key('coach_assistant_entry'),
                          value: _PlayerAction.askAssistant,
                          child: Text('Ask assistant'),
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
        builder: (BuildContext context) =>
            CoachAssistantScreen(entry: _entry),
      ),
    );
  }

  /// One open coach alert with its actions (#120): acknowledge and resolve
  /// through the existing alert client calls, plus **Log check-in** while a
  /// follow-up is due.
  Widget _alertCard(BuildContext context, CoachAlert alert) {
    final MayosThemeExtension c = MayosTheme.of(context);
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
                  child: Text(
                    alert.description,
                    style: MayosTypography.body.copyWith(color: c.textPrimary),
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
                    label: 'Log check-in',
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : _openCheckInSheet,
                  ),
                if (alert.isNew)
                  MayosButton(
                    label: 'Acknowledge',
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
                    label: 'Resolve',
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
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(_error!,
                  textAlign: TextAlign.center,
                  style: MayosTypography.body.copyWith(color: c.textPrimary)),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: 'Retry',
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
        if (_publishError != null) ...<Widget>[
          Text(
            _publishError!,
            style: MayosTypography.bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_alerts.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Text('Open alerts',
              style: MayosTypography.sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          for (final CoachAlert alert in _alerts) _alertCard(context, alert),
        ],
        const SizedBox(height: MayosSpacing.md),
        MayosSegmentedControl<_PlayerSegment>(
          segments: <MayosSegment<_PlayerSegment>>[
            const MayosSegment<_PlayerSegment>(
                value: _PlayerSegment.history, label: 'History'),
            const MayosSegment<_PlayerSegment>(
                value: _PlayerSegment.checkIns, label: 'Check-ins'),
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.requests,
              label: _pendingRequests > 0
                  ? 'Requests ($_pendingRequests)'
                  : 'Requests',
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
      Text('Since ${summary.startedAt}', style: MayosTypography.bodySecondary),
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
  publishProgram,
  askAssistant,
}
