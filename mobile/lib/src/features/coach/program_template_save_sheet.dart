import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_bottom_sheet_editor.dart';

/// One free-text value copied from a player's program after Coach review.
class ProgramTemplateNoteReview {
  const ProgramTemplateNoteReview({
    this.weekOrder,
    this.dayOrder,
    required this.field,
    this.itemIndex,
    required this.locationLabel,
    required this.value,
  });

  final int? weekOrder;
  final int? dayOrder;

  /// `program_instructions`, `day_cardio`, `exercise_notes`, or `warmup_note`.
  final String field;
  final int? itemIndex;
  final String locationLabel;
  final String value;

  Map<String, dynamic> toDecision(String value) => <String, dynamic>{
        if (weekOrder != null) 'week_order': weekOrder,
        if (dayOrder != null) 'day_order': dayOrder,
        'field': field,
        if (itemIndex != null) 'item_index': itemIndex,
        'value': value,
      };
}

/// The coach's confirmed save-as-template input.
class ProgramTemplateSaveRequest {
  const ProgramTemplateSaveRequest({
    required this.name,
    required this.description,
    required this.notes,
  });

  final String name;
  final String? description;
  final List<Map<String, dynamic>> notes;
}

/// Collects free-text notes and prescriptions for review before template save.
///
/// Catalog-derived exercise `note` is shared library content, not copied source
/// text. Empty reviews are omitted, so unreviewed text is never carried over.
List<ProgramTemplateNoteReview> programTemplateNoteReviews(
  Map<String, dynamic> program,
) {
  final List<Map<String, dynamic>> weeks = _normalizedWeeks(program);
  final List<ProgramTemplateNoteReview> reviews = <ProgramTemplateNoteReview>[];
  final String? instructions = _text(program['instructions']);
  if (instructions != null) {
    reviews.add(ProgramTemplateNoteReview(
      field: 'program_instructions',
      locationLabel: '',
      value: instructions,
    ));
  }
  for (final Map<String, dynamic> week in weeks) {
    final int weekOrder = (week['week_order'] as num?)?.toInt() ?? 1;
    final String weekName = week['week_name'] as String? ?? '';
    for (final dynamic rawDay
        in week['days'] as List<dynamic>? ?? <dynamic>[]) {
      if (rawDay is! Map) continue;
      final Map<String, dynamic> day = Map<String, dynamic>.from(rawDay);
      final int dayOrder = (day['day_order'] as num?)?.toInt() ?? 1;
      final String dayName = day['day_name'] as String? ?? '';
      final String? cardio = _text(day['cardio']);
      if (cardio != null) {
        reviews.add(ProgramTemplateNoteReview(
          weekOrder: weekOrder,
          dayOrder: dayOrder,
          field: 'day_cardio',
          locationLabel: _location(weekName, dayName, ''),
          value: cardio,
        ));
      }
      final List<dynamic> warmups =
          day['warmup_exercises'] as List<dynamic>? ?? <dynamic>[];
      for (int index = 0; index < warmups.length; index++) {
        final Map<String, dynamic> movement =
            Map<String, dynamic>.from(warmups[index] as Map);
        final String? note = _text(movement['notes']);
        if (note == null) continue;
        reviews.add(ProgramTemplateNoteReview(
          weekOrder: weekOrder,
          dayOrder: dayOrder,
          field: 'warmup_note',
          itemIndex: index,
          locationLabel: _location(
              weekName, dayName, movement['exercise_name'] as String? ?? ''),
          value: note,
        ));
      }
      final List<dynamic> exercises =
          day['exercises'] as List<dynamic>? ?? <dynamic>[];
      for (int index = 0; index < exercises.length; index++) {
        final Map<String, dynamic> exercise =
            Map<String, dynamic>.from(exercises[index] as Map);
        final String? note = _text(exercise['notes']);
        if (note == null) continue;
        reviews.add(ProgramTemplateNoteReview(
          weekOrder: weekOrder,
          dayOrder: dayOrder,
          field: 'exercise_notes',
          itemIndex: index,
          locationLabel: _location(
              weekName, dayName, exercise['exercise_name'] as String? ?? ''),
          value: note,
        ));
      }
    }
  }
  return reviews;
}

/// Opens the review-and-name sheet. Returns null when the coach cancels.
Future<ProgramTemplateSaveRequest?> showProgramTemplateSaveSheet(
  BuildContext context, {
  required List<ProgramTemplateNoteReview> notes,
}) {
  final bool desktop = isDesktopLayout(context);
  final _ProgramTemplateSaveController controller =
      _ProgramTemplateSaveController();
  final Future<ProgramTemplateSaveRequest?> result;
  if (desktop) {
    result = showModalBottomSheet<ProgramTemplateSaveRequest>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext context) => Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: SafeArea(
          top: false,
          child: SingleChildScrollView(
            padding: MayosSpacing.screen,
            child: _ProgramTemplateSaveSheet(
              notes: notes,
              controller: controller,
              includeActions: true,
            ),
          ),
        ),
      ),
    );
  } else {
    result = showMayosBottomSheetEditor<ProgramTemplateSaveRequest>(
      context: context,
      content: _ProgramTemplateSaveSheet(
        notes: notes,
        controller: controller,
      ),
      actions: _ProgramTemplateSaveActions(controller: controller),
    );
  }
  return result.whenComplete(controller.dispose);
}

class _ProgramTemplateSaveController extends ChangeNotifier {
  VoidCallback? _submit;

  void bind(VoidCallback submit) {
    _submit = submit;
    notifyListeners();
  }

  void unbind() {
    _submit = null;
  }

  bool get canSubmit => _submit != null;

  void submit() => _submit?.call();
}

List<Map<String, dynamic>> _normalizedWeeks(Map<String, dynamic> program) {
  final List<dynamic> rawWeeks =
      program['weeks'] as List<dynamic>? ?? <dynamic>[];
  final List<Map<String, dynamic>> weeks = <Map<String, dynamic>>[];
  if (rawWeeks.isEmpty) {
    final List<dynamic> days = program['days'] as List<dynamic>? ?? <dynamic>[];
    weeks.add(<String, dynamic>{
      'week_name': 'Week 1',
      'week_order': 1,
      'days': _orderedDays(days),
    });
  } else {
    for (final dynamic rawWeek in rawWeeks) {
      if (rawWeek is! Map) continue;
      final Map<String, dynamic> week = Map<String, dynamic>.from(rawWeek);
      week['days'] =
          _orderedDays(week['days'] as List<dynamic>? ?? <dynamic>[]);
      weeks.add(week);
    }
    weeks.sort((Map<String, dynamic> a, Map<String, dynamic> b) =>
        ((a['week_order'] as num?)?.toInt() ?? 1)
            .compareTo((b['week_order'] as num?)?.toInt() ?? 1));
  }
  return weeks;
}

List<Map<String, dynamic>> _orderedDays(List<dynamic> days) {
  final List<Map<String, dynamic>> ordered = <Map<String, dynamic>>[
    for (final dynamic day in days)
      if (day is Map) Map<String, dynamic>.from(day),
  ];
  ordered.sort((Map<String, dynamic> a, Map<String, dynamic> b) =>
      ((a['day_order'] as num?)?.toInt() ?? 1)
          .compareTo((b['day_order'] as num?)?.toInt() ?? 1));
  return ordered;
}

String _location(String weekName, String dayName, String exerciseName) {
  final List<String> parts = <String>[
    if (weekName.isNotEmpty) weekName,
    if (dayName.isNotEmpty) dayName,
    if (exerciseName.isNotEmpty) exerciseName,
  ];
  return parts.join(' · ');
}

String _reviewLocation(
  ProgramTemplateNoteReview review,
  CoachCopy copy,
) {
  return switch (review.field) {
    'program_instructions' => copy.programInstructions,
    'day_cardio' => <String>[
        review.locationLabel,
        copy.cardioPrescription,
      ].where((String part) => part.isNotEmpty).join(' · '),
    _ => review.locationLabel,
  };
}

String? _text(dynamic value) {
  if (value is! String) return null;
  final String trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}

class _ProgramTemplateSaveSheet extends StatefulWidget {
  const _ProgramTemplateSaveSheet({
    required this.notes,
    required this.controller,
    this.includeActions = false,
  });

  final List<ProgramTemplateNoteReview> notes;
  final _ProgramTemplateSaveController controller;
  final bool includeActions;

  @override
  State<_ProgramTemplateSaveSheet> createState() =>
      _ProgramTemplateSaveSheetState();
}

class _ProgramTemplateSaveSheetState extends State<_ProgramTemplateSaveSheet> {
  final TextEditingController _name = TextEditingController();
  final TextEditingController _description = TextEditingController();
  late final List<TextEditingController> _notes;
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.controller.bind(_submit);
    _notes = <TextEditingController>[
      for (final ProgramTemplateNoteReview note in widget.notes)
        TextEditingController(text: note.value),
    ];
  }

  @override
  void dispose() {
    widget.controller.unbind();
    _name.dispose();
    _description.dispose();
    for (final TextEditingController controller in _notes) {
      controller.dispose();
    }
    super.dispose();
  }

  void _submit() {
    final CoachCopy copy = coachCopyOf(context);
    final String name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = copy.templateNameRequired);
      return;
    }
    final String description = _description.text.trim();
    final List<Map<String, dynamic>> notes = <Map<String, dynamic>>[];
    for (int index = 0; index < widget.notes.length; index++) {
      final String value = _notes[index].text.trim();
      if (value.isEmpty) continue;
      notes.add(widget.notes[index].toDecision(value));
    }
    Navigator.of(context).pop(ProgramTemplateSaveRequest(
      name: name,
      description: description.isEmpty ? null : description,
      notes: notes,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return _form(copy, colors);
  }

  Widget _form(CoachCopy copy, MayosThemeExtension colors) => Column(
        key: const Key('program_template_save_sheet'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          _titleAndNotice(copy, colors),
          const SizedBox(height: MayosSpacing.md),
          _reviewSection(copy, colors),
          const SizedBox(height: MayosSpacing.md),
          _nameField(copy),
          const SizedBox(height: MayosSpacing.sm),
          _descriptionField(copy),
          if (_error != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            _errorMessage(colors),
          ],
          if (widget.includeActions) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            _ProgramTemplateSaveActions(controller: widget.controller),
          ],
        ],
      );

  Widget _titleAndNotice(CoachCopy copy, MayosThemeExtension colors) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            copy.saveAsTemplate,
            style: MayosTypography.of(context).sectionHeading,
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            copy.saveAsTemplateNotesNotice,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: colors.textSecondary),
          ),
        ],
      );

  Widget _reviewSection(CoachCopy copy, MayosThemeExtension colors) {
    if (widget.notes.isEmpty) {
      return Text(
        copy.saveAsTemplateNoNotes,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: colors.textSecondary),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          copy.saveAsTemplateNotesHeading,
          style: MayosTypography.of(context).sectionHeading,
        ),
        for (int index = 0; index < widget.notes.length; index++)
          _reviewNote(index, copy, colors),
      ],
    );
  }

  Widget _reviewNote(
    int index,
    CoachCopy copy,
    MayosThemeExtension colors,
  ) =>
      Padding(
        padding: const EdgeInsets.only(top: MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(
              _reviewLocation(widget.notes[index], copy),
              style: MayosTypography.of(context)
                  .bodySecondary
                  .copyWith(color: colors.textSecondary),
            ),
            TextField(
              key: Key('program_template_save_note_$index'),
              controller: _notes[index],
              minLines: 1,
              maxLines: 3,
              decoration: const InputDecoration(labelText: ''),
            ),
          ],
        ),
      );

  Widget _nameField(CoachCopy copy) => TextField(
        key: const Key('program_template_save_name'),
        controller: _name,
        decoration: InputDecoration(labelText: copy.templateName),
        onChanged: (_) {
          if (_error != null) setState(() => _error = null);
        },
      );

  Widget _descriptionField(CoachCopy copy) => TextField(
        key: const Key('program_template_save_description'),
        controller: _description,
        minLines: 1,
        maxLines: 3,
        decoration: InputDecoration(labelText: copy.templateDescription),
      );

  Widget _errorMessage(MayosThemeExtension colors) => Text(
        _error!,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: colors.danger),
      );
}

class _ProgramTemplateSaveActions extends StatelessWidget {
  const _ProgramTemplateSaveActions({required this.controller});

  final _ProgramTemplateSaveController controller;

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return AnimatedBuilder(
      animation: controller,
      builder: (BuildContext context, Widget? child) => Row(
        children: <Widget>[
          Expanded(
            child: MayosButton(
              key: const Key('program_template_save_cancel'),
              label: copy.cancel,
              variant: MayosButtonVariant.secondary,
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: MayosButton(
              key: const Key('program_template_save_confirm'),
              label: copy.saveTemplate,
              onPressed: controller.canSubmit ? controller.submit : null,
            ),
          ),
        ],
      ),
    );
  }
}
