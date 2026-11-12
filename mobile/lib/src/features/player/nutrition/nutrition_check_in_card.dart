import 'package:flutter/material.dart';

import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import 'nutrition_tile.dart';

class NutritionCheckInCard extends StatelessWidget {
  const NutritionCheckInCard(
      {required this.day,
      required this.plan,
      required this.copy,
      required this.todayWaterGlasses,
      required this.onWaterChanged,
      required this.onVerdict,
      required this.onAnswerYesterday,
      this.saving = false,
      this.waterSaving = false,
      super.key});
  final FoodLogDay day;
  final NutritionPlanState plan;
  final NutritionCopy copy;
  final int todayWaterGlasses;
  final ValueChanged<bool> onWaterChanged;
  final ValueChanged<String> onVerdict;
  final ValueChanged<String> onAnswerYesterday;
  final bool saving;
  final bool waterSaving;

  bool get _today => day.date == day.today;
  DateTime get _yesterday =>
      DateTime(day.today.year, day.today.month, day.today.day - 1);
  bool get _answerable => _today || day.date == _yesterday;
  String _dateKey(DateTime date) => date.toIso8601String().substring(0, 10);

  String? _verdict(DateTime date) {
    for (final Map<String, dynamic> entry in plan.adherenceDays) {
      if (entry['date'] == _dateKey(date)) return entry['value'] as String?;
    }
    if (date == day.today && plan.adherenceDays.isEmpty) {
      return plan.todayAdherence;
    }
    return date == day.date ? day.adherence : null;
  }

  @override
  Widget build(BuildContext context) => NutritionCard(
        key: const Key('nutrition_check_in'),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text(copy.checkIn,
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: MayosSpacing.sm),
              _waterRow(context),
              const Divider(height: MayosSpacing.xl),
              Text(
                  _today
                      ? copy.howTodayWent
                      : day.date == _yesterday
                          ? copy.howYesterdayWent
                          : copy.howDayWent,
                  style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: MayosSpacing.sm),
              _segments(context),
              const Divider(height: MayosSpacing.xl),
              _history(context),
            ]),
      );

  Widget _waterRow(BuildContext context) {
    final int? glasses = _today ? todayWaterGlasses : day.waterGlasses;
    final int? targetMl = (day.targets?['water_ml'] as num?)?.toInt();
    return Row(key: const Key('nutrition_water_row'), children: <Widget>[
      Icon(Icons.water_drop_outlined,
          color: Theme.of(context).colorScheme.primary),
      const SizedBox(width: MayosSpacing.xs),
      Expanded(
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
            Text(copy.coachWater,
                style: Theme.of(context).textTheme.titleSmall),
            Text(
                glasses == null
                    ? copy.waterUnavailable
                    : targetMl == null
                        ? copy.waterAmount(glasses)
                        : copy.waterProgress(glasses, targetMl),
                key: const Key('water_progress'),
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: MayosTheme.of(context).textMuted)),
          ])),
      if (_today) ...<Widget>[
        IconButton(
            key: const Key('remove_water_glass'),
            tooltip: copy.removeGlass,
            constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
            onPressed: saving || waterSaving || todayWaterGlasses <= 0
                ? null
                : () => onWaterChanged(true),
            icon: const Icon(Icons.remove)),
        IconButton(
            key: const Key('add_water_glass'),
            tooltip: copy.addWaterGlass,
            constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
            onPressed: saving || waterSaving || todayWaterGlasses >= 30
                ? null
                : () => onWaterChanged(false),
            icon: const Icon(Icons.add)),
      ],
    ]);
  }

  Widget _segments(BuildContext context) => DecoratedBox(
        key: const Key('nutrition_verdict'),
        decoration: BoxDecoration(
            border: Border.all(color: MayosTheme.of(context).border),
            borderRadius: MayosRadii.mediumRadius),
        child: ClipRRect(
            borderRadius: MayosRadii.mediumRadius,
            child: IntrinsicHeight(
                child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                for (final String verdict in <String>[
                  'on_target',
                  'roughly',
                  'off'
                ])
                  Expanded(child: _segment(context, verdict)),
              ],
            ))),
      );

  Widget _segment(BuildContext context, String verdict) {
    final bool selected = _verdict(day.date) == verdict;
    final MayosThemeExtension tokens = MayosTheme.of(context);
    return Semantics(
        selected: selected,
        button: true,
        child: Material(
          color: selected ? tokens.selectedSurface : tokens.surface,
          child: InkWell(
            key: Key('adherence_$verdict'),
            onTap: saving || !_answerable ? null : () => onVerdict(verdict),
            child: Container(
                constraints: const BoxConstraints(minHeight: 64),
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                decoration: BoxDecoration(
                    border: BorderDirectional(
                        end: verdict == 'off'
                            ? BorderSide.none
                            : BorderSide(color: tokens.border))),
                child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: <Widget>[
                      NutritionAdherenceMark(verdict: verdict),
                      const SizedBox(height: 4),
                      Text(copy.adherenceLabel(verdict),
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.labelMedium),
                    ])),
          ),
        ));
  }

  Widget _history(BuildContext context) {
    final List<DateTime> dates = List<DateTime>.generate(
        7,
        (int index) => DateTime(
            day.today.year, day.today.month, day.today.day - 6 + index));
    return Column(
        key: const Key('nutrition_week'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Wrap(
              alignment: WrapAlignment.spaceBetween,
              spacing: MayosSpacing.xs,
              children: <Widget>[
                Text(copy.lastSevenDays,
                    style: Theme.of(context).textTheme.titleSmall),
                Text(
                    copy.onTargetCount(dates
                        .where((DateTime date) => _verdict(date) == 'on_target')
                        .length),
                    style: Theme.of(context).textTheme.bodySmall),
              ]),
          const SizedBox(height: MayosSpacing.xs),
          _historyMarks(dates),
        ]);
  }

  Widget _historyMarks(List<DateTime> dates) => LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) =>
            Stack(children: <Widget>[
          Row(children: <Widget>[
            for (final DateTime date in dates)
              Expanded(
                  child: Tooltip(
                message:
                    '${_dateKey(date)}: ${copy.adherenceLabel(_verdict(date))}',
                child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: 48),
                    child: Column(children: <Widget>[
                      NutritionAdherenceMark(verdict: _verdict(date)),
                      const SizedBox(height: MayosSpacing.xxs),
                      Text(copy.weekdayInitial(date),
                          style: Theme.of(context).textTheme.labelSmall),
                    ])),
              )),
          ]),
          // At 360 dp a strip column is narrower than 44 dp. Only yesterday is
          // actionable; its hit area extends into its non-interactive neighbours.
          PositionedDirectional(
              top: 0,
              bottom: 0,
              width: 44,
              end: constraints.maxWidth / 7 +
                  (constraints.maxWidth / 7 - 44) / 2,
              child: Semantics(
                  button: true,
                  label:
                      '${_dateKey(_yesterday)}: ${copy.adherenceLabel(_verdict(_yesterday))}',
                  child: InkWell(
                      key: const Key('answer_yesterday'),
                      borderRadius: MayosRadii.mediumRadius,
                      onTap: saving
                          ? null
                          : () => onAnswerYesterday(_dateKey(_yesterday))))),
        ]),
      );
}

class NutritionAdherenceMark extends StatelessWidget {
  const NutritionAdherenceMark({required this.verdict, super.key});
  final String? verdict;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension tokens = MayosTheme.of(context);
    final (IconData, Color) mark = switch (verdict) {
      'on_target' => (Icons.circle, tokens.accent),
      'roughly' => (Icons.change_history, tokens.success),
      'off' => (Icons.square, tokens.warning),
      _ => (Icons.circle_outlined, tokens.borderStrong),
    };
    return SizedBox(
        width: 24, height: 24, child: Icon(mark.$1, color: mark.$2, size: 18));
  }
}
