import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';

const double kExercisePickerDialogWidth = 360;

/// Searches the real catalog so an exercise picked here carries an id the
/// service can validate, rather than an invented one that would be refused on
/// sync (ADR 020/033). It is both the **Add exercise** dialog and the search
/// **Replace exercise** opens (#162), which passes [targetMuscle].
///
/// The service's search matches names only — `GET /workouts/exercises` has no
/// muscle parameter — so the pre-filter is applied here: while the chip is on,
/// only rows whose `target_muscle` equals [targetMuscle] are offered, and
/// clearing the chip (or any query the player types) searches the whole
/// catalog again.
class ExercisePickerDialog extends ConsumerStatefulWidget {
  const ExercisePickerDialog({
    super.key,
    this.title = 'Add unplanned exercise',
    this.targetMuscle,
    this.excludeExerciseIds = const <String>{},
    this.emptyFilteredMessage = 'Every match is already in this workout.',
  });

  /// The dialog's heading: "Add unplanned exercise", or "Replace exercise".
  final String title;

  /// The planned exercise's target muscle (#162): when present the search
  /// opens listing that muscle's exercises (server-side `target_muscle`),
  /// with a pill that turns the pre-filter off to search by name.
  final String? targetMuscle;

  /// Exercise ids already in this workout (#162): the Replace search never
  /// offers them, planned or unplanned. Empty for Add exercise, which keeps
  /// offering the whole catalog.
  final Set<String> excludeExerciseIds;

  final String emptyFilteredMessage;

  @override
  ConsumerState<ExercisePickerDialog> createState() =>
      _ExercisePickerDialogState();
}

class _ExercisePickerDialogState
    extends ConsumerState<ExercisePickerDialog> {
  final TextEditingController _query = TextEditingController();

  bool _searching = false;
  String? _error;
  List<ExerciseCatalogEntry> _results = const <ExerciseCatalogEntry>[];

  /// Whether [widget.targetMuscle] narrows the results right now (#162).
  bool _muscleFilter = false;

  @override
  void initState() {
    super.initState();
    // Replace opens pre-listed with the target muscle; Add exercise never
    // filters and so never searches until the player asks.
    _muscleFilter = widget.targetMuscle != null;
    if (_muscleFilter) {
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

  /// The muscle the query is narrowed by right now, or null while the pill
  /// is off — the one place the two search modes are decided (#162).
  String? get _activeMuscle => _muscleFilter ? widget.targetMuscle : null;

  Future<void> _search() async {
    final String query = _query.text.trim();
    final String? muscle = _activeMuscle;
    if (query.isEmpty && muscle == null) {
      setState(() => _error = 'Type an exercise name to search.');
      return;
    }
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      // With a muscle set the server lists or narrows by `target_muscle`, so
      // the Replace dialog can show that muscle before any typing (#162);
      // Add exercise passes nothing and searches by name exactly as before.
      final List<ExerciseCatalogEntry> results = await ref
          .read(apiClientProvider)
          .searchExercises(query, targetMuscle: muscle);
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = results;
        _error = results.isEmpty
            ? (muscle == null
                  ? 'No matching exercise found.'
                  : 'No $muscle exercise matched.')
            : null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _searching = false;
        _results = const <ExerciseCatalogEntry>[];
        _error = error.message;
      });
    }
  }

  /// What the player is offered: the search's rows minus every exercise
  /// already in this workout (#162). The muscle itself is the server's job —
  /// `GET /workouts/exercises?target_muscle=` — so this list is whatever that
  /// query returned, minus the workout's own exercises.
  List<ExerciseCatalogEntry> get _visible => _results
      .where(
        (ExerciseCatalogEntry entry) =>
            !widget.excludeExerciseIds.contains(entry.id),
      )
      .toList(growable: false);

  /// The pill (#162): on, the server lists the target muscle (no name needed);
  /// off, the search goes back to the whole catalog by name — which needs a
  /// query, so an empty one says exactly that instead of showing muscle rows.
  void _toggleMuscleFilter() {
    setState(() {
      _muscleFilter = !_muscleFilter;
      if (!_muscleFilter && _query.text.trim().isEmpty) {
        _results = const <ExerciseCatalogEntry>[];
        _error = 'Type an exercise name to search.';
      }
    });
    // Re-list the muscle when it turns on; re-search by name when it turns
    // off and there is a query to search with.
    if (!_muscleFilter && _query.text.trim().isEmpty) {
      return;
    }
    unawaited(_search());
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ExerciseCatalogEntry> visible = _visible;
    final bool filteredOut = _results.isNotEmpty && visible.isEmpty;
    return AlertDialog(
      title: Text(widget.title),
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
              label: 'Search the exercise catalog',
            ),
            if (widget.targetMuscle != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.xs),
                child: _ExercisePickerMuscleFilterChip(
                  muscle: widget.targetMuscle!,
                  active: _muscleFilter,
                  onToggle: _toggleMuscleFilter,
                ),
              ),
            if (_searching)
              const Padding(
                padding: EdgeInsets.only(top: MayosSpacing.sm),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  _error!,
                  style: MayosTypography.bodySecondary.copyWith(
                    color: c.danger,
                  ),
                ),
              ),
            if (filteredOut)
              Padding(
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
                child: Text(
                  widget.emptyFilteredMessage,
                  style: MayosTypography.bodySecondary.copyWith(
                    color: c.textSecondary,
                  ),
                ),
              ),
            if (visible.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: <Widget>[
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
          label: 'Cancel',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          label: 'Search',
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
class _ExercisePickerMuscleFilterChip extends StatelessWidget {
  const _ExercisePickerMuscleFilterChip({
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
        alignment: Alignment.centerLeft,
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
                  'Muscle: $muscle',
                  style: MayosTypography.caption.copyWith(
                    color: active ? c.accent : c.textSecondary,
                  ),
                ),
                if (active) ...<Widget>[
                  const SizedBox(width: MayosSpacing.xs),
                  Icon(
                    Icons.close,
                    size: MayosIconSizes.small,
                    color: c.textMuted,
                    semanticLabel: 'Clear the muscle filter',
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
