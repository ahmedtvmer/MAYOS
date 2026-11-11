import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/food_swap_request_copy.dart';
import '../../core/models.dart';
import '../../providers.dart';

class CoachFoodSwapRequestEditor extends ConsumerStatefulWidget {
  const CoachFoodSwapRequestEditor({super.key, required this.request, required this.onResolved});
  final ProgramRequest request;
  final ValueChanged<ProgramRequest> onResolved;
  @override
  ConsumerState<CoachFoodSwapRequestEditor> createState() => _CoachFoodSwapRequestEditorState();
}

class _CoachFoodSwapRequestEditorState extends ConsumerState<CoachFoodSwapRequestEditor> {
  final TextEditingController _query = TextEditingController();
  final TextEditingController _grams = TextEditingController();
  final TextEditingController _reply = TextEditingController();
  List<Map<String, dynamic>> _foods = <Map<String, dynamic>>[];
  String? _foodId;
  String? _error;
  bool _busy = false;
  bool _searching = false;
  int _sequence = 0;

  @override
  void initState() { super.initState(); _search(); }
  @override
  void dispose() { _query.dispose(); _grams.dispose(); _reply.dispose(); super.dispose(); }

  Future<void> _search() async {
    final int sequence = ++_sequence;
    setState(() { _searching = true; _error = null; });
    try {
      final List<Map<String, dynamic>> foods = await ref.read(apiClientProvider)
          .nutritionDraftFoods(widget.request.assignmentId, _query.text.trim());
      if (mounted && sequence == _sequence) setState(() => _foods = foods
          .where((Map<String, dynamic> food) => food['id'] != widget.request.foodSwap!['food_id']).toList());
    } on ApiException catch (error) {
      if (mounted && sequence == _sequence) setState(() => _error =
          displayCopyOf(context).failureMessage(apiFailureMessage(error)));
    } finally {
      if (mounted && sequence == _sequence) setState(() => _searching = false);
    }
  }

  Future<void> _decide(FoodSwapRequestDecision decision) async {
    final bool apply = decision == FoodSwapRequestDecision.apply;
    final double? grams = double.tryParse(_grams.text.trim());
    if ((!apply && _reply.text.trim().isEmpty) || (apply &&
        (_foodId == null || grams == null || !grams.isFinite || grams <= 0 || grams > 10000))) {
      setState(() => _error = FoodSwapRequestCopy(ref.read(displayLanguageProvider)).invalid);
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final ProgramRequest updated = apply
          ? await api.applyFoodSwapRequest(widget.request, reply: _reply.text.trim(), foodId: _foodId!, grams: grams!)
          : await api.declineFoodSwapRequest(widget.request, _reply.text.trim());
      if (mounted) widget.onResolved(updated);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = displayCopyOf(context).failureMessage(mutationFailureMessage(error)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodSwapRequestCopy copy = FoodSwapRequestCopy(ref.watch(displayLanguageProvider));
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: PopScope(canPop: !_busy, child: AlertDialog(
      title: Text(copy.target(widget.request.foodSwap!)),
      content: SizedBox(width: 460, child: SingleChildScrollView(child: Column(
        mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
          if (widget.request.playerUsername != null) Text(widget.request.playerUsername!),
          Text(widget.request.reason),
          TextField(controller: _query, enabled: !_busy, decoration: InputDecoration(labelText: copy.search),
            onSubmitted: (_) => _search()),
          TextButton(onPressed: _busy || _searching ? null : _search, child: Text(copy.search)),
          if (_searching) const LinearProgressIndicator(),
          for (final Map<String, dynamic> food in _foods)
            RadioListTile<String>(key: Key('replacement_${food['id']}'), value: food['id'] as String,
              groupValue: _foodId, onChanged: _busy ? null : (String? id) => setState(() => _foodId = id),
              title: Text('${copy.arabic ? food['arabic_name'] ?? food['name'] : food['name']}'),
              subtitle: (food['restriction_reasons'] as List<dynamic>? ?? <dynamic>[]).isEmpty ? null
                  : Text(copy.arabic ? 'تحذير: قيود غذائية' : 'Warning: Food restrictions')),
          TextField(key: const Key('food_swap_grams'), controller: _grams, enabled: !_busy,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: copy.grams)),
          TextField(key: const Key('food_swap_coach_reply'), controller: _reply, enabled: !_busy,
            maxLength: 500, maxLines: 3, decoration: InputDecoration(labelText: copy.reply, helperText: copy.replyHint)),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ]))),
      actions: <Widget>[
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: Text(copy.cancel)),
        TextButton(key: const Key('decline_food_swap'), onPressed: _busy ? null : () => _decide(FoodSwapRequestDecision.decline),
          child: Text(copy.decline)),
        FilledButton(key: const Key('apply_food_swap_request'), onPressed: _busy ? null : () => _decide(FoodSwapRequestDecision.apply),
          child: Text(copy.apply)),
      ],
    )));
  }
}
