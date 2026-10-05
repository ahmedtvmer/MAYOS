import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import '../../router.dart';
import 'coach_shared.dart';

/// Coach-side roster (#24): the assigned players in the order the service
/// returns them, with their urgency chips, revocation, and coaching controls.
/// Tapping a roster row pushes the player page (#120).
///
/// It is the Roster tab of the Coach mode shell (#119); the player invite and
/// notices live on the Profile tab. The client never re-sorts: the server
/// computes the roster urgency order (#118), and the tab only reloads when
/// data changes (foreground return, drill-down return, or a coaching action
/// reported through [coachRosterRevisionProvider]).
class CoachAssignmentsScreen extends ConsumerStatefulWidget {
  const CoachAssignmentsScreen({super.key, this.selectedAssignmentId});

  final String? selectedAssignmentId;

  @override
  ConsumerState<CoachAssignmentsScreen> createState() =>
      _CoachAssignmentsScreenState();
}

class _CoachAssignmentsScreenState extends ConsumerState<CoachAssignmentsScreen>
    with WidgetsBindingObserver {
  bool _loading = true;
  bool _disabling = false;
  FailureMessage? _error;
  String? _busyAssignmentId;
  List<CoachRosterEntry> _assignments = <CoachRosterEntry>[];

  /// Bumped by every load so a slower, older response can never overwrite a
  /// newer one when revision bumps start overlapping loads (#120).
  int _loadSeq = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final List<CoachRosterEntry>? cached = ref.read(coachRosterEntriesProvider);
    final int? cacheRevision = ref.read(coachRosterEntriesRevisionProvider);
    if (cached == null ||
        cacheRevision != ref.read(coachRosterRevisionProvider)) {
      _load();
    } else {
      _assignments = cached;
      _loading = false;
      _publishRoster(cached);
    }
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
    final int seq = ++_loadSeq;
    if (showLoader) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final List<CoachRosterEntry> assignments =
          await ref.read(apiClientProvider).coachAssignments();
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _assignments = assignments;
        _loading = false;
      });
      ref.read(coachRosterEntriesProvider.notifier).state = assignments;
      ref.read(coachRosterEntriesRevisionProvider.notifier).state =
          ref.read(coachRosterRevisionProvider);
      _publishRoster(assignments);
    } on ApiException catch (error) {
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _loading = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  void _publishRoster(List<CoachRosterEntry> assignments) {
    // The refreshed roster is the authority on what is still assigned: an
    // assignment that vanished ends the coach assistant's in-memory
    // transcript for it (issue #45).
    ref.read(coachAssistantControllerProvider.notifier).clearUnlessAssigned(
      <String>[
        for (final CoachRosterEntry row in assignments) row.assignmentId,
      ],
    );
  }

  Future<void> _revoke(CoachRosterEntry entry) async {
    final copy = coachCopyOf(context);
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(copy.revokeAssignmentQuestion),
        content: Text(copy.revokeAssignmentLead(entry.playerUsername)),
        actions: <Widget>[
          MayosButton(
            label: copy.cancel,
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: copy.revoke,
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
      ref.read(coachRosterEntriesProvider.notifier).state = _assignments;
      // Revocation ends the assistant's in-memory context for that player too
      // (issue #45): no further question can be asked about them.
      ref
          .read(coachAssistantControllerProvider.notifier)
          .clearFor(entry.assignmentId);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(copy.assignmentRevoked(entry.playerUsername))),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busyAssignmentId = null;
        _error = apiFailureMessage(error);
      });
    }
  }

  Future<void> _disable() async {
    final copy = coachCopyOf(context);
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(copy.disableCoachingQuestion),
        content: Text(copy.disableCoachingLead),
        actions: <Widget>[
          MayosButton(
            label: copy.cancel,
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: copy.disableCoaching,
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
        SnackBar(content: Text(copy.coachingDisabled(ended))),
      );
      ref.read(authControllerProvider.notifier).markCoachDisabled();
      // Every assignment just ended: no assistant context survives it (#45).
      ref.read(coachAssistantControllerProvider.notifier).clear();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _disabling = false;
        _error = apiFailureMessage(error);
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
        displayCopyOf(context).failureMessage(_error!),
        style: MayosTypography.of(context).bodySecondary
            .copyWith(color: MayosTheme.of(context).danger),
      ),
    );
  }

  /// The chips as they apply (#120): missed days, a follow-up due today or
  /// overdue, new alerts, and pending program requests. Nothing renders when
  /// the player needs no attention.
  List<Widget> _rosterChips(BuildContext context, CoachRosterEntry entry) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final String today = isoDateOf(DateTime.now());
    final String? dueOn = entry.nextFollowUpOn;
    final String? followUp = dueOn == null || dueOn.compareTo(today) > 0
        ? null
        : dueOn == today
            ? copy.followUpToday
            : copy.followUpOverdue;
    return <Widget>[
      if (entry.currentMissedStreak > 0)
        coachPillChip(
            context, copy.missedDays(entry.currentMissedStreak), c.danger),
      if (entry.stallLength > 0)
        coachPillChip(
          context,
          copy.stalledSessions(entry.stallLength),
          c.warning,
        ),
      if (followUp != null) coachPillChip(context, followUp, c.warning),
      if (entry.alertsNew > 0)
        coachPillChip(
          context,
          copy.alertsCount(entry.alertsNew),
          c.danger,
        ),
      if (entry.pendingRequests > 0)
        coachPillChip(
          context,
          copy.requestsCount(entry.pendingRequests),
          c.accent,
        ),
    ];
  }

  /// One roster row: avatar, username, "Last workout · program", the urgency
  /// chips, and the revoke action. The whole row opens the player page.
  Widget _rosterRow(BuildContext context, CoachRosterEntry entry) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final List<Widget> chips = _rosterChips(context, entry);
    final bool selected = widget.selectedAssignmentId == entry.assignmentId;
    return Material(
      color: selected ? c.selectedSurface : Colors.transparent,
      child: InkWell(
        key: Key('roster_row_${entry.assignmentId}'),
        onTap: selected
            ? null
            : () {
                final String location =
                    coachAssignmentLocation(entry.assignmentId);
                context.go(location, extra: entry);
              },
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              CircleAvatar(
                radius: 20,
                backgroundColor: c.secondarySurface,
                child: Text(
                  entry.playerUsername.isEmpty
                      ? '?'
                      : entry.playerUsername.substring(0, 1).toUpperCase(),
                  style: MayosTypography.of(context).label.copyWith(color: c.textPrimary),
                ),
              ),
              const SizedBox(width: MayosSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      entry.playerUsername,
                      style: MayosTypography.of(context).exerciseTitle
                          .copyWith(color: c.textPrimary),
                    ),
                    const SizedBox(height: MayosSpacing.xxs),
                    Text(
                      copy.rosterSubtitle(
                        lastWorkout: entry.lastWorkoutOn,
                        program: entry.programName,
                      ),
                      style: MayosTypography.of(context).caption
                          .copyWith(color: c.textSecondary),
                    ),
                    if (chips.isNotEmpty) ...<Widget>[
                      const SizedBox(height: MayosSpacing.xs),
                      Wrap(
                        spacing: MayosSpacing.xs,
                        runSpacing: MayosSpacing.xs,
                        children: chips,
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: MayosSpacing.xs),
              MayosButton(
                label: _busyAssignmentId == entry.assignmentId
                    ? copy.revoking
                    : copy.revoke,
                variant: MayosButtonVariant.tertiary,
                expand: false,
                onPressed: _busyAssignmentId == entry.assignmentId
                    ? null
                    : () => _revoke(entry),
              ),
              Icon(
                Directionality.of(context) == TextDirection.rtl
                    ? Icons.chevron_left
                    : Icons.chevron_right,
                color: c.textMuted,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _assignmentsCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(copy.activeAssignments,
              style: MayosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          if (_assignments.isEmpty)
            Text(copy.noAssignedPlayers,
                style: MayosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary))
          else
            for (int i = 0; i < _assignments.length; i++) ...<Widget>[
              if (i > 0) Divider(height: 1, indent: 52, color: c.border),
              _rosterRow(context, _assignments[i]),
            ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    // A coaching action landed elsewhere (the player page's alert buttons or
    // check-in sheet, the Alerts tab): refetch quietly so this row's chips
    // track it without a restart (#120). Producers bump the revision; this
    // tab never does, so the listener cannot loop.
    ref.listen<int>(coachRosterRevisionProvider, (int? previous, int next) {
      if (previous != next) {
        _load(showLoader: false);
      }
    });
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
          label: coachCopyOf(context).disableCoaching,
          icon: Icons.logout,
          variant: MayosButtonVariant.secondary,
          loading: _disabling,
          onPressed: _disabling ? null : _disable,
        ),
      ],
    );
  }
}
