part of '../coach_program_draft_screen.dart';

enum _ProgramDraftWarmupAction { insertAbove, insertBelow, remove }

class _ProgramDraftWarmupMovementCard extends StatelessWidget {
  const _ProgramDraftWarmupMovementCard({
    required this.dayIndex,
    required this.movementIndex,
    required this.movementCount,
    required this.movement,
    required this.busy,
    required this.errorFor,
    required this.onChanged,
    required this.onMove,
    required this.onRemove,
    required this.onInsertAbove,
    required this.onInsertBelow,
  });

  final int dayIndex;
  final int movementIndex;
  final int movementCount;
  final _DraftWarmupEditor movement;
  final bool busy;
  final String? Function(String field) errorFor;
  final ValueChanged<String> onChanged;
  final ValueChanged<int> onMove;
  final VoidCallback onRemove;
  final VoidCallback onInsertAbove;
  final VoidCallback onInsertBelow;

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  key: Key('program_draft_warmup_name_${dayIndex}_$movementIndex'),
                  controller: movement.name,
                  enabled: !busy,
                  decoration: InputDecoration(
                    labelText: copy.warmupMovementName,
                    border: const OutlineInputBorder(),
                    isDense: true,
                    errorText: errorFor('exercise_name'),
                  ),
                  onChanged: (_) => onChanged('exercise_name'),
                ),
              ),
              IconButton(
                key: Key('program_draft_warmup_up_${dayIndex}_$movementIndex'),
                tooltip: copy.moveWarmupMovementUp,
                onPressed: busy || movementIndex == 0
                    ? null
                    : () => onMove(-1),
                icon: const Icon(Icons.arrow_upward),
              ),
              IconButton(
                key: Key('program_draft_warmup_down_${dayIndex}_$movementIndex'),
                tooltip: copy.moveWarmupMovementDown,
                onPressed: busy || movementIndex == movementCount - 1
                    ? null
                    : () => onMove(1),
                icon: const Icon(Icons.arrow_downward),
              ),
              PopupMenuButton<_ProgramDraftWarmupAction>(
                key: Key(
                  'program_draft_warmup_menu_${dayIndex}_$movementIndex',
                ),
                tooltip: copy.warmupMovementActions,
                enabled: !busy,
                onSelected: (_ProgramDraftWarmupAction action) {
                  switch (action) {
                    case _ProgramDraftWarmupAction.insertAbove:
                      onInsertAbove();
                    case _ProgramDraftWarmupAction.insertBelow:
                      onInsertBelow();
                    case _ProgramDraftWarmupAction.remove:
                      onRemove();
                  }
                },
                itemBuilder: (BuildContext context) =>
                    <PopupMenuEntry<_ProgramDraftWarmupAction>>[
                  PopupMenuItem<_ProgramDraftWarmupAction>(
                    key: Key(
                      'program_draft_warmup_insert_above_${dayIndex}_$movementIndex',
                    ),
                    value: _ProgramDraftWarmupAction.insertAbove,
                    child: Text(copy.insertWarmupAbove),
                  ),
                  PopupMenuItem<_ProgramDraftWarmupAction>(
                    key: Key(
                      'program_draft_warmup_insert_below_${dayIndex}_$movementIndex',
                    ),
                    value: _ProgramDraftWarmupAction.insertBelow,
                    child: Text(copy.insertWarmupBelow),
                  ),
                  PopupMenuItem<_ProgramDraftWarmupAction>(
                    key: Key(
                      'program_draft_warmup_remove_${dayIndex}_$movementIndex',
                    ),
                    value: _ProgramDraftWarmupAction.remove,
                    child: Text(copy.removeWarmupMovement),
                  ),
                ],
                icon: const Icon(Icons.more_vert),
              ),
            ],
          ),
          Row(
            children: <Widget>[
              Expanded(
                child: _editorNumberField(
                  key: Key('program_draft_warmup_sets_${dayIndex}_$movementIndex'),
                  controller: movement.sets,
                  label: copy.movementSets,
                  enabled: !busy,
                  errorText: errorFor('sets'),
                  onChanged: (_) => onChanged('sets'),
                ),
              ),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: _editorNumberField(
                  key: Key('program_draft_warmup_reps_${dayIndex}_$movementIndex'),
                  controller: movement.reps,
                  label: copy.movementReps,
                  enabled: !busy,
                  errorText: errorFor('reps'),
                  onChanged: (_) => onChanged('reps'),
                ),
              ),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: _editorNumberField(
                  key: Key('program_draft_warmup_rest_${dayIndex}_$movementIndex'),
                  controller: movement.rest,
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
                  key: Key('program_draft_warmup_notes_${dayIndex}_$movementIndex'),
            controller: movement.notes,
            enabled: !busy,
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
    );
  }
}
