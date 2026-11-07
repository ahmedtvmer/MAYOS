import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/coach_food_log_models.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_food_log_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../providers.dart';

class CoachFoodLogView extends ConsumerStatefulWidget {
  const CoachFoodLogView({super.key, required this.assignmentId});
  final String assignmentId;

  @override
  ConsumerState<CoachFoodLogView> createState() => _CoachFoodLogViewState();
}

class _CoachFoodLogViewState extends ConsumerState<CoachFoodLogView> {
  static final DateTime _firstDate = DateTime(1);
  CoachFoodLogDay? _day;
  DateTime? _selectedDate;
  bool _loading = true;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(CoachFoodLogView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.assignmentId != widget.assignmentId) {
      _day = null;
      _load();
    }
  }

  Future<void> _load([DateTime? date]) async {
    final int request = ++_request;
    setState(() {
      _loading = true;
      _error = null;
      _selectedDate = date;
    });
    try {
      final CoachFoodLogDay day = await ref.read(apiClientProvider)
          .coachPlayerFoodLog(widget.assignmentId,
            day: date?.toIso8601String().substring(0, 10));
      if (!mounted || request != _request) return;
      setState(() {
        _day = day;
        _selectedDate = day.date;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted || request != _request) return;
      setState(() {
        _error = displayCopyOf(context).failureMessage(apiFailureMessage(error));
        _loading = false;
      });
    }
  }

  Future<void> _pickDay() async {
    final DateTime? date = await showDatePicker(
      context: context, initialDate: _selectedDate!,
      firstDate: _firstDate, lastDate: _day!.today,
    );
    if (mounted && date != null) await _load(date);
  }

  void _moveDay(int offset) {
    final DateTime date = _selectedDate!;
    _load(DateTime(date.year, date.month, date.day + offset));
  }

  @override
  Widget build(BuildContext context) {
    final CoachFoodLogCopy copy = CoachFoodLogCopy(
      displayCopyOf(context).nutrition.languageCode);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        if (_day != null) _dayPicker(copy),
        if (_loading) const Center(child: CircularProgressIndicator())
        else if (_error != null) ...<Widget>[
          Text(_error!),
          Align(alignment: AlignmentDirectional.centerStart,
            child: TextButton(onPressed: () => _load(_selectedDate), child: Text(copy.retry))),
        ] else if (_day != null) ...<Widget>[
          _adherenceBadge(copy),
          const SizedBox(height: 12),
          if (_day!.entries.isEmpty) Text(copy.noEntries),
          _dayTable(copy),
        ],
      ],
    );
  }

  Widget _dayPicker(CoachFoodLogCopy copy) => Row(children: <Widget>[
    IconButton(key: const ValueKey<String>('coach-log-previous'),
      tooltip: copy.previousDay,
      onPressed: _loading || !_selectedDate!.isAfter(_firstDate) ? null : () => _moveDay(-1),
      icon: const Icon(Icons.arrow_back)),
    Expanded(child: TextButton(key: const ValueKey<String>('coach-log-date'),
      onPressed: _loading ? null : _pickDay,
      child: Text(MaterialLocalizations.of(context).formatMediumDate(_selectedDate!),
        textAlign: TextAlign.center))),
    IconButton(key: const ValueKey<String>('coach-log-next'),
      tooltip: copy.nextDay,
      onPressed: _loading || !_selectedDate!.isBefore(_day!.today) ? null : () => _moveDay(1),
      icon: const Icon(Icons.arrow_forward)),
  ]);

  Widget _adherenceBadge(CoachFoodLogCopy copy) {
    final Map<String, dynamic>? adherence = _day!.adherence;
    final String? value = adherence?['value'] as String?;
    final ColorScheme colors = Theme.of(context).colorScheme;
    final Color color = switch (value) {
      'off' => colors.error,
      'roughly' => colors.tertiary,
      _ => colors.primary,
    };
    final String source = adherence == null ? ''
        : ' · ${adherence['source'] == 'computed' ? copy.computed : copy.answered}';
    return Align(alignment: AlignmentDirectional.centerStart,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(border: Border.all(color: color),
          borderRadius: BorderRadius.circular(16)),
        child: Text('${copy.adherenceLabel(value)}$source', style: TextStyle(color: color)),
      ));
  }

  Widget _dayTable(CoachFoodLogCopy copy) => LayoutBuilder(
    builder: (BuildContext context, BoxConstraints constraints) => Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(12)),
      child: SingleChildScrollView(
        key: const ValueKey<String>('coach-log-table-scroll'),
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: BoxConstraints(minWidth: constraints.maxWidth),
          child: DataTable(
            horizontalMargin: 16, columnSpacing: 24,
            dataRowMinHeight: 56, dataRowMaxHeight: double.infinity,
            columns: <DataColumn>[
              for (final String label in <String>[
                copy.meal, copy.foodLogFood, copy.amount, copy.calories,
                '${copy.protein} (${copy.grams})', '${copy.carbs} (${copy.grams})',
                '${copy.fat} (${copy.grams})',
              ]) DataColumn(label: Text(label)),
            ],
            rows: <DataRow>[
              for (final CoachFoodLogEntry entry in _day!.entries) _entryRow(entry, copy),
              _totalsRow(copy),
            ],
          ),
        ),
      ),
    ),
  );

  DataRow _entryRow(CoachFoodLogEntry entry, CoachFoodLogCopy copy) => DataRow(
    cells: <DataCell>[
      DataCell(Text(copy.mealLabel(entry.meal))),
      DataCell(_foodName(entry, copy)),
      DataCell(Text(entry.quantity == null ? ''
        : copy.amountLabel(entry.quantity!.toDouble(), entry.unit!, entry.portionLabel))),
      for (final String key in _nutrientKeys) DataCell(Text(_number(entry.nutrients[key]))),
    ],
  );

  Widget _foodName(CoachFoodLogEntry entry, CoachFoodLogCopy copy) {
    final String? tag = switch (entry.kind) {
      'quick_add' => copy.quickAdd,
      'personal_food' => copy.personalFood,
      _ => entry.foodId?.startsWith('mayos:') == true ? copy.recipe : null,
    };
    final String name = entry.kind == 'quick_add' ? copy.quickAdd
      : copy.isArabic ? entry.arabicName ?? entry.name : entry.name;
    return SizedBox(width: 260, child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min, children: <Widget>[
          Text(name),
          if (tag != null) Chip(label: Text(tag), visualDensity: VisualDensity.compact),
        ]),
    ));
  }

  DataRow _totalsRow(CoachFoodLogCopy copy) => DataRow(cells: <DataCell>[
    DataCell(SizedBox(width: 180, child: Text(
      _day!.targets == null ? copy.dayTotal : copy.totalTarget))),
    const DataCell(Text('')), const DataCell(Text('')),
    for (int index = 0; index < _nutrientKeys.length; index++)
      DataCell(_totalComparison(index, copy)),
  ]);

  Widget _totalComparison(int index, CoachFoodLogCopy copy) {
    final num total = _day!.totals[_nutrientKeys[index]]!;
    final num? target = _day!.targets?[_targetKeys[index]] as num?;
    if (target == null) return Text(_number(total));
    final num difference = total - target;
    final ColorScheme colors = Theme.of(context).colorScheme;
    final String status = difference > 0 ? copy.over : difference < 0 ? copy.short : copy.atTarget;
    return Padding(padding: const EdgeInsets.symmetric(vertical: 8),
      child: Text('${_number(total)} · ${_number(target)}\n$status',
        style: TextStyle(color: difference > 0 ? colors.error
          : difference < 0 ? colors.tertiary : colors.primary)));
  }

  static const List<String> _nutrientKeys = <String>[
    'energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g',
  ];
  static const List<String> _targetKeys = <String>['calories', 'protein_g', 'carbs_g', 'fat_g'];
  String _number(num? value) => value == null ? ''
    : value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(1);
}
