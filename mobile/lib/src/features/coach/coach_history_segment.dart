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

typedef _ExerciseHistoryDisplay = ({
  CoachExerciseHistoryPoint point,
  WorkoutEquipmentKind? zeroLoadKind,
  String weight,
  String weightUnit,
  String? rir,
  String? e1rm,
});

enum CoachHistorySection {
  recentSessions,
  records,
  checkpoints,
  exercises,
}

const CoachTableColumns _recentSessionColumns =
    CoachTableColumns(<double>[120, 190, 70, 110, 350], 4);

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
  static const CoachTableColumns _recordColumns = CoachTableColumns(
    <double>[250, 110, 110, 65, 115],
    0,
  );
  static const CoachTableColumns _historyColumns = CoachTableColumns(
    <double>[105, 135, 65, 70, 95],
    0,
  );

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
        label: copy.weeklyVolume,
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
      return _section(context, copy.weeklyVolume, <Widget>[Text(copy.noVolume)]);
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final double largestVolume = entries.first.value;
    return _section(
      context,
      copy.weeklyVolume,
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
    final List<Widget> flags = _SessionFlagData.fromSession(context, (
      divergences: latest.divergences,
      warmupMovementCount: latest.warmupMovements.length,
      cardio: latest.cardio,
      readinessScore: latest.readinessScore,
      programVersion: latest.programVersion,
      activeProgramVersionAtSync: latest.activeProgramVersionAtSync,
      isHistoricalProgram: latest.isHistoricalProgram,
      corrections: latest.corrections,
    )).chips;
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
          _wrappedSessionFlagChips(context, flags),
        ],
      const SizedBox(height: MayosSpacing.sm),
      if (isDesktopLayout(context))
        _sessionExerciseTable(context, latest.exercises)
      else
        _sessionExerciseCompactRows(context, latest.exercises),
    ]);
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
                if (isDesktopLayout(context))
                  _recentSessionsTable(context, sessions)
                else
                  for (final CoachPlayerRecentSession session in sessions)
                    _RecentSessionRow(
                      key: ValueKey<String>(
                        'coach_history_recent_session_${session.sessionId}',
                      ),
                      session: session,
                    ),
              ],
      ),
    );
  }

  Widget _recentSessionsTable(
    BuildContext context,
    List<CoachPlayerRecentSession> sessions,
  ) {
    return CoachExerciseTableFrame(
      columns: _recentSessionColumns,
      child: Column(
        children: <Widget>[
          _recentSessionTableHeader(context),
          for (final CoachPlayerRecentSession session in sessions)
            _RecentSessionRow(
              key: ValueKey<String>(
                'coach_history_recent_session_${session.sessionId}',
              ),
              session: session,
            ),
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
            : <Widget>[_recordsContent(context, copy)],
      ),
    );
  }

  Widget _recordsContent(BuildContext context, CoachCopy copy) {
    return isDesktopLayout(context)
        ? _recordsDesktopTable(context, copy)
        : _recordsPhoneRows(context, copy);
  }

  Widget _recordsPhoneRows(BuildContext context, CoachCopy copy) => Column(
        children: <Widget>[
          for (final PersonalRecord record in data.records)
            CoachCompactExerciseRow(
              imagePath: record.imagePath,
              name: record.name,
              muscleLine:
                  coachExerciseMuscleLabel(context, record.primaryMuscle),
              prescription: copy.recordCompactSummary(
                record.recordType,
                '${record.value}',
                record.reps,
                _achievedDate(record.achievedAt),
              ),
            ),
        ],
      );

  Widget _recordsDesktopTable(BuildContext context, CoachCopy copy) =>
      CoachExerciseTableFrame(
        columns: _recordColumns,
        child: Column(
          children: <Widget>[
            _tableHeader(
              context,
              <String>[
                copy.programExerciseColumn,
                copy.recordTypeColumn,
                copy.valueColumn,
                copy.programRepsColumn,
                copy.dateColumn,
              ],
            ),
            for (final PersonalRecord record in data.records)
              _recordTableRow(context, copy, record),
          ],
        ),
      );

  Widget _recordTableRow(
    BuildContext context,
    CoachCopy copy,
    PersonalRecord record,
  ) =>
      CoachExerciseTableRow(
        cells: <Widget>[
          CoachExerciseCell(
            imagePath: record.imagePath,
            name: record.name,
            muscleLine:
                coachExerciseMuscleLabel(context, record.primaryMuscle),
          ),
          _tableText(context, copy.recordTypeLabel(record.recordType)),
          _tableText(context, copy.recordValueLabel(
            record.recordType,
            '${record.value}',
            record.reps,
          )),
          _tableText(context, copy.recordRepsCell(record.reps),
              textDirection: TextDirection.ltr),
          _tableText(context, _achievedDate(record.achievedAt),
              textDirection: TextDirection.ltr),
        ],
      );

  Widget _tableHeader(
    BuildContext context,
    List<String> labels,
  ) =>
      CoachExerciseTableHeader(
        labels: labels,
        alignments: List<TextAlign>.filled(labels.length, TextAlign.start),
      );

  String _achievedDate(String achievedAt) => achievedAt.split('T').first;

  Widget _tableText(
    BuildContext context,
    String text, {
    TextDirection? textDirection,
  }) =>
      Text(
        text,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        textDirection: textDirection,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: MayosTheme.of(context).textPrimary),
      );

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
    return _exerciseHistoryContent(context, history);
  }

  Widget _exerciseHistoryContent(
    BuildContext context,
    CoachExerciseHistory history,
  ) {
    final CoachCopy copy = coachCopyOf(context);
    final List<_ExerciseHistoryDisplay> points =
        _exerciseHistoryDisplays(context, copy, history);
    final String? caption = _historyCaption(history.caption, points);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (caption != null) Text(caption),
        const SizedBox(height: MayosSpacing.xxs),
        _exerciseHistoryPoints(context, copy, history, points),
        if (history.records.isNotEmpty)
          ..._historyRecordRows(context, copy, history),
      ],
    );
  }

  List<_ExerciseHistoryDisplay> _exerciseHistoryDisplays(
    BuildContext context,
    CoachCopy copy,
    CoachExerciseHistory history,
  ) =>
      <_ExerciseHistoryDisplay>[
        for (final CoachExerciseHistoryPoint point in history.history)
          _exerciseHistoryDisplay(context, copy, point, history.equipment),
      ];

  _ExerciseHistoryDisplay _exerciseHistoryDisplay(
    BuildContext context,
    CoachCopy copy,
    CoachExerciseHistoryPoint point,
    String? equipment,
  ) {
    final WorkoutEquipmentKind? zeroLoadKind =
        zeroLoadLabelKind(point.weightKg, equipment);
    final String weight = zeroLoadKind == null
        ? '${point.weightKg}'
        : workoutCopyOf(context).zeroLoadWeightLabel(zeroLoadKind);
    final String weightUnit = exerciseWeightUnit(point.weightKg, equipment);
    return (
      point: point,
      zeroLoadKind: zeroLoadKind,
      weight: weight,
      weightUnit: weightUnit,
      rir: _historyRirLabel(point),
      e1rm: zeroLoadKind == null ? '${point.e1rm}' : null,
    );
  }

  String? _historyRirLabel(CoachExerciseHistoryPoint point) {
    // Effort is hidden when nobody rated the set, as this line always
    // was; a rated one reads as RIR (#111).
    return point.rpe == null ? null : rirLabel(point.rpe!);
  }

  String? _historyCaption(
    String? caption,
    List<_ExerciseHistoryDisplay> points,
  ) {
    if (caption == null || points.isEmpty) return caption;
    return points.last.zeroLoadKind == null ? caption : null;
  }

  Widget _exerciseHistoryPoints(
    BuildContext context,
    CoachCopy copy,
    CoachExerciseHistory history,
    List<_ExerciseHistoryDisplay> points,
  ) {
    if (history.history.isEmpty) return Text(copy.noExerciseSets);
    if (isDesktopLayout(context)) {
      return _exerciseHistoryTable(context, copy, points);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (final _ExerciseHistoryDisplay point in points)
          _exerciseHistoryCompactRow(copy, point),
      ],
    );
  }

  Widget _exerciseHistoryCompactRow(
    CoachCopy copy,
    _ExerciseHistoryDisplay display,
  ) =>
      Text(copy.exerciseHistoryCompactPoint(
        display.point.date,
        display.weight,
        display.point.reps,
        weightUnit: display.weightUnit,
        rir: display.rir,
        e1rm: display.e1rm,
      ));

  Widget _exerciseHistoryTable(
    BuildContext context,
    CoachCopy copy,
    List<_ExerciseHistoryDisplay> points,
  ) =>
      CoachExerciseTableFrame(
        columns: _historyColumns,
        child: Column(
          children: <Widget>[
            _tableHeader(
              context,
              <String>[
                copy.dateColumn,
                copy.weightColumn,
                copy.programRepsColumn,
                copy.programRirColumn,
                copy.e1rmColumn,
              ],
            ),
            for (final _ExerciseHistoryDisplay point in points)
              _historyTableRow(context, copy, point),
          ],
        ),
      );

  Widget _historyTableRow(
    BuildContext context,
    CoachCopy copy,
    _ExerciseHistoryDisplay point,
  ) =>
      CoachExerciseTableRow(
        cells: _historyTableCells(context, copy, point),
      );

  List<Widget> _historyTableCells(
    BuildContext context,
    CoachCopy copy,
    _ExerciseHistoryDisplay display,
  ) =>
      <Widget>[
        _tableText(
          context,
          display.point.date,
          textDirection: TextDirection.ltr,
        ),
        _historyWeightCell(context, copy, display),
        _tableText(
          context,
          '${display.point.reps}',
          textDirection: TextDirection.ltr,
        ),
        _tableText(
          context,
          display.rir ?? '',
          textDirection: TextDirection.ltr,
        ),
        _tableText(
          context,
          display.e1rm ?? '',
          textDirection: TextDirection.ltr,
        ),
      ];

  Widget _historyWeightCell(
    BuildContext context,
    CoachCopy copy,
    _ExerciseHistoryDisplay display,
  ) {
    final String weight = copy.exerciseHistoryWeight(
      display.weight,
      weightUnit: display.weightUnit,
    );
    return _tableText(
      context,
      weight,
      textDirection: display.zeroLoadKind == null ? TextDirection.ltr : null,
    );
  }

  List<Widget> _historyRecordRows(
    BuildContext context,
    CoachCopy copy,
    CoachExerciseHistory history,
  ) =>
      <Widget>[
        const SizedBox(height: MayosSpacing.xs),
        Text(copy.records),
        for (final CoachExerciseRecord record in history.records)
          Text(copy.recordHistory(
            record.recordType,
            '${record.value}',
            record.reps,
            _achievedDate(record.achievedAt),
          )),
      ];

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
                    title: CoachExerciseCell(
                      imagePath: exercise.imagePath,
                      name: exercise.name,
                      muscleLine: coachExerciseMuscleLabel(
                        context,
                        exercise.primaryMuscle,
                      ),
                    ),
                    children: <Widget>[
                      _exerciseDetail(context, exercise.id),
                    ],
                  ),
              ],
      ),
    );
  }
}

Widget _recentSessionTableHeader(BuildContext context) {
  final copy = coachCopyOf(context);
  return CoachExerciseTableHeader(
    labels: <String>[
      copy.sessionDateColumn,
      copy.sessionSplitColumn,
      copy.programSetsColumn,
      copy.sessionVolumeColumn,
      copy.sessionFlagsColumn,
    ],
    alignments: <TextAlign>[
      TextAlign.start,
      TextAlign.start,
      TextAlign.center,
      TextAlign.center,
      TextAlign.start,
    ],
  );
}

Widget _wrappedSessionFlagChips(BuildContext context, List<Widget> flags) =>
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
    );

String _sessionDivergenceLabel(
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

const CoachTableColumns _sessionExerciseColumns =
    CoachTableColumns(<double>[290, 185, 95, 70, 120], 0);

Widget _sessionExerciseTable(
  BuildContext context,
  List<CoachPlayerSessionExercise> exercises,
) =>
    CoachExerciseTableFrame(
      columns: _sessionExerciseColumns,
      child: _sessionExerciseTableContent(context, exercises),
    );

Widget _sessionExerciseTableContent(
  BuildContext context,
  List<CoachPlayerSessionExercise> exercises,
) =>
    Column(
      children: <Widget>[
        _sessionExerciseTableHeader(context),
        for (final CoachPlayerSessionExercise exercise in exercises)
          _sessionExerciseTableRow(context, exercise),
      ],
    );

Widget _sessionExerciseTableHeader(BuildContext context) {
  final copy = coachCopyOf(context);
  return CoachExerciseTableHeader(
    labels: <String>[
      copy.programExerciseColumn,
      copy.programActionColumn,
      copy.programSetsColumn,
      copy.programRepsColumn,
      copy.sessionVolumeColumn,
    ],
    alignments: <TextAlign>[
      TextAlign.start,
      TextAlign.start,
      TextAlign.center,
      TextAlign.center,
      TextAlign.center,
    ],
  );
}

Widget _sessionExerciseTableRow(
  BuildContext context,
  CoachPlayerSessionExercise exercise,
) =>
    CoachExerciseTableRow(
      cells: _sessionExerciseTableCells(context, exercise),
    );

List<Widget> _sessionExerciseTableCells(
  BuildContext context,
  CoachPlayerSessionExercise exercise,
) {
  final copy = coachCopyOf(context);
  return <Widget>[
    CoachExerciseCell(
      imagePath: exercise.imagePath,
      name: exercise.name,
      muscleLine: coachExerciseMuscleLabel(context, exercise.primaryMuscle),
    ),
    CoachExerciseActionCell(primaryAction: exercise.primaryAction),
    Text('${exercise.sets}', textAlign: TextAlign.center),
    Text('${exercise.reps}', textAlign: TextAlign.center),
    Text(
      copy.formatVolume(exercise.volumeKg),
      textAlign: TextAlign.center,
      textDirection: TextDirection.ltr,
    ),
  ];
}

Widget _sessionExerciseCompactRows(
  BuildContext context,
  List<CoachPlayerSessionExercise> exercises,
) {
  return Column(
    children: <Widget>[
      for (int index = 0; index < exercises.length; index++) ...<Widget>[
        if (index > 0) const Divider(height: 1),
        _sessionExerciseCompactRow(context, exercises[index]),
      ],
    ],
  );
}

Widget _sessionExerciseCompactRow(
  BuildContext context,
  CoachPlayerSessionExercise exercise,
) {
  final copy = coachCopyOf(context);
  return CoachCompactExerciseRow(
    imagePath: exercise.imagePath,
    name: exercise.name,
    muscleLine: coachExerciseMuscleLabel(context, exercise.primaryMuscle),
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
}

class _RecentSessionRow extends StatefulWidget {
  const _RecentSessionRow({super.key, required this.session});

  final CoachPlayerRecentSession session;

  @override
  State<_RecentSessionRow> createState() => _RecentSessionRowState();
}

class _RecentSessionRowState extends State<_RecentSessionRow> {
  bool _expanded = false;

  CoachPlayerRecentSession get session => widget.session;

  @override
  Widget build(BuildContext context) {
    final _SessionFlagData flagData = _SessionFlagData.fromSession(context, (
        divergences: session.divergences,
        warmupMovementCount: session.warmupMovements.length,
        cardio: session.cardio,
        readinessScore: session.readinessScore,
        programVersion: session.programVersion,
        activeProgramVersionAtSync: session.activeProgramVersionAtSync,
        isHistoricalProgram: session.isHistoricalProgram,
        corrections: session.corrections,
      ));
    final List<Widget> flags = flagData.chips;
    return Column(
      children: <Widget>[
        isDesktopLayout(context)
            ? _desktopSummary(context, flags)
            : _compactSummary(context, flags),
        if (_expanded) _expandedDetails(context),
      ],
    );
  }

  void _toggle() => setState(() => _expanded = !_expanded);

  Widget _desktopSummary(BuildContext context, List<Widget> flags) {
    return _rowToggle(
      context,
      CoachExerciseTableRow(
        cells: _desktopCells(context, flags),
      ),
    );
  }

  List<Widget> _desktopCells(BuildContext context, List<Widget> flags) =>
      <Widget>[
        Text(session.sessionDate, textDirection: TextDirection.ltr),
        Text(session.splitName, maxLines: 2, overflow: TextOverflow.ellipsis),
        Text('${session.setsCount}', textAlign: TextAlign.center),
        Text(
          coachCopyOf(context).formatVolume(session.totalVolumeKg),
          textAlign: TextAlign.center,
          textDirection: TextDirection.ltr,
        ),
        _desktopFlagsCell(context, flags),
      ];

  Widget _desktopFlagsCell(BuildContext context, List<Widget> flags) => Row(
        children: <Widget>[
          Expanded(
            child: flags.isEmpty
                ? const SizedBox.shrink()
                : _wrappedSessionFlagChips(context, flags),
          ),
          _expandCollapseIcon(context),
        ],
      );

  Widget _compactSummary(BuildContext context, List<Widget> flags) {
    return _rowToggle(
      context,
      Padding(
        padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
        child: Row(
          children: <Widget>[
            _expandCollapseIcon(context),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(child: _compactContent(context, flags)),
          ],
        ),
      ),
    );
  }

  Widget _compactContent(BuildContext context, List<Widget> flags) {
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(copy.sessionTitle(session.splitName, session.sessionDate)),
        Text(
          copy.latestSessionTotals(session.setsCount, session.totalVolumeKg),
        ),
        if (flags.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.xxs),
          _wrappedSessionFlagChips(context, flags),
        ],
      ],
    );
  }

  Widget _rowToggle(BuildContext context, Widget child) => Semantics(
        button: true,
        expanded: _expanded,
        child: InkWell(
          key: Key('coach_history_recent_session_${session.sessionId}_toggle'),
          onTap: _toggle,
          child: child,
        ),
      );

  Widget _expandCollapseIcon(BuildContext context) => Icon(
        _expanded ? Icons.expand_less : Icons.expand_more,
        color: MayosTheme.of(context).textSecondary,
        size: MayosIconSizes.small,
      );

  Widget _expandedDetails(BuildContext context) {
    final bool desktop = isDesktopLayout(context);
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: MayosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Padding(
            padding: const EdgeInsetsDirectional.only(
              start: MayosSpacing.sm,
              end: MayosSpacing.sm,
            ),
            child: _expandedSummary(context),
          ),
          Padding(
            padding: EdgeInsetsDirectional.only(
              start: MayosSpacing.sm,
              end: desktop ? 0 : MayosSpacing.sm,
            ),
            child: _exerciseBreakdown(context),
          ),
        ],
      ),
    );
  }

  Widget _expandedSummary(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            coachCopyOf(context).sessionExerciseCompact(
              session.setsCount,
              session.exercises.fold<int>(
                0,
                (int total, CoachPlayerSessionExercise exercise) =>
                    total + exercise.reps,
              ),
              session.totalVolumeKg,
            ),
          ),
          const SizedBox(height: MayosSpacing.xs),
        ],
      );

  Widget _exerciseBreakdown(BuildContext context) => isDesktopLayout(context)
      ? CoachExerciseTableFrame(
          columns: _sessionExerciseColumns,
          decorated: false,
          scrollable: false,
          child: _sessionExerciseTableContent(context, session.exercises),
        )
      : _sessionExerciseCompactRows(context, session.exercises);
}

typedef _SessionFlagFields = ({
  List<CoachPlayerDivergence> divergences,
  int warmupMovementCount,
  WorkoutCardio? cardio,
  int? readinessScore,
  int? programVersion,
  int? activeProgramVersionAtSync,
  bool isHistoricalProgram,
  List<PerformedDateCorrection> corrections,
});

class _SessionFlagData {
  const _SessionFlagData(this.labels);

  final List<String> labels;

  factory _SessionFlagData.fromSession(
    BuildContext context,
    _SessionFlagFields fields,
  ) {
    final copy = coachCopyOf(context);
    final String? versionNote = copy.historicalProgramIfNeeded(
      fields.programVersion,
      fields.activeProgramVersionAtSync,
      fields.isHistoricalProgram,
    );
    return _SessionFlagData(<String>[
      for (final CoachPlayerDivergence divergence in fields.divergences)
        _sessionDivergenceLabel(context, divergence),
      if (fields.warmupMovementCount > 0)
        copy.warmupMovements(fields.warmupMovementCount),
      if (fields.cardio != null) copy.cardioMinutes(fields.cardio!.minutes),
      if (fields.readinessScore != null) copy.readiness(fields.readinessScore!),
      if (versionNote != null) versionNote,
      for (final PerformedDateCorrection correction in fields.corrections)
        copy.correctedDate(correction.previousDate, correction.correctedDate),
    ]);
  }

  List<Widget> get chips => <Widget>[
        for (final String label in labels) CoachStatusChip(label: label),
      ];
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
