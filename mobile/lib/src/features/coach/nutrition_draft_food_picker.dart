import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/nutrition_draft_copy.dart';
import '../../providers.dart';

class NutritionDraftFoodPicker extends ConsumerStatefulWidget {
  const NutritionDraftFoodPicker({required this.assignmentId, super.key});
  final String assignmentId;
  @override
  ConsumerState<NutritionDraftFoodPicker> createState() => _NutritionDraftFoodPickerState();
}

class _NutritionDraftFoodPickerState extends ConsumerState<NutritionDraftFoodPicker> {
  List<Map<String, dynamic>> _foods = <Map<String, dynamic>>[];
  bool _loading = true;
  String? _error;
  Timer? _timer;
  int _request = 0;
  String _query = '';

  @override
  void initState() { super.initState(); _search(''); }
  @override
  void dispose() { _timer?.cancel(); super.dispose(); }

  Future<void> _search(String query) async {
    final int request = ++_request;
    setState(() { _loading = true; _error = null; });
    try {
      final List<Map<String, dynamic>> foods = await ref.read(apiClientProvider).nutritionDraftFoods(widget.assignmentId, query);
      if (mounted && request == _request) setState(() => _foods = foods);
    } on ApiException catch (error) {
      if (mounted && request == _request) setState(() => _error = error.message);
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final NutritionDraftCopy copy = NutritionDraftCopy(ref.watch(displayLanguageProvider));
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(appBar: AppBar(title: Text(copy.addFood)), body: Column(children: <Widget>[
        Padding(padding: const EdgeInsets.all(16), child: TextField(autofocus: true,
          decoration: InputDecoration(labelText: copy.text('Search reviewed Staple foods', 'البحث في الأطعمة الأساسية المعتمدة')),
          onChanged: (String query) {
            _query = query;
            _request++;
            _timer?.cancel();
            _timer = Timer(const Duration(milliseconds: 300), () => _search(query));
          })),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null) TextButton(onPressed: () => _search(_query),
          child: Text(copy.text('Could not load foods. Retry', 'تعذر تحميل الأطعمة. أعد المحاولة'))),
        if (!_loading && _foods.isEmpty && _error == null)
          Text(copy.text('No reviewed Staple foods found.', 'لم يتم العثور على أطعمة أساسية معتمدة.')),
        Expanded(child: ListView(children: <Widget>[
          for (final Map<String, dynamic> food in _foods)
            ListTile(title: Text((copy.arabic ? food['arabic_name'] ?? food['name'] : food['name']) as String),
              subtitle: (food['restriction_reasons'] as List).isEmpty ? null
                : Text(copy.text('⚠ Food restriction: ${food['restriction_reasons'].join(', ')}',
                    '⚠ يتعارض مع القيود الغذائية أو يحتاج إلى مراجعة الحساسية'),
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
              onTap: () => Navigator.pop(context, food)),
        ])),
      ])));
  }
}
