import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/models.dart';
import '../../../providers.dart';
import '../../nutrition/pace_proposal_card.dart';
import '../tour/tour_targets.dart';
import 'nutrition_pace_dial.dart';
import 'food_log_day_view.dart';

class NutritionTab extends ConsumerStatefulWidget {
  const NutritionTab({this.targetsOnly = false, super.key});
  final bool targetsOnly;

  @override
  ConsumerState<NutritionTab> createState() => _NutritionTabState();
}

class _NutritionTabState extends ConsumerState<NutritionTab> {
  NutritionPlanState? _plan;
  String _sex = 'male';
  String _activity = 'mostly_sitting';
  bool _pregnancy = false;
  bool _condition = false;
  bool _eatingDisorder = false;
  bool _loading = true;
  bool _saving = false;
  bool _waterSaving = false;
  int _waterGlasses = 0;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final NutritionPlanState plan = await ref.read(apiClientProvider).nutrition();
      if (mounted) {
        setState(() { _plan = plan; _sex = plan.sex ?? 'male';
          _activity = plan.dailyActivity ?? _activity; _waterGlasses = plan.todayWaterGlasses;
          _loading = false; _error = null; });
      }
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _loading = false; });
    }
  }

  Future<void> _save() async {
    setState(() { _saving = true; _error = null; });
    try {
      final NutritionPlanState plan = await ref.read(apiClientProvider).setupNutrition(
        sex: _sex,
        sexConfirmed: true,
        dailyActivity: _activity,
        screening: <String, bool>{
          'pregnant_or_breastfeeding': _pregnancy,
          'medical_condition': _condition,
          'eating_disorder': _eatingDisorder,
        },
      );
      if (mounted) setState(() { _plan = plan; _saving = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Future<void> _editActivity(NutritionCopy copy) async {
    final String? selectedActivity = await _chooseActivity(copy);
    if (selectedActivity == null || !mounted) return;
    await _saveActivity(selectedActivity);
  }

  Future<String?> _chooseActivity(NutritionCopy copy) {
    String selected = _activity;
    return showDialog<String>(context: context, builder: (BuildContext context) =>
      AlertDialog(title: Text(copy.dailyActivity), content: DropdownButtonFormField<String>(
        initialValue: selected,
        items: <DropdownMenuItem<String>>[
          DropdownMenuItem(value: 'mostly_sitting', child: Text(copy.mostlySitting)),
          DropdownMenuItem(value: 'on_feet', child: Text(copy.onFeet)),
          DropdownMenuItem(value: 'physical_job', child: Text(copy.physicalJob)),
        ], onChanged: (String? value) { if (value != null) selected = value; }),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context), child: Text(copy.cancel)),
          FilledButton(onPressed: () => Navigator.pop(context, selected), child: Text(copy.updateTargets)),
        ]));
  }

  Future<void> _saveActivity(String activity) async {
    setState(() { _saving = true; _error = null; });
    try {
      final NutritionPlanState plan = await ref.read(apiClientProvider).updateNutritionActivity(activity);
      if (mounted) setState(() { _activity = activity; _plan = plan; _saving = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Future<void> _logAdherence(String value, {String? entryDate}) async {
    setState(() { _saving = true; _error = null; });
    try {
      final NutritionPlanState plan = await ref.read(apiClientProvider).logNutritionAdherence(value, entryDate: entryDate);
      if (mounted) setState(() { _plan = plan; _saving = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Future<void> _changeWater(bool undo, NutritionCopy copy) async {
    if (_waterSaving || (!undo && _waterGlasses >= 30) || (undo && _waterGlasses == 0)) return;
    setState(() => _waterSaving = true);
    try {
      final int count = await ref.read(apiClientProvider).changeWaterGlasses(undo: undo);
      if (mounted) setState(() => _waterGlasses = count);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${copy.waterUpdateFailed}: ${error.message}')),
        );
      }
    } finally {
      if (mounted) setState(() => _waterSaving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool arabic = ref.watch(displayLanguageProvider) == 'ar';
    final NutritionCopy copy = NutritionCopy(arabic ? 'ar' : 'en');
    return Directionality(
      textDirection: arabic ? TextDirection.rtl : TextDirection.ltr,
      child: _content(context, copy),
    );
  }

  Widget _content(BuildContext context, NutritionCopy copy) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return _loadError(context, copy);
    if (_plan?.state == 'not_started') return _setupForm(context, copy);
    if (_plan?.state == 'incomplete') return _incomplete(context, copy);
    if (_plan?.state == 'ready') {
      return _targets(context, copy, Theme.of(context).colorScheme, Theme.of(context).textTheme);
    }
    return _blocked(context, copy);
  }

  Widget _setupForm(BuildContext context, NutritionCopy copy) => ListView(
        padding: const EdgeInsets.all(24),
        children: <Widget>[
          TourTarget(
            id: 'nutrition',
            child: Text(copy.setup,
                style: Theme.of(context).textTheme.headlineMedium),
          ),
          const SizedBox(height: 16),
          _sexConfirmation(copy),
          const SizedBox(height: 16),
          _activityQuestion(copy),
          const SizedBox(height: 16),
          _healthCheck(copy),
          _setupButton(copy),
        ],
      );

  Widget _sexConfirmation(NutritionCopy copy) => Column(children: <Widget>[
    Text(copy.confirmSex),
    DropdownButtonFormField<String>(initialValue: _sex,
      items: <DropdownMenuItem<String>>[
        DropdownMenuItem(value: 'male', child: Text(copy.male)),
        DropdownMenuItem(value: 'female', child: Text(copy.female)),
      ], onChanged: (String? value) { if (value != null) setState(() => _sex = value); }),
  ]);

  Widget _activityQuestion(NutritionCopy copy) => Column(children: <Widget>[
    Text(copy.activityQuestion),
    DropdownButtonFormField<String>(initialValue: _activity,
      items: <DropdownMenuItem<String>>[
        DropdownMenuItem(value: 'mostly_sitting', child: Text(copy.mostlySitting)),
        DropdownMenuItem(value: 'on_feet', child: Text(copy.onFeet)),
        DropdownMenuItem(value: 'physical_job', child: Text(copy.physicalJob)),
      ], onChanged: (String? value) { if (value != null) setState(() => _activity = value); }),
  ]);

  Widget _healthCheck(NutritionCopy copy) => Column(children: <Widget>[
    Text(copy.healthCheck),
    CheckboxListTile(value: _pregnancy,
      onChanged: (bool? value) => setState(() => _pregnancy = value ?? false),
      title: Text(copy.pregnancy)),
    CheckboxListTile(value: _condition,
      onChanged: (bool? value) => setState(() => _condition = value ?? false),
      title: Text(copy.condition)),
    CheckboxListTile(value: _eatingDisorder,
      onChanged: (bool? value) => setState(() => _eatingDisorder = value ?? false),
      title: Text(copy.eatingDisorder)),
  ]);

  Widget _setupButton(NutritionCopy copy) => TourTarget(id: 'food_log', child: FilledButton(
    key: const Key('food_log_entry_point'),
    onPressed: _saving ? null : _save,
    child: Text(_saving ? copy.saving : copy.showTargets)));

  Widget _blocked(BuildContext context, NutritionCopy copy) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_plan?.state == 'under_18' ? copy.under18 : copy.dietitian,
              textAlign: TextAlign.center),
        ),
      );

  Widget _targets(BuildContext context, NutritionCopy copy, ColorScheme colors, TextTheme text) {
    if (widget.targetsOnly) return _targetDetails(context, copy, colors, text);
    return FoodLogDayView(targets: _plan!.targets,
      dailyControls: Column(crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _adherenceControl(copy),
          const SizedBox(height: 12),
          _waterLog(_plan!.targets ?? <String, dynamic>{}, copy),
          const SizedBox(height: 12),
          _recentAdherence(copy),
        ]),
      onShowTargets: () async {
        await Navigator.of(context).push<void>(MaterialPageRoute<void>(builder: (_) =>
          Scaffold(appBar: AppBar(title: Text(copy.coachTargets)), body: const NutritionTab(targetsOnly: true))));
        if (mounted) await _load();
      });
  }

  Widget _adherenceControl(NutritionCopy copy) => Column(
    crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      Text(copy.howTodayWent, style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 8),
      Wrap(spacing: 8, children: <Widget>[
        _adherenceButton(copy.onTarget, 'on_target', copy),
        _adherenceButton(copy.roughly, 'roughly', copy),
        _adherenceButton(copy.off, 'off', copy),
      ]),
    ]);

  Widget _targetDetails(BuildContext context, NutritionCopy copy, ColorScheme colors, TextTheme text) {
    final Map<String, dynamic> targets = _plan!.targets ?? <String, dynamic>{};
    final List<(String, String, Color)> macroCards = <(String, String, Color)>[
      (copy.protein, 'protein_g', colors.primary),
      (copy.carbs, 'carbs_g', colors.tertiary),
      (copy.fat, 'fat_g', colors.secondary),
    ];
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
      children: <Widget>[
        Text(copy.tab, style: text.headlineMedium),
        if (_plan!.goal != null) ...<Widget>[
          Text(_plan!.intensity == null ? copy.goal(_plan!.goal!)
              : copy.stop(_plan!.goal!, _plan!.intensity!), style: text.titleMedium),
          if (_plan!.goalReason != null)
            Text(copy.goalReason(_plan!.goalReason!)),
        ],
        if (_plan!.authority == 'coach')
          Align(alignment: AlignmentDirectional.centerStart,
            child: Chip(label: Text(copy.setByCoach))),
        if (_plan!.pendingGoal != null && _plan!.authority != 'coach') Card(child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
          Text(copy.updateOffer),
          Wrap(spacing: 8, children: <Widget>[
            TextButton(onPressed: _saving ? null : _dismissGoalOffer, child: Text(copy.dismiss)),
            FilledButton(onPressed: _saving ? null : () async {
              final NutritionPlanState? saved = await Navigator.of(context).push<NutritionPlanState>(
                MaterialPageRoute<NutritionPlanState>(builder: (_) => NutritionPaceDial(plan: _plan!, initialGoal: _plan!.pendingGoal)));
              if (saved != null && mounted) setState(() => _plan = saved);
            }, child: Text(copy.accept)),
          ]),
          ]),
        )),
        if (_plan!.paceProposal != null) PaceProposalCard(proposal: _plan!.paceProposal!,
          canDecide: _plan!.authority != 'coach', busy: _saving,
          onDecision: _decidePaceProposal),
        if (_plan!.authority != 'coach') Align(alignment: AlignmentDirectional.centerEnd, child: TextButton.icon(
          onPressed: _saving ? null : () async {
            final NutritionPlanState? saved = await Navigator.of(context).push<NutritionPlanState>(
              MaterialPageRoute<NutritionPlanState>(builder: (_) => NutritionPaceDial(plan: _plan!)));
            if (saved != null && mounted) setState(() => _plan = saved);
          }, icon: const Icon(Icons.tune), label: Text(copy.adjust))),
        _activityRow(copy),
        if (_plan!.cardioBurnedKcal > 0)
          Padding(padding: const EdgeInsets.only(top: 8),
            child: Text(copy.cardioBurned(_plan!.cardioBurnedKcal), style: text.bodyMedium)),
        if (_plan!.cardioAdjustmentKcal > 0)
          Padding(padding: const EdgeInsets.only(top: 4),
            child: Text(copy.cardioAdjustment(_plan!.cardioAdjustmentKcal), style: text.bodyMedium)),
        const SizedBox(height: 20),
        TourTarget(
          id: 'nutrition',
          child: _plate(targets, macroCards, copy, text),
        ),
        const SizedBox(height: 12),
        Text(copy.macrosTitle, style: text.titleMedium),
        _macroCards(targets, macroCards),
        const SizedBox(height: 8),
        _fiberWaterCards(targets, copy),
        const SizedBox(height: 12),
        _adherenceControl(copy),
        const SizedBox(height: 16),
        _recentAdherence(copy),
        if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
      ],
    );
  }

  Widget _recentAdherence(NutritionCopy copy) {
    final TextTheme text = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
        Text(copy.lastSevenDays, style: text.titleMedium),
        const SizedBox(height: 8),
        Wrap(spacing: 12, children: <Widget>[
          for (final Map<String, dynamic> day in _plan!.adherenceDays)
            Tooltip(message: '${day['date']}: ${copy.adherenceLabel(day['value'] as String?)}',
              child: InkWell(
                onTap: !_saving && _plan!.adherenceDays.length >= 2 &&
                    day['date'] == _plan!.adherenceDays[_plan!.adherenceDays.length - 2]['date']
                    ? () => _answerPastDay(day['date'] as String, copy) : null,
                child: _adherenceMark(day['value'] as String?, Theme.of(context).colorScheme))),
        ]),
        const SizedBox(height: 16),
        Text('${copy.latestWeight}: ${_plan!.latestWeight == null ? '—' : '${_plan!.latestWeight} ${copy.kilograms}'}', style: text.bodyLarge),
        Text('${copy.targetWeight}: ${_plan!.targetWeight == null ? '—' : '${_plan!.targetWeight} ${copy.kilograms}'}', style: text.bodyMedium),
    ]);
  }

  Future<void> _answerPastDay(String entryDate, NutritionCopy copy) async {
    final String? answer = await showDialog<String>(context: context,
      builder: (BuildContext dialogContext) => SimpleDialog(title: Text(entryDate),
        children: <Widget>[
          for (final String verdict in <String>['on_target', 'roughly', 'off'])
            SimpleDialogOption(onPressed: () => Navigator.pop(dialogContext, verdict),
              child: Text(copy.adherenceLabel(verdict))),
        ]));
    if (answer != null && mounted) await _logAdherence(answer, entryDate: entryDate);
  }

  Future<void> _decidePaceProposal(String decision) async {
    final Object? rawId = _plan?.paceProposal?['id'];
    final int? proposalId = rawId is num ? rawId.toInt() : int.tryParse('$rawId');
    if (proposalId == null || _saving) return;
    setState(() { _saving = true; _error = null; });
    try {
      final NutritionPlanState plan = await ref.read(apiClientProvider)
          .decideNutritionPaceProposal(proposalId, decision);
      if (mounted) setState(() { _plan = plan; _saving = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Widget _adherenceButton(String label, String value, NutritionCopy copy) =>
      ChoiceChip(label: Text(label), selected: _plan?.todayAdherence == value,
        onSelected: _saving ? null : (_) => _logAdherence(value));

  Widget _adherenceMark(String? value, ColorScheme colors) {
    final Color color = switch (value) {
      'on_target' => colors.primary,
      'roughly' => colors.tertiary,
      'off' => colors.error,
      _ => colors.outlineVariant,
    };
    final Widget mark = switch (value) {
      'on_target' => Icon(Icons.circle, color: color, size: 18),
      'roughly' => Icon(Icons.change_history, color: color, size: 20),
      'off' => Icon(Icons.square, color: color, size: 16),
      _ => Icon(Icons.circle_outlined, color: color, size: 18),
    };
    return SizedBox(width: 24, height: 24, child: Center(child: mark));
  }


  Future<void> _dismissGoalOffer() async {
    setState(() => _saving = true);
    try {
      final NutritionPlanState dismissed = await ref.read(apiClientProvider).dismissNutritionGoalOffer();
      if (mounted) setState(() { _plan = dismissed; _saving = false; });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Widget _activityRow(NutritionCopy copy) => ListTile(
    title: Text(copy.dailyActivity), subtitle: Text(copy.activityLabel(_activity)),
    trailing: _plan?.authority == 'coach' ? null : const Icon(Icons.edit),
    onTap: _saving || _plan?.authority == 'coach' ? null : () => _editActivity(copy));

  Widget _plate(Map<String, dynamic> targets,
      List<(String, String, Color)> macroCards, NutritionCopy copy, TextTheme text) {
    final int calories = (targets['calories'] as num? ?? 0).round();
    final List<Color> colors = macroCards.map(((String, String, Color) macro) => macro.$3).toList();
    final List<double> caloriesByMacro = <double>[
      (targets['protein_g'] as num? ?? 0) * 4,
      (targets['carbs_g'] as num? ?? 0) * 4,
      (targets['fat_g'] as num? ?? 0) * 9,
    ];
    return SizedBox(height: 220, child: Center(child: CustomPaint(
      size: const Size.square(210), painter: _PlatePainter(colors, caloriesByMacro),
      child: SizedBox(width: 210, height: 210, child: Center(child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[Text('$calories', style: text.headlineLarge), Text(copy.calories)],
      ))),
    )));
  }

  Widget _macroCards(Map<String, dynamic> targets,
      List<(String, String, Color)> macroCards) => Row(crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (int index = 0; index < macroCards.length; index++) ...<Widget>[
          if (index > 0) const SizedBox(width: 8),
          Expanded(child: Card(child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 12),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: <Widget>[
              CircleAvatar(backgroundColor: macroCards[index].$3, radius: 6),
              const SizedBox(height: 6),
              Text(macroCards[index].$1, textAlign: TextAlign.center,
                maxLines: 2, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 4),
              Text('${targets[macroCards[index].$2] ?? 0} g'),
            ]),
          ))),
        ],
      ]);

  Widget _fiberWaterCards(Map<String, dynamic> targets, NutritionCopy copy) =>
      Row(children: <Widget>[
        Expanded(child: Card(child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          child: Column(children: <Widget>[
            Text(copy.fiberTarget, textAlign: TextAlign.center, maxLines: 2,
                overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Text(copy.fiberValue(targets['fiber_g'] ?? 0)),
          ]),
        ))),
        const SizedBox(width: 8),
        Expanded(child: _waterLog(targets, copy)),
      ]);

  Widget _waterLog(Map<String, dynamic> targets, NutritionCopy copy) =>
      Card(child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          child: Column(children: <Widget>[
            Text(copy.waterTarget, textAlign: TextAlign.center, maxLines: 2,
                overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Text(copy.waterValue((targets['water_ml'] as num?)?.toInt() ?? 0),
                textAlign: TextAlign.center, maxLines: 2,
                overflow: TextOverflow.ellipsis),
            const SizedBox(height: 8),
            Text('${copy.waterLog}: ${copy.waterGlasses} $_waterGlasses'),
            Wrap(alignment: WrapAlignment.center, children: <Widget>[
              TextButton(onPressed: _saving || _waterSaving || _waterGlasses >= 30
                  ? null : () => _changeWater(false, copy), child: Text(copy.addGlass)),
              TextButton(onPressed: _saving || _waterSaving || _waterGlasses == 0
                  ? null : () => _changeWater(true, copy), child: Text(copy.undoGlass)),
            ]),
          ]),
      ));

  Widget _loadError(BuildContext context, NutritionCopy copy) => Center(child: Padding(
    padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
      Text(_error ?? '', textAlign: TextAlign.center),
      const SizedBox(height: 12), OutlinedButton(onPressed: () { setState(() { _loading = true; _error = null; }); _load(); }, child: Text(copy.retry)),
    ])));

  Widget _incomplete(BuildContext context, NutritionCopy copy) => Center(child: Padding(
    padding: const EdgeInsets.all(24), child: Text(_plan?.message ?? copy.incomplete, textAlign: TextAlign.center)));
}

class _PlatePainter extends CustomPainter {
  const _PlatePainter(this.colors, this.values);
  final List<Color> colors;
  final List<double> values;

  @override
  void paint(Canvas canvas, Size size) {
    final Rect rect = Offset.zero & size;
    final Paint paint = Paint()..style = PaintingStyle.stroke..strokeWidth = 20;
    final double total = values.fold<double>(0, (double a, double b) => a + b);
    double start = -1.5708;
    for (int i = 0; i < colors.length; i++) {
      paint.color = colors[i];
      final double sweep = total == 0 ? 0 : 6.2832 * values[i] / total;
      canvas.drawArc(rect.deflate(12), start, sweep, false, paint);
      start += sweep;
    }
  }

  @override
  bool shouldRepaint(_PlatePainter oldDelegate) =>
      oldDelegate.colors != colors || oldDelegate.values != values;
}
