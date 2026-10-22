import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/catalog.dart' show MyosCopy;
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/effort.dart';
import '../../core/models.dart';
import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/myos_card.dart';
import '../../core/ui/myos_card_table.dart';
import '../../core/ui/myos_section_header.dart';
import '../../core/ui/myos_table_frame.dart';
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

const MyosTableColumns _recentSessionColumns =
    MyosTableColumns(<double>[120, 190, 70, 110, 350], 4);

class CoachHistorySegmentData {
  const CoachHistorySegmentData({
    required this.summary,
    required this.records,
    required this.checkpointReviews,
    this.volumeReview,
    required this.exercises,
    required this.histories,
    required this.openExerciseId,
    required this.loadingHistory,
    required this.expandedSections,
  });

  final CoachPlayerSummary summary;
  final List<PersonalRecord> records;
  final List<CheckpointReviewListItem> checkpointReviews;
  final VolumeReview? volumeReview;
  final List<CoachPlayerExercise> exercises;
  final Map<String, CoachExerciseHistory> histories;
  final String? openExerciseId;
  final bool loadingHistory;
  final Map<CoachHistorySection, bool> expandedSections;
}

class CoachHistorySegment extends StatelessWidget {
  static const MyosTableColumns _recordColumns = MyosTableColumns(
    <double>[250, 110, 110, 65, 115],
    0,
  );
  static const MyosTableColumns _historyColumns = MyosTableColumns(
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
        const SizedBox(height: MyosSpacing.sm),
        _latestSessionCard(context),
        const SizedBox(height: MyosSpacing.sm),
        _volumeCard(context, entries),
        const SizedBox(height: MyosSpacing.sm),
        if (data.summary.schedule != null || data.summary.pauses.isNotEmpty)
          ...<Widget>[
            _scheduleCard(context),
            const SizedBox(height: MyosSpacing.sm),
          ],
        _injuriesCard(context),
        const SizedBox(height: MyosSpacing.sm),
        _recentSessionsCard(context),
        const SizedBox(height: MyosSpacing.sm),
        _recordsCard(context),
        const SizedBox(height: MyosSpacing.sm),
        _checkpointReviewsCard(context),
        const SizedBox(height: MyosSpacing.sm),
        if (data.volumeReview != null) ...<Widget>[
          _volumeReviewCard(context),
          const SizedBox(height: MyosSpacing.sm),
        ],
        _exercisesCard(context),
      ],
    );
  }

  Widget _volumeReviewCard(BuildContext context) {
    final VolumeReview review = data.volumeReview!;
    final MyosCopy copy = displayCopyOf(context);
    return MyosCard(
      padding: const EdgeInsets.all(MyosSpacing.md),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
        MyosSectionHeader(title: copy.volumeReview),
        for (final VolumeReviewMuscle muscle in review.muscles) ...<Widget>[
          const SizedBox(height: MyosSpacing.sm),
          Text(
            '${copy.primaryMuscleLabel(muscle.muscle)} · ${copy.volumeReviewChange(muscle.setDelta)}',
            key: Key('coach_volume_review_muscle_${muscle.muscle}'),
            style: MyosTypography.of(context).exerciseTitle,
          ),
          const SizedBox(height: MyosSpacing.xs),
          Text(
            copy.volumeReviewReason(
              muscle.verdict,
              copy.primaryMuscleLabel(muscle.muscle),
            ),
          ),
        ],
      ]),
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
    return MyosCard(
      padding: const EdgeInsets.all(MyosSpacing.md),
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final int columns = isDesktopLayout(context) ? 4 : 2;
          final double tileWidth = (constraints.maxWidth -
                  (MyosSpacing.xs * (columns - 1))) /
              columns;
          return Wrap(
            spacing: MyosSpacing.xs,
            runSpacing: MyosSpacing.xs,
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
    return MyosCard(
      padding: const EdgeInsets.all(MyosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MyosSectionHeader(
            title: title,
            padding: const EdgeInsets.only(bottom: MyosSpacing.xs),
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
    final double largestVolume = entries.first.value;
    return _section(context, copy.weeklyVolume, <Widget>[
      MyosCardTable(
        columns: <String>[copy.muscleColumn, copy.workingSets],
        desktopTable: Column(
          children: <Widget>[
            for (final MapEntry<String, double> entry in entries)
              _volumeRow(context, entry, largestVolume),
          ],
        ),
        rows: <MyosCardTableRow>[
          for (final MapEntry<String, double> entry in entries)
            MyosCardTableRow(
              cells: <Widget?>[
                Text(
                  displayCopyOf(context).primaryMuscleLabel(entry.key),
                ),
                _volumeBar(context, entry, largestVolume),
              ],
            ),
        ],
      ),
    ]);
  }

  Widget _volumeRow(
    BuildContext context,
    MapEntry<String, double> entry,
    double largestVolume,
  ) =>
      Padding(
        padding: const EdgeInsets.symmetric(vertical: MyosSpacing.xxs),
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
            const SizedBox(width: MyosSpacing.xs),
            Expanded(
              child: ClipRRect(
                borderRadius: MyosRadii.pillRadius,
                child: LinearProgressIndicator(
                  value: entry.value / largestVolume,
                  minHeight: MyosSpacing.xs,
                  color: MyosTheme.of(context).chartPrimary,
                  backgroundColor: MyosTheme.of(context).surfaceSunken,
                ),
              ),
            ),
            const SizedBox(width: MyosSpacing.xs),
            Text(
              _formatWorkingSets(entry.value),
              textDirection: TextDirection.ltr,
            ),
          ],
        ),
      );

  Widget _volumeBar(
    BuildContext context,
    MapEntry<String, double> entry,
    double largestVolume,
  ) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    return Row(
      children: <Widget>[
        Expanded(
          child: ClipRRect(
            borderRadius: MyosRadii.pillRadius,
            child: LinearProgressIndicator(
              value: entry.value / largestVolume,
              minHeight: MyosSpacing.xs,
              color: colors.chartPrimary,
              backgroundColor: colors.surfaceSunken,
            ),
          ),
        ),
        const SizedBox(width: MyosSpacing.xs),
        Text(_formatWorkingSets(entry.value), textDirection: TextDirection.ltr),
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
    final MyosThemeExtension c = MyosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.xs),
      child: Container(
        padding: const EdgeInsets.all(MyosSpacing.sm),
        decoration: BoxDecoration(
          color: c.surfaceElevated,
          borderRadius: MyosRadii.mediumRadius,
          border: Border.all(color: c.border),
        ),
        child: Row(
          children: <Widget>[
            Icon(icon, size: MyosIconSizes.medium, color: c.textSecondary),
            const SizedBox(width: MyosSpacing.xs),
            Expanded(child: Text(text)),
          ],
        ),
      ),
    );
  }

  Widget _injuriesCard(BuildContext context) {
    final copy = coachCopyOf(context);
    if (data.summary.injuries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: MyosSpacing.sm,
          vertical: MyosSpacing.xxs,
        ),
        child: Text(
          '${copy.injuries}: ${copy.noInjuries}',
          style: MyosTypography.of(context).bodySecondary,
        ),
      );
    }
    return _section(
      context,
      copy.injuries,
      <Widget>[
        for (final InjuryRecord injury in data.summary.injuries)
          Padding(
            padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  '${copy.injuryArea(injury.bodyArea)} · ${copy.injuryStatus(injury.status)}',
                  style: MyosTypography.of(context).body.copyWith(
                        color: MyosTheme.of(context).textPrimary,
                      ),
                ),
                Text(injury.description),
                for (final ExerciseClearance clearance in injury.clearances)
                  Padding(
                    padding: const EdgeInsetsDirectional.only(
                      start: MyosSpacing.sm,
                      top: MyosSpacing.xxs,
                    ),
                    child: Text(
                      '${clearance.exerciseName}: ${copy.clearanceVerdict(clearance.verdict)}'
                      '${clearance.note == null ? '' : ' · ${clearance.note}'}',
                    ),
                  ),
              ],
            ),
          ),
      ],
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
        style: MyosTypography.of(context)
            .body
            .copyWith(color: MyosTheme.of(context).textPrimary),
      ),
      Text(copy.latestSessionTotals(latest.setsCount, latest.totalVolumeKg)),
      if (flags.isNotEmpty)
        ...<Widget>[
          const SizedBox(height: MyosSpacing.xs),
          _wrappedSessionFlagChips(context, flags),
        ],
      const SizedBox(height: MyosSpacing.sm),
      if (isDesktopLayout(context))
        _sessionExerciseTable(context, latest.exercises)
      else
        MyosCardTable(
          columns: _sessionExerciseLabels(context),
          rows: _sessionExerciseRows(context, latest.exercises),
        ),
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

  Widget _recordsContent(BuildContext context, CoachCopy copy) =>
      MyosCardTable(
        columns: <String>[copy.programExerciseColumn],
        desktopTable: _recordsDesktopTable(context, copy),
        rows: <MyosCardTableRow>[
          for (final PersonalRecord record in data.records)
            MyosCardTableRow(
              cells: <Widget?>[
                CoachExerciseCell(
                  imagePath: record.imagePath,
                  name: record.name,
                  exerciseId: coachCatalogExerciseId(record.exerciseId),
                  muscleLine: coachExerciseMuscleLabel(
                    context,
                    record.primaryMuscle,
                  ),
                ),
              ],
              subtitle: Text(copy.recordCompactSummary(
                record.recordType,
                '${record.value}',
                record.reps,
                _achievedDate(record.achievedAt),
              )),
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
      MyosTableRow(
        cells: <Widget>[
          CoachExerciseCell(
            imagePath: record.imagePath,
            name: record.name,
            exerciseId: coachCatalogExerciseId(record.exerciseId),
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
      MyosTableHeader(
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
        style: MyosTypography.of(context)
            .bodySecondary
            .copyWith(color: MyosTheme.of(context).textPrimary),
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final bool rtl = Directionality.of(context) == TextDirection.rtl;
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.xs),
      child: MyosCard(
        key: ValueKey<String>('coach.checkpoint.${review.checkpoint}'),
        onTap: () => onCheckpointTap(review),
        color: c.surfaceElevated,
        radius: MyosRadii.medium,
        padding: const EdgeInsets.all(MyosSpacing.sm),
        child: Row(
          children: <Widget>[
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    copy.checkpointNumber(review.checkpoint),
                    style: MyosTypography.of(context).label,
                  ),
                  Text(copy.checkpointPeriod(
                      review.periodStart, review.periodEnd)),
                ],
              ),
            ),
            const SizedBox(width: MyosSpacing.xs),
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
        const SizedBox(height: MyosSpacing.xxs),
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
    return _exerciseHistoryTable(context, copy, points);
  }

  Widget _exerciseHistoryTable(
    BuildContext context,
    CoachCopy copy,
    List<_ExerciseHistoryDisplay> points,
  ) =>
      MyosCardTable(
        columns: <String>[copy.dateColumn],
        desktopTable: _exerciseHistoryDesktopTable(context, copy, points),
        rows: <MyosCardTableRow>[
          for (final _ExerciseHistoryDisplay point in points)
            MyosCardTableRow(
              cells: <Widget?>[
                Text(copy.exerciseHistoryCompactPoint(
                  point.point.date,
                  point.weight,
                  point.point.reps,
                  weightUnit: point.weightUnit,
                  rir: point.rir,
                  e1rm: point.e1rm,
                )),
              ],
            ),
        ],
      );

  Widget _exerciseHistoryDesktopTable(
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
      MyosTableRow(
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
        const SizedBox(height: MyosSpacing.xs),
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
                      if (coachCatalogExerciseId(exercise.id) case
                          final String exerciseId)
                        TextButton.icon(
                          onPressed: () =>
                              openCoachExerciseDetail(context, exerciseId),
                          icon: const Icon(Icons.info_outline),
                          label: Text(
                              workoutCopyOf(context).viewExerciseDetails),
                        ),
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
  return MyosTableHeader(
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
        spacing: MyosSpacing.xs,
        runSpacing: MyosSpacing.xs,
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

const MyosTableColumns _sessionExerciseColumns =
    MyosTableColumns(<double>[290, 230, 95, 70, 120], 0);

List<String> _sessionExerciseLabels(BuildContext context) {
  final copy = coachCopyOf(context);
  return <String>[copy.programExerciseColumn];
}

List<MyosCardTableRow> _sessionExerciseRows(
  BuildContext context,
  List<CoachPlayerSessionExercise> exercises,
) =>
    <MyosCardTableRow>[
      for (final CoachPlayerSessionExercise exercise in exercises)
        MyosCardTableRow(
          cells: <Widget?>[
            CoachExerciseCell(
              imagePath: exercise.imagePath,
              name: exercise.name,
              exerciseId: coachCatalogExerciseId(exercise.exerciseId),
              muscleLine:
                  coachExerciseMuscleLabel(context, exercise.primaryMuscle),
              secondaryLine: coachExerciseActionDetailLine(
                context,
                exercise.primaryAction,
              ),
            ),
          ],
          subtitle: Text(coachCopyOf(context).sessionExerciseCompact(
            exercise.sets,
            exercise.reps,
            exercise.volumeKg,
          )),
        ),
    ];

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
  return MyosTableHeader(
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
    MyosTableRow(
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
      exerciseId: coachCatalogExerciseId(exercise.exerciseId),
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
      MyosTableRow(
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
    final copy = coachCopyOf(context);
    return Semantics(
      button: true,
      expanded: _expanded,
      child: MyosCardTable(
        columns: <String>[
          copy.sessionDateColumn,
          copy.programSetsColumn,
          copy.sessionVolumeColumn,
          copy.sessionFlagsColumn,
        ],
        rows: <MyosCardTableRow>[
          MyosCardTableRow(
            key: Key(
              'coach_history_recent_session_${session.sessionId}_toggle',
            ),
            cells: <Widget?>[
              Text(
                copy.sessionTitle(session.splitName, session.sessionDate),
              ),
              Text('${session.setsCount}', textDirection: TextDirection.ltr),
              Text(
                '${copy.formatVolume(session.totalVolumeKg)} '
                '${copy.volumeUnit}',
                textDirection: TextDirection.ltr,
              ),
              flags.isEmpty ? null : _wrappedSessionFlagChips(context, flags),
            ],
            onTap: _toggle,
            actions: _expandCollapseIcon(context),
          ),
        ],
      ),
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
        color: MyosTheme.of(context).textSecondary,
        size: MyosIconSizes.small,
      );

  Widget _expandedDetails(BuildContext context) {
    final bool desktop = isDesktopLayout(context);
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: MyosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Padding(
            padding: const EdgeInsetsDirectional.only(
              start: MyosSpacing.sm,
              end: MyosSpacing.sm,
            ),
            child: _expandedSummary(context),
          ),
          Padding(
            padding: EdgeInsetsDirectional.only(
              start: MyosSpacing.sm,
              end: desktop ? 0 : MyosSpacing.sm,
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
          const SizedBox(height: MyosSpacing.xs),
        ],
      );

  Widget _exerciseBreakdown(BuildContext context) => isDesktopLayout(context)
      ? CoachExerciseTableFrame(
          columns: _sessionExerciseColumns,
          decorated: false,
          scrollable: false,
          child: _sessionExerciseTableContent(context, session.exercises),
        )
      : MyosCardTable(
          columns: _sessionExerciseLabels(context),
          rows: _sessionExerciseRows(context, session.exercises),
        );
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final bool rtl = Directionality.of(context) == TextDirection.rtl;
    return Container(
      padding: const EdgeInsets.all(MyosSpacing.sm),
      decoration: BoxDecoration(
        color: c.surfaceElevated,
        borderRadius: MyosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            label,
            style: MyosTypography.of(context)
                .bodySecondary
                .copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MyosSpacing.xxs),
          Text(
            value,
            style: MyosTypography.of(context).numericSmall
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
        child: MyosCard(
          onTap: onToggle,
          padding: const EdgeInsets.all(MyosSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Semantics(
                excludeSemantics: true,
                child: MyosSectionHeader(
                  title: heading.label,
                  padding: EdgeInsets.only(
                    bottom: expanded ? MyosSpacing.xs : 0,
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
