import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
import '../player/exercise_picker_dialog.dart';

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
  final TextEditingController _dayName = TextEditingController();
  final List<_DraftExerciseEditor> _exercises = <_DraftExerciseEditor>[];
  Map<String, dynamic>? _draft;
  bool _loading = true;
  bool _saving = false;
  bool _publishing = false;
  bool _discarding = false;
  FailureMessage? _failure;
  String? _inputError;
  String? _serverDayError;
  String? _serverSummary;
  final Map<int, Map<String, String>> _serverExerciseErrors =
      <int, Map<String, String>>{};

  @override
  void initState() {
    super.initState();
    _loadDraft();
  }

  @override
  void dispose() {
    _dayName.dispose();
    for (final _DraftExerciseEditor exercise in _exercises) {
      exercise.dispose();
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
    if (days.isEmpty) days.addAll(_emptyDraft()['days'] as List<dynamic>);
    final Map<String, dynamic> firstDay = days.first as Map<String, dynamic>;
    _dayName.text = firstDay['day_name'] as String? ??
        coachCopyOf(context).firstTrainingDay;
    for (final dynamic rawExercise
        in firstDay['exercises'] as List<dynamic>? ?? <dynamic>[]) {
      _exercises.add(
        _DraftExerciseEditor(_copyMap(rawExercise as Map<String, dynamic>)),
      );
    }
    setState(() {
      _draft = draft;
      _loading = false;
      _failure = null;
    });
  }

  Map<String, dynamic> _copyMap(Map<String, dynamic> source) =>
      jsonDecode(jsonEncode(source)) as Map<String, dynamic>;

  Map<String, dynamic> _serializedDraft() {
    final Map<String, dynamic> draft = _copyMap(_draft!);
    final List<dynamic> days = draft['days'] as List<dynamic>;
    final Map<String, dynamic> firstDay = days.first as Map<String, dynamic>;
    firstDay['day_name'] = _dayName.text.trim();
    firstDay['exercises'] = <Map<String, dynamic>>[
      for (final _DraftExerciseEditor exercise in _exercises)
        exercise.toJson(coachCopyOf(context)),
    ];
    return draft;
  }

  Future<void> _addExercise() async {
    final ExerciseCatalogEntry? selected =
        await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => const ExercisePickerDialog(),
    );
    if (selected == null || !mounted) return;
    setState(() {
      _exercises.add(
        _DraftExerciseEditor(<String, dynamic>{
          'exercise_id': selected.id,
          'exercise_name': selected.name,
          'equipment': selected.equipment,
          'image_path': selected.imagePath,
          'warmup_sets': 0,
          'target_sets': ProgramDraftPrescription.defaultSets,
          'target_reps_min': ProgramDraftPrescription.defaultMinReps,
          'target_reps_max': ProgramDraftPrescription.defaultMaxReps,
          'target_rir': ProgramDraftPrescription.defaultRir,
          'rest_seconds': 180,
          'notes': null,
          'suggested_substitutes': <dynamic>[],
        }),
      );
      _inputError = null;
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
      setState(() => _draft = _copyMap(saved['draft'] as Map<String, dynamic>));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(coachCopyOf(context).draftSaved)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _failure = apiFailureMessage(error));
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
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(copy.cancel),
              ),
              TextButton(
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
    if (!await _confirm(
      copy.publishDraft,
      copy.confirmPublishDraft,
      copy.publish,
    )) {
      return;
    }
    final Map<String, dynamic>? draft = _draftForSave();
    if (draft == null || !mounted) return;
    setState(() {
      _publishing = true;
      _failure = null;
      _inputError = null;
      _clearServerErrors();
    });
    try {
      await ref.read(apiClientProvider).coachReplaceProgramDraft(
            widget.assignmentId,
            draft,
          );
      final TrainingProgram program = await ref
          .read(apiClientProvider)
          .coachPublishProgramDraft(widget.assignmentId);
      if (mounted) Navigator.of(context).pop(program);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.serverDetails?['errors'] is List) {
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
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _discarding = false);
    }
  }

  void _removeExercise(int index) {
    final _DraftExerciseEditor removed = _exercises.removeAt(index);
    removed.dispose();
    setState(() {
      _inputError = null;
      _clearServerErrors();
    });
  }

  void _clearServerErrors() {
    _serverDayError = null;
    _serverSummary = null;
    _serverExerciseErrors.clear();
  }

  void _applyServerValidation(Map<String, dynamic> details) {
    final CoachCopy copy = coachCopyOf(context);
    final List<dynamic> issues = details['errors'] as List<dynamic>;
    final List<String> summary = <String>[];
    for (final dynamic rawIssue in issues) {
      if (rawIssue is! Map) continue;
      final Map<String, dynamic> issue = Map<String, dynamic>.from(rawIssue);
      final String code = issue['code'] as String? ?? 'invalid_program_field';
      final Map<String, dynamic> location =
          issue['location'] is Map<String, dynamic>
              ? issue['location'] as Map<String, dynamic>
              : <String, dynamic>{};
      final String message = copy.programDraftValidationMessage(code);
      final int? exerciseIndex = location['exercise_index'] as int?;
      final String field = location['field'] as String? ?? 'program';
      if (exerciseIndex != null &&
          exerciseIndex >= 0 &&
          exerciseIndex < _exercises.length) {
        _serverExerciseErrors.putIfAbsent(
          exerciseIndex,
          () => <String, String>{},
        )[field] = message;
      } else if (location['day_index'] == 0) {
        _serverDayError = message;
      } else {
        summary.add(message);
      }
    }
    _serverSummary = summary.isEmpty ? null : summary.join('\n');
  }

  Widget _fieldError(int index, String field, MayosThemeExtension colors) {
    final String? message = _serverExerciseErrors[index]?[field];
    if (message == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Text(
        message,
        style: MayosTypography.body.copyWith(color: colors.danger),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(copy.writeProgram)),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _draft == null
              ? _loadError(context)
              : Column(
                  children: <Widget>[
                    Expanded(
                      child: ListView(
                        padding: MayosSpacing.screen,
                        children: <Widget>[
                          Text(widget.playerUsername,
                              style: MayosTypography.sectionHeading),
                          const SizedBox(height: MayosSpacing.md),
                          MayosCard(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                Text(copy.trainingDay,
                                    style: MayosTypography.sectionHeading),
                                const SizedBox(height: MayosSpacing.sm),
                                TextField(
                                  key: const Key('program_draft_day_name'),
                                  controller: _dayName,
                                  decoration: InputDecoration(
                                    labelText: copy.dayName,
                                    border: const OutlineInputBorder(),
                                  ),
                                ),
                                if (_serverDayError != null) ...<Widget>[
                                  const SizedBox(height: MayosSpacing.xs),
                                  Text(
                                    _serverDayError!,
                                    style: MayosTypography.body
                                        .copyWith(color: colors.danger),
                                  ),
                                ],
                              ],
                            ),
                          ),
                          const SizedBox(height: MayosSpacing.md),
                          for (int index = 0;
                              index < _exercises.length;
                              index++)
                            _exerciseCard(context, index),
                          MayosButton(
                            key: const Key('program_draft_add_exercise'),
                            label: copy.addExercise,
                            icon: Icons.add,
                            variant: MayosButtonVariant.secondary,
                            onPressed:
                                _publishing || _saving ? null : _addExercise,
                          ),
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
                              onPressed: _publishing || _discarding
                                  ? null
                                  : _saveDraft,
                            ),
                            const SizedBox(height: MayosSpacing.xs),
                            MayosButton(
                              key: const Key('program_draft_publish'),
                              label: copy.publishDraft,
                              loading: _publishing,
                              onPressed:
                                  _saving || _discarding ? null : _publishDraft,
                            ),
                            MayosButton(
                              key: const Key('program_draft_discard'),
                              label: copy.discardDraft,
                              variant: MayosButtonVariant.tertiary,
                              loading: _discarding,
                              onPressed: _saving || _publishing || _discarding
                                  ? null
                                  : _discardDraft,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
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

  Widget _exerciseCard(BuildContext context, int index) {
    final copy = coachCopyOf(context);
    final _DraftExerciseEditor exercise = _exercises[index];
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    exercise.exerciseName,
                    style: MayosTypography.sectionHeading,
                  ),
                ),
                IconButton(
                  key: Key('program_draft_remove_$index'),
                  tooltip: copy.removeExercise,
                  onPressed: _saving || _publishing || _discarding
                      ? null
                      : () => _removeExercise(index),
                  icon: Icon(Icons.delete_outline, color: colors.danger),
                ),
              ],
            ),
            _fieldError(index, 'exercise_id', colors),
            Row(
              children: <Widget>[
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      _numberField(
                        key: Key('program_draft_sets_$index'),
                        controller: exercise.sets,
                        label: copy.workingSets,
                        onChanged: (_) => setState(
                          () =>
                              _serverExerciseErrors[index]?.remove('target_sets'),
                        ),
                      ),
                      _fieldError(index, 'target_sets', colors),
                    ],
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      _numberField(
                        key: Key('program_draft_reps_$index'),
                        controller: exercise.reps,
                        label: copy.repsOrRange,
                        allowRange: true,
                        onChanged: (_) => setState(() {
                          _serverExerciseErrors[index]
                            ?..remove('target_reps_min')
                            ..remove('target_reps_max');
                        }),
                      ),
                      _fieldError(index, 'target_reps_min', colors),
                      _fieldError(index, 'target_reps_max', colors),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.sm),
            SizedBox(
              width: 140,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  _numberField(
                    key: Key('program_draft_rir_$index'),
                    controller: exercise.rir,
                    label: copy.targetRir,
                    decimal: true,
                    onChanged: (_) => setState(() {
                      _serverExerciseErrors[index]
                        ?..remove('target_rpe')
                        ..remove('target_rir');
                    }),
                  ),
                  _fieldError(index, 'target_rpe', colors),
                  _fieldError(index, 'target_rir', colors),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _numberField({
    required Key key,
    required TextEditingController controller,
    required String label,
    bool allowRange = false,
    bool decimal = false,
    ValueChanged<String>? onChanged,
  }) =>
      TextField(
        key: key,
        controller: controller,
        keyboardType: allowRange
            ? const TextInputType.numberWithOptions(signed: true)
            : decimal
                ? const TextInputType.numberWithOptions(
                    decimal: true, signed: true)
                : TextInputType.number,
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
          isDense: true,
        ),
        onChanged: onChanged,
      );
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
        );

  final Map<String, dynamic> source;
  final TextEditingController sets;
  final TextEditingController reps;
  final TextEditingController rir;

  String get exerciseName => source['exercise_name'] as String? ?? '';

  static String _repsText(num lower, num upper) =>
      lower == upper ? '$lower' : '$lower-$upper';

  static String _rirText(num value) =>
      value == value.roundToDouble() ? value.toInt().toString() : '$value';

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
    return <String, dynamic>{
      ...source,
      'target_sets': workingSets,
      'target_reps_min': lowerReps,
      'target_reps_max': upperReps,
      'target_rir': targetRir,
    };
  }

  void dispose() {
    sets.dispose();
    reps.dispose();
    rir.dispose();
  }
}
