import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/nutrition_copy.dart';
import '../../core/display_language/coach_food_log_copy.dart';
import '../../core/models.dart';
import '../../providers.dart';
import 'coach_food_log_view.dart';

class CoachNutritionSegment extends ConsumerStatefulWidget {
  const CoachNutritionSegment({super.key, required this.assignmentId});

  final String assignmentId;

  @override
  ConsumerState<CoachNutritionSegment> createState() =>
      _CoachNutritionSegmentState();
}

class _CoachNutritionSegmentState extends ConsumerState<CoachNutritionSegment> {
  static const List<String> _targetFields = <String>[
    'calories',
    'protein_g',
    'carbs_g',
    'fat_g',
    'fiber_g',
    'water_ml',
  ];
  final Map<String, TextEditingController> _controllers =
      <String, TextEditingController>{
    for (final String day in <String>['daily', 'training_day', 'rest_day'])
      for (final String key in _targetFields)
        '${day}_$key': TextEditingController(),
  };
  CoachNutritionState? _state;
  String _goal = 'maintain';
  String _activity = 'mostly_sitting';
  bool _separateDayTargets = false;
  bool _busy = false;
  String? _error;
  bool _foodLog = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final TextEditingController controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final CoachNutritionState state = await ref
          .read(apiClientProvider)
          .coachPlayerNutrition(widget.assignmentId);
      if (!mounted) return;
      setState(() {
        _state = state;
        _goal = state.goal ?? 'maintain';
        _activity = state.dailyActivity ?? 'mostly_sitting';
        _showTargets(state.targets);
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error =
            displayCopyOf(context).failureMessage(apiFailureMessage(error)));
      }
    }
  }

  void _showTargets(Map<String, dynamic>? targets) {
    final Map<String, dynamic>? options = _state?.targetOptions;
    final Map<String, dynamic>? daily =
        options?['daily'] is Map<String, dynamic>
            ? options!['daily'] as Map<String, dynamic>
            : targets;
    final Map<String, dynamic>? training =
        options?['training_day'] is Map<String, dynamic>
            ? options!['training_day'] as Map<String, dynamic>
            : null;
    final Map<String, dynamic>? rest =
        options?['rest_day'] is Map<String, dynamic>
            ? options!['rest_day'] as Map<String, dynamic>
            : null;
    _separateDayTargets = training != null || rest != null;
    _setTargetFields('daily', daily);
    _setTargetFields('training_day', training);
    _setTargetFields('rest_day', rest);
  }

  void _setTargetFields(String day, Map<String, dynamic>? targets) {
    for (final String key in _targetFields) {
      final Object? value = targets?[key];
      _controllers['${day}_$key']!.text = value == null ? '' : '$value';
    }
  }

  Map<String, dynamic> _targetValue(String day) => <String, dynamic>{
        for (final String key in _targetFields)
          if (_controllers['${day}_$key']!.text.trim().isNotEmpty)
            key: int.tryParse(_controllers['${day}_$key']!.text.trim()) ?? 0,
      };

  Future<void> _save(NutritionCopy copy) async {
    bool confirmTakeover = false;
    if (_state?.authority != 'coach') {
      confirmTakeover = await showDialog<bool>(
            context: context,
            builder: (BuildContext context) => AlertDialog(
              title: Text(copy.coachTakeoverTitle),
              content: Text(copy.coachTakeoverPrompt),
              actions: <Widget>[
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: Text(copy.cancel)),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: Text(copy.coachConfirmTakeover)),
              ],
            ),
          ) ??
          false;
      if (!confirmTakeover) return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final CoachNutritionState state = await api.saveCoachPlayerNutrition(
        widget.assignmentId,
        goal: _goal,
        dailyActivity: _activity,
        confirmTakeover: confirmTakeover,
        targets: _separateDayTargets ? null : _targetValue('daily'),
        trainingDayTargets:
            _separateDayTargets ? _targetValue('training_day') : null,
        restDayTargets: _separateDayTargets ? _targetValue('rest_day') : null,
      );
      if (!mounted) return;
      setState(() {
        _state = state;
        _busy = false;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.coachNutritionSaved)));
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = copy.coachValidationError(error.message) ??
              displayCopyOf(context).failureMessage(apiFailureMessage(error));
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final NutritionCopy copy = displayCopyOf(context).nutrition;
    final CoachFoodLogCopy logCopy = CoachFoodLogCopy(copy.languageCode);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Wrap(spacing: 8, runSpacing: 8, children: <Widget>[
          ChoiceChip(label: Text(logCopy.targetsView), selected: !_foodLog,
            onSelected: (_) => setState(() => _foodLog = false)),
          ChoiceChip(label: Text(logCopy.foodLog), selected: _foodLog,
            onSelected: (_) => setState(() => _foodLog = true)),
        ]),
        const SizedBox(height: 12),
        if (_foodLog)
          CoachFoodLogView(assignmentId: widget.assignmentId)
        else
          _targetsContent(copy),
      ],
    );
  }

  Widget _targetsContent(NutritionCopy copy) {
    if (_error != null && _state == null) return Text(_error!);
    if (_state == null) return const Center(child: CircularProgressIndicator());
    return _nutritionContent(copy);
  }

  Widget _nutritionContent(NutritionCopy copy) =>
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
        _authorityHeader(copy),
        const SizedBox(height: 12),
        Text(copy.coachTargets, style: Theme.of(context).textTheme.titleLarge),
        _targetsEditor(copy),
        _saveButton(copy),
        if (_error != null)
          Text(_error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error)),
        const SizedBox(height: 20),
        _nutritionInsights(copy),
      ]);

  Widget _authorityHeader(NutritionCopy copy) {
    final bool coachAuthority = _state!.authority == 'coach';
    return Column(
      children: <Widget>[
        Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              Chip(
                  label: Text(coachAuthority
                      ? copy.coachSetByYou
                      : copy.coachSetByPlayer)),
              if (_state!.goal != null)
                Chip(label: Text(copy.goal(_state!.goal!))),
            ]),
      ],
    );
  }

  Widget _targetsEditor(NutritionCopy copy) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
        _goalSelector(copy),
        _activitySelector(copy),
        Text(
            '${copy.coachCalorieFloor}: ${_state!.calorieFloor ?? '—'} ${copy.calories}'),
        const SizedBox(height: 8),
        if (!_separateDayTargets)
          _targetFieldsRow(copy, 'daily')
        else ...<Widget>[
          Text(copy.coachTrainingDay,
              style: Theme.of(context).textTheme.titleMedium),
          _targetFieldsRow(copy, 'training_day'),
          Text(copy.coachRestDay,
              style: Theme.of(context).textTheme.titleMedium),
          _targetFieldsRow(copy, 'rest_day'),
        ],
        _dayTargetToggle(copy),
      ]);

  Widget _dayTargetToggle(NutritionCopy copy) => CheckboxListTile(
        contentPadding: EdgeInsets.zero,
        value: _separateDayTargets,
        onChanged: _busy
            ? null
            : (bool? value) {
                final bool separate = value ?? false;
                setState(() {
                  if (separate) {
                    for (final String key in _targetFields) {
                      _controllers['training_day_$key']!.text =
                          _controllers['daily_$key']!.text;
                      _controllers['rest_day_$key']!.text =
                          _controllers['daily_$key']!.text;
                    }
                  } else {
                    for (final String key in _targetFields) {
                      _controllers['daily_$key']!.text =
                          _controllers['training_day_$key']!.text;
                    }
                  }
                  _separateDayTargets = separate;
                });
              },
        title: Text(copy.coachUseDayTargets),
      );

  Widget _saveButton(NutritionCopy copy) => Align(
        alignment: AlignmentDirectional.centerStart,
        child: FilledButton(
            onPressed: _busy ? null : () => _save(copy),
            child: Text(_busy ? copy.saving : copy.coachSaveTargets)),
      );

  Widget _nutritionInsights(NutritionCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _adherenceStrip(copy),
        if (_state!.cardioBurnedKcal > 0)
          ListTile(dense: true, leading: const Icon(Icons.directions_run),
            title: Text(copy.cardioBurned(_state!.cardioBurnedKcal)),
            subtitle: Text(copy.cardioAdjustment(_state!.cardioAdjustmentKcal))),
        const SizedBox(height: 16),
        Card(child: ListTile(
          leading: const Icon(Icons.water_drop_outlined),
          title: Text(copy.waterLog),
          subtitle: Text('${copy.waterGlasses}: ${_state!.todayWaterGlasses}'),
        )),
        Text(copy.coachWaterHistory, style: Theme.of(context).textTheme.titleSmall),
        Wrap(spacing: 5, children: <Widget>[
          for (final Map<String, dynamic> day in _state!.waterDays)
            Tooltip(message: '${day['date']}: ${day['glasses']}',
              child: CircleAvatar(radius: 10,
                child: Text('${day['glasses']}', style: const TextStyle(fontSize: 9)))),
        ]),
        if (_state!.fiberEatenDays != null)
          Text(copy.fiberEaten),
          const SizedBox(height: 16),
          _weightTrend(copy),
          const SizedBox(height: 12),
          _paceCheck(copy),
        ],
      );

  Widget _paceCheck(NutritionCopy copy) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.speed),
        title: Text(copy.coachNextPaceCheck),
        subtitle: Text(copy.coachPaceCheckValue(_state!.nextPaceCheck)),
      );

  Widget _goalSelector(NutritionCopy copy) => DropdownButtonFormField<String>(
        initialValue: _goal,
        decoration: InputDecoration(labelText: copy.coachGoal),
        items: <String>['lose', 'maintain', 'gain']
            .map((String goal) => DropdownMenuItem<String>(
                value: goal, child: Text(copy.goal(goal))))
            .toList(),
        onChanged: _busy
            ? null
            : (String? value) {
                if (value != null) setState(() => _goal = value);
              },
      );

  Widget _activitySelector(NutritionCopy copy) =>
      DropdownButtonFormField<String>(
        initialValue: _activity,
        decoration: InputDecoration(labelText: copy.dailyActivity),
        items: <String>['mostly_sitting', 'on_feet', 'physical_job']
            .map((String value) => DropdownMenuItem<String>(
                value: value, child: Text(copy.activityLabel(value))))
            .toList(),
        onChanged: _busy
            ? null
            : (String? value) {
                if (value != null) setState(() => _activity = value);
              },
      );

  Widget _targetFieldsRow(NutritionCopy copy, String day) => LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
        final double width =
            constraints.maxWidth.isFinite ? constraints.maxWidth : 400;
        final double fieldWidth = (width - 24) / 3;
        final List<(String, String)> labels = <(String, String)>[
          ('calories', copy.coachTargetCalories),
          ('protein_g', copy.protein),
          ('carbs_g', copy.carbs),
          ('fat_g', copy.fat),
          ('fiber_g', copy.coachFiber),
          ('water_ml', copy.coachWater),
        ];
        return Wrap(
            spacing: 8,
            runSpacing: 8,
            children: labels
                .map(((String, String) field) => SizedBox(
                    width: fieldWidth.clamp(88, 180),
                    child: TextField(
                      controller: _controllers['${day}_${field.$1}'],
                      enabled: !_busy,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                          labelText: field.$2,
                          suffixText: field.$1 == 'calories' ? copy.calories
                              : field.$1 == 'water_ml' ? copy.waterUnit : copy.fiberUnit),
                    )))
                .toList());
      });

  Widget _adherenceStrip(NutritionCopy copy) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(copy.coachAdherence14,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SizedBox(
              height: 56,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                    children:
                        _state!.adherenceDays.skip(_state!.adherenceDays.length > 14 ? _state!.adherenceDays.length - 14 : 0).map((Map<String, dynamic> day) {
                  final String? value = day['value'] as String?;
                  final Color color = switch (value) {
                    'on_target' => colors.primary,
                    'roughly' => colors.tertiary,
                    'off' => colors.error,
                    _ => colors.outlineVariant,
                  };
                  return Tooltip(
                      message: '${day['date']}: ${copy.adherenceLabel(value)}',
                      child: Container(
                          width: 34,
                          height: 34,
                          margin: const EdgeInsetsDirectional.only(end: 8),
                          decoration: BoxDecoration(
                              color: color, shape: BoxShape.circle),
                          child: Center(
                              child: Text(
                                  value == null
                                      ? '·'
                                      : value == 'on_target'
                                          ? '●'
                                          : value == 'roughly'
                                              ? '▲'
                                              : '■',
                                  style: TextStyle(
                                      color: colors.onPrimary,
                                      fontSize: 13)))));
                }).toList()),
              )),
        ]);
  }

  Widget _weightTrend(NutritionCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(copy.coachWeightTrend,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          SizedBox(
              height: 46,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                    children: _state!.weightTrend
                        .map((Map<String, dynamic> point) => Padding(
                              padding:
                                  const EdgeInsetsDirectional.only(end: 12),
                              child: Text(copy.coachWeightValue(
                                  '${point['date']}',
                                  point['weight_kg'] ?? '—')),
                            ))
                        .toList()),
              )),
          if (_state!.targetWeight != null)
            Text(
                '${copy.targetWeight}: ${_state!.targetWeight} ${copy.kilograms}'),
        ],
      );
}
