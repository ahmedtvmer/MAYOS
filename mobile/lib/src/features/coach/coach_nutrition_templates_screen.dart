import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/nutrition_draft_copy.dart';
import '../../providers.dart';
import 'coach_nutrition_draft_screen.dart';

class CoachNutritionTemplatesScreen extends ConsumerStatefulWidget {
  const CoachNutritionTemplatesScreen({this.selectForDraft = false, super.key});
  final bool selectForDraft;
  @override
  ConsumerState<CoachNutritionTemplatesScreen> createState() => _CoachNutritionTemplatesScreenState();
}

class _CoachNutritionTemplatesScreenState extends ConsumerState<CoachNutritionTemplatesScreen> {
  List<Map<String, dynamic>> _templates = <Map<String, dynamic>>[];
  bool _loading = true;
  String? _error;
  NutritionDraftCopy get copy => NutritionDraftCopy(ref.read(displayLanguageProvider));
  ApiClient get api => ref.read(apiClientProvider);

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final List<Map<String, dynamic>> templates = await api.nutritionTemplates();
      if (mounted) setState(() => _templates = templates);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit(String templateId) async {
    await Navigator.push<void>(context, MaterialPageRoute<void>(builder: (_) =>
      CoachNutritionDraftScreen.template(templateId: templateId)));
    if (mounted) await _load();
  }

  Future<void> _delete(Map<String, dynamic> template) async {
    final bool confirmed = await showDialog<bool>(context: context, builder: (BuildContext context) => AlertDialog(
      title: Text(copy.text('Delete Nutrition template?', 'حذف قالب خطة التغذية؟')),
      content: Text(copy.text('Player plans and drafts keep their own copies.', 'تحتفظ خطط اللاعبين ومسوداتهم بنسخها الخاصة.')),
      actions: <Widget>[
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text(copy.text('Cancel', 'إلغاء'))),
        TextButton(onPressed: () => Navigator.pop(context, true), child: Text(copy.text('Delete', 'حذف'))),
      ])) ?? false;
    if (!confirmed || !mounted) return;
    try {
      await api.deleteNutritionTemplate(template['template_id'] as String);
      if (mounted) await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(appBar: AppBar(title: Text(copy.text('Nutrition templates', 'قوالب خطط التغذية'))),
        body: _loading ? const Center(child: CircularProgressIndicator()) : ListView(padding: const EdgeInsets.all(16),
          children: <Widget>[
            if (_error != null) ...<Widget>[
              Text(copy.arabic ? 'تعذر تحميل القوالب أو حفظ التغيير.' : _error!),
              TextButton(onPressed: _load, child: Text(copy.text('Retry', 'إعادة المحاولة'))),
            ],
            if (_templates.isEmpty && _error == null) Text(copy.text(
              'Save a Player’s draft or current Nutrition plan as a template to reuse it here.',
              'احفظ مسودة لاعب أو خطة تغذيته الحالية كقالب لإعادة استخدامها هنا.')),
            for (final Map<String, dynamic> template in _templates) Card(child: ListTile(
              title: Text(template['name'] as String), subtitle: Text(template['description'] as String? ?? ''),
              onTap: () {
                if (widget.selectForDraft) {
                  Navigator.pop(context, template['template_id'] as String);
                } else {
                  _edit(template['template_id'] as String);
                }
              },
              trailing: widget.selectForDraft ? const Icon(Icons.chevron_right) : IconButton(
                tooltip: copy.text('Delete template', 'حذف القالب'), icon: const Icon(Icons.delete_outline),
                onPressed: () => _delete(template)),
            )),
          ])));
  }
}
