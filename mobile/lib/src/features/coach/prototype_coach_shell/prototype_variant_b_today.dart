// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// Variant B · Today inbox: Today · Players · Profile, landing on Today.
// One prioritised to-do feed merges new alerts, pending requests and due
// follow-ups, each actionable inline. It empties to "All clear". Players is
// the plain roster for browsing.

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_scaffold.dart';
import 'prototype_coach_model.dart';
import 'prototype_coach_widgets.dart';

class VariantBToday extends StatefulWidget {
  const VariantBToday({super.key, required this.state, required this.header});
  static const String label = 'Today inbox';
  final ProtoCoachState state;
  final Widget header;

  @override
  State<VariantBToday> createState() => _VariantBTodayState();
}

class _VariantBTodayState extends State<VariantBToday> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final ProtoCoachState s = widget.state;
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ProtoRequest> reqs = s.pendingRequests();
    final List<ProtoAlert> fresh =
        s.alerts.where((ProtoAlert a) => a.state == 'new').toList();
    final List<ProtoAlert> waiting =
        s.alerts.where((ProtoAlert a) => a.state == 'acknowledged').toList();
    final int todo = reqs.length + fresh.length;

    final Widget today = ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 4),
          child: Text('Today', style: MayosTypography.pageHeading),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
          child: Text(
              todo == 0
                  ? 'Nothing needs you right now.'
                  : '$todo thing${todo == 1 ? '' : 's'} need you · ${s.players.length} players',
              style: MayosTypography.bodySecondary),
        ),
        if (todo == 0)
          Padding(
            padding: const EdgeInsets.all(16),
            child: MayosCard(
              child: Row(children: <Widget>[
                Icon(Icons.check_circle_outline, color: c.success),
                const SizedBox(width: 12),
                const Expanded(child: Text('All clear. Browse Players for detail.')),
              ]),
            ),
          ),
        if (reqs.isNotEmpty) _label(context, 'Requests to answer'),
        for (final ProtoRequest r in reqs)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: ProtoRequestCard(state: s, request: r),
          ),
        if (fresh.isNotEmpty) _label(context, 'New alerts'),
        for (final ProtoAlert a in fresh)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: ProtoAlertTile(state: s, alert: a),
          ),
        if (waiting.isNotEmpty) _label(context, 'Acknowledged · still open'),
        for (final ProtoAlert a in waiting)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: ProtoAlertTile(state: s, alert: a),
          ),
      ],
    );

    final List<ProtoPlayer> roster = <ProtoPlayer>[...s.players]
      ..sort((ProtoPlayer a, ProtoPlayer b) => a.username.compareTo(b.username));
    final Widget players = ListView(children: <Widget>[
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
        child: Text('Players', style: MayosTypography.pageHeading),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: TextField(
          decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: 'Search ${s.players.length} players',
              isDense: true),
        ),
      ),
      for (final ProtoPlayer p in roster) ...<Widget>[
        ProtoRosterRow(state: s, player: p),
        Divider(height: 1, indent: 72, color: c.border),
      ],
    ]);

    return MayosScaffold(
      header: widget.header,
      body: IndexedStack(
          index: _tab,
          children: <Widget>[today, players, ProtoCoachProfile(state: s)]),
      bottomBar: ProtoNavBar(
        index: _tab,
        onSelected: (int i) => setState(() => _tab = i),
        items: <ProtoNavItem>[
          ProtoNavItem('Today', Icons.today_outlined, Icons.today, todo),
          const ProtoNavItem('Players', Icons.groups_outlined, Icons.groups),
          const ProtoNavItem('Profile', Icons.badge_outlined, Icons.badge),
        ],
      ),
    );
  }

  Widget _label(BuildContext context, String t) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 6),
        child: Text(t.toUpperCase(),
            style: MayosTypography.label.copyWith(
                letterSpacing: 1.2, color: MayosTheme.of(context).textSecondary)),
      );
}
