import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/message_resolver.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_segmented_control.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../providers.dart';
import '../../router.dart';
import 'coach_assistant_screen.dart';
import 'coach_check_in_sheet.dart';
import 'coach_history_segment.dart';
import 'coach_program_card.dart';
import 'coach_program_draft_screen.dart';
import 'program_import_files.dart';
import 'program_import_screen.dart';
import 'coach_request_sheet.dart';
import 'coach_shared.dart';
import 'program_publish_confirmation.dart';

/// The player page (#120): one assigned player's open coach alerts on top,
/// then the **Program · History · Check-ins · Requests** segments.
///
/// History carries sessions, volume, personal records, Checkpoints, and
/// per-exercise history in collapsible sections. Every read is gated by the
/// active assignment server-side, so a revoked or foreign assignment yields a
/// denial and no training data.
/// Player-assistant chats never appear here.
class CoachPlayerHistoryScreen extends ConsumerStatefulWidget {
  const CoachPlayerHistoryScreen({
    super.key,
    required this.assignmentId,
    this.entry,
  });

  final CoachRosterEntry? entry;
  final String assignmentId;

  @override
  ConsumerState<CoachPlayerHistoryScreen> createState() =>
      _CoachPlayerHistoryScreenState();
}

class _GenerateDraftRequest {
  const _GenerateDraftRequest({
    required this.split,
    required this.repPreference,
    required this.frequency,
  });

  final String split;
  final String repPreference;
  final int frequency;

  Map<String, dynamic> toJson() => <String, dynamic>{
        if (split.isNotEmpty) 'user_split_override': split,
        'rep_preference_override': repPreference,
        'frequency_override': frequency,
      };
}

class _GenerateDraftDialog extends StatefulWidget {
  const _GenerateDraftDialog();

  @override
  State<_GenerateDraftDialog> createState() => _GenerateDraftDialogState();
}

class _GenerateDraftDialogState extends State<_GenerateDraftDialog> {
  final TextEditingController _split = TextEditingController();
  String _repPreference = 'balanced';
  int _frequency = 4;

  @override
  void dispose() {
    _split.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final copy = coachCopyOf(context);
    return AlertDialog(
      title: Text(copy.generateDraft),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          TextField(
            key: const Key('generate_draft_split_field'),
            controller: _split,
            decoration: InputDecoration(
              labelText: copy.split,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.md),
          DropdownButtonFormField<String>(
            key: const Key('generate_draft_rep_field'),
            initialValue: _repPreference,
            decoration: InputDecoration(
              labelText: copy.repRangePreference,
              border: const OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<String>>[
              DropdownMenuItem<String>(value: 'low', child: Text(copy.low)),
              DropdownMenuItem<String>(
                value: 'balanced',
                child: Text(copy.balanced),
              ),
              DropdownMenuItem<String>(value: 'high', child: Text(copy.high)),
            ],
            onChanged: (String? value) => setState(
              () => _repPreference = value ?? _repPreference,
            ),
          ),
          const SizedBox(height: MayosSpacing.md),
          DropdownButtonFormField<int>(
            key: const Key('generate_draft_frequency_field'),
            initialValue: _frequency,
            decoration: InputDecoration(
              labelText: copy.daysPerWeek,
              border: const OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<int>>[
              for (int day = 1; day <= 5; day++)
                DropdownMenuItem<int>(
                  value: day,
                  child: Text('$day', textDirection: TextDirection.ltr),
                ),
            ],
            onChanged: (int? value) => setState(
              () => _frequency = value ?? _frequency,
            ),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(copy.cancel),
        ),
        MayosButton(
          key: const Key('generate_draft_confirm_button'),
          label: copy.generate,
          expand: false,
          onPressed: () => Navigator.of(context).pop(
            _GenerateDraftRequest(
              split: _split.text.trim(),
              repPreference: _repPreference,
              frequency: _frequency,
            ),
          ),
        ),
      ],
    );
  }
}

class _CoachPlayerHistoryScreenState
    extends ConsumerState<CoachPlayerHistoryScreen> {
  late CoachRosterEntry _entry;
  bool _loading = true;
  FailureMessage? _error;
  bool _assignmentDenied = false;
  CoachPlayerSummary? _summary;
  CoachActiveProgram? _activeProgram;
  List<PersonalRecord> _records = const <PersonalRecord>[];
  List<CheckpointReviewListItem> _checkpointReviews =
      const <CheckpointReviewListItem>[];
  List<CoachPlayerExercise> _exercises = const <CoachPlayerExercise>[];
  final Map<String, CoachExerciseHistory> _histories =
      <String, CoachExerciseHistory>{};
  String? _openExerciseId;
  bool _loadingHistory = false;
  bool _generatingDraft = false;
  FailureMessage? _generateError;
  bool _copyingActiveProgram = false;
  bool _approvingActiveProgram = false;
  bool _downloadingProgramTemplate = false;
  FailureMessage? _programActionError;
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  FailureMessage? _requestError;
  List<CheckIn> _checkIns = const <CheckIn>[];
  String? _nextFollowUpOn;
  List<CoachAlert> _alerts = const <CoachAlert>[];
  String? _busyAlertId;
  _PlayerSegment _segment = _PlayerSegment.history;
  final Map<CoachHistorySection, bool> _expandedHistorySections =
      <CoachHistorySection, bool>{};

  /// Sequence numbers so a slower, older response can never overwrite the
  /// result of a newer one when revision bumps start overlapping loads (#120).
  int _loadSeq = 0;
  int _alertsSeq = 0;
  int _requestsSeq = 0;

  @override
  void initState() {
    super.initState();
    _entry = _routeEntry();
    _nextFollowUpOn = _entry.nextFollowUpOn;
    _load();
  }

  CoachRosterEntry _routeEntry() =>
      widget.entry ??
      CoachRosterEntry(
        assignmentId: widget.assignmentId,
        playerUsername: '',
        startedAt: '',
        status: 'active',
      );

  /// This assignment's open (new or acknowledged) alerts, as the player page
  /// shows them (#120).
  List<CoachAlert> _openAlerts(Iterable<CoachAlert> alerts) => alerts
      .where((CoachAlert alert) => alert.assignmentId == _entry.assignmentId)
      .toList(growable: false);

  Future<void> _load() async {
    final int seq = ++_loadSeq;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      await _loadRouteEntry(api, seq);
      if (!mounted || seq != _loadSeq) return;
      final List<Object> playerData = await _loadPlayerData(api);
      if (!mounted || seq != _loadSeq) return;
      _applyPlayerData(playerData);
    } on ApiException catch (error) {
      _showLoadError(error, seq);
    }
  }

  Future<void> _loadRouteEntry(ApiClient api, int seq) async {
    if (widget.entry != null) return;
    final List<CoachRosterEntry> roster = await api.coachAssignments();
    if (!mounted || seq != _loadSeq) return;
    for (final CoachRosterEntry row in roster) {
      if (row.assignmentId == widget.assignmentId) {
        _entry = row;
        break;
      }
    }
    if (mounted && seq == _loadSeq) {
      setState(() => _nextFollowUpOn = _entry.nextFollowUpOn);
    }
  }

  Future<List<Object>> _loadPlayerData(ApiClient api) =>
      Future.wait<Object>(<Future<Object>>[
        api.coachAlerts(states: <String>['new', 'acknowledged']),
        api.coachPlayerSummary(_entry.assignmentId),
        api.coachPlayerPersonalRecords(_entry.assignmentId),
        api.coachCheckpointReviews(_entry.assignmentId),
        api.coachPlayerExercises(_entry.assignmentId),
        api.coachProgramRequests(_entry.assignmentId),
        api.coachCheckIns(_entry.assignmentId),
        api.coachActiveProgram(_entry.assignmentId),
      ]);

  void _applyPlayerData(List<Object> playerData) {
    setState(() {
      _alerts = _openAlerts(playerData[0] as List<CoachAlert>);
      _summary = playerData[1] as CoachPlayerSummary;
      _records = playerData[2] as List<PersonalRecord>;
      _checkpointReviews = playerData[3] as List<CheckpointReviewListItem>;
      _exercises = playerData[4] as List<CoachPlayerExercise>;
      _programRequests =
          sortCoachRequests(playerData[5] as List<ProgramRequest>);
      _checkIns = sortCheckInsNewestFirst(playerData[6] as List<CheckIn>);
      _activeProgram = playerData[7] as CoachActiveProgram;
      _loading = false;
      _assignmentDenied = false;
      _requestError = null;
    });
  }

  void _showLoadError(ApiException error, int seq) {
    if (!mounted || seq != _loadSeq) return;
    if (error.statusCode == 403) {
      ref
          .read(coachAssistantControllerProvider.notifier)
          .clearFor(_entry.assignmentId);
    }
    setState(() {
      _loading = false;
      _assignmentDenied = error.statusCode == 403;
      _error = error.statusCode == 403 ? null : apiFailureMessage(error);
    });
  }

  /// Refetches only the open alerts: saving a check-in can resolve a
  /// follow-up on the service side, and the page must show that (#120).
  Future<void> _loadAlerts() async {
    final int seq = ++_alertsSeq;
    try {
      final List<CoachAlert> alerts = await ref
          .read(apiClientProvider)
          .coachAlerts(states: <String>['new', 'acknowledged']);
      if (!mounted || seq != _alertsSeq) return;
      setState(() => _alerts = _openAlerts(alerts));
    } on ApiException {
      // Keep the alerts already on screen; the Alerts tab refetches its own
      // copy from the revision bump this save published.
    }
  }

  /// Refetches only this assignment's program requests: a refused resolve
  /// must refresh the list so a request answered elsewhere shows its true
  /// state (#121), without blanking the whole page.
  Future<void> _loadRequests() async {
    final int seq = ++_requestsSeq;
    try {
      final List<ProgramRequest> requests = sortCoachRequests(await ref
          .read(apiClientProvider)
          .coachProgramRequests(_entry.assignmentId));
      if (!mounted || seq != _requestsSeq) return;
      setState(() {
        _programRequests = requests;
        _requestError = null;
      });
    } on ApiException catch (error) {
      if (!mounted || seq != _requestsSeq) return;
      // A failed refresh is surfaced like every other load error (#121).
      setState(() => _requestError = apiFailureMessage(error));
    }
  }

  Future<void> _toggleExercise(CoachPlayerExercise exercise) async {
    if (_openExerciseId == exercise.id) {
      setState(() => _openExerciseId = null);
      return;
    }
    setState(() {
      _openExerciseId = exercise.id;
      _loadingHistory = true;
    });
    if (_histories.containsKey(exercise.id)) {
      setState(() => _loadingHistory = false);
      return;
    }
    try {
      final CoachExerciseHistory history = await ref
          .read(apiClientProvider)
          .coachPlayerExerciseHistory(_entry.assignmentId, exercise.id);
      if (!mounted) return;
      setState(() {
        _histories[exercise.id] = history;
        _loadingHistory = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingHistory = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  Future<void> _openGenerateDraftDialog() async {
    final _GenerateDraftRequest? request = await showDialog<_GenerateDraftRequest>(
      context: context,
      builder: (BuildContext context) => const _GenerateDraftDialog(),
    );
    if (request == null || !mounted) return;
    await _generateDraft(request);
  }

  Future<void> _generateDraft(_GenerateDraftRequest request) async {
    setState(() {
      _generatingDraft = true;
      _generateError = null;
    });
    try {
      try {
        await ref.read(apiClientProvider).coachGenerateProgramDraft(
              _entry.assignmentId,
              generationOverrides: request.toJson(),
            );
      } on ApiException catch (error) {
        if (error.statusCode != 409) rethrow;
        final bool replace = await _confirmProgramDraftReplacement();
        if (!mounted || !replace) return;
        await ref.read(apiClientProvider).coachReplaceGeneratedProgramDraft(
              _entry.assignmentId,
              generationOverrides: request.toJson(),
            );
      }
      if (!mounted) return;
      _openProgramDraft();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _generateError = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _generatingDraft = false);
    }
  }

  Future<bool> _confirmProgramDraftReplacement() async {
    final copy = coachCopyOf(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text(copy.replaceProgramDraftTitle),
            content: Text(copy.replaceProgramDraftPrompt),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(copy.cancel),
              ),
              TextButton(
                key: const Key('generate_draft_replace_confirm'),
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(copy.replaceProgramDraftAction),
              ),
            ],
          ),
        ) ??
        false;
  }

  /// Opens the resolve sheet and runs the shared post-resolve flow (#121):
  /// snackbar, the Requests badge and roster chip revisions, the page's own
  /// refresh, and — on a refusal (an already-answered request, a stale
  /// target) — the readable message it refreshes from.
  Future<void> _resolveRequest(ProgramRequest request) async {
    setState(() => _requestError = null);
    final CoachRequestResolution result = await showCoachRequestResolveSheet(
      context,
      request: request,
      playerUsername: _entry.playerUsername,
    );
    if (!mounted) return;
    await applyCoachRequestAction(
      ref,
      context: context,
      result: result,
      // An applied request republishes the program, so the whole page
      // refetches; a refusal only needs this segment's list back.
      reload: () => result.resolved ? _load() : _loadRequests(),
      showError: (FailureMessage failure) =>
          setState(() => _requestError = failure),
      // The Requests tab listens on its revision and republishes the badge.
      notifyRequestsTab: true,
    );
  }

  /// The header **Log check-in** action and the Check-ins segment's button
  /// open the same sheet (#120): channel, optional note, dated today.
  Future<void> _openCheckInSheet() async {
    await showLogCheckInSheet(
      context,
      assignmentId: _entry.assignmentId,
      playerUsername: _entry.playerUsername,
      onSaved: _onCheckInSaved,
    );
  }

  /// Saves land here: the check-in list and the next follow-up update
  /// immediately, the open alerts are refetched (the service may resolve the
  /// follow-up this check-in satisfied), and both the Alerts tab badge and the
  /// roster row are told to refetch (#120).
  void _onCheckInSaved(CheckInCreation created) {
    if (!mounted) return;
    setState(() {
      _checkIns =
          sortCheckInsNewestFirst(<CheckIn>[created.checkIn, ..._checkIns]);
      if (created.nextFollowUpOn != null) {
        _nextFollowUpOn = created.nextFollowUpOn;
      }
    });
    _loadAlerts();
    ref.read(coachAlertsRevisionProvider.notifier).state++;
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(coachCopyOf(context).checkInRecorded)),
    );
  }

  /// Acknowledge / resolve through the existing alert client calls, then
  /// publish the shared badge and revision updates and drop a resolved alert
  /// from the open list (#120).
  Future<void> _applyAlert(
    CoachAlert alert,
    Future<CoachAlert> Function() action,
  ) async {
    setState(() => _busyAlertId = alert.alertId);
    try {
      final CoachAlert updated = await applyCoachAlertAction(
        ref,
        action,
        wasNew: alert.isNew,
      );
      if (!mounted) return;
      setState(() {
        _busyAlertId = null;
        _alerts = updated.isResolved
            ? _alerts
                .where((CoachAlert row) => row.alertId != updated.alertId)
                .toList(growable: false)
            : _alerts
                .map((CoachAlert row) =>
                    row.alertId == updated.alertId ? updated : row)
                .toList(growable: false);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _busyAlertId = null);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            displayCopyOf(context).failureMessage(apiFailureMessage(error)),
          ),
        ),
      );
    }
  }

  Widget _checkInsSegment(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          copy.nextFollowUpLabel(_nextFollowUpOn),
          style: MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: MayosButton(
            key: const Key('record_check_in_button'),
            label: copy.logCheckIn,
            icon: Icons.note_add_outlined,
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: _openCheckInSheet,
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (_checkIns.isEmpty)
          Text(
            copy.noRecordedCheckIns,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final CheckIn checkIn in _checkIns)
            MayosSettingsTile(
              key: Key('check_in_${checkIn.checkInId}'),
              icon: Icons.forum_outlined,
              title: copy.checkInTitle(
                checkIn.checkedInOn,
                copy.checkInChannel(checkIn.channel),
              ),
              subtitle: checkIn.note == null || checkIn.note!.isEmpty
                  ? null
                  : checkIn.note!,
            ),
      ],
    );
  }

  /// The **Requests (count)** segment (#121): this assignment's program
  /// requests in the tab's order, with the shared resolve sheet. A pending
  /// row opens the sheet; answered rows are read-only.
  Widget _requestsSegment(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: copy.programRequests),
        if (_requestError != null) ...<Widget>[
          Text(
            displayCopyOf(context).failureMessage(_requestError!),
            style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_programRequests.isEmpty)
          Text(
            copy.noProgramRequests,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final ProgramRequest request in _programRequests)
            CoachRequestCard(
              request: request,
              playerUsername: _entry.playerUsername,
              onTap: () => _resolveRequest(request),
            ),
      ],
    );
  }

  Widget _programCard(BuildContext context) {
    return CoachProgramCard(
      active: _activeProgram!,
      busyState: (
        generatingDraft: _generatingDraft,
        copyingActiveProgram: _copyingActiveProgram,
        approvingActiveProgram: _approvingActiveProgram,
        downloadingProgramTemplate: _downloadingProgramTemplate,
      ),
      actionError: _programActionError == null
          ? null
          : displayCopyOf(context).failureMessage(_programActionError!),
      callbacks: (
        writeProgram: _openProgramDraft,
        generateDraft: _openGenerateDraftDialog,
        importProgram: _openProgramImport,
        downloadTemplate: _downloadProgramTemplate,
        editActiveProgram: _editActiveProgram,
        approveActiveProgram: _approveActiveProgramAsIs,
      ),
    );
  }

  Future<void> _openProgramImport() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachProgramImportScreen(
          assignmentId: _entry.assignmentId,
          playerUsername: _entry.playerUsername,
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _downloadProgramTemplate() => runProgramTemplateDownload(
        ref: ref,
        extension: 'xlsx',
        onBusyChanged: (bool busy) =>
            setState(() => _downloadingProgramTemplate = busy),
        isMounted: () => mounted,
        onFailure: (FailureMessage message) =>
            setState(() => _programActionError = message),
        onDownloaded: () => ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(coachCopyOf(context).importTemplateSaved)),
        ),
      );

  /// The segment label counts what still needs the coach (#121): the pending
  /// requests, or no number once nothing is waiting.
  int get _pendingRequests => _programRequests
      .where((ProgramRequest request) => request.isPending)
      .length;

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    final CoachRosterEntry entry = _entry;
    final copy = coachCopyOf(context);
    final bool assistantEnabled =
        ref.watch(authControllerProvider).session?.account.coachAiEnabled ??
            false;
    final bool phoneAssignmentRoute = !isDesktopLayout(context);
    return PopScope<void>(
      onPopInvokedWithResult: (bool didPop, _) {
        if (didPop) {
          ref.read(coachRosterRevisionProvider.notifier).state++;
        }
      },
      child: Scaffold(
        appBar: AppBar(
          key: const Key('coach_player_history_app_bar'),
          automaticallyImplyLeading: false,
          leading: phoneAssignmentRoute
              ? BackButton(
                  onPressed: () {
                    if (GoRouter.of(context).canPop()) {
                      context.pop();
                    } else {
                      ref.read(coachRosterRevisionProvider.notifier).state++;
                      context.go(coachRosterPath);
                    }
                  },
                )
              : null,
          title: Text(entry.playerUsername),
          actions: _assignmentDenied
              ? const <Widget>[]
              : <Widget>[
                  TextButton(
                    key: const Key('log_check_in_action'),
                    onPressed: _loading ? null : _openCheckInSheet,
                    child: Text(copy.logCheckInAction),
                  ),
                  if (assistantEnabled)
                    IconButton(
                      key: const Key('coach_assistant_entry'),
                      tooltip: copy.askAssistant,
                      icon: const Icon(Icons.auto_awesome_outlined),
                      onPressed: _openAssistant,
                    ),
                ],
        ),
        body: Column(
          children: <Widget>[
            const OfflineBannerSlot(),
            Expanded(child: _buildBody(context)),
          ],
        ),
      ),
    );
  }

  /// Opens the in-memory coach assistant for this one player (#45). The entry
  /// exists only when the service reports the feature enabled.
  void _openAssistant() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachAssistantScreen(entry: _entry),
      ),
    );
  }

  void _openProgramDraft() {
    Navigator.of(context)
        .push<CoachProgramPublication>(
      MaterialPageRoute<CoachProgramPublication>(
        builder: (BuildContext context) => CoachProgramDraftScreen(
          assignmentId: _entry.assignmentId,
          playerUsername: _entry.playerUsername,
        ),
      ),
    )
        .then((CoachProgramPublication? publication) async {
      if (!mounted) return;
      if (publication != null) {
        ref.read(coachRosterRevisionProvider.notifier).state++;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              coachCopyOf(context).programPublished(
                publication.program.version,
                resolvedRequestCount: publication.resolvedRequestIds.length,
              ),
            ),
          ),
        );
      }
      await _load();
    });
  }

  Future<void> _editActiveProgram() async {
    final CoachActiveProgram? active = _activeProgram;
    if (active?.program == null) return;
    final _ExistingDraftChoice? choice = active!.hasDraft
        ? await _chooseExistingDraftAction()
        : _ExistingDraftChoice.copyActive;
    if (!mounted || choice == null) return;
    if (choice == _ExistingDraftChoice.continueDraft) {
      _openProgramDraft();
      return;
    }
    await _copyActiveProgramDraft(
      replace: choice == _ExistingDraftChoice.replaceWithActive,
    );
  }

  Future<void> _copyActiveProgramDraft({bool replace = false}) async {
    setState(() {
      _copyingActiveProgram = true;
      _programActionError = null;
    });
    try {
      await ref.read(apiClientProvider).coachCopyActiveProgramToDraft(
            _entry.assignmentId,
            replace: replace,
          );
      if (mounted) _openProgramDraft();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _copyingActiveProgram = false);
    }
  }

  Future<_ExistingDraftChoice?> _chooseExistingDraftAction() =>
      showDialog<_ExistingDraftChoice>(
        context: context,
        builder: (BuildContext context) {
          final copy = coachCopyOf(context);
          return AlertDialog(
            title: Text(copy.programDraftChoiceTitle),
            content: Text(copy.programDraftChoicePrompt),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text(copy.cancel),
              ),
              TextButton(
                key: const Key('coach_program_continue_draft'),
                onPressed: () => Navigator.of(context)
                    .pop(_ExistingDraftChoice.continueDraft),
                child: Text(copy.continueProgramDraft),
              ),
              TextButton(
                key: const Key('coach_program_replace_draft'),
                onPressed: () => Navigator.of(context)
                    .pop(_ExistingDraftChoice.replaceWithActive),
                child: Text(copy.replaceDraftWithActiveProgram),
              ),
            ],
          );
        },
      );

  Future<void> _approveActiveProgramAsIs() async {
    final CoachActiveProgram? active = _activeProgram;
    final int? expectedVersion = active?.program?.version;
    if (expectedVersion == null) return;
    final ApiClient api = ref.read(apiClientProvider);
    final List<String>? resolveRequestIds =
        await _confirmApproveActiveProgram(api);
    if (!mounted) return;
    if (resolveRequestIds == null) return;
    await _publishActiveProgramAsIs(
      expectedVersion,
      resolveRequestIds: resolveRequestIds,
    );
  }

  Future<void> _publishActiveProgramAsIs(
    int expectedActiveVersion, {
    required List<String> resolveRequestIds,
  }) async {
    setState(() {
      _approvingActiveProgram = true;
      _programActionError = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final CoachProgramPublication published = await api.coachApproveActiveProgram(
        _entry.assignmentId,
        expectedActiveVersion: expectedActiveVersion,
        resolveRequestIds: resolveRequestIds,
      );
      if (mounted) await _showPublishedProgram(published);
    } on ApiException catch (error) {
      if (error.errorCode == 'program_version_mismatch') {
        await _load();
        if (mounted) {
          setState(
            () => _programActionError = const AppFailureMessage(
              AppFailureId.coachProgramChanged,
              "The player's program changed. Review it and approve again.",
            ),
          );
        }
      } else if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _approvingActiveProgram = false);
    }
  }

  Future<void> _showPublishedProgram(CoachProgramPublication published) async {
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          coachCopyOf(context).programPublished(
            published.program.version,
            resolvedRequestCount: published.resolvedRequestIds.length,
          ),
        ),
      ),
    );
    await _load();
  }

  Future<List<String>?> _confirmApproveActiveProgram(
    ApiClient api,
  ) async {
    final copy = coachCopyOf(context);
    return showProgramPublishConfirmation(
      context,
      api,
      _entry.assignmentId,
      ProgramPublishConfirmation(
        title: copy.confirmApproveProgramTitle,
        prompt: copy.approveProgramAsIsPrompt,
        confirmLabel: copy.confirmApproveProgram,
        cancelLabel: copy.cancel,
        confirmKey: 'coach_program_approve_confirm',
      ),
      onRequestsLoadError: (ApiException error) {
        if (mounted) {
          setState(() => _programActionError = apiFailureMessage(error));
        }
      },
    );
  }

  /// One open coach alert with its actions (#120): acknowledge and resolve
  /// through the existing alert client calls, plus **Log check-in** while a
  /// follow-up is due.
  Widget _alertCard(BuildContext context, CoachAlert alert) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final String description = resolveCoachAlertDescription(
      alert,
      displayCopyOf(context).languageCode,
    );
    final bool busy = _busyAlertId == alert.alertId;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('player_alert_${alert.alertId}'),
        borderColor: alert.isNew ? c.danger : c.border,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: FirstStrongDirection(
                    text: description,
                    child: Text(
                      description,
                      style:
                          MayosTypography.of(context).body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ),
                coachAlertStateChip(context, alert),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            Wrap(
              spacing: MayosSpacing.xs,
              runSpacing: MayosSpacing.xs,
              children: <Widget>[
                if (alert.isFollowUpDue)
                  MayosButton(
                    label: copy.logCheckInAction,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : _openCheckInSheet,
                  ),
                if (alert.isNew)
                  MayosButton(
                    label: copy.acknowledge,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy
                        ? null
                        : () => _applyAlert(
                              alert,
                              () => ref
                                  .read(apiClientProvider)
                                  .acknowledgeCoachAlert(alert.alertId),
                            ),
                  ),
                if (!alert.isResolved)
                  MayosButton(
                    label: copy.resolve,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    loading: busy,
                    onPressed: busy
                        ? null
                        : () => _applyAlert(
                              alert,
                              () => ref
                                  .read(apiClientProvider)
                                  .resolveCoachAlert(alert.alertId),
                            ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null || _assignmentDenied) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                  _assignmentDenied
                      ? copy.noActiveAssignment
                      : displayCopyOf(context).failureMessage(_error!),
                  textAlign: TextAlign.center,
                  style: MayosTypography.of(context).body.copyWith(color: c.textPrimary)),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: copy.retry,
                expand: false,
                onPressed: _load,
              ),
            ],
          ),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(MayosSpacing.md),
      children: <Widget>[
        if (_generateError != null) ...<Widget>[
          Text(
            displayCopyOf(context).failureMessage(_generateError!),
            style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        if (_alerts.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Text(copy.openAlerts,
              style: MayosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          for (final CoachAlert alert in _alerts) _alertCard(context, alert),
        ],
        const SizedBox(height: MayosSpacing.md),
        MayosSegmentedControl<_PlayerSegment>(
          segments: <MayosSegment<_PlayerSegment>>[
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.program,
              label: copy.program,
            ),
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.history,
              label: copy.history,
            ),
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.checkIns,
              label: copy.checkIns,
            ),
            MayosSegment<_PlayerSegment>(
              value: _PlayerSegment.requests,
              label: _pendingRequests > 0
                  ? copy.requestsWithCount(_pendingRequests)
                  : copy.requests,
            ),
          ],
          selected: _segment,
          onChanged: (_PlayerSegment value) => setState(() => _segment = value),
        ),
        const SizedBox(height: MayosSpacing.md),
        if (_segment == _PlayerSegment.program)
          _programCard(context)
        else if (_segment == _PlayerSegment.history)
          _historySegment(context)
        else if (_segment == _PlayerSegment.checkIns)
          _checkInsSegment(context)
        else
          _requestsSegment(context),
      ],
    );
  }

  Widget _historySegment(BuildContext context) {
    return CoachHistorySegment(
      data: CoachHistorySegmentData(
        summary: _summary!,
        records: _records,
        checkpointReviews: _checkpointReviews,
        exercises: _exercises,
        histories: _histories,
        openExerciseId: _openExerciseId,
        loadingHistory: _loadingHistory,
        expandedSections: _expandedHistorySections,
      ),
      onToggleSection: _toggleHistorySection,
      onExerciseToggle: _toggleExercise,
      onCheckpointTap: (CheckpointReviewListItem review) => context.push(
        '$checkpointReviewPath/${review.checkpoint}'
        '?assignment_id=${_entry.assignmentId}',
      ),
    );
  }

  void _toggleHistorySection(CoachHistorySection section) {
    setState(() {
      final bool expanded = _expandedHistorySections[section] ?? false;
      _expandedHistorySections[section] = !expanded;
    });
  }
}

/// The player page's segments (#120/#121).
enum _PlayerSegment {
  program,
  history,
  checkIns,
  requests,
}

enum _ExistingDraftChoice {
  copyActive,
  continueDraft,
  replaceWithActive,
}
