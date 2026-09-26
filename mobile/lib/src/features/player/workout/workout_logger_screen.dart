import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'draft_sync_service.dart';

/// The offline-capable workout logger (ADR 020/033).
///
/// The prescribed day is loaded from the per-account cache and refreshed online
/// when possible, so the player can record sets without connectivity. "Finish"
/// always writes a protected draft first, then attempts a sync.
class WorkoutLoggerScreen extends ConsumerStatefulWidget {
  const WorkoutLoggerScreen({super.key, required this.dayOrder});

  final int dayOrder;

  @override
  ConsumerState<WorkoutLoggerScreen> createState() =>
      _WorkoutLoggerScreenState();
}

class _WorkoutLoggerScreenState extends ConsumerState<WorkoutLoggerScreen> {
  final TextEditingController _notes = TextEditingController();

  bool _loading = true;
  String? _loadError;
  String? _saveError;
  bool _saving = false;
  bool _fromCache = false;

  String? _accountId;
  int? _programVersion;
  ProgramDay? _day;

  /// Null only when it could not be determined at all (never guessed as
  /// `'UTC'`) — Finish is blocked until it is known (ADR 020/033).
  String? _timezone;
  DateTime _performedDate = DateTime.now();
  int _readiness = 4;
  List<_LogExercise> _exercises = <_LogExercise>[];

  /// Why Finish is disabled beyond "no working sets logged", or null when
  /// nothing else blocks it.
  String? get _blockReason {
    if (_timezone == null) {
      return 'Your device timezone could not be determined, so the workout '
          'date cannot be recorded truthfully. Check your device time-zone '
          'settings and try again.';
    }
    if (_programVersion == null) {
      return 'No cached program version is available offline. Connect once '
          'to refresh your program before logging this workout.';
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _notes.dispose();
    for (final _LogExercise exercise in _exercises) {
      exercise.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    if (!ref.read(offlineWorkoutDraftsEnabledProvider)) {
      // The web client is online-only and never captures offline drafts (ADR 022).
      setState(() => _loading = false);
      return;
    }
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    if (accountId == null) {
      setState(() {
        _loading = false;
        _loadError = 'You are not signed in.';
      });
      return;
    }
    _accountId = accountId;
    final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
    TrainingProgram? program = await cache.readProgram(accountId);
    Prescription? prescription =
        await cache.readPrescription(accountId, widget.dayOrder);
    // The banner is shown only when the online fetch failed and the cached
    // program is what the player is actually logging against.
    bool fromCache = false;

    try {
      final TrainingProgram? online =
          await ref.read(apiClientProvider).activeProgram();
      program = online;
      if (online != null) {
        await cache.writeProgram(accountId, online);
      }
    } on ApiException {
      // Offline: fall back to whatever was cached.
      fromCache = program != null;
    }
    try {
      final Prescription fetched =
          await ref.read(apiClientProvider).prescription(widget.dayOrder);
      prescription = fetched;
      await cache.writePrescription(accountId, widget.dayOrder, fetched);
    } on ApiException {
      // Offline: use whatever was cached.
    }

    ProgramDay? day;
    for (final ProgramDay candidate in program?.days ?? const <ProgramDay>[]) {
      if (candidate.dayOrder == widget.dayOrder) {
        day = candidate;
      }
    }
    final String? timezone = await _resolveTimezone();

    if (day == null) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = 'This training day is not available offline.';
      });
      return;
    }

    if (!mounted) return;
    setState(() {
      _programVersion = program?.version;
      _day = day;
      _timezone = timezone;
      _exercises = <_LogExercise>[
        for (final ProgramExercise exercise in day!.exercises)
          _LogExercise.fromPrescription(
              exercise, prescription?.forExercise(exercise.exerciseId)),
      ];
      _fromCache = fromCache;
      _loading = false;
    });
  }

  /// The device's IANA timezone, or null when it could not be determined.
  ///
  /// The performed date is derived from the device wall clock, so it must be
  /// recorded against the device timezone. Falling back to the training
  /// schedule's timezone while still using the device date would misrecord a
  /// near-midnight workout, so Finish is blocked instead of guessing (ADR
  /// 020/029/033).
  Future<String?> _resolveTimezone() async =>
      ref.read(deviceTimezoneOrNullProvider);

  Future<void> _pickDate() async {
    // The device has no IANA timezone database, so "today" is computed from
    // the device's own wall clock; this is the same clock [_timezone] names
    // (the device zone, or the cached schedule zone only when the device
    // zone truly could not be read), so the two stay consistent.
    final PerformedDateWindow window = performedDateWindow();
    final DateTime initial = window.clamp(_performedDate);
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: window.first,
      lastDate: window.last,
    );
    if (picked != null) {
      setState(() => _performedDate = picked);
    }
  }

  Future<void> _addUnplanned() async {
    final ExerciseCatalogEntry? entry = await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => const _UnplannedExerciseDialog(),
    );
    if (entry == null) {
      return;
    }
    setState(() {
      _exercises = <_LogExercise>[
        ..._exercises,
        _LogExercise.unplanned(entry),
      ];
    });
  }

  Future<void> _finish() async {
    final String? accountId = _accountId;
    final ProgramDay? day = _day;
    final int? version = _programVersion;
    final String? timezone = _timezone;
    if (accountId == null || day == null) {
      return;
    }
    final String? blockReason = _blockReason;
    if (blockReason != null) {
      setState(() => _saveError = blockReason);
      return;
    }
    if (_exercises.every((_LogExercise exercise) => !exercise.hasWorkingSets)) {
      setState(() {
        _saveError = 'Log at least one working set before finishing.';
      });
      return;
    }
    setState(() {
      _saving = true;
      _saveError = null;
    });

    final DateTime now = DateTime.now();
    final String performedDate = formatPerformedDate(_performedDate);
    final DraftSyncService sync = ref.read(draftSyncServiceProvider);
    final WorkoutDraft draft = WorkoutDraft(
      clientSessionId: sync.newClientSessionId(),
      accountId: accountId,
      performedDate: performedDate,
      performedTimezone: timezone!,
      programVersion: version!,
      dayOrder: day.dayOrder,
      dayName: day.dayName,
      capturedAt: now.toUtc().toIso8601String(),
      exercises: <DraftExercise>[
        for (final _LogExercise exercise in _exercises)
          DraftExercise(
            exercise: exercise.exercise,
            sets: exercise.sets
                .map((_EditableSet set) => set.toLog())
                .toList(growable: false),
            skipped: exercise.skipped,
          ),
      ],
      readiness: _readiness,
      notes: _notes.text.trim(),
      status: DraftStatus.pending,
      updatedAt: now.toUtc().toIso8601String(),
    );

    await sync.saveDraft(draft);
    if (!mounted) return;
    setState(() => _saving = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Workout saved to your drafts.')),
    );
    context.go(workoutsPath);
  }

  @override
  Widget build(BuildContext context) {
    if (!ref.watch(offlineWorkoutDraftsEnabledProvider)) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Offline workout logging is available in the Android app.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_loadError!, textAlign: TextAlign.center),
        ),
      );
    }
    final ProgramDay day = _day!;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          if (_fromCache)
            const Padding(
              padding: EdgeInsets.only(bottom: 8),
              child: Text('Offline: showing your cached program.'),
            ),
          Text(day.dayName, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.event_outlined),
            title: const Text('Performed date'),
            subtitle: Text(
                '${_performedDate.year}-${_performedDate.month.toString().padLeft(2, '0')}-'
                '${_performedDate.day.toString().padLeft(2, '0')}'),
            trailing: const Icon(Icons.edit_outlined),
            onTap: _pickDate,
          ),
          Text('Readiness: $_readiness/5'),
          Slider(
            value: _readiness.toDouble(),
            min: 1,
            max: 5,
            divisions: 4,
            label: '$_readiness',
            onChanged: (double value) =>
                setState(() => _readiness = value.round()),
          ),
          const SizedBox(height: 8),
          ..._exercises.map(_buildExerciseCard),
          OutlinedButton.icon(
            onPressed: _addUnplanned,
            icon: const Icon(Icons.add),
            label: const Text('Add unplanned exercise'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _notes,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: 'Notes (pumps, joint aches, fatigue)',
              border: OutlineInputBorder(),
            ),
          ),
          if (_blockReason != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(_blockReason!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          if (_saveError != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(_saveError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _saving || _blockReason != null ? null : _finish,
            icon: _saving
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.check),
            label: const Text('Finish and save draft'),
          ),
        ],
      ),
    );
  }

  Widget _buildExerciseCard(_LogExercise exercise) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(exercise.exerciseName,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                if (exercise.unplanned)
                  const Padding(
                    padding: EdgeInsets.only(right: 4),
                    child: Chip(label: Text('Unplanned')),
                  ),
                Checkbox(
                  value: exercise.skipped,
                  onChanged: (bool? value) =>
                      setState(() => exercise.skipped = value ?? false),
                ),
                const Text('Skip'),
              ],
            ),
            if (exercise.targetLabel != null)
              Text(exercise.targetLabel!,
                  style: Theme.of(context).textTheme.bodySmall),
            if (!exercise.skipped) ...<Widget>[
              const SizedBox(height: 8),
              ...exercise.sets.asMap().entries.map(
                    (MapEntry<int, _EditableSet> entry) =>
                        _buildSetRow(exercise, entry.key, entry.value),
                  ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () => setState(exercise.addSet),
                  icon: const Icon(Icons.add),
                  label: const Text('Add set'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildSetRow(_LogExercise exercise, int index, _EditableSet set) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: <Widget>[
          SizedBox(width: 24, child: Text('${index + 1}')),
          Expanded(
            child: TextField(
              controller: set.weight,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'kg', isDense: true),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: set.reps,
              keyboardType: TextInputType.number,
              decoration:
                  const InputDecoration(labelText: 'reps', isDense: true),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: set.rpe,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration:
                  const InputDecoration(labelText: 'RPE', isDense: true),
            ),
          ),
          IconButton(
            tooltip: set.isWarmup ? 'Warm-up set' : 'Working set',
            onPressed: () => setState(() => set.isWarmup = !set.isWarmup),
            icon: Icon(set.isWarmup
                ? Icons.local_fire_department
                : Icons.fitness_center),
          ),
          IconButton(
            tooltip: 'Remove set',
            onPressed: exercise.sets.length <= 1
                ? null
                : () => setState(() => exercise.removeSet(index)),
            icon: const Icon(Icons.close),
          ),
        ],
      ),
    );
  }
}

class _EditableSet {
  _EditableSet({
    required double weight,
    required int reps,
    required double rpe,
  })  : weight = TextEditingController(text: _format(weight)),
        reps = TextEditingController(text: '$reps'),
        rpe = TextEditingController(text: _format(rpe));

  final TextEditingController weight;
  final TextEditingController reps;
  final TextEditingController rpe;
  bool isWarmup = false;

  static String _format(double value) => value == value.roundToDouble()
      ? value.round().toString()
      : value.toStringAsFixed(1);

  WorkoutSetLog toLog() => WorkoutSetLog(
        weightKg: double.tryParse(weight.text) ?? 0,
        reps: int.tryParse(reps.text) ?? 0,
        rpe: double.tryParse(rpe.text) ?? 8.5,
        isWarmup: isWarmup,
      );

  void dispose() {
    weight.dispose();
    reps.dispose();
    rpe.dispose();
  }
}

class _LogExercise {
  _LogExercise({
    required this.exercise,
    required this.sets,
    this.unplanned = false,
    this.targetLabel,
  });

  factory _LogExercise.fromPrescription(
      ProgramExercise exercise, PrescriptionTarget? target) {
    final double weight = target?.projectedWeight ?? 0;
    final double rpe = target?.targetRpeCap ?? exercise.targetRpe;
    final int setCount = target?.effectiveSets ?? exercise.targetSets;
    return _LogExercise(
      exercise: exercise.toJson(),
      sets: <_EditableSet>[
        for (int i = 0; i < setCount; i++)
          _EditableSet(weight: weight, reps: exercise.targetRepsMin, rpe: rpe),
      ],
      targetLabel: exercise.prescription,
    );
  }

  factory _LogExercise.unplanned(ExerciseCatalogEntry entry) {
    return _LogExercise(
      exercise: <String, dynamic>{
        'exercise_id': entry.id,
        'exercise_name': entry.name,
        'target_sets': 3,
        'target_reps_min': 8,
        'target_reps_max': 12,
        'target_rpe': 8.0,
        'rest_seconds': 120,
        'notes': null,
      },
      sets: <_EditableSet>[
        _EditableSet(weight: 0, reps: 8, rpe: 8.0),
        _EditableSet(weight: 0, reps: 8, rpe: 8.0),
        _EditableSet(weight: 0, reps: 8, rpe: 8.0),
      ],
      unplanned: true,
    );
  }

  final Map<String, dynamic> exercise;
  final bool unplanned;
  final String? targetLabel;
  List<_EditableSet> sets;
  bool skipped = false;

  String get exerciseId => exercise['exercise_id'] as String;
  String get exerciseName => exercise['exercise_name'] as String;

  bool get hasWorkingSets =>
      !skipped && sets.any((_EditableSet set) => !set.isWarmup);

  void addSet() {
    final _EditableSet last = sets.isEmpty
        ? _EditableSet(weight: 0, reps: 8, rpe: 8)
        : _EditableSet(
            weight: double.tryParse(sets.last.weight.text) ?? 0,
            reps: int.tryParse(sets.last.reps.text) ?? 8,
            rpe: double.tryParse(sets.last.rpe.text) ?? 8,
          );
    sets = <_EditableSet>[...sets, last];
  }

  void removeSet(int index) {
    final _EditableSet removed = sets[index];
    sets = <_EditableSet>[...sets]..removeAt(index);
    removed.dispose();
  }

  void dispose() {
    for (final _EditableSet set in sets) {
      set.dispose();
    }
  }
}

class _UnplannedExerciseDialog extends ConsumerStatefulWidget {
  const _UnplannedExerciseDialog();

  @override
  ConsumerState<_UnplannedExerciseDialog> createState() =>
      _UnplannedExerciseDialogState();
}

class _UnplannedExerciseDialogState
    extends ConsumerState<_UnplannedExerciseDialog> {
  final TextEditingController _query = TextEditingController();

  bool _searching = false;
  String? _error;
  List<ExerciseCatalogEntry> _results = const <ExerciseCatalogEntry>[];

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  /// Searches the real catalog so an unplanned exercise carries an id the
  /// service can validate, rather than an invented one that would be refused
  /// on sync (ADR 020/033).
  Future<void> _search() async {
    final String query = _query.text.trim();
    if (query.isEmpty) {
      setState(() => _error = 'Type an exercise name to search.');
      return;
    }
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      final List<ExerciseCatalogEntry> results =
          await ref.read(apiClientProvider).searchExercises(query);
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = results;
        _error = results.isEmpty ? 'No matching exercise found.' : null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = const <ExerciseCatalogEntry>[];
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add unplanned exercise'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            TextField(
              controller: _query,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              decoration: const InputDecoration(
                labelText: 'Search the exercise catalog',
              ),
            ),
            if (_searching)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (_results.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: <Widget>[
                    for (final ExerciseCatalogEntry entry in _results)
                      ListTile(
                        dense: true,
                        title: Text(entry.name),
                        onTap: () => Navigator.of(context).pop(entry),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _searching ? null : _search,
          child: const Text('Search'),
        ),
      ],
    );
  }
}
