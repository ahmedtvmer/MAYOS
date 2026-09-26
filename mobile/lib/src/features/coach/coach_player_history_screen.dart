import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../providers.dart';

/// Coach drill-down (#25): one actively assigned player's sessions, volume,
/// personal records, and per-exercise history.
///
/// Every read is gated by the active assignment server-side, so a revoked or
/// foreign assignment yields a denial and no training data. Player-assistant
/// chats never appear here.
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

  @override
  void initState() {
    super.initState();
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
        api.coachPlayerSummary(widget.entry.assignmentId),
        api.coachPlayerPersonalRecords(widget.entry.assignmentId),
        api.coachPlayerExercises(widget.entry.assignmentId),
      ]);
      if (!mounted) return;
      setState(() {
        _summary = results[0] as CoachPlayerSummary;
        _records = results[1] as List<PersonalRecord>;
        _exercises = results[2] as List<CoachPlayerExercise>;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
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
      final TrainingProgram program = await ref
          .read(apiClientProvider)
          .coachPublishProgram(
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

  Widget _section(BuildContext context, String title, List<Widget> children) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
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

  Widget _latestSessionCard(BuildContext context) {
    final CoachPlayerLatestSession? latest = _summary!.latestSession;
    if (latest == null) {
      return _section(context, 'Latest session',
          <Widget>[const Text('No sessions logged yet.')]);
    }
    return _section(context, 'Latest session', <Widget>[
      Text('${latest.splitName} · ${latest.sessionDate}'),
      Text(
          '${latest.setsCount} sets · ${latest.totalVolumeKg.toStringAsFixed(1)} kg'),
      if (latest.readinessScore != null)
        Text('Readiness ${latest.readinessScore}/5'),
      const SizedBox(height: 8),
      for (final CoachPlayerSessionExercise exercise in latest.exercises)
        Text(
            '${exercise.name}: ${exercise.sets} sets · ${exercise.volumeKg.toStringAsFixed(1)} kg'),
    ]);
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
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${session.splitName} · ${session.sessionDate}'),
                  subtitle: Text(
                      '${session.setsCount} sets · ${session.totalVolumeKg.toStringAsFixed(1)} kg'),
                ),
            ],
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
            Text(
                '${point.date}: ${point.weightKg} kg × ${point.reps}'
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
    return Scaffold(
      appBar: AppBar(
        title: Text(entry.playerUsername),
        actions: <Widget>[
          TextButton(
            onPressed: _publishing ? null : _openPublishDialog,
            child: _publishing
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Publish program'),
          ),
        ],
      ),
      body: _buildBody(context),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
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
    final CoachPlayerSummary summary = _summary!;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        if (_publishError != null) ...<Widget>[
          Text(
            _publishError!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          const SizedBox(height: 12),
        ],
        Text('Since ${summary.startedAt}',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        _volumeCard(context),
        const SizedBox(height: 12),
        _latestSessionCard(context),
        const SizedBox(height: 12),
        _recentSessionsCard(context),
        const SizedBox(height: 12),
        _recordsCard(context),
        const SizedBox(height: 12),
        _exercisesCard(context),
      ],
    );
  }
}
