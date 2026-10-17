import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_assistant_screen.dart';
import 'coach_roster_assistant_panel.dart';
import 'coach_roster_loader.dart';

/// The Coach shell's Assistant tab (#309), with the existing one-player
/// assistant available for active assignments.
class CoachAssistantTabScreen extends ConsumerStatefulWidget {
  const CoachAssistantTabScreen({super.key});

  @override
  ConsumerState<CoachAssistantTabScreen> createState() =>
      _CoachAssistantTabScreenState();
}

class _CoachAssistantTabScreenState
    extends ConsumerState<CoachAssistantTabScreen> with WidgetsBindingObserver {
  String? _selectedAssignmentId;
  FailureMessage? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadAssignments();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refreshAssignments();
  }

  Future<void> _loadAssignments() => _requestRoster(
        ref.read(coachRosterLoaderProvider).load,
      );

  Future<void> _refreshAssignments() => _requestRoster(
        ref.read(coachRosterLoaderProvider).refresh,
      );

  Future<void> _requestRoster(
    Future<List<CoachRosterEntry>?> Function() loadRoster,
  ) async {
    if (!mounted) return;
    setState(() => _error = null);
    try {
      await loadRoster();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = apiFailureMessage(error));
    }
  }

  CoachRosterEntry? get _selectedAssignment {
    final String? selectedId = _selectedAssignmentId;
    if (selectedId == null) return null;
    final List<CoachRosterEntry> assignments = _activeAssignments(
      ref.read(coachRosterEntriesProvider) ?? <CoachRosterEntry>[],
    );
    for (final CoachRosterEntry row in assignments) {
      if (row.assignmentId == selectedId) return row;
    }
    return null;
  }

  void _selectAssignment(String assignmentId) {
    setState(() => _selectedAssignmentId = assignmentId);
  }

  void _openAssistant() {
    final CoachRosterEntry? entry = _selectedAssignment;
    if (entry == null) return;
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachAssistantScreen(entry: entry),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    ref.listen<int>(coachRosterRevisionProvider, (int? previous, int next) {
      if (previous != next) _refreshAssignments();
    });
    ref.listen<List<CoachRosterEntry>?>(coachRosterEntriesProvider,
        (List<CoachRosterEntry>? previous, List<CoachRosterEntry>? next) {
      final String? selectedId = _selectedAssignmentId;
      if (selectedId != null &&
          !_activeAssignments(next ?? <CoachRosterEntry>[]).any(
            (CoachRosterEntry row) => row.assignmentId == selectedId,
          )) {
        setState(() => _selectedAssignmentId = null);
      }
    });

    final List<CoachRosterEntry>? roster =
        ref.watch(coachRosterEntriesProvider);
    final int? cacheRevision = ref.watch(coachRosterEntriesRevisionProvider);
    final int rosterRevision = ref.watch(coachRosterRevisionProvider);
    final List<CoachRosterEntry> assignments = _activeAssignments(
      roster ?? <CoachRosterEntry>[],
    );
    final bool rosterReady = roster != null && cacheRevision == rosterRevision;
    final Account? account =
        ref.watch(authControllerProvider).session?.account;
    final CoachCopy copy = coachCopyOf(context);
    final String? error =
        _error == null ? null : displayCopyOf(context).failureMessage(_error!);
    return _assistantTab(
      copy,
      error,
      MayosTheme.of(context),
      assignments,
      rosterReady,
      account?.coachRosterAiEnabled ?? false,
      account?.coachAiEnabled ?? false,
      account?.coachRosterAiAvailable ?? false,
      account?.coachAiAllowance,
    );
  }

  Widget _assistantTab(
    CoachCopy copy,
    String? error,
    MayosThemeExtension colors,
    List<CoachRosterEntry> assignments,
    bool rosterReady,
    bool rosterAiEnabled,
    bool playerAiEnabled,
    bool coachPro,
    AiAllowance? coachAllowance,
  ) =>
      SingleChildScrollView(
        padding: const EdgeInsets.all(MayosSpacing.lg),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                if (coachAllowance != null)
                  CoachAllowanceNotice(allowance: coachAllowance),
                CoachRosterAssistantPanel(
                  enabled: rosterAiEnabled,
                  coachPro: coachPro,
                  assignments: assignments,
                ),
                _playerAssistantSection(
                  copy,
                  colors,
                  error,
                  assignments,
                  rosterReady,
                  playerAiEnabled,
                ),
              ],
            ),
          ),
        ),
      );

  Widget _playerAssistantSection(
    CoachCopy copy,
    MayosThemeExtension colors,
    String? error,
    List<CoachRosterEntry> assignments,
    bool rosterReady,
    bool playerAiEnabled,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(copy.askAboutOnePlayer,
              style: MayosTypography.of(context).sectionHeading),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            copy.assistantPickerLead,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: colors.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          if (!playerAiEnabled)
            _disabledState(copy.coachAiDisabled)
          else
            _playerControls(copy, error, assignments, rosterReady),
        ],
      );

  Widget _playerControls(
    CoachCopy copy,
    String? error,
    List<CoachRosterEntry> assignments,
    bool rosterReady,
  ) {
    if (error != null) return _loadError(error, copy);
    if (!rosterReady) return _loadingIndicator(copy);
    if (assignments.isEmpty) return Text(copy.noAssignedPlayers);
    return _assignmentPicker(copy, assignments);
  }

  Widget _loadingIndicator(CoachCopy copy) => Column(
        children: <Widget>[
          const CircularProgressIndicator(),
          const SizedBox(height: MayosSpacing.sm),
          Text(copy.loadingPlayers),
        ],
      );

  Widget _assignmentPicker(
    CoachCopy copy,
    List<CoachRosterEntry> assignments,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _assignmentDropdown(copy, assignments),
          const SizedBox(height: MayosSpacing.md),
          _openPlayerButton(copy),
        ],
      );

  Widget _assignmentDropdown(
    CoachCopy copy,
    List<CoachRosterEntry> assignments,
  ) {
    final String? selectedId = assignments.any(
      (CoachRosterEntry entry) => entry.assignmentId == _selectedAssignmentId,
    )
        ? _selectedAssignmentId
        : null;
    final String rosterKey = assignments
        .map((CoachRosterEntry entry) => entry.assignmentId)
        .join(',');
    return DropdownButtonFormField<String>(
      key: ValueKey<String>(
        'coach_assistant_player_picker:$rosterKey:${selectedId ?? ''}',
      ),
      initialValue: selectedId,
      decoration: InputDecoration(
        labelText: copy.chooseAssignedPlayer,
        border: const OutlineInputBorder(),
      ),
      items: <DropdownMenuItem<String>>[
        for (final CoachRosterEntry entry in assignments)
          DropdownMenuItem<String>(
            value: entry.assignmentId,
            child: Text(entry.playerUsername),
          ),
      ],
      onChanged: (String? assignmentId) {
        if (assignmentId != null) _selectAssignment(assignmentId);
      },
    );
  }

  Widget _openPlayerButton(CoachCopy copy) => MayosButton(
        key: const Key('coach_assistant_open_player'),
        label: copy.openPlayerAssistant,
        icon: Icons.auto_awesome_outlined,
        onPressed: _selectedAssignment == null ? null : _openAssistant,
      );

  Widget _disabledState(String message) => Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.lg),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: MayosCard(
              key: const Key('coach_ai_disabled'),
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  Icons.info_outline,
                  color: MayosTheme.of(context).textSecondary,
                ),
                title: Text(message),
              ),
            ),
          ),
        ),
      );

  Widget _loadError(String message, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(message),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            label: copy.retry,
            variant: MayosButtonVariant.secondary,
            onPressed: _refreshAssignments,
          ),
        ],
      );

  List<CoachRosterEntry> _activeAssignments(
    List<CoachRosterEntry> assignments,
  ) =>
      assignments
          .where((CoachRosterEntry entry) => entry.status == 'active')
          .toList(growable: false);
}
