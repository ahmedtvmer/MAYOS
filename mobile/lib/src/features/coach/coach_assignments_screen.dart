import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_card_table.dart';
import '../../core/ui/mayos_phone_tap_target.dart';
import '../../providers.dart';
import '../../router.dart';
import 'coach_roster_loader.dart';
import 'coach_shared.dart';

/// Coach-side roster (#24): the assigned players in the order the service
/// returns them, with their urgency chips, revocation, and coaching controls.
/// Tapping a roster card opens the player page (#120).
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
  bool _loadingStalledFilter = false;
  bool _stalledFilterSelected = false;
  FailureMessage? _error;
  String? _busyAssignmentId;
  List<CoachRosterEntry> _assignments = <CoachRosterEntry>[];
  Set<String> _stalledAssignmentIds = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadCached();
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
  Future<void> _load({bool showLoader = true}) => _requestRoster(
        ref.read(coachRosterLoaderProvider).refresh,
        showLoader: showLoader,
      );

  Future<void> _loadCached() => _requestRoster(
        ref.read(coachRosterLoaderProvider).load,
        showLoader: false,
      );

  Future<void> _requestRoster(
    Future<List<CoachRosterEntry>?> Function() loadRoster, {
    required bool showLoader,
  }) async {
    if (showLoader) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final List<CoachRosterEntry>? assignments = await loadRoster();
      if (!mounted || assignments == null) return;
      final FailureMessage? signalError = await _refreshStalledSnapshot();
      if (!mounted) return;
      setState(() {
        _assignments = assignments;
        _loading = false;
        _error = signalError;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  Future<FailureMessage?> _refreshStalledSnapshot() async {
    if (!_stalledFilterSelected) return null;
    try {
      final CoachRosterSignalSnapshot signals = await ref
          .read(apiClientProvider)
          .coachRosterSignalSnapshot();
      _stalledAssignmentIds = signals.stalledAssignmentIds;
      return null;
    } on ApiException catch (error) {
      _stalledAssignmentIds = <String>{};
      return apiFailureMessage(error);
    }
  }

  Future<void> _selectStalledFilter() async {
    setState(() {
      _stalledFilterSelected = true;
      _loadingStalledFilter = true;
      _stalledAssignmentIds = <String>{};
      _error = null;
    });
    final FailureMessage? error = await _refreshStalledSnapshot();
    if (!mounted) return;
    setState(() {
      _loadingStalledFilter = false;
      if (error != null) {
        _stalledFilterSelected = false;
        _error = error;
      }
    });
  }

  void _selectAllFilter() {
    setState(() {
      _stalledFilterSelected = false;
      _loadingStalledFilter = false;
    });
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
      ref.read(coachRosterLoaderProvider).publish(_assignments);
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
      ref.read(coachRosterAssistantControllerProvider.notifier).clear();
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

  double _rosterActionsWidth(BuildContext context, String label) {
    final ButtonStyle style =
        TextButtonTheme.of(context).style ?? const ButtonStyle();
    const Set<WidgetState> states = <WidgetState>{};
    final TextStyle textStyle = style.textStyle?.resolve(states) ??
        Theme.of(context).textTheme.labelLarge!;
    final EdgeInsetsGeometry padding = style.padding?.resolve(states) ??
        const EdgeInsets.symmetric(horizontal: MayosSpacing.xs);
    final double minimumWidth =
        style.minimumSize?.resolve(states)?.width ?? kMayosMinTapTarget;
    final TextPainter labelPainter = TextPainter(
      text: TextSpan(text: label, style: textStyle),
      textDirection: Directionality.of(context),
      textScaler: MediaQuery.textScalerOf(context),
      locale: Localizations.maybeLocaleOf(context),
      maxLines: 1,
    )..layout();
    final double labelAndPaddingWidth = labelPainter.width + padding.horizontal;
    final double buttonWidth = labelAndPaddingWidth > minimumWidth
        ? labelAndPaddingWidth
        : minimumWidth;
    final double chevronWidth =
        IconTheme.of(context).size ?? MayosIconSizes.navigation;
    return buttonWidth + chevronWidth;
  }

  /// Desktop roster chips for missed days, follow-ups, new alerts and requests.
  /// Phone cards show attendance and follow-up as labelled fields.
  List<Widget> _rosterChips(
    BuildContext context,
    CoachRosterEntry entry, {
    bool includeAttendance = true,
    bool includeFollowUp = true,
  }) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final String? followUp = _followUpStatus(context, entry);
    return <Widget>[
      if (includeAttendance && entry.currentMissedStreak > 0)
        coachPillChip(
            context, copy.missedDays(entry.currentMissedStreak), c.danger),
      if (entry.stallLength > 0)
        coachPillChip(
          context,
          copy.stalledSessions(entry.stallLength),
          c.warning,
        ),
      if (includeFollowUp && followUp != null)
        coachPillChip(context, followUp, c.warning),
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

  String? _followUpStatus(BuildContext context, CoachRosterEntry entry) {
    final String? dueOn = entry.nextFollowUpOn;
    if (dueOn == null) return null;
    final String today = isoDateOf(DateTime.now());
    if (dueOn.compareTo(today) > 0) return null;
    final CoachCopy copy = coachCopyOf(context);
    return dueOn == today ? copy.followUpToday : copy.followUpOverdue;
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
          child: LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              const double avatarRadius = 20;
              final bool busy = _busyAssignmentId == entry.assignmentId;
              final String actionLabel = busy ? copy.revoking : copy.revoke;
              final Widget avatar = CircleAvatar(
                radius: avatarRadius,
                backgroundColor: c.secondarySurface,
                child: Text(
                  entry.playerUsername.isEmpty
                      ? '?'
                      : entry.playerUsername.substring(0, 1).toUpperCase(),
                  style: MayosTypography.of(context).label
                      .copyWith(color: c.textPrimary),
                ),
              );
              final Widget details = Column(
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
              );
              final Widget actions = Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  MayosButton(
                    label: actionLabel,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : () => _revoke(entry),
                  ),
                  Icon(
                    Icons.chevron_right,
                    color: c.textMuted,
                  ),
                ],
              );
              final double inlineWidth =
                  avatarRadius * 2 +
                  MayosSpacing.md +
                  MayosLayout.coachRosterRowMinimumDetailsWidth +
                  MayosSpacing.xs +
                  _rosterActionsWidth(context, actionLabel);
              final bool narrowDesktopPane =
                  constraints.maxWidth < inlineWidth;
              if (narrowDesktopPane) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        avatar,
                        const SizedBox(width: MayosSpacing.md),
                        Expanded(child: details),
                      ],
                    ),
                    const SizedBox(height: MayosSpacing.xs),
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: actions,
                    ),
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  avatar,
                  const SizedBox(width: MayosSpacing.md),
                  Expanded(child: details),
                  const SizedBox(width: MayosSpacing.xs),
                  actions,
                ],
              );
            },
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
        crossAxisAlignment: isDesktopLayout(context)
            ? CrossAxisAlignment.start
            : CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(copy.activeAssignments,
              style: MayosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          _rosterFilters(context, copy),
          const SizedBox(height: MayosSpacing.xs),
          _assignmentRows(context, c, copy),
        ],
      ),
    );
  }

  Widget _rosterFilters(BuildContext context, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _filterOptions(copy),
          _stalledFilterProgress(),
        ],
      );

  Widget _filterOptions(CoachCopy copy) => Wrap(
        spacing: MayosSpacing.xs,
        children: <Widget>[
          _filterChip(
            context: context,
            key: const Key('roster_filter_all'),
            label: copy.allPlayers,
            selected: !_stalledFilterSelected,
            onSelected: (_) => _selectAllFilter(),
          ),
          _filterChip(
            context: context,
            key: const Key('roster_filter_stalled'),
            label: copy.stalledFilter,
            selected: _stalledFilterSelected,
            onSelected: _loadingStalledFilter
                ? null
                : (_) => _selectStalledFilter(),
          ),
        ],
      );

  Widget _filterChip({
    required BuildContext context,
    required Key key,
    required String label,
    required bool selected,
    required ValueChanged<bool>? onSelected,
  }) => mayosPhoneTapTarget(context, ChoiceChip(
        key: key,
        label: Text(label),
        selected: selected,
        onSelected: onSelected,
      ));

  Widget _stalledFilterProgress() {
    if (!_loadingStalledFilter) return const SizedBox.shrink();
    return const Padding(
      padding: EdgeInsets.only(top: MayosSpacing.xs),
      child: LinearProgressIndicator(),
    );
  }

  Widget _assignmentRows(
    BuildContext context,
    MayosThemeExtension colors,
    CoachCopy copy,
  ) {
    if (_assignments.isEmpty) {
      return _emptyAssignments(context, colors, copy.noAssignedPlayers);
    }
    if (_visibleAssignments.isEmpty) {
      return _emptyAssignments(context, colors, copy.noStalledPlayers);
    }
    return _assignmentRowList(context, colors);
  }

  Widget _emptyAssignments(
    BuildContext context,
    MayosThemeExtension colors,
    String message,
  ) => Padding(
        padding: EdgeInsets.only(
          top: _assignments.isEmpty ? 0 : MayosSpacing.sm,
        ),
        child: Text(
          message,
          style: MayosTypography.of(context)
              .bodySecondary
              .copyWith(color: colors.textSecondary),
        ),
      );

  Widget _assignmentRowList(
    BuildContext context,
    MayosThemeExtension colors,
  ) {
    return MayosCardTable(
      columns: <String>[
        coachCopyOf(context).player,
        coachCopyOf(context).rosterAlertsLabel,
        coachCopyOf(context).rosterAttendance,
        coachCopyOf(context).rosterFollowUpStatusLabel,
        coachCopyOf(context).rosterNextFollowUpLabel,
      ],
      rows: <MayosCardTableRow>[
        for (final CoachRosterEntry entry in _visibleAssignments)
          MayosCardTableRow(
            key: Key('roster_row_${entry.assignmentId}'),
            cells: <Widget?>[
              Text(entry.playerUsername),
              _rosterAlertCell(context, entry),
              Text(coachCopyOf(context)
                  .rosterAttendanceStatus(entry.currentMissedStreak)),
              _followUpUrgency(context, entry),
              Text(coachCopyOf(context).rosterNextFollowUp(entry.nextFollowUpOn)),
            ],
            subtitle: Text(
              coachCopyOf(context).rosterSubtitle(
                lastWorkout: entry.lastWorkoutOn,
                program: entry.programName,
              ),
              style: MayosTypography.of(context).caption
                  .copyWith(color: colors.textSecondary),
            ),
            onTap: () => context.go(
              coachAssignmentLocation(entry.assignmentId),
              extra: entry,
            ),
            actions: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                MayosButton(
                  key: Key('roster_revoke_${entry.assignmentId}'),
                  label: _busyAssignmentId == entry.assignmentId
                      ? coachCopyOf(context).revoking
                      : coachCopyOf(context).revoke,
                  variant: MayosButtonVariant.tertiary,
                  expand: false,
                  onPressed: _busyAssignmentId == entry.assignmentId
                      ? null
                      : () => _revoke(entry),
                ),
                Icon(
                  Icons.chevron_right,
                  color: colors.textMuted,
                ),
              ],
            ),
          ),
      ],
      desktopTable: Column(
        children: <Widget>[
          for (int i = 0; i < _visibleAssignments.length; i++) ...<Widget>[
            if (i > 0) Divider(height: 1, indent: 52, color: colors.border),
            _rosterRow(context, _visibleAssignments[i]),
          ],
        ],
      ),
    );
  }

  Widget? _rosterAlertCell(BuildContext context, CoachRosterEntry entry) {
    final List<Widget> chips = _rosterChips(
      context,
      entry,
      includeAttendance: false,
      includeFollowUp: false,
    );
    if (chips.isEmpty) return null;
    return Wrap(
      spacing: MayosSpacing.xs,
      runSpacing: MayosSpacing.xs,
      children: chips,
    );
  }

  Widget? _followUpUrgency(BuildContext context, CoachRosterEntry entry) {
    final String? status = _followUpStatus(context, entry);
    return status == null ? null : Text(status);
  }

  List<CoachRosterEntry> get _visibleAssignments => _stalledFilterSelected
      ? _assignments
          .where((CoachRosterEntry row) =>
              _stalledAssignmentIds.contains(row.assignmentId))
          .toList(growable: false)
      : _assignments;

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    // A coaching action landed elsewhere (the player page's alert buttons or
    // check-in sheet, the Alerts tab): refetch quietly so this row's chips
    // track it without a restart (#120). Producers bump the revision; this
    // tab never does, so the listener cannot loop.
    ref.listen<int>(coachRosterRevisionProvider, (int? previous, int next) {
      if (previous != next) _load(showLoader: false);
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
