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
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          OutlinedButton.icon(
            key: const Key('exercise_primary_muscle_filter'),
            onPressed: () => _chooseMuscles(context),
            icon: const Icon(Icons.filter_list),
            label: Text(
              copy.primaryMuscleFilterLabel(filterState.primaryMuscles.length),
            ),
          ),
          if (filterState.primaryMuscles.isNotEmpty) _selectedMuscleChips(copy),
        ],
      ),
    );
  }

  Widget _selectedMuscleChips(MayosCopy copy) => SizedBox(
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

  void _removeMuscle(String muscle) => onChanged(
        filterState.copyWith(
          primaryMuscles: filterState.primaryMuscles
              .where((String candidateMuscle) => candidateMuscle != muscle)
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
