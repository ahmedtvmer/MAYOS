import 'package:flutter/material.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';

class FocusExtraTag extends StatelessWidget {
  const FocusExtraTag({super.key, required this.extra});

  final Map<String, dynamic> extra;

  @override
  Widget build(BuildContext context) {
    final copy = displayCopyOf(context);
    final String label = copy.focusExtraTag(
      extra['muscle'] as String, extra['kind'] as String,
    );
    final Map<String, dynamic> reasons = extra['reason'] as Map<String, dynamic>;
    final String reason = reasons[copy.languageCode] as String? ?? reasons['en'] as String;
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: ActionChip(
        key: const Key('focus_extra_tag'),
        label: Text(label, style: MayosTypography.of(context).caption),
        onPressed: () => showDialog<void>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            content: Text(reason, key: const Key('focus_extra_reason')),
            actions: <Widget>[
              TextButton(onPressed: () => Navigator.of(context).pop(),
                  child: Text(MaterialLocalizations.of(context).closeButtonLabel)),
            ],
          ),
        ),
        side: BorderSide(color: MayosTheme.of(context).textMuted),
        visualDensity: VisualDensity.compact,
      ),
    );
  }
}
