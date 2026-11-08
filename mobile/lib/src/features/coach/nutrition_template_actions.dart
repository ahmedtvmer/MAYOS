import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/nutrition_draft_copy.dart';
import '../../providers.dart';
import 'coach_nutrition_templates_screen.dart';
import 'nutrition_template_save_dialog.dart';

class NutritionTemplateActions extends ConsumerStatefulWidget {
  const NutritionTemplateActions({required this.assignmentId, super.key});
  final String assignmentId;
  @override
  ConsumerState<NutritionTemplateActions> createState() => _NutritionTemplateActionsState();
}

class _NutritionTemplateActionsState extends ConsumerState<NutritionTemplateActions> {
  bool _busy = false;
  String? _error;
  NutritionDraftCopy get copy => NutritionDraftCopy(ref.read(displayLanguageProvider));

  Future<void> _saveCurrent() async {
    setState(() { _busy = true; _error = null; });
    final ApiClient api = ref.read(apiClientProvider);
    try {
      final Map<String, dynamic> source = await api.nutritionTemplateSource(widget.assignmentId);
      if (!mounted) return;
      final Map<String, dynamic>? metadata = await nutritionTemplateSaveDialog(context, copy);
      if (metadata == null || !mounted) return;
      await api.saveNutritionTemplate(widget.assignmentId, <String, dynamic>{
        ...metadata, 'source': 'current', 'plan_version_id': source['plan_version_id'],
      });
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:
        Text(copy.text('Nutrition template saved', 'تم حفظ قالب خطة التغذية'))));
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      Wrap(spacing: 12, children: <Widget>[
        TextButton(onPressed: _busy ? null : _saveCurrent,
          child: Text(copy.text('Save current plan as Nutrition template', 'حفظ الخطة الحالية كقالب خطة تغذية'))),
        TextButton(onPressed: () => Navigator.push<void>(context, MaterialPageRoute<void>(
          builder: (_) => const CoachNutritionTemplatesScreen())),
          child: Text(copy.text('Nutrition templates', 'قوالب خطط التغذية'))),
      ]),
      if (_busy) const LinearProgressIndicator(),
      if (_error != null) Text(copy.arabic ? 'تعذر حفظ القالب. راجع الخطة وأعد المحاولة.' : _error!),
    ]);
  }
}
