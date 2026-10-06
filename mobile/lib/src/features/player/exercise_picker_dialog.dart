import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/exercise_filters.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import '../../shared/exercise_filter_bar.dart';

const double kExercisePickerDialogWidth = 360;

/// Returns the catalog's primary target muscle for a planned exercise.
/// Missing/offline/slow detail lookups produce an unfiltered picker instead.
Future<String?> exerciseTargetMuscle(ApiClient api, String exerciseId) async {
  try {
    final ExerciseCatalogDetail detail = await api
        .exerciseCatalogDetail(exerciseId)
        .timeout(const Duration(seconds: 3));
    return detail.primaryMuscles.isEmpty ? null : detail.primaryMuscles.first;
  } on Object {
    return null;
  }
}

/// Searches the real catalog so an exercise picked here carries an id the
/// service can validate, rather than an invented one that would be refused on
/// sync (ADR 020/033). It is both the **Add exercise** dialog and the search
/// **Replace exercise** opens (#162), which passes [targetMuscle].
///
/// The source [targetMuscle] filter remains available for the Replace flow;
/// the shared filter bar adds curated Primary muscle filters for every picker.
class ExercisePickerDialog extends ConsumerStatefulWidget {
  const ExercisePickerDialog({
    super.key,
    this.title,
    this.targetMuscle,
    this.excludeExerciseIds = const <String>{},
    this.suggestedSubstitutes = const <SuggestedSubstitute>[],
    this.emptyFilteredMessage,
  });

  /// The dialog's heading: "Add unplanned exercise", or "Replace exercise".
  final String? title;

  /// The planned exercise's source target muscle (#162), initially enabled
  /// when present. The separate shared bar filters curated Primary muscles.
  final String? targetMuscle;

  /// Exercise ids already in this workout (#162): the Replace search never
  /// offers them, planned or unplanned. Empty for Add exercise, which keeps
  /// offering the whole catalog.
  final Set<String> excludeExerciseIds;

  final List<SuggestedSubstitute> suggestedSubstitutes;

  final String? emptyFilteredMessage;

  @override
  ConsumerState<ExercisePickerDialog> createState() =>
      _ExercisePickerDialogState();
}

class _ExercisePickerDialogState extends ConsumerState<ExercisePickerDialog> {
  final TextEditingController _query = TextEditingController();

  bool _searching = false;
  String? _error;
  FailureMessage? _failure;
  List<ExerciseCatalogEntry> _results = const <ExerciseCatalogEntry>[];

  /// Whether [widget.targetMuscle] narrows the results right now (#162).
  bool _targetMuscleFilter = false;
  ExerciseFilterState _filterState = const ExerciseFilterState();

  @override
  void initState() {
    super.initState();
    // Replace opens pre-listed with the target muscle; Add exercise never
    // filters and so never searches until the player asks.
    _targetMuscleFilter = widget.targetMuscle != null;
    if (_targetMuscleFilter) {
      // The first listing runs before the player types anything (#162);
      // a microtask keeps setState out of initState.
      Future<void>.microtask(() {
        if (mounted) {
          unawaited(_search());
        }
      });
    }
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  /// The source target muscle selected for this Replace search (#162).
  String? get _activeTargetMuscle =>
      _targetMuscleFilter ? widget.targetMuscle : null;

  Future<void> _search() async {
    final String query = _query.text.trim();
    final String? targetMuscle = _activeTargetMuscle;
    final ExerciseFilterState filters = _filterState;
    if (query.isEmpty && targetMuscle == null && !filters.hasCuratedFilters) {
      setState(() {
        _results = const <ExerciseCatalogEntry>[];
        _error = displayCopyOf(context).typeExerciseName;
      });
      return;
    }
    setState(() {
      _searching = true;
      _error = null;
      _failure = null;
    });
    try {
      // Filter-only requests browse before the player enters a name.
      final List<ExerciseCatalogEntry> results = await ref
          .read(apiClientProvider)
          .searchExercises(
            query,
            targetMuscle: targetMuscle,
            primaryMuscles: filters.primaryMuscles,
            primaryActions: filters.primaryActions,
          );
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = results;
        _error = results.isEmpty && targetMuscle != null
            ? displayCopyOf(context).noMuscleExerciseMatched(targetMuscle)
            : results.isEmpty
                ? displayCopyOf(context).noMatchingExercise
                : null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = const <ExerciseCatalogEntry>[];
        _failure = apiFailureMessage(error);
      });
    }
  }

  /// What the player is offered: the search's rows minus every exercise
  /// already in this workout (#162). The server applies the source and
  /// curated muscle filters; this list removes exercises already in the workout.
  List<ExerciseCatalogEntry> get _visible => _results
      .where(
        (ExerciseCatalogEntry entry) =>
            !widget.excludeExerciseIds.contains(entry.id),
      )
      .toList(growable: false);

  List<SuggestedSubstitute> get _visibleSuggestions =>
      widget.suggestedSubstitutes
          .where((SuggestedSubstitute item) =>
              !widget.excludeExerciseIds.contains(item.exerciseId))
          .toList(growable: false);

  /// Toggle the source target muscle while preserving any curated filters.
  void _toggleTargetMuscleFilter() {
    setState(() {
      _targetMuscleFilter = !_targetMuscleFilter;
      if (!_targetMuscleFilter &&
          !_filterState.hasCuratedFilters &&
          _query.text.trim().isEmpty) {
        _results = const <ExerciseCatalogEntry>[];
        _error = displayCopyOf(context).typeExerciseName;
      }
    });
    unawaited(_search());
  }

  void _filtersChanged(ExerciseFilterState filters) {
    setState(() {
      _filterState = filters;
      if (filters.hasCuratedFilters) _targetMuscleFilter = false;
    });
    unawaited(_search());
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = displayCopyOf(context);
    final List<ExerciseCatalogEntry> visible = _visible;
    final bool filteredOut = _results.isNotEmpty && visible.isEmpty;
    return AlertDialog(
      title: Text(widget.title ?? copy.addUnplannedExercise),
      content: SizedBox(
        width: kExercisePickerDialogWidth,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosTextField(
              controller: _query,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              label: copy.searchExerciseCatalog,
            ),
            if (widget.targetMuscle != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.xs),
                child: _ExercisePickerTargetMuscleFilterChip(
                  muscle: widget.targetMuscle!,
                  active: _targetMuscleFilter,
                  onToggle: _toggleTargetMuscleFilter,
                ),
              ),
            ExerciseFilterBar(
              filterState: _filterState,
              onChanged: _filtersChanged,
            ),
            if (_searching)
              const Padding(
                padding: EdgeInsets.only(top: MayosSpacing.sm),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_error != null || _failure != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  _failure == null ? _error! : copy.failureMessage(_failure!),
                  style: MayosTypography.of(context).bodySecondary.copyWith(
                    color: c.danger,
                  ),
                ),
              ),
            if (filteredOut)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  widget.emptyFilteredMessage ??
                      copy.everyExerciseMatchInWorkout,
                  style: MayosTypography.of(context).bodySecondary.copyWith(
                    color: c.textSecondary,
                  ),
                ),
              ),
            if (visible.isNotEmpty || _visibleSuggestions.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: <Widget>[
                    if (_visibleSuggestions.isNotEmpty) ...<Widget>[
                      Padding(
                        padding: EdgeInsets.only(top: MayosSpacing.sm),
                        child: Text(copy.suggestedSubstitutes),
                      ),
                      for (final SuggestedSubstitute item
                          in _visibleSuggestions)
                        MayosSettingsTile(
                          icon: Icons.swap_horiz,
                          title: item.exerciseName,
                          onTap: () => Navigator.of(context).pop(
                            ExerciseCatalogEntry(
                              id: item.exerciseId,
                              name: item.exerciseName,
                            ),
                          ),
                        ),
                    ],
                    for (final ExerciseCatalogEntry entry in visible)
                      MayosSettingsTile(
                        icon: Icons.fitness_center,
                        title: entry.name,
                        onTap: () => Navigator.of(context).pop(entry),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
      actions: <Widget>[
        MayosButton(
          label: copy.cancel,
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          label: copy.search,
          expand: false,
          loading: _searching,
          onPressed: _searching ? null : _search,
        ),
      ],
    );
  }
}

/// The Replace search's pre-filter (#162): a full-height pill naming the
/// target muscle. On, the dialog lists that muscle straight from
/// `GET /workouts/exercises?target_muscle=`; the ✕ (or a tap) turns it off so
/// the same dialog searches the whole catalog by name.
class _ExercisePickerTargetMuscleFilterChip extends StatelessWidget {
  const _ExercisePickerTargetMuscleFilterChip({
    required this.muscle,
    required this.active,
    required this.onToggle,
  });

  final String muscle;
  final bool active;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return SizedBox(
      height: kMayosMinTapTarget,
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        child: InkWell(
          key: const ValueKey<String>('logger.search.muscleFilter'),
          borderRadius: MayosRadii.pillRadius,
          onTap: onToggle,
          child: Container(
            padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.sm,
              vertical: MayosSpacing.xxs,
            ),
            decoration: BoxDecoration(
              color: active ? c.accentSubtle : c.surfaceSunken,
              borderRadius: MayosRadii.pillRadius,
              border: Border.all(color: active ? c.accent : c.border),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  displayCopyOf(context).muscleFilterLabel(muscle),
                  style: MayosTypography.of(context).caption.copyWith(
                    color: active ? c.accent : c.textSecondary,
                  ),
                ),
                if (active) ...<Widget>[
                  const SizedBox(width: MayosSpacing.xs),
                  Icon(
                    Icons.close,
                    size: MayosIconSizes.small,
                    color: c.textMuted,
                    semanticLabel: displayCopyOf(context).clearMuscleFilter,
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
