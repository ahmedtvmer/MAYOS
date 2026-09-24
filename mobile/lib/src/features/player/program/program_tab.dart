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
          return const Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                  'No active program yet. Complete onboarding to build one.'),
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
