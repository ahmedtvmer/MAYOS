import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_player_history_screen.dart';

/// Coach-side roster (#24): the assigned players with their alert badges,
/// revocation, and coaching controls. Tapping a roster row opens the assigned
/// player's history drill-down (#25).
///
/// It is the Roster tab of the Coach mode shell (#119); the player invite and
/// notices live on the Profile tab.
class CoachAssignmentsScreen extends ConsumerStatefulWidget {
  const CoachAssignmentsScreen({super.key});

  @override
  ConsumerState<CoachAssignmentsScreen> createState() =>
      _CoachAssignmentsScreenState();
}

class _CoachAssignmentsScreenState extends ConsumerState<CoachAssignmentsScreen>
    with WidgetsBindingObserver {
  bool _loading = true;
  bool _disabling = false;
  String? _error;
  String? _busyAssignmentId;
  List<CoachRosterEntry> _assignments = <CoachRosterEntry>[];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Grants and revocations happen elsewhere: a return to the foreground
  /// refreshes the roster so a lost assignment drops its assistant transcript
  /// before the coach can reopen it (issue #45).
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _load(showLoader: false);
    }
  }

  /// [showLoader] blanks the list while fetching; the background refreshes
  /// (app resume, drill-down return) keep the current rows until data lands.
  Future<void> _load({bool showLoader = true}) async {
    if (showLoader) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final List<CoachRosterEntry> assignments =
          await ref.read(apiClientProvider).coachAssignments();
      if (!mounted) return;
      setState(() {
        _assignments = assignments;
        _loading = false;
      });
      // The refreshed roster is the authority on what is still assigned: an
      // assignment that vanished ends the coach assistant's in-memory
      // transcript for it (issue #45).
      ref
          .read(coachAssistantControllerProvider.notifier)
          .clearUnlessAssigned(<String>[
        for (final CoachRosterEntry row in assignments) row.assignmentId,
      ]);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _revoke(CoachRosterEntry entry) async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Revoke assignment?'),
        content: Text(
            '${entry.playerUsername} will lose coaching immediately and can no longer be seen by you.'),
        actions: <Widget>[
          MayosButton(
            label: 'Cancel',
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: 'Revoke',
            expand: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busyAssignmentId = entry.assignmentId;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).revokeAssignment(entry.assignmentId);
      if (!mounted) return;
      setState(() {
        _busyAssignmentId = null;
        // The revoke response is the committed truth; drop the row locally.
        _assignments = _assignments
            .where((CoachRosterEntry row) =>
                row.assignmentId != entry.assignmentId)
            .toList(growable: false);
      });
      // Revocation ends the assistant's in-memory context for that player too
      // (issue #45): no further question can be asked about them.
      ref
          .read(coachAssistantControllerProvider.notifier)
          .clearFor(entry.assignmentId);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Revoked ${entry.playerUsername}.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busyAssignmentId = null;
        _error = error.message;
      });
    }
  }

  Future<void> _disable() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Disable coaching?'),
        content: const Text(
            'Every assignment ends immediately and your coach capability is removed. '
            'Your own player training data is kept.'),
        actions: <Widget>[
          MayosButton(
            label: 'Cancel',
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: 'Disable coaching',
            expand: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _disabling = true;
      _error = null;
    });
    try {
      final int ended =
          await ref.read(apiClientProvider).disableCoachCapability();
      if (!mounted) return;
      setState(() => _disabling = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text('Coaching disabled. $ended assignment(s) ended.')),
      );
      ref.read(authControllerProvider.notifier).markCoachDisabled();
      // Every assignment just ended: no assistant context survives it (#45).
      ref.read(coachAssistantControllerProvider.notifier).clear();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _disabling = false;
        _error = error.message;
      });
    }
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Text(
        _error!,
        style: MayosTypography.bodySecondary
            .copyWith(color: MayosTheme.of(context).danger),
      ),
    );
  }

  Widget _badge(String label, Color color, Color foreground) {
    return Container(
      padding:
          const EdgeInsets.symmetric(horizontal: MayosSpacing.xs, vertical: 2),
      decoration: BoxDecoration(
        color: color,
        borderRadius: MayosRadii.pillRadius,
      ),
      child: Text(
        label,
        style: MayosTypography.caption.copyWith(color: foreground),
      ),
    );
  }

  Widget _rosterBadges(BuildContext context, CoachRosterEntry entry) {
    if (entry.alertsOpen == 0) {
      return const SizedBox.shrink();
    }
    final MayosThemeExtension tokens = MayosTheme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (entry.alertsNew > 0)
          _badge('${entry.alertsNew}', tokens.danger, tokens.onDanger),
        if (entry.alertsNew > 0 && entry.alertsAcknowledged > 0)
          const SizedBox(width: 4),
        if (entry.alertsAcknowledged > 0)
          _badge(
              '${entry.alertsAcknowledged}', tokens.warning, tokens.onWarning),
      ],
    );
  }

  Widget _assignmentsCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Active assignments',
              style:
                  MayosTypography.sectionHeading.copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          if (_assignments.isEmpty)
            Text('No assigned players yet.',
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textSecondary))
          else
            for (final CoachRosterEntry entry in _assignments)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.person_outline, color: c.textSecondary),
                title: Text(entry.playerUsername),
                subtitle: Text('Since ${entry.startedAt}'),
                onTap: () async {
                  await Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (BuildContext context) =>
                          CoachPlayerHistoryScreen(entry: entry),
                    ),
                  );
                  // The drill-down (and the assistant under it) is closed:
                  // reload the roster, since a revocation may have landed
                  // while it was open (issue #45).
                  if (mounted) {
                    await _load(showLoader: false);
                  }
                },
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    _rosterBadges(context, entry),
                    const SizedBox(width: MayosSpacing.xs),
                    MayosButton(
                      label: _busyAssignmentId == entry.assignmentId
                          ? 'Revoking…'
                          : 'Revoke',
                      variant: MayosButtonVariant.tertiary,
                      expand: false,
                      onPressed: _busyAssignmentId == entry.assignmentId
                          ? null
                          : () => _revoke(entry),
                    ),
                  ],
                ),
              ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        _errorBanner(context),
        _assignmentsCard(context),
        const SizedBox(height: MayosSpacing.xl),
        MayosButton(
          label: 'Disable coaching',
          icon: Icons.logout,
          variant: MayosButtonVariant.secondary,
          loading: _disabling,
          onPressed: _disabling ? null : _disable,
        ),
      ],
    );
  }
}
