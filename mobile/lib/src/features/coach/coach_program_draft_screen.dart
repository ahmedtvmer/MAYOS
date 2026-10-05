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

part 'program_editor/day_card.dart';
part 'program_editor/exercise_card.dart';
part 'program_editor/warmup_movement_card.dart';

typedef _EditorErrorLocation = ({
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
  });

  final String assignmentId;
  final String playerUsername;

  @override
  ConsumerState<CoachProgramDraftScreen> createState() =>
      _CoachProgramDraftScreenState();
}

class _CoachProgramDraftScreenState
    extends ConsumerState<CoachProgramDraftScreen> {
  final List<_DraftDayEditor> _days = <_DraftDayEditor>[];
  Map<String, dynamic>? _draft;
  bool _loading = true;
  bool _saving = false;
  bool _publishing = false;
  bool _discarding = false;
  bool _hasUnsavedChanges = false;
  bool _allowPop = false;
  FailureMessage? _failure;
  String? _inputError;
  String? _serverSummary;
  final Map<_EditorErrorLocation, String> _serverErrors =
      <_EditorErrorLocation, String>{};

  bool get _busy => _saving || _publishing || _discarding;

  @override
  void initState() {
    super.initState();
    _loadDraft();
  }

  @override
  void dispose() {
    for (final _DraftDayEditor day in _days) {
      day.dispose();
    }
    super.dispose();
  }

  Future<void> _loadDraft() async {
    final ApiClient api = ref.read(apiClientProvider);
    try {
      Map<String, dynamic> envelope;
      try {
        envelope = await api.coachReadProgramDraft(widget.assignmentId);
      } on ApiException catch (error) {
        if (error.statusCode != 404) rethrow;
        envelope = await api.coachCreateProgramDraft(
          widget.assignmentId,
          draft: _emptyDraft(),
        );
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
    return <String, dynamic>{
      'program_name': copy.customProgram,
      'split_type': 'custom',
      'weekly_frequency': 1,
      'instructions': '',
      'days': <Map<String, dynamic>>[
        <String, dynamic>{
          'day_name': copy.firstTrainingDay,
          'day_order': 1,
          'warmup_exercises': <dynamic>[],
          'exercises': <dynamic>[],
          'cardio': null,
        },
      ],
    };
  }

  void _applyEnvelope(Map<String, dynamic> envelope) {
    final Map<String, dynamic> draft = _copyMap(
      envelope['draft'] as Map<String, dynamic>,
    );
    final List<dynamic> days = draft['days'] as List<dynamic>? ?? <dynamic>[];
    for (final _DraftDayEditor day in _days) {
      day.dispose();
    }
    _days
      ..clear()
      ..addAll(
        days.map(
          (dynamic rawDay) => _DraftDayEditor(
            _copyMap(rawDay as Map<String, dynamic>),
          ),
        ),
      );
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
    draft['weekly_frequency'] = _days.length.clamp(1, ProgramDraftPrescription.maxDays);
    draft['days'] = <Map<String, dynamic>>[
      for (int index = 0; index < _days.length; index++)
        _days[index].toJson(index + 1, coachCopyOf(context)),
    ];
    return draft;
  }

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

  void _syncDayOrders() {
    for (int index = 0; index < _days.length; index++) {
      _days[index].source['day_order'] = index + 1;
    }
    if (_draft != null) {
      _draft!['weekly_frequency'] = _days.length.clamp(1, ProgramDraftPrescription.maxDays);
    }
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

  Future<void> _addExercise(int dayIndex) async {
    final ExerciseCatalogEntry? selected =
        await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => const CoachExercisePickerDialog(),
    );
    if (selected == null || !mounted) return;
    setState(() {
      _days[dayIndex].exercises.add(
        _DraftExerciseEditor(<String, dynamic>{
          'exercise_id': selected.id,
          'exercise_name': selected.name,
          'body_part': selected.bodyPart,
          'equipment': selected.equipment,
          'note': selected.note,
          'video_url': selected.videoUrl,
          'is_coach_exercise': selected.isCoachExercise,
          'image_path': selected.imagePath,
          'warmup_sets': 0,
          'target_sets': ProgramDraftPrescription.defaultSets,
          'target_reps_min': ProgramDraftPrescription.defaultMinReps,
          'target_reps_max': ProgramDraftPrescription.defaultMaxReps,
          'target_rir': ProgramDraftPrescription.defaultRir,
          'rest_seconds': ProgramDraftPrescription.defaultExerciseRestSeconds,
          'tempo': null,
          'notes': null,
          'suggested_substitutes': <dynamic>[],
        }),
      );
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
    final Map<String, dynamic>? draft = _draftForSave();
    if (draft == null) return;
    setState(() {
      _saving = true;
      _failure = null;
      _inputError = null;
      _clearServerErrors();
    });
    try {
      final Map<String, dynamic> saved = await ref
          .read(apiClientProvider)
          .coachReplaceProgramDraft(widget.assignmentId, draft);
      if (!mounted) return;
      setState(() {
        _draft = _copyMap(saved['draft'] as Map<String, dynamic>);
        _hasUnsavedChanges = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(coachCopyOf(context).draftSaved)),
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
      widget.assignmentId,
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
            widget.assignmentId,
            draft,
      );
      if (mounted) setState(() => _hasUnsavedChanges = false);
      final CoachProgramPublication publication =
          await api.coachPublishProgramDraft(
        widget.assignmentId,
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
          .coachDiscardProgramDraft(widget.assignmentId);
      if (mounted) _popEditor();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _discarding = false);
    }
  }

  void _moveExercise(int dayIndex, int index, int delta) {
    final List<_DraftExerciseEditor> exercises = _days[dayIndex].exercises;
    if (!_moveListItem(exercises, index, delta)) return;
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

  void _addWarmupMovement(int dayIndex) {
    setState(() {
      _hasUnsavedChanges = true;
      _days[dayIndex].warmups.add(_DraftWarmupEditor(<String, dynamic>{
        'exercise_name': '',
        'sets': ProgramDraftPrescription.defaultWarmupMovementSets,
        'reps': ProgramDraftPrescription.defaultWarmupMovementReps,
        'rest_seconds': ProgramDraftPrescription.defaultWarmupMovementRestSeconds,
        'notes': null,
      }));
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
      final String field = normalized['field'] as String;
      final String? code = normalized['code'] as String?;
      final String rendered = code == null
          ? message
          : copy.programDraftValidationMessage(code);
      final _EditorErrorLocation location = (
        dayIndex: dayIndex ?? -1,
        exerciseIndex: exerciseIndex,
        warmupMovementIndex: movementIndex,
        field: field,
      );
      if (dayIndex == null || dayIndex < 0 || dayIndex >= _days.length) {
        summary.add(rendered);
      } else if (movementIndex != null &&
          movementIndex >= 0 &&
          movementIndex < _days[dayIndex].warmups.length &&
          const <String>{'exercise_name', 'sets', 'reps', 'rest_seconds', 'notes'}
              .contains(field)) {
        _serverErrors[location] = rendered;
      } else if (exerciseIndex != null &&
          exerciseIndex >= 0 &&
          exerciseIndex < _days[dayIndex].exercises.length &&
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
    int? dayIndex;
    int? exerciseIndex;
    int? movementIndex;
    String field = 'program';
    final int dayAt = location.indexOf('days');
    if (dayAt >= 0 && location.length > dayAt + 1 && location[dayAt + 1] is int) {
      dayIndex = location[dayAt + 1] as int;
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
        title: Text(copy.writeProgram),
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
                              Text(widget.playerUsername,
                                  style: MayosTypography.sectionHeading),
                              const SizedBox(height: MayosSpacing.md),
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
                                  style: MayosTypography.body
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
                              label: copy.saveDraft,
                              variant: MayosButtonVariant.secondary,
                              loading: _saving,
                              onPressed: _busy ? null : _saveDraft,
                            ),
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
                        ),
                      ),
                    ),
                  ],
                ),
      ),
    );
  }

  Widget _loadError(BuildContext context) {
    final String message = _failure == null
        ? coachCopyOf(context).noActiveAssignment
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
      onChanged: (String field) => setState(() {
        _hasUnsavedChanges = true;
        _serverErrors.remove((
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
          dayIndex: dayIndex,
          exerciseIndex: null,
          warmupMovementIndex: movementIndex,
          field: field,
        ));
      }),
      onMove: (int delta) => _moveWarmupMovement(dayIndex, movementIndex, delta),
      onRemove: () => _removeWarmupMovement(dayIndex, movementIndex),
    );
  }

  Widget _exerciseCard(int dayIndex, int exerciseIndex) {
    final _DraftExerciseEditor exercise =
        _days[dayIndex].exercises[exerciseIndex];
    return _ProgramDraftExerciseCard(
      dayIndex: dayIndex,
      exerciseIndex: exerciseIndex,
      exerciseCount: _days[dayIndex].exercises.length,
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
          dayIndex: dayIndex,
          exerciseIndex: exerciseIndex,
          warmupMovementIndex: null,
          field: field,
        ));
      }),
      onMove: (int delta) => _moveExercise(dayIndex, exerciseIndex, delta),
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
        dayIndex: dayIndex,
        exerciseIndex: exerciseIndex,
        warmupMovementIndex: warmupMovementIndex,
        field: field,
      )];

  String? _generalDayError(int dayIndex) {
    for (final MapEntry<_EditorErrorLocation, String> entry
        in _serverErrors.entries) {
      if (entry.key.dayIndex == dayIndex &&
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

Widget _editorErrorText(String? message, MayosThemeExtension colors) {
  if (message == null) return const SizedBox.shrink();
  return Padding(
    padding: const EdgeInsets.only(top: MayosSpacing.xs),
    child: Text(
      message,
      style: MayosTypography.body.copyWith(color: colors.danger),
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

  Map<String, dynamic> toJson(int order, CoachCopy copy) => <String, dynamic>{
        ...source,
        'day_name': dayName.text.trim(),
        'day_order': order,
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
