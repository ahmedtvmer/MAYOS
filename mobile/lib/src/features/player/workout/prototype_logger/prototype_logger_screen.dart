// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// Three variants of the Hevy-style in-workout screen, switchable via
// `?variant=A|B|C` on the debug-only `/prototype/logger` route. The real
// logger needs a signed-in account, a program and Android offline storage;
// this route runs on stub data so it opens anywhere (web or phone).
//
// The switcher floats at the TOP (not bottom-centre): the bottom of this
// screen is exactly what is being judged (keypad, rest bar, composer).

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/mayos_spacing.dart';
import '../../../../core/theme/mayos_theme.dart';
import '../../../../core/theme/mayos_typography.dart';
import '../../../../core/ui/mayos_scaffold.dart';
import 'prototype_logger_model.dart';
import 'prototype_logger_widgets.dart';
import 'prototype_variant_a_table.dart';
import 'prototype_variant_b_focus.dart';
import 'prototype_variant_c_feed.dart';

const String prototypeLoggerPath = '/prototype/logger';

const List<(String, String)> _variants = <(String, String)>[
  ('A', VariantATable.label),
  ('B', VariantBFocus.label),
  ('C', VariantCFeed.label),
];

class PrototypeLoggerScreen extends StatefulWidget {
  const PrototypeLoggerScreen({super.key, required this.variant});
  final String variant;

  @override
  State<PrototypeLoggerScreen> createState() => _PrototypeLoggerScreenState();
}

class _PrototypeLoggerScreenState extends State<PrototypeLoggerScreen> {
  bool _showState = false;
  bool _lock = false;

  int get _index {
    final int i = _variants.indexWhere(((String, String) v) => v.$1 == widget.variant);
    return i < 0 ? 0 : i;
  }

  void _go(int delta) {
    final int next = (_index + delta) % _variants.length;
    context.go('$prototypeLoggerPath?variant=${_variants[next].$1}');
  }

  @override
  Widget build(BuildContext context) {
    final Widget body = switch (_variants[_index].$1) {
      'B' => VariantBFocus(key: const ValueKey<String>('B'), session: protoSession),
      'C' => VariantCFeed(key: const ValueKey<String>('C'), session: protoSession),
      _ => VariantATable(key: const ValueKey<String>('A'), session: protoSession),
    };
    return CallbackShortcuts(
      bindings: <ShortcutActivator, VoidCallback>{
        const SingleActivator(LogicalKeyboardKey.arrowLeft): () => _go(-1),
        const SingleActivator(LogicalKeyboardKey.arrowRight): () => _go(1),
      },
      child: Focus(
        autofocus: true,
        child: MayosScaffold(
          title: 'Push A',
          actions: const <Widget>[
            Tooltip(
              message: 'Screen stays awake while logging',
              child: Padding(
                padding: EdgeInsets.all(12),
                child: Icon(Icons.light_mode_outlined, size: 20),
              ),
            ),
          ],
          body: Stack(children: <Widget>[
            Padding(padding: const EdgeInsets.only(top: 44), child: body),
            Positioned(top: 4, left: 0, right: 0, child: Center(
                child: ConstrainedBox(
                    constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width - 16),
                    child: _switcher()))),
            if (_showState)
              Positioned(
                top: 48,
                left: 8,
                right: 8,
                bottom: 8,
                child: _StatePanel(session: protoSession),
              ),
            if (_lock)
              Positioned.fill(
                child: ListenableBuilder(
                  listenable: protoSession,
                  builder: (BuildContext context, _) => ProtoLockScreen(
                    session: protoSession,
                    onClose: () => setState(() => _lock = false),
                  ),
                ),
              ),
          ]),
        ),
      ),
    );
  }

  Widget _switcher() {
    const Color fg = Colors.white;
    Widget btn(IconData icon, String tip, VoidCallback onTap, {bool on = false}) =>
        IconButton(
          tooltip: tip,
          visualDensity: VisualDensity.compact,
          color: on ? Colors.amber : fg,
          onPressed: onTap,
          icon: Icon(icon, size: 18),
        );
    return Material(
      color: const Color(0xFFE8335B),
      elevation: 6,
      borderRadius: MayosRadii.pillRadius,
      child: FittedBox(child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
        btn(Icons.chevron_left, 'Previous variant', () => _go(-1)),
        Text('${_variants[_index].$1} · ${_variants[_index].$2}',
            style: MayosTypography.label.copyWith(color: fg)),
        btn(Icons.chevron_right, 'Next variant', () => _go(1)),
        btn(Icons.data_object, 'Show state', () => setState(() => _showState = !_showState),
            on: _showState),
        btn(Icons.lock_outline, 'Lock-screen notification', () => setState(() => _lock = true)),
        btn(Icons.restart_alt, 'Reset workout', protoSession.reset),
      ])),
    );
  }
}

class _StatePanel extends StatelessWidget {
  const _StatePanel({required this.session});
  final ProtoSession session;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.surfaceElevated.withValues(alpha: 0.97),
      elevation: 8,
      borderRadius: MayosRadii.largeRadius,
      child: ListenableBuilder(
        listenable: session,
        builder: (BuildContext context, _) {
          final TextStyle mono = TextStyle(
              fontFamily: 'monospace', fontSize: 12, color: c.textPrimary);
          final ProtoRest? r = session.rest;
          return ListView(padding: const EdgeInsets.all(12), children: <Widget>[
            Text('Prototype state', style: MayosTypography.sectionHeading),
            const SizedBox(height: 8),
            Text('rest: ${r == null ? 'idle' : '${r.exercise.name} ${fmtClock(r.remaining)} / ${fmtClock(r.total)}'}',
                style: mono),
            const SizedBox(height: 8),
            for (final ProtoExercise ex in session.exercises) ...<Widget>[
              Text(
                  '${ex.name}${ex.planned ? '' : ' [unplanned]'} rest=${fmtClock(ex.restSeconds)} '
                  'baseline=${ex.baseline == null ? 'none (first session → no records)' : '${fmtKg(ex.baseline!.maxKg)}kg / e1RM ${ex.baseline!.bestE1rm}'}',
                  style: mono.copyWith(fontWeight: FontWeight.bold)),
              for (int i = 0; i < ex.sets.length; i++)
                Text(
                    '  set ${i + 1}: kg=${ex.sets[i].kg == null ? '-' : fmtKg(ex.sets[i].kg!)} '
                    'reps=${ex.sets[i].reps ?? '-'} rir=${ex.sets[i].rir ?? 'unrated'} '
                    '${ex.sets[i].done ? '✓#${ex.sets[i].doneSeq} e1RM=${e1rm(ex.sets[i].kg!, ex.sets[i].reps!, ex.sets[i].rir).toStringAsFixed(1)}' : ''}'
                    '${session.badgesOf(ex.sets[i]).isEmpty ? '' : ' PR:${session.badgesOf(ex.sets[i]).map(prLabel).join('+')}'}'
                    '${session.beatenOf(ex.sets[i]).isEmpty ? '' : ' beaten:${session.beatenOf(ex.sets[i]).map(prLabel).join('+')}'}',
                    style: mono),
            ],
            const Divider(),
            Text('event log (newest first)', style: MayosTypography.label),
            for (final String line in session.log) Text(line, style: mono),
          ]);
        },
      ),
    );
  }
}
