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
import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/myos_button.dart';
import '../../core/ui/myos_card.dart';
import '../../core/ui/myos_section_header.dart';
import '../../core/ui/myos_segmented_control.dart';
import '../../core/ui/myos_settings_tile.dart';
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
import 'program_template_save_sheet.dart';

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
    required this.splitId,
    required this.repPreference,
    required this.frequency,
    required this.cardioDays,
    required this.cardioMinutes,
    required this.cardioType,
    required this.cardioCustomNote,
  });

  final String splitId;
  final String repPreference;
  final int frequency;
  final int cardioDays;
  final int cardioMinutes;
  final String cardioType;
  final String? cardioCustomNote;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'split_id': splitId,
        'rep_preference_override': repPreference,
        'frequency_override': frequency,
        'cardio_days': cardioDays,
        'cardio_minutes': cardioMinutes,
        'cardio_type': cardioType,
        'cardio_custom_note': cardioCustomNote,
      };
}

class _GenerateDraftDialogOptions {
  const _GenerateDraftDialogOptions({
    required this.optionsByDays,
    required this.days,
    required this.splitId,
    required this.repPreference,
    required this.cardioDays,
    required this.cardioMinutes,
    required this.cardioType,
    required this.cardioCustomNote,
  });

  factory _GenerateDraftDialogOptions.fromDraft(
    Map<int, List<CoachProgramSplitOption>> optionsByDays,
    Map<String, dynamic>? draft,
  ) {
    final dynamic rawSavedOptions = draft?['generation_options'];
    final Map<String, dynamic>? savedOptions =
        rawSavedOptions is Map<String, dynamic> ? rawSavedOptions : null;
    final dynamic days =
        savedOptions?['days'] ?? draft?['weekly_frequency'];
    final dynamic splitId = savedOptions?['split_id'];
    final dynamic repPreference = savedOptions?['rep_preference'];
    final int selectedDays = _validDays(days);
    final int cardioDays = _validCardioDays(
      savedOptions?['cardio_days'],
      selectedDays,
    );
    final String cardioType = _validCardioType(
      savedOptions?['cardio_type'],
      cardioDays,
      savedOptions?['cardio_custom_note'],
    );
    return _GenerateDraftDialogOptions(
      optionsByDays: optionsByDays,
      days: selectedDays,
      splitId: splitId is String ? splitId : 'auto',
      repPreference: _validRepPreference(repPreference),
      cardioDays: cardioType == 'none' ? 0 : cardioDays,
      cardioMinutes: _validCardioMinutes(savedOptions?['cardio_minutes']),
      cardioType: cardioType,
      cardioCustomNote: savedOptions?['cardio_custom_note'] is String
          ? savedOptions!['cardio_custom_note'] as String
          : null,
    );
  }

  static int _validDays(dynamic days) =>
      days is num && days.toInt() >= 1 && days.toInt() <= 5
          ? days.toInt()
          : 4;

  static String _validRepPreference(dynamic preference) =>
      preference is String &&
              const <String>{'low', 'balanced', 'high'}.contains(preference)
          ? preference
          : 'balanced';

  static int _validCardioDays(dynamic days, int frequency) =>
      days is num && days.toInt() >= 0 && days.toInt() <= frequency
          ? days.toInt()
          : 0;

  static int _validCardioMinutes(dynamic minutes) =>
      minutes is num && minutes.toInt() >= 1 && minutes.toInt() <= 600
          ? minutes.toInt()
          : 20;

  static String _validCardioType(
    dynamic cardioType,
    int cardioDays,
    dynamic customNote,
  ) {
    const Set<String> accepted = <String>{
      'none',
      'steady',
      'intervals',
      'custom',
    };
    if (cardioType is! String || !accepted.contains(cardioType)) return 'none';
    if (cardioType != 'none' && cardioDays == 0) return 'none';
    if (cardioType == 'custom' &&
        (customNote is! String || customNote.trim().isEmpty)) {
      return 'none';
    }
    return cardioType;
  }

  final Map<int, List<CoachProgramSplitOption>> optionsByDays;
  final int days;
  final String splitId;
  final String repPreference;
  final int cardioDays;
  final int cardioMinutes;
  final String cardioType;
  final String? cardioCustomNote;
}

class _GenerateDraftResult {
  const _GenerateDraftResult({this.completed = false, this.failure});

  final bool completed;
  final FailureMessage? failure;
}

class _GenerateDraftDialog extends StatefulWidget {
  const _GenerateDraftDialog({
    required this.onGenerate,
    required this.options,
  });

  final Future<_GenerateDraftResult> Function(_GenerateDraftRequest request)
      onGenerate;
  final _GenerateDraftDialogOptions options;

  @override
  State<_GenerateDraftDialog> createState() => _GenerateDraftDialogState();
}

class _GenerateDraftDialogState extends State<_GenerateDraftDialog> {
  late String _splitId;
  late String _repPreference;
  late int _frequency;
  late int _cardioDays;
  late int _cardioMinutes;
  late String _cardioType;
  late final TextEditingController _cardioCustomNoteController;
  late final TextEditingController _cardioMinutesController;
  bool _submitting = false;
  FailureMessage? _failure;
  bool _customCardioNoteMissing = false;
  bool _cardioMinutesInvalid = false;

  @override
  void initState() {
    super.initState();
    _frequency = widget.options.days;
    _repPreference = widget.options.repPreference;
    _cardioDays = widget.options.cardioDays;
    _cardioMinutes = widget.options.cardioMinutes;
    _cardioType = widget.options.cardioType;
    _cardioCustomNoteController = TextEditingController(
      text: widget.options.cardioCustomNote ?? '',
    );
    _cardioMinutesController = TextEditingController(
      text: '$_cardioMinutes',
    );
    final List<CoachProgramSplitOption> optionsForDays =
        widget.options.optionsByDays[_frequency] ??
            const <CoachProgramSplitOption>[];
    _splitId = optionsForDays.any((CoachProgramSplitOption option) =>
            option.splitId == widget.options.splitId)
        ? widget.options.splitId
        : 'auto';
  }

  _GenerateDraftRequest? _requestFromFields() {
    final int? cardioMinutes = int.tryParse(_cardioMinutesController.text);
    if (!_validCardioMinutes(cardioMinutes)) return null;
    final String? customNote = _cardioType == 'custom'
        ? _cardioCustomNoteController.text
        : null;
    if (!_validCustomCardioNote(customNote)) return null;
    return _GenerateDraftRequest(
      splitId: _splitId,
      repPreference: _repPreference,
      frequency: _frequency,
      cardioDays: _cardioDays,
      cardioMinutes: cardioMinutes ?? _cardioMinutes,
      cardioType: _cardioType,
      cardioCustomNote: customNote,
    );
  }

  bool _validCardioMinutes(int? minutes) {
    if (_cardioDays == 0 ||
        (minutes != null && minutes >= 1 && minutes <= 600)) {
      return true;
    }
    setState(() => _cardioMinutesInvalid = true);
    return false;
  }

  bool _validCustomCardioNote(String? note) {
    if (_cardioDays == 0 ||
        _cardioType != 'custom' ||
        (note != null && note.trim().isNotEmpty)) {
      return true;
    }
    setState(() => _customCardioNoteMissing = true);
    return false;
  }

  Future<void> _submit() async {
    final _GenerateDraftRequest? request = _requestFromFields();
    if (request == null) return;
    setState(() {
      _submitting = true;
      _failure = null;
      _customCardioNoteMissing = false;
      _cardioMinutesInvalid = false;
    });
    await _runGeneration(request);
  }

  Future<void> _runGeneration(_GenerateDraftRequest request) async {
    late final _GenerateDraftResult result;
    try {
      result = await widget.onGenerate(request);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
    if (!mounted) return;
    setState(() => _failure = result.failure);
    if (result.completed) Navigator.of(context).pop(true);
  }

  @override
  void dispose() {
    _cardioCustomNoteController.dispose();
    _cardioMinutesController.dispose();
    super.dispose();
  }

  InputDecoration _cardioFieldDecoration(String label, {String? errorText}) =>
      InputDecoration(
        labelText: label,
        errorText: errorText,
        border: const OutlineInputBorder(),
      );

  List<DropdownMenuItem<String>> _cardioTypeOptions() {
    final copy = coachCopyOf(context);
    return <DropdownMenuItem<String>>[
      DropdownMenuItem<String>(value: 'none', child: Text(copy.noCardio)),
      DropdownMenuItem<String>(value: 'steady', child: Text(copy.steadyCardio)),
      DropdownMenuItem<String>(value: 'intervals', child: Text(copy.intervalCardio)),
      DropdownMenuItem<String>(value: 'custom', child: Text(copy.customCardioNote)),
    ];
  }

  Widget _cardioTypeField() => DropdownButtonFormField<String>(
        key: const Key('generate_draft_cardio_type_field'),
        initialValue: _cardioType,
        decoration: _cardioFieldDecoration(coachCopyOf(context).cardioType),
        items: _cardioTypeOptions(),
        onChanged: _selectCardioType,
      );

  void _selectCardioType(String? type) {
    if (type == null) return;
    setState(() {
      _cardioType = type;
      _cardioDays = type == 'none' ? 0 : (_cardioDays == 0 ? 1 : _cardioDays);
      _customCardioNoteMissing = false;
    });
  }

  List<DropdownMenuItem<int>> _cardioDayOptions() {
    final copy = coachCopyOf(context);
    return <DropdownMenuItem<int>>[
      for (int day = 0; day <= _frequency; day++)
        DropdownMenuItem<int>(
          value: day,
          child: Text(day == 0 ? copy.noCardio : '$day'),
        ),
    ];
  }

  Widget _cardioDaysField() => DropdownButtonFormField<int>(
        key: const Key('generate_draft_cardio_days_field'),
        initialValue: _cardioDays,
        decoration: _cardioFieldDecoration(coachCopyOf(context).cardioDays),
        items: _cardioDayOptions(),
        onChanged: _selectCardioDays,
      );

  void _selectCardioDays(int? selectedDays) {
    if (selectedDays == null) return;
    setState(() {
      _cardioDays = selectedDays;
      _cardioType = selectedDays == 0
          ? 'none'
          : (_cardioType == 'none' ? 'steady' : _cardioType);
    });
  }

  Widget _cardioMinutesField() {
    final copy = coachCopyOf(context);
    return TextField(
      key: const Key('generate_draft_cardio_minutes_field'),
      controller: _cardioMinutesController,
      keyboardType: TextInputType.number,
      maxLength: 3,
      decoration: _cardioFieldDecoration(
        copy.cardioMinutesPerSession,
        errorText: _cardioMinutesInvalid ? copy.cardioMinutesRange : null,
      ),
      onChanged: _updateCardioMinutes,
    );
  }

  void _updateCardioMinutes(String value) {
    final int? minutes = int.tryParse(value);
    if (minutes == null || minutes < 1 || minutes > 600) return;
    setState(() {
      _cardioMinutes = minutes;
      _cardioMinutesInvalid = false;
    });
  }

  Widget _customCardioNoteField() {
    final copy = coachCopyOf(context);
    return TextField(
      key: const Key('generate_draft_custom_cardio_note_field'),
      controller: _cardioCustomNoteController,
      maxLength: 2000,
      maxLines: 3,
      decoration: _cardioFieldDecoration(
        copy.customCardioNoteText,
        errorText: _customCardioNoteMissing ? copy.customCardioNoteRequired : null,
      ),
      onChanged: _updateCustomCardioNote,
    );
  }

  void _updateCustomCardioNote(String _) {
    if (_customCardioNoteMissing) {
      setState(() => _customCardioNoteMissing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final copy = coachCopyOf(context);
    final MyosThemeExtension c = MyosTheme.of(context);
    final List<CoachProgramSplitOption> splitOptions =
        widget.options.optionsByDays[_frequency] ??
            const <CoachProgramSplitOption>[];
    return AlertDialog(
      scrollable: true,
      title: Text(copy.generateDraft),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          DropdownButtonFormField<String>(
            key: const Key('generate_draft_split_field'),
            initialValue: _splitId,
            decoration: InputDecoration(
              labelText: copy.split,
              border: const OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<String>>[
              for (final CoachProgramSplitOption option in splitOptions)
                DropdownMenuItem<String>(
                  value: option.splitId,
                  child: Text(copy.splitOptionName(
                    option.splitId,
                    _frequency,
                    option.displayName,
                  )),
                ),
            ],
            onChanged: (String? selectedSplitId) => setState(
              () => _splitId = selectedSplitId ?? _splitId,
            ),
          ),
          if (_failure != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.sm),
            Text(
              displayCopyOf(context).failureMessage(_failure!),
              style: MyosTypography.of(context)
                  .bodySecondary
                  .copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MyosSpacing.md),
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
          const SizedBox(height: MyosSpacing.md),
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
            onChanged: (int? selectedDays) {
              if (selectedDays == null) return;
              setState(() {
                _frequency = selectedDays;
                if (_cardioDays > selectedDays) {
                  _cardioDays = selectedDays;
                }
                if (!(widget.options.optionsByDays[selectedDays] ??
                        const <CoachProgramSplitOption>[])
                    .any((CoachProgramSplitOption option) =>
                        option.splitId == _splitId)) {
                  _splitId = 'auto';
                }
              });
            },
          ),
          const SizedBox(height: MyosSpacing.md),
          _cardioTypeField(),
          const SizedBox(height: MyosSpacing.md),
          _cardioDaysField(),
          if (_cardioDays > 0) ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            _cardioMinutesField(),
          ],
          if (_cardioDays > 0 && _cardioType == 'custom') ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            _customCardioNoteField(),
          ],
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: Text(copy.cancel),
        ),
        MyosButton(
          key: const Key('generate_draft_confirm_button'),
          label: copy.generate,
          expand: false,
          loading: _submitting,
          onPressed: _submit,
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
  VolumeReview? _volumeReview;
  List<CoachPlayerExercise> _exercises = const <CoachPlayerExercise>[];
  final Map<String, CoachExerciseHistory> _histories =
      <String, CoachExerciseHistory>{};
  String? _openExerciseId;
  bool _loadingHistory = false;
  bool _generatingDraft = false;
  bool _copyingActiveProgram = false;
  bool _approvingActiveProgram = false;
  bool _downloadingProgramTemplate = false;
  bool _savingProgramTemplate = false;
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
      final List<Object?> playerData = await _loadPlayerData(api);
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

  Future<List<Object?>> _loadPlayerData(ApiClient api) =>
      Future.wait<Object?>(<Future<Object?>>[
        api.coachAlerts(states: <String>['new', 'acknowledged']),
        api.coachPlayerSummary(_entry.assignmentId),
        api.coachPlayerPersonalRecords(_entry.assignmentId),
        api.coachCheckpointReviews(_entry.assignmentId),
        api.coachPlayerExercises(_entry.assignmentId),
        api.coachProgramRequests(_entry.assignmentId),
        api.coachCheckIns(_entry.assignmentId),
        api.coachActiveProgram(_entry.assignmentId),
        api.coachPlayerVolumeReview(_entry.assignmentId),
      ]);

  void _applyPlayerData(List<Object?> playerData) {
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
      _volumeReview = playerData[8] as VolumeReview?;
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
    try {
      final _GenerateDraftDialogOptions options =
          await _loadGenerateDraftOptions();
      if (!mounted) return;
      final bool? generated = await showDialog<bool>(
        context: context,
        builder: (BuildContext context) => _GenerateDraftDialog(
          onGenerate: _generateDraft,
          options: options,
        ),
      );
      if (generated == true && mounted) _openProgramDraft();
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    }
  }

  Future<_GenerateDraftDialogOptions> _loadGenerateDraftOptions() async {
    final ApiClient api = ref.read(apiClientProvider);
    final Map<int, List<CoachProgramSplitOption>> optionsByDays =
        await api.coachProgramSplitOptions(_entry.assignmentId);
    final Map<String, dynamic>? draft = await _readExistingProgramDraft(api);
    return _GenerateDraftDialogOptions.fromDraft(optionsByDays, draft);
  }

  Future<Map<String, dynamic>?> _readExistingProgramDraft(
    ApiClient api,
  ) async {
    if (!(_activeProgram?.hasDraft ?? false)) return null;
    try {
      final Map<String, dynamic> envelope =
          await api.coachReadProgramDraft(_entry.assignmentId);
      return envelope['draft'] as Map<String, dynamic>?;
    } on ApiException catch (error) {
      if (error.statusCode != 404) rethrow;
      return null;
    }
  }

  Future<_GenerateDraftResult> _generateDraft(
    _GenerateDraftRequest request,
  ) async {
    setState(() {
      _generatingDraft = true;
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
        if (!mounted || !replace) return const _GenerateDraftResult();
        await ref.read(apiClientProvider).coachReplaceGeneratedProgramDraft(
              _entry.assignmentId,
              generationOverrides: request.toJson(),
            );
      }
      return const _GenerateDraftResult(completed: true);
    } on ApiException catch (error) {
      return _GenerateDraftResult(failure: apiFailureMessage(error));
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          copy.nextFollowUpLabel(_nextFollowUpOn),
          style: MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MyosSpacing.sm),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: MyosButton(
            key: const Key('record_check_in_button'),
            label: copy.logCheckIn,
            icon: Icons.note_add_outlined,
            variant: MyosButtonVariant.secondary,
            expand: false,
            onPressed: _openCheckInSheet,
          ),
        ),
        const SizedBox(height: MyosSpacing.sm),
        if (_checkIns.isEmpty)
          Text(
            copy.noRecordedCheckIns,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final CheckIn checkIn in _checkIns)
            MyosSettingsTile(
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MyosSectionHeader(title: copy.programRequests),
        if (_requestError != null) ...<Widget>[
          Text(
            displayCopyOf(context).failureMessage(_requestError!),
            style: MyosTypography.of(context).bodySecondary.copyWith(color: c.danger),
          ),
          const SizedBox(height: MyosSpacing.sm),
        ],
        if (_programRequests.isEmpty)
          Text(
            copy.noProgramRequests,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
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
        savingProgramTemplate: _savingProgramTemplate,
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
        saveAsTemplate: _saveProgramAsTemplate,
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
        key: const Key('coach_player_history_screen'),
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

  Future<void> _saveProgramAsTemplate() async {
    final TrainingProgram? program = _activeProgram?.program;
    final int? version = program?.version;
    if (program == null || version == null) return;
    final ProgramTemplateSaveRequest? request = await showProgramTemplateSaveSheet(
      context,
      notes: programTemplateNoteReviews(program.toJson()),
    );
    if (!mounted || request == null) return;
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
    setState(() {
      _savingProgramTemplate = true;
      _programActionError = null;
    });
    try {
      await ref.read(apiClientProvider).coachSaveAssignedProgramAsTemplate(
            assignmentId: _entry.assignmentId,
            fromDraft: false,
            sourceRevision: version.toString(),
            name: request.name,
            description: request.description,
            notes: request.notes,
          );
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text(coachCopyOf(context).templateSaved)),
      );
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _programActionError = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _savingProgramTemplate = false);
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final copy = coachCopyOf(context);
    final String description = resolveCoachAlertDescription(
      alert,
      displayCopyOf(context).languageCode,
    );
    final bool busy = _busyAlertId == alert.alertId;
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
      child: MyosCard(
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
                          MyosTypography.of(context).body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ),
                coachAlertStateChip(context, alert),
              ],
            ),
            const SizedBox(height: MyosSpacing.xs),
            Wrap(
              spacing: MyosSpacing.xs,
              runSpacing: MyosSpacing.xs,
              children: <Widget>[
                if (alert.isFollowUpDue)
                  MyosButton(
                    label: copy.logCheckInAction,
                    variant: MyosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : _openCheckInSheet,
                  ),
                if (alert.isNew)
                  MyosButton(
                    label: copy.acknowledge,
                    variant: MyosButtonVariant.tertiary,
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
                  MyosButton(
                    label: copy.resolve,
                    variant: MyosButtonVariant.tertiary,
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final copy = coachCopyOf(context);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null || _assignmentDenied) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MyosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                  _assignmentDenied
                      ? copy.noActiveAssignment
                      : displayCopyOf(context).failureMessage(_error!),
                  textAlign: TextAlign.center,
                  style: MyosTypography.of(context).body.copyWith(color: c.textPrimary)),
              const SizedBox(height: MyosSpacing.md),
              MyosButton(
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
      key: const Key('coach_player_history_scroll'),
      padding: const EdgeInsets.all(MyosSpacing.md),
      children: <Widget>[
        if (_alerts.isNotEmpty) ...<Widget>[
          const SizedBox(height: MyosSpacing.md),
          Text(copy.openAlerts,
              style: MyosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MyosSpacing.xs),
          for (final CoachAlert alert in _alerts) _alertCard(context, alert),
        ],
        const SizedBox(height: MyosSpacing.md),
        MyosSegmentedControl<_PlayerSegment>(
          segments: <MyosSegment<_PlayerSegment>>[
            MyosSegment<_PlayerSegment>(
              value: _PlayerSegment.program,
              label: copy.program,
            ),
            MyosSegment<_PlayerSegment>(
              value: _PlayerSegment.history,
              label: copy.history,
            ),
            MyosSegment<_PlayerSegment>(
              value: _PlayerSegment.checkIns,
              label: copy.checkIns,
            ),
            MyosSegment<_PlayerSegment>(
              value: _PlayerSegment.requests,
              label: _pendingRequests > 0
                  ? copy.requestsWithCount(_pendingRequests)
                  : copy.requests,
            ),
          ],
          selected: _segment,
          onChanged: (_PlayerSegment value) => setState(() => _segment = value),
        ),
        const SizedBox(height: MyosSpacing.md),
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
        volumeReview: _volumeReview,
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
