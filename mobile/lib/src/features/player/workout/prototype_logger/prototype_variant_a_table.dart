// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// Variant A — "Table" (classic Hevy): every exercise is a card with a set
// table (SET · PREVIOUS · KG · REPS · RIR · ✓). A slim rest bar sticks to the
// bottom; the keypad slides up over it when a cell is tapped.

import 'package:flutter/material.dart';

import '../../../../core/theme/mayos_spacing.dart';
import '../../../../core/theme/mayos_theme.dart';
import '../../../../core/theme/mayos_typography.dart';
import 'prototype_logger_model.dart';
import 'prototype_logger_widgets.dart';

class VariantATable extends StatefulWidget {
  const VariantATable({super.key, required this.session});
  static const String label = 'Table';
  final ProtoSession session;

  @override
  State<VariantATable> createState() => _VariantATableState();
}

class _VariantATableState extends State<VariantATable> {
  ProtoFocus? _focus;

  ProtoSession get s => widget.session;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ListenableBuilder(
      listenable: s,
      builder: (BuildContext context, _) => Column(children: <Widget>[
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 120),
            children: <Widget>[
              for (final ProtoExercise ex in s.exercises) _card(context, c, ex),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(52)),
                onPressed: () => showAddExercise(context, s),
                icon: const Icon(Icons.add),
                label: const Text('Add exercise'),
              ),
              const SizedBox(height: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(52)),
                onPressed: () => showFinish(context, s),
                child: const Text('Finish workout'),
              ),
            ],
          ),
        ),
        if (_focus != null)
          ProtoKeypad(
            session: s,
            focus: _focus!,
            onFocus: (ProtoFocus? f) => setState(() => _focus = f),
          )
        else if (s.rest != null)
          _restBar(c, s.rest!),
      ]),
    );
  }

  Widget _card(BuildContext context, MayosThemeExtension c, ProtoExercise ex) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: MayosRadii.largeRadius,
        border: Border.all(color: c.border),
      ),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
        Row(children: <Widget>[
          Expanded(
            child: Text(ex.name,
                style: MayosTypography.exerciseTitle
                    .copyWith(color: c.accent)),
          ),
          if (!ex.planned)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                  color: c.secondarySurface,
                  borderRadius: MayosRadii.pillRadius),
              child: Text('Unplanned', style: MayosTypography.caption),
            ),
        ]),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
            onPressed: () => showRestPicker(context, s, ex),
            icon: const Icon(Icons.timer_outlined, size: 18),
            label: Text('Rest ${ex.restSeconds == 0 ? 'off' : fmtClock(ex.restSeconds)}'),
          ),
        ),
        _headerRow(c),
        for (int i = 0; i < ex.sets.length; i++) _row(c, ex, i),
        TextButton.icon(
          style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
          onPressed: () => s.addSet(ex),
          icon: const Icon(Icons.add),
          label: const Text('Add set'),
        ),
      ]),
    );
  }

  static const List<int> _flex = <int>[2, 5, 3, 3, 2, 3];

  Widget _headerRow(MayosThemeExtension c) {
    final TextStyle st = MayosTypography.caption
        .copyWith(color: c.textMuted, fontWeight: FontWeight.w700);
    const List<String> h = <String>['SET', 'PREVIOUS', 'KG', 'REPS', 'RIR', ''];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: <Widget>[
        for (int i = 0; i < h.length; i++)
          Expanded(
              flex: _flex[i],
              child: Text(h[i], textAlign: TextAlign.center, style: st)),
      ]),
    );
  }

  Widget _row(MayosThemeExtension c, ProtoExercise ex, int i) {
    final ProtoSet set = ex.sets[i];
    final ProtoPrevSet? prev = ex.previousFor(i);
    final List<Widget> badges = protoBadges(s, set);
    Widget cell(ProtoField field, String? value, String? hint) {
      final bool focused = _focus?.set == set && _focus?.field == field;
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: Material(
          color: focused
              ? c.selectedSurface
              : set.done
                  ? Colors.transparent
                  : c.surfaceSunken,
          shape: RoundedRectangleBorder(
            borderRadius: MayosRadii.smallRadius,
            side: BorderSide(color: focused ? c.selectedBorder : Colors.transparent),
          ),
          child: InkWell(
            borderRadius: MayosRadii.smallRadius,
            onTap: () => setState(() => _focus = ProtoFocus(ex, set, field)),
            child: SizedBox(
              height: 44,
              child: Center(
                child: Text(
                  value ?? hint ?? '–',
                  style: MayosTypography.numeric.copyWith(
                    fontSize: 17,
                    color: value == null ? c.textDisabled : c.textPrimary,
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return Dismissible(
      key: ObjectKey(set),
      direction: DismissDirection.endToStart,
      onDismissed: (_) => s.removeSet(ex, set),
      background: Container(
        color: c.danger,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 16),
        child: Icon(Icons.delete, color: c.onDanger),
      ),
      child: AnimatedContainer(
        duration: MayosMotion.base,
        margin: const EdgeInsets.symmetric(vertical: 2),
        decoration: BoxDecoration(
          color: set.done ? c.success.withValues(alpha: 0.16) : null,
          borderRadius: MayosRadii.smallRadius,
        ),
        child: Column(children: <Widget>[
          Row(children: <Widget>[
            Expanded(
              flex: _flex[0],
              child: Text('${i + 1}',
                  textAlign: TextAlign.center,
                  style: MayosTypography.numericSmall),
            ),
            Expanded(
              flex: _flex[1],
              child: Text(prev?.label ?? '—',
                  textAlign: TextAlign.center,
                  style: MayosTypography.caption.copyWith(color: c.textMuted)),
            ),
            Expanded(
                flex: _flex[2],
                child: cell(ProtoField.kg,
                    set.kg == null ? null : fmtKg(set.kg!),
                    prev == null ? null : fmtKg(prev.kg))),
            Expanded(
                flex: _flex[3],
                child: cell(ProtoField.reps, set.reps?.toString(),
                    prev?.reps.toString())),
            Expanded(
                flex: _flex[4],
                child: cell(ProtoField.rir, set.rir?.toString(),
                    prev?.rir?.toString())),
            Expanded(
              flex: _flex[5],
              child: SizedBox(
                height: 48,
                child: IconButton(
                  onPressed: () {
                    if (!s.toggle(ex, set)) {
                      setState(() => _focus = ProtoFocus(ex, set, ProtoField.kg));
                    } else if (_focus?.set == set) {
                      setState(() => _focus = null);
                    }
                  },
                  style: IconButton.styleFrom(
                    backgroundColor: set.done ? c.success : c.surfaceSunken,
                    foregroundColor: set.done ? c.onSuccess : c.textMuted,
                    shape: RoundedRectangleBorder(
                        borderRadius: MayosRadii.smallRadius),
                  ),
                  icon: const Icon(Icons.check),
                ),
              ),
            ),
          ]),
          if (badges.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Wrap(spacing: 6, children: badges),
            ),
        ]),
      ),
    );
  }

  Widget _restBar(MayosThemeExtension c, ProtoRest r) {
    final double progress = r.total == 0 ? 0 : r.remaining / r.total;
    return Container(
      decoration: BoxDecoration(
        color: c.surfaceElevated,
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: Stack(children: <Widget>[
        Positioned.fill(
          child: FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: progress.clamp(0, 1),
            child: Container(color: c.accentSubtle),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(children: <Widget>[
            TextButton(onPressed: () => s.adjustRest(-15), child: const Text('−15')),
            Expanded(
              child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
                Text(fmtClock(r.remaining),
                    style: MayosTypography.numeric.copyWith(fontSize: 24)),
                Text('Rest · ${r.exercise.name}',
                    style: MayosTypography.caption.copyWith(color: c.textMuted)),
              ]),
            ),
            TextButton(onPressed: () => s.adjustRest(15), child: const Text('+15')),
            FilledButton.tonal(onPressed: s.skipRest, child: const Text('Skip')),
          ]),
        ),
      ]),
    );
  }
}
