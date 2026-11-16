import 'package:flutter/material.dart';

import '../../core/display_language/nutrition_draft_copy.dart';

Future<Map<String, dynamic>?> nutritionTemplateSaveDialog(BuildContext context, NutritionDraftCopy copy) =>
  showDialog<Map<String, dynamic>>(context: context,
    builder: (_) => _SaveDialog(copy: copy));

class _SaveDialog extends StatefulWidget {
  const _SaveDialog({required this.copy});
  final NutritionDraftCopy copy;
  @override
  State<_SaveDialog> createState() => _SaveDialogState();
}

class _SaveDialogState extends State<_SaveDialog> {
  final TextEditingController _name = TextEditingController();
  final TextEditingController _description = TextEditingController();
  bool _includeTargets = false;

  @override
  void dispose() { _name.dispose(); _description.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final NutritionDraftCopy copy = widget.copy;
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: AlertDialog(title: Text(copy.text('Save Nutrition template', 'حفظ قالب خطة تغذية')),
        content: SizedBox(width: 420, child: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            TextField(key: const Key('nutrition_template_name'), controller: _name, maxLength: 120,
              decoration: InputDecoration(labelText: copy.text('Name', 'الاسم')),
              onChanged: (_) => setState(() {})),
            TextField(controller: _description, maxLength: 2000, maxLines: 3,
              decoration: InputDecoration(labelText: copy.text('Description (optional)', 'الوصف (اختياري)'))),
            SwitchListTile(contentPadding: EdgeInsets.zero, value: _includeTargets,
              title: Text(copy.text('Include targets', 'تضمين الأهداف')),
              onChanged: (bool enabled) => setState(() => _includeTargets = enabled)),
            Text(copy.text('Without targets, portions are fitted to each Player’s targets when applied.',
              'بدون أهداف، تُعدّل الكميات حسب أهداف كل لاعب عند تطبيق القالب.')),
          ]))),
        actions: <Widget>[
          TextButton(onPressed: () => Navigator.pop(context), child: Text(copy.text('Cancel', 'إلغاء'))),
          FilledButton(key: const Key('confirm_save_nutrition_template'),
            onPressed: _name.text.trim().isEmpty ? null : () => Navigator.pop(context, <String, dynamic>{
              'name': _name.text.trim(), 'description': _description.text.trim(), 'include_targets': _includeTargets,
            }), child: Text(copy.text('Save template', 'حفظ القالب'))),
        ]));
  }
}
