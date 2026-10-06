import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/catalog.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/exercise_filters.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import '../../shared/exercise_filter_bar.dart';

class CoachExercisePickerDialog extends ConsumerStatefulWidget {
  const CoachExercisePickerDialog({
    super.key,
    this.currentExerciseId,
    this.title,
  });

  final String? currentExerciseId;
  final String? title;

  @override
  ConsumerState<CoachExercisePickerDialog> createState() =>
      _CoachExercisePickerDialogState();
}

class _CoachExercisePickerDialogState
    extends ConsumerState<CoachExercisePickerDialog> {
  final TextEditingController _query = TextEditingController();
  List<ExerciseCatalogEntry> _results = const <ExerciseCatalogEntry>[];
  bool _searching = false;
  bool _searched = false;
  String? _error;
  FailureMessage? _failure;
  ExerciseFilterState _filterState = const ExerciseFilterState();

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final String query = _query.text.trim();
    final ExerciseFilterState filters = _filterState;
    if (query.isEmpty && !filters.hasCuratedFilters) {
      setState(() {
        _results = const <ExerciseCatalogEntry>[];
        _searched = false;
        _error = coachCopyOf(context).exerciseNameRequired;
      });
      return;
    }
    _startSearch();
    await _loadResults(
      query,
      filters.primaryMuscles,
      filters.primaryActions,
      filters.loadTypes,
      filters.equipmentCategories,
    );
  }

  void _startSearch() {
    setState(() {
      _searching = true;
      _error = null;
      _failure = null;
    });
  }

  Future<void> _loadResults(
    String query,
    List<String> primaryMuscles,
    List<String> primaryActions,
    List<String> loadTypes,
    List<String> equipmentCategories,
  ) async {
    try {
      final List<ExerciseCatalogEntry> results =
          await ref
              .read(apiClientProvider)
              .coachSearchExercises(
                query,
                primaryMuscles: primaryMuscles,
                primaryActions: primaryActions,
                loadTypes: loadTypes,
                equipmentCategories: equipmentCategories,
              );
      if (!mounted) return;
      setState(() {
        _results = results;
        _searching = false;
        _searched = true;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _results = const <ExerciseCatalogEntry>[];
        _searching = false;
        _failure = apiFailureMessage(error);
      });
    }
  }

  void _filtersChanged(ExerciseFilterState filters) {
    setState(() => _filterState = filters);
    unawaited(_search());
  }

  Future<void> _createExercise() async {
    final ExerciseCatalogEntry? created =
        await showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => CoachExerciseCreateDialog(
        initialName: _query.text.trim(),
      ),
    );
    if (created != null && mounted) Navigator.of(context).pop(created);
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy coachCopy = coachCopyOf(context);
    final MayosCopy copy = displayCopyOf(context);
    return AlertDialog(
      title: Text(widget.title ?? coachCopy.addExercise),
      content: SizedBox(
        width: 360,
        child: _pickerContent(context, coachCopy, copy),
      ),
      actions: _pickerActions(context, coachCopy, copy),
    );
  }

  Widget _pickerContent(
          BuildContext context, CoachCopy coachCopy, MayosCopy copy) =>
      Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _searchField(copy),
          ExerciseFilterBar(
            filterState: _filterState,
            onChanged: _filtersChanged,
          ),
          if (_searching) const _ExerciseSearchProgress(),
          if (_error != null || _failure != null) _searchError(copy),
          if (_results.isNotEmpty) _resultList(context, coachCopy),
          if (_showNoMatches)
            _NoExerciseMatches(copy: coachCopy, onCreate: _createExercise),
        ],
      );

  Widget _resultList(BuildContext context, CoachCopy copy) => Flexible(
        child: _ExerciseSearchResults(
          exercises: _results,
          yourExerciseLabel: copy.yourExercise,
          onSelected: (ExerciseCatalogEntry exercise) =>
              Navigator.of(context).pop(exercise),
        ),
      );

  Widget _searchField(MayosCopy copy) => MayosTextField(
        controller: _query,
        autofocus: true,
        label: copy.searchExerciseCatalog,
        textInputAction: TextInputAction.search,
        onSubmitted: (_) => _search(),
      );

  Widget _searchError(MayosCopy copy) => Padding(
        padding: const EdgeInsets.only(top: MayosSpacing.sm),
        child: Text(
          _failure == null ? _error! : copy.failureMessage(_failure!),
          style: MayosTypography.of(context).bodySecondary,
        ),
      );

  List<Widget> _pickerActions(
    BuildContext context,
    CoachCopy coachCopy,
    MayosCopy copy,
  ) =>
      <Widget>[
        MayosButton(
          label: coachCopy.cancel,
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          key: const Key('coach_exercise_search'),
          label: copy.search,
          expand: false,
          loading: _searching,
          onPressed: _searching ? null : _search,
        ),
      ];

  bool get _showNoMatches =>
      _searched &&
      !_searching &&
      _failure == null &&
      _error == null &&
      _results.isEmpty;
}

class _ExerciseSearchProgress extends StatelessWidget {
  const _ExerciseSearchProgress();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.only(top: MayosSpacing.sm),
        child: Center(child: CircularProgressIndicator()),
      );
}

class _ExerciseSearchResults extends StatelessWidget {
  const _ExerciseSearchResults({
    required this.exercises,
    required this.yourExerciseLabel,
    required this.onSelected,
  });

  final List<ExerciseCatalogEntry> exercises;
  final String yourExerciseLabel;
  final ValueChanged<ExerciseCatalogEntry> onSelected;

  @override
  Widget build(BuildContext context) => ListView(
        shrinkWrap: true,
        children: exercises
            .map(
              (ExerciseCatalogEntry exercise) => MayosSettingsTile(
                icon: Icons.fitness_center,
                title: exercise.name,
                subtitle: exercise.isCoachExercise ? yourExerciseLabel : null,
                onTap: () => onSelected(exercise),
              ),
            )
            .toList(growable: false),
      );
}

class _NoExerciseMatches extends StatelessWidget {
  const _NoExerciseMatches({required this.copy, required this.onCreate});

  final CoachCopy copy;
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Text(copy.noMatchingExercise),
            const SizedBox(height: MayosSpacing.xs),
            MayosButton(
              key: const Key('coach_create_exercise_open'),
              label: copy.createExercise,
              variant: MayosButtonVariant.secondary,
              onPressed: onCreate,
            ),
          ],
        ),
      );
}

class CoachExerciseCreateDialog extends ConsumerStatefulWidget {
  const CoachExerciseCreateDialog({super.key, this.initialName = ''});

  final String initialName;

  @override
  ConsumerState<CoachExerciseCreateDialog> createState() =>
      _CoachExerciseCreateDialogState();
}

class _CoachExerciseCreateDialogState
    extends ConsumerState<CoachExerciseCreateDialog> {
  late final TextEditingController _name =
      TextEditingController(text: widget.initialName);
  final TextEditingController _bodyPart = TextEditingController();
  final TextEditingController _equipment = TextEditingController();
  final TextEditingController _note = TextEditingController();
  final TextEditingController _video = TextEditingController();
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _bodyPart.dispose();
    _equipment.dispose();
    _note.dispose();
    _video.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final String? validationError = _validationError();
    if (validationError != null) {
      setState(() => _error = validationError);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final ExerciseCatalogEntry created = await _submit();
      if (mounted) Navigator.of(context).pop(created);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showError(error);
    }
  }

  String? _validationError() {
    final CoachCopy copy = coachCopyOf(context);
    if (_name.text.trim().isEmpty) return copy.exerciseNameRequired;
    final String videoUrl = _video.text.trim();
    if (videoUrl.isEmpty) return null;
    final Uri? videoUri = Uri.tryParse(videoUrl);
    if (videoUri == null ||
        videoUri.scheme != 'https' ||
        videoUri.host.isEmpty) {
      return copy.videoLinkMustUseHttps;
    }
    return null;
  }

  Future<ExerciseCatalogEntry> _submit() =>
      ref.read(apiClientProvider).coachCreateExercise(
            CoachExerciseCreateRequest(
              name: _name.text.trim(),
              bodyPart: _bodyPart.text.trim(),
              equipment: _equipment.text.trim(),
              note: _note.text.trim(),
              videoUrl: _video.text.trim(),
            ),
          );

  void _showError(ApiException error) {
    setState(() {
      _saving = false;
      _error = displayCopyOf(context).failureMessage(apiFailureMessage(error));
    });
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return AlertDialog(
      title: Text(copy.createExercise),
      content: SizedBox(
        width: 360,
        child: SingleChildScrollView(child: _formFields(copy)),
      ),
      actions: _formActions(copy),
    );
  }

  Widget _formFields(CoachCopy copy) => Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          _nameField(copy),
          const SizedBox(height: MayosSpacing.sm),
          _bodyPartField(copy),
          const SizedBox(height: MayosSpacing.sm),
          _equipmentField(copy),
          const SizedBox(height: MayosSpacing.sm),
          _noteField(copy),
          const SizedBox(height: MayosSpacing.sm),
          _videoField(copy),
          if (_error != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            Text(_error!, style: MayosTypography.of(context).bodySecondary),
          ],
        ],
      );

  Widget _nameField(CoachCopy copy) => MayosTextField(
        controller: _name,
        autofocus: true,
        label: copy.exerciseName,
        fieldKey: const Key('coach_exercise_name'),
      );

  Widget _bodyPartField(CoachCopy copy) => MayosTextField(
        controller: _bodyPart,
        label: copy.bodyPartTag,
        fieldKey: const Key('coach_exercise_body_part'),
      );

  Widget _equipmentField(CoachCopy copy) => MayosTextField(
        controller: _equipment,
        label: copy.equipmentTag,
        fieldKey: const Key('coach_exercise_equipment'),
      );

  Widget _noteField(CoachCopy copy) => MayosTextField(
        controller: _note,
        label: copy.exerciseNoteOptional,
        fieldKey: const Key('coach_exercise_note'),
        minLines: 2,
        maxLines: 4,
      );

  Widget _videoField(CoachCopy copy) => MayosTextField(
        controller: _video,
        label: copy.videoLinkOptional,
        keyboardType: TextInputType.url,
        fieldKey: const Key('coach_exercise_video'),
      );

  List<Widget> _formActions(CoachCopy copy) => <Widget>[
        MayosButton(
          label: copy.cancel,
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
        ),
        MayosButton(
          key: const Key('coach_exercise_create'),
          label: copy.saveExercise,
          loading: _saving,
          expand: false,
          onPressed: _saving ? null : _save,
        ),
      ];
}
