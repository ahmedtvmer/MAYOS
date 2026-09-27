// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// Variant A · Four tabs: the ticket's starting proposal.
// Roster · Alerts · Requests · Profile, landing on Roster. Each concern has
// its own list; badges on the tabs carry the counts.

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_scaffold.dart';
import 'prototype_coach_model.dart';
import 'prototype_coach_widgets.dart';

class VariantATabs extends StatefulWidget {
  const VariantATabs({super.key, required this.state, required this.header});
  static const String label = 'Four tabs';
  final ProtoCoachState state;
  final Widget header;

  @override
  State<VariantATabs> createState() => _VariantATabsState();
}

class _VariantATabsState extends State<VariantATabs> {
  int _tab = 0;
  bool _showResolved = false;

  @override
  Widget build(BuildContext context) {
    final ProtoCoachState s = widget.state;
    final MayosThemeExtension c = MayosTheme.of(context);
    final int newAlerts =
        s.openAlerts().where((ProtoAlert a) => a.state == 'new').length;
    final int pending = s.pendingRequests().length;
    return MayosScaffold(
      header: widget.header,
      body: IndexedStack(index: _tab, children: <Widget>[
        // Roster
        ListView(children: <Widget>[
          _title('Roster', '${s.players.length} players · most urgent first'),
          for (final ProtoPlayer p in s.rosterByAttention()) ...<Widget>[
            ProtoRosterRow(state: s, player: p),
            Divider(height: 1, indent: 72, color: c.border),
          ],
        ]),
        // Alerts
        ListView(padding: const EdgeInsets.only(bottom: 24), children: <Widget>[
          _title('Alerts', '$newAlerts new'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(spacing: 8, children: <Widget>[
              FilterChip(
                  label: const Text('Show resolved'),
                  selected: _showResolved,
                  onSelected: (bool v) => setState(() => _showResolved = v)),
            ]),
          ),
          for (final ProtoAlert a in s.alerts.where(
              (ProtoAlert a) => _showResolved || a.state != 'resolved'))
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: ProtoAlertTile(state: s, alert: a),
            ),
        ]),
        // Requests
        ListView(padding: const EdgeInsets.only(bottom: 24), children: <Widget>[
          _title('Requests', '$pending waiting for you'),
          if (pending == 0)
            const Padding(
                padding: EdgeInsets.all(20), child: Text('No pending requests.')),
          for (final ProtoRequest r in s.pendingRequests())
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: ProtoRequestCard(state: s, request: r),
            ),
          _title('Answered', null),
          for (final ProtoRequest r
              in s.requests.where((ProtoRequest r) => r.status != 'pending'))
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: ProtoRequestCard(state: s, request: r),
            ),
        ]),
        ProtoCoachProfile(state: s),
      ]),
      bottomBar: ProtoNavBar(
        index: _tab,
        onSelected: (int i) => setState(() => _tab = i),
        items: <ProtoNavItem>[
          const ProtoNavItem('Roster', Icons.groups_outlined, Icons.groups),
          ProtoNavItem('Alerts', Icons.notifications_outlined,
              Icons.notifications, newAlerts),
          ProtoNavItem('Requests', Icons.inbox_outlined, Icons.inbox, pending),
          const ProtoNavItem('Profile', Icons.badge_outlined, Icons.badge),
        ],
      ),
    );
  }

  Widget _title(String t, String? sub) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
          Text(t, style: MayosTypography.pageHeading),
          if (sub != null) Text(sub, style: MayosTypography.caption),
          const SizedBox(height: MayosSpacing.xxs),
        ]),
      );
}
