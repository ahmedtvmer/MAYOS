import 'package:flutter/material.dart';

import '../../../core/active_workout.dart';
import '../../../core/baselines.dart';
import '../../../core/config.dart';
import '../../../core/effort.dart';
import '../../../core/personal_records.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import 'logger_keypad.dart';
import 'personal_record_badge.dart';
import 'rest_timer_widgets.dart';

// Presentation only (#158, plan §13): one compact card per exercise, a
// leaner SET · KG · REPS · RIR · ✓ table with no PREVIOUS column, the
// "Last:" line that replaces it, and the row states (pending / Current set /
// ticked). Every value, decision and mutation comes from the Active workout,
// its controller and the logger screen above, so the later slices (#159
// header, #160 bottom bar, #161 pictures, #162 card menu) extend this file
// without touching the logging rules.

/// The two narrow tap columns of the leaner table — the SET number and the
/// tick — hold a **fixed 48dp** each, so both stay full-size tap targets
/// whatever the screen is (#158 review): at the 360dp minimum the row has
/// about 286dp, and a flex share would have squeezed them under 48.
const double kLoggerFixedColumnWidth = kMayosMinTapTarget;

/// The value columns KG · REPS · RIR share whatever width the two fixed
/// columns leave, in the plan's priority order (weight, reps, effort).
const List<int> kLoggerValueColumnFlex = <int>[4, 3, 3];

/// The spec's tick: a 40dp square inside the row's 48dp tap area (#107).
const double kLoggerTickSize = 40;

/// The one mapping from a field to what its cell shows (#123 item 12): the
/// typed [value] when there is one, else the faded [hint].
///
/// The hint is the previous set first (#107/#123 item 1), falling back to
/// the prescription target — projected weight, target reps, target RIR — when
/// there is no previous value to take (#108: prescription `last_perf` stays
/// for the progression projection alone, so it never appears here).
///
/// The PREVIOUS column is gone (#158), so these hints are now the only place
/// last time's values appear while the player is entering a set.
({String? value, String? hint}) cellTexts({
  required ActiveWorkoutSet set,
  required BaselineSet? previous,
  required PrescriptionHint? prescriptionHint,
  required LoggerField field,
}) {
  String? fromPrevious;
  String? fromPrescription;
  switch (field) {
    case LoggerField.kg:
      fromPrevious =
          previous == null ? null : formatCellWeight(previous.weightKg);
      final double? projected = prescriptionHint?.weightKg;
      fromPrescription = projected == null || projected <= 0
          ? null
          : formatCellWeight(projected);
      return (
        value: set.weightKg > 0 ? formatCellWeight(set.weightKg) : null,
        hint: fromPrevious ?? fromPrescription,
      );
    case LoggerField.reps:
      fromPrevious = previous == null ? null : '${previous.reps}';
      final int? targetReps = prescriptionHint?.reps;
      fromPrescription =
          targetReps == null || targetReps <= 0 ? null : '$targetReps';
      return (
        value: set.reps > 0 ? '${set.reps}' : null,
        hint: fromPrevious ?? fromPrescription,
      );
    case LoggerField.rir:
      // A recorded RIR reads as itself (5 → 5+); the prescription fallback is
      // a *target*, so it reads as the equivalent minimum RIR (≥ n) (#111).
      final double? previousRir = previous?.rir;
      fromPrevious = previousRir == null ? null : formatRir(previousRir);
      final double? targetRir = prescriptionHint?.rir;
      fromPrescription = targetRir == null ? null : formatMinRir(targetRir);
      return (
        value: set.rir == null ? null : formatRir(set.rir!),
        hint: fromPrevious ?? fromPrescription,
      );
  }
}

/// The `Last:` line under the prescription, replacing the PREVIOUS column
/// (#158, plan §7). Not editable, not per set: one line for the exercise,
/// formatted by [lastSessionLabel] next to the model.
class PreviousPerformanceSummary extends StatelessWidget {
  const PreviousPerformanceSummary({super.key, required this.sets});

  /// The baseline's last-session working sets, in logged order.
  final List<BaselineSet> sets;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Text(
      lastSessionLabel(sets),
      style: MayosTypography.caption.copyWith(color: c.textSecondary),
    );
  }
}

/// The table's column labels, over the same shares as every row.
class LoggerTableHeader extends StatelessWidget {
  const LoggerTableHeader({super.key});

  static const List<String> labels = <String>[
    'SET',
    'KG',
    'REPS',
    'RIR',
    '✓',
  ];

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Row(
        children: <Widget>[
          SizedBox(
            width: kLoggerFixedColumnWidth,
            child: Text(
              labels[0],
              textAlign: TextAlign.center,
              style: MayosTypography.captionStrong.copyWith(color: c.textMuted),
            ),
          ),
          for (int i = 1; i < labels.length - 1; i++)
            Expanded(
              flex: kLoggerValueColumnFlex[i - 1],
              child: Text(
                labels[i],
                textAlign: TextAlign.center,
                style:
                    MayosTypography.captionStrong.copyWith(color: c.textMuted),
              ),
            ),
          SizedBox(
            width: kLoggerFixedColumnWidth,
            child: Text(
              labels[labels.length - 1],
              textAlign: TextAlign.center,
              style: MayosTypography.captionStrong.copyWith(color: c.textMuted),
            ),
          ),
        ],
      ),
    );
  }
}

/// The exercise's catalog picture (#161), a fixed rounded thumbnail.
///
/// The box is a constant [size] square whatever the picture does: while it
/// loads it shows a placeholder on the sunken surface, a catalog row without
/// an image path shows the missing-picture fallback, and a picture the API
/// answers 404 (or fails to decode) shows the failed-picture fallback — the
/// three states occupy identical space, so the card never shifts.
///
/// The bytes come from the public `GET /media/<image_path>` route built from
/// the configured API base ([mediaUrlFor]); no token is sent and no picture
/// is bundled. Flutter's own image cache holds the decoded result, so a
/// rebuild paints from memory instead of refetching, and `gaplessPlayback`
/// keeps the last frame across rebuilds.
///
/// The build-time media flag gates it (#53): when [mayosExerciseMediaEnabled]
/// is off (`--dart-define=MAYOS_EXERCISE_MEDIA=false`) the box shows the
/// missing-picture fallback and no request is ever made.
class ExerciseCatalogThumbnail extends StatelessWidget {
  const ExerciseCatalogThumbnail({
    super.key,
    required this.imagePath,
    this.enabled = mayosExerciseMediaEnabled,
  });

  /// Fixed 48dp: a full-size tap-adjacent block that still leaves the title,
  /// the Unplanned pill and the rest chip their room at 360dp (#161).
  static const double size = kMayosMinTapTarget;

  /// The catalog's relative image path (`images/0001-2gPfomN.jpg`), null
  /// when the exercise has no picture.
  final String? imagePath;

  /// The media flag this card renders under (#53): with [mayosExerciseMediaEnabled]
  /// as its default the widget follows the build-time kill switch, while a
  /// test can pin either state.
  final bool enabled;

  /// The served `/media` URL for the catalog path, or null when there is
  /// nothing to load (no path, media switched off, or a payload pointing at
  /// another host — [mediaUrlFor] refuses those).
  String? get _url => enabled ? mediaUrlFor(imagePath) : null;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String? url = _url;
    return ClipRRect(
      borderRadius: MayosRadii.mediumRadius,
      child: SizedBox(
        width: size,
        height: size,
        child: ColoredBox(
          color: c.surfaceSunken,
          child: url == null
              ? _fallback(c, failed: false)
              : Image.network(
                  url,
                  width: size,
                  height: size,
                  fit: BoxFit.cover,
                  // No flash of an empty box while the cached frame resolves.
                  gaplessPlayback: true,
                  // Decode at display size: the picture never needs more
                  // pixels than the thumbnail shows.
                  cacheWidth:
                      (size * MediaQuery.devicePixelRatioOf(context)).round(),
                  loadingBuilder: (_, Widget child, ImageChunkEvent? progress) =>
                      progress == null ? child : _placeholder(c),
                  errorBuilder: (_, __, ___) => _fallback(c, failed: true),
                ),
        ),
      ),
    );
  }

  /// The loading state (#161): a static glyph, never a spinner, so a picture
  /// that takes a moment cannot keep the screen animating.
  Widget _placeholder(MayosThemeExtension c) => ColoredBox(
        color: c.surfaceSunken,
        child: Center(
          child: Icon(
            Icons.image_outlined,
            size: MayosIconSizes.medium,
            color: c.textDisabled,
          ),
        ),
      );

  /// The missing- and failed-picture states: an exercise glyph on a surface
  /// tint, in the same fixed box (#161). Both look alike on purpose — only
  /// the semantic label tells a screen reader which one it is.
  Widget _fallback(MayosThemeExtension c, {required bool failed}) =>
      ColoredBox(
        color: c.secondarySurface,
        child: Center(
          child: Icon(
            Icons.fitness_center,
            size: MayosIconSizes.medium,
            color: c.textMuted,
            semanticLabel: failed ? 'Picture unavailable' : 'No picture',
          ),
        ),
      );
}

/// One compact exercise card (#158, plan §2): the name in primary text
/// colour, the catalog picture (#161), the prescription line, the `Last:`
/// line when there is history, the leaner table, and a full-width "+ Add
/// set". The rest chip (#125) trails the title so a later slice can park a
/// menu beside it; nothing here decides anything — rows and callbacks arrive
/// from the logger.
class ExerciseLoggingCard extends StatelessWidget {
  const ExerciseLoggingCard({
    super.key,
    required this.exercise,
    required this.restSeconds,
    required this.lastSession,
    required this.rows,
    required this.onPickRest,
    required this.onAddSet,
    this.unplanned = false,
    this.restChipKey,
    this.addSetKey,
  });

  final ActiveWorkoutExercise exercise;

  /// The rest length this card is using right now (#125), for the chip and
  /// the prescription line alike.
  final int restSeconds;

  /// The frozen baseline's last session; empty hides the `Last:` line.
  final List<BaselineSet> lastSession;

  /// The exercise's rows, built by the logger so focus, records and the
  /// Current set stay its own decisions.
  final List<Widget> rows;

  final VoidCallback onPickRest;
  final VoidCallback onAddSet;
  final bool unplanned;
  final Key? restChipKey;
  final Key? addSetKey;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: MayosCard(
        padding: const EdgeInsets.fromLTRB(MayosSpacing.md, MayosSpacing.sm,
            MayosSpacing.md, MayosSpacing.xxs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  // Primary text colour: the accent blue is reserved for
                  // what the player must act on (#157).
                  child: Text(
                    exercise.exerciseName,
                    style: MayosTypography.exerciseTitle
                        .copyWith(color: c.textPrimary),
                  ),
                ),
                if (unplanned) const _UnplannedTag(),
                Padding(
                  padding: const EdgeInsets.only(left: MayosSpacing.xs),
                  child: RestLengthChip(
                    key: restChipKey,
                    seconds: restSeconds,
                    onPressed: onPickRest,
                  ),
                ),
              ],
            ),
            // The picture sits beside the caption lines rather than the title
            // row (#161): the pill and the chip already fill that row at 2.0
            // text scale, and the caption text wraps into the room the fixed
            // thumbnail leaves.
            Padding(
              padding: const EdgeInsets.only(top: MayosSpacing.xxs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  // A fixed box, so a card with, without, or waiting for a
                  // picture is laid out the same way and never shifts.
                  ExerciseCatalogThumbnail(imagePath: exercise.imagePath),
                  const SizedBox(width: MayosSpacing.xs),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        Text(
                          exercisePrescriptionLine(exercise,
                              restSeconds: restSeconds),
                          style: MayosTypography.caption
                              .copyWith(color: c.textMuted),
                        ),
                        if (lastSession.isNotEmpty)
                          Padding(
                            padding:
                                const EdgeInsets.only(top: MayosSpacing.xxs),
                            child:
                                PreviousPerformanceSummary(sets: lastSession),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const LoggerTableHeader(),
            ...rows,
            MayosButton(
              key: addSetKey,
              label: '+ Add set',
              variant: MayosButtonVariant.secondary,
              onPressed: onAddSet,
            ),
          ],
        ),
      ),
    );
  }
}

/// The Unplanned pill, only where it applies (#123).
class _UnplannedTag extends StatelessWidget {
  const _UnplannedTag();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.pillRadius,
      ),
      child: Text('Unplanned', style: MayosTypography.caption),
    );
  }
}

/// One set row of the leaner table (#158, plan §5/§6): the set number
/// (tap to toggle N ↔ W), KG, REPS, the compact RIR selector and the tick —
/// in the three states: pending (neutral, outlined check), **Current set**
/// (blue tint) and ticked (filled check, subtle tint, still editable).
/// Personal-record badges keep sitting under their row (#124).
class SetLoggingRow extends StatelessWidget {
  const SetLoggingRow({
    super.key,
    required this.exerciseIndex,
    required this.setIndex,
    required this.set,
    required this.previous,
    required this.prescriptionHint,
    required this.badges,
    required this.focus,
    required this.isCurrent,
    required this.onSelectCell,
    required this.onToggleWarmup,
    required this.onToggleTick,
    this.onDismissed,
  });

  final int exerciseIndex;
  final int setIndex;
  final ActiveWorkoutSet set;

  /// This row's frozen previous working set, for hints and tick-to-fill.
  final BaselineSet? previous;
  final PrescriptionHint? prescriptionHint;
  final SetRecordBadges badges;
  final LoggerCellFocus? focus;

  /// The derived Current set points here (#158): blue tint, no other change.
  final bool isCurrent;

  final ValueChanged<LoggerField> onSelectCell;
  final VoidCallback onToggleWarmup;
  final VoidCallback onToggleTick;
  final VoidCallback? onDismissed;

  ({String? value, String? hint}) _texts(LoggerField field) => cellTexts(
        set: set,
        previous: previous,
        prescriptionHint: prescriptionHint,
        field: field,
      );

  bool _focused(LoggerField field) =>
      focus == LoggerCellFocus(exerciseIndex, setIndex, field);

  /// The cell's surface: focused wins, then the row's own tint shows through
  /// (a ticked or Current row), else the sunken input well.
  Color _surface(MayosThemeExtension c, LoggerField field) {
    if (_focused(field)) {
      return c.selectedSurface;
    }
    if (set.ticked || isCurrent) {
      return Colors.transparent;
    }
    return c.surfaceSunken;
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool muted = set.isWarmup;

    Widget row = Container(
      key: ValueKey<String>('logger.row.$exerciseIndex.$setIndex'),
      margin: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: isCurrent
            ? c.accentSubtle
            : set.ticked
                ? c.successTint
                : null,
        borderRadius: MayosRadii.smallRadius,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              SizedBox(
                width: kLoggerFixedColumnWidth,
                child: InkWell(
                  key: ValueKey<String>(
                      'logger.setlabel.$exerciseIndex.$setIndex'),
                  borderRadius: MayosRadii.smallRadius,
                  onTap: onToggleWarmup,
                  child: SizedBox(
                    height: kMayosMinTapTarget,
                    child: Center(
                      child: Text(
                        set.isWarmup ? 'W' : '${setIndex + 1}',
                        style: MayosTypography.numericSmall.copyWith(
                          color: muted ? c.textMuted : c.textPrimary,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              _cell(context, LoggerField.kg, kLoggerValueColumnFlex[0]),
              _cell(context, LoggerField.reps, kLoggerValueColumnFlex[1]),
              Expanded(
                flex: kLoggerValueColumnFlex[2],
                child: RirSelector(
                  cellKey: ValueKey<String>(
                      'logger.cell.$exerciseIndex.$setIndex.rir'),
                  value: _texts(LoggerField.rir).value,
                  hint: _texts(LoggerField.rir).hint,
                  muted: muted,
                  surface: _surface(c, LoggerField.rir),
                  focused: _focused(LoggerField.rir),
                  onTap: () => onSelectCell(LoggerField.rir),
                ),
              ),
              SizedBox(
                // Fixed 48dp for the tick too (#158 review): the tap target
                // never shrinks with a flex share at any screen width.
                width: kLoggerFixedColumnWidth,
                height: kMayosMinTapTarget,
                child: InkWell(
                  key: ValueKey<String>(
                      'logger.tick.$exerciseIndex.$setIndex'),
                  borderRadius: MayosRadii.smallRadius,
                  onTap: onToggleTick,
                  child: Center(
                    child: SizedBox(
                      width: kLoggerTickSize,
                      height: kLoggerTickSize,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: set.ticked ? c.accent : null,
                          border: set.ticked
                              ? null
                              : Border.all(color: c.borderStrong),
                          borderRadius: MayosRadii.smallRadius,
                        ),
                        child: Icon(
                          Icons.check,
                          size: MayosIconSizes.medium,
                          color: set.ticked ? c.onAccent : c.textMuted,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
          // The PR badges sit under the row they belong to (#107/#124).
          if (!badges.isEmpty) _badges(context),
        ],
      ),
    );

    if (onDismissed != null) {
      // Keyed by the row's own stable id, so removing an earlier row never
      // re-identifies the one being swiped (#123 item 3).
      row = Dismissible(
        key: ValueKey<String>(set.id),
        direction: DismissDirection.endToStart,
        onDismissed: (_) => onDismissed!(),
        background: Container(
          color: c.danger,
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: MayosSpacing.md),
          child: Icon(Icons.delete, color: c.onDanger),
        ),
        child: row,
      );
    }
    return row;
  }

  /// KG and REPS: the typed value or the faded hint, one tap to edit.
  Widget _cell(BuildContext context, LoggerField field, int flex) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ({String? value, String? hint}) texts = _texts(field);
    final Color color =
        texts.value == null || set.isWarmup ? c.textDisabled : c.textPrimary;
    return Expanded(
      flex: flex,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xxs),
        child: Material(
          color: _surface(c, field),
          shape: RoundedRectangleBorder(
            borderRadius: MayosRadii.smallRadius,
            side: BorderSide(
                color: _focused(field) ? c.selectedBorder : Colors.transparent),
          ),
          child: InkWell(
            key: ValueKey<String>(
                'logger.cell.$exerciseIndex.$setIndex.${field.name}'),
            borderRadius: MayosRadii.smallRadius,
            onTap: () => onSelectCell(field),
            child: SizedBox(
              height: kMayosMinTapTarget,
              child: Center(
                child: Text(
                  texts.value ?? texts.hint ?? '–',
                  style: MayosTypography.numericSmall.copyWith(color: color),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// The badges under one set row: the records it still holds solidly first,
  /// then the ones a later set took over — struck through and muted (#107
  /// resolution, #124).
  Widget _badges(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: MayosSpacing.xxs),
        child: Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xxs,
          alignment: WrapAlignment.center,
          children: <Widget>[
            for (final PrRecordKind kind in badges.current)
              PersonalRecordBadge(
                key: ValueKey<String>(
                    'logger.pr.$exerciseIndex.$setIndex.${kind.name}'),
                kind: kind,
              ),
            for (final PrRecordKind kind in badges.beaten)
              PersonalRecordBadge(
                key: ValueKey<String>(
                    'logger.pr.$exerciseIndex.$setIndex.${kind.name}'),
                kind: kind,
                beaten: true,
              ),
          ],
        ),
      );
}

/// The row's RIR cell as a compact selector (#158): the recorded effort
/// (0–4, 5+) or the faded hint, with a chevron saying it opens. Tapping it
/// opens the keypad's existing one-tap chips — 0, 1, 2, 3, 4, 5+ and
/// Unrated (#107/#111) — so the custom keypad and its Next order are
/// untouched, and effort entry stays optional and chip-only.
class RirSelector extends StatelessWidget {
  const RirSelector({
    super.key,
    required this.cellKey,
    required this.value,
    required this.hint,
    required this.muted,
    required this.surface,
    required this.focused,
    required this.onTap,
  });

  /// The cell's stable identity, the same `logger.cell.*` key the kg and
  /// reps cells carry.
  final Key cellKey;

  /// The typed RIR, already formatted (`2`, `5+`), or null when unrated.
  final String? value;

  /// The faded previous/prescription hint shown while there is no value.
  final String? hint;
  final bool muted;
  final Color surface;
  final bool focused;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color color = value == null || muted ? c.textDisabled : c.textPrimary;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xxs),
      child: Material(
        color: surface,
        shape: RoundedRectangleBorder(
          borderRadius: MayosRadii.smallRadius,
          side: BorderSide(color: focused ? c.selectedBorder : Colors.transparent),
        ),
        child: InkWell(
          key: cellKey,
          borderRadius: MayosRadii.smallRadius,
          onTap: onTap,
          child: SizedBox(
            height: kMayosMinTapTarget,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: <Widget>[
                Flexible(
                  child: Text(
                    value ?? hint ?? '–',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style:
                        MayosTypography.numericSmall.copyWith(color: color),
                  ),
                ),
                Icon(
                  Icons.expand_more,
                  size: MayosIconSizes.small,
                  color: c.textMuted,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
