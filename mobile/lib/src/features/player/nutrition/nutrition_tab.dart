import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/models.dart';
import '../../../core/food_log_models.dart';
import '../../../core/theme/mayos_spacing.dart';
import 'nutrition_check_in_card.dart';
import 'nutrition_tile.dart';
import '../../../providers.dart';
import '../../nutrition/pace_proposal_card.dart';
import '../tour/tour_targets.dart';
import 'nutrition_pace_dial.dart';
import 'food_log_day_view.dart';
import 'nutrition_targets_view.dart';

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
      final NutritionPlanState plan =
          await ref.read(apiClientProvider).nutrition();
      if (mounted) {
        setState(() {
          _plan = plan;
          _sex = plan.sex ?? 'male';
          _activity = plan.dailyActivity ?? _activity;
          _waterGlasses = plan.todayWaterGlasses;
          _loading = false;
          _error = null;
        });
      }
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _loading = false;
        });
    }
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final NutritionPlanState plan =
          await ref.read(apiClientProvider).setupNutrition(
        sex: _sex,
        sexConfirmed: true,
        dailyActivity: _activity,
        screening: <String, bool>{
          'pregnant_or_breastfeeding': _pregnancy,
          'medical_condition': _condition,
          'eating_disorder': _eatingDisorder,
        },
      );
      if (mounted)
        setState(() {
          _plan = plan;
          _saving = false;
        });
      if (mounted && plan.state == 'ready' && !widget.targetsOnly) {
        await _showTargets(NutritionCopy(ref.read(displayLanguageProvider)));
      }
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  Future<void> _editActivity(NutritionCopy copy) async {
    final String? selectedActivity = await _chooseActivity(copy);
    if (selectedActivity == null || !mounted) return;
    await _saveActivity(selectedActivity);
  }

  Future<String?> _chooseActivity(NutritionCopy copy) {
    String selected = _activity;
    return showDialog<String>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
                title: Text(copy.dailyActivity),
                content: DropdownButtonFormField<String>(
                    initialValue: selected,
                    items: <DropdownMenuItem<String>>[
                      DropdownMenuItem(
                          value: 'mostly_sitting',
                          child: Text(copy.mostlySitting)),
                      DropdownMenuItem(
                          value: 'on_feet', child: Text(copy.onFeet)),
                      DropdownMenuItem(
                          value: 'physical_job', child: Text(copy.physicalJob)),
                    ],
                    onChanged: (String? value) {
                      if (value != null) selected = value;
                    }),
                actions: <Widget>[
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: Text(copy.cancel)),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, selected),
                      child: Text(copy.updateTargets)),
                ]));
  }

  Future<void> _saveActivity(String activity) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final NutritionPlanState plan =
          await ref.read(apiClientProvider).updateNutritionActivity(activity);
      if (mounted)
        setState(() {
          _activity = activity;
          _plan = plan;
          _saving = false;
        });
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  Future<void> _logAdherence(String value, {String? entryDate}) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final NutritionPlanState plan = await ref
          .read(apiClientProvider)
          .logNutritionAdherence(value, entryDate: entryDate);
      if (mounted)
        setState(() {
          _plan = plan;
          _saving = false;
        });
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  Future<void> _changeWater(bool undo, NutritionCopy copy) async {
    if (_waterSaving ||
        (!undo && _waterGlasses >= 30) ||
        (undo && _waterGlasses == 0)) return;
    setState(() => _waterSaving = true);
    try {
      final int count =
          await ref.read(apiClientProvider).changeWaterGlasses(undo: undo);
      if (mounted) setState(() => _waterGlasses = count);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text('${copy.waterUpdateFailed}: ${error.message}')),
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
      return _targets(context, copy);
    }
    return _blocked(context, copy);
  }

  Widget _setupForm(BuildContext context, NutritionCopy copy) => ListView(
        padding: const EdgeInsets.all(24),
        children: <Widget>[
          Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                TourTarget(
                  id: 'nutrition',
                  child: Text(copy.setup,
                      style: Theme.of(context).textTheme.headlineMedium),
                ),
                const SizedBox(height: MayosSpacing.md),
                _sexConfirmation(copy),
                const SizedBox(height: 16),
                _activityQuestion(copy),
                const SizedBox(height: 16),
                _healthCheck(copy),
                const SizedBox(height: MayosSpacing.md),
                _setupButton(copy),
              ])
        ],
      );

  Widget _sexConfirmation(NutritionCopy copy) => NutritionCard(
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
            Text(copy.confirmSex,
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: MayosSpacing.sm),
            SegmentedButton<String>(
                expandedInsets: EdgeInsets.zero,
                segments: <ButtonSegment<String>>[
                  ButtonSegment(value: 'male', label: Text(copy.male)),
                  ButtonSegment(value: 'female', label: Text(copy.female)),
                ],
                selected: <String>{_sex},
                onSelectionChanged: _saving
                    ? null
                    : (Set<String> selected) =>
                        setState(() => _sex = selected.single)),
          ]));

  Widget _activityQuestion(NutritionCopy copy) => NutritionCard(
      child: RadioGroup<String>(
          groupValue: _activity,
          onChanged: (String? selected) {
            if (selected != null) setState(() => _activity = selected);
          },
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Text(copy.activityQuestion,
                    style: Theme.of(context).textTheme.titleMedium),
                for (final String activity in <String>[
                  'mostly_sitting',
                  'on_feet',
                  'physical_job'
                ])
                  Padding(
                      padding: const EdgeInsets.only(top: MayosSpacing.xs),
                      child: Card(
                          margin: EdgeInsets.zero,
                          shape: const RoundedRectangleBorder(
                              borderRadius: MayosRadii.mediumRadius),
                          child: RadioListTile<String>(
                              value: activity,
                              enabled: !_saving,
                              title: Text(copy.activityLabel(activity)),
                              subtitle: Text(copy.activityExample(activity))))),
              ])));

  Widget _healthCheck(NutritionCopy copy) => NutritionCard(
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
            Text(copy.healthCheck,
                style: Theme.of(context).textTheme.titleMedium),
            CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _pregnancy,
                onChanged: _saving
                    ? null
                    : (bool? selected) =>
                        setState(() => _pregnancy = selected ?? false),
                title: Text(copy.pregnancy)),
            CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _condition,
                onChanged: _saving
                    ? null
                    : (bool? selected) =>
                        setState(() => _condition = selected ?? false),
                title: Text(copy.condition)),
            CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _eatingDisorder,
                onChanged: _saving
                    ? null
                    : (bool? selected) =>
                        setState(() => _eatingDisorder = selected ?? false),
                title: Text(copy.eatingDisorder)),
            Text(copy.screeningNote,
                style: Theme.of(context).textTheme.bodySmall),
          ]));

  Widget _setupButton(NutritionCopy copy) => TourTarget(
      id: 'meal_setup',
      child: TourTarget(
          id: 'food_log',
          child: FilledButton(
              key: const Key('food_log_entry_point'),
              onPressed: _saving ? null : _save,
              child: Text(_saving ? copy.saving : copy.showTargets))));

  Widget _blocked(BuildContext context, NutritionCopy copy) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
              _plan?.state == 'under_18' ? copy.under18 : copy.dietitian,
              textAlign: TextAlign.center),
        ),
      );

  Widget _targets(BuildContext context, NutritionCopy copy) {
    if (widget.targetsOnly) return _targetDetails(copy);
    return FoodLogDayView(
        targets: _plan!.targets,
        onTodayWaterLoaded: (int count) {
          if (!_waterSaving) setState(() => _waterGlasses = count);
        },
        checkInBuilder: (FoodLogDay day) => NutritionCheckInCard(
            day: day,
            plan: _plan!,
            copy: copy,
            todayWaterGlasses: _waterGlasses,
            saving: _saving,
            waterSaving: _waterSaving,
            onWaterChanged: (bool undo) => _changeWater(undo, copy),
            onVerdict: (String verdict) => _logAdherence(verdict,
                entryDate: day.date == day.today
                    ? null
                    : day.date.toIso8601String().substring(0, 10)),
            onAnswerYesterday: (String date) => _answerPastDay(date, copy)),
        onShowTargets: () => _showTargets(copy));
  }

  Future<void> _showTargets(NutritionCopy copy) async {
    await Navigator.of(context).push<void>(MaterialPageRoute<void>(
        builder: (_) => Directionality(
            textDirection:
                copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
            child: Scaffold(
                appBar: AppBar(title: Text(copy.coachTargets)),
                body: const NutritionTab(targetsOnly: true)))));
    if (mounted) await _load();
  }

  Widget _targetDetails(NutritionCopy copy) => NutritionTargetsView(
      plan: _plan!,
      copy: copy,
      onAdjust: _saving ? null : _adjustGoal,
      onActivity: _saving || _plan!.authority == 'coach'
          ? null
          : () => _editActivity(copy),
      offers: Column(children: <Widget>[
        if (_plan!.pendingGoal != null && _plan!.authority != 'coach')
          NutritionCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                Text(copy.updateOffer),
                Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 8,
                    children: <Widget>[
                      TextButton(
                          onPressed: _saving ? null : _dismissGoalOffer,
                          child: Text(copy.dismiss)),
                      FilledButton(
                          onPressed: _saving
                              ? null
                              : () =>
                                  _adjustGoal(initialGoal: _plan!.pendingGoal),
                          child: Text(copy.accept)),
                    ]),
              ])),
        if (_plan!.paceProposal != null)
          PaceProposalCard(
              proposal: _plan!.paceProposal!,
              canDecide: _plan!.authority != 'coach',
              busy: _saving,
              onDecision: _decidePaceProposal),
      ]));

  Future<void> _adjustGoal({String? initialGoal}) async {
    final NutritionPlanState? saved = await Navigator.of(context)
        .push<NutritionPlanState>(MaterialPageRoute<NutritionPlanState>(
            builder: (_) =>
                NutritionPaceDial(plan: _plan!, initialGoal: initialGoal)));
    if (saved != null && mounted) setState(() => _plan = saved);
  }

  Future<void> _answerPastDay(String entryDate, NutritionCopy copy) async {
    final String? answer = await showDialog<String>(
        context: context,
        builder: (BuildContext dialogContext) =>
            SimpleDialog(title: Text(entryDate), children: <Widget>[
              for (final String verdict in <String>[
                'on_target',
                'roughly',
                'off'
              ])
                SimpleDialogOption(
                    onPressed: () => Navigator.pop(dialogContext, verdict),
                    child: Text(copy.adherenceLabel(verdict))),
            ]));
    if (answer != null && mounted)
      await _logAdherence(answer, entryDate: entryDate);
  }

  Future<void> _decidePaceProposal(String decision) async {
    final Object? rawId = _plan?.paceProposal?['id'];
    final int? proposalId =
        rawId is num ? rawId.toInt() : int.tryParse('$rawId');
    if (proposalId == null || _saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final NutritionPlanState plan = await ref
          .read(apiClientProvider)
          .decideNutritionPaceProposal(proposalId, decision);
      if (mounted)
        setState(() {
          _plan = plan;
          _saving = false;
        });
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  Future<void> _dismissGoalOffer() async {
    setState(() => _saving = true);
    try {
      final NutritionPlanState dismissed =
          await ref.read(apiClientProvider).dismissNutritionGoalOffer();
      if (mounted)
        setState(() {
          _plan = dismissed;
          _saving = false;
        });
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  Widget _loadError(BuildContext context, NutritionCopy copy) => Center(
      child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
            Text(_error ?? '', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            OutlinedButton(
                onPressed: () {
                  setState(() {
                    _loading = true;
                    _error = null;
                  });
                  _load();
                },
                child: Text(copy.retry)),
          ])));

  Widget _incomplete(BuildContext context, NutritionCopy copy) => Center(
      child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_plan?.message ?? copy.incomplete,
              textAlign: TextAlign.center)));
}
