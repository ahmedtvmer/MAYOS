import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/nutrition_draft_copy.dart';
import '../../providers.dart';
import 'nutrition_draft_food_picker.dart';
import 'coach_nutrition_templates_screen.dart';
import 'nutrition_template_save_dialog.dart';

const List<String> _nutrients = <String>['calories', 'protein_g', 'carbs_g', 'fat_g'];
const Map<String, String> _foodNutrients = <String, String>{
  'calories': 'energy_kcal', 'protein_g': 'protein_g', 'carbs_g': 'carbohydrate_g', 'fat_g': 'fat_g',
};

class CoachNutritionDraftScreen extends ConsumerStatefulWidget {
  const CoachNutritionDraftScreen({required this.assignmentId, super.key}) : templateId = null;
  const CoachNutritionDraftScreen.template({required String templateId, super.key})
      : templateId = templateId, assignmentId = '';
  final String assignmentId;
  final String? templateId;
  @override
  ConsumerState<CoachNutritionDraftScreen> createState() => _CoachNutritionDraftScreenState();
}

class _CoachNutritionDraftScreenState extends ConsumerState<CoachNutritionDraftScreen> {
  Map<String, dynamic>? _draft;
  Map<String, dynamic> _evaluation = <String, dynamic>{};
  final Map<String, Map<String, dynamic>> _foods = <String, Map<String, dynamic>>{};
  int _revision = 0;
  int _mealSequence = 0;
  int _editorGeneration = 0;
  bool _loading = true;
  bool _dirty = false;
  bool _publishing = false;
  bool _targetsChanged = false;
  bool _conflict = false;
  bool _allowPop = false;
  String? _error;
  Timer? _timer;
  Future<bool>? _saving;
  String _templateName = '';
  String? _templateDescription;
  bool _includeTemplateTargets = false;

  NutritionDraftCopy get copy => NutritionDraftCopy(ref.read(displayLanguageProvider));
  ApiClient get api => ref.read(apiClientProvider);

  @override
  void initState() { super.initState(); _load(); }

  @override
  void dispose() { _timer?.cancel(); super.dispose(); }

  void _accept(Map<String, dynamic> record) {
    _revision = record['revision'] as int;
    _targetsChanged = record['targets_changed'] == true;
    _acceptEvaluation(Map<String, dynamic>.from(record['evaluation'] as Map));
  }

  void _acceptEvaluation(Map<String, dynamic> evaluation) {
    _evaluation = evaluation;
    final Map variants = _evaluation['variants'] as Map? ?? <String, dynamic>{};
    for (final dynamic variant in variants.values) {
      for (final dynamic meal in variant['meals'] as List) {
        for (final dynamic food in meal['foods'] as List) {
          _foods[food['id'] as String] = Map<String, dynamic>.from(food as Map);
        }
      }
    }
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; _draft = null; _foods.clear(); _editorGeneration++; });
    try {
      if (widget.templateId != null) {
        final Map<String, dynamic> template = await api.nutritionTemplate(widget.templateId!);
        if (mounted) setState(() => _acceptTemplate(template));
        return;
      }
      final Map<String, dynamic> record = await api.coachNutritionDraft(widget.assignmentId);
      if (!mounted) return;
      setState(() { _draft = Map<String, dynamic>.from(record['draft'] as Map); _accept(record); });
    } on ApiException catch (error) {
      if (mounted && (error.statusCode != 404 || widget.templateId != null)) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _acceptTemplate(Map<String, dynamic> template) {
    _templateName = template['name'] as String;
    _templateDescription = template['description'] as String?;
    _draft = Map<String, dynamic>.from(template['nutrition'] as Map);
    for (final dynamic food in template['foods'] as List? ?? <dynamic>[]) {
      _foods[food['id'] as String] = Map<String, dynamic>.from(food as Map);
    }
    _includeTemplateTargets = (_draft!['targets'] as Map).isNotEmpty;
    if (!_includeTemplateTargets) {
      final Map variants = _draft!['variants'] as Map;
      _draft!['targets'] = <String, dynamic>{for (final String day in variants.keys.cast<String>()) day:
        <String, dynamic>{for (final String key in _nutrients) key:
          (variants[day] as List).fold<double>(0, (double sum, dynamic meal) => sum + _mealTotals(meal as Map)[key]!)}};
    }
    _evaluation = <String, dynamic>{'errors': <String>[], 'variants': <String, dynamic>{}};
  }

  Map<String, dynamic> _templateBody(Map<String, dynamic> snapshot) => <String, dynamic>{
    'name': _templateName, 'description': _templateDescription,
    'nutrition': <String, dynamic>{...snapshot, if (!_includeTemplateTargets) 'targets': <String, dynamic>{}},
  };

  Future<void> _start(String source) async {
    setState(() { _loading = true; _error = null; });
    try {
      final Map<String, dynamic> record = await api.startNutritionDraft(widget.assignmentId, source);
      if (!mounted) return;
      setState(() { _draft = Map<String, dynamic>.from(record['draft'] as Map); _accept(record); });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _changed(VoidCallback change) {
    setState(() { change(); _dirty = true; if (!_conflict) _error = null; });
    _timer?.cancel();
    _timer = Timer(const Duration(milliseconds: 600), _save);
  }

  Future<bool> _save() async {
    _timer?.cancel();
    if (_saving != null) return _saving!;
    if (!_dirty || _draft == null) return true;
    if (_conflict) return false;
    final Future<bool> pending = _saveChanges();
    _saving = pending;
    final bool saved = await pending;
    _saving = null;
    if (mounted) setState(() {});
    return saved;
  }

  Future<bool> _saveChanges() async {
    while (_dirty && mounted) {
      _dirty = false;
      final Map<String, dynamic> snapshot = jsonDecode(jsonEncode(_draft)) as Map<String, dynamic>;
      setState(() {});
      try {
        final Map<String, dynamic> record = widget.templateId == null
          ? await api.saveNutritionDraft(widget.assignmentId, snapshot, _revision)
          : await api.updateNutritionTemplate(widget.templateId!, _templateBody(snapshot));
        if (!mounted) return false;
        setState(() { if (widget.templateId == null) _accept(record); _error = null; });
      } on ApiException catch (error) {
        if (mounted) setState(() { _dirty = true; _error = error.message; _conflict = error.statusCode == 409; });
        return false;
      }
    }
    return true;
  }

  Future<void> _saveAsTemplate() async {
    if (!await _save() || !mounted) return;
    final Map<String, dynamic>? metadata = await nutritionTemplateSaveDialog(context, copy);
    if (metadata == null || !mounted || !await _save() || !mounted) return;
    setState(() => _publishing = true);
    try {
      await api.saveNutritionTemplate(widget.assignmentId, <String, dynamic>{
        ...metadata, 'source': 'draft', 'revision': _revision,
      });
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:
        Text(copy.text('Nutrition template saved', 'تم حفظ قالب خطة التغذية'))));
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _conflict = error.statusCode == 409; });
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _applyTemplate() async {
    if (!await _save() || !mounted) return;
    final String? templateId = await Navigator.push<String>(context, MaterialPageRoute<String>(
      builder: (_) => const CoachNutritionTemplatesScreen(selectForDraft: true)));
    if (templateId == null || !mounted) return;
    if (_draft != null) {
      final bool replace = await showDialog<bool>(context: context, builder: (BuildContext context) => AlertDialog(
        title: Text(copy.text('Replace this draft?', 'استبدال هذه المسودة؟')),
        content: Text(copy.text('The template fills this draft. Review it before publishing.', 'يملأ القالب هذه المسودة. راجعها قبل النشر.')),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(copy.text('Cancel', 'إلغاء'))),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(copy.text('Replace draft', 'استبدال المسودة'))),
        ])) ?? false;
      if (!replace || !mounted) return;
    }
    setState(() => _publishing = true);
    try {
      final Map<String, dynamic> record = await api.applyNutritionTemplate(templateId, widget.assignmentId,
        revision: _draft == null ? null : _revision);
      if (!mounted) return;
      setState(() {
        _draft = Map<String, dynamic>.from(record['draft'] as Map);
        _foods.clear(); _accept(record); _dirty = false; _error = null; _editorGeneration++;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _conflict = error.statusCode == 409; });
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _leave() async {
    if (_publishing || !await _save() || !mounted) return;
    setState(() => _allowPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.pop(context);
    });
  }

  Future<void> _publish() async {
    if (!await _save() || !mounted || _evaluation['can_publish'] != true) return;
    final bool confirmed = await showDialog<bool>(context: context, builder: (BuildContext context) => AlertDialog(
      title: Text(copy.publish),
      content: Text(copy.text('This replaces the Player’s Nutrition plan and gives you Nutrition authority.',
        'ستحل هذه الخطة محل خطة تغذية اللاعب وستنتقل إليك صلاحية التغذية.')),
      actions: <Widget>[
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text(copy.text('Cancel', 'إلغاء'))),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(copy.publish)),
      ],
    )) ?? false;
    if (!confirmed || !mounted) return;
    setState(() => _publishing = true);
    try {
      await api.publishNutritionDraft(widget.assignmentId, _revision);
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (error) {
      if (mounted) setState(() {
        _error = error.message;
        _conflict = error.statusCode == 409;
        final Object? evaluation = error.serverDetails?['evaluation'];
        if (evaluation is Map) _acceptEvaluation(Map<String, dynamic>.from(evaluation));
      });
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _discard() async {
    final bool confirmed = await showDialog<bool>(context: context, builder: (BuildContext context) => AlertDialog(
      title: Text(copy.text('Discard this draft?', 'حذف هذه المسودة؟')),
      actions: <Widget>[
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text(copy.text('Keep editing', 'متابعة التعديل'))),
        TextButton(onPressed: () => Navigator.pop(context, true), child: Text(copy.text('Discard', 'حذف'))),
      ],
    )) ?? false;
    if (!confirmed || !mounted) return;
    _timer?.cancel();
    if (_saving != null) await _saving;
    try {
      await api.discardNutritionDraft(widget.assignmentId);
      _dirty = false;
      if (mounted) Navigator.pop(context);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: PopScope<Object?>(canPop: _allowPop || (!_dirty && _saving == null && !_publishing),
        onPopInvokedWithResult: (bool didPop, Object? result) { if (!didPop) _leave(); },
        child: Scaffold(
        appBar: AppBar(title: Text(widget.templateId == null ? copy.title : copy.text('Edit Nutrition template', 'تعديل قالب خطة تغذية')),
          leading: BackButton(onPressed: _leave)),
        body: _loading ? const Center(child: CircularProgressIndicator()) : Center(
          child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 1000),
            child: AbsorbPointer(absorbing: _publishing, child: ListView(key: ValueKey<int>(_editorGeneration), padding: const EdgeInsets.all(16),
              children: <Widget>[
                if (_error != null) ...<Widget>[
                  Text(copy.arabic ? copy.text('', 'تعذر الحفظ. راجع المسودة وأعد المحاولة.') : _error!,
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  if (_conflict) TextButton(onPressed: () { _dirty = false; _conflict = false; _load(); },
                    child: Text(copy.text('Reopen saved draft', 'فتح المسودة المحفوظة')))
                  else if (_draft != null) TextButton(onPressed: _save, child: Text(copy.retry))
                  else TextButton(onPressed: _load, child: Text(copy.text('Retry', 'إعادة المحاولة'))),
                ],
                if (widget.templateId == null) Wrap(spacing: 12, children: <Widget>[
                  OutlinedButton(key: const Key('apply_nutrition_template'), onPressed: _applyTemplate,
                    child: Text(copy.text('Apply Nutrition template', 'تطبيق قالب خطة تغذية'))),
                  if (_draft != null) TextButton(key: const Key('save_nutrition_template'), onPressed: _saveAsTemplate,
                    child: Text(copy.text('Save as Nutrition template', 'حفظ كقالب خطة تغذية'))),
                ]),
                if (_draft == null && widget.templateId == null) _starts() else if (_draft != null) ..._editor(),
              ])))),
      )));
  }

  Widget _starts() => Wrap(spacing: 12, runSpacing: 12, children: <Widget>[
    for (final String source in <String>['blank', 'current', 'generated'])
      OutlinedButton(key: Key('nutrition_start_$source'), onPressed: () => _start(source),
        child: Text(switch (source) {
          'blank' => copy.text('Start blank', 'البدء بمسودة فارغة'),
          'current' => copy.text('Copy current plan', 'نسخ الخطة الحالية'),
          _ => copy.text('Start from generated meals', 'البدء بالوجبات المُنشأة'),
        })),
  ]);

  List<Widget> _editor() {
    final Map<String, dynamic> targets = _draft!['targets'] as Map<String, dynamic>;
    final Map<String, dynamic> variants = _draft!['variants'] as Map<String, dynamic>;
    return <Widget>[
      Text(_saving != null || _dirty ? copy.saving : copy.saved),
      if (widget.templateId != null) ...<Widget>[
        TextFormField(initialValue: _templateName, maxLength: 120,
          decoration: InputDecoration(labelText: copy.text('Template name', 'اسم القالب')),
          onChanged: (String name) => _changed(() => _templateName = name)),
        TextFormField(initialValue: _templateDescription, maxLength: 2000, maxLines: 3,
          decoration: InputDecoration(labelText: copy.text('Description (optional)', 'الوصف (اختياري)')),
          onChanged: (String description) => _changed(() => _templateDescription = description)),
        SwitchListTile(contentPadding: EdgeInsets.zero, value: _includeTemplateTargets,
          title: Text(copy.text('Include targets', 'تضمين الأهداف')),
          onChanged: (bool enabled) => _changed(() => _includeTemplateTargets = enabled)),
        Text(copy.text('Editing this template never changes a Player’s plan or draft.', 'تعديل القالب لا يغيّر خطط اللاعبين أو مسوداتهم.')),
      ],
      if (_targetsChanged) Text(copy.text('The Player’s targets changed since this draft started. Review targets and meals.',
        'تغيّرت أهداف اللاعب منذ بدء المسودة. راجع الأهداف والوجبات.')),
      DropdownButtonFormField<String>(value: _draft!['goal'] as String,
        decoration: InputDecoration(labelText: copy.text('Nutrition goal', 'الهدف الغذائي')),
        items: <DropdownMenuItem<String>>[
          DropdownMenuItem(value: 'lose', child: Text(copy.text('Lose', 'خسارة الوزن'))),
          DropdownMenuItem(value: 'maintain', child: Text(copy.text('Maintain', 'الحفاظ على الوزن'))),
          DropdownMenuItem(value: 'gain', child: Text(copy.text('Gain', 'زيادة الوزن'))),
        ], onChanged: (String? goal) { if (goal != null) _changed(() => _draft!['goal'] = goal); }),
      SwitchListTile(contentPadding: EdgeInsets.zero, title: Text(copy.text('Training / rest variants', 'أيام التدريب والراحة')),
        value: targets.containsKey('training_day'), onChanged: _variantsChanged),
      SwitchListTile(contentPadding: EdgeInsets.zero, title: Text(copy.text('Include meals', 'إضافة الوجبات')),
        value: variants.isNotEmpty, onChanged: (bool enabled) => _changed(() {
          _draft!['variants'] = enabled ? <String, dynamic>{for (final String day in targets.keys) day: <dynamic>[]} : <String, dynamic>{};
        })),
      for (final String day in targets.keys) ...<Widget>[
        const SizedBox(height: 16), Text(copy.day(day), style: Theme.of(context).textTheme.titleLarge),
        if (widget.templateId == null || _includeTemplateTargets) Wrap(spacing: 12, runSpacing: 12, children: <Widget>[
          for (final String key in _nutrients) SizedBox(width: 190, child: TextFormField(
            key: ValueKey<String>('target_${day}_$key'), initialValue: '${targets[day][key] ?? ''}',
            decoration: InputDecoration(labelText: copy.nutrient(key)), keyboardType: TextInputType.number,
            onChanged: (String amount) => _changed(() => targets[day][key] = int.tryParse(amount) ?? -1))),
        ]),
        if (variants.containsKey(day)) ...<Widget>[
          if (widget.templateId == null || _includeTemplateTargets) _totals(day, variants[day] as List, targets[day] as Map),
          for (final Map<String, dynamic> meal in (variants[day] as List).cast<Map<String, dynamic>>())
            _meal(day, meal, variants[day] as List, targets[day] as Map),
          TextButton.icon(key: Key('add_meal_$day'), onPressed: (variants[day] as List).length >= 12 ? null : () => _changed(() {
            (variants[day] as List).add(<String, dynamic>{'slot': 'coach_${DateTime.now().microsecondsSinceEpoch}_${_mealSequence++}',
              'name': copy.text('Meal', 'وجبة'), 'note': '', 'log_label': 'lunch', 'foods': <dynamic>[]});
          }), icon: const Icon(Icons.add), label: Text(copy.addMeal)),
        ],
      ],
      for (final dynamic issue in _evaluation['errors'] as List? ?? <dynamic>[])
        Text(copy.issue('$issue'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
      Wrap(spacing: 12, children: <Widget>[
        if (widget.templateId != null) TextButton(onPressed: _save,
          child: Text(copy.text('Save template', 'حفظ القالب')))
        else ...<Widget>[
        FilledButton(key: const Key('publish_nutrition_draft'), onPressed: _dirty || _saving != null || _evaluation['can_publish'] != true || _conflict
          ? null : _publish, child: Text(copy.publish)),
        TextButton(onPressed: _discard, child: Text(copy.text('Discard draft', 'حذف المسودة'))),
        ],
      ]),
    ];
  }

  void _variantsChanged(bool separate) => _changed(() {
    final Map targets = _draft!['targets'] as Map;
    final Map variants = _draft!['variants'] as Map;
    final String source = separate ? 'daily' : 'training_day';
    final List<String> days = separate ? <String>['training_day', 'rest_day'] : <String>['daily'];
    _draft!['targets'] = <String, dynamic>{for (final String day in days) day: jsonDecode(jsonEncode(targets[source]))};
    _draft!['variants'] = variants.isEmpty ? <String, dynamic>{} : <String, dynamic>{
      for (final String day in days) day: jsonDecode(jsonEncode(variants[source]))};
  });

  Map<String, double> _mealTotals(Map meal) => <String, double>{
    for (final String key in _nutrients) key: (meal['foods'] as List).fold<double>(0, (double sum, dynamic portion) {
      final Map? nutrients = _foods[portion['id']]?['nutrients_per_100g'] as Map?;
      return sum + ((nutrients?[_foodNutrients[key]] as num?)?.toDouble() ?? 0) * (portion['grams'] as num).toDouble() / 100;
    }),
  };

  Widget _totals(String day, List meals, Map targets) {
    final Map<String, double> totals = <String, double>{for (final String key in _nutrients) key: 0};
    for (final dynamic meal in meals) {
      final Map<String, double> mealTotals = _mealTotals(meal as Map);
      for (final String key in _nutrients) { totals[key] = totals[key]! + mealTotals[key]!; }
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      Text(copy.text('Actual / target', 'الإجمالي / الهدف')),
      for (final String key in _nutrients) Builder(builder: (BuildContext context) {
        final num target = targets[key] as num? ?? 0;
        final bool warning = (totals[key]! - target).abs() > target.abs() * .05 + .000001;
        return Text('${copy.nutrient(key)}: ${totals[key]!.round()} / $target${warning ? ' ⚠' : ''}',
          style: TextStyle(color: warning ? Theme.of(context).colorScheme.error : null));
      }),
      Text(copy.text('Warn above 5%; publishing requires every daily total within 15% and above the Calorie floor.',
        'تحذير بعد ٥٪؛ النشر يتطلب إجماليات يومية ضمن ١٥٪ وأعلى من الحد الأدنى للسعرات.')),
      if (_evaluation['calorie_floor'] != null)
        Text('${copy.text('Calorie floor', 'الحد الأدنى للسعرات')}: ${_evaluation['calorie_floor']}'),
    ]);
  }

  Widget _meal(String day, Map<String, dynamic> meal, List meals, Map targets) {
    final Map<String, double> totals = _mealTotals(meal);
    final bool compareTargets = widget.templateId == null || _includeTemplateTargets;
    return Card(key: ValueKey<String>('${day}_${meal['slot']}'), child: Padding(padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
        TextFormField(initialValue: meal['name'] as String? ?? '',
          decoration: InputDecoration(labelText: copy.text('Meal name', 'اسم الوجبة')),
          onChanged: (String name) => _changed(() => meal['name'] = name)),
        TextFormField(initialValue: meal['note'] as String? ?? '', maxLines: 2,
          decoration: InputDecoration(labelText: copy.text('Meal note', 'ملاحظة الوجبة')),
          onChanged: (String note) => _changed(() => meal['note'] = note)),
        Wrap(spacing: 10, children: <Widget>[
          for (final String key in _nutrients)
            Builder(builder: (BuildContext context) {
              final double share = (targets[key] as num? ?? 0) / meals.length;
              final bool warning = compareTargets && (totals[key]! - share).abs() > share.abs() * .05 + .000001;
              return Text('${copy.nutrient(key)}: ${totals[key]!.round()}${compareTargets ? ' / ${share.round()}' : ''}${warning ? ' ⚠' : ''}',
                style: TextStyle(color: warning ? Theme.of(context).colorScheme.error : null));
            }),
        ]),
        if (compareTargets) Text(copy.text('Meal totals / equal share of daily targets', 'إجمالي الوجبة / حصة متساوية من الأهداف اليومية')),
        for (final Map<String, dynamic> portion in (meal['foods'] as List).cast<Map<String, dynamic>>())
          _portion(meal, portion),
        Wrap(spacing: 8, children: <Widget>[
          TextButton(onPressed: (meal['foods'] as List).length >= 40 ? null : () => _pickFood(meal), child: Text(copy.addFood)),
          TextButton(onPressed: () => _changed(() => meals.remove(meal)), child: Text(copy.text('Remove meal', 'حذف الوجبة'))),
        ]),
      ])));
  }

  Widget _portion(Map meal, Map<String, dynamic> portion) {
    final Map<String, dynamic>? food = _foods[portion['id']];
    final String name = (copy.arabic ? food?['arabic_name'] ?? food?['name'] : food?['name']) as String? ?? '${portion['id']}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      Text(name),
      if ((food?['restriction_reasons'] as List? ?? <dynamic>[]).isNotEmpty)
        Text(copy.text('⚠ Food restriction', '⚠ قيد غذائي'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
      Row(children: <Widget>[
        Expanded(child: TextFormField(key: ValueKey<String>('${meal['slot']}_${portion['id']}'),
          initialValue: '${portion['grams']}', keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: copy.text('Grams', 'جرامات')),
          onChanged: (String grams) => _changed(() => portion['grams'] = double.tryParse(grams) ?? 0))),
        IconButton(tooltip: copy.text('Remove food', 'حذف الطعام'), icon: const Icon(Icons.delete_outline),
          onPressed: () => _changed(() => (meal['foods'] as List).remove(portion))),
      ]),
    ]);
  }

  Future<void> _pickFood(Map meal) async {
    if ((meal['foods'] as List).length >= 40) return;
    final Map<String, dynamic>? food = await Navigator.push<Map<String, dynamic>>(context,
      MaterialPageRoute<Map<String, dynamic>>(builder: (_) => NutritionDraftFoodPicker(assignmentId: widget.assignmentId)));
    if (food == null || !mounted) return;
    _changed(() {
      _foods[food['id'] as String] = food;
      final List portions = meal['foods'] as List;
      if (!portions.any((dynamic portion) => portion['id'] == food['id'])) {
        portions.add(<String, dynamic>{'id': food['id'], 'grams': 100});
      }
    });
  }
}
