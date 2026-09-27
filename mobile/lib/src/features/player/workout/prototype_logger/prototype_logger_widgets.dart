// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// Small pieces every variant reuses: the in-app number keypad, the Personal
// record badge, and the sheets (rest picker, add exercise, finish).

import 'package:flutter/material.dart';

import '../../../../core/theme/mayos_spacing.dart';
import '../../../../core/theme/mayos_theme.dart';
import '../../../../core/theme/mayos_typography.dart';
import 'prototype_logger_model.dart';

ProtoFocus? nextFocus(ProtoSession s, ProtoFocus f) {
  switch (f.field) {
    case ProtoField.kg:
      return ProtoFocus(f.exercise, f.set, ProtoField.reps);
    case ProtoField.reps:
      return ProtoFocus(f.exercise, f.set, ProtoField.rir);
    case ProtoField.rir:
      final int i = f.exercise.sets.indexOf(f.set);
      if (i + 1 < f.exercise.sets.length) {
        return ProtoFocus(f.exercise, f.exercise.sets[i + 1], ProtoField.kg);
      }
      return null;
  }
}

/// The in-app number keypad (no system keyboard, no weight steppers). RIR
/// switches to a one-tap chip row.
class ProtoKeypad extends StatefulWidget {
  const ProtoKeypad({
    super.key,
    required this.session,
    required this.focus,
    required this.onFocus,
    this.compact = false,
  });

  final ProtoSession session;
  final ProtoFocus focus;
  final ValueChanged<ProtoFocus?> onFocus;
  final bool compact;

  @override
  State<ProtoKeypad> createState() => _ProtoKeypadState();
}

class _ProtoKeypadState extends State<ProtoKeypad> {
  final ProtoKeypadBuffer _buffer = ProtoKeypadBuffer();
  ProtoFocus? _loadedFor;

  void _syncBuffer() {
    final ProtoFocus f = widget.focus;
    final ProtoFocus? l = _loadedFor;
    if (l == null || l.set != f.set || l.field != f.field) {
      _buffer.load(widget.session, f);
      _loadedFor = f;
    }
  }

  @override
  Widget build(BuildContext context) {
    _syncBuffer();
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProtoFocus f = widget.focus;
    final int index = f.exercise.sets.indexOf(f.set) + 1;
    final String fieldName = switch (f.field) {
      ProtoField.kg => 'Weight (kg)',
      ProtoField.reps => 'Reps',
      ProtoField.rir => 'Reps in reserve',
    };
    final double keyH = widget.compact ? 48 : 56;

    Widget key(String label, {VoidCallback? onTap, Color? bg, Color? fg}) {
      return Expanded(
        child: Padding(
          padding: const EdgeInsets.all(3),
          child: Material(
            color: bg ?? c.surfaceElevated,
            borderRadius: MayosRadii.mediumRadius,
            child: InkWell(
              borderRadius: MayosRadii.mediumRadius,
              onTap: onTap ??
                  () => setState(
                      () => _buffer.press(widget.session, f, label)),
              child: SizedBox(
                height: keyH,
                child: Center(
                  child: Text(label,
                      style: MayosTypography.numeric
                          .copyWith(color: fg ?? c.textPrimary, fontSize: 22)),
                ),
              ),
            ),
          ),
        ),
      );
    }

    final Widget body;
    if (f.field == ProtoField.rir) {
      body = Column(
        children: <Widget>[
          Row(children: <Widget>[
            for (final int v in <int>[0, 1, 2, 3, 4, 5])
              key('$v', onTap: () {
                widget.session.setRir(f.set, v);
                widget.onFocus(nextFocus(widget.session, f));
              },
                  bg: f.set.rir == v ? c.accent : null,
                  fg: f.set.rir == v ? c.onAccent : null),
          ]),
          Row(children: <Widget>[
            key('Unrated', onTap: () {
              widget.session.setRir(f.set, null);
              widget.onFocus(nextFocus(widget.session, f));
            }),
            key('Done',
                onTap: () => widget.onFocus(null),
                bg: c.secondarySurface),
          ]),
        ],
      );
    } else {
      body = Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(
            flex: 3,
            child: Column(children: <Widget>[
              Row(children: <Widget>[key('1'), key('2'), key('3')]),
              Row(children: <Widget>[key('4'), key('5'), key('6')]),
              Row(children: <Widget>[key('7'), key('8'), key('9')]),
              Row(children: <Widget>[
                key(f.field == ProtoField.kg ? '.' : ' ', onTap: () {
                  if (f.field == ProtoField.kg) {
                    setState(() => _buffer.press(widget.session, f, '.'));
                  }
                }),
                key('0'),
                key('⌫'),
              ]),
            ]),
          ),
          Expanded(
            child: Column(children: <Widget>[
              Row(children: <Widget>[
                key('Hide',
                    onTap: () => widget.onFocus(null), bg: c.secondarySurface),
              ]),
              SizedBox(
                height: (keyH + 6) * 3,
                child: Row(children: <Widget>[
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.all(3),
                      child: Material(
                        color: c.accent,
                        borderRadius: MayosRadii.mediumRadius,
                        child: InkWell(
                          borderRadius: MayosRadii.mediumRadius,
                          onTap: () =>
                              widget.onFocus(nextFocus(widget.session, f)),
                          child: Center(
                            child: Text('Next',
                                style: MayosTypography.label
                                    .copyWith(color: c.onAccent)),
                          ),
                        ),
                      ),
                    ),
                  ),
                ]),
              ),
            ]),
          ),
        ],
      );
    }

    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.xs, MayosSpacing.xs, MayosSpacing.xs, MayosSpacing.xs),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 0, 6, 6),
            child: Text('${f.exercise.name} · set $index · $fieldName',
                style: MayosTypography.caption.copyWith(color: c.textMuted)),
          ),
          body,
        ],
      ),
    );
  }
}

/// Small Personal record badge; `beaten` renders the struck-through version a
/// later set in the same session took over from.
class ProtoPrBadge extends StatelessWidget {
  const ProtoPrBadge(this.kind, {super.key, this.beaten = false});
  final PrKind kind;
  final bool beaten;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color fg = beaten ? c.textMuted : c.onWarning;
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: beaten ? 1 : 0.4, end: 1),
      duration: MayosMotion.slow,
      curve: Curves.elasticOut,
      builder: (BuildContext context, double t, Widget? child) =>
          Transform.scale(scale: t, child: child),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: beaten ? Colors.transparent : c.warning,
          border: Border.all(color: beaten ? c.border : c.warning),
          borderRadius: MayosRadii.pillRadius,
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
          Icon(Icons.emoji_events, size: 12, color: fg),
          const SizedBox(width: 3),
          Text(
            kind == PrKind.weight ? 'PR kg' : 'PR e1RM',
            style: MayosTypography.caption.copyWith(
              color: fg,
              fontWeight: FontWeight.w700,
              decoration: beaten ? TextDecoration.lineThrough : null,
            ),
          ),
        ]),
      ),
    );
  }
}

List<Widget> protoBadges(ProtoSession s, ProtoSet set) => <Widget>[
      for (final PrKind k in s.badgesOf(set)) ProtoPrBadge(k),
      for (final PrKind k in s.beatenOf(set)) ProtoPrBadge(k, beaten: true),
    ];

Future<void> showRestPicker(
    BuildContext context, ProtoSession s, ProtoExercise ex) {
  return showModalBottomSheet<void>(
    context: context,
    builder: (BuildContext context) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
        Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Text('Rest timer · ${ex.name}',
              style: MayosTypography.sectionHeading),
        ),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            for (final int sec in <int>[0, 60, 90, 120, 150, 180, 240, 300])
              ChoiceChip(
                label: Text(sec == 0 ? 'Off' : fmtClock(sec)),
                selected: ex.restSeconds == sec,
                onSelected: (_) {
                  s.setExerciseRest(ex, sec);
                  Navigator.pop(context);
                },
              ),
          ],
        ),
        const Padding(
          padding: EdgeInsets.all(MayosSpacing.md),
          child: Text('Remembered for this exercise on this device.'),
        ),
      ]),
    ),
  );
}

Future<ProtoExercise?> showAddExercise(BuildContext context, ProtoSession s) {
  return showModalBottomSheet<ProtoExercise>(
    context: context,
    builder: (BuildContext context) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
        const Padding(
          padding: EdgeInsets.all(MayosSpacing.md),
          child: Text('Add exercise', style: MayosTypography.sectionHeading),
        ),
        for (final (String, ProtoBaseline?) item in protoLibrary)
          ListTile(
            minTileHeight: kMayosMinTapTarget + 8,
            title: Text(item.$1),
            subtitle: Text(item.$2 == null
                ? 'Never logged: this session sets the baseline'
                : 'Best ${fmtKg(item.$2!.maxKg)} kg · '
                    'e1RM ${item.$2!.bestE1rm.toStringAsFixed(1)}'),
            trailing: const Icon(Icons.add),
            onTap: () =>
                Navigator.pop(context, s.addUnplanned(item.$1, item.$2)),
          ),
      ]),
    ),
  );
}

/// Finish with sets that were never ticked (open question on #108).
Future<void> showFinish(BuildContext context, ProtoSession s) async {
  final int unticked = s.untickedTotal;
  if (unticked > 0) {
    final String? choice = await showModalBottomSheet<String>(
      context: context,
      builder: (BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('$unticked sets aren\'t ticked',
                  style: MayosTypography.sectionHeading),
              const SizedBox(height: 8),
              const Text('Only ticked sets are saved to the workout.'),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => Navigator.pop(context, 'discard'),
                child: const Text('Discard unticked sets and finish'),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: () => Navigator.pop(context, null),
                child: const Text('Keep logging'),
              ),
            ],
          ),
        ),
      ),
    );
    if (choice != 'discard') return;
    s.discardUnticked();
  }
  if (!context.mounted) return;
  final List<(ProtoExercise, ProtoSet, PrKind)> records = s.records;
  await showDialog<void>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(records.isEmpty
          ? 'Workout saved'
          : '${records.length} personal record${records.length == 1 ? '' : 's'}!'),
      content: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
        const Text('(Summary screen stub — the celebration lives here.)'),
        for (final (ProtoExercise, ProtoSet, PrKind) r in records)
          ListTile(
            leading: const Icon(Icons.emoji_events),
            title: Text('${r.$1.name} · ${prLabel(r.$3)}'),
            subtitle: Text(r.$3 == PrKind.weight
                ? '${fmtKg(r.$2.kg!)} kg (was ${fmtKg(r.$1.baseline!.maxKg)})'
                : '${e1rm(r.$2.kg!, r.$2.reps!, r.$2.rir).toStringAsFixed(1)} kg '
                    '(was ${r.$1.baseline!.bestE1rm.toStringAsFixed(1)})'),
          ),
      ]),
      actions: <Widget>[
        TextButton(
          onPressed: () {
            Navigator.pop(context);
            s.reset();
          },
          child: const Text('Done (reset prototype)'),
        ),
      ],
    ),
  );
}

/// Mock of the Android lock-screen rest notification (a system chronometer).
class ProtoLockScreen extends StatelessWidget {
  const ProtoLockScreen({super.key, required this.session, required this.onClose});
  final ProtoSession session;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final ProtoRest? r = session.rest;
    final (ProtoExercise, ProtoSet)? next = session.nextUp;
    String nextLine = 'Workout complete';
    if (next != null) {
      final int i = next.$1.sets.indexOf(next.$2);
      final ProtoPrevSet? p = next.$1.previousFor(i);
      nextLine = 'Next: ${next.$1.name} · set ${i + 1}'
          '${p == null ? '' : ' · last ${p.label}'}';
    }
    return GestureDetector(
      onTap: onClose,
      child: Container(
        color: Colors.black.withValues(alpha: 0.92),
        alignment: Alignment.topCenter,
        padding: const EdgeInsets.fromLTRB(16, 80, 16, 16),
        child: Column(children: <Widget>[
          Text(TimeOfDay.now().format(context),
              style: const TextStyle(color: Colors.white, fontSize: 64)),
          const SizedBox(height: 32),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF2A2F36),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(children: <Widget>[
              const Icon(Icons.timer_outlined, color: Colors.white70),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      r == null
                          ? 'MAYOS · Workout in progress'
                          : 'MAYOS · Rest ${fmtClock(r.remaining)}',
                      style: const TextStyle(
                          color: Colors.white, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 2),
                    Text(nextLine,
                        style: const TextStyle(color: Colors.white70)),
                  ],
                ),
              ),
            ]),
          ),
          const Spacer(),
          const Text('Prototype mock of the lock-screen notification · tap to close',
              style: TextStyle(color: Colors.white38)),
        ]),
      ),
    );
  }
}
