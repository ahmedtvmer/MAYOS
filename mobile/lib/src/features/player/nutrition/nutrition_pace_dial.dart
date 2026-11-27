import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/models.dart';
import '../../../providers.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/ui/mayos_error_text.dart';

class NutritionPaceDial extends ConsumerStatefulWidget {
  const NutritionPaceDial({required this.plan, this.initialGoal, super.key});
  final NutritionPlanState plan;
  final String? initialGoal;

  @override
  ConsumerState<NutritionPaceDial> createState() => _NutritionPaceDialState();
}

class _NutritionPaceDialState extends ConsumerState<NutritionPaceDial> {
  static const List<(String, String)> _stops = <(String, String)>[
    ('lose', 'aggressive'), ('lose', 'moderate'), ('lose', 'light'),
    ('maintain', 'moderate'), ('gain', 'light'), ('gain', 'moderate'), ('gain', 'aggressive'),
  ];
  late (String, String) _selected;
  Map<String, dynamic>? _preview;
  bool _loading = false;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final int current = _stops.indexWhere((stop) => stop.$1 == widget.plan.goal &&
        (stop.$2 == (widget.plan.intensity ?? 'moderate')));
    _selected = _stops[current < 0 ? 3 : current];
    if (widget.initialGoal != null) {
      final int pending = _stops.indexWhere((stop) =>
          stop.$1 == widget.initialGoal && stop.$2 == 'moderate');
      if (pending >= 0) _selected = _stops[pending];
    }
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadPreview());
  }

  Future<void> _loadPreview() async {
    setState(() { _loading = true; _error = null; });
    try {
      final Map<String, dynamic> value = await ref.read(apiClientProvider)
          .previewNutrition(_selected.$1, _selected.$2);
      if (mounted) setState(() { _preview = value; _loading = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = displayCopyOf(context).failureMessage(apiFailureMessage(error)); _loading = false; });
    }
  }

  Future<void> _save(NutritionCopy copy) async {
    Map<String, bool>? screening;
    if (_selected.$1 == 'lose' && widget.plan.goal != 'lose') {
      screening = await _screening(copy);
      if (screening == null || !mounted) return;
    }
    setState(() { _saving = true; _error = null; });
    try {
      final NutritionPlanState saved = await ref.read(apiClientProvider)
          .saveNutritionGoal(_selected.$1, _selected.$2, screening: screening);
      if (mounted) Navigator.of(context).pop(saved);
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = displayCopyOf(context).failureMessage(apiFailureMessage(error)); _saving = false; });
    }
  }

  Future<Map<String, bool>?> _screening(NutritionCopy copy) async {
    bool pregnancy = false, condition = false, disorder = false;
    return showDialog<Map<String, bool>>(context: context, builder: (BuildContext context) => StatefulBuilder(
      builder: (BuildContext context, StateSetter setDialog) => AlertDialog(
        title: Text(copy.healthCheck),
        content: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
          CheckboxListTile(value: pregnancy, onChanged: (bool? v) => setDialog(() => pregnancy = v ?? false), title: Text(copy.pregnancy)),
          CheckboxListTile(value: condition, onChanged: (bool? v) => setDialog(() => condition = v ?? false), title: Text(copy.condition)),
          CheckboxListTile(value: disorder, onChanged: (bool? v) => setDialog(() => disorder = v ?? false), title: Text(copy.eatingDisorder)),
        ]),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context), child: Text(copy.cancel)),
          FilledButton(onPressed: () => Navigator.pop(context, <String, bool>{
            'pregnant_or_breastfeeding': pregnancy, 'medical_condition': condition, 'eating_disorder': disorder,
          }), child: Text(copy.continueLabel)),
        ],
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final bool arabic = ref.watch(displayLanguageProvider) == 'ar';
    final NutritionCopy copy = NutritionCopy(arabic ? 'ar' : 'en');
    final Map<String, dynamic> targets = Map<String, dynamic>.from(_preview?['targets'] as Map? ?? <String, dynamic>{});
    final double weeklyChange = ( _preview?['weekly_change_kg'] as num? ?? 0).toDouble();
    return Directionality(textDirection: arabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(appBar: AppBar(title: Text(copy.adjust)), body: ListView(padding: const EdgeInsets.all(20), children: <Widget>[
        Text(copy.adjust, style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 16),
        Wrap(spacing: 8, children: <Widget>[
          for (final (String, String) stop in _stops) ChoiceChip(
            label: Text(copy.stop(stop.$1, stop.$2)), selected: stop == _selected,
            onSelected: _loading ? null : (bool selected) {
              if (selected) { setState(() => _selected = stop); _loadPreview(); }
            }),
        ]),
        if (_loading) const Center(child: CircularProgressIndicator()),
        if (targets.isNotEmpty) ...<Widget>[
          Text('${targets['calories']} ${copy.calories}', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
          Text('${copy.protein}: ${targets['protein_g']} g · ${copy.carbs}: ${targets['carbs_g']} g · ${copy.fat}: ${targets['fat_g']} g'),
          Text('${copy.weeklyChange}: ${copy.weeklyRate(weeklyChange)}'),
          if (targets['floor_applied'] == true) Text(copy.floorWarning, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (_preview?['gain_target_warning'] == true) Text(copy.gainWarning, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (_preview?['reach_target_date'] != null)
            Text('${copy.reachTarget}: ${copy.formatDate(_preview!['reach_target_date'] as String)}'),
        ],
        if (_error != null) MayosErrorText(_error!),
        FilledButton(onPressed: _saving || _loading ? null : () => _save(copy), child: Text(copy.saveGoal)),
      ])));
  }
}
