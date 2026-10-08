import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/effort.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';

typedef CoachProgramCardBusyState = ({
  bool generatingDraft,
  bool copyingActiveProgram,
  bool approvingActiveProgram,
  bool downloadingProgramTemplate,
});

typedef CoachProgramCardCallbacks = ({
  VoidCallback writeProgram,
  VoidCallback generateDraft,
  VoidCallback importProgram,
  VoidCallback downloadTemplate,
  VoidCallback editActiveProgram,
  VoidCallback approveActiveProgram,
});

/// The Program segment card on the Coach's Player screen.
///
/// Workflow state and navigation stay owned by the Player screen; this widget
/// renders the active program and forwards each action to its existing handler.
class CoachProgramCard extends StatelessWidget {
  const CoachProgramCard({
    super.key,
    required this.active,
    required this.busyState,
    required this.callbacks,
    this.actionError,
  });

  final CoachActiveProgram active;
  final CoachProgramCardBusyState busyState;
  final CoachProgramCardCallbacks callbacks;
  final String? actionError;

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MayosSectionHeader(
            title: copy.program,
            padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
          ),
          ..._programContent(context, copy),
        ],
      ),
    );
  }

  List<Widget> _programContent(BuildContext context, CoachCopy copy) =>
      <Widget>[
        if (active.hasDraft) _pendingProgramDraftBadge(context),
        ..._activeProgramContent(context, copy),
        if (actionError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          _actionErrorText(context),
        ],
        const SizedBox(height: MayosSpacing.md),
        _programActions(context),
      ];

  List<Widget> _activeProgramContent(BuildContext context, CoachCopy copy) {
    final TrainingProgram? program = active.program;
    if (program == null) {
      return <Widget>[
        Text(
          copy.noActiveProgram,
          style: MayosTypography.of(context)
              .bodySecondary
              .copyWith(color: MayosTheme.of(context).textSecondary),
        ),
      ];
    }
    return _programDetails(context, program);
  }

  Widget _actionErrorText(BuildContext context) => Text(
        actionError!,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: MayosTheme.of(context).danger),
      );

  Widget _programActions(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return isDesktopLayout(context)
        ? _desktopProgramActions(context, copy)
        : _phoneProgramActions(context, copy);
  }

  Widget _desktopProgramActions(BuildContext context, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _actionsHeading(context, copy),
          const SizedBox(height: MayosSpacing.xs),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              ..._desktopActiveActions(copy),
              if (active.program != null)
                const SizedBox(
                  height: kMayosMinTapTarget,
                  child: VerticalDivider(width: 1),
                ),
              ..._desktopDraftActions(copy),
            ],
          ),
        ],
      );

  List<Widget> _desktopActiveActions(CoachCopy copy) => active.program == null
      ? <Widget>[]
      : <Widget>[
          _approveButton(copy),
          _editButton(copy),
        ];

  List<Widget> _desktopDraftActions(CoachCopy copy) => <Widget>[
        _generateButton(copy),
        _writeButton(copy),
        _importButton(copy),
        _downloadButton(copy),
      ];

  Widget _actionGap() => const SizedBox(width: MayosSpacing.xs);

  Widget _phoneProgramActions(BuildContext context, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _actionsHeading(context, copy),
          const SizedBox(height: MayosSpacing.xs),
          if (active.program != null) _phoneActiveActions(copy),
          if (active.program != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            const Divider(height: 1),
            const SizedBox(height: MayosSpacing.xs),
          ],
          _phoneDraftActions(context, copy),
        ],
      );

  Widget _phoneActiveActions(CoachCopy copy) => Row(
        children: <Widget>[
          Expanded(child: _approveButton(copy)),
          _actionGap(),
          Expanded(child: _editButton(copy)),
        ],
      );

  Widget _phoneDraftActions(BuildContext context, CoachCopy copy) =>
      LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final double buttonWidth =
              (constraints.maxWidth - MayosSpacing.xs) / 2;
          return Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              SizedBox(width: buttonWidth, child: _generateButton(copy)),
              SizedBox(width: buttonWidth, child: _writeButton(copy)),
              SizedBox(width: buttonWidth, child: _importButton(copy)),
              SizedBox(width: buttonWidth, child: _downloadButton(copy)),
            ],
          );
        },
      );

  Widget _actionsHeading(BuildContext context, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            copy.programActions,
            style: MayosTypography.of(context).sectionHeading.copyWith(
                  color: MayosTheme.of(context).textPrimary,
                ),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            copy.programActionsSubtitle,
            style: MayosTypography.of(context).bodySecondary.copyWith(
                  color: MayosTheme.of(context).textSecondary,
                ),
          ),
        ],
      );

  bool get _activeProgramActionBusy =>
      busyState.copyingActiveProgram || busyState.approvingActiveProgram;

  Widget _approveButton(CoachCopy copy) {
    final bool canApprove = active.program?.version != null;
    return MayosButton(
      key: const Key('coach_program_approve_as_is'),
      label: copy.approveProgramAsIs,
      icon: Icons.check,
      expand: false,
      loading: busyState.approvingActiveProgram,
      onPressed: _activeProgramActionBusy || !canApprove
          ? null
          : callbacks.approveActiveProgram,
    );
  }

  Widget _editButton(CoachCopy copy) => MayosButton(
        key: const Key('coach_program_edit_active'),
        label: copy.editActiveProgram,
        icon: Icons.edit_outlined,
        variant: MayosButtonVariant.secondary,
        expand: false,
        loading: busyState.copyingActiveProgram,
        onPressed:
            _activeProgramActionBusy ? null : callbacks.editActiveProgram,
      );

  Widget _generateButton(CoachCopy copy) => MayosButton(
        key: const Key('generate_draft_action'),
        label: copy.generateDraft,
        icon: Icons.auto_awesome_outlined,
        variant: active.program == null
            ? MayosButtonVariant.primary
            : MayosButtonVariant.secondary,
        expand: false,
        loading: busyState.generatingDraft,
        onPressed:
            busyState.generatingDraft ? null : callbacks.generateDraft,
      );

  Widget _writeButton(CoachCopy copy) => MayosButton(
        key: const Key('write_program_action'),
        label: copy.writeProgram,
        icon: Icons.edit_outlined,
        variant: MayosButtonVariant.secondary,
        expand: false,
        onPressed: callbacks.writeProgram,
      );

  Widget _importButton(CoachCopy copy) => MayosButton(
        key: const Key('program_import_action'),
        label: copy.importProgramAction,
        icon: Icons.upload_file,
        variant: MayosButtonVariant.secondary,
        expand: false,
        onPressed: callbacks.importProgram,
      );

  Widget _downloadButton(CoachCopy copy) => MayosButton(
        key: const Key('program_template_download_action'),
        label: copy.downloadProgramTemplateAction,
        icon: Icons.download_outlined,
        variant: MayosButtonVariant.secondary,
        expand: false,
        loading: busyState.downloadingProgramTemplate,
        onPressed: busyState.downloadingProgramTemplate
            ? null
            : callbacks.downloadTemplate,
      );

  Widget _pendingProgramDraftBadge(BuildContext context) => Align(
        alignment: AlignmentDirectional.centerStart,
        child: Chip(
          key: const Key('coach_program_pending_draft'),
          label: Text(coachCopyOf(context).pendingProgramDraft),
        ),
      );

  List<Widget> _programDetails(
    BuildContext context,
    TrainingProgram program,
  ) {
    final CoachCopy copy = coachCopyOf(context);
    final String? activeDate = active.activeSince?.split('T').first;
    return <Widget>[
      Text(active.provenance == 'coach'
          ? copy.publishedByYou
          : copy.generatedAutomatically),
      if (active.editedByPlayer) Text(copy.editedByPlayer),
      if (program.version != null) Text(copy.programVersion(program.version!)),
      if (activeDate != null) Text(copy.activeProgramSince(activeDate)),
      Text(program.programName),
      for (final ProgramDay day in program.days) _programDay(context, day),
    ];
  }

  Widget _programDay(BuildContext context, ProgramDay day) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            day.dayName,
            style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
          ),
          for (final ProgramExercise exercise in day.exercises)
            _programExercise(context, exercise),
        ],
      ),
    );
  }

  Widget _programExercise(BuildContext context, ProgramExercise exercise) =>
      Padding(
        padding: const EdgeInsetsDirectional.only(start: MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: _programExerciseDetails(context, exercise),
        ),
      );

  List<Widget> _programExerciseDetails(
    BuildContext context,
    ProgramExercise exercise,
  ) {
    final CoachCopy copy = coachCopyOf(context);
    return <Widget>[
      Text(exercise.exerciseName),
      Text(
        _programPrescription(copy, exercise),
        style: MayosTypography.of(context).bodySecondary,
      ),
      if (exercise.tempo != null && exercise.tempo!.isNotEmpty)
        Text(copy.programTempo(exercise.tempo!)),
      if (exercise.notes != null && exercise.notes!.isNotEmpty)
        Text(copy.programNotes(exercise.notes!)),
    ];
  }

  String _programPrescription(CoachCopy copy, ProgramExercise exercise) =>
      copy.programPrescription(
        copy.programWorkingSets(exercise.targetSets),
        copy.programRepRange(
          exercise.targetRepsMin,
          exercise.targetRepsMax,
        ),
        minRirLabel(exercise.targetRpe),
        exercise.restSecondsOrDefault,
      );
}
