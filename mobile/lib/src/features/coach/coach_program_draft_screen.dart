import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/program_prescription.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_exercise_picker_dialog.dart';
import 'program_publish_confirmation.dart';
import 'program_import_files.dart';

part 'program_editor/day_card.dart';
part 'program_editor/exercise_card.dart';
part 'program_editor/warmup_movement_card.dart';

typedef _EditorErrorLocation = ({
  int weekIndex,
  int dayIndex,
  int? exerciseIndex,
  int? warmupMovementIndex,
  String field,
});

class CoachProgramDraftScreen extends ConsumerStatefulWidget {
  const CoachProgramDraftScreen({
    super.key,
    required this.assignmentId,
    required this.playerUsername,
  })  : templateId = null,
        templateName = null,
        templateDescription = null,
        isNewTemplate = false;

  /// Opens an existing Coach-owned Program template (ticket #305), where the
  /// Publish action is replaced by Save.
  const CoachProgramDraftScreen.template({
    super.key,
    required this.templateId,
    required this.templateName,
    this.templateDescription,
  })  : assignmentId = null,
        playerUsername = null,
        isNewTemplate = false;

  /// Opens a blank Program template; the first Save creates it.
  const CoachProgramDraftScreen.newTemplate({super.key})
      : assignmentId = null,
        playerUsername = null,
        templateId = null,
        templateName = null,
        templateDescription = null,
        isNewTemplate = true;

  final String? assignmentId;
  final String? playerUsername;
  final String? templateId;
  final String? templateName;
  final String? templateDescription;
  final bool isNewTemplate;

  bool get isTemplateMode => isNewTemplate || templateId != null;

  @override
  ConsumerState<CoachProgramDraftScreen> createState() =>
      _CoachProgramDraftScreenState();
}

class _CoachProgramDraftScreenState
    extends ConsumerState<CoachProgramDraftScreen> {
  final List<_DraftWeekEditor> _weeks = <_DraftWeekEditor>[];
  int _selectedWeekIndex = 0;
  Map<String, dynamic>? _draft;
  bool _loading = true;
  bool _saving = false;
  bool _publishing = false;
  bool _discarding = false;
  bool _downloadingTemplate = false;
  bool _hasUnsavedChanges = false;
  bool _allowPop = false;
  FailureMessage? _failure;
  String? _inputError;
  String? _serverSummary;
  String? _sourceTemplateName;
  final Map<_EditorErrorLocation, String> _serverErrors =
      <_EditorErrorLocation, String>{};
  late final TextEditingController _templateName;
  late final TextEditingController _templateDescription;

  bool get _busy => _saving || _publishing || _discarding;
  List<_DraftDayEditor> get _days => _weeks[_selectedWeekIndex].days;

  @override
  void initState() {
    super.initState();
    _templateName = TextEditingController(text: widget.templateName ?? '');
    _templateDescription =
        TextEditingController(text: widget.templateDescription ?? '');
    _loadDraft();
  }

  @override
  void dispose() {
    for (final _DraftWeekEditor week in _weeks) {
      week.dispose();
    }
    _templateName.dispose();
    _templateDescription.dispose();
    super.dispose();
  }

  Future<void> _loadDraft() async {
    await null;
    final ApiClient api = ref.read(apiClientProvider);
    try {
      Map<String, dynamic> envelope;
      if (widget.isTemplateMode) {
        if (widget.isNewTemplate) {
          envelope = <String, dynamic>{'program': _emptyDraft()};
        } else {
          envelope = await api.coachReadProgramTemplate(widget.templateId!);
        }
      } else {
        try {
          envelope = await api.coachReadProgramDraft(widget.assignmentId!);
        } on ApiException catch (error) {
          if (error.statusCode != 404) rethrow;
          envelope = await api.coachCreateProgramDraft(
            widget.assignmentId!,
            draft: _emptyDraft(),
          );
        }
      }
      if (mounted) _applyEnvelope(envelope);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _failure = apiFailureMessage(error);
      });
    }
  }

  Map<String, dynamic> _emptyDraft() {
    final copy = coachCopyOf(context);
    final Map<String, dynamic> firstDay = <String, dynamic>{
      'day_name': copy.firstTrainingDay,
      'day_order': 1,
      'warmup_exercises': <dynamic>[],
      'exercises': <dynamic>[],
      'cardio': null,
    };
    return <String, dynamic>{
      'program_name': copy.customProgram,
      'split_type': 'custom',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[firstDay],
      'weeks': <Map<String, dynamic>>[
        <String, dynamic>{
          'week_name': copy.firstWeekName,
          'week_order': 1,
          'days': <Map<String, dynamic>>[firstDay],
        },
      ],
    };
  }

  void _applyEnvelope(Map<String, dynamic> envelope) {
    final Map<String, dynamic> draft = _copyMap(
      (envelope['draft'] ?? envelope['program']) as Map<String, dynamic>,
    );
    final List<dynamic> sourceWeeks = draft['weeks'] as List<dynamic>? ?? <dynamic>[];
    final List<dynamic> weeks = sourceWeeks.isEmpty
        ? <dynamic>[
            <String, dynamic>{
              'week_name': coachCopyOf(context).firstWeekName,
              'week_order': 1,
              'days': draft['days'] as List<dynamic>? ?? <dynamic>[],
            },
          ]
        : sourceWeeks;
    for (final _DraftWeekEditor week in _weeks) {
      week.dispose();
    }
    _weeks
      ..clear()
      ..addAll(
        weeks.map((dynamic rawWeek) {
          final Map<String, dynamic> week = _copyMap(rawWeek as Map<String, dynamic>);
          return _DraftWeekEditor(
            week,
            <_DraftDayEditor>[
              for (final dynamic rawDay in week['days'] as List<dynamic>? ?? <dynamic>[])
                _DraftDayEditor(_copyMap(rawDay as Map<String, dynamic>)),
            ],
          );
        }),
      );
    _selectedWeekIndex = 0;
    if (_weeks.isEmpty) {
      _weeks.add(_newWeek(1));
    }
    if (widget.isTemplateMode && !widget.isNewTemplate) {
      final String? name = envelope['name'] as String?;
      if (name != null) _templateName.text = name;
      _templateDescription.text = envelope['description'] as String? ?? '';
    }
    _sourceTemplateName = envelope['source_template_name'] as String?;
    setState(() {
      _draft = draft;
      _loading = false;
      _failure = null;
      _hasUnsavedChanges = false;
    });
  }

  Map<String, dynamic> _copyMap(Map<String, dynamic> source) =>
      jsonDecode(jsonEncode(source)) as Map<String, dynamic>;

  Map<String, dynamic> _serializedDraft() {
    final Map<String, dynamic> draft = _copyMap(_draft!);
    draft['weekly_frequency'] = _maximumWeekFrequency;
    final List<Map<String, dynamic>> weeks = <Map<String, dynamic>>[
      for (int weekIndex = 0; weekIndex < _weeks.length; weekIndex++)
        _weeks[weekIndex].toJson(weekIndex + 1, coachCopyOf(context)),
    ];
    draft['weeks'] = weeks;
    draft['days'] = <Map<String, dynamic>>[
      for (final Map<String, dynamic> week in weeks)
        for (final dynamic day in week['days'] as List<dynamic>)
          day as Map<String, dynamic>,
    ];
    return draft;
  }

  int get _maximumWeekFrequency => _weeks.fold<int>(
        1,
        (int maxDays, _DraftWeekEditor week) =>
            week.days.length > maxDays ? week.days.length : maxDays,
      );

  _DraftDayEditor _newDay(int order) {
    final CoachCopy copy = coachCopyOf(context);
    return _DraftDayEditor(<String, dynamic>{
      'day_name': copy.trainingDayNumber(order),
      'day_order': order,
      'warmup_exercises': <dynamic>[],
      'exercises': <dynamic>[],
      'cardio': null,
    });
  }

  _DraftWeekEditor _newWeek(int order) {
    final CoachCopy copy = coachCopyOf(context);
    return _DraftWeekEditor(
      <String, dynamic>{
        'week_name': copy.weekNameNumber(order),
        'week_order': order,
        'days': <dynamic>[],
      },
      <_DraftDayEditor>[_newDay(1)],
    )..name.text = copy.weekNameNumber(order);
  }

  void _syncWeekOrders() {
    for (int weekIndex = 0; weekIndex < _weeks.length; weekIndex++) {
      final _DraftWeekEditor week = _weeks[weekIndex];
      week.source['week_order'] = weekIndex + 1;
      for (int dayIndex = 0; dayIndex < week.days.length; dayIndex++) {
        week.days[dayIndex].source['day_order'] = dayIndex + 1;
        week.days[dayIndex].source['week_order'] = weekIndex + 1;
      }
    }
    if (_draft != null) _draft!['weekly_frequency'] = _maximumWeekFrequency;
  }

  void _addWeek() {
    if (_weeks.length >= ProgramDraftPrescription.maxWeeks) return;
    setState(() {
      _weeks.add(_newWeek(_weeks.length + 1));
      _selectedWeekIndex = _weeks.length - 1;
      _hasUnsavedChanges = true;
      _syncWeekOrders();
      _clearServerErrors();
    });
  }

  void _duplicateWeek() {
    if (_weeks.length >= ProgramDraftPrescription.maxWeeks) return;
    final int duplicateIndex = _selectedWeekIndex + 1;
    final _DraftWeekEditor duplicate = _weeks[_selectedWeekIndex].copy();
    setState(() {
      _weeks.insert(duplicateIndex, duplicate);
      _selectedWeekIndex = duplicateIndex;
      _hasUnsavedChanges = true;
      _syncWeekOrders();
      _clearServerErrors();
    });
  }

  void _moveWeek(int delta) {
    final int target = _selectedWeekIndex + delta;
    if (target < 0 || target >= _weeks.length) return;
    if (!_moveListItem(_weeks, _selectedWeekIndex, delta)) return;
    setState(() {
      _selectedWeekIndex = target;
      _hasUnsavedChanges = true;
      _syncWeekOrders();
      _clearServerErrors();
    });
  }

  void _removeWeek() {
    if (_weeks.length <= 1) return;
    final _DraftWeekEditor removed = _weeks.removeAt(_selectedWeekIndex);
    removed.dispose();
    setState(() {
      _selectedWeekIndex = _selectedWeekIndex.clamp(0, _weeks.length - 1);
      _hasUnsavedChanges = true;
      _syncWeekOrders();
      _clearServerErrors();
    });
  }

  void _selectWeek(int index) {
    if (index == _selectedWeekIndex) return;
    setState(() {
      _selectedWeekIndex = index;
      _clearServerErrors();
    });
  }

  void _syncDayOrders() {
    for (int index = 0; index < _days.length; index++) {
      _days[index].source['day_order'] = index + 1;
    }
    if (_draft != null) _draft!['weekly_frequency'] = _maximumWeekFrequency;
  }

  void _addDay() {
    if (_days.length >= ProgramDraftPrescription.maxDays) return;
    setState(() {
      _days.add(_newDay(_days.length + 1));
      _hasUnsavedChanges = true;
      _syncDayOrders();
      _clearServerErrors();
    });
  }

  void _moveDay(int index, int delta) {
    if (!_moveListItem(_days, index, delta)) return;
    setState(() {
      _hasUnsavedChanges = true;
      _syncDayOrders();
      _clearServerErrors();
    });
  }

  void _duplicateDay(int index) {
    if (_days.length >= ProgramDraftPrescription.maxDays) return;
    final _DraftDayEditor original = _days[index];
    final _DraftDayEditor duplicate = original.copy();
    duplicate.dayName.text = coachCopyOf(context).dayDuplicateName(
      original.dayName.text.trim(),
    );
    setState(() {
      _days.insert(index + 1, duplicate);
      _hasUnsavedChanges = true;
      _syncDayOrders();
      _clearServerErrors();
    });
  }

  void _removeDay(int index) {
    final _DraftDayEditor removed = _days.removeAt(index);
    removed.dispose();
    setState(() {
      _hasUnsavedChanges = true;
      _syncDayOrders();
      _clearServerErrors();
    });
  }

  Widget _weekControls(CoachCopy copy) {
    if (_weeks.length <= 1) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        _weekTabStrip(copy),
        const SizedBox(height: MayosSpacing.xs),
        _weekNameField(copy),
        _weekOrderButtons(copy),
      ],
    );
  }

  Widget _addWeekButton(CoachCopy copy) => MayosButton(
        key: const Key('program_draft_add_week'),
        label: copy.addWeek,
        icon: Icons.add,
        variant: MayosButtonVariant.secondary,
        onPressed: _busy || _weeks.length >= ProgramDraftPrescription.maxWeeks
            ? null
            : _addWeek,
      );

  Widget _duplicateWeekButton(CoachCopy copy) => MayosButton(
        key: const Key('program_draft_duplicate_week'),
        label: copy.duplicateWeek,
        icon: Icons.copy_outlined,
        variant: MayosButtonVariant.secondary,
        onPressed: _busy || _weeks.length >= ProgramDraftPrescription.maxWeeks
            ? null
            : _duplicateWeek,
      );

  Widget _weekTabStrip(CoachCopy copy) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: <Widget>[
            for (int index = 0; index < _weeks.length; index++)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: MayosSpacing.xs),
                child: TextButton(
                  key: Key('program_draft_week_tab_${index + 1}'),
                  onPressed: () => _selectWeek(index),
                  child: Text(copy.weekTabLabel(
                    index + 1,
                    _weeks[index].name.text.trim(),
                  )),
                ),
              ),
          ],
        ),
      );

  Widget _weekNameField(CoachCopy copy) => TextField(
        key: const Key('program_draft_week_name'),
        controller: _weeks[_selectedWeekIndex].name,
        enabled: !_busy,
        decoration: InputDecoration(
          labelText: copy.weekName,
          border: const OutlineInputBorder(),
        ),
        onChanged: (_) => setState(() => _hasUnsavedChanges = true),
      );

  Widget _weekOrderButtons(CoachCopy copy) => Row(
        children: <Widget>[
          IconButton(
            key: const Key('program_draft_week_up'),
            tooltip: copy.moveWeekUp,
            onPressed: _busy || _selectedWeekIndex == 0
                ? null
                : () => _moveWeek(-1),
            icon: const Icon(Icons.arrow_upward),
          ),
          IconButton(
            key: const Key('program_draft_week_down'),
            tooltip: copy.moveWeekDown,
            onPressed: _busy || _selectedWeekIndex == _weeks.length - 1
                ? null
                : () => _moveWeek(1),
            icon: const Icon(Icons.arrow_downward),
          ),
          const Spacer(),
          IconButton(
            key: const Key('program_draft_week_remove'),
            tooltip: copy.removeWeek,
            onPressed: _busy ? null : _removeWeek,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      );

  Future<ExerciseCatalogEntry?> _pickExercise({
    String? replacingExerciseId,
    String? title,
  }) =>
      showDialog<ExerciseCatalogEntry>(
        context: context,
        builder: (BuildContext context) => CoachExercisePickerDialog(
          replacingExerciseId: replacingExerciseId,
          title: title,
        ),
      );

  _DraftExerciseEditor _newExercise(ExerciseCatalogEntry selected) =>
      _DraftExerciseEditor(<String, dynamic>{
        ..._exerciseIdentity(selected),
        'warmup_sets': 0,
        'target_sets': ProgramDraftPrescription.defaultSets,
        'target_reps_min': ProgramDraftPrescription.defaultMinReps,
        'target_reps_max': ProgramDraftPrescription.defaultMaxReps,
        'target_rir': ProgramDraftPrescription.defaultRir,
        'rest_seconds': ProgramDraftPrescription.defaultExerciseRestSeconds,
        'tempo': null,
        'notes': null,
        'suggested_substitutes': <dynamic>[],
      });

  Future<void> _addExercise(int dayIndex) async {
    final ExerciseCatalogEntry? selected = await _pickExercise();
    if (selected == null || !mounted) return;
    setState(() {
      _days[dayIndex].exercises.add(_newExercise(selected));
      _hasUnsavedChanges = true;
      _inputError = null;
      _clearServerErrors();
    });
  }

  Future<void> _insertExercise(
    int dayIndex,
    int index, {
    required String title,
  }) async {
    final ExerciseCatalogEntry? selected = await _pickExercise(title: title);
    if (selected == null || !mounted) return;
    setState(() {
      _days[dayIndex].exercises.insert(index, _newExercise(selected));
      _hasUnsavedChanges = true;
      _inputError = null;
      _clearServerErrors();
    });
  }

  Future<void> _swapExercise(int dayIndex, int index) async {
    final _DraftExerciseEditor exercise = _days[dayIndex].exercises[index];
    final ExerciseCatalogEntry? selected = await _pickExercise(
      replacingExerciseId: exercise.source['exercise_id'] as String?,
      title: coachCopyOf(context).swapExercise,
    );
    if (selected == null || !mounted) return;
    setState(() {
      exercise.swapIdentity(selected);
      _hasUnsavedChanges = true;
      _inputError = null;
      _clearServerErrors();
    });
  }

  Map<String, dynamic>? _draftForSave() {
    try {
      return _serializedDraft();
    } on FormatException catch (error) {
      setState(() => _inputError = error.message);
      return null;
    }
  }

  Future<void> _saveDraft() async {
    final CoachCopy copy = coachCopyOf(context);
    final Map<String, dynamic>? draft = _draftForSave();
    if (draft == null) return;
    final String templateName =
        widget.isTemplateMode ? _templateName.text.trim() : '';
    if (widget.isTemplateMode && templateName.isEmpty) {
      setState(() => _inputError = copy.templateNameRequired);
      return;
    }
    setState(() {
      _saving = true;
      _failure = null;
      _inputError = null;
      _clearServerErrors();
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      if (widget.isTemplateMode) {
        final String description = _templateDescription.text.trim();
        final Map<String, dynamic> saved = widget.isNewTemplate
            ? await api.coachCreateProgramTemplate(
                name: templateName,
                description: description,
                program: draft,
              )
            : await api.coachUpdateProgramTemplate(
                widget.templateId!,
                name: templateName,
                description: description,
                program: draft,
              );
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(copy.templateSaved)),
        );
        _popEditor(saved);
        return;
      }
      final Map<String, dynamic> saved = await api
          .coachReplaceProgramDraft(widget.assignmentId!, draft);
      if (!mounted) return;
      setState(() {
        _draft = _copyMap(saved['draft'] as Map<String, dynamic>);
        _hasUnsavedChanges = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(copy.draftSaved)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        if (error.serverDetails?['errors'] is List ||
            error.serverDetails?['pydantic_errors'] is List) {
          _applyServerValidation(error.serverDetails!);
        } else {
          _failure = apiFailureMessage(error);
        }
      });
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<bool> _confirm(String title, String lead, String action) async {
    final copy = coachCopyOf(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text(title),
            content: Text(lead),
            actions: <Widget>[
              TextButton(
                key: const Key('program_draft_confirm_cancel'),
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(copy.cancel),
              ),
              TextButton(
                key: const Key('program_draft_confirm_action'),
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(action),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _publishDraft() async {
    final copy = coachCopyOf(context);
    final ApiClient api = ref.read(apiClientProvider);
    final List<String>? resolveRequestIds =
        await showProgramPublishConfirmation(
      context,
      api,
      widget.assignmentId!,
      ProgramPublishConfirmation(
        title: copy.publishDraft,
        prompt: copy.confirmPublishDraft,
        confirmLabel: copy.publish,
        cancelLabel: copy.cancel,
      ),
      onRequestsLoadError: (ApiException error) {
        if (mounted) setState(() => _failure = apiFailureMessage(error));
      },
    );
    if (!mounted || resolveRequestIds == null) return;
    final Map<String, dynamic>? draft = _draftForSave();
    if (draft == null || !mounted) return;
    setState(() {
      _publishing = true;
      _failure = null;
      _inputError = null;
      _clearServerErrors();
    });
    try {
      await api.coachReplaceProgramDraft(
            widget.assignmentId!,
            draft,
      );
      if (mounted) setState(() => _hasUnsavedChanges = false);
      final CoachProgramPublication publication =
          await api.coachPublishProgramDraft(
        widget.assignmentId!,
        resolveRequestIds: resolveRequestIds,
      );
      if (mounted) _popEditor(publication);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.serverDetails?['errors'] is List ||
          error.serverDetails?['pydantic_errors'] is List) {
        setState(() => _applyServerValidation(error.serverDetails!));
      } else {
        setState(() => _failure = apiFailureMessage(error));
      }
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _discardDraft() async {
    final copy = coachCopyOf(context);
    if (!await _confirm(
      copy.discardDraft,
      copy.confirmDiscardDraft,
      copy.discardDraft,
    )) {
      return;
    }
    setState(() {
      _discarding = true;
      _failure = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .coachDiscardProgramDraft(widget.assignmentId!);
      if (mounted) _popEditor();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _discarding = false);
    }
  }

  void _reorderExercises(int dayIndex, int oldIndex, int newIndex) {
    final List<_DraftExerciseEditor> exercises = _days[dayIndex].exercises;
    if (oldIndex == newIndex) return;
    exercises.insert(newIndex, exercises.removeAt(oldIndex));
    setState(() {
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  void _duplicateExercise(int dayIndex, int index) {
    final List<_DraftExerciseEditor> exercises = _days[dayIndex].exercises;
    setState(() {
      exercises.insert(index + 1, exercises[index].copy());
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  void _removeExercise(int dayIndex, int index) {
    final _DraftExerciseEditor removed = _days[dayIndex].exercises.removeAt(index);
    removed.dispose();
    setState(() {
      _inputError = null;
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  _DraftWarmupEditor _newWarmupMovement() => _DraftWarmupEditor(
        <String, dynamic>{
          'exercise_name': '',
          'sets': ProgramDraftPrescription.defaultWarmupMovementSets,
          'reps': ProgramDraftPrescription.defaultWarmupMovementReps,
          'rest_seconds': ProgramDraftPrescription.defaultWarmupMovementRestSeconds,
          'notes': null,
        },
      );

  void _addWarmupMovement(int dayIndex) {
    setState(() {
      _hasUnsavedChanges = true;
      _days[dayIndex].warmups.add(_newWarmupMovement());
      _clearServerErrors();
    });
  }

  void _insertWarmupMovement(int dayIndex, int index) {
    setState(() {
      _days[dayIndex].warmups.insert(index, _newWarmupMovement());
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  void _moveWarmupMovement(int dayIndex, int index, int delta) {
    final List<_DraftWarmupEditor> warmups = _days[dayIndex].warmups;
    if (!_moveListItem(warmups, index, delta)) return;
    setState(() {
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  void _removeWarmupMovement(int dayIndex, int index) {
    final _DraftWarmupEditor removed = _days[dayIndex].warmups.removeAt(index);
    removed.dispose();
    setState(() {
      _hasUnsavedChanges = true;
      _clearServerErrors();
    });
  }

  void _clearServerErrors() {
    _serverSummary = null;
    _serverErrors.clear();
  }

  void _applyServerValidation(Map<String, dynamic> details) {
    final CoachCopy copy = coachCopyOf(context);
    final List<dynamic> issues = details['errors'] as List<dynamic>? ??
        details['pydantic_errors'] as List<dynamic>? ?? <dynamic>[];
    final List<String> summary = <String>[];
    for (final dynamic rawIssue in issues) {
      if (rawIssue is! Map) continue;
      final Map<String, dynamic> issue = Map<String, dynamic>.from(rawIssue);
      final Map<String, dynamic> normalized =
          _normalizeServerIssue(issue);
      final String message = normalized['message'] as String;
      final int? dayIndex = normalized['day_index'] as int?;
      final int? exerciseIndex = normalized['exercise_index'] as int?;
      final int? movementIndex =
          normalized['warmup_movement_index'] as int?;
      final int weekIndex =
          (normalized['week_index'] as int? ?? _selectedWeekIndex)
              .clamp(0, _weeks.length - 1);
      final String field = normalized['field'] as String;
      final String? code = normalized['code'] as String?;
      final String rendered = code == null
          ? message
          : copy.programDraftValidationMessage(code);
      final _EditorErrorLocation location = (
        weekIndex: weekIndex,
        dayIndex: dayIndex ?? -1,
        exerciseIndex: exerciseIndex,
        warmupMovementIndex: movementIndex,
        field: field,
      );
      final List<_DraftDayEditor> errorDays = _weeks[weekIndex].days;
      if (dayIndex == null || dayIndex < 0 || dayIndex >= errorDays.length) {
        summary.add(rendered);
      } else if (movementIndex != null &&
          movementIndex >= 0 &&
          movementIndex < errorDays[dayIndex].warmups.length &&
          const <String>{'exercise_name', 'sets', 'reps', 'rest_seconds', 'notes'}
              .contains(field)) {
        _serverErrors[location] = rendered;
      } else if (exerciseIndex != null &&
          exerciseIndex >= 0 &&
          exerciseIndex < errorDays[dayIndex].exercises.length &&
          const <String>{
            'exercise_id', 'target_sets', 'target_reps_min', 'target_reps_max',
            'target_rir', 'target_rpe', 'warmup_sets', 'rest_seconds', 'tempo', 'notes'
          }.contains(field)) {
        _serverErrors[location] = rendered;
      } else if (exerciseIndex == null && movementIndex == null &&
          const <String>{'day_name', 'cardio'}.contains(field)) {
        _serverErrors[location] = rendered;
      } else if (exerciseIndex == null && movementIndex == null) {
        _serverErrors[location] = rendered;
      } else {
        summary.add(rendered);
      }
    }
    _serverSummary = summary.isEmpty ? null : summary.join('\n');
  }

  Map<String, dynamic> _normalizeServerIssue(Map<String, dynamic> issue) {
    if (issue['location'] is Map) {
      final Map<String, dynamic> location =
          Map<String, dynamic>.from(issue['location'] as Map);
      return <String, dynamic>{
        'code': issue['code'],
        'message': issue['message'] as String? ?? '',
        ...location,
      };
    }
    final List<dynamic> rawLocation = issue['loc'] as List<dynamic>? ?? <dynamic>[];
    final List<dynamic> location = rawLocation.skipWhile((dynamic item) => item == 'body').toList();
    int? weekIndex;
    int? dayIndex;
    int? exerciseIndex;
    int? movementIndex;
    String field = 'program';
    final int weeksAt = location.indexOf('weeks');
    if (weeksAt >= 0 &&
        location.length > weeksAt + 1 &&
        location[weeksAt + 1] is int) {
      weekIndex = location[weeksAt + 1] as int;
    }
    final int dayAt = location.indexOf('days');
    if (dayAt >= 0 && location.length > dayAt + 1 && location[dayAt + 1] is int) {
      dayIndex = location[dayAt + 1] as int;
      weekIndex ??= _selectedWeekIndex;
      if (location.length > dayAt + 2) {
        final dynamic group = location[dayAt + 2];
        if (group == 'exercises' && location.length > dayAt + 3 && location[dayAt + 3] is int) {
          exerciseIndex = location[dayAt + 3] as int;
          if (location.length > dayAt + 4) field = '${location[dayAt + 4]}';
        } else if (group == 'warmup_exercises' && location.length > dayAt + 3 && location[dayAt + 3] is int) {
          movementIndex = location[dayAt + 3] as int;
          if (location.length > dayAt + 4) field = '${location[dayAt + 4]}';
        } else {
          field = '$group';
        }
      }
    } else if (location.isNotEmpty) {
      field = '${location.last}';
    }
    final String type = issue['type'] as String? ?? '';
    final String code = switch (field) {
      'warmup_sets' => 'invalid_warmup_sets',
      'sets' when movementIndex != null => 'invalid_movement_sets',
      'reps' when movementIndex != null => 'invalid_movement_reps',
      'tempo' => 'tempo_too_long',
      'notes' => 'notes_too_long',
      'target_reps_min' || 'target_reps_max' => 'invalid_reps',
      'target_sets' => 'invalid_sets',
      'target_rir' || 'target_rpe' => 'invalid_rir',
      'day_order' => 'invalid_day_order',
      'weekly_frequency' => 'invalid_weekly_frequency',
      'days' => 'too_many_days',
      _ => 'invalid_program_field',
    };
    final String message = issue['msg'] as String? ?? 'The field is invalid.';
    return <String, dynamic>{
      'code': code,
      'message': message,
      'week_index': weekIndex,
      'day_index': dayIndex,
      'exercise_index': exerciseIndex,
      'warmup_movement_index': movementIndex,
      'field': field,
      'type': type,
    };
  }

  @override
  Widget build(BuildContext context) {
    final copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return PopScope<Object?>(
      canPop: _allowPop || !_hasUnsavedChanges,
      onPopInvokedWithResult: _onPopInvoked,
      child: Scaffold(
      appBar: AppBar(
        leading: BackButton(onPressed: _requestPop),
        title: Text(widget.isTemplateMode ? copy.writeTemplate : copy.writeProgram),
        actions: <Widget>[
          if (!widget.isTemplateMode) ...<Widget>[
            IconButton(
              key: const Key('program_template_xlsx_download'),
              tooltip: copy.downloadProgramTemplate,
              onPressed: _downloadingTemplate ? null : () => _downloadTemplate('xlsx'),
              icon: const Icon(Icons.download_outlined),
            ),
            IconButton(
              key: const Key('program_template_csv_download'),
              tooltip: copy.downloadProgramTemplateCsv,
              onPressed: _downloadingTemplate ? null : () => _downloadTemplate('csv'),
              icon: const Icon(Icons.table_view_outlined),
            ),
          ],
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _draft == null
              ? _loadError(context)
              : Column(
                  children: <Widget>[
                    Expanded(
                      child: Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 960),
                          child: ListView(
                            padding: MayosSpacing.screen,
                            children: <Widget>[
                              if (!widget.isTemplateMode &&
                                  _sourceTemplateName != null) ...<Widget>[
                                Text(
                                  copy.fromTemplate(_sourceTemplateName!),
                                  key: const Key('program_draft_source_template'),
                                  style: MayosTypography.of(context)
                                      .bodySecondary,
                                ),
                                const SizedBox(height: MayosSpacing.sm),
                              ],
                              if (widget.isTemplateMode) ...<Widget>[
                                TextField(
                                  key: const Key('program_template_name'),
                                  controller: _templateName,
                                  enabled: !_busy,
                                  decoration: InputDecoration(
                                    labelText: copy.templateName,
                                  ),
                                  onChanged: (_) {
                                    setState(() {
                                      _hasUnsavedChanges = true;
                                      _inputError = null;
                                    });
                                  },
                                ),
                                const SizedBox(height: MayosSpacing.sm),
                                TextField(
                                  key: const Key('program_template_description'),
                                  controller: _templateDescription,
                                  enabled: !_busy,
                                  minLines: 1,
                                  maxLines: 3,
                                  decoration: InputDecoration(
                                    labelText: copy.templateDescription,
                                  ),
                                  onChanged: (_) {
                                    setState(() {
                                      _hasUnsavedChanges = true;
                                      _inputError = null;
                                    });
                                  },
                                ),
                              ] else
                                Text(widget.playerUsername ?? '',
                                    style: MayosTypography.of(context).sectionHeading),
                              const SizedBox(height: MayosSpacing.md),
                              if (_weeks.length > 1) ...<Widget>[
                                _weekControls(copy),
                                const SizedBox(height: MayosSpacing.md),
                              ],
                              for (int index = 0; index < _days.length; index++)
                                _dayCard(context, index),
                              MayosButton(
                                key: const Key('program_draft_add_day'),
                                label: copy.addDay,
                                icon: Icons.add,
                                variant: MayosButtonVariant.secondary,
                                onPressed: _days.length >=
                                            ProgramDraftPrescription.maxDays ||
                                        _busy
                                    ? null
                                    : _addDay,
                              ),
                              const SizedBox(height: MayosSpacing.xs),
                              _addWeekButton(copy),
                              const SizedBox(height: MayosSpacing.xs),
                              _duplicateWeekButton(copy),
                              if (_days.isEmpty) ...<Widget>[
                                const SizedBox(height: MayosSpacing.sm),
                                Text(copy.noTrainingDays),
                              ],
                              if (_inputError != null ||
                                  _serverSummary != null ||
                                  _failure != null) ...<Widget>[
                                const SizedBox(height: MayosSpacing.md),
                                Text(
                                  _inputError ??
                                      _serverSummary ??
                                      displayCopyOf(context)
                                          .failureMessage(_failure!),
                                  style: MayosTypography.of(context).body
                                      .copyWith(color: colors.danger),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                    SafeArea(
                      top: false,
                      child: Padding(
                        padding: MayosSpacing.screen,
                        child: Column(
                          children: <Widget>[
                            MayosButton(
                              key: const Key('program_draft_save'),
                              label: widget.isTemplateMode
                                  ? copy.saveTemplate
                                  : copy.saveDraft,
                              variant: widget.isTemplateMode
                                  ? MayosButtonVariant.primary
                                  : MayosButtonVariant.secondary,
                              loading: _saving,
                              onPressed: _busy ? null : _saveDraft,
                            ),
                            if (!widget.isTemplateMode) ...<Widget>[
                              const SizedBox(height: MayosSpacing.xs),
                              MayosButton(
                                key: const Key('program_draft_publish'),
                                label: copy.publishDraft,
                                loading: _publishing,
                                onPressed: _busy ? null : _publishDraft,
                              ),
                              MayosButton(
                                key: const Key('program_draft_discard'),
                                label: copy.discardDraft,
                                variant: MayosButtonVariant.tertiary,
                                loading: _discarding,
                                onPressed: _busy ? null : _discardDraft,
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
      ),
    );
  }

  Future<void> _downloadTemplate(String extension) => runProgramTemplateDownload(
        ref: ref,
        extension: extension,
        onBusyChanged: (bool busy) => setState(() => _downloadingTemplate = busy),
        isMounted: () => mounted,
        onFailure: (FailureMessage message) => setState(() => _failure = message),
      );

  Widget _loadError(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final String message = _failure == null
        ? (widget.isTemplateMode ? copy.programTemplates : copy.noActiveAssignment)
        : displayCopyOf(context).failureMessage(_failure!);
    return Center(
      child: Padding(
        padding: MayosSpacing.screen,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: MayosSpacing.md),
            MayosButton(
              label: coachCopyOf(context).retry,
              expand: false,
              onPressed: _retryLoad,
            ),
          ],
        ),
      ),
    );
  }

  void _retryLoad() {
    setState(() {
      _failure = null;
      _loading = true;
    });
    _loadDraft();
  }

  Widget _dayCard(BuildContext context, int index) {
    final _DraftDayEditor day = _days[index];
    return _ProgramDraftDayCard(
      index: index,
      dayCount: _days.length,
      day: day,
      busy: _busy,
      dayNameError: _serverError(index, 'day_name'),
      cardioError: _serverError(index, 'cardio'),
      dayError: _generalDayError(index),
      buildWarmupCard: (int movementIndex) =>
          _warmupMovementCard(index, movementIndex),
      buildExerciseCard: (int exerciseIndex) =>
          _exerciseCard(index, exerciseIndex),
      onReorderExercises: (int oldIndex, int newIndex) =>
          _reorderExercises(index, oldIndex, newIndex),
      onChanged: (String field) => setState(() {
        _hasUnsavedChanges = true;
        _serverErrors.remove((
          weekIndex: _selectedWeekIndex,
          dayIndex: index,
          exerciseIndex: null,
          warmupMovementIndex: null,
          field: field,
        ));
      }),
      onMove: (int delta) => _moveDay(index, delta),
      onDuplicate: () => _duplicateDay(index),
      onRemove: () => _removeDay(index),
      onAddWarmup: () => _addWarmupMovement(index),
      onAddExercise: () => _addExercise(index),
    );
  }

  Widget _warmupMovementCard(int dayIndex, int movementIndex) {
    final _DraftWarmupEditor movement = _days[dayIndex].warmups[movementIndex];
    return _ProgramDraftWarmupMovementCard(
      dayIndex: dayIndex,
      movementIndex: movementIndex,
      movementCount: _days[dayIndex].warmups.length,
      movement: movement,
      busy: _busy,
      errorFor: (String field) => _serverError(
        dayIndex,
        field,
        warmupMovementIndex: movementIndex,
      ),
      onChanged: (String field) => setState(() {
        _hasUnsavedChanges = true;
        _serverErrors.remove((
          weekIndex: _selectedWeekIndex,
          dayIndex: dayIndex,
          exerciseIndex: null,
          warmupMovementIndex: movementIndex,
          field: field,
        ));
      }),
      onMove: (int delta) => _moveWarmupMovement(dayIndex, movementIndex, delta),
      onRemove: () => _removeWarmupMovement(dayIndex, movementIndex),
      onInsertAbove: () => _insertWarmupMovement(dayIndex, movementIndex),
      onInsertBelow: () =>
          _insertWarmupMovement(dayIndex, movementIndex + 1),
    );
  }

  Widget _exerciseCard(int dayIndex, int exerciseIndex) {
    final _DraftExerciseEditor exercise =
        _days[dayIndex].exercises[exerciseIndex];
    return _ProgramDraftExerciseCard(
      dayIndex: dayIndex,
      exerciseIndex: exerciseIndex,
      exercise: exercise,
      busy: _busy,
      errorFor: (String field) => _serverError(
        dayIndex,
        field,
        exerciseIndex: exerciseIndex,
      ),
      onChanged: (String field) => setState(() {
        _hasUnsavedChanges = true;
        _serverErrors.remove((
          weekIndex: _selectedWeekIndex,
          dayIndex: dayIndex,
          exerciseIndex: exerciseIndex,
          warmupMovementIndex: null,
          field: field,
        ));
      }),
      onSwap: () => _swapExercise(dayIndex, exerciseIndex),
      onInsertAbove: () => _insertExercise(
        dayIndex,
        exerciseIndex,
        title: coachCopyOf(context).insertExerciseAbove,
      ),
      onInsertBelow: () => _insertExercise(
        dayIndex,
        exerciseIndex + 1,
        title: coachCopyOf(context).insertExerciseBelow,
      ),
      onDuplicate: () => _duplicateExercise(dayIndex, exerciseIndex),
      onRemove: () => _removeExercise(dayIndex, exerciseIndex),
    );
  }

  String? _serverError(
    int dayIndex,
    String field, {
    int? exerciseIndex,
    int? warmupMovementIndex,
  }) =>
      _serverErrors[(
        weekIndex: _selectedWeekIndex,
        dayIndex: dayIndex,
        exerciseIndex: exerciseIndex,
        warmupMovementIndex: warmupMovementIndex,
        field: field,
      )];

  String? _generalDayError(int dayIndex) {
    for (final MapEntry<_EditorErrorLocation, String> entry
        in _serverErrors.entries) {
      if (entry.key.weekIndex == _selectedWeekIndex &&
          entry.key.dayIndex == dayIndex &&
          entry.key.exerciseIndex == null &&
          entry.key.warmupMovementIndex == null &&
          entry.key.field != 'day_name' &&
          entry.key.field != 'cardio') {
        return entry.value;
      }
    }
    return null;
  }

  Future<void> _onPopInvoked(bool didPop, Object? result) async {
    if (!didPop && !_allowPop) await _requestPop();
  }

  Future<void> _requestPop() async {
    if (_busy) return;
    if (_hasUnsavedChanges) {
      final CoachCopy copy = coachCopyOf(context);
      if (!await _confirm(
        copy.leaveUnsavedChangesTitle,
        copy.leaveUnsavedChangesPrompt,
        copy.leaveWithoutSaving,
      )) {
        return;
      }
    }
    if (mounted) _popEditor();
  }

  void _popEditor([Object? result]) {
    setState(() => _allowPop = true);
    Navigator.of(context).pop(result);
  }


}

bool _moveListItem<T>(List<T> items, int index, int delta) {
  final int destination = index + delta;
  if (index < 0 || index >= items.length || destination < 0 || destination >= items.length) {
    return false;
  }
  items.insert(destination, items.removeAt(index));
  return true;
}

String? _trimToNull(String value) {
  final String trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}

Widget _editorErrorText(
  BuildContext context,
  String? message,
  MayosThemeExtension colors,
) {
  if (message == null) return const SizedBox.shrink();
  return Padding(
    padding: const EdgeInsets.only(top: MayosSpacing.xs),
    child: Text(
      message,
      style: MayosTypography.of(context).body.copyWith(color: colors.danger),
    ),
  );
}

Widget _editorNumberField({
  required Key key,
  required TextEditingController controller,
  required String label,
  String? errorText,
  bool enabled = true,
  bool allowRange = false,
  bool decimal = false,
  ValueChanged<String>? onChanged,
}) =>
    TextField(
      key: key,
      controller: controller,
      enabled: enabled,
      keyboardType: allowRange
          ? const TextInputType.numberWithOptions(signed: true)
          : decimal
              ? const TextInputType.numberWithOptions(decimal: true, signed: true)
              : TextInputType.number,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
        isDense: true,
        errorText: errorText,
      ),
      onChanged: onChanged,
    );

class _DraftWeekEditor {
  _DraftWeekEditor(this.source, this.days)
      : name = TextEditingController(text: source['week_name'] as String? ?? '');

  final Map<String, dynamic> source;
  final TextEditingController name;
  final List<_DraftDayEditor> days;

  Map<String, dynamic> toJson(int order, CoachCopy copy) => <String, dynamic>{
        ...source,
        'week_name': name.text.trim(),
        'week_order': order,
        'days': <Map<String, dynamic>>[
          for (int dayIndex = 0; dayIndex < days.length; dayIndex++)
            days[dayIndex].toJson(dayIndex + 1, copy, weekOrder: order),
        ],
      };

  _DraftWeekEditor copy() {
    final Map<String, dynamic> copiedSource =
        jsonDecode(jsonEncode(source)) as Map<String, dynamic>;
    copiedSource['days'] = <dynamic>[];
    return _DraftWeekEditor(
      copiedSource,
      days.map((_DraftDayEditor day) => day.copy()).toList(),
    )..name.text = name.text;
  }

  void dispose() {
    name.dispose();
    for (final _DraftDayEditor day in days) {
      day.dispose();
    }
  }
}

class _DraftDayEditor {
  _DraftDayEditor(this.source)
      : dayName = TextEditingController(
          text: source['day_name'] as String? ?? '',
        ),
        cardio = TextEditingController(text: source['cardio'] as String? ?? ''),
        warmups = <_DraftWarmupEditor>[
          for (final dynamic raw in
              source['warmup_exercises'] as List<dynamic>? ?? <dynamic>[])
            _DraftWarmupEditor(Map<String, dynamic>.from(raw as Map)),
        ],
        exercises = <_DraftExerciseEditor>[
          for (final dynamic raw
              in source['exercises'] as List<dynamic>? ?? <dynamic>[])
            _DraftExerciseEditor(Map<String, dynamic>.from(raw as Map)),
        ];

  final Map<String, dynamic> source;
  final TextEditingController dayName;
  final TextEditingController cardio;
  final List<_DraftWarmupEditor> warmups;
  final List<_DraftExerciseEditor> exercises;

  _DraftDayEditor copy() {
    final Map<String, dynamic> sourceCopy =
        jsonDecode(jsonEncode(source)) as Map<String, dynamic>;
    sourceCopy['warmup_exercises'] = <dynamic>[];
    sourceCopy['exercises'] = <dynamic>[];
    final _DraftDayEditor duplicate = _DraftDayEditor(
      sourceCopy,
    )
      ..dayName.text = dayName.text
      ..cardio.text = cardio.text;
    duplicate
      ..warmups.addAll(warmups.map((_DraftWarmupEditor item) => item.copy()))
      ..exercises.addAll(
        exercises.map((_DraftExerciseEditor item) => item.copy()),
      );
    return duplicate;
  }

  Map<String, dynamic> toJson(
    int order,
    CoachCopy copy, {
    int weekOrder = 1,
  }) => <String, dynamic>{
        ...source,
        'day_name': dayName.text.trim(),
        'day_order': order,
        'week_order': weekOrder,
        'warmup_exercises': <Map<String, dynamic>>[
          for (final _DraftWarmupEditor movement in warmups)
            movement.toJson(copy),
        ],
        'exercises': <Map<String, dynamic>>[
          for (final _DraftExerciseEditor exercise in exercises)
            exercise.toJson(copy),
        ],
        'cardio': _trimToNull(cardio.text),
      };

  void dispose() {
    dayName.dispose();
    cardio.dispose();
    for (final _DraftWarmupEditor movement in warmups) {
      movement.dispose();
    }
    for (final _DraftExerciseEditor exercise in exercises) {
      exercise.dispose();
    }
  }
}

class _DraftWarmupEditor {
  _DraftWarmupEditor(this.source)
      : name = TextEditingController(text: source['exercise_name'] as String? ?? ''),
        sets = TextEditingController(
            text: '${source['sets'] ?? ProgramDraftPrescription.defaultWarmupMovementSets}'),
        reps = TextEditingController(
            text: '${source['reps'] ?? ProgramDraftPrescription.defaultWarmupMovementReps}'),
        rest = TextEditingController(
            text: '${source['rest_seconds'] ?? ProgramDraftPrescription.defaultWarmupMovementRestSeconds}'),
        notes = TextEditingController(text: source['notes'] as String? ?? '');

  final Map<String, dynamic> source;
  final TextEditingController name;
  final TextEditingController sets;
  final TextEditingController reps;
  final TextEditingController rest;
  final TextEditingController notes;

  _DraftWarmupEditor copy() {
    final _DraftWarmupEditor duplicate = _DraftWarmupEditor(
      jsonDecode(jsonEncode(source)) as Map<String, dynamic>,
    );
    duplicate
      ..name.text = name.text
      ..sets.text = sets.text
      ..reps.text = reps.text
      ..rest.text = rest.text
      ..notes.text = notes.text;
    return duplicate;
  }

  Map<String, dynamic> toJson(CoachCopy copy) {
    final int setCount = _wholeNumber(sets, copy);
    final int repCount = _wholeNumber(reps, copy);
    if (setCount < ProgramDraftPrescription.minWarmupMovementSets ||
        setCount > ProgramDraftPrescription.maxWarmupMovementSets) {
      throw FormatException(copy.invalidMovementSets);
    }
    if (repCount < ProgramDraftPrescription.minWarmupMovementReps ||
        repCount > ProgramDraftPrescription.maxWarmupMovementReps) {
      throw FormatException(copy.invalidMovementReps);
    }
    return <String, dynamic>{
      ...source,
      'exercise_name': name.text.trim(),
      'sets': setCount,
      'reps': repCount,
      'rest_seconds': _wholeNumber(rest, copy),
      'notes': _trimToNull(notes.text),
    };
  }

  void dispose() {
    name.dispose();
    sets.dispose();
    reps.dispose();
    rest.dispose();
    notes.dispose();
  }
}

int _wholeNumber(TextEditingController controller, CoachCopy copy) {
  final int? value = int.tryParse(controller.text.trim());
  if (value == null) throw FormatException(copy.invalidWholeNumber);
  return value;
}

Map<String, dynamic> _exerciseIdentity(ExerciseCatalogEntry selected) =>
    <String, dynamic>{
      'exercise_id': selected.id,
      'exercise_name': selected.name,
      'body_part': selected.bodyPart,
      'equipment': selected.equipment,
      'note': selected.note,
      'video_url': selected.videoUrl,
      'is_coach_exercise': selected.isCoachExercise,
      'image_path': selected.imagePath,
    };

class _DraftExerciseEditor {
  _DraftExerciseEditor(this.source)
      : sets = TextEditingController(
          text: '${source['target_sets'] ?? ProgramDraftPrescription.defaultSets}',
        ),
        reps = TextEditingController(
          text: _repsText(
            source['target_reps_min'] as num? ??
                ProgramDraftPrescription.defaultMinReps,
            source['target_reps_max'] as num? ??
                ProgramDraftPrescription.defaultMaxReps,
          ),
        ),
        rir = TextEditingController(
          text: _rirText(
            source['target_rir'] as num? ?? ProgramDraftPrescription.defaultRir,
          ),
        ),
        warmupSets = TextEditingController(
            text: '${source['warmup_sets'] ?? ProgramDraftPrescription.minWarmupSets}'),
        rest = TextEditingController(
            text: '${source['rest_seconds'] ?? ProgramDraftPrescription.defaultExerciseRestSeconds}'),
        tempo = TextEditingController(text: source['tempo'] as String? ?? ''),
        notes = TextEditingController(text: source['notes'] as String? ?? '');

  final Map<String, dynamic> source;
  final TextEditingController sets;
  final TextEditingController reps;
  final TextEditingController rir;
  final TextEditingController warmupSets;
  final TextEditingController rest;
  final TextEditingController tempo;
  final TextEditingController notes;

  String get exerciseName => source['exercise_name'] as String? ?? '';

  void swapIdentity(ExerciseCatalogEntry selected) {
    source.addAll(_exerciseIdentity(selected));
    source['suggested_substitutes'] = <dynamic>[];
  }

  static String _repsText(num lower, num upper) =>
      lower == upper ? '$lower' : '$lower-$upper';

  static String _rirText(num value) =>
      value == value.roundToDouble() ? value.toInt().toString() : '$value';

  _DraftExerciseEditor copy() {
    final _DraftExerciseEditor duplicate = _DraftExerciseEditor(
      jsonDecode(jsonEncode(source)) as Map<String, dynamic>,
    );
    duplicate
      ..sets.text = sets.text
      ..reps.text = reps.text
      ..rir.text = rir.text
      ..warmupSets.text = warmupSets.text
      ..rest.text = rest.text
      ..tempo.text = tempo.text
      ..notes.text = notes.text;
    return duplicate;
  }

  Map<String, dynamic> toJson(CoachCopy copy) {
    final int? workingSets = int.tryParse(sets.text.trim());
    if (workingSets == null || workingSets < 1) {
      throw FormatException(copy.invalidSetCount);
    }
    final RegExp range = RegExp(r'^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$');
    final RegExpMatch? match = range.firstMatch(reps.text);
    if (match == null) throw FormatException(copy.invalidRepTarget);
    final int lowerReps = int.parse(match.group(1)!);
    final int upperReps = int.parse(match.group(2) ?? match.group(1)!);
    final double? targetRir = double.tryParse(rir.text.trim());
    if (lowerReps < ProgramDraftPrescription.minReps ||
        upperReps > ProgramDraftPrescription.maxReps ||
        lowerReps > upperReps) {
      throw FormatException(copy.invalidRepTarget);
    }
    if (targetRir == null ||
        targetRir < ProgramDraftPrescription.minRir ||
        targetRir > ProgramDraftPrescription.maxRir) {
      throw FormatException(copy.invalidRirTarget);
    }
    final int rampedWarmupSets = _wholeNumber(warmupSets, copy);
    if (rampedWarmupSets < ProgramDraftPrescription.minWarmupSets ||
        rampedWarmupSets > ProgramDraftPrescription.maxWarmupSets) {
      throw FormatException(copy.invalidWarmupSets);
    }
    return <String, dynamic>{
      ...source,
      'target_sets': workingSets,
      'target_reps_min': lowerReps,
      'target_reps_max': upperReps,
      'target_rir': targetRir,
      'warmup_sets': rampedWarmupSets,
      'rest_seconds': _wholeNumber(rest, copy),
      'tempo': _trimToNull(tempo.text),
      'notes': _trimToNull(notes.text),
    };
  }

  void dispose() {
    sets.dispose();
    reps.dispose();
    rir.dispose();
    warmupSets.dispose();
    rest.dispose();
    tempo.dispose();
    notes.dispose();
  }
}
