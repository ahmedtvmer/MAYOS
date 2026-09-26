import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';

/// A cache read on the offline path may never block indefinitely.
const Duration _cacheReadTimeout = Duration(seconds: 3);

class ProgramTab extends ConsumerStatefulWidget {
  const ProgramTab({super.key});

  @override
  ConsumerState<ProgramTab> createState() => _ProgramTabState();
}

class _ProgramTabState extends ConsumerState<ProgramTab> {
  bool _loading = true;
  bool _generating = false;
  String? _loadError;
  String? _actionError;
  TrainingProgram? _program;

  /// True only when [_program] is being served from the offline cache after
  /// an online fetch failed (ADR 020/033) — never merely because a cache
  /// exists alongside a successful fetch.
  bool _fromCache = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String? get _accountId =>
      ref.read(authControllerProvider).session?.account.accountId;

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    final String? accountId = _accountId;
    final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
    try {
      final TrainingProgram? online =
          await ref.read(apiClientProvider).activeProgram();
      if (online != null && accountId != null) {
        unawaited(_cacheProgram(cache, accountId, online));
      }
      if (!mounted) return;
      setState(() {
        _program = online;
        _fromCache = false;
        _loading = false;
      });
    } on ApiException catch (error) {
      final TrainingProgram? cached =
          accountId == null ? null : await _readCachedProgram(cache, accountId);
      if (!mounted) return;
      if (cached != null) {
        setState(() {
          _program = cached;
          _fromCache = true;
          _loading = false;
        });
      } else {
        setState(() {
          _loadError = error.message;
          _loading = false;
        });
      }
    }
  }

  Future<void> _generate() async {
    setState(() {
      _generating = true;
      _actionError = null;
    });
    try {
      final TrainingProgram program =
          await ref.read(apiClientProvider).playerGenerateProgram();
      final String? accountId = _accountId;
      if (accountId != null) {
        unawaited(_cacheProgram(
            ref.read(workoutCacheStoreProvider), accountId, program));
      }
      if (!mounted) return;
      setState(() {
        _generating = false;
        _program = program;
        _fromCache = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _generating = false;
        _actionError = error.message;
      });
    }
  }

  /// Caching the fetched program is fire-and-forget: a slow or failing store
  /// must never hide (or delay showing) an otherwise-successful online fetch
  /// (ADR 020/033).
  Future<void> _cacheProgram(
      WorkoutCacheStore cache, String accountId, TrainingProgram program) async {
    try {
      await cache.writeProgram(accountId, program);
    } on Object {
      // Offline logging simply won't have this program cached; not fatal here.
    }
  }

  Future<TrainingProgram?> _readCachedProgram(
      WorkoutCacheStore cache, String accountId) async {
    try {
      return await cache.readProgram(accountId).timeout(_cacheReadTimeout);
    } on Object {
      return null;
    }
  }

  Widget _generateButton() {
    return FilledButton.tonalIcon(
      onPressed: _generating ? null : _generate,
      icon: _generating
          ? const SizedBox(
              height: 18,
              width: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.auto_awesome),
      label: const Text('Regenerate program'),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(_loadError!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final TrainingProgram? program = _program;
    if (program == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              const Text(
                  'No active program yet. Complete onboarding to build one.'),
              if (_actionError != null) ...<Widget>[
                const SizedBox(height: 12),
                Text(
                  _actionError!,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              const SizedBox(height: 16),
              _generateButton(),
            ],
          ),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          if (_fromCache)
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: _OfflineBanner(),
            ),
          Text(program.programName,
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 4),
          Text('${program.splitType} · ${program.weeklyFrequency} days/week'),
          if (program.version != null) ...<Widget>[
            const SizedBox(height: 4),
            Text('Version ${program.version}',
                style: Theme.of(context).textTheme.bodySmall),
          ],
          if (program.isCoachPublished) ...<Widget>[
            const SizedBox(height: 4),
            Row(
              children: <Widget>[
                const Icon(Icons.verified_user_outlined, size: 16),
                const SizedBox(width: 4),
                Text('Published by your coach',
                    style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ],
          if (_actionError != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(_actionError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 12),
          _generateButton(),
          const SizedBox(height: 16),
          ...program.days.map(
            (ProgramDay day) => Card(
              child: ExpansionTile(
                initiallyExpanded: day.dayOrder == 1,
                title: Text('Day ${day.dayOrder}: ${day.dayName}'),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                children: <Widget>[
                  if (ref.watch(offlineWorkoutDraftsEnabledProvider))
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: () =>
                            context.go('$logWorkoutPath/${day.dayOrder}'),
                        icon: const Icon(Icons.edit_note),
                        label: const Text('Log workout'),
                      ),
                    ),
                  if (day.hasWarmup) ...<Widget>[
                    const _SectionLabel('Warm-up'),
                    ...day.warmupExercises.map(
                      (WarmupExercise warmup) => ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: Text(warmup.exerciseName),
                        subtitle: Text(<String>[
                          warmup.prescription,
                          if (warmup.hasNotes) warmup.notes!,
                        ].join('\n')),
                        isThreeLine: warmup.hasNotes,
                      ),
                    ),
                  ],
                  const _SectionLabel('Working sets'),
                  ...day.exercises.map(
                    (ProgramExercise exercise) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            exercise.exerciseName,
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                          Text(exercise.prescription),
                          Text(<String>[
                            if (exercise.hasWarmupSets)
                              '${exercise.warmupSets} warm-up sets',
                            exercise.restLabel,
                          ].join(' · ')),
                          if (exercise.hasNotes) Text(exercise.notes!),
                        ],
                      ),
                    ),
                  ),
                  if (day.hasCardio)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.directions_run),
                      title: const Text('Cardio'),
                      subtitle: Text(day.cardio!),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OfflineBanner extends StatelessWidget {
  const _OfflineBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.cloud_off,
              size: 18, color: Theme.of(context).colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Offline — showing saved program',
              style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 4),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Text(text, style: Theme.of(context).textTheme.labelLarge),
      ),
    );
  }
}
