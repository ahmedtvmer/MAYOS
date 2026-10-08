import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/effort.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/workout_equipment.dart';
import 'coach_exercise_table.dart';

enum CoachHistorySection {
  recentSessions,
  records,
  checkpoints,
  exercises,
}

class CoachHistorySegmentData {
  const CoachHistorySegmentData({
    required this.summary,
    required this.records,
    required this.checkpointReviews,
    required this.exercises,
    required this.histories,
    required this.openExerciseId,
    required this.loadingHistory,
    required this.expandedSections,
  });

  final CoachPlayerSummary summary;
  final List<PersonalRecord> records;
  final List<CheckpointReviewListItem> checkpointReviews;
  final List<CoachPlayerExercise> exercises;
  final Map<String, CoachExerciseHistory> histories;
  final String? openExerciseId;
  final bool loadingHistory;
  final Map<CoachHistorySection, bool> expandedSections;
}

class CoachHistorySegment extends StatelessWidget {
  const CoachHistorySegment({
    super.key,
    required this.data,
    required this.onToggleSection,
    required this.onExerciseToggle,
    required this.onCheckpointTap,
  });

  final CoachHistorySegmentData data;
  final ValueChanged<CoachHistorySection> onToggleSection;
  final ValueChanged<CoachPlayerExercise> onExerciseToggle;
  final ValueChanged<CheckpointReviewListItem> onCheckpointTap;

  @override
  Widget build(BuildContext context) {
    final List<MapEntry<String, double>> entries = _volumeEntries();
    final double weeklySets = entries.fold<double>(
      0,
      (double total, MapEntry<String, double> entry) => total + entry.value,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _summaryCard(context, weeklySets),
        const SizedBox(height: MayosSpacing.sm),
        _latestSessionCard(context),
        const SizedBox(height: MayosSpacing.sm),
        _volumeCard(context, entries),
        const SizedBox(height: MayosSpacing.sm),
        if (data.summary.schedule != null || data.summary.pauses.isNotEmpty)
          ...<Widget>[
            _scheduleCard(context),
            const SizedBox(height: MayosSpacing.sm),
          ],
        _recentSessionsCard(context),
        const SizedBox(height: MayosSpacing.sm),
        _recordsCard(context),
        const SizedBox(height: MayosSpacing.sm),
        _checkpointReviewsCard(context),
        const SizedBox(height: MayosSpacing.sm),
        _exercisesCard(context),
      ],
    );
  }

  List<MapEntry<String, double>> _volumeEntries() {
    final List<MapEntry<String, double>> entries = data.summary.volume.entries
        .where((MapEntry<String, double> entry) => entry.value > 0)
        .toList();
    entries.sort((MapEntry<String, double> first,
        MapEntry<String, double> second) {
      final int byVolume = second.value.compareTo(first.value);
      return byVolume == 0 ? first.key.compareTo(second.key) : byVolume;
    });
    return entries;
  }

  Widget _summaryCard(BuildContext context, double weeklySets) {
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final int columns = isDesktopLayout(context) ? 4 : 2;
          final double tileWidth = (constraints.maxWidth -
                  (MayosSpacing.xs * (columns - 1))) /
              columns;
          return Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (final Widget stat in _summaryStats(context, weeklySets))
                SizedBox(width: tileWidth, child: stat),
            ],
          );
        },
      ),
    );
  }

  List<Widget> _summaryStats(BuildContext context, double weeklySets) {
    final copy = coachCopyOf(context);
    final CoachPlayerLatestSession? latest = data.summary.latestSession;
    return <Widget>[
      _HistoryStatTile(
        label: copy.coachingSince,
        value: copy.coachingSinceDate(data.summary.startedAt.split('T').first),
      ),
      if (latest != null)
        _HistoryStatTile(label: copy.lastSession, value: latest.sessionDate),
      _HistoryStatTile(
        label: copy.weeklyWorkingSets,
        value: _formatWorkingSets(weeklySets),
      ),
      _HistoryStatTile(
        label: copy.personalRecordsTitle,
        value: '${data.records.length}',
      ),
    ];
  }

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

  Widget _historySection(
    BuildContext context, {
    required CoachHistorySection section,
    required _HistorySectionContent content,
  }) {
    final bool expanded = data.expandedSections[section] ?? false;
    return _CollapsibleHistorySection(
      heading: (
        key: Key('coach_history_section_${section.name}_semantics'),
        label: '${content.title} '
            '${coachCopyOf(context).historyItemCount(content.count)}',
      ),
      expanded: expanded,
      onToggle: () => onToggleSection(section),
      children: content.children,
    );
  }

  Widget _volumeCard(
    BuildContext context,
    List<MapEntry<String, double>> entries,
  ) {
    final copy = coachCopyOf(context);
    if (entries.isEmpty) {
      return _section(context, copy.playerVolume, <Widget>[Text(copy.noVolume)]);
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final double largestVolume = entries.first.value;
    return _section(
      context,
      copy.playerVolume,
      <Widget>[
        for (final MapEntry<String, double> entry in entries)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
            child: Row(
              children: <Widget>[
                Flexible(
                  child: Text(
                    entry.key,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.ltr,
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: ClipRRect(
                    borderRadius: MayosRadii.pillRadius,
                    child: LinearProgressIndicator(
                      value: entry.value / largestVolume,
                      minHeight: MayosSpacing.xs,
                      color: c.chartPrimary,
                      backgroundColor: c.surfaceSunken,
                    ),
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Text(
                  _formatWorkingSets(entry.value),
                  textDirection: TextDirection.ltr,
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _scheduleCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final CoachPlayerSchedule? schedule = data.summary.schedule;
    final List<Widget> children = <Widget>[];
    if (schedule != null) {
      final String days = schedule.weekdays.map(copy.weekday).join(', ');
      children.add(_scheduleRow(
        context,
        copy.expectedDays(days),
        Icons.calendar_month_outlined,
      ));
      children.add(_scheduleRow(
        context,
        copy.timezone(schedule.timezone),
        Icons.schedule_outlined,
      ));
    }
    for (final CoachPlayerPause pause in data.summary.pauses) {
      children.add(_scheduleRow(
        context,
        copy.pauseDates(pause.startsOn, pause.endsOn),
        Icons.pause_circle_outline,
      ));
    }
    return _section(context, copy.trainingSchedule, children);
  }

  Widget _scheduleRow(BuildContext context, String text, IconData icon) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
      child: Container(
        padding: const EdgeInsets.all(MayosSpacing.sm),
        decoration: BoxDecoration(
          color: c.surfaceElevated,
          borderRadius: MayosRadii.mediumRadius,
          border: Border.all(color: c.border),
        ),
        child: Row(
          children: <Widget>[
            Icon(icon, size: MayosIconSizes.medium, color: c.textSecondary),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(child: Text(text)),
          ],
        ),
      ),
    );
  }

  Widget _latestSessionCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final CoachPlayerLatestSession? latest = data.summary.latestSession;
    if (latest == null) {
      return _section(
          context, copy.latestSession, <Widget>[Text(copy.noSessions)]);
    }
    final String? versionNote = copy.historicalProgramIfNeeded(
      latest.programVersion,
      latest.activeProgramVersionAtSync,
      latest.isHistoricalProgram,
    );
    final List<Widget> flags =
        _latestSessionFlagChips(context, latest, versionNote);
    return _section(context, copy.latestSession, <Widget>[
      Text(
        copy.sessionTitle(latest.splitName, latest.sessionDate),
        style: MayosTypography.of(context)
            .body
            .copyWith(color: MayosTheme.of(context).textPrimary),
      ),
      Text(copy.latestSessionTotals(latest.setsCount, latest.totalVolumeKg)),
      if (flags.isNotEmpty)
        ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) => Wrap(
              spacing: MayosSpacing.xs,
              runSpacing: MayosSpacing.xs,
              children: <Widget>[
                for (final Widget flag in flags)
                  ConstrainedBox(
                    constraints: BoxConstraints(maxWidth: constraints.maxWidth),
                    child: flag,
                  ),
              ],
            ),
          ),
        ],
      const SizedBox(height: MayosSpacing.sm),
      if (isDesktopLayout(context))
        _latestSessionTable(context, latest)
      else
        _latestSessionCompactRows(context, latest),
    ]);
  }

  List<Widget> _latestSessionFlagChips(
    BuildContext context,
    CoachPlayerLatestSession latest,
    String? versionNote,
  ) {
    final copy = coachCopyOf(context);
    return <Widget>[
      for (final CoachPlayerDivergence divergence in latest.divergences)
        CoachStatusChip(label: _divergenceLabel(context, divergence)),
      if (latest.warmupMovements.isNotEmpty)
        CoachStatusChip(
          label: copy.warmupMovements(latest.warmupMovements.length),
        ),
      if (latest.cardio != null)
        CoachStatusChip(label: copy.cardioMinutes(latest.cardio!.minutes)),
      if (latest.readinessScore != null)
        CoachStatusChip(label: copy.readiness(latest.readinessScore!)),
      if (versionNote != null) CoachStatusChip(label: versionNote),
      for (final PerformedDateCorrection correction in latest.corrections)
        CoachStatusChip(
          label: copy.correctedDate(
            correction.previousDate,
            correction.correctedDate,
          ),
        ),
    ];
  }

  Widget _latestSessionTable(
    BuildContext context,
    CoachPlayerLatestSession latest,
  ) {
    const List<double> widths = <double>[290, 160, 70, 70, 120];
    final copy = coachCopyOf(context);
    return CoachExerciseTableFrame(
      widths: widths,
      child: Column(
        children: <Widget>[
          CoachExerciseTableHeader(
            labels: <String>[
              copy.programExerciseColumn,
              copy.programActionColumn,
              copy.programSetsColumn,
              copy.programRepsColumn,
              copy.sessionVolumeColumn,
            ],
            widths: widths,
            alignments: <TextAlign>[
              TextAlign.start,
              TextAlign.start,
              TextAlign.center,
              TextAlign.center,
              TextAlign.center,
            ],
          ),
          for (final CoachPlayerSessionExercise exercise in latest.exercises)
            _latestSessionTableRow(context, exercise, widths),
        ],
      ),
    );
  }

  Widget _latestSessionTableRow(
    BuildContext context,
    CoachPlayerSessionExercise exercise,
    List<double> widths,
  ) =>
      CoachExerciseTableRow(
        widths: widths,
        cells: <Widget>[
          CoachExerciseCell(
            imagePath: exercise.imagePath,
            name: exercise.name,
            muscleLine: coachExerciseMuscleLabel(
              context,
              exercise.primaryMuscle,
            ),
          ),
          CoachExerciseActionCell(primaryAction: exercise.primaryAction),
          Text('${exercise.sets}', textAlign: TextAlign.center),
          Text('${exercise.reps}', textAlign: TextAlign.center),
          Text(
            coachCopyOf(context).formatVolume(exercise.volumeKg),
            textAlign: TextAlign.center,
            textDirection: TextDirection.ltr,
          ),
        ],
      );

  Widget _latestSessionCompactRows(
    BuildContext context,
    CoachPlayerLatestSession latest,
  ) {
    final copy = coachCopyOf(context);
    return Column(
      children: <Widget>[
        for (int index = 0;
            index < latest.exercises.length;
            index++) ...<Widget>[
          if (index > 0) const Divider(height: 1),
          _latestSessionCompactRow(context, copy, latest.exercises[index]),
        ],
      ],
    );
  }

  Widget _latestSessionCompactRow(
    BuildContext context,
    CoachCopy copy,
    CoachPlayerSessionExercise exercise,
  ) =>
      CoachCompactExerciseRow(
        imagePath: exercise.imagePath,
        name: exercise.name,
        muscleLine: coachExerciseMuscleLabel(
          context,
          exercise.primaryMuscle,
        ),
        prescription: copy.sessionExerciseCompact(
          exercise.sets,
          exercise.reps,
          exercise.volumeKg,
        ),
        secondaryLine: coachExerciseActionDetailLine(
          context,
          exercise.primaryAction,
        ),
      );

  String _divergenceLabel(
    BuildContext context,
    CoachPlayerDivergence divergence,
  ) {
    final String kind = switch (divergence.kind) {
      'skipped' => 'Skipped',
      'unplanned' => 'Unplanned',
      _ => divergence.kind,
    };
    return coachCopyOf(context).divergence(kind, divergence.exerciseName);
  }

  Widget _recentSessionsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    final List<CoachPlayerRecentSession> sessions =
        data.summary.recentSessions;
    return _historySection(
      context,
      section: CoachHistorySection.recentSessions,
      content: (
        title: copy.recentSessions,
        count: sessions.length,
        children: sessions.isEmpty
            ? <Widget>[Text(copy.noSessions)]
            : <Widget>[
                for (final CoachPlayerRecentSession session in sessions)
                  _recentSessionTile(context, session),
              ],
      ),
    );
  }

  Widget _recentSessionTile(
    BuildContext context,
    CoachPlayerRecentSession session,
  ) {
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
            Text(_divergenceLabel(context, divergence)),
        ],
      ),
    );
  }

  Widget _recordsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    return _historySection(
      context,
      section: CoachHistorySection.records,
      content: (
        title: copy.personalRecordsTitle,
        count: data.records.length,
        children: data.records.isEmpty
            ? <Widget>[Text(copy.noPersonalRecords)]
            : <Widget>[
                for (final PersonalRecord record in data.records)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(record.name),
                    subtitle: Text(copy.recordSummary(
                        record.recordType, '${record.value}', record.reps)),
                  ),
              ],
      ),
    );
  }

  Widget _checkpointReviewsCard(BuildContext context) {
    final copy = coachCopyOf(context);
    return _historySection(
      context,
      section: CoachHistorySection.checkpoints,
      content: (
        title: copy.checkpoints,
        count: data.checkpointReviews.length,
        children: data.checkpointReviews.isEmpty
            ? <Widget>[Text(copy.noCheckpoints)]
            : <Widget>[
                for (final CheckpointReviewListItem review
                    in data.checkpointReviews)
                  _checkpointRow(context, review),
              ],
      ),
    );
  }

  Widget _checkpointRow(
    BuildContext context,
    CheckpointReviewListItem review,
  ) {
    final copy = coachCopyOf(context);
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool rtl = Directionality.of(context) == TextDirection.rtl;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
      child: MayosCard(
        key: ValueKey<String>('coach.checkpoint.${review.checkpoint}'),
        onTap: () => onCheckpointTap(review),
        color: c.surfaceElevated,
        radius: MayosRadii.medium,
        padding: const EdgeInsets.all(MayosSpacing.sm),
        child: Row(
          children: <Widget>[
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    copy.checkpointNumber(review.checkpoint),
                    style: MayosTypography.of(context).label,
                  ),
                  Text(copy.checkpointPeriod(
                      review.periodStart, review.periodEnd)),
                ],
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Icon(
              rtl ? Icons.chevron_left : Icons.chevron_right,
              color: c.textSecondary,
            ),
          ],
        ),
      ),
    );
  }

  Widget _exerciseDetail(BuildContext context, String exerciseId) {
    final copy = coachCopyOf(context);
    if (data.loadingHistory) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final CoachExerciseHistory? history = data.histories[exerciseId];
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
    return _historySection(
      context,
      section: CoachHistorySection.exercises,
      content: (
        title: copy.exercises,
        count: data.exercises.length,
        children: data.exercises.isEmpty
            ? <Widget>[Text(copy.noExercisesLogged)]
            : <Widget>[
                for (final CoachPlayerExercise exercise in data.exercises)
                  ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    initiallyExpanded: data.openExerciseId == exercise.id,
                    onExpansionChanged: (_) => onExerciseToggle(exercise),
                    title: Text(exercise.name),
                    children: <Widget>[
                      _exerciseDetail(context, exercise.id),
                    ],
                  ),
              ],
      ),
    );
  }
}

class _HistoryStatTile extends StatelessWidget {
  const _HistoryStatTile({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool rtl = Directionality.of(context) == TextDirection.rtl;
    return Container(
      padding: const EdgeInsets.all(MayosSpacing.sm),
      decoration: BoxDecoration(
        color: c.surfaceElevated,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            label,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            value,
            style: MayosTypography.of(context).numericSmall
                .copyWith(color: c.textPrimary),
            textAlign: rtl ? TextAlign.end : TextAlign.start,
            textDirection: TextDirection.ltr,
          ),
        ],
      ),
    );
  }
}

class _CollapsibleHistorySection extends StatelessWidget {
  const _CollapsibleHistorySection({
    required this.heading,
    required this.expanded,
    required this.onToggle,
    required this.children,
  });

  final _HistorySectionHeading heading;
  final bool expanded;
  final VoidCallback onToggle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Semantics(
        key: heading.key,
        button: true,
        expanded: expanded,
        label: heading.label,
        child: MayosCard(
          onTap: onToggle,
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Semantics(
                excludeSemantics: true,
                child: MayosSectionHeader(
                  title: heading.label,
                  padding: EdgeInsets.only(
                    bottom: expanded ? MayosSpacing.xs : 0,
                  ),
                  trailing: Icon(
                    expanded ? Icons.expand_less : Icons.expand_more,
                  ),
                ),
              ),
              if (expanded) ...children,
            ],
          ),
        ),
      );
}

typedef _HistorySectionHeading = ({Key key, String label});
typedef _HistorySectionContent = ({
  String title,
  int count,
  List<Widget> children,
});

String _formatWorkingSets(double sets) {
  final String formatted = ((sets * 10).round() / 10).toStringAsFixed(1);
  return formatted.endsWith('.0')
      ? formatted.substring(0, formatted.length - 2)
      : formatted;
}
