import 'package:flutter/material.dart';

import '../core/display_language/catalog.dart';
import '../core/display_language/copy_context.dart';
import '../core/exercise_filters.dart';
import '../core/theme/mayos_spacing.dart';

class ExerciseFilterBar extends StatelessWidget {
  const ExerciseFilterBar({
    required this.filterState,
    required this.onChanged,
    super.key,
  });

  final ExerciseFilterState filterState;
  final ValueChanged<ExerciseFilterState> onChanged;

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    final ButtonStyle filterButtonStyle = OutlinedButton.styleFrom(
      minimumSize: const Size(0, 48),
      padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xs),
      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: OutlinedButton(
                  key: const Key('exercise_primary_muscle_filter'),
                  onPressed: () => _chooseMuscles(context),
                  style: filterButtonStyle,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.filter_list),
                      const SizedBox(width: MayosSpacing.xs),
                      Flexible(
                        child: Text(
                          copy.primaryMuscleFilterLabel(
                            filterState.primaryMuscles.length,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: OutlinedButton(
                  key: const Key('exercise_primary_action_filter'),
                  onPressed: () => _chooseActions(context),
                  style: filterButtonStyle,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.filter_list),
                      const SizedBox(width: MayosSpacing.xs),
                      Flexible(
                        child: Text(
                          copy.actionFilterLabel(
                            filterState.primaryActions.length,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          if (filterState.primaryMuscles.isNotEmpty ||
              filterState.primaryActions.isNotEmpty)
            _selectedFilterChips(copy),
        ],
      ),
    );
  }

  Widget _selectedFilterChips(MayosCopy copy) => SizedBox(
        height: 48,
        child: ListView(
          scrollDirection: Axis.horizontal,
          children: <Widget>[
            for (final String muscle in filterState.primaryMuscles)
              InputChip(
                key: ValueKey<String>('primary_muscle_$muscle'),
                label: Text(copy.primaryMuscleLabel(muscle)),
                onDeleted: () => _removeMuscle(muscle),
              ),
            for (final String action in filterState.primaryActions)
              InputChip(
                key: ValueKey<String>('primary_action_$action'),
                label: Text(copy.primaryActionLabel(action)),
                onDeleted: () => _removeAction(action),
              ),
          ],
        ),
      );

  Future<void> _chooseMuscles(BuildContext context) async {
    final List<String>? selection = await showModalBottomSheet<List<String>>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext context) => _PrimaryMusclePickerSheet(
        initialSelection: filterState.primaryMuscles,
      ),
    );
    if (selection != null) {
      onChanged(filterState.copyWith(primaryMuscles: selection));
    }
  }

  Future<void> _chooseActions(BuildContext context) async {
    final List<String>? selection = await showModalBottomSheet<List<String>>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext context) => _PrimaryActionPickerSheet(
        initialSelection: filterState.primaryActions,
      ),
    );
    if (selection != null) {
      onChanged(filterState.copyWith(primaryActions: selection));
    }
  }

  void _removeMuscle(String muscle) => onChanged(
        filterState.copyWith(
          primaryMuscles: filterState.primaryMuscles
              .where((String candidateMuscle) => candidateMuscle != muscle)
              .toList(growable: false),
        ),
      );

  void _removeAction(String action) => onChanged(
        filterState.copyWith(
          primaryActions: filterState.primaryActions
              .where((String candidateAction) => candidateAction != action)
              .toList(growable: false),
        ),
      );
}

class _PrimaryMusclePickerSheet extends StatefulWidget {
  const _PrimaryMusclePickerSheet({required this.initialSelection});

  final List<String> initialSelection;

  @override
  State<_PrimaryMusclePickerSheet> createState() =>
      _PrimaryMusclePickerSheetState();
}

class _PrimaryMusclePickerSheetState extends State<_PrimaryMusclePickerSheet> {
  late final Set<String> _selectedMuscles =
      Set<String>.of(widget.initialSelection);

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    final double sheetHeight = MediaQuery.of(context).size.height * .72;
    return SafeArea(
      child: SizedBox(
        height: sheetHeight,
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(copy.primaryMuscle,
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: MayosSpacing.sm),
              Expanded(child: _muscleOptions(copy)),
              _actions(copy),
            ],
          ),
        ),
      ),
    );
  }

  Widget _muscleOptions(MayosCopy copy) => SingleChildScrollView(
        child: Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (final PrimaryMuscle muscle in primaryMuscles)
              FilterChip(
                key: ValueKey<String>(
                  'primary_muscle_option_${muscle.apiValue}',
                ),
                label: Text(copy.primaryMuscleLabel(muscle.apiValue)),
                selected: _selectedMuscles.contains(muscle.apiValue),
                onSelected: (bool isSelected) =>
                    _toggleMuscle(muscle.apiValue, isSelected),
              ),
          ],
        ),
      );

  Widget _actions(MayosCopy copy) => Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: <Widget>[
          TextButton(
            onPressed: () => setState(_selectedMuscles.clear),
            child: Text(copy.clear),
          ),
          const SizedBox(width: MayosSpacing.xs),
          FilledButton(
            key: const Key('exercise_primary_muscle_done'),
            onPressed: () => Navigator.of(context).pop(_orderedSelection),
            child: Text(copy.done),
          ),
        ],
      );

  List<String> get _orderedSelection => primaryMuscles
      .map((PrimaryMuscle muscle) => muscle.apiValue)
      .where(_selectedMuscles.contains)
      .toList(growable: false);

  void _toggleMuscle(String muscle, bool isSelected) {
    setState(() {
      if (isSelected) {
        _selectedMuscles.add(muscle);
      } else {
        _selectedMuscles.remove(muscle);
      }
    });
  }
}

class _PrimaryActionPickerSheet extends StatefulWidget {
  const _PrimaryActionPickerSheet({required this.initialSelection});

  final List<String> initialSelection;

  @override
  State<_PrimaryActionPickerSheet> createState() =>
      _PrimaryActionPickerSheetState();
}

class _PrimaryActionPickerSheetState extends State<_PrimaryActionPickerSheet> {
  late final Set<String> _selectedActions =
      Set<String>.of(widget.initialSelection);

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    final double sheetHeight = MediaQuery.of(context).size.height * .72;
    return SafeArea(
      child: SizedBox(
        height: sheetHeight,
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(copy.action, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: MayosSpacing.sm),
              Expanded(child: _actionOptions(copy)),
              _actions(copy),
            ],
          ),
        ),
      ),
    );
  }

  Widget _actionOptions(MayosCopy copy) => SingleChildScrollView(
        child: Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (final PrimaryAction action in primaryActions)
              FilterChip(
                key: ValueKey<String>(
                  'primary_action_option_${action.apiValue}',
                ),
                label: Text(copy.primaryActionLabel(action.apiValue)),
                selected: _selectedActions.contains(action.apiValue),
                onSelected: (bool isSelected) =>
                    _toggleAction(action.apiValue, isSelected),
              ),
          ],
        ),
      );

  Widget _actions(MayosCopy copy) => Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: <Widget>[
          TextButton(
            onPressed: () => setState(_selectedActions.clear),
            child: Text(copy.clear),
          ),
          const SizedBox(width: MayosSpacing.xs),
          FilledButton(
            key: const Key('exercise_primary_action_done'),
            onPressed: () => Navigator.of(context).pop(_orderedSelection),
            child: Text(copy.done),
          ),
        ],
      );

  List<String> get _orderedSelection => primaryActions
      .map((PrimaryAction action) => action.apiValue)
      .where(_selectedActions.contains)
      .toList(growable: false);

  void _toggleAction(String action, bool isSelected) {
    setState(() {
      if (isSelected) {
        _selectedActions.add(action);
      } else {
        _selectedActions.remove(action);
      }
    });
  }
}
