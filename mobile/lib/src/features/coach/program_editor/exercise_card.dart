part of '../coach_program_draft_screen.dart';

enum _ProgramDraftExerciseAction {
  moveUp,
  moveDown,
  swap,
  insertAbove,
  insertBelow,
  duplicate,
  delete,
}

class _ProgramDraftExerciseCard extends StatelessWidget {
  const _ProgramDraftExerciseCard({
    required this.dayIndex,
    required this.exerciseIndex,
    required this.exerciseCount,
    required this.exercise,
    required this.busy,
    required this.onEdit,
    this.isEditorForm = false,
    required this.errorFor,
    required this.onChanged,
    required this.onSwap,
    required this.onMove,
    required this.onInsertAbove,
    required this.onInsertBelow,
    required this.onDuplicate,
    required this.onRemove,
  });

  final int dayIndex;
  final int exerciseIndex;
  final int exerciseCount;
  final _DraftExerciseEditor exercise;
  final bool busy;
  final VoidCallback onEdit;
  final bool isEditorForm;
  final String? Function(String field) errorFor;
  final ValueChanged<String> onChanged;
  final VoidCallback onSwap;
  final ValueChanged<int> onMove;
  final VoidCallback onInsertAbove;
  final VoidCallback onInsertBelow;
  final VoidCallback onDuplicate;
  final VoidCallback onRemove;

  Key _fieldKey(String field) => field == 'warmup_sets'
      ? Key('program_draft_exercise_warmup_sets_${dayIndex}_$exerciseIndex')
      : Key('program_draft_${field}_${dayIndex}_$exerciseIndex');

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    if (!isEditorForm && !isDesktopLayout(context)) {
      return _phoneCard(context, copy);
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        padding: const EdgeInsets.all(MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(exercise.exerciseName,
                      style: MayosTypography.of(context).sectionHeading),
                ),
                _exerciseActionControls(context, copy, colors),
              ],
            ),
            _editorErrorText(context, errorFor('exercise_id'), colors),
            if (isEditorForm) _phoneExerciseError(context, colors),
            Row(
              children: <Widget>[
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('sets'),
                    controller: exercise.sets,
                    label: copy.workingSets,
                    enabled: !busy,
                    errorText: errorFor('target_sets'),
                    onChanged: (_) => onChanged('target_sets'),
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('reps'),
                    controller: exercise.reps,
                    label: copy.repsOrRange,
                    enabled: !busy,
                    allowRange: true,
                    errorText: errorFor('target_reps_min') ??
                        errorFor('target_reps_max'),
                    onChanged: (_) {
                      onChanged('target_reps_min');
                      onChanged('target_reps_max');
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.sm),
            SizedBox(
              width: 180,
              child: _editorNumberField(
                key: _fieldKey('rir'),
                controller: exercise.rir,
                label: copy.targetRir,
                enabled: !busy,
                decimal: true,
                errorText: errorFor('target_rir') ?? errorFor('target_rpe'),
                onChanged: (_) {
                  onChanged('target_rir');
                  onChanged('target_rpe');
                },
              ),
            ),
            const SizedBox(height: MayosSpacing.sm),
            DropdownButtonFormField<String>(
              key: _fieldKey('load_kind'),
              isExpanded: true,
              initialValue: exercise.loadKind,
              decoration: InputDecoration(
                labelText: copy.loadPrescription,
                border: const OutlineInputBorder(),
                isDense: true,
              ),
              items: <DropdownMenuItem<String>>[
                DropdownMenuItem<String>(value: '', child: Text(copy.noLoad)),
                DropdownMenuItem<String>(value: 'kg', child: Text(copy.fixedLoadKg)),
                DropdownMenuItem<String>(value: 'pct_e1rm', child: Text(copy.loadPercentE1rm)),
              ],
              onChanged: busy
                  ? null
                  : (String? value) {
                      exercise.loadKind = value ?? '';
                      onChanged('load');
                    },
            ),
            if (exercise.loadKind.isNotEmpty) ...<Widget>[
              const SizedBox(height: MayosSpacing.xs),
              _editorNumberField(
                key: _fieldKey('load_value'),
                controller: exercise.loadValue,
                label: exercise.loadKind == 'kg' ? copy.fixedLoadKg : copy.loadPercentE1rm,
                enabled: !busy,
                decimal: true,
                errorText: errorFor('load'),
                onChanged: (_) => onChanged('load'),
              ),
            ],
            if (isEditorForm) ...<Widget>[
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                title: Text(copy.amrapLastSet),
                value: exercise.setGroups.first['amrap_last_set'] == true,
                onChanged: busy ? null : (bool value) {
                  exercise.setGroups.first['amrap_last_set'] = value;
                  onChanged('set_groups');
                },
              ),
              for (int groupIndex = 1; groupIndex < exercise.setGroups.length; groupIndex++)
                _backoffGroup(context, copy, groupIndex),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton.icon(
                  key: const Key('program_draft_add_backoff'),
                  onPressed: busy ? null : () {
                    exercise.setGroups.add(<String, dynamic>{
                      'sets': ProgramDraftPrescription.defaultBackoffSets,
                      'reps_min': exercise.setGroups.first['reps_min'],
                      'reps_max': exercise.setGroups.first['reps_max'],
                      'target_rir': exercise.setGroups.first['target_rir'],
                      'load': <String, dynamic>{
                        'kind': 'pct_of_first_group',
                        'value': ProgramDraftPrescription.defaultBackoffLoadPercent,
                      },
                      'amrap_last_set': false,
                    });
                    onChanged('set_groups');
                  },
                  icon: const Icon(Icons.add),
                  label: Text(copy.addBackoffSets),
                ),
              ),
            ],
            const SizedBox(height: MayosSpacing.sm),
            Row(
              children: <Widget>[
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('warmup_sets'),
                    controller: exercise.warmupSets,
                    label: copy.rampedWarmupSets,
                    enabled: !busy,
                    errorText: errorFor('warmup_sets'),
                    onChanged: (_) => onChanged('warmup_sets'),
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('rest'),
                    controller: exercise.rest,
                    label: copy.restSeconds,
                    enabled: !busy,
                    errorText: errorFor('rest_seconds'),
                    onChanged: (_) => onChanged('rest_seconds'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            TextField(
              key: _fieldKey('tempo'),
              controller: exercise.tempo,
              enabled: !busy,
              maxLength: ProgramDraftPrescription.maxTempoLength,
              inputFormatters: <TextInputFormatter>[
                LengthLimitingTextInputFormatter(
                  ProgramDraftPrescription.maxTempoLength,
                ),
              ],
              decoration: InputDecoration(
                labelText: copy.tempo,
                border: const OutlineInputBorder(),
                isDense: true,
                errorText: errorFor('tempo'),
                counterText: '',
              ),
              onChanged: (_) => onChanged('tempo'),
            ),
            const SizedBox(height: MayosSpacing.xs),
            TextField(
              key: _fieldKey('notes'),
              controller: exercise.notes,
              enabled: !busy,
              minLines: 1,
              maxLines: 3,
              maxLength: ProgramDraftPrescription.maxProgramNotesLength,
              inputFormatters: <TextInputFormatter>[
                LengthLimitingTextInputFormatter(
                  ProgramDraftPrescription.maxProgramNotesLength,
                ),
              ],
              decoration: InputDecoration(
                labelText: copy.notesOptional,
                border: const OutlineInputBorder(),
                errorText: errorFor('notes'),
                counterText: '',
              ),
              onChanged: (_) => onChanged('notes'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _backoffGroup(BuildContext context, CoachCopy copy, int index) {
    final Map<String, dynamic> group = exercise.setGroups[index];
    final String prefix = 'program_draft_group_${dayIndex}_${exerciseIndex}_${exercise.groupId(group)}';
    Widget field(String suffix, String label, String key, {bool integer = true}) => SizedBox(
      width: 92,
      child: TextFormField(
        key: Key('${prefix}_$suffix'),
        initialValue: '${group[key] ?? ''}',
        keyboardType: TextInputType.numberWithOptions(decimal: !integer),
        decoration: InputDecoration(labelText: label, isDense: true),
        onChanged: (String value) {
          final num? parsed = integer ? int.tryParse(value) : double.tryParse(value);
          if (parsed != null) group[key] = parsed;
          onChanged('set_groups');
        },
      ),
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.xs),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
          Row(children: <Widget>[
            Expanded(child: Text(copy.backoffGroupTitle(index))),
            IconButton(
              key: Key('${prefix}_remove'),
              tooltip: copy.removeSetGroup,
              onPressed: busy ? null : () { exercise.setGroups.removeAt(index); onChanged('set_groups'); },
              icon: const Icon(Icons.remove_circle_outline),
            ),
          ]),
          Wrap(spacing: MayosSpacing.xs, runSpacing: MayosSpacing.xs, children: <Widget>[
            field('sets', copy.workingSets, 'sets'),
            field('reps', copy.repsOrRange, 'reps_min'),
            field('reps_max', copy.repsOrRange, 'reps_max'),
            field('rir', copy.targetRir, 'target_rir', integer: false),
          ]),
          _backoffLoadFields(context, copy, group, prefix),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            title: Text(copy.amrapLastSet),
            value: group['amrap_last_set'] == true,
            onChanged: (bool value) { group['amrap_last_set'] = value; onChanged('set_groups'); },
          ),
        ]),
      ),
    );
  }

  Widget _backoffLoadFields(
    BuildContext context,
    CoachCopy copy,
    Map<String, dynamic> group,
    String prefix,
  ) => Column(
        children: <Widget>[
          DropdownButtonFormField<String>(
            isExpanded: true,
            initialValue:
                (group['load'] as Map<String, dynamic>?)?['kind'] as String? ?? '',
            decoration: InputDecoration(
              labelText: copy.loadPrescription,
              isDense: true,
            ),
            items: <DropdownMenuItem<String>>[
              DropdownMenuItem<String>(value: '', child: Text(copy.noLoad)),
              DropdownMenuItem<String>(value: 'kg', child: Text(copy.fixedLoadKg)),
              DropdownMenuItem<String>(
                value: 'pct_e1rm',
                child: Text(copy.loadPercentE1rm),
              ),
              DropdownMenuItem<String>(
                value: 'pct_of_first_group',
                child: Text(copy.firstGroupLoadPercent),
              ),
            ],
            onChanged: (String? kind) {
              group['load'] = kind == null || kind.isEmpty
                  ? null
                  : <String, dynamic>{
                      'kind': kind,
                      'value':
                          (group['load'] as Map<String, dynamic>?)?['value'] ??
                              ProgramDraftPrescription.defaultBackoffLoadPercent,
                    };
              onChanged('set_groups');
            },
          ),
          if ((group['load'] as Map<String, dynamic>?) != null)
            TextFormField(
              key: Key('${prefix}_load_value'),
              initialValue: '${(group['load'] as Map<String, dynamic>)['value']}',
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: _backoffLoadLabel(copy, group),
                isDense: true,
              ),
              onChanged: (String value) {
                final double? parsed = double.tryParse(value);
                if (parsed != null) {
                  (group['load'] as Map<String, dynamic>)['value'] = parsed;
                }
                onChanged('set_groups');
              },
            ),
        ],
      );

  String _backoffLoadLabel(CoachCopy copy, Map<String, dynamic> group) =>
      switch ((group['load'] as Map<String, dynamic>)['kind']) {
        'kg' => copy.fixedLoadKg,
        'pct_of_first_group' => copy.firstGroupLoadPercent,
        _ => copy.loadPercentE1rm,
      };

  Widget _phoneCard(BuildContext context, CoachCopy copy) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final String prescription = exercise.setGroups.length > 1 ||
            exercise.setGroups.first['amrap_last_set'] == true
        ? formatSetGroups(
            exercise.setGroups,
            amrapLabel: displayCopyOf(context).amrapLabel,
          )
        : copy.exercisePrescriptionSummary(
      sets: exercise.sets.text,
      reps: exercise.reps.text,
      rir: exercise.rir.text,
      warmupSets: exercise.warmupSets.text,
      rest: exercise.rest.text,
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('program_draft_exercise_card_${dayIndex}_$exerciseIndex'),
        onTap: busy ? null : onEdit,
        padding: const EdgeInsetsDirectional.only(
          start: MayosSpacing.md,
          end: MayosSpacing.xs,
          top: MayosSpacing.sm,
          bottom: MayosSpacing.sm,
        ),
        child: Row(
          children: <Widget>[
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(exercise.exerciseName,
                      style: MayosTypography.of(context).sectionHeading),
                  const SizedBox(height: MayosSpacing.xxs),
                  Text(prescription,
                      style: MayosTypography.of(context).bodySecondary),
                  if (_firstExerciseError != null)
                    _phoneExerciseError(context, colors),
                  if (exercise.tempo.text.isNotEmpty ||
                      exercise.notes.text.isNotEmpty)
                    Text(
                      <String>[
                        if (exercise.tempo.text.isNotEmpty)
                          '${copy.tempo}: ${exercise.tempo.text}',
                        if (exercise.notes.text.isNotEmpty) exercise.notes.text,
                      ].join(' · '),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: MayosTypography.of(context).bodySecondary,
                    ),
                ],
              ),
            ),
            _exerciseActionControls(context, copy, colors),
            const Icon(Icons.edit_outlined),
            const SizedBox(width: MayosSpacing.sm),
          ],
        ),
      ),
    );
  }

  Widget _exerciseActionControls(
    BuildContext context,
    CoachCopy copy,
    MayosThemeExtension colors,
  ) {
    if (isEditorForm) return const SizedBox.shrink();
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        ReorderableDragStartListener(
          index: exerciseIndex,
          enabled: !busy,
          child: Tooltip(
            key: Key('program_draft_exercise_reorder_${dayIndex}_$exerciseIndex'),
            message: copy.reorderExercise,
            child: const Padding(
              padding: EdgeInsets.all(MayosSpacing.sm),
              child: Icon(Icons.drag_handle),
            ),
          ),
        ),
        PopupMenuButton<_ProgramDraftExerciseAction>(
          key: Key('program_draft_exercise_menu_${dayIndex}_$exerciseIndex'),
          tooltip: copy.exerciseActions,
          enabled: !busy,
          onSelected: (_ProgramDraftExerciseAction action) {
            switch (action) {
              case _ProgramDraftExerciseAction.moveUp:
                onMove(-1);
              case _ProgramDraftExerciseAction.moveDown:
                onMove(1);
              case _ProgramDraftExerciseAction.swap:
                onSwap();
              case _ProgramDraftExerciseAction.insertAbove:
                onInsertAbove();
              case _ProgramDraftExerciseAction.insertBelow:
                onInsertBelow();
              case _ProgramDraftExerciseAction.duplicate:
                onDuplicate();
              case _ProgramDraftExerciseAction.delete:
                onRemove();
            }
          },
          itemBuilder: (BuildContext context) =>
              <PopupMenuEntry<_ProgramDraftExerciseAction>>[
            if (!isDesktopLayout(context)) ...<PopupMenuEntry<_ProgramDraftExerciseAction>>[
              PopupMenuItem<_ProgramDraftExerciseAction>(
                key: Key(
                    'program_draft_exercise_move_up_${dayIndex}_$exerciseIndex'),
                value: _ProgramDraftExerciseAction.moveUp,
                enabled: !busy && exerciseIndex > 0,
                child: Text(copy.moveExerciseUp),
              ),
              PopupMenuItem<_ProgramDraftExerciseAction>(
                key: Key(
                    'program_draft_exercise_move_down_${dayIndex}_$exerciseIndex'),
                value: _ProgramDraftExerciseAction.moveDown,
                enabled: !busy && exerciseIndex < exerciseCount - 1,
                child: Text(copy.moveExerciseDown),
              ),
            ],
            PopupMenuItem<_ProgramDraftExerciseAction>(
              key: Key('program_draft_exercise_swap_${dayIndex}_$exerciseIndex'),
              value: _ProgramDraftExerciseAction.swap,
              child: Text(copy.swapExercise),
            ),
            PopupMenuItem<_ProgramDraftExerciseAction>(
              key: Key(
                'program_draft_exercise_insert_above_${dayIndex}_$exerciseIndex',
              ),
              value: _ProgramDraftExerciseAction.insertAbove,
              child: Text(copy.insertExerciseAbove),
            ),
            PopupMenuItem<_ProgramDraftExerciseAction>(
              key: Key(
                'program_draft_exercise_insert_below_${dayIndex}_$exerciseIndex',
              ),
              value: _ProgramDraftExerciseAction.insertBelow,
              child: Text(copy.insertExerciseBelow),
            ),
            PopupMenuItem<_ProgramDraftExerciseAction>(
              key: Key(
                'program_draft_exercise_duplicate_${dayIndex}_$exerciseIndex',
              ),
              value: _ProgramDraftExerciseAction.duplicate,
              child: Text(copy.duplicateExerciseAction),
            ),
            PopupMenuItem<_ProgramDraftExerciseAction>(
              key: Key('program_draft_remove_${dayIndex}_$exerciseIndex'),
              value: _ProgramDraftExerciseAction.delete,
              child: Text(copy.deleteExercise,
                  style: TextStyle(color: colors.danger)),
            ),
          ],
          icon: const Icon(Icons.more_vert),
        ),
      ],
    );
  }

  String? get _firstExerciseError {
    for (final String field in <String>[
      'exercise_id',
      'target_sets',
      'target_reps_min',
      'target_reps_max',
      'target_rir',
      'target_rpe',
      'warmup_sets',
      'rest_seconds',
      'tempo',
      'notes',
    ]) {
      final String? error = errorFor(field);
      if (error != null) return error;
    }
    return null;
  }

  Widget _phoneExerciseError(BuildContext context, MayosThemeExtension colors) {
    final String? error = _firstExerciseError;
    if (error == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(Icons.error_outline, color: colors.danger, size: 18),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(error,
                style: MayosTypography.of(context)
                    .body
                    .copyWith(color: colors.danger)),
          ),
        ],
      ),
    );
  }
}
