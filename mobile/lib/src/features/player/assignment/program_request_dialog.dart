import 'package:flutter/material.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';

/// A player program-request payload ready for the existing create-request API.
class ProgramRequestDraft {
  const ProgramRequestDraft({
    required this.kind,
    required this.reason,
    this.dayName,
    this.exerciseId,
    this.replacementExerciseId,
    this.desiredWeeklyFrequency,
    this.desiredSplitPreference,
  });

  final String kind;
  final String reason;
  final String? dayName;
  final String? exerciseId;
  final String? replacementExerciseId;
  final int? desiredWeeklyFrequency;
  final String? desiredSplitPreference;
}

/// The read-only substitution slot shown before the player enters a reason.
class ProgramSubstitutionRequestPrefill {
  const ProgramSubstitutionRequestPrefill({
    required this.dayName,
    required this.exerciseId,
    required this.exerciseName,
    required this.replacementExerciseId,
    required this.replacementName,
  });

  final String dayName;
  final String exerciseId;
  final String exerciseName;
  final String replacementExerciseId;
  final String replacementName;
}

/// The shared request form used from both the assignment page and Program tab.
class ProgramRequestDialog extends StatefulWidget {
  const ProgramRequestDialog({super.key}) : substitution = null;

  const ProgramRequestDialog.forSubstitution({
    super.key,
    required this.substitution,
  }) : assert(substitution != null);

  final ProgramSubstitutionRequestPrefill? substitution;

  @override
  State<ProgramRequestDialog> createState() => _ProgramRequestDialogState();
}

class _ProgramRequestDialogState extends State<ProgramRequestDialog> {
  late final TextEditingController _day;
  late final TextEditingController _exercise;
  late final TextEditingController _replacement;
  final TextEditingController _preference = TextEditingController();
  final TextEditingController _reason = TextEditingController();
  String _kind = 'exercise_substitution';
  int _frequency = 4;
  String? _localError;

  @override
  void initState() {
    super.initState();
    _day = TextEditingController(text: widget.substitution?.dayName);
    _exercise = TextEditingController(text: widget.substitution?.exerciseId);
    _replacement = TextEditingController(
      text: widget.substitution?.replacementExerciseId,
    );
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

  void _submit() {
    final String? error = _validationError();
    if (error != null) {
      setState(() => _localError = error);
      return;
    }
    Navigator.of(context).pop(_buildDraft());
  }

  String? _validationError() {
    if (_reason.text.trim().isEmpty) return 'A reason is required.';
    if (_kind == 'exercise_substitution' &&
        (_day.text.trim().isEmpty ||
            _exercise.text.trim().isEmpty ||
            _replacement.text.trim().isEmpty)) {
      return 'Pick the day, the exercise, and its replacement.';
    }
    return null;
  }

  ProgramRequestDraft _buildDraft() => ProgramRequestDraft(
        kind: _kind,
        reason: _reason.text.trim(),
        dayName: _kind == 'exercise_substitution' ? _day.text.trim() : null,
        exerciseId:
            _kind == 'exercise_substitution' ? _exercise.text.trim() : null,
        replacementExerciseId:
            _kind == 'exercise_substitution' ? _replacement.text.trim() : null,
        desiredWeeklyFrequency: _kind == 'split_change' ? _frequency : null,
        desiredSplitPreference:
            _kind == 'split_change' ? _preference.text.trim() : null,
      );

  Widget _buildRequestTypeField() => DropdownButtonFormField<String>(
        key: const Key('program_request_kind_field'),
        initialValue: _kind,
        decoration: const InputDecoration(
            labelText: 'Request type', border: OutlineInputBorder()),
        items: const <DropdownMenuItem<String>>[
          DropdownMenuItem<String>(
              value: 'exercise_substitution',
              child: Text('Exercise substitution')),
          DropdownMenuItem<String>(
              value: 'split_change', child: Text('Split change')),
        ],
        onChanged: (String? value) => setState(() {
          _kind = value ?? _kind;
          _localError = null;
        }),
      );

  Widget _buildReadOnlyValue(String label, String value) => InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(
            value,
            style: MayosTypography.body.copyWith(
              color: MayosTheme.of(context).textPrimary,
            ),
          ),
        ),
      );

  List<Widget> _buildSubstitutionFields() {
    final ProgramSubstitutionRequestPrefill? prefill = widget.substitution;
    if (prefill != null) {
      return <Widget>[
        _buildReadOnlyValue('Day', prefill.dayName),
        const SizedBox(height: MayosSpacing.md),
        _buildReadOnlyValue('Exercise', prefill.exerciseName),
        const SizedBox(height: MayosSpacing.md),
        _buildReadOnlyValue('Replacement', prefill.replacementName),
      ];
    }
    return <Widget>[
      MayosTextField(
        fieldKey: const Key('program_request_day_field'),
        controller: _day,
        label: 'Day name',
      ),
      const SizedBox(height: MayosSpacing.md),
      MayosTextField(
        fieldKey: const Key('program_request_exercise_field'),
        controller: _exercise,
        label: 'Current exercise id',
      ),
      const SizedBox(height: MayosSpacing.md),
      MayosTextField(
        fieldKey: const Key('program_request_replacement_field'),
        controller: _replacement,
        label: 'Replacement exercise id',
      ),
    ];
  }

  List<Widget> _buildSplitChangeFields() => <Widget>[
        DropdownButtonFormField<int>(
          key: const Key('program_request_frequency_field'),
          initialValue: _frequency,
          decoration: const InputDecoration(
              labelText: 'Days per week', border: OutlineInputBorder()),
          items: <DropdownMenuItem<int>>[
            for (int day = 1; day <= 5; day++)
              DropdownMenuItem<int>(value: day, child: Text('$day')),
          ],
          onChanged: (int? value) =>
              setState(() => _frequency = value ?? _frequency),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('program_request_split_field'),
          controller: _preference,
          label: 'Split preference (optional)',
        ),
      ];

  List<Widget> _buildReasonFields(MayosThemeExtension colors) => <Widget>[
        MayosTextField(
          fieldKey: const Key('program_request_reason_field'),
          controller: _reason,
          maxLines: 2,
          label: 'Reason',
        ),
        if (_localError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            _localError!,
            style: MayosTypography.bodySecondary.copyWith(color: colors.danger),
          ),
        ],
      ];

  List<Widget> _buildActions() => <Widget>[
        MayosButton(
          label: 'Cancel',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          key: const Key('program_request_submit_button'),
          label: 'Submit request',
          expand: false,
          onPressed: _submit,
        ),
      ];

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return AlertDialog(
      title: const Text('Request a program change'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            if (widget.substitution == null) ...<Widget>[
              _buildRequestTypeField(),
              const SizedBox(height: MayosSpacing.md),
            ],
            if (_kind == 'exercise_substitution')
              ..._buildSubstitutionFields()
            else
              ..._buildSplitChangeFields(),
            const SizedBox(height: MayosSpacing.md),
            ..._buildReasonFields(colors),
          ],
        ),
      ),
      actions: _buildActions(),
    );
  }
}
