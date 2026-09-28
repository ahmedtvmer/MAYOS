import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_segmented_control.dart';
import '../../providers.dart';
import 'coach_assistant_screen.dart';
import 'coach_check_in_sheet.dart';

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
  const CoachPlayerHistoryScreen({super.key, required this.entry});

  final CoachRosterEntry entry;

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
  bool _loading = true;
  String? _error;
  CoachPlayerSummary? _summary;
  List<PersonalRecord> _records = const <PersonalRecord>[];
  List<CoachPlayerExercise> _exercises = const <CoachPlayerExercise>[];
  final Map<String, CoachExerciseHistory> _histories =
      <String, CoachExerciseHistory>{};
  String? _openExerciseId;
  bool _loadingHistory = false;
  bool _publishing = false;
  String? _publishError;
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  bool _resolvingRequest = false;
  String? _requestError;
  List<CheckIn> _checkIns = const <CheckIn>[];
  String? _nextFollowUpOn;
  List<CoachAlert> _alerts = const <CoachAlert>[];
  String? _busyAlertId;
  int _segment = 0;

  @override
  void initState() {
    super.initState();
    _nextFollowUpOn = widget.entry.nextFollowUpOn;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final List<Object> results = await Future.wait<Object>(<Future<Object>>[
        api.coachAlerts(states: <String>['new', 'acknowledged']),
        api.coachPlayerSummary(widget.entry.assignmentId),
        api.coachPlayerPersonalRecords(widget.entry.assignmentId),
        api.coachPlayerExercises(widget.entry.assignmentId),
        api.coachProgramRequests(widget.entry.assignmentId),
        api.coachCheckIns(widget.entry.assignmentId),
      ]);
      if (!mounted) return;
      final List<CoachAlert> allAlerts =
          results[0] as List<CoachAlert>;
      setState(() {
        // The player page shows this assignment's open alerts only (#120).
        _alerts = allAlerts
            .where((CoachAlert alert) =>
                alert.assignmentId == widget.entry.assignmentId)
            .toList(growable: false);
        _summary = results[1] as CoachPlayerSummary;
        _records = results[2] as List<PersonalRecord>;
        _exercises = results[3] as List<CoachPlayerExercise>;
        _programRequests = results[4] as List<ProgramRequest>;
        // Newest first whatever order the list endpoint returned (#120).
        _checkIns =
            sortCheckInsNewestFirst(results[5] as List<CheckIn>);
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.statusCode == 403) {
        // The assignment ended or was revoked while this screen was open: the
        // drill-down is refused, so the assistant's in-memory context for this
        // player goes with it (issue #45).
        ref
            .read(coachAssistantControllerProvider.notifier)
            .clearFor(widget.entry.assignmentId);
      }
      setState(() {
        _loading = false;
        _error = error.message;
      });
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
          .coachPlayerExerciseHistory(widget.entry.assignmentId, exercise.id);
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
              const SizedBox(height: 16),
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
              const SizedBox(height: 16),
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
            FilledButton(
              key: const Key('publish_confirm_button'),
              onPressed: () => Navigator.of(context).pop(
                _PublishRequest(
                  split: split.text.trim(),
                  repPreference: repPreference,
                  frequency: frequency,
                ),
              ),
              child: const Text('Publish'),
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
                widget.entry.assignmentId,
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

  Future<void> _applyRequest(ProgramRequest request) async {
    setState(() {
      _resolvingRequest = true;
      _requestError = null;
    });
    try {
      await ref.read(apiClientProvider).applyCoachProgramRequest(
          widget.entry.assignmentId, request.requestId);
      if (!mounted) return;
      setState(() => _resolvingRequest = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Program request applied.')),
      );
      await _load();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _resolvingRequest = false;
        _requestError = error.message;
      });
    }
  }

  Future<void> _declineRequest(ProgramRequest request) async {
    final String? text = await showDialog<String>(
      context: context,
      builder: (BuildContext context) => const _DeclineRequestDialog(),
    );
    if (text == null || !mounted) return;
    setState(() {
      _resolvingRequest = true;
      _requestError = null;
    });
    try {
      await ref.read(apiClientProvider).declineCoachProgramRequest(
          widget.entry.assignmentId, request.requestId, text);
      if (!mounted) return;
      setState(() => _resolvingRequest = false);
      await _load();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _resolvingRequest = false;
        _requestError = error.message;
      });
    }
  }

  /// The header **Log check-in** action and the Check-ins segment's button
  /// open the same sheet (#120): channel, optional note, dated today.
  Future<void> _openCheckInSheet() async {
    await showLogCheckInSheet(
      context,
      assignmentId: widget.entry.assignmentId,
      playerUsername: widget.entry.playerUsername,
      onSaved: _onCheckInSaved,
    );
  }

  /// Saves land here: the page's check-in list and next follow-up update
  /// immediately, and the roster row is told to reload so its follow-up chip
  /// tracks the new cadence (#120).
  void _onCheckInSaved(CheckInCreation created) {
    if (!mounted) return;
    setState(() {
      _checkIns = sortCheckInsNewestFirst(<CheckIn>[created.checkIn, ..._checkIns]);
      if (created.nextFollowUpOn != null) {
        _nextFollowUpOn = created.nextFollowUpOn;
      }
    });
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Check-in recorded.')),
    );
  }

  /// Acknowledge / resolve through the existing alert client calls. Both the
  /// Alerts tab badge and the roster row follow the change without a restart
  /// (#120): the badge loses a `new` alert it just lost, and both tabs are
  /// told to refetch.
  Future<void> _applyAlert(
    CoachAlert alert,
    Future<CoachAlert> Function() action,
  ) async {
    setState(() => _busyAlertId = alert.alertId);
    try {
      final CoachAlert updated = await action();
      if (!mounted) return;
      final bool wasNew = alert.isNew;
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
      if (wasNew) {
        final int count = ref.read(coachNewAlertsCountProvider);
        ref.read(coachNewAlertsCountProvider.notifier).state =
            count > 0 ? count - 1 : 0;
      }
      ref.read(coachAlertsRevisionProvider.notifier).state++;
      ref.read(coachRosterRevisionProvider.notifier).state++;
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
          child: FilledButton.icon(
            key: const Key('record_check_in_button'),
            onPressed: _openCheckInSheet,
            icon: const Icon(Icons.note_add_outlined),
            label: const Text('Log check-in'),
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
            ListTile(
              key: Key('check_in_${checkIn.checkInId}'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('${checkIn.checkedInOn} · ${checkIn.channelLabel}'),
              subtitle: checkIn.note == null || checkIn.note!.isEmpty
                  ? null
                  : Text(checkIn.note!),
            ),
      ],
    );
  }

  Widget _programRequestsCard(BuildContext context) {
    return _section(context, 'Program requests', <Widget>[
      if (_requestError != null) ...<Widget>[
        Text(
          _requestError!,
          style: TextStyle(color: MayosTheme.of(context).danger),
        ),
        const SizedBox(height: 12),
      ],
      if (_programRequests.isEmpty)
        const Text('No program requests yet.')
      else
        for (final ProgramRequest request in _programRequests)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  children: <Widget>[
                    Chip(label: Text(request.statusLabel)),
                    const SizedBox(width: 8),
                    Expanded(child: Text(request.description)),
                  ],
                ),
                Text('Reason: ${request.reason}'),
                if (request.hasResponse) Text('Response: ${request.response}'),
                if (request.isPending)
                  Row(
                    children: <Widget>[
                      TextButton(
                        onPressed: _resolvingRequest
                            ? null
                            : () => _applyRequest(request),
                        child: const Text('Apply'),
                      ),
                      TextButton(
                        onPressed: _resolvingRequest
                            ? null
                            : () => _declineRequest(request),
                        child: const Text('Decline'),
                      ),
                    ],
                  ),
              ],
            ),
          ),
    ]);
  }

  Widget _section(BuildContext context, String title, List<Widget> children) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
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
      if (latest.readinessScore != null)
        Text('Readiness ${latest.readinessScore}/5'),
      if (versionNote != null) Text(versionNote),
      for (final PerformedDateCorrection correction in latest.corrections)
        Text(correction.label),
      const SizedBox(height: 8),
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
        const SizedBox(height: 4),
        if (history.history.isEmpty)
          const Text('No recorded sets for this exercise.')
        else
          for (final CoachExerciseHistoryPoint point in history.history)
            Text('${point.date}: ${point.weightKg} kg × ${point.reps}'
                '${point.rpe == null ? '' : ' @ RPE ${point.rpe}'}'
                ' (e1RM ${point.e1rm})'),
        if (history.records.isNotEmpty) ...<Widget>[
          const SizedBox(height: 8),
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

  @override
  Widget build(BuildContext context) {
    final CoachRosterEntry entry = widget.entry;
    final bool assistantEnabled =
        ref.watch(authControllerProvider).session?.account.coachAiEnabled ??
            false;
    return Scaffold(
      appBar: AppBar(
        title: Text(entry.playerUsername),
        actions: <Widget>[
          // The header action of the player page (#120): it opens the
          // channel + note sheet dated today.
          TextButton(
            key: const Key('log_check_in_action'),
            onPressed: _loading ? null : _openCheckInSheet,
            child: const Text('Log check-in'),
          ),
        ],
      ),
      body: _buildBody(context, assistantEnabled),
    );
  }

  /// Opens the in-memory coach assistant for this one player (#45). The entry
  /// exists only when the service reports the feature enabled.
  void _openAssistant() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (BuildContext context) =>
            CoachAssistantScreen(entry: widget.entry),
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
                    style:
                        MayosTypography.body.copyWith(color: c.textPrimary),
                  ),
                ),
                Chip(
                  label: Text(alert.stateLabel),
                  labelStyle: MayosTypography.caption.copyWith(
                    color: switch (alert.state) {
                      'new' => c.danger,
                      'acknowledged' => c.warning,
                      _ => c.textMuted,
                    },
                  ),
                  visualDensity: VisualDensity.compact,
                  side: BorderSide(
                    color: switch (alert.state) {
                      'new' => c.danger,
                      'acknowledged' => c.warning,
                      _ => c.textMuted,
                    },
                  ),
                  backgroundColor: Colors.transparent,
                ),
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

  Widget _buildBody(BuildContext context, bool assistantEnabled) {
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
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final CoachPlayerSummary summary = _summary!;
    return ListView(
      padding: const EdgeInsets.all(MayosSpacing.md),
      children: <Widget>[
        if (_publishError != null) ...<Widget>[
          Text(
            _publishError!,
            style: TextStyle(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        Text(
          'Coached since ${summary.startedAt} · '
          'Next follow-up ${_nextFollowUpOn ?? 'not scheduled'}',
          style: MayosTypography.caption.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Wrap(
          spacing: MayosSpacing.sm,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            MayosButton(
              label: 'Publish program',
              variant: MayosButtonVariant.secondary,
              expand: false,
              loading: _publishing,
              onPressed: _publishing ? null : _openPublishDialog,
            ),
            if (assistantEnabled)
              MayosButton(
                key: const Key('coach_assistant_entry'),
                label: 'Ask assistant',
                variant: MayosButtonVariant.tertiary,
                expand: false,
                onPressed: _openAssistant,
              ),
          ],
        ),
        if (_alerts.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Text('Open alerts',
              style: MayosTypography.sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          for (final CoachAlert alert in _alerts)
            _alertCard(context, alert),
        ],
        const SizedBox(height: MayosSpacing.md),
        MayosSegmentedControl<String>(
          segments: const <MayosSegment<String>>[
            MayosSegment<String>(value: 'history', label: 'History'),
            MayosSegment<String>(value: 'checkins', label: 'Check-ins'),
          ],
          selected: _segment == 0 ? 'history' : 'checkins',
          onChanged: (String value) =>
              setState(() => _segment = value == 'history' ? 0 : 1),
        ),
        const SizedBox(height: MayosSpacing.md),
        if (_segment == 0) ..._historyChildren(context) else _checkInsSegment(context),
      ],
    );
  }

  /// The original drill-down content (#25), embedded as the History segment
  /// of the player page (#120) instead of being duplicated here.
  List<Widget> _historyChildren(BuildContext context) {
    final CoachPlayerSummary summary = _summary!;
    return <Widget>[
      Text('Since ${summary.startedAt}',
          style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 12),
      _volumeCard(context),
      const SizedBox(height: 12),
      if (summary.schedule != null || summary.pauses.isNotEmpty) ...<Widget>[
        _scheduleCard(context),
        const SizedBox(height: 12),
      ],
      _latestSessionCard(context),
      const SizedBox(height: 12),
      _recentSessionsCard(context),
      const SizedBox(height: 12),
      _recordsCard(context),
      const SizedBox(height: 12),
      _programRequestsCard(context),
      const SizedBox(height: 12),
      _exercisesCard(context),
    ];
  }
}

/// The decline dialog. It owns its controller so it is disposed only after the
/// route fully leaves the tree.
class _DeclineRequestDialog extends StatefulWidget {
  const _DeclineRequestDialog();

  @override
  State<_DeclineRequestDialog> createState() => _DeclineRequestDialogState();
}

class _DeclineRequestDialogState extends State<_DeclineRequestDialog> {
  final TextEditingController _response = TextEditingController();

  @override
  void dispose() {
    _response.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Decline request'),
      content: TextField(
        key: const Key('decline_response_field'),
        controller: _response,
        maxLines: 2,
        decoration: const InputDecoration(
            labelText: 'Response to the player', border: OutlineInputBorder()),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('decline_submit_button'),
          onPressed: () => Navigator.of(context).pop(_response.text.trim()),
          child: const Text('Decline'),
        ),
      ],
    );
  }
}

