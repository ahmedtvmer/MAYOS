import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

class ProgramTab extends ConsumerStatefulWidget {
  const ProgramTab({super.key});

  @override
  ConsumerState<ProgramTab> createState() => _ProgramTabState();
}

class _ProgramTabState extends ConsumerState<ProgramTab> {
  late Future<TrainingProgram?> _future;
  bool _generating = false;
  String? _actionError;

  @override
  void initState() {
    super.initState();
    _future = ref.read(apiClientProvider).activeProgram();
  }

  Future<void> _refresh() async {
    final Future<TrainingProgram?> future =
        ref.read(apiClientProvider).activeProgram();
    setState(() => _future = future);
    await future;
  }

  Future<void> _generate() async {
    setState(() {
      _generating = true;
      _actionError = null;
    });
    try {
      final TrainingProgram program =
          await ref.read(apiClientProvider).playerGenerateProgram();
      if (!mounted) return;
      setState(() {
        _generating = false;
        _future = Future<TrainingProgram?>.value(program);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _generating = false;
        _actionError = error.message;
      });
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
    return FutureBuilder<TrainingProgram?>(
      future: _future,
      builder:
          (BuildContext context, AsyncSnapshot<TrainingProgram?> snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          final Object error = snapshot.error!;
          final String message = error is ApiException
              ? error.message
              : 'Could not load your program.';
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(message, textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _refresh, child: const Text('Retry')),
                ],
              ),
            ),
          );
        }
        final TrainingProgram? program = snapshot.data;
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
          onRefresh: _refresh,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              Text(program.programName,
                  style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 4),
              Text(
                  '${program.splitType} · ${program.weeklyFrequency} days/week'),
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
      },
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
