// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// Three Coach mode shells, switchable via `?variant=A|B|C` on the debug-only
// `/prototype/coach` route, on stub data (no coach account needed):
//   A · Four tabs      Roster · Alerts · Requests · Profile (landing Roster)
//   B · Today inbox    Today · Players · Profile (landing Today)
//   C · Player-first   no tabs; filterable roster, all actions in the player
// Every variant shares the header avatar that switches Player/Coach mode.
//
// The switcher floats at the TOP: the bottom tabs are what is being judged.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../core/ui/mayos_scaffold.dart';
import 'prototype_coach_model.dart';
import 'prototype_coach_widgets.dart';
import 'prototype_variant_a_tabs.dart';
import 'prototype_variant_b_today.dart';
import 'prototype_variant_c_players.dart';

const String prototypeCoachPath = '/prototype/coach';

const List<(String, String)> _variants = <(String, String)>[
  ('A', VariantATabs.label),
  ('B', VariantBToday.label),
  ('C', VariantCPlayers.label),
];

class PrototypeCoachScreen extends StatefulWidget {
  const PrototypeCoachScreen({super.key, required this.variant});
  final String variant;

  @override
  State<PrototypeCoachScreen> createState() => _PrototypeCoachScreenState();
}

class _PrototypeCoachScreenState extends State<PrototypeCoachScreen> {
  bool _showState = false;

  int get _index {
    final int i =
        _variants.indexWhere(((String, String) v) => v.$1 == widget.variant);
    return i < 0 ? 0 : i;
  }

  void _go(int delta) {
    final int next = (_index + delta) % _variants.length;
    context.go('$prototypeCoachPath?variant=${_variants[next].$1}');
  }

  Widget _header(ProtoCoachState s, String key) => Padding(
        padding: const EdgeInsets.only(top: 44),
        child: MayosAppHeader(actions: <Widget>[
          if (key == 'C' && s.mode == ProtoMode.coach)
            IconButton(
              tooltip: 'Coach profile',
              icon: const Icon(Icons.badge_outlined),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => MayosScaffold(
                      title: 'Coach profile',
                      showBack: true,
                      body: ProtoCoachProfile(state: s)))),
            ),
          ProtoAvatarSwitch(state: s),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    return CallbackShortcuts(
      bindings: <ShortcutActivator, VoidCallback>{
        const SingleActivator(LogicalKeyboardKey.arrowLeft): () => _go(-1),
        const SingleActivator(LogicalKeyboardKey.arrowRight): () => _go(1),
      },
      child: Focus(
        autofocus: true,
        child: ListenableBuilder(
          listenable: protoCoach,
          builder: (BuildContext context, _) {
            final ProtoCoachState s = protoCoach;
            final String key = _variants[_index].$1;
            final Widget header = _header(s, key);
            final Widget shell = s.mode == ProtoMode.player
                ? MayosScaffold(header: header, body: ProtoPlayerModeStub(state: s))
                : switch (key) {
                    'B' => VariantBToday(
                        key: const ValueKey<String>('B'), state: s, header: header),
                    'C' => VariantCPlayers(
                        key: const ValueKey<String>('C'), state: s, header: header),
                    _ => VariantATabs(
                        key: const ValueKey<String>('A'), state: s, header: header),
                  };
            return Stack(children: <Widget>[
              shell,
              Positioned(
                top: MediaQuery.paddingOf(context).top + 4,
                left: 0,
                right: 0,
                child: Center(child: _switcher()),
              ),
              if (_showState)
                Positioned(
                  top: MediaQuery.paddingOf(context).top + 48,
                  left: 8,
                  right: 8,
                  bottom: 80,
                  child: _StatePanel(state: s),
                ),
            ]);
          },
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
      child: FittedBox(
        child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
          btn(Icons.chevron_left, 'Previous variant', () => _go(-1)),
          Text('${_variants[_index].$1} · ${_variants[_index].$2}',
              style: MayosTypography.label.copyWith(color: fg)),
          btn(Icons.chevron_right, 'Next variant', () => _go(1)),
          btn(Icons.data_object, 'Show state',
              () => setState(() => _showState = !_showState),
              on: _showState),
          btn(Icons.restart_alt, 'Reset stub data', protoCoach.reset),
        ]),
      ),
    );
  }
}

class _StatePanel extends StatelessWidget {
  const _StatePanel({required this.state});
  final ProtoCoachState state;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextStyle mono =
        TextStyle(fontFamily: 'monospace', fontSize: 12, color: c.textPrimary);
    final ProtoCoachState s = state;
    return Material(
      color: c.surfaceElevated.withValues(alpha: 0.97),
      elevation: 8,
      borderRadius: MayosRadii.largeRadius,
      child: ListView(padding: const EdgeInsets.all(12), children: <Widget>[
        Text('Prototype state', style: MayosTypography.sectionHeading),
        const SizedBox(height: 8),
        Text('mode=${s.mode.name}  lastMode(persisted)=${s.lastMode.name}  '
            'playerOnboarded=${s.playerOnboarded}', style: mono),
        const SizedBox(height: 8),
        for (final ProtoPlayer p in s.rosterByAttention())
          Text(
              '${p.username.padRight(12)} attention=${s.attention(p)} '
              'streak=${p.missedStreak} followUp=${p.nextFollowUpOn ?? '-'}${s.followUpDue(p) ? '(due)' : ''} '
              'alerts=${s.openAlerts(p.assignmentId).map((ProtoAlert a) => '${a.kind}:${a.state}').join(',')} '
              'requests=${s.pendingRequests(p.assignmentId).length}',
              style: mono),
        const Divider(),
        Text('event log (newest first)', style: MayosTypography.label),
        for (final String line in s.log) Text(line, style: mono),
      ]),
    );
  }
}
