import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';
import '../theme/myos_theme.dart';

enum MyosButtonVariant { primary, secondary, tertiary }

/// MYOS action button.
///
/// Primary is a filled blue CTA; secondary is outlined; tertiary is a quiet
/// text action. All variants keep a >=48dp target, show a pressed state, and
/// swap their label for a spinner while [loading]. [destructive] paints a
/// primary button in the danger colour (account deletion, discards).
class MyosButton extends StatelessWidget {
  const MyosButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = MyosButtonVariant.primary,
    this.icon,
    this.loading = false,
    this.expand = true,
    this.destructive = false,
    this.semanticsLabel,
  });

  final String label;
  final VoidCallback? onPressed;
  final MyosButtonVariant variant;
  final IconData? icon;
  final bool loading;
  final bool expand;
  final bool destructive;
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final bool enabled = onPressed != null && !loading;
    final MyosThemeExtension c = MyosTheme.of(context);
    final Widget child = loading
        ? SizedBox(
            height: 18,
            width: 18,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: variant == MyosButtonVariant.primary
                  ? (destructive ? c.onDanger : c.onAccent)
                  : c.accent,
            ),
          )
        : _content(context);

    final Widget button = switch (variant) {
      MyosButtonVariant.primary => FilledButton(
          onPressed: enabled ? onPressed : null,
          style: destructive
              ? FilledButton.styleFrom(
                  backgroundColor: c.danger,
                  foregroundColor: c.onDanger,
                )
              : null,
          child: child,
        ),
      MyosButtonVariant.secondary => OutlinedButton(
          onPressed: enabled ? onPressed : null,
          child: child,
        ),
      MyosButtonVariant.tertiary => TextButton(
          onPressed: enabled ? onPressed : null,
          child: child,
        ),
    };

    final Widget wrapped = semanticsLabel == null
        ? button
        : Semantics(label: semanticsLabel, button: true, child: button);

    if (!expand) {
      return wrapped;
    }
    return SizedBox(width: double.infinity, child: wrapped);
  }

  Widget _content(BuildContext context) {
    if (icon == null) {
      return Text(label);
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: <Widget>[
        Icon(icon, size: 18),
        const SizedBox(width: MyosSpacing.xs),
        Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
      ],
    );
  }
}
