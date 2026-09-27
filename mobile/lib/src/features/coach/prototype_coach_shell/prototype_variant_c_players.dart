// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// Variant C · Player-first, no bottom tabs. The roster is the whole shell,
// sorted by attention. Summary counters on top filter it (Requests, Alerts,
// Follow-ups, Missed). Alerts and requests are handled inside the player, so
// every action happens in the player's context. Profile/invite sit behind the
// header's badge icon.

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_scaffold.dart';
import 'prototype_coach_model.dart';
import 'prototype_coach_widgets.dart';

enum _Filter { all, requests, alerts, followUps, missed }

class VariantCPlayers extends StatefulWidget {
  const VariantCPlayers({super.key, required this.state, required this.header});
  static const String label = 'Player-first';
  final ProtoCoachState state;
  final Widget header;

  @override
  State<VariantCPlayers> createState() => _VariantCPlayersState();
}

class _VariantCPlayersState extends State<VariantCPlayers> {
  _Filter _filter = _Filter.all;

  bool _match(ProtoCoachState s, ProtoPlayer p) => switch (_filter) {
        _Filter.all => true,
        _Filter.requests => s.pendingRequests(p.assignmentId).isNotEmpty,
        _Filter.alerts => s
            .openAlerts(p.assignmentId)
            .any((ProtoAlert a) => a.state == 'new'),
        _Filter.followUps => s.followUpDue(p),
        _Filter.missed => p.missedStreak > 0,
      };

  @override
  Widget build(BuildContext context) {
    final ProtoCoachState s = widget.state;
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ProtoPlayer> sorted = s.rosterByAttention();
    final List<ProtoPlayer> needs =
        sorted.where((ProtoPlayer p) => s.attention(p) > 0 && _match(s, p)).toList();
    final List<ProtoPlayer> onTrack = _filter == _Filter.all
        ? sorted.where((ProtoPlayer p) => s.attention(p) == 0).toList()
        : <ProtoPlayer>[];

    Widget counter(_Filter f, int n, String label, Color color) {
      final bool on = _filter == f;
      return Expanded(
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => setState(() => _filter = on ? _Filter.all : f),
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.symmetric(vertical: 8),
            decoration: BoxDecoration(
              color: on ? color.withValues(alpha: 0.14) : c.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: on ? color : c.border),
            ),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: <Widget>[
              Text('$n',
                  style: MayosTypography.numeric
                      .copyWith(fontSize: 22, color: n > 0 ? color : c.textMuted)),
              Text(label,
                  style: MayosTypography.caption.copyWith(color: c.textSecondary)),
            ]),
          ),
        ),
      );
    }

    return MayosScaffold(
      header: widget.header,
      body: ListView(padding: const EdgeInsets.only(bottom: 32), children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
          child: Text('Your players', style: MayosTypography.pageHeading),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(children: <Widget>[
            counter(_Filter.requests, s.pendingRequests().length, 'Requests', c.accent),
            const SizedBox(width: 8),
            counter(_Filter.alerts,
                s.alerts.where((ProtoAlert a) => a.state == 'new').length, 'Alerts', c.danger),
            const SizedBox(width: 8),
            counter(_Filter.followUps, s.players.where(s.followUpDue).length,
                'Follow-ups', c.warning),
            const SizedBox(width: 8),
            counter(_Filter.missed,
                s.players.where((ProtoPlayer p) => p.missedStreak > 0).length,
                'Missing', c.danger),
          ]),
        ),
        const SizedBox(height: 8),
        if (needs.isNotEmpty) _label(context, 'Needs attention'),
        for (final ProtoPlayer p in needs) _row(s, p, c),
        if (needs.isEmpty && _filter != _Filter.all)
          const Padding(padding: EdgeInsets.all(20), child: Text('Nobody here.')),
        if (onTrack.isNotEmpty) _label(context, 'On track'),
        for (final ProtoPlayer p in onTrack) _row(s, p, c),
      ]),
    );
  }

  Widget _row(ProtoCoachState s, ProtoPlayer p, MayosThemeExtension c) => Column(
        children: <Widget>[
          ProtoRosterRow(state: s, player: p),
          Divider(height: 1, indent: 72, color: c.border),
        ],
      );

  Widget _label(BuildContext context, String t) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 4),
        child: Text(t.toUpperCase(),
            style: MayosTypography.label.copyWith(
                letterSpacing: 1.2, color: MayosTheme.of(context).textSecondary)),
      );
}
