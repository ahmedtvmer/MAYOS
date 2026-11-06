import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';
import 'food_nutrient_fields.dart';

class PersonalFoodScreen extends ConsumerStatefulWidget {
  const PersonalFoodScreen({this.initialName = '', super.key});
  final String initialName;

  @override
  ConsumerState<PersonalFoodScreen> createState() => _PersonalFoodScreenState();
}

class _PersonalFoodScreenState extends ConsumerState<PersonalFoodScreen> {
  late final TextEditingController _name;
  final TextEditingController _portionName = TextEditingController();
  final TextEditingController _portionGrams = TextEditingController();
  final Map<String, TextEditingController> _fields = <String, TextEditingController>{
    for (final String key in foodNutrientKeys) key: TextEditingController(),
  };
  String _basis = '100g';
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initialName);
  }

  @override
  void dispose() {
    for (final TextEditingController field in <TextEditingController>[
      _name, _portionName, _portionGrams, ..._fields.values,
    ]) { field.dispose(); }
    super.dispose();
  }

  bool get _valid {
    if (_name.text.trim().isEmpty || _name.text.trim().length > 200) return false;
    if (_basis == 'portion') {
      final double? grams = foodNumber(_portionGrams.text);
      if (_portionName.text.trim().isEmpty || _portionName.text.trim().length > 100 ||
          grams == null || !grams.isFinite || grams <= 0 || grams > 10000) return false;
      if (_fields.entries.any((MapEntry<String, TextEditingController> field) {
        final double density = (foodNumber(field.value.text) ?? double.nan) / grams * 100;
        return !density.isFinite || density > (field.key == 'energy_kcal' ? 100000 : 10000);
      })) return false;
    }
    return _fields.entries.every((MapEntry<String, TextEditingController> field) {
      final double? value = foodNumber(field.value.text);
      return value != null && value.isFinite && value >= 0 &&
          value <= (field.key == 'energy_kcal' ? 100000 : 10000);
    });
  }

  Future<void> _save() async {
    if (_saving || !_valid) return;
    setState(() { _saving = true; _error = null; });
    try {
      final FoodLibraryItem food = await ref.read(apiClientProvider).createPersonalFood(<String, dynamic>{
        'name': _name.text.trim(), 'basis': _basis,
        if (_basis == 'portion') 'portion_label': _portionName.text.trim(),
        if (_basis == 'portion') 'portion_grams': foodNumber(_portionGrams.text),
        for (final String key in foodNutrientKeys) key: foodNumber(_fields[key]!.text),
      });
      if (mounted) {
        setState(() => _saving = false);
        Navigator.of(context).pop(food);
      }
    } on ApiException catch (error) {
      if (mounted) setState(() { _saving = false; _error = error.message; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    return Directionality(
      textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: PopScope(canPop: !_saving, child: Scaffold(
        appBar: AppBar(title: Text(copy.createPersonal)),
        body: ListView(padding: const EdgeInsets.all(20), children: <Widget>[
          TextField(key: const Key('personal_food_name'), controller: _name, enabled: !_saving,
            decoration: InputDecoration(labelText: copy.foodName),
            onChanged: (_) => setState(() {})),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue: _basis,
            decoration: InputDecoration(labelText: copy.nutrientBasis),
            items: <DropdownMenuItem<String>>[
              DropdownMenuItem(value: '100g', child: Text(copy.hundredGrams)),
              DropdownMenuItem(value: 'portion', child: Text(copy.portion)),
            ],
            onChanged: _saving ? null : (String? value) {
              if (value != null) setState(() => _basis = value);
            },
          ),
          if (_basis == 'portion') ...<Widget>[
            TextField(key: const Key('personal_portion_name'), controller: _portionName,
              enabled: !_saving, decoration: InputDecoration(labelText: copy.portionName),
              onChanged: (_) => setState(() {})),
            TextField(key: const Key('personal_portion_grams'), controller: _portionGrams,
              enabled: !_saving, keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: copy.portionWeight),
              onChanged: (_) => setState(() {})),
          ],
          FoodNutrientFields(controllers: _fields, copy: copy,
            onChanged: () => setState(() {}), enabled: !_saving),
          if (!_valid) Text(copy.invalidNutrients),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 20),
          FilledButton(onPressed: _saving || !_valid ? null : _save,
            child: Text(_saving ? copy.saving : copy.save)),
        ]),
      )),
    );
  }
}
