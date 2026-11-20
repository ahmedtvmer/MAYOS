import 'package:flutter/material.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/xp_copy.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';

/// XP, ranks and the Weekly streak in the Player app (#743, #796).

XpCopy xpCopyOf(BuildContext context) =>
    XpCopy(displayCopyOf(context).isArabic ? 'ar' : 'en');

PlayerRank _rankOf(TrainingStatus status) => status.rank ?? playerRankLadder.first;

/// Fraction of the way from the current rank to the next (1 at the top rank).
double rankFraction({required int into, required int? span}) {
  if (span == null || span <= 0) return 1;
  return (into / span).clamp(0.0, 1.0);
}

class RankBadge extends StatelessWidget {
  const RankBadge({super.key, required this.rank, this.size = 14});

  final PlayerRank rank;
  final double size;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: c.selectedSurface,
        borderRadius: MayosRadii.pillRadius,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(Icons.shield_outlined, size: size, color: c.accent),
          const SizedBox(width: 6),
          Text(
            rank.name(isArabic),
            style: MayosTypography.of(context)
                .captionStrong
                .copyWith(color: c.accent, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

class _ProgressBar extends StatelessWidget {
  const _ProgressBar({required this.fraction, this.height = 6});

  final double fraction;
  final double height;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ClipRRect(
      borderRadius: BorderRadius.circular(height / 2),
      child: LinearProgressIndicator(
        value: fraction,
        minHeight: height,
        color: c.accent,
        backgroundColor: c.surfaceSunken,
      ),
    );
  }
}

/// The streak chip text: "4-wk streak", "Streak paused" or "No streak yet".
String streakLabel(XpCopy copy, {required int weeks, required bool paused}) {
  if (paused) return copy.streakPaused;
  if (weeks <= 0) return copy.noStreakYet;
  return copy.weekStreak(weeks);
}

/// Home's one-row status strip above the session card (#796).
class XpStatusStrip extends StatelessWidget {
  const XpStatusStrip({super.key, required this.status, required this.onTap});

  static const Key stripKey = ValueKey<String>('home.xpStrip');

  final TrainingStatus status;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final PlayerRank rank = _rankOf(status);
    final PlayerRank? next = status.nextRank;
    final bool rookie = status.xpTotal == 0 && status.mayosWorkouts == 0;
    final String progress = rookie
        ? copy.firstWorkoutHint
        : next == null
            ? copy.topRankReached
            : copy.progressToNext(
                status.xpIntoRank, status.xpForNextRank ?? 0, next.name(isArabic));
    return Material(
      key: stripKey,
      color: c.surface,
      shape: RoundedRectangleBorder(
        borderRadius: MayosRadii.mediumRadius,
        side: BorderSide(color: c.border),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: MayosRadii.mediumRadius,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.md, vertical: MayosSpacing.sm),
            child: Row(
              children: <Widget>[
                RankBadge(rank: rank),
                const SizedBox(width: MayosSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      if (!rookie) ...<Widget>[
                        _ProgressBar(
                          fraction: rankFraction(
                              into: status.xpIntoRank, span: status.xpForNextRank),
                        ),
                        const SizedBox(height: 5),
                      ],
                      Text(
                        progress,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: type.caption.copyWith(color: c.textSecondary),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: MayosSpacing.sm),
                _StreakChip(status: status),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StreakChip extends StatelessWidget {
  const _StreakChip({required this.status});

  final TrainingStatus status;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final XpCopy copy = xpCopyOf(context);
    final String label = status.weekPaused
        ? copy.paused
        : status.weeklyStreak > 0
            ? copy.weekStreak(status.weeklyStreak)
            : copy.noStreakYet;
    return Semantics(
      label: status.thisWeekDone ? '$label, ${copy.thisWeekDone}' : label,
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            label,
            style: MayosTypography.of(context)
                .captionStrong
                .copyWith(color: status.weekPaused ? c.textSecondary : c.textPrimary),
          ),
          if (status.thisWeekDone && !status.weekPaused) ...<Widget>[
            const SizedBox(width: 3),
            Icon(Icons.check, size: 16, color: c.success,
                key: const ValueKey<String>('xp.thisWeekTick')),
          ],
        ],
      ),
    );
  }
}

/// The Rank sheet: rank, progress, the ladder and how XP is earned.
Future<void> showRankSheet(BuildContext context, TrainingStatus status) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (BuildContext sheetContext) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
              maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.9),
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(
                MayosSpacing.lg, 0, MayosSpacing.lg, MayosSpacing.lg),
            child: RankSheetBody(status: status),
          ),
        ),
      ),
    );

class RankSheetBody extends StatelessWidget {
  const RankSheetBody({super.key, required this.status});

  static const Key bodyKey = ValueKey<String>('xp.rankSheet');

  final TrainingStatus status;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final PlayerRank rank = _rankOf(status);
    final PlayerRank? next = status.nextRank;
    final int remaining = (status.xpForNextRank ?? 0) - status.xpIntoRank;
    return Column(
      key: bodyKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          children: <Widget>[
            CircleAvatar(
              radius: 26,
              backgroundColor: c.selectedSurface,
              child: Icon(Icons.shield_outlined, color: c.accent, size: 26),
            ),
            const SizedBox(width: MayosSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(copy.yourRank,
                      style: type.captionStrong.copyWith(color: c.textSecondary)),
                  Text(rank.name(isArabic),
                      style: type.pageHeading.copyWith(color: c.textPrimary)),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: <Widget>[
                Text(copy.xp(status.xpTotal),
                    style: type.numericSmall.copyWith(color: c.textPrimary)),
                Text(
                  streakLabel(copy, weeks: status.weeklyStreak, paused: status.weekPaused),
                  style: type.caption.copyWith(color: c.textSecondary),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.md),
        _ProgressBar(
          fraction: rankFraction(into: status.xpIntoRank, span: status.xpForNextRank),
          height: 8,
        ),
        const SizedBox(height: 6),
        Text(
          next == null ? copy.topRankReached : copy.moreToNext(remaining, next.name(isArabic)),
          style: type.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.lg),
        Text(copy.allRanks, style: type.captionStrong.copyWith(color: c.textSecondary)),
        const SizedBox(height: MayosSpacing.xs),
        for (final PlayerRank step in playerRankLadder)
          _LadderRow(
            rank: step,
            current: step.id == rank.id,
            reached: step.threshold <= rank.threshold,
          ),
        const SizedBox(height: MayosSpacing.lg),
        Text(copy.howYouEarn, style: type.captionStrong.copyWith(color: c.textSecondary)),
        const SizedBox(height: MayosSpacing.xs),
        for (final ({String label, String value}) row in copy.earningTable)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: Text(row.label,
                      style: type.body.copyWith(color: c.textPrimary)),
                ),
                Text(row.value,
                    style: type.body.copyWith(
                        color: c.textPrimary, fontWeight: FontWeight.w600)),
              ],
            ),
          ),
        const SizedBox(height: MayosSpacing.sm),
        Text(copy.earningFootnote,
            style: type.caption.copyWith(color: c.textSecondary)),
      ],
    );
  }
}

class _LadderRow extends StatelessWidget {
  const _LadderRow({required this.rank, required this.current, required this.reached});

  final PlayerRank rank;
  final bool current;
  final bool reached;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final Color color = current ? c.accent : c.textPrimary;
    return Container(
      key: ValueKey<String>('xp.ladder.${rank.id}'),
      padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.sm, vertical: 8),
      decoration: BoxDecoration(
        color: current ? c.selectedSurface : null,
        borderRadius: MayosRadii.mediumRadius,
      ),
      child: Row(
        children: <Widget>[
          SizedBox(
            width: 24,
            child: current
                ? Icon(Icons.circle, size: 10, color: c.accent)
                : reached
                    ? Icon(Icons.check, size: 16, color: c.success)
                    : null,
          ),
          Expanded(
            child: Text(
              current ? '${rank.name(isArabic)} · ${copy.you}' : rank.name(isArabic),
              style: type.body.copyWith(
                color: color,
                fontWeight: current ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ),
          Text(copy.xp(rank.threshold),
              style: type.caption.copyWith(color: current ? c.accent : c.textSecondary)),
        ],
      ),
    );
  }
}

/// Profile's rank card (#796): rank, progress and three stats.
class RankProfileCard extends StatelessWidget {
  const RankProfileCard({super.key, required this.status, required this.onTap});

  static const Key cardKey = ValueKey<String>('profile.rankCard');

  final TrainingStatus status;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final PlayerRank rank = _rankOf(status);
    final PlayerRank? next = status.nextRank;
    final int remaining = (status.xpForNextRank ?? 0) - status.xpIntoRank;
    Widget stat(String value, String label) => Expanded(
          child: Container(
            padding: const EdgeInsets.all(MayosSpacing.sm),
            decoration: BoxDecoration(
              color: c.surfaceSunken,
              borderRadius: MayosRadii.mediumRadius,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(value, style: type.numericSmall.copyWith(color: c.textPrimary)),
                Text(label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: type.caption.copyWith(color: c.textSecondary)),
              ],
            ),
          ),
        );
    return Material(
      key: cardKey,
      color: c.surface,
      shape: RoundedRectangleBorder(
        borderRadius: MayosRadii.largeRadius,
        side: BorderSide(color: c.border),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: MayosRadii.largeRadius,
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Row(
                children: <Widget>[
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: c.selectedSurface,
                    child: Icon(Icons.shield_outlined, color: c.accent, size: 26),
                  ),
                  const SizedBox(width: MayosSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(copy.rank,
                            style: type.captionStrong.copyWith(color: c.textSecondary)),
                        Text(rank.name(isArabic),
                            style: type.pageHeading.copyWith(color: c.textPrimary)),
                      ],
                    ),
                  ),
                  Icon(Icons.chevron_right, color: c.textSecondary),
                ],
              ),
              const SizedBox(height: MayosSpacing.md),
              _ProgressBar(
                fraction: rankFraction(into: status.xpIntoRank, span: status.xpForNextRank),
                height: 8,
              ),
              const SizedBox(height: 6),
              Text(
                next == null
                    ? copy.topRankReached
                    : '${copy.xp(status.xpTotal)} · ${copy.toNext(remaining, next.name(isArabic))}',
                style: type.bodySecondary.copyWith(color: c.textSecondary),
              ),
              const SizedBox(height: MayosSpacing.md),
              Row(
                children: <Widget>[
                  stat(copy.weeklyStreakWeeks(status.weeklyStreak), copy.weeklyStreak),
                  const SizedBox(width: MayosSpacing.xs),
                  stat(copy.weeklyStreakWeeks(status.longestStreak), copy.longestStreak),
                  const SizedBox(width: MayosSpacing.xs),
                  stat('${status.mayosWorkouts}', copy.workouts),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The saved summary's XP card, from the commit response (#796).
class WorkoutXpCard extends StatelessWidget {
  const WorkoutXpCard({super.key, required this.xp, this.effortAboveRange = false});

  static const Key cardKey = ValueKey<String>('logger.xpCard');

  final WorkoutXp xp;
  final bool effortAboveRange;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final PlayerRank? next = xp.nextRank;
    final int remaining = (xp.xpForNextRank ?? 0) - xp.xpIntoRank;
    final bool showEffortNote = xp.counted &&
        xp.breakdown.any((({String kind, int xp}) line) =>
            line.kind == 'effort_in_range' && line.xp == 0) &&
        xp.breakdown.any((({String kind, int xp}) line) =>
            line.kind == 'planned_workout' && line.xp > 0);
    return Container(
      key: cardKey,
      padding: const EdgeInsets.all(MayosSpacing.md),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: MayosRadii.largeRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: <Widget>[
              Text(copy.awarded(xp.awarded),
                  style: type.numeric.copyWith(color: c.accent)),
              const SizedBox(width: MayosSpacing.sm),
              Expanded(
                child: Text(copy.earnedForThisWorkout,
                    style: type.bodySecondary.copyWith(color: c.textSecondary)),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.sm),
          if (!xp.counted)
            Text(copy.notCountedToday,
                style: type.bodySecondary.copyWith(color: c.textSecondary))
          else ...<Widget>[
            for (final ({String kind, int xp}) line in xp.breakdown)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  children: <Widget>[
                    Expanded(
                      child: Text(copy.ruleLabel(line.kind),
                          style: type.body.copyWith(color: c.textPrimary)),
                    ),
                    Text(
                      '+${line.xp}',
                      textDirection: TextDirection.ltr,
                      style: type.body.copyWith(
                        fontWeight: FontWeight.w600,
                        color: line.xp == 0 ? c.textSecondary : c.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(copy.streakCountsAtWeekEnd,
                  style: type.caption.copyWith(color: c.textSecondary)),
            ),
          ],
          Divider(height: MayosSpacing.lg, color: c.border),
          Row(
            children: <Widget>[
              Expanded(
                child: Text(copy.rankLine(xp.rank.name(isArabic), xp.xpTotal),
                    style: type.bodySecondary.copyWith(color: c.textPrimary)),
              ),
              if (next != null)
                Text(copy.toNext(remaining, next.name(isArabic)),
                    style: type.caption.copyWith(color: c.textSecondary)),
            ],
          ),
          const SizedBox(height: 6),
          _ProgressBar(
            fraction: rankFraction(into: xp.xpIntoRank, span: xp.xpForNextRank),
            height: 8,
          ),
          if (showEffortNote || effortAboveRange) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(copy.effortAboveRangeNote,
                style: type.caption.copyWith(color: c.textSecondary)),
          ],
        ],
      ),
    );
  }
}

/// The full-screen rank-up celebration (#796). The badge rises in once; with
/// reduced motion it simply appears.
class RankUpScreen extends StatefulWidget {
  const RankUpScreen({
    super.key,
    required this.rank,
    required this.status,
    required this.onSeeAllRanks,
  });

  static const Key screenKey = ValueKey<String>('xp.rankUp');

  final PlayerRank rank;
  final TrainingStatus? status;
  final VoidCallback onSeeAllRanks;

  @override
  State<RankUpScreen> createState() => _RankUpScreenState();
}

class _RankUpScreenState extends State<RankUpScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _rise = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 600),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.maybeDisableAnimationsOf(context) ?? false) {
      _rise.value = 1;
    } else if (!_rise.isAnimating && _rise.value == 0) {
      _rise.forward();
    }
  }

  @override
  void dispose() {
    _rise.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final TrainingStatus? status = widget.status;
    final PlayerRank? next = status?.nextRank;
    final Animation<double> curve =
        CurvedAnimation(parent: _rise, curve: Curves.easeOutCubic);
    return Scaffold(
      key: RankUpScreen.screenKey,
      backgroundColor: c.canvas,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.xl, vertical: MayosSpacing.lg),
          child: Column(
            children: <Widget>[
              const Spacer(),
              AnimatedBuilder(
                animation: curve,
                builder: (BuildContext context, Widget? child) => Opacity(
                  opacity: curve.value,
                  child: Transform.translate(
                    offset: Offset(0, 24 * (1 - curve.value)),
                    child: child,
                  ),
                ),
                child: Container(
                  width: 168,
                  height: 168,
                  decoration: BoxDecoration(
                    color: c.selectedSurface,
                    shape: BoxShape.circle,
                  ),
                  child: Center(
                    child: Icon(Icons.shield, size: 72, color: c.accent),
                  ),
                ),
              ),
              const SizedBox(height: MayosSpacing.lg),
              Text(copy.newRank,
                  style: type.captionStrong.copyWith(color: c.accent)),
              const SizedBox(height: MayosSpacing.xs),
              Text(widget.rank.name(isArabic),
                  textAlign: TextAlign.center,
                  style: type.display.copyWith(color: c.textPrimary, fontSize: 40)),
              const SizedBox(height: MayosSpacing.sm),
              Text(copy.rankUpLine,
                  textAlign: TextAlign.center,
                  style: type.bodySecondary.copyWith(color: c.textSecondary)),
              if (status != null) ...<Widget>[
                const SizedBox(height: MayosSpacing.lg),
                SizedBox(
                  width: 300,
                  child: _ProgressBar(
                    fraction: rankFraction(
                        into: status.xpIntoRank, span: status.xpForNextRank),
                    height: 8,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  copy.rankUpProgress(
                      status.xpTotal, next?.name(isArabic), next?.threshold),
                  style: type.caption.copyWith(color: c.textSecondary),
                ),
              ],
              const Spacer(flex: 2),
              MayosButton(
                key: const ValueKey<String>('xp.rankUp.keepGoing'),
                label: copy.keepGoing,
                onPressed: () => Navigator.of(context).pop(),
              ),
              const SizedBox(height: MayosSpacing.xs),
              TextButton(
                key: const ValueKey<String>('xp.rankUp.allRanks'),
                onPressed: widget.onSeeAllRanks,
                child: Text(copy.seeAllRanks),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Opens the rank-up celebration over the current screen.
Future<void> showRankUp(
  BuildContext context, {
  required PlayerRank rank,
  required TrainingStatus? status,
}) =>
    Navigator.of(context, rootNavigator: true).push<void>(
      MaterialPageRoute<void>(
        fullscreenDialog: true,
        builder: (BuildContext routeContext) => RankUpScreen(
          rank: rank,
          status: status,
          onSeeAllRanks: () {
            Navigator.of(routeContext).pop();
            if (status != null) showRankSheet(context, status);
          },
        ),
      ),
    );

/// Read-only rank and streak chips for the coach roster (#796).
class CoachRankChips extends StatelessWidget {
  const CoachRankChips({super.key, required this.entry});

  final CoachRosterEntry entry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final XpCopy copy = xpCopyOf(context);
    final bool isArabic = displayCopyOf(context).isArabic;
    final PlayerRank? rank = entry.rank;
    final int? streak = entry.weeklyStreak;
    if (rank == null && streak == null) return const SizedBox.shrink();
    Widget chip(String text, {required bool accent}) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: accent ? c.selectedSurface : c.surfaceSunken,
            borderRadius: MayosRadii.pillRadius,
          ),
          child: Text(
            text,
            style: type.caption.copyWith(
              color: accent ? c.accent : c.textSecondary,
              fontWeight: FontWeight.w600,
            ),
          ),
        );
    return Wrap(
      spacing: 6,
      runSpacing: 4,
      children: <Widget>[
        if (rank != null) chip(rank.name(isArabic), accent: true),
        if (streak != null)
          chip(streakLabel(copy, weeks: streak, paused: entry.weekPaused == true),
              accent: false),
      ],
    );
  }
}
