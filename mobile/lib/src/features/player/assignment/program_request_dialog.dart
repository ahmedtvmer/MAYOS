import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/assignment_copy.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';

/// The read-only substitution slot shown before the player enters a reason.
class ProgramSubstitutionRequestPrefill {
  const ProgramSubstitutionRequestPrefill({
    required this.dayName,
    required this.weekOrder,
    required this.dayOrder,
    required this.exerciseId,
    required this.exerciseName,
    required this.replacementExerciseId,
    required this.replacementName,
  });

  final String dayName;
  final int weekOrder;
  final int dayOrder;
  final String exerciseId;
  final String exerciseName;
  final String replacementExerciseId;
  final String replacementName;
}

/// The shared request form used from both the assignment page and Program tab.
class ProgramRequestDialog extends StatefulWidget {
  const ProgramRequestDialog({
    super.key,
    this.initialDraft,
    this.onSubmit,
  }) : substitution = null;

  const ProgramRequestDialog.forSubstitution({
    super.key,
    required this.substitution,
  })  : assert(substitution != null),
        initialDraft = null,
        onSubmit = null;

  final ProgramSubstitutionRequestPrefill? substitution;
  final ProgramRequestDraft? initialDraft;
  final Future<ProgramRequest> Function(ProgramRequestDraft draft)? onSubmit;

  @override
  State<ProgramRequestDialog> createState() => _ProgramRequestDialogState();
}

Future<ProgramRequest?> requestProgramChange(
  BuildContext context,
  WidgetRef ref, {
  ProgramRequestDraft? initialDraft,
  VoidCallback? onSubmitting,
  VoidCallback? onFinished,
}) =>
    _showProgramRequestDialog(
      context,
      initialDraft,
      (ProgramRequestDraft draft) {
        onSubmitting?.call();
        return _createProgramRequest(ref, draft);
      },
      onFinished,
    );

Future<ProgramRequest?> _showProgramRequestDialog(
  BuildContext context,
  ProgramRequestDraft? initialDraft,
  Future<ProgramRequest> Function(ProgramRequestDraft draft) onSubmit,
  VoidCallback? onFinished,
) async {
  try {
    return await showDialog<ProgramRequest>(
      context: context,
      builder: (_) => ProgramRequestDialog(
        initialDraft: initialDraft,
        onSubmit: onSubmit,
      ),
    );
  } finally {
    onFinished?.call();
  }
}

Future<ProgramRequest> _createProgramRequest(
  WidgetRef ref,
  ProgramRequestDraft draft,
) =>
    ref.read(apiClientProvider).createPlayerProgramRequest(
          kind: draft.kind,
          dayName: draft.dayName,
          weekOrder: draft.weekOrder,
          dayOrder: draft.dayOrder,
          exerciseId: draft.exerciseId,
          replacementExerciseId: draft.replacementExerciseId,
          desiredWeeklyFrequency: draft.desiredWeeklyFrequency,
          desiredSplitPreference: draft.desiredSplitPreference,
          reason: draft.reason,
        );

class _ProgramRequestDialogState extends State<ProgramRequestDialog> {
  late final TextEditingController _day;
  late final TextEditingController _exercise;
  late final TextEditingController _replacement;
  final TextEditingController _preference = TextEditingController();
  final TextEditingController _reason = TextEditingController();
  late String _kind;
  int? _frequency;
  String? _localError;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _kind = widget.initialDraft?.kind ?? 'exercise_substitution';
    _frequency = widget.initialDraft == null
        ? 4
        : widget.initialDraft!.desiredWeeklyFrequency;
    _day = TextEditingController(
      text: widget.substitution?.dayName ?? widget.initialDraft?.dayName,
    );
    _exercise = TextEditingController(
      text: widget.substitution?.exerciseId ?? widget.initialDraft?.exerciseId,
    );
    _replacement = TextEditingController(
      text: widget.substitution?.replacementExerciseId ??
          widget.initialDraft?.replacementExerciseId,
    );
    _preference.text = widget.initialDraft?.desiredSplitPreference ?? '';
    _reason.text = widget.initialDraft?.reason ?? '';
  }

  @override
  void dispose() {
    _day.dispose();
    _exercise.dispose();
    _replacement.dispose();
    _preference.dispose();
    _reason.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting || !_validateAndShowError()) return;
    final ProgramRequestDraft draft = _buildDraft();
    final Future<ProgramRequest> Function(ProgramRequestDraft draft)? submit =
        widget.onSubmit;
    if (submit == null) {
      Navigator.of(context).pop(draft);
      return;
    }

    await _submitToServer(draft, submit);
  }

  bool _validateAndShowError() {
    final String? error = _validationError(context);
    if (error == null) return true;
    setState(() => _localError = error);
    return false;
  }

  Future<void> _submitToServer(
    ProgramRequestDraft draft,
    Future<ProgramRequest> Function(ProgramRequestDraft draft) submit,
  ) async {
    _beginSubmission();
    ProgramRequest? created;
    try {
      created = await submit(draft);
    } on ApiException catch (error) {
      _showSubmissionError(error);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
    if (created != null && mounted) Navigator.of(context).pop(created);
  }

  void _beginSubmission() {
    setState(() {
      _submitting = true;
      _localError = null;
    });
  }

  void _showSubmissionError(ApiException error) {
    if (!mounted) return;
    setState(() {
      _localError =
          displayCopyOf(context).failureMessage(mutationFailureMessage(error));
    });
  }

  String? _validationError(BuildContext context) {
    final AssignmentCopy copy = assignmentCopyOf(context);
    if (_reason.text.trim().isEmpty) return copy.reasonRequired;
    if (_reason.text.trim().runes.length > maxProgramRequestReasonChars) {
      return copy.reasonTooLong;
    }
    if (_kind == 'exercise_substitution' &&
        (_day.text.trim().isEmpty ||
            _exercise.text.trim().isEmpty ||
            _replacement.text.trim().isEmpty)) {
      return copy.chooseSubstitutionValues;
    }
    if (_kind == 'split_change' && _frequency == null) {
      return copy.chooseFrequency;
    }
    return null;
  }

  ProgramRequestDraft _buildDraft() => ProgramRequestDraft(
        kind: _kind,
        reason: _reason.text.trim(),
        dayName: _kind == 'exercise_substitution' ? _day.text.trim() : null,
        weekOrder: widget.substitution?.weekOrder ?? widget.initialDraft?.weekOrder,
        dayOrder: widget.substitution?.dayOrder ?? widget.initialDraft?.dayOrder,
        exerciseId:
            _kind == 'exercise_substitution' ? _exercise.text.trim() : null,
        replacementExerciseId:
            _kind == 'exercise_substitution' ? _replacement.text.trim() : null,
        desiredWeeklyFrequency: _kind == 'split_change' ? _frequency : null,
        desiredSplitPreference:
            _kind == 'split_change' ? _preference.text.trim() : null,
      );

  Widget _buildRequestTypeField(BuildContext context) {
    final AssignmentCopy copy = assignmentCopyOf(context);
    return DropdownButtonFormField<String>(
      key: const Key('program_request_kind_field'),
      isExpanded: true,
      initialValue: _kind,
      decoration: InputDecoration(
          labelText: copy.requestType, border: OutlineInputBorder()),
      items: <DropdownMenuItem<String>>[
        DropdownMenuItem<String>(
            value: 'exercise_substitution',
            child: Text(copy.exerciseSubstitutionRequest)),
        DropdownMenuItem<String>(
            value: 'split_change', child: Text(copy.splitChange)),
      ],
      onChanged: (String? value) => setState(() {
        _kind = value ?? _kind;
        _localError = null;
      }),
    );
  }

  Widget _buildReadOnlyValue(
          BuildContext context, String label, String value) =>
      InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
        child: Align(
          alignment: AlignmentDirectional.centerStart,
          child: Text(
            value,
            style: MayosTypography.of(context).body.copyWith(
              color: MayosTheme.of(context).textPrimary,
            ),
            textDirection: TextDirection.ltr,
          ),
        ),
      );

  List<Widget> _buildSubstitutionFields() {
    final AssignmentCopy copy = assignmentCopyOf(context);
    final ProgramSubstitutionRequestPrefill? prefill = widget.substitution;
    if (prefill != null) {
      return <Widget>[
        _buildReadOnlyValue(context, copy.day, prefill.dayName),
        const SizedBox(height: MayosSpacing.md),
        _buildReadOnlyValue(context, copy.exercise, prefill.exerciseName),
        const SizedBox(height: MayosSpacing.md),
        _buildReadOnlyValue(context, copy.replacement, prefill.replacementName),
      ];
    }
    return <Widget>[
      MayosTextField(
        fieldKey: const Key('program_request_day_field'),
        controller: _day,
        label: copy.dayName,
      ),
      const SizedBox(height: MayosSpacing.md),
      Directionality(
        textDirection: TextDirection.ltr,
        child: MayosTextField(
          fieldKey: const Key('program_request_exercise_field'),
          controller: _exercise,
          label: copy.currentExerciseId,
        ),
      ),
      const SizedBox(height: MayosSpacing.md),
      Directionality(
        textDirection: TextDirection.ltr,
        child: MayosTextField(
          fieldKey: const Key('program_request_replacement_field'),
          controller: _replacement,
          label: copy.replacementExerciseId,
        ),
      ),
    ];
  }

  List<Widget> _buildSplitChangeFields() {
    final AssignmentCopy copy = assignmentCopyOf(context);
    return <Widget>[
      DropdownButtonFormField<int>(
        key: const Key('program_request_frequency_field'),
        isExpanded: true,
        initialValue: _frequency,
        hint: Text(copy.chooseFrequency),
        decoration: InputDecoration(
            labelText: copy.daysPerWeek, border: OutlineInputBorder()),
        items: <DropdownMenuItem<int>>[
          for (int day = 1; day <= 5; day++)
            DropdownMenuItem<int>(
                value: day,
                child: Text('$day', textDirection: TextDirection.ltr)),
        ],
        onChanged: (int? value) => setState(() {
          _frequency = value;
          _localError = null;
        }),
      ),
      const SizedBox(height: MayosSpacing.md),
      MayosTextField(
        fieldKey: const Key('program_request_split_field'),
        controller: _preference,
        label: copy.splitPreferenceOptional,
        onChanged: (_) => setState(() => _localError = null),
      ),
    ];
  }

  List<Widget> _buildReasonFields(
      BuildContext context, MayosThemeExtension colors) {
    final AssignmentCopy copy = assignmentCopyOf(context);
    final int reasonLength = _reason.text.trim().runes.length;
    return <Widget>[
      MayosTextField(
        fieldKey: const Key('program_request_reason_field'),
        controller: _reason,
        maxLines: 2,
        label: copy.reason,
        onChanged: (_) => setState(() => _localError = null),
      ),
      const SizedBox(height: MayosSpacing.xxs),
      Align(
        alignment: AlignmentDirectional.centerEnd,
        child: Text(
          copy.reasonCharacterCount(reasonLength, maxProgramRequestReasonChars),
          key: const Key('program_request_reason_counter'),
          style: MayosTypography.of(context).bodySecondary.copyWith(
            color: reasonLength > maxProgramRequestReasonChars
                ? colors.danger
                : null,
          ),
        ),
      ),
      if (_localError != null) ...<Widget>[
        const SizedBox(height: MayosSpacing.sm),
        Text(
          _localError!,
          style: MayosTypography.of(context).bodySecondary.copyWith(color: colors.danger),
        ),
      ],
    ];
  }

  List<Widget> _buildActions() {
    final AssignmentCopy copy = assignmentCopyOf(context);
    return <Widget>[
      MayosButton(
        label: copy.cancel,
        variant: MayosButtonVariant.tertiary,
        expand: false,
        onPressed: _submitting ? null : () => Navigator.of(context).pop(),
      ),
      MayosButton(
        key: const Key('program_request_submit_button'),
        label: copy.submitRequest,
        expand: false,
        loading: _submitting,
        onPressed: _submitting ? null : _submit,
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final AssignmentCopy copy = assignmentCopyOf(context);
    return PopScope<Object?>(
      canPop: !_submitting,
      child: AlertDialog(
        title: Text(copy.programChangeRequest),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              if (widget.substitution == null) ...<Widget>[
                _buildRequestTypeField(context),
                const SizedBox(height: MayosSpacing.md),
              ],
              if (_kind == 'exercise_substitution')
                ..._buildSubstitutionFields()
              else
                ..._buildSplitChangeFields(),
              const SizedBox(height: MayosSpacing.md),
              ..._buildReasonFields(context, colors),
            ],
          ),
        ),
        actions: _buildActions(),
      ),
    );
  }
}
