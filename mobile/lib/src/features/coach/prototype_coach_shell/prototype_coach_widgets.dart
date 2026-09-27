// PROTOTYPE — throwaway (wayfinder #105). Not production code; do not merge.
//
// Pieces shared by every variant: the header avatar with the Player/Coach
// switch, roster rows, alert and request tiles, the request-resolve sheet, the
// player drill-down (history · check-ins · requests), and a stub Player mode.
// Variants disagree on the shell structure, not on these pieces.

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_scaffold.dart';
import 'prototype_coach_model.dart';

// ─── Header avatar + mode switch ────────────────────────────────────────────

/// The avatar in the header. A small corner badge shows the current mode, so
/// the coach can tell at a glance which side of the app they are on.
class ProtoAvatarSwitch extends StatelessWidget {
  const ProtoAvatarSwitch({super.key, required this.state});
  final ProtoCoachState state;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool coach = state.mode == ProtoMode.coach;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Semantics(
        button: true,
        label: 'Account and mode. Current: ${coach ? 'Coach' : 'Player'} mode',
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () => showModeSheet(context, state),
          child: SizedBox(
            width: 48,
            height: 48,
            child: Stack(alignment: Alignment.center, children: <Widget>[
              CircleAvatar(
                radius: 17,
                backgroundColor: c.accentSubtle,
                child: Text('AH',
                    style: MayosTypography.label
                        .copyWith(fontSize: 12, color: c.accent)),
              ),
              Positioned(
                right: 4,
                bottom: 6,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                  decoration: BoxDecoration(
                    color: coach ? c.accent : c.success,
                    borderRadius: MayosRadii.pillRadius,
                    border: Border.all(color: c.canvas, width: 1.5),
                  ),
                  child: Text(coach ? 'C' : 'P',
                      style: TextStyle(
                          fontSize: 9,
                          fontWeight: FontWeight.w700,
                          color: coach ? c.onAccent : c.onSuccess)),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

Future<void> showModeSheet(BuildContext context, ProtoCoachState state) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (BuildContext context) {
      final MayosThemeExtension c = MayosTheme.of(context);
      Widget modeRow(ProtoMode m, IconData icon, String title, String sub) {
        final bool on = state.mode == m;
        return ListTile(
          minTileHeight: 64,
          leading: Icon(icon, color: on ? c.accent : c.textSecondary),
          title: Text(title, style: MayosTypography.body),
          subtitle: Text(sub, style: MayosTypography.caption),
          trailing:
              on ? Icon(Icons.check_circle, color: c.accent) : null,
          selected: on,
          onTap: () {
            state.switchMode(m);
            Navigator.of(context).pop();
          },
        );
      }

      return SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Row(children: <Widget>[
              Text('ahmed_h', style: MayosTypography.sectionHeading),
              const Spacer(),
              Text('Switch mode', style: MayosTypography.caption),
            ]),
          ),
          modeRow(ProtoMode.player, Icons.fitness_center, 'Player mode',
              state.playerOnboarded ? 'Your own training' : 'Set up your own training'),
          modeRow(ProtoMode.coach, Icons.groups_outlined, 'Coach mode',
              '${state.players.length} players · ${state.openAlerts().where((ProtoAlert a) => a.state == 'new').length} new alerts'),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('Settings'),
            onTap: () => Navigator.of(context).pop(),
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Log out'),
            onTap: () => Navigator.of(context).pop(),
          ),
        ]),
      );
    },
  );
}

// ─── Player mode stub ───────────────────────────────────────────────────────

/// Stand-in for the real PlayerShell, only to show the switch round-trip and
/// the deferred player onboarding for a coach who never set up training.
class ProtoPlayerModeStub extends StatelessWidget {
  const ProtoPlayerModeStub({super.key, required this.state});
  final ProtoCoachState state;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    if (!state.playerOnboarded) {
      return Padding(
        padding: MayosSpacing.screen,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Icon(Icons.fitness_center, size: 40, color: c.accent),
            const SizedBox(height: 16),
            Text('Set up your own training',
                textAlign: TextAlign.center, style: MayosTypography.pageHeading),
            const SizedBox(height: 8),
            Text(
                'Player mode needs a short intake before it can build your program. '
                'Your coaching stays as it is.',
                textAlign: TextAlign.center,
                style: MayosTypography.bodySecondary),
            const SizedBox(height: 24),
            MayosButton(
                label: 'Start intake (stub)',
                onPressed: state.finishPlayerOnboarding),
            const SizedBox(height: 8),
            MayosButton(
                label: 'Back to Coach mode',
                variant: MayosButtonVariant.tertiary,
                onPressed: () => state.switchMode(ProtoMode.coach)),
          ],
        ),
      );
    }
    return ListView(padding: MayosSpacing.screen, children: <Widget>[
      Text('Player mode', style: MayosTypography.caption),
      Text('Next session · Upper A', style: MayosTypography.pageHeading),
      const SizedBox(height: 16),
      const MayosCard(
          child: Text('(The real Home · Program · Progress shell goes here.)')),
    ]);
  }
}

// ─── Attention chips ────────────────────────────────────────────────────────

class ProtoChip extends StatelessWidget {
  const ProtoChip(this.text, {super.key, required this.color, this.icon});
  final String text;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: MayosRadii.pillRadius,
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
        if (icon != null) ...<Widget>[
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 3),
        ],
        Text(text,
            style: MayosTypography.caption
                .copyWith(color: color, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

List<Widget> attentionChips(
    BuildContext context, ProtoCoachState s, ProtoPlayer p) {
  final MayosThemeExtension c = MayosTheme.of(context);
  final int newAlerts = s
      .openAlerts(p.assignmentId)
      .where((ProtoAlert a) => a.state == 'new')
      .length;
  final int reqs = s.pendingRequests(p.assignmentId).length;
  return <Widget>[
    if (p.missedStreak > 0)
      ProtoChip('Missed ${p.missedStreak}d',
          color: c.danger, icon: Icons.event_busy),
    if (s.followUpDue(p))
      ProtoChip(
          p.nextFollowUpOn == today ? 'Follow-up today' : 'Follow-up overdue',
          color: c.warning,
          icon: Icons.phone_callback_outlined),
    if (newAlerts > 0)
      ProtoChip('$newAlerts alert${newAlerts == 1 ? '' : 's'}',
          color: c.danger, icon: Icons.notifications_active_outlined),
    if (reqs > 0)
      ProtoChip('$reqs request${reqs == 1 ? '' : 's'}',
          color: c.accent, icon: Icons.swap_horiz),
  ];
}

// ─── Roster row ─────────────────────────────────────────────────────────────

class ProtoRosterRow extends StatelessWidget {
  const ProtoRosterRow({super.key, required this.state, required this.player});
  final ProtoCoachState state;
  final ProtoPlayer player;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<Widget> chips = attentionChips(context, state, player);
    return InkWell(
      onTap: () => openPlayer(context, state, player),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        child: Row(children: <Widget>[
          CircleAvatar(
            radius: 20,
            backgroundColor: c.secondarySurface,
            child: Text(player.username.substring(0, 1).toUpperCase(),
                style: MayosTypography.label.copyWith(color: c.textPrimary)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(player.username, style: MayosTypography.exerciseTitle),
                  const SizedBox(height: 2),
                  Text(
                      'Last workout ${player.lastWorkoutOn ?? '—'} · ${player.programName}',
                      style: MayosTypography.caption
                          .copyWith(color: c.textSecondary)),
                  if (chips.isNotEmpty) ...<Widget>[
                    const SizedBox(height: 6),
                    Wrap(spacing: 6, runSpacing: 4, children: chips),
                  ],
                ]),
          ),
          Icon(Icons.chevron_right, color: c.textMuted),
        ]),
      ),
    );
  }
}

// ─── Alert tile ─────────────────────────────────────────────────────────────

IconData alertIcon(String kind) => switch (kind) {
      'missed_day' => Icons.event_busy,
      'follow_up_due' => Icons.phone_callback_outlined,
      'deload' => Icons.battery_2_bar,
      _ => Icons.trending_down,
    };

class ProtoAlertTile extends StatelessWidget {
  const ProtoAlertTile(
      {super.key,
      required this.state,
      required this.alert,
      this.showPlayer = true});
  final ProtoCoachState state;
  final ProtoAlert alert;
  final bool showPlayer;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProtoPlayer p = state.player(alert.assignmentId);
    final bool isNew = alert.state == 'new';
    return MayosCard(
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
      borderColor: isNew ? c.danger.withValues(alpha: 0.5) : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
        Row(children: <Widget>[
          Icon(alertIcon(alert.kind), size: 20, color: isNew ? c.danger : c.textSecondary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
                showPlayer ? '${p.username} · ${alert.title}' : alert.title,
                style: MayosTypography.body.copyWith(fontWeight: FontWeight.w600)),
          ),
          if (!isNew) ProtoChip(alert.state, color: c.textMuted),
        ]),
        Padding(
          padding: const EdgeInsets.only(left: 28, top: 2),
          child: Text(alert.detail,
              style: MayosTypography.caption.copyWith(color: c.textSecondary)),
        ),
        Wrap(alignment: WrapAlignment.end, children: <Widget>[
          if (showPlayer)
            TextButton(
                onPressed: () => openPlayer(context, state, p),
                child: const Text('Open player')),
          if (alert.kind == 'follow_up_due')
            TextButton(
                onPressed: () => showCheckInSheet(context, state, p),
                child: const Text('Log check-in')),
          if (isNew)
            TextButton(
                onPressed: () => state.acknowledge(alert),
                child: const Text('Acknowledge')),
          TextButton(
              onPressed: () => state.resolve(alert),
              child: const Text('Resolve')),
        ]),
      ]),
    );
  }
}

// ─── Request card + resolve sheet ───────────────────────────────────────────

String requestTitle(ProtoRequest r) => r.kind == 'exercise_substitution'
    ? '${r.fromExercise} → ${r.toExercise}'
    : 'Split change → ${r.toExercise}';

class ProtoRequestCard extends StatelessWidget {
  const ProtoRequestCard(
      {super.key,
      required this.state,
      required this.request,
      this.showPlayer = true});
  final ProtoCoachState state;
  final ProtoRequest request;
  final bool showPlayer;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProtoPlayer p = state.player(request.assignmentId);
    final bool pending = request.status == 'pending';
    return MayosCard(
      onTap: pending ? () => showResolveSheet(context, state, request) : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
        Row(children: <Widget>[
          Icon(request.kind == 'exercise_substitution'
              ? Icons.swap_horiz
              : Icons.calendar_view_week, size: 20, color: c.accent),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
                showPlayer
                    ? '${p.username}${request.dayName == null ? '' : ' · ${request.dayName}'}'
                    : (request.dayName ?? 'Whole program'),
                style: MayosTypography.caption.copyWith(color: c.textSecondary)),
          ),
          ProtoChip(request.status,
              color: switch (request.status) {
                'pending' => c.accent,
                'applied' => c.success,
                _ => c.textMuted,
              }),
        ]),
        const SizedBox(height: 6),
        Text(requestTitle(request), style: MayosTypography.exerciseTitle),
        const SizedBox(height: 4),
        Text('“${request.reason}”', style: MayosTypography.bodySecondary),
        if (request.response != null) ...<Widget>[
          const SizedBox(height: 6),
          Text('You: ${request.response}',
              style: MayosTypography.caption.copyWith(color: c.textSecondary)),
        ],
        if (pending) ...<Widget>[
          const SizedBox(height: 4),
          Text('Sent ${request.createdAt} · tap to review',
              style: MayosTypography.caption.copyWith(color: c.textMuted)),
        ],
      ]),
    );
  }
}

Future<void> showResolveSheet(
    BuildContext context, ProtoCoachState state, ProtoRequest r) {
  final TextEditingController note = TextEditingController();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) {
      final MayosThemeExtension c = MayosTheme.of(context);
      final ProtoPlayer p = state.player(r.assignmentId);
      String? text() => note.text.trim().isEmpty ? null : note.text.trim();
      return Padding(
        padding: EdgeInsets.fromLTRB(
            20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
        child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('${p.username} asks', style: MayosTypography.caption),
              Text(requestTitle(r), style: MayosTypography.sectionHeading),
              if (r.dayName != null)
                Text('${r.dayName} · program v3',
                    style: MayosTypography.caption.copyWith(color: c.textSecondary)),
              const SizedBox(height: 8),
              Text('“${r.reason}”', style: MayosTypography.bodySecondary),
              const SizedBox(height: 16),
              TextField(
                controller: note,
                maxLength: 500,
                decoration: const InputDecoration(
                    labelText: 'Reply to the player (optional)'),
              ),
              const SizedBox(height: 8),
              MayosButton(
                  label: r.kind == 'exercise_substitution'
                      ? 'Apply swap'
                      : 'Apply (rebuilds program)',
                  onPressed: () {
                    state.apply(r, text());
                    Navigator.of(context).pop();
                  }),
              const SizedBox(height: 8),
              MayosButton(
                  label: 'Decline',
                  variant: MayosButtonVariant.secondary,
                  onPressed: () {
                    state.decline(r, text());
                    Navigator.of(context).pop();
                  }),
            ]),
      );
    },
  );
}

// ─── Check-in sheet ─────────────────────────────────────────────────────────

Future<void> showCheckInSheet(
    BuildContext context, ProtoCoachState state, ProtoPlayer p) {
  String channel = 'call';
  final TextEditingController note = TextEditingController();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) => StatefulBuilder(
      builder: (BuildContext context, StateSetter set) => Padding(
        padding: EdgeInsets.fromLTRB(
            20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
        child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('Check-in with ${p.username}',
                  style: MayosTypography.sectionHeading),
              const SizedBox(height: 12),
              Wrap(spacing: 8, children: <Widget>[
                for (final String ch in <String>['call', 'message', 'in_person', 'other'])
                  ChoiceChip(
                      label: Text(ch.replaceAll('_', ' ')),
                      selected: channel == ch,
                      onSelected: (_) => set(() => channel = ch)),
              ]),
              TextField(
                  controller: note,
                  decoration: const InputDecoration(labelText: 'Note (optional)')),
              const SizedBox(height: 16),
              MayosButton(
                  label: 'Save check-in · today',
                  onPressed: () {
                    state.addCheckIn(p, channel,
                        note.text.trim().isEmpty ? null : note.text.trim());
                    Navigator.of(context).pop();
                  }),
            ]),
      ),
    ),
  );
}

// ─── Player drill-down ──────────────────────────────────────────────────────

void openPlayer(BuildContext context, ProtoCoachState state, ProtoPlayer p) {
  Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => ProtoPlayerDetail(state: state, player: p)));
}

/// One player: attention strip on top, then History · Check-ins · Requests.
/// In the real app History is the existing CoachPlayerHistoryScreen.
class ProtoPlayerDetail extends StatefulWidget {
  const ProtoPlayerDetail({super.key, required this.state, required this.player});
  final ProtoCoachState state;
  final ProtoPlayer player;

  @override
  State<ProtoPlayerDetail> createState() => _ProtoPlayerDetailState();
}

class _ProtoPlayerDetailState extends State<ProtoPlayerDetail> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProtoCoachState s = widget.state;
    final ProtoPlayer p = widget.player;
    return ListenableBuilder(
      listenable: s,
      builder: (BuildContext context, _) {
        final List<ProtoAlert> alerts = s.openAlerts(p.assignmentId);
        final int pending = s.pendingRequests(p.assignmentId).length;
        final List<String> tabs = <String>[
          'History',
          'Check-ins',
          pending > 0 ? 'Requests · $pending' : 'Requests',
        ];
        return MayosScaffold(
          title: p.username,
          showBack: true,
          actions: <Widget>[
            IconButton(
                tooltip: 'Log check-in',
                onPressed: () => showCheckInSheet(context, s, p),
                icon: const Icon(Icons.add_comment_outlined)),
          ],
          body: ListView(padding: const EdgeInsets.only(bottom: 32), children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                  '${p.programName} · coached since ${p.startedAt} · next follow-up ${p.nextFollowUpOn ?? 'not set'}',
                  style: MayosTypography.caption.copyWith(color: c.textSecondary)),
            ),
            if (alerts.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(children: <Widget>[
                  for (final ProtoAlert a in alerts)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: ProtoAlertTile(state: s, alert: a, showPlayer: false),
                    ),
                ]),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: SegmentedButton<int>(
                showSelectedIcon: false,
                segments: <ButtonSegment<int>>[
                  for (int i = 0; i < tabs.length; i++)
                    ButtonSegment<int>(value: i, label: Text(tabs[i])),
                ],
                selected: <int>{_tab},
                onSelectionChanged: (Set<int> v) => setState(() => _tab = v.first),
              ),
            ),
            ...switch (_tab) {
              0 => _history(c, p),
              1 => _checkIns(c, s, p),
              _ => _requests(s, p),
            },
          ]),
        );
      },
    );
  }

  List<Widget> _history(MayosThemeExtension c, ProtoPlayer p) => <Widget>[
        _section('Recent sessions'),
        for (final (String, String, String) r in p.recentSessions)
          ListTile(
            title: Text('${r.$2} · ${r.$1}'),
            subtitle: Text(r.$3),
            trailing: const Icon(Icons.chevron_right),
          ),
        _section('Personal records'),
        if (p.prs.isEmpty)
          const ListTile(title: Text('No records yet')),
        for (final (String, String) pr in p.prs)
          ListTile(title: Text(pr.$1), trailing: Text(pr.$2)),
        _section('Exercises'),
        const ListTile(
            title: Text('All exercises →'),
            subtitle: Text('Per-exercise history (existing screen)')),
      ];

  List<Widget> _checkIns(MayosThemeExtension c, ProtoCoachState s, ProtoPlayer p) {
    final List<ProtoCheckIn> list = s.checkInsOf(p.assignmentId);
    return <Widget>[
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: MayosButton(
            label: 'Log check-in',
            icon: Icons.add,
            variant: MayosButtonVariant.secondary,
            onPressed: () => showCheckInSheet(context, s, p)),
      ),
      if (list.isEmpty) const ListTile(title: Text('No check-ins yet')),
      for (final ProtoCheckIn ci in list)
        ListTile(
          leading: const Icon(Icons.forum_outlined),
          title: Text('${ci.on} · ${ci.channel.replaceAll('_', ' ')}'),
          subtitle: ci.note == null ? null : Text(ci.note!),
        ),
    ];
  }

  List<Widget> _requests(ProtoCoachState s, ProtoPlayer p) {
    final List<ProtoRequest> list = s.requestsOf(p.assignmentId);
    return <Widget>[
      if (list.isEmpty) const ListTile(title: Text('No program requests')),
      for (final ProtoRequest r in list)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: ProtoRequestCard(state: s, request: r, showPlayer: false),
        ),
    ];
  }

  Widget _section(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
        child: Text(t, style: MayosTypography.sectionHeading),
      );
}

// ─── Coach profile (shared tab content) ─────────────────────────────────────

class ProtoCoachProfile extends StatelessWidget {
  const ProtoCoachProfile({super.key, required this.state});
  final ProtoCoachState state;

  @override
  Widget build(BuildContext context) {
    return ListView(padding: MayosSpacing.screen, children: <Widget>[
      Text('Coach profile', style: MayosTypography.pageHeading),
      const SizedBox(height: 12),
      const MayosCard(
          child: Text('Display name · bio · capacity 5 / 8 players\n'
              '(existing CoachProfileScreen)')),
      const SizedBox(height: 12),
      MayosButton(
          label: 'Invite a player',
          icon: Icons.person_add_alt,
          onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Invite code MAY-4821 (stub)')))),
      const SizedBox(height: 12),
      const ListTile(title: Text('Notices'), trailing: Text('2 unread')),
      const ListTile(title: Text('Resolved alerts'), trailing: Icon(Icons.chevron_right)),
    ]);
  }
}

// ─── Bottom bar with count badges ───────────────────────────────────────────

class ProtoNavItem {
  const ProtoNavItem(this.label, this.icon, this.selectedIcon, [this.badge = 0]);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final int badge;
}

/// Same restrained look as MayosBottomNavigation, plus a count badge.
class ProtoNavBar extends StatelessWidget {
  const ProtoNavBar(
      {super.key, required this.items, required this.index, required this.onSelected});
  final List<ProtoNavItem> items;
  final int index;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
          color: c.surface, border: Border(top: BorderSide(color: c.border))),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 62,
          child: Row(children: <Widget>[
            for (int i = 0; i < items.length; i++)
              Expanded(
                child: InkResponse(
                  onTap: () => onSelected(i),
                  containedInkWell: true,
                  highlightShape: BoxShape.rectangle,
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: <Widget>[
                    Badge(
                      isLabelVisible: items[i].badge > 0,
                      label: Text('${items[i].badge}'),
                      backgroundColor: c.danger,
                      child: Icon(i == index ? items[i].selectedIcon : items[i].icon,
                          color: i == index ? c.accent : c.textMuted),
                    ),
                    const SizedBox(height: 3),
                    Text(items[i].label,
                        maxLines: 1,
                        style: MayosTypography.caption.copyWith(
                            color: i == index ? c.accent : c.textMuted,
                            fontWeight: i == index ? FontWeight.w600 : FontWeight.w500)),
                  ]),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}
