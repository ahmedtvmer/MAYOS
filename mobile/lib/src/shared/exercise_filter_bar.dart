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
          Row(
            children: <Widget>[
              Expanded(child: _primaryMuscleButton(copy)),
              const SizedBox(width: MayosSpacing.xxs),
              Expanded(child: _primaryActionButton(copy)),
              const SizedBox(width: MayosSpacing.xxs),
              Expanded(child: _equipmentCategoryButton(copy)),
              if (filterState.showsLoadTypeFilter) ...<Widget>[
                const SizedBox(width: MayosSpacing.xxs),
                Expanded(child: _loadTypeButton(copy)),
              ],
            ],
          ),
          if (filterState.primaryMuscles.isNotEmpty ||
              filterState.primaryActions.isNotEmpty ||
              filterState.equipmentCategories.isNotEmpty ||
              filterState.loadTypes.isNotEmpty)
            _selectedChips(copy),
        ],
      ),
    );
  }

  Widget _primaryMuscleButton(MayosCopy copy) => _FilterSectionButton(
        title: copy.primaryMuscle,
        buttonLabel: copy.primaryMuscleFilterLabel(
          filterState.primaryMuscles.length,
        ),
        options: <_FilterOption>[
          for (final PrimaryMuscle muscle in primaryMuscles)
            _FilterOption(
              muscle.apiValue,
              copy.primaryMuscleLabel(muscle.apiValue),
            ),
        ],
        selectedValues: filterState.primaryMuscles,
        buttonKey: const Key('exercise_primary_muscle_filter'),
        keyPrefix: 'primary_muscle',
        doneKey: 'exercise_primary_muscle_done',
        onSelected: (List<String> values) => onChanged(
          filterState.copyWith(primaryMuscles: values),
        ),
      );

  Widget _primaryActionButton(MayosCopy copy) => _FilterSectionButton(
        title: copy.primaryAction,
        buttonLabel: copy.primaryActionFilterLabel(
          filterState.primaryActions.length,
        ),
        options: <_FilterOption>[
          for (final PrimaryAction action in primaryActions)
            _FilterOption(
              action.apiValue,
              copy.primaryActionLabel(action.apiValue),
            ),
        ],
        selectedValues: filterState.primaryActions,
        buttonKey: const Key('exercise_primary_action_filter'),
        keyPrefix: 'primary_action',
        doneKey: 'exercise_primary_action_done',
        onSelected: (List<String> values) => onChanged(
          filterState.copyWith(primaryActions: values),
        ),
      );

  Widget _equipmentCategoryButton(MayosCopy copy) => _FilterSectionButton(
        title: copy.equipmentCategory,
        buttonLabel: _countedLabel(
          copy.equipmentCategoryFilterShort,
          filterState.equipmentCategories.length,
        ),
        options: <_FilterOption>[
          for (final EquipmentCategory category in equipmentCategories)
            _FilterOption(
              category.apiValue,
              copy.equipmentCategoryLabel(category.apiValue),
            ),
        ],
        selectedValues: filterState.equipmentCategories,
        buttonKey: const Key('exercise_equipment_category_filter'),
        keyPrefix: 'equipment_category',
        doneKey: 'exercise_equipment_category_done',
        onSelected: (List<String> values) => onChanged(
          filterState.copyWith(equipmentCategories: values),
        ),
      );

  Widget _loadTypeButton(MayosCopy copy) => _FilterSectionButton(
        title: copy.loadType,
        buttonLabel: _countedLabel(
          copy.loadTypeFilterShort,
          filterState.loadTypes.length,
        ),
        options: <_FilterOption>[
          for (final LoadType loadType in loadTypes)
            _FilterOption(
              loadType.apiValue,
              copy.loadTypeLabel(loadType.apiValue),
            ),
        ],
        selectedValues: filterState.loadTypes,
        buttonKey: const Key('exercise_load_type_filter'),
        keyPrefix: 'load_type',
        doneKey: 'exercise_load_type_done',
        onSelected: (List<String> values) => onChanged(
          filterState.copyWith(loadTypes: values),
        ),
      );

  Widget _selectedChips(MayosCopy copy) => SizedBox(
        height: 48,
        child: ListView(
          scrollDirection: Axis.horizontal,
          children: <Widget>[
            for (final String muscle in filterState.primaryMuscles)
              _selectedFilterChip(
                'primary_muscle',
                muscle,
                copy.primaryMuscleLabel(muscle),
                () => onChanged(
                  filterState.copyWith(
                    primaryMuscles: filterState.primaryMuscles
                        .where((String selected) => selected != muscle)
                        .toList(growable: false),
                  ),
                ),
              ),
            for (final String action in filterState.primaryActions)
              _selectedFilterChip(
                'primary_action',
                action,
                copy.primaryActionLabel(action),
                () => onChanged(
                  filterState.copyWith(
                    primaryActions: filterState.primaryActions
                        .where((String selected) => selected != action)
                        .toList(growable: false),
                  ),
                ),
              ),
            for (final String category in filterState.equipmentCategories)
              _selectedFilterChip(
                'equipment_category',
                category,
                copy.equipmentCategoryLabel(category),
                () => onChanged(
                  filterState.copyWith(
                    equipmentCategories: filterState.equipmentCategories
                        .where((String selected) => selected != category)
                        .toList(growable: false),
                  ),
                ),
              ),
            for (final String loadType in filterState.loadTypes)
              _selectedFilterChip(
                'load_type',
                loadType,
                copy.loadTypeLabel(loadType),
                () => onChanged(
                  filterState.copyWith(
                    loadTypes: filterState.loadTypes
                        .where((String selected) => selected != loadType)
                        .toList(growable: false),
                  ),
                ),
              ),
          ],
        ),
      );

  Widget _selectedFilterChip(
    String keyPrefix,
    String apiValue,
    String label,
    VoidCallback onDeleted,
  ) =>
      InputChip(
        key: ValueKey<String>('${keyPrefix}_$apiValue'),
        label: Text(label),
        onDeleted: onDeleted,
      );

}

String _countedLabel(String label, int selectedCount) =>
    selectedCount == 0 ? label : '$label ($selectedCount)';

class _FilterOption {
  const _FilterOption(this.apiValue, this.label);

  final String apiValue;
  final String label;
}

class _FilterSectionButton extends StatelessWidget {
  const _FilterSectionButton({
    required this.title,
    required this.buttonLabel,
    required this.options,
    required this.selectedValues,
    required this.buttonKey,
    required this.keyPrefix,
    required this.doneKey,
    required this.onSelected,
  });

  final String title;
  final String buttonLabel;
  final List<_FilterOption> options;
  final List<String> selectedValues;
  final Key buttonKey;
  final String keyPrefix;
  final String doneKey;
  final ValueChanged<List<String>> onSelected;

  Future<void> _choose(BuildContext context) async {
    final List<String>? selection = await showModalBottomSheet<List<String>>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext context) => _MultiSelectFilterSheet(
        title: title,
        options: options,
        initialSelection: selectedValues,
        keyPrefix: keyPrefix,
        doneKey: doneKey,
      ),
    );
    if (selection != null) onSelected(selection);
  }

  @override
  Widget build(BuildContext context) => Tooltip(
        message: title,
        child: OutlinedButton(
          key: buttonKey,
          onPressed: () => _choose(context),
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xxs),
            minimumSize: const Size(0, 40),
          ),
          child: Text(buttonLabel, maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
      );
}

class _MultiSelectFilterSheet extends StatefulWidget {
  const _MultiSelectFilterSheet({
    required this.title,
    required this.options,
    required this.initialSelection,
    required this.keyPrefix,
    required this.doneKey,
  });

  final String title;
  final List<_FilterOption> options;
  final List<String> initialSelection;
  final String keyPrefix;
  final String doneKey;

  @override
  State<_MultiSelectFilterSheet> createState() => _MultiSelectFilterSheetState();
}

class _MultiSelectFilterSheetState extends State<_MultiSelectFilterSheet> {
  late final Set<String> _selected = Set<String>.of(widget.initialSelection);

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
              Text(widget.title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: MayosSpacing.sm),
              Expanded(
                child: SingleChildScrollView(
                  child: Wrap(
                    spacing: MayosSpacing.xs,
                    runSpacing: MayosSpacing.xs,
                    children: <Widget>[
                      for (final _FilterOption option in widget.options)
                        FilterChip(
                          key: ValueKey<String>(
                            '${widget.keyPrefix}_option_${option.apiValue}',
                          ),
                          label: Text(option.label),
                          selected: _selected.contains(option.apiValue),
                          onSelected: (bool selected) => setState(() {
                            if (selected) {
                              _selected.add(option.apiValue);
                            } else {
                              _selected.remove(option.apiValue);
                            }
                          }),
                        ),
                    ],
                  ),
                ),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: <Widget>[
                  TextButton(
                    onPressed: () => setState(_selected.clear),
                    child: Text(copy.clear),
                  ),
                  const SizedBox(width: MayosSpacing.xs),
                  FilledButton(
                    key: Key(widget.doneKey),
                    onPressed: () => Navigator.of(context).pop(
                      <String>[
                        for (final _FilterOption option in widget.options)
                          if (_selected.contains(option.apiValue))
                            option.apiValue,
                      ],
                    ),
                    child: Text(copy.done),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
