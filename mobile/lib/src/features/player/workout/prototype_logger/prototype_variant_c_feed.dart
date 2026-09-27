// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// Variant C — "Feed + composer": completed sets scroll up as a log (newest at
// the bottom, like a chat), and a pinned composer at the bottom always holds
// the next set, pre-filled from last time, with one big tick. The rest timer
// is a pill in the composer header. Exercises are chips along the top.

import 'package:flutter/material.dart';

import '../../../../core/theme/mayos_spacing.dart';
import '../../../../core/theme/mayos_theme.dart';
import '../../../../core/theme/mayos_typography.dart';
import 'prototype_logger_model.dart';
import 'prototype_logger_widgets.dart';

class VariantCFeed extends StatefulWidget {
  const VariantCFeed({super.key, required this.session});
  static const String label = 'Feed + composer';
  final ProtoSession session;

  @override
  State<VariantCFeed> createState() => _VariantCFeedState();
}

class _VariantCFeedState extends State<VariantCFeed> {
  final ScrollController _scroll = ScrollController();
  ProtoExercise? _target;
  ProtoFocus? _focus;

  ProtoSession get s => widget.session;

  ProtoExercise? get _exercise {
    final ProtoExercise? t = _target;
    if (t != null && s.exercises.contains(t)) return t;
    return s.nextUp?.$1 ?? (s.exercises.isEmpty ? null : s.exercises.last);
  }

  ProtoSet? _setOf(ProtoExercise ex) {
    for (final ProtoSet set in ex.sets) {
      if (!set.done) return set;
    }
    return null;
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _toBottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: MayosMotion.base, curve: MayosMotion.standard);
        }
      });

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ListenableBuilder(
      listenable: s,
      builder: (BuildContext context, _) {
        final ProtoExercise? ex = _exercise;
        return Column(children: <Widget>[
          _strip(context, c, ex),
          Expanded(child: _feed(c)),
          if (ex != null) _composer(context, c, ex),
        ]);
      },
    );
  }

  Widget _strip(BuildContext context, MayosThemeExtension c, ProtoExercise? cur) {
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: <Widget>[
          for (final ProtoExercise ex in s.exercises)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: FilterChip(
                showCheckmark: false,
                avatar: ex.doneCount == ex.sets.length && ex.sets.isNotEmpty
                    ? Icon(Icons.check, size: 16, color: c.success)
                    : null,
                label: Text('${ex.name} ${ex.doneCount}/${ex.sets.length}'),
                selected: ex == cur,
                onSelected: (_) => setState(() {
                  _target = ex;
                  _focus = null;
                }),
              ),
            ),
          ActionChip(
            avatar: const Icon(Icons.add, size: 18),
            label: const Text('Exercise'),
            onPressed: () async {
              final ProtoExercise? ex = await showAddExercise(context, s);
              if (ex != null) setState(() => _target = ex);
            },
          ),
        ],
      ),
    );
  }

  Widget _feed(MayosThemeExtension c) {
    final List<(ProtoExercise, ProtoSet)> done = <(ProtoExercise, ProtoSet)>[
      for (final ProtoExercise ex in s.exercises)
        for (final ProtoSet set in ex.sets)
          if (set.done) (ex, set),
    ]..sort(((ProtoExercise, ProtoSet) a, (ProtoExercise, ProtoSet) b) =>
        a.$2.doneSeq.compareTo(b.$2.doneSeq));
    if (done.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text('Ticked sets appear here.\nThe next set is waiting below.',
              textAlign: TextAlign.center,
              style: MayosTypography.bodySecondary.copyWith(color: c.textMuted)),
        ),
      );
    }
    final List<Widget> children = <Widget>[];
    ProtoExercise? lastEx;
    for (final (ProtoExercise, ProtoSet) item in done) {
      if (item.$1 != lastEx) {
        lastEx = item.$1;
        children.add(Padding(
          padding: const EdgeInsets.fromLTRB(4, 14, 4, 4),
          child: Text(item.$1.name.toUpperCase(),
              style: MayosTypography.label.copyWith(color: c.textMuted)),
        ));
      }
      final int i = item.$1.sets.indexOf(item.$2);
      final ProtoSet set = item.$2;
      children.add(Material(
        color: c.surface,
        borderRadius: MayosRadii.mediumRadius,
        child: InkWell(
          borderRadius: MayosRadii.mediumRadius,
          onLongPress: () => s.toggle(item.$1, set),
          onTap: () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Set ${i + 1} of ${item.$1.name}'),
            action: SnackBarAction(
                label: 'Untick', onPressed: () => s.toggle(item.$1, set)),
          )),
          child: Container(
            margin: const EdgeInsets.only(bottom: 4),
            constraints: const BoxConstraints(minHeight: 48),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(children: <Widget>[
              Icon(Icons.check_circle, size: 18, color: c.success),
              const SizedBox(width: 10),
              Text('Set ${i + 1}',
                  style: MayosTypography.caption.copyWith(color: c.textMuted)),
              const SizedBox(width: 10),
              Expanded(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text('${fmtKg(set.kg!)} kg × ${set.reps}'
                        '${set.rir == null ? '' : '  RIR ${set.rir}'}',
                        style: MayosTypography.numericSmall),
                    ...protoBadges(s, set),
                  ],
                ),
              ),
            ]),
          ),
        ),
      ));
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      children: children,
    );
  }

  Widget _composer(BuildContext context, MayosThemeExtension c, ProtoExercise ex) {
    final ProtoSet? set = _setOf(ex);
    final ProtoRest? r = s.rest;
    return Material(
      color: c.surfaceElevated,
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 8, 4),
            child: Row(children: <Widget>[
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
                  Text(ex.name, style: MayosTypography.exerciseTitle),
                  Text(
                    set == null
                        ? 'All ${ex.sets.length} sets done'
                        : 'Set ${ex.sets.indexOf(set) + 1} of ${ex.sets.length}'
                            '${ex.planned ? '' : ' · Unplanned'}',
                    style: MayosTypography.caption.copyWith(color: c.textMuted),
                  ),
                ]),
              ),
              if (r != null) _restPill(c, r) else
                TextButton.icon(
                  onPressed: () => showRestPicker(context, s, ex),
                  icon: const Icon(Icons.timer_outlined, size: 18),
                  label: Text(ex.restSeconds == 0 ? 'off' : fmtClock(ex.restSeconds)),
                ),
            ]),
          ),
          if (set != null) _fields(c, ex, set) else
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: <Widget>[
                Expanded(
                  child: OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                    onPressed: () => s.addSet(ex),
                    icon: const Icon(Icons.add),
                    label: const Text('Another set'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                    onPressed: () => showFinish(context, s),
                    child: const Text('Finish'),
                  ),
                ),
              ]),
            ),
          if (_focus != null)
            ProtoKeypad(
              session: s,
              focus: _focus!,
              compact: true,
              onFocus: (ProtoFocus? f) => setState(() {
                _focus = f != null && f.set != _focus!.set ? null : f;
              }),
            ),
        ]),
      ),
    );
  }

  Widget _fields(MayosThemeExtension c, ProtoExercise ex, ProtoSet set) {
    final int i = ex.sets.indexOf(set);
    final ProtoPrevSet? prev = ex.previousFor(i);
    Widget field(String caption, ProtoField f, String? value, String? hint) {
      final bool focused = _focus?.set == set && _focus?.field == f;
      return Expanded(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Material(
            color: focused ? c.selectedSurface : c.surface,
            shape: RoundedRectangleBorder(
              borderRadius: MayosRadii.mediumRadius,
              side: BorderSide(color: focused ? c.selectedBorder : c.border),
            ),
            child: InkWell(
              borderRadius: MayosRadii.mediumRadius,
              onTap: () => setState(() => _focus = ProtoFocus(ex, set, f)),
              child: SizedBox(
                height: 68,
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: <Widget>[
                  Text(value ?? hint ?? '–',
                      style: MayosTypography.numeric.copyWith(
                          fontSize: 24,
                          color: value == null ? c.textDisabled : c.textPrimary)),
                  Text(caption,
                      style: MayosTypography.caption.copyWith(color: c.textMuted)),
                ]),
              ),
            ),
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
      child: Column(children: <Widget>[
        Row(children: <Widget>[
          field('kg', ProtoField.kg, set.kg == null ? null : fmtKg(set.kg!),
              prev == null ? null : fmtKg(prev.kg)),
          field('reps', ProtoField.reps, set.reps?.toString(), prev?.reps.toString()),
          field('RIR', ProtoField.rir, set.rir?.toString(), prev?.rir?.toString()),
          const SizedBox(width: 4),
          SizedBox(
            width: 72,
            height: 68,
            child: FilledButton(
              style: FilledButton.styleFrom(
                padding: EdgeInsets.zero,
                backgroundColor: c.success,
                foregroundColor: c.onSuccess,
                shape: RoundedRectangleBorder(borderRadius: MayosRadii.mediumRadius),
              ),
              onPressed: () => setState(() {
                if (!s.toggle(ex, set)) {
                  _focus = ProtoFocus(ex, set, ProtoField.kg);
                  return;
                }
                _focus = null;
                _toBottom();
              }),
              child: const Icon(Icons.check, size: 32),
            ),
          ),
        ]),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(prev == null ? 'First time: sets your baseline' : 'Last time ${prev.label}',
              style: MayosTypography.caption.copyWith(color: c.textMuted)),
        ),
        Row(children: <Widget>[
          Expanded(child: TextButton(onPressed: () => s.addSet(ex), child: const Text('+ set'))),
          Expanded(
            child: TextButton(
              onPressed: () => s.removeSet(ex, set),
              child: const Text('Skip set'),
            ),
          ),
          Expanded(child: TextButton(onPressed: () => showFinish(context, s), child: const Text('Finish'))),
        ]),
      ]),
    );
  }

  Widget _restPill(MayosThemeExtension c, ProtoRest r) {
    return Container(
      decoration: BoxDecoration(
        color: c.accentSubtle,
        borderRadius: MayosRadii.pillRadius,
        border: Border.all(color: c.accent),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
        IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: () => s.adjustRest(-15),
            icon: const Icon(Icons.remove)),
        Text(fmtClock(r.remaining), style: MayosTypography.numeric.copyWith(fontSize: 20)),
        IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: () => s.adjustRest(15),
            icon: const Icon(Icons.add)),
        IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: s.skipRest,
            icon: const Icon(Icons.skip_next)),
      ]),
    );
  }
}
