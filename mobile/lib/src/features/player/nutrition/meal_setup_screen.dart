import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/meal_setup_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../core/meal_setup_models.dart';
import '../../../providers.dart';
import '../tour/tour_targets.dart';
import 'food_search_screen.dart';

class MealSetupEntry extends ConsumerWidget {
  const MealSetupEntry({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MealSetupCopy copy = MealSetupCopy(ref.watch(displayLanguageProvider));
    return TourTarget(id: 'meal_setup', child: ListTile(
      key: const Key('meal_setup_entry'), leading: const Icon(Icons.restaurant_menu),
      title: Text(copy.mealSetup), subtitle: Text(copy.restrictions),
      onTap: () => Navigator.of(context).push<bool>(
        MaterialPageRoute<bool>(builder: (_) => const MealSetupScreen())),
    ));
  }
}

class MealSetupScreen extends ConsumerStatefulWidget {
  const MealSetupScreen({super.key});

  @override
  ConsumerState<MealSetupScreen> createState() => _MealSetupScreenState();
}

class _MealSetupScreenState extends ConsumerState<MealSetupScreen> {
  bool _loading = true;
  bool _hasSetup = false;
  bool _saving = false;
  String? _error;
  int _count = 3;
  String _trainingTime = 'evening';
  final Set<String> _allergies = <String>{};
  bool _vegetarian = false;
  final Map<String, Map<String, dynamic>> _dislikes = <String, Map<String, dynamic>>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final MealSetupState setup = await ref.read(apiClientProvider).mealSetup();
      if (!mounted) return;
      setState(() {
        _count = setup.mealCount;
        _trainingTime = setup.trainingTime;
        _allergies..clear()..addAll(setup.allergies);
        _vegetarian = setup.vegetarian;
        _dislikes..clear()..addAll(setup.dislikes);
        _loading = false;
        _hasSetup = true;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _loading = false; });
    }
  }

  Future<void> _save() async {
    setState(() { _saving = true; _error = null; });
    try {
      await ref.read(apiClientProvider).saveMealSetup(MealSetupState(
        mealCount: _count, trainingTime: _trainingTime, allergies: _allergies,
        vegetarian: _vegetarian, dislikes: _dislikes));
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) setState(() { _error = error.message; _saving = false; });
    }
  }

  Future<void> _addDislike() async {
    final FoodLibraryItem? food = await Navigator.of(context).push<FoodLibraryItem>(
      MaterialPageRoute<FoodLibraryItem>(builder: (_) => const FoodSearchScreen(
        day: '', kcalLeft: null, mealLabel: 'breakfast', selectOnly: true)));
    if (!mounted || food == null) return;
    setState(() => _dislikes[food.id] = <String, dynamic>{
      'id': food.id, 'name': food.name, 'arabic_name': food.arabicName,
    });
  }

  @override
  Widget build(BuildContext context) {
    final MealSetupCopy copy = MealSetupCopy(ref.watch(displayLanguageProvider));
    return Directionality(textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(appBar: AppBar(title: Text(copy.mealSetup)),
        body: _loading ? const Center(child: CircularProgressIndicator()) :
          _error != null && !_hasSetup ? Center(child: Column(mainAxisSize: MainAxisSize.min,
            children: <Widget>[Text(_error!), TextButton(onPressed: _load, child: Text(copy.retry))])) :
          AbsorbPointer(absorbing: _saving, child: _form(copy))));
  }

  Widget _form(MealSetupCopy copy) => ListView(padding: const EdgeInsets.all(16), children: <Widget>[
    Text(copy.mealCount, style: Theme.of(context).textTheme.titleMedium),
    Wrap(spacing: 8, children: <Widget>[
      for (final int count in <int>[3, 4, 5]) ChoiceChip(key: Key('meal_count_$count'),
        label: Text('$count'), selected: count == _count, onSelected: (_) => setState(() => _count = count)),
    ]),
    Text(copy.slotLayout(_count)),
    const SizedBox(height: 16),
    DropdownButtonFormField<String>(key: const Key('meal_training_time'), initialValue: _trainingTime,
      decoration: InputDecoration(labelText: copy.trainingTime),
      items: <DropdownMenuItem<String>>[
        for (final String time in <String>['morning', 'afternoon', 'evening'])
          DropdownMenuItem<String>(value: time, child: Text(copy.timeLabel(time))),
      ], onChanged: (String? time) { if (time != null) setState(() => _trainingTime = time); }),
    const SizedBox(height: 24),
    Text(copy.restrictions, style: Theme.of(context).textTheme.titleLarge),
    Text(copy.allergies, style: Theme.of(context).textTheme.titleMedium),
    Text(copy.allergyNote),
    Wrap(spacing: 8, children: <Widget>[
      for (final String tag in MealSetupCopy.allergens) FilterChip(key: Key('allergy_$tag'),
        label: Text(copy.reason(tag)), selected: _allergies.contains(tag), onSelected: (bool selected) =>
          setState(() { if (selected) { _allergies.add(tag); } else { _allergies.remove(tag); } })),
    ]),
    SwitchListTile(key: const Key('meal_vegetarian'), contentPadding: EdgeInsets.zero,
      title: Text(copy.vegetarian), subtitle: Text(copy.vegetarianNote), value: _vegetarian,
      onChanged: (bool selected) => setState(() => _vegetarian = selected)),
    _dislikedFoods(copy),
    if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
    const SizedBox(height: 16),
    FilledButton(key: const Key('save_meal_setup'), onPressed: _saving ? null : _save,
      child: Text(_saving ? copy.saving : copy.save)),
  ]);

  Widget _dislikedFoods(MealSetupCopy copy) => Column(crossAxisAlignment: CrossAxisAlignment.start,
    children: <Widget>[
      Text(copy.dislikes, style: Theme.of(context).textTheme.titleMedium),
      for (final MapEntry<String, Map<String, dynamic>> food in _dislikes.entries) ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text((copy.isArabic ? food.value['arabic_name'] : null) as String? ?? food.value['name'] as String),
        trailing: IconButton(tooltip: copy.remove, icon: const Icon(Icons.close),
          onPressed: () => setState(() => _dislikes.remove(food.key)))),
      TextButton.icon(key: const Key('add_disliked_food'), onPressed: _addDislike,
        icon: const Icon(Icons.add), label: Text(copy.addDislike)),
    ]);
}
